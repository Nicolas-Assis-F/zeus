"""Medida do turno: onde o tempo foi, sem guardar o que foi dito.

Um turno atravessa fila, escuta, contexto, uma ou mais rodadas do modelo,
ferramentas e voz. Sem medir cada parte, "o Zeus está lento" vira palpite, e
a próxima otimização escolhida é a que parece melhor, não a que é.

Três regras deste módulo:

- **Relógio monotônico** para toda duração local. Hora de parede só entra como
  carimbo do registro, nunca numa subtração.
- **Ausente é `null`**, nunca zero. Quando o provedor não informa uma contagem,
  o campo fica vazio e `ausentes` diz por quê.
- **Nenhum conteúdo.** Nem texto de Nicolas, nem resposta, nem argumento de
  ferramenta, nem chave de fato. Só contagens, tamanhos, nomes de etapa e de
  ferramenta, e durações. O arquivo de medidas não pode virar uma segunda cópia
  da memória.
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSAO = 1

# Etapas que a interface pode mostrar na faixa "Agora". São nomes de contrato:
# a HUD traduz para texto, o núcleo só publica o que de fato está fazendo.
ETAPAS = (
    "em_fila", "transcrevendo", "montando_contexto", "consultando_modelo",
    "escrevendo", "executando_ferramenta", "sintetizando_voz",
    "concluida", "falhou", "interrompida",
)

# Campos do servidor que valem a pena comparar entre versões. As durações do
# Ollama chegam em nanossegundos; aqui viram milissegundos.
CAMPOS_DO_SERVIDOR = ("load_ms", "prompt_eval_count", "prompt_eval_ms",
                      "eval_count", "eval_ms", "total_ms")


def _ms(inicio, fim):
    if inicio is None or fim is None:
        return None
    return round((fim - inicio) * 1000, 1)


def estatisticas_do_ollama(pacote: dict) -> dict:
    """Converte o pacote final do Ollama para o contrato da medida.

    O que o servidor não mandou continua `None`: um zero aqui diria que a
    leitura do prompt foi instantânea, e isso é exatamente a hipótese que a
    medição existe para testar."""
    def nano(chave):
        valor = pacote.get(chave)
        return round(valor / 1e6, 1) if isinstance(valor, (int, float)) else None

    def inteiro(chave):
        valor = pacote.get(chave)
        return int(valor) if isinstance(valor, (int, float)) else None

    return {
        "load_ms": nano("load_duration"),
        "prompt_eval_count": inteiro("prompt_eval_count"),
        "prompt_eval_ms": nano("prompt_eval_duration"),
        "eval_count": inteiro("eval_count"),
        "eval_ms": nano("eval_duration"),
        "total_ms": nano("total_duration"),
    }


def estatisticas_openai(dados: dict) -> dict:
    """OpenRouter informa contagens em `usage`, e não informa durações."""
    uso = dados.get("usage") or {}

    def inteiro(chave):
        valor = uso.get(chave)
        return int(valor) if isinstance(valor, (int, float)) else None

    return {"load_ms": None, "prompt_eval_count": inteiro("prompt_tokens"),
            "prompt_eval_ms": None, "eval_count": inteiro("completion_tokens"),
            "eval_ms": None, "total_ms": None}


class Rodada:
    """Uma chamada ao modelo dentro de um turno."""

    def __init__(self, numero: int, ofertadas: int, relogio):
        self.numero = numero
        self.ofertadas = ofertadas
        self._relogio = relogio
        self.inicio = relogio()
        self.fim = None
        self.primeiro_pedaco = None
        self.pedacos = 0
        self.chamadas = []           # nomes de ferramenta pedidos pelo modelo
        self.servidor = []           # uma entrada por chamada ao provedor
        self.erro = None

    def pedaco(self):
        if self.primeiro_pedaco is None:
            self.primeiro_pedaco = self._relogio()
        self.pedacos += 1

    def concluir(self, resposta=None, erro=None):
        self.fim = self._relogio()
        if erro is not None:
            self.erro = type(erro).__name__
        if resposta is not None:
            self.chamadas = [c.get("nome", "") for c in (resposta.chamadas or [])]
            for medida in getattr(resposta, "medidas", None) or []:
                self.servidor.append({"provedor": medida.get("provedor"),
                                      "fluxo": bool(medida.get("fluxo")),
                                      **{c: medida.get(c) for c in CAMPOS_DO_SERVIDOR}})

    def como_dict(self, origem):
        return {
            "numero": self.numero,
            "ferramentas_ofertadas": self.ofertadas,
            "inicio_ms": _ms(origem, self.inicio),
            "duracao_ms": _ms(self.inicio, self.fim),
            "primeiro_pedaco_ms": _ms(self.inicio, self.primeiro_pedaco),
            "pedacos": self.pedacos,
            "chamadas": list(self.chamadas),
            "servidor": list(self.servidor),
            "erro": self.erro,
        }


class Medida:
    """Tudo o que se sabe do tempo de um turno.

    `ao_mudar(etapa, detalhe, decorrido_ms)` é chamado a cada troca de etapa:
    é assim que a faixa "Agora" da interface mostra a etapa real, e não um
    "pensando" genérico."""

    def __init__(self, canal: str = "cli", origem: str = "texto", geracao=None,
                 turno: str = None, recebido_em: float = None, relogio=None,
                 ao_mudar=None):
        self._relogio = relogio or time.monotonic
        self.turno = turno or uuid.uuid4().hex
        self.canal = canal
        self.origem = origem
        self.geracao = geracao
        self.recebido_em = recebido_em
        self.inicio = self._relogio()
        self.fim = None
        self.ao_mudar = ao_mudar
        self.etapa_atual = None
        self._inicio_da_etapa = None
        self.marcas = {}
        self.rodadas = []
        self.ferramentas = []
        self.contexto = {}
        self.escuta = None
        self.resultado = None
        self.erro = None
        self.ausentes = {}

    # ---------------------------------------------------------------- etapas
    def etapa(self, nome: str, **detalhe):
        agora = self._relogio()
        self.etapa_atual = nome
        self._inicio_da_etapa = agora
        if self.ao_mudar is not None:
            try:
                self.ao_mudar(nome, detalhe, _ms(self.recebido_em or self.inicio, agora))
            except Exception:
                pass  # a tela nunca derruba o turno

    def marcar(self, nome: str):
        """Primeira ocorrência vale: repetir a marca não a move."""
        self.marcas.setdefault(nome, self._relogio())

    def nova_rodada(self, ofertadas: int) -> Rodada:
        rodada = Rodada(len(self.rodadas) + 1, ofertadas, self._relogio)
        self.rodadas.append(rodada)
        return rodada

    def ferramenta(self, nome: str, inicio: float, resultado: str, efeito: str):
        self.ferramentas.append({"nome": nome, "duracao_ms": _ms(inicio, self._relogio()),
                                 "resultado": resultado, "efeito": efeito})

    def concluir(self, resultado: str, erro=None):
        if self.fim is None:
            self.fim = self._relogio()
            self.resultado = resultado
            if erro is not None:
                self.erro = erro if isinstance(erro, str) else type(erro).__name__
            self.etapa(resultado if resultado in ETAPAS else "concluida")

    def agora_ms(self):
        return _ms(self.recebido_em or self.inicio, self._relogio())

    # ---------------------------------------------------------------- saída
    def como_linha(self) -> dict:
        origem = self.inicio
        final = None
        if self.rodadas and self.rodadas[-1].primeiro_pedaco is not None \
                and not self.rodadas[-1].chamadas:
            final = self.rodadas[-1].primeiro_pedaco
        ausentes = dict(self.ausentes)
        if self.recebido_em is None:
            ausentes.setdefault("espera_fila_ms", "entrada sem carimbo de chegada")
        if final is None:
            ausentes.setdefault("primeiro_fragmento_final_ms",
                                "resposta final sem fluxo ou sem texto")
        linha = {
            "tipo": "turno",
            "v": VERSAO,
            "turno": self.turno,
            "geracao": self.geracao,
            "canal": self.canal,
            "origem": self.origem,
            "registrado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "espera_fila_ms": _ms(self.recebido_em, self.inicio),
            "contexto_ms": _ms(self.marcas.get("contexto_inicio"),
                               self.marcas.get("contexto_pronto")),
            "primeiro_pedaco_ms": _ms(origem, min((r.primeiro_pedaco for r in self.rodadas
                                                   if r.primeiro_pedaco is not None),
                                                  default=None)),
            "primeiro_fragmento_final_ms": _ms(origem, final),
            "texto_final_ms": _ms(origem, self.marcas.get("texto_final")),
            "total_ms": _ms(origem, self.fim),
            "rodadas": [r.como_dict(origem) for r in self.rodadas],
            "ferramentas": list(self.ferramentas),
            "contexto": dict(self.contexto),
            "escuta": self.escuta,
            "resultado": self.resultado,
            "erro": self.erro,
            "ausentes": ausentes,
        }
        return linha


class Telemetria:
    """Guarda as medidas: em memória sempre, em disco só quando ligado.

    A memória alimenta o Diagnóstico da interface. O arquivo é opcional
    (`telemetria_arquivo`) e serve para comparar versões com `./zeus medidas`.
    Falha de disco nunca atrapalha a conversa: conta e segue."""

    def __init__(self, diretorio=None, gravar: bool = False, dias: int = 14,
                 recentes: int = 30):
        self.diretorio = Path(diretorio) / "medidas" if diretorio else None
        self.gravar = bool(gravar and self.diretorio)
        self.dias = max(1, int(dias))
        self._recentes = []
        self._limite = recentes
        self._trava = threading.Lock()
        self.falhas = 0
        if self.gravar:
            self.diretorio.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._podar()

    def registrar(self, linha: dict):
        with self._trava:
            self._recentes.append(linha)
            del self._recentes[:-self._limite]
            if not self.gravar:
                return
            try:
                arquivo = self.diretorio / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
                novo = not arquivo.exists()
                with open(arquivo, "a", encoding="utf-8") as saida:
                    saida.write(json.dumps(linha, ensure_ascii=False) + "\n")
                if novo:
                    os.chmod(arquivo, 0o600)
            except OSError:
                self.falhas += 1

    def recentes(self, tipo: str = "turno", limite: int = 10):
        with self._trava:
            linhas = [l for l in self._recentes if l.get("tipo") == tipo]
        return linhas[-limite:]

    def _podar(self):
        corte = datetime.now(timezone.utc).date() - timedelta(days=self.dias)
        for arquivo in self.diretorio.glob("*.jsonl"):
            try:
                if datetime.strptime(arquivo.stem, "%Y-%m-%d").date() < corte:
                    arquivo.unlink()
            except (ValueError, OSError):
                continue


# ------------------------------------------------------------------ resumo
def percentil(valores, fracao):
    ordenados = sorted(v for v in valores if v is not None)
    if not ordenados:
        return None
    posicao = min(len(ordenados) - 1, max(0, round(fracao * (len(ordenados) - 1))))
    return ordenados[posicao]


def ler_medidas(pasta: Path):
    linhas = []
    for arquivo in sorted(Path(pasta).glob("*.jsonl")):
        with open(arquivo, encoding="utf-8") as entrada:
            for bruta in entrada:
                try:
                    linhas.append(json.loads(bruta))
                except json.JSONDecodeError:
                    continue
    return linhas


def resumir(linhas) -> dict:
    """p50/p95 por campo, com o tamanho da amostra sempre declarado."""
    turnos = [l for l in linhas if l.get("tipo") == "turno"]
    campos = {
        "espera_fila_ms": [t.get("espera_fila_ms") for t in turnos],
        "contexto_ms": [t.get("contexto_ms") for t in turnos],
        "primeiro_pedaco_ms": [t.get("primeiro_pedaco_ms") for t in turnos],
        "primeiro_fragmento_final_ms": [t.get("primeiro_fragmento_final_ms") for t in turnos],
        "total_ms": [t.get("total_ms") for t in turnos],
        "rodadas_por_turno": [len(t.get("rodadas") or []) for t in turnos],
    }
    servidor = [s for t in turnos for r in t.get("rodadas") or [] for s in r.get("servidor") or []]
    for campo in CAMPOS_DO_SERVIDOR:
        campos["servidor." + campo] = [s.get(campo) for s in servidor]
    voz = [l for l in linhas if l.get("tipo") == "voz"]
    campos["voz.sintese_ms"] = [v.get("sintese_ms") for v in voz]
    resumo = {}
    for nome, valores in campos.items():
        presentes = [v for v in valores if v is not None]
        resumo[nome] = {"n": len(presentes), "ausentes": len(valores) - len(presentes),
                        "p50": percentil(presentes, 0.5), "p95": percentil(presentes, 0.95)}
    resultados = {}
    for t in turnos:
        resultados[t.get("resultado") or "desconhecido"] = resultados.get(
            t.get("resultado") or "desconhecido", 0) + 1
    return {"turnos": len(turnos), "resultados": resultados, "campos": resumo}
