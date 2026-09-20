"""Avaliação cega de persona.

Ajustar personalidade no escuro não é método. A única evidência sobre tom, hoje,
é a impressão de Nicolas depois de uma conversa — foi assim que apareceu o "não
senti ele vivo, parece um robô". Impressão vale, mas comparar variantes exige
que ninguém saiba, na hora de julgar, qual variante gerou qual resposta.

Este módulo roda N variantes de `persona.md` sobre as mesmas jornadas
conversacionais, com o mesmo modelo, e monta uma folha cega: as respostas de
cada variante aparecem sob rótulos opacos, embaralhados a cada jornada, sem nada
que ligue rótulo a arquivo. Nicolas julga por critério; só depois vem a
revelação, com o agregado por variante. O resultado é gravado junto da versão
da persona, para comparar ao longo do tempo.

Uma honestidade fica dita desde já, como na avaliação por jornadas: com dublê,
as respostas não são do modelo real, e nenhum número aqui vale como evidência de
tom. O que fecha a comparação é a rodada `--real` no equipamento.
"""

import hashlib
import json
import random
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from .canais import CanalMemoria
from .ferramentas import Ferramentas
from .llm import Resposta
from .nucleo import Zeus
from .persona import Persona
from .store import Store

# Os seis critérios são os do plano mestre. A folha cega pede nota em cada um.
CRITERIOS = ["competência serena", "humor", "lealdade",
             "familiaridade", "iniciativa", "companhia"]
JORNADAS_PADRAO = Path("avaliacao/persona_jornadas.json")


class ModeloDeEnsaio:
    """Dublê para ensaiar a máquina sem modelo. Ignora a persona de propósito:
    serve para provar o fluxo, nunca o tom. Toda saída sai marcada assim."""

    modelo = "dublê-de-ensaio"

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0):
        return Resposta("(resposta de ensaio; rode com --real para medir tom)",
                        [], self.modelo)

    def mensagem_do_assistente(self, resposta):
        return {"role": "assistant", "content": resposta.texto}

    def mensagem_de_ferramenta(self, chamada, conteudo):
        return {"role": "tool", "name": chamada["nome"], "content": conteudo}


def _rotulo(indice: int) -> str:
    if indice < 26:
        return chr(ord("A") + indice)
    return f"v{indice + 1}"


def _apelido(caminho) -> str:
    return re.sub(r"[^a-z0-9]+", "-", Path(caminho).name.lower()).strip("-") or "persona"


def versao_da_persona(caminho) -> str:
    """Identidade estável de uma variante: nome do arquivo e marca do conteúdo.
    Muda quando o texto muda, para o histórico comparar a coisa certa."""
    persona = Persona.carregar(caminho)
    marca = hashlib.sha1(persona.texto.encode("utf-8")).hexdigest()[:8]
    return f"{Path(caminho).name}@{marca}"


class AvaliacaoCegaDePersona:
    def __init__(self, config, diretorio, variantes, provedor=None,
                 origem="simulada", criterios=None, embaralhar=None):
        self.config = config
        self.diretorio = Path(diretorio)
        self.variantes = list(variantes)
        self.provedor = provedor or ModeloDeEnsaio()
        self.origem = origem
        self.criterios = list(criterios or CRITERIOS)
        # Embaralhar é injetável para o teste poder fixar a ordem.
        self.embaralhar = embaralhar or random.shuffle

    def _rodar_variante(self, caminho, jornada):
        persona = Persona.carregar(caminho)
        pasta = self.diretorio / _apelido(caminho) / str(jornada.get("id", "jornada"))
        pasta.mkdir(parents=True, exist_ok=True)
        store = Store(pasta)
        zeus = Zeus(store, self.provedor, persona, Ferramentas(store),
                    self.config, CanalMemoria())
        falas = []
        try:
            for turno in jornada.get("turnos", []):
                inicio = time.perf_counter()
                resposta = zeus.conversar(turno, canal="persona-cega")
                falas.append({"nicolas": turno, "zeus": resposta,
                              "segundos": round(time.perf_counter() - inicio, 3)})
        finally:
            store.close()
        return falas

    def gerar(self, jornadas) -> dict:
        """Roda todas as variantes e devolve a rodada, com o gabarito selado.
        A folha que vai para Nicolas sai de `folha_cega`, sem o gabarito."""
        rodada = {
            "em": datetime.now(timezone.utc).isoformat(),
            "modelo": getattr(self.provedor, "modelo", "dublê"),
            "origem": self.origem,
            "criterios": self.criterios,
            "variantes": [versao_da_persona(c) for c in self.variantes],
            "itens": [],
        }
        for jornada in jornadas.get("jornadas", []):
            transcricoes = [(c, self._rodar_variante(c, jornada)) for c in self.variantes]
            # Rótulos opacos, embaralhados nesta jornada: nem a ordem denuncia a
            # variante. O gabarito fica no item, mas some na folha cega.
            self.embaralhar(transcricoes)
            respostas, gabarito = [], {}
            for indice, (caminho, falas) in enumerate(transcricoes):
                rotulo = _rotulo(indice)
                gabarito[rotulo] = versao_da_persona(caminho)
                respostas.append({"rotulo": rotulo, "falas": falas})
            rodada["itens"].append({
                "jornada": jornada.get("id", "sem-id"),
                "titulo": jornada.get("titulo", ""),
                "dimensoes": jornada.get("dimensoes", []),
                "turnos": jornada.get("turnos", []),
                "respostas": respostas,
                "_gabarito": gabarito,
            })
        return rodada


def folha_cega(rodada: dict) -> dict:
    """O que Nicolas vê para julgar: rótulos e respostas, sem o gabarito. A
    revelação só acontece depois, em `revelar`."""
    return {
        "em": rodada["em"],
        "modelo": rodada["modelo"],
        "origem": rodada["origem"],
        "criterios": rodada["criterios"],
        "como_julgar": ("Dê nota 0 a 5 por critério a cada rótulo. Não há como "
                        "saber qual variante é qual — é de propósito. Revele só "
                        "depois de julgar tudo."),
        "itens": [{
            "jornada": item["jornada"],
            "titulo": item["titulo"],
            "dimensoes": item.get("dimensoes", []),
            "turnos": item["turnos"],
            "respostas": [{"rotulo": r["rotulo"], "falas": r["falas"]}
                          for r in item["respostas"]],
        } for item in rodada["itens"]],
    }


def revelar(rodada: dict, julgamento: dict) -> dict:
    """Depois do julgamento, liga cada rótulo à variante e agrega por variante.

    julgamento: {jornada_id: {rotulo: {criterio: nota}}}."""
    por_variante = {}
    for item in rodada["itens"]:
        notas = julgamento.get(item["jornada"], {})
        for resposta in item["respostas"]:
            variante = item["_gabarito"][resposta["rotulo"]]
            alvo = por_variante.setdefault(variante, {c: [] for c in rodada["criterios"]})
            for criterio, nota in (notas.get(resposta["rotulo"]) or {}).items():
                if criterio in alvo:
                    alvo[criterio].append(float(nota))
    agregado = {}
    for variante, criterios in por_variante.items():
        medias = {c: round(statistics.mean(v), 2) for c, v in criterios.items() if v}
        todas = [n for v in criterios.values() for n in v]
        agregado[variante] = {
            "por_criterio": medias,
            "media_geral": round(statistics.mean(todas), 2) if todas else None,
            "respostas_julgadas": len(todas),
        }
    return {
        "em": rodada["em"],
        "modelo": rodada["modelo"],
        "origem": rodada["origem"],
        "criterios": rodada["criterios"],
        "por_variante": agregado,
    }


def gravar_historico(diretorio, revelacao: dict) -> Path:
    """Grava a revelação junto da versão da persona, uma linha por rodada, para
    comparar ao longo do tempo."""
    pasta = Path(diretorio)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "historico.jsonl"
    with arquivo.open("a", encoding="utf-8") as saida:
        saida.write(json.dumps(revelacao, ensure_ascii=False) + "\n")
    return arquivo


def carregar_jornadas_de_persona(caminho=None) -> dict:
    alvo = Path(caminho or JORNADAS_PADRAO)
    if not alvo.exists():
        raiz = Path(__file__).resolve().parents[2]
        alvo = raiz / (caminho or JORNADAS_PADRAO)
    return json.loads(alvo.read_text(encoding="utf-8"))


def em_texto_revelacao(revelacao: dict) -> str:
    origem = ("dublê — não vale como evidência de tom; rode --real no X99"
              if revelacao["origem"] == "simulada"
              else f"modelo real {revelacao['modelo']} no equipamento desta execução")
    linhas = ["Avaliação cega de persona",
              f"Origem: {origem}", f"Em: {revelacao['em']}", ""]
    ordenadas = sorted(revelacao["por_variante"].items(),
                       key=lambda par: (par[1]["media_geral"] is not None,
                                        par[1]["media_geral"] or 0),
                       reverse=True)
    for variante, dados in ordenadas:
        geral = dados["media_geral"]
        linhas.append(f"{variante}: média geral "
                      + (f"{geral}" if geral is not None else "sem julgamento")
                      + f" ({dados['respostas_julgadas']} resposta(s) julgada(s))")
        for criterio in revelacao["criterios"]:
            if criterio in dados["por_criterio"]:
                linhas.append(f"        {criterio}: {dados['por_criterio'][criterio]}")
    return "\n".join(linhas)
