"""Provedores de modelo, com verificação obrigatória do modelo servido.

Regra dura do escopo: já aconteceu de um servidor entregar uma variante
diferente da pedida (vision ou coder no lugar do instruct), quebrando o uso de
ferramentas em silêncio. Por isso o modelo é verificado antes da primeira
conversa e conferido de novo em cada resposta. Divergência levanta erro em vez
de virar comportamento estranho sem explicação.

O transporte é injetável para que o teste não precise de rede nem de servidor.
"""

import json
import urllib.error
import urllib.request

TEMPO_LIMITE = 120


class ErroDeModelo(RuntimeError):
    pass


def transporte_http(metodo: str, url: str, corpo=None, cabecalhos=None, timeout=TEMPO_LIMITE):
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    pedido = urllib.request.Request(url, data=dados, method=metodo)
    pedido.add_header("Content-Type", "application/json")
    for nome, valor in (cabecalhos or {}).items():
        pedido.add_header(nome, valor)
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            return json.loads(resposta.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", "replace")[:300]
        raise ErroDeModelo(f"{metodo} {url} respondeu {erro.code}: {detalhe}")
    except urllib.error.URLError as erro:
        raise ErroDeModelo(f"Não consegui falar com {url}: {erro.reason}")


class Resposta:
    def __init__(self, texto: str, chamadas=None, modelo: str = ""):
        self.texto = texto or ""
        self.chamadas = chamadas or []
        self.modelo = modelo

    def __repr__(self):
        return f"Resposta(modelo={self.modelo!r}, chamadas={len(self.chamadas)})"


def _mesmo_modelo(pedido: str, servido: str) -> bool:
    if not servido:
        return False
    normaliza = lambda nome: nome.split(":")[0] if nome.endswith(":latest") else nome
    return normaliza(pedido) == normaliza(servido)


class ProvedorOllama:
    nome = "ollama"

    def __init__(self, url: str, modelo: str, transporte=None, timeout=TEMPO_LIMITE,
                 keep_alive: str = "30m"):
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.transporte = transporte or transporte_http
        self.timeout = timeout
        # Recarregar 4,9 GB a cada mensagem custa mais que a resposta inteira.
        self.keep_alive = keep_alive

    def verificar(self) -> str:
        dados = self.transporte("GET", f"{self.url}/api/tags", None, None, self.timeout)
        disponiveis = [m.get("name", "") for m in dados.get("models", [])]
        if not any(_mesmo_modelo(self.modelo, nome) for nome in disponiveis):
            raise ErroDeModelo(
                f"O modelo {self.modelo} não está no Ollama. Disponíveis: "
                + (", ".join(disponiveis) if disponiveis else "nenhum")
                + f". Baixe com: ollama pull {self.modelo}"
            )
        return self.modelo

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0) -> Resposta:
        corpo = {
            "model": self.modelo,
            "messages": mensagens,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperatura},
        }
        if ferramentas:
            corpo["tools"] = ferramentas
        dados = self.transporte("POST", f"{self.url}/api/chat", corpo, None, self.timeout)
        servido = dados.get("model", "")
        if not _mesmo_modelo(self.modelo, servido):
            raise ErroDeModelo(
                f"Pedi {self.modelo} e o servidor respondeu como {servido or 'desconhecido'}."
            )
        mensagem = dados.get("message", {}) or {}
        chamadas = []
        for indice, chamada in enumerate(mensagem.get("tool_calls") or []):
            funcao = chamada.get("function", {}) or {}
            argumentos = funcao.get("arguments", {})
            if isinstance(argumentos, str):
                try:
                    argumentos = json.loads(argumentos or "{}")
                except json.JSONDecodeError:
                    argumentos = {}
            chamadas.append({
                "id": chamada.get("id") or f"chamada-{indice}",
                "nome": funcao.get("name", ""),
                "argumentos": argumentos if isinstance(argumentos, dict) else {},
            })
        return Resposta(mensagem.get("content", ""), chamadas, servido)

    def mensagem_do_assistente(self, resposta: Resposta) -> dict:
        mensagem = {"role": "assistant", "content": resposta.texto}
        if resposta.chamadas:
            mensagem["tool_calls"] = [
                {"function": {"name": c["nome"], "arguments": c["argumentos"]}}
                for c in resposta.chamadas
            ]
        return mensagem

    def mensagem_de_ferramenta(self, chamada, conteudo: str) -> dict:
        return {"role": "tool", "content": conteudo, "name": chamada["nome"]}


class ProvedorOpenRouter:
    nome = "openrouter"

    def __init__(self, url: str, modelo: str, chave: str, transporte=None, timeout=TEMPO_LIMITE):
        if not chave:
            raise ErroDeModelo("OpenRouter exige uma chave configurada fora do Git.")
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.chave = chave
        self.transporte = transporte or transporte_http
        self.timeout = timeout

    def _cabecalhos(self):
        return {"Authorization": f"Bearer {self.chave}"}

    def verificar(self) -> str:
        dados = self.transporte("GET", f"{self.url}/models", None, self._cabecalhos(), self.timeout)
        disponiveis = [m.get("id", "") for m in dados.get("data", [])]
        if disponiveis and self.modelo not in disponiveis:
            raise ErroDeModelo(f"O modelo {self.modelo} não aparece no catálogo do OpenRouter.")
        return self.modelo

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0) -> Resposta:
        corpo = {"model": self.modelo, "messages": mensagens, "temperature": temperatura}
        if ferramentas:
            corpo["tools"] = ferramentas
        dados = self.transporte("POST", f"{self.url}/chat/completions", corpo,
                                self._cabecalhos(), self.timeout)
        servido = dados.get("model", "")
        if not _mesmo_modelo(self.modelo, servido):
            raise ErroDeModelo(
                f"Pedi {self.modelo} e a resposta veio marcada como {servido or 'desconhecido'}."
            )
        escolhas = dados.get("choices") or [{}]
        mensagem = escolhas[0].get("message", {}) or {}
        chamadas = []
        for indice, chamada in enumerate(mensagem.get("tool_calls") or []):
            funcao = chamada.get("function", {}) or {}
            try:
                argumentos = json.loads(funcao.get("arguments") or "{}")
            except json.JSONDecodeError:
                argumentos = {}
            chamadas.append({
                "id": chamada.get("id") or f"chamada-{indice}",
                "nome": funcao.get("name", ""),
                "argumentos": argumentos if isinstance(argumentos, dict) else {},
            })
        return Resposta(mensagem.get("content", ""), chamadas, servido)

    def mensagem_do_assistente(self, resposta: Resposta) -> dict:
        mensagem = {"role": "assistant", "content": resposta.texto}
        if resposta.chamadas:
            mensagem["tool_calls"] = [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["nome"],
                              "arguments": json.dumps(c["argumentos"], ensure_ascii=False)}}
                for c in resposta.chamadas
            ]
        return mensagem

    def mensagem_de_ferramenta(self, chamada, conteudo: str) -> dict:
        return {"role": "tool", "tool_call_id": chamada["id"], "content": conteudo}


def criar_provedor(config, transporte=None):
    if config.provedor == "ollama":
        return ProvedorOllama(config.ollama_url, config.modelo, transporte,
                              keep_alive=config.keep_alive)
    if config.provedor == "openrouter":
        return ProvedorOpenRouter(config.openrouter_url, config.modelo,
                                  config.openrouter_chave, transporte)
    raise ErroDeModelo(f"Provedor desconhecido: {config.provedor}")
