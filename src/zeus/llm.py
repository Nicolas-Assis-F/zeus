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


def transporte_fluxo(metodo: str, url: str, corpo=None, cabecalhos=None, timeout=TEMPO_LIMITE):
    """Percorre uma resposta NDJSON conforme ela chega, sem esperar o fim.

    É o que permite a primeira palavra aparecer em segundos em vez de a
    resposta inteira aparecer de uma vez. O plano mestre pede resposta inicial
    útil em até dois segundos; a 9,8 tokens por segundo, isso só existe em
    fluxo."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    pedido = urllib.request.Request(url, data=dados, method=metodo)
    pedido.add_header("Content-Type", "application/json")
    for nome, valor in (cabecalhos or {}).items():
        pedido.add_header(nome, valor)
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            for linha in resposta:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    yield json.loads(linha.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", "replace")[:300]
        raise ErroDeModelo(f"{metodo} {url} respondeu {erro.code}: {detalhe}")
    except urllib.error.URLError as erro:
        raise ErroDeModelo(f"Não consegui falar com {url}: {erro.reason}")


def transporte_sse(metodo: str, url: str, corpo=None, cabecalhos=None, timeout=TEMPO_LIMITE):
    """Fluxo no formato SSE, usado pelos serviços compatíveis com OpenAI."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    pedido = urllib.request.Request(url, data=dados, method=metodo)
    pedido.add_header("Content-Type", "application/json")
    pedido.add_header("Accept", "text/event-stream")
    for nome, valor in (cabecalhos or {}).items():
        pedido.add_header(nome, valor)
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            for linha in resposta:
                linha = linha.strip()
                if not linha.startswith(b"data:"):
                    continue
                conteudo = linha[5:].strip()
                if conteudo == b"[DONE]":
                    return
                try:
                    yield json.loads(conteudo.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", "replace")[:300]
        raise ErroDeModelo(f"{metodo} {url} respondeu {erro.code}: {detalhe}")
    except urllib.error.URLError as erro:
        raise ErroDeModelo(f"Não consegui falar com {url}: {erro.reason}")


class Resposta:
    def __init__(self, texto: str, chamadas=None, modelo: str = "", estatisticas=None):
        self.texto = texto or ""
        self.chamadas = chamadas or []
        self.modelo = modelo
        # Números do próprio servidor: melhores que cronômetro nosso para
        # comparar modelos, porque separam leitura do prompt de geração.
        self.estatisticas = estatisticas or {}

    def __repr__(self):
        return f"Resposta(modelo={self.modelo!r}, chamadas={len(self.chamadas)})"


def _normalizar_chamadas(brutas) -> list:
    """Uma chamada de ferramenta, um formato só, venha de onde vier."""
    chamadas = []
    for indice, chamada in enumerate(brutas or []):
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
    return chamadas


def _mesmo_modelo(pedido: str, servido: str) -> bool:
    if not servido:
        return False
    normaliza = lambda nome: nome.split(":")[0] if nome.endswith(":latest") else nome
    return normaliza(pedido) == normaliza(servido)


def _modelo_do_pacote(pedido, pacote, anterior=""):
    if pacote.get("error"):
        raise ErroDeModelo("O provedor interrompeu a resposta em fluxo.")
    servido = pacote.get("model") or anterior
    if not _mesmo_modelo(pedido, servido):
        raise ErroDeModelo("O fluxo não confirmou o modelo solicitado.")
    return servido


class ProvedorOllama:
    nome = "ollama"

    def __init__(self, url: str, modelo: str, transporte=None, timeout=TEMPO_LIMITE,
                 keep_alive: str = "30m", limite_de_resposta: int = 320):
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.transporte = transporte or transporte_http
        self.timeout = timeout
        # Recarregar 4,9 GB a cada mensagem custa mais que a resposta inteira.
        self.keep_alive = keep_alive
        # A 9,8 tokens por segundo, resposta longa é espera longa. O teto corta
        # a divagação antes de ela virar um minuto de silêncio no Telegram.
        self.limite_de_resposta = limite_de_resposta
        self.transporte_de_fluxo = transporte_fluxo

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
            "options": {"temperature": temperatura,
                        "num_predict": self.limite_de_resposta},
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
        chamadas = _normalizar_chamadas(mensagem.get("tool_calls"))
        return Resposta(mensagem.get("content", ""), chamadas, servido)

    def conversar_em_fluxo(self, mensagens, ferramentas=None, temperatura=0.0,
                           ao_receber=None) -> Resposta:
        """Mesma conversa, entregue em pedaços.

        `ao_receber` é chamado a cada trecho novo. A verificação de modelo
        continua valendo: o primeiro pacote já diz quem respondeu, e divergir
        levanta erro antes de qualquer texto chegar a Nicolas."""
        corpo = {
            "model": self.modelo,
            "messages": mensagens,
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperatura,
                        "num_predict": self.limite_de_resposta},
        }
        if ferramentas:
            corpo["tools"] = ferramentas
        fluxo = self.transporte_de_fluxo("POST", f"{self.url}/api/chat", corpo, None,
                                         self.timeout)
        partes, chamadas, servido, estatisticas = [], [], "", {}
        concluido = False
        for pacote in fluxo:
            servido = _modelo_do_pacote(self.modelo, pacote, servido)
            mensagem = pacote.get("message", {}) or {}
            pedaco = mensagem.get("content", "")
            if pedaco:
                partes.append(pedaco)
                if ao_receber:
                    ao_receber(pedaco)
            chamadas.extend(_normalizar_chamadas(mensagem.get("tool_calls")))
            if pacote.get("done"):
                concluido = True
                estatisticas = {chave: pacote.get(chave) for chave in
                                ("eval_count", "eval_duration", "prompt_eval_count",
                                 "prompt_eval_duration", "load_duration")
                                if pacote.get(chave) is not None}
        if not concluido:
            raise ErroDeModelo("O fluxo terminou antes da confirmação de conclusão.")
        return Resposta("".join(partes), chamadas, servido, estatisticas)

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
        self.transporte_de_fluxo = transporte_sse
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

    def conversar_em_fluxo(self, mensagens, ferramentas=None, temperatura=0.0,
                           ao_receber=None) -> Resposta:
        corpo = {"model": self.modelo, "messages": mensagens,
                 "temperature": temperatura, "stream": True}
        if ferramentas:
            corpo["tools"] = ferramentas
        partes, servido, chamadas = [], "", {}
        concluido = False
        for pacote in self.transporte_de_fluxo("POST", f"{self.url}/chat/completions",
                                               corpo, self._cabecalhos(), self.timeout):
            servido = _modelo_do_pacote(self.modelo, pacote, servido)
            for escolha in pacote.get("choices") or []:
                if escolha.get("index", 0) != 0:
                    continue
                delta = escolha.get("delta") or {}
                pedaco = delta.get("content") or ""
                if pedaco:
                    partes.append(pedaco)
                    if ao_receber:
                        ao_receber(pedaco)
                for fragmento in delta.get("tool_calls") or []:
                    indice = fragmento.get("index", 0)
                    chamada = chamadas.setdefault(indice, {
                        "id": "", "function": {"name": "", "arguments": ""}})
                    if fragmento.get("id"):
                        chamada["id"] = fragmento["id"]
                    for campo in ("name", "arguments"):
                        chamada["function"][campo] += (fragmento.get("function") or {}).get(campo) or ""
                motivo = escolha.get("finish_reason")
                if motivo:
                    if motivo not in ("stop", "tool_calls"):
                        raise ErroDeModelo("A resposta foi interrompida pelo provedor.")
                    concluido = True
        if not concluido:
            raise ErroDeModelo("O fluxo terminou antes da confirmação de conclusão.")
        return Resposta("".join(partes), _normalizar_chamadas(
            [chamadas[i] for i in sorted(chamadas)]), servido)

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


class ProvedorHibrido:
    """Local decide e usa ferramenta; remoto conduz a conversa.

    É o "híbrido seletivo" do plano mestre, e a divisão não é arbitrária:
    roteamento e uso de ferramenta pedem obediência ao formato, que um modelo
    pequeno entrega a temperatura zero; conversa pede profundidade, que é
    exatamente o que não cabe em 4 GiB de VRAM.

    Memória, agenda e decisão continuam em casa. O que sai é o texto da
    conversa, e só quando este provedor está escolhido de propósito."""

    nome = "hibrido"

    def __init__(self, local, remoto):
        self.local = local
        self.remoto = remoto
        self.modelo = f"{local.modelo} + {remoto.modelo}"

    def verificar(self) -> str:
        return f"{self.local.verificar()} + {self.remoto.verificar()}"

    def _mensagens_remotas(self, mensagens):
        convertidas, pendentes = [], []
        for mensagem in mensagens:
            nova = dict(mensagem)
            if mensagem.get("role") == "assistant" and mensagem.get("tool_calls"):
                chamadas = _normalizar_chamadas(mensagem["tool_calls"])
                nova = self.remoto.mensagem_do_assistente(
                    Resposta(mensagem.get("content", ""), chamadas))
                pendentes = [c["id"] for c in chamadas]
            elif mensagem.get("role") == "tool" and pendentes:
                nova = {"role": "tool", "tool_call_id": pendentes.pop(0),
                        "content": mensagem.get("content", "")}
            convertidas.append(nova)
        return convertidas

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0) -> Resposta:
        if ferramentas:
            decisao = self.local.conversar(mensagens, ferramentas, 0.0)
            if decisao.chamadas:
                return decisao
        return self.remoto.conversar(self._mensagens_remotas(mensagens), None, temperatura)

    def conversar_em_fluxo(self, mensagens, ferramentas=None, temperatura=0.0,
                           ao_receber=None) -> Resposta:
        if ferramentas:
            decisao = self.local.conversar(mensagens, ferramentas, 0.0)
            if decisao.chamadas:
                return decisao
        return self.remoto.conversar_em_fluxo(
            self._mensagens_remotas(mensagens), None, temperatura, ao_receber)

    def mensagem_do_assistente(self, resposta: Resposta) -> dict:
        alvo = self.local if resposta.chamadas else self.remoto
        return alvo.mensagem_do_assistente(resposta)

    def mensagem_de_ferramenta(self, chamada, conteudo: str) -> dict:
        return self.local.mensagem_de_ferramenta(chamada, conteudo)


def criar_provedor(config, transporte=None):
    if config.provedor == "ollama":
        return ProvedorOllama(config.ollama_url, config.modelo, transporte,
                              keep_alive=config.keep_alive,
                              limite_de_resposta=config.limite_de_resposta)
    if config.provedor == "openrouter":
        return ProvedorOpenRouter(config.openrouter_url, config.modelo,
                                  config.openrouter_chave, transporte)
    if config.provedor == "hibrido":
        if not config.modelo_conversa:
            raise ErroDeModelo("O híbrido precisa de modelo_conversa configurado.")
        local = ProvedorOllama(config.ollama_url, config.modelo, transporte,
                               keep_alive=config.keep_alive,
                               limite_de_resposta=config.limite_de_resposta)
        remoto = ProvedorOpenRouter(config.openrouter_url, config.modelo_conversa,
                                    config.openrouter_chave, transporte)
        return ProvedorHibrido(local, remoto)
    raise ErroDeModelo(f"Provedor desconhecido: {config.provedor}")
