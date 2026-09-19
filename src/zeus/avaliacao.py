"""Avaliação por jornadas.

A régua deste produto é companhia útil com continuidade. Contagem de testes e
tokens por segundo não demonstram isso: um Zeus que passa em oitenta testes
unitários pode ainda cobrar duas vezes o mesmo lembrete, perder o assunto
depois de reiniciar ou responder com segurança o que não sabe.

Uma jornada é uma conversa inteira com verificações no meio. Ela é dada, não
código: vive em `avaliacao/jornadas.json` e se edita como a persona.

Dois modos, e a diferença entre eles é a honestidade do resultado:

- simulada: o modelo é um dublê roteirizado. Prova o comportamento do sistema —
  roteamento de ferramenta, entrega, deduplicação, continuidade, recusa — e não
  prova nada sobre a qualidade do modelo.
- real: fala com o modelo instalado. Prova o que o Zeus faz de verdade no X99 e
  mede latência. Só este resultado vale como evidência de hardware.

O relatório sempre diz de qual dos dois veio cada número.
"""

import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .canais import CanalMemoria
from .ferramentas import Ferramentas
from .llm import Resposta
from .nucleo import Zeus
from .persona import Persona
from .store import Store
from .tempo import interpretar

JORNADAS_PADRAO = Path("avaliacao/jornadas.json")


class RelogioDeTeste:
    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora

    def avancar_para(self, expressao):
        self.agora = interpretar(expressao, self.agora)
        return self.agora


class ModeloRoteirizado:
    """Dublê que entrega as respostas escritas na jornada, em ordem."""

    nome = "roteirizado"

    def __init__(self):
        self.modelo = "dublê-roteirizado"
        self.fila = []
        self.catalogos = []

    def enfileirar(self, roteiro):
        for passo in roteiro or []:
            chamadas = []
            if passo.get("ferramenta"):
                chamadas = [{"id": "c", "nome": passo["ferramenta"],
                             "argumentos": passo.get("argumentos", {})}]
            self.fila.append(Resposta(passo.get("texto", ""), chamadas, self.modelo))

    def verificar(self):
        return self.modelo

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0):
        self.catalogos.append(ferramentas)
        if self.fila:
            return self.fila.pop(0)
        return Resposta("Sem mais nada a dizer.", [], self.modelo)

    def mensagem_do_assistente(self, resposta):
        return {"role": "assistant", "content": resposta.texto}

    def mensagem_de_ferramenta(self, chamada, conteudo):
        return {"role": "tool", "name": chamada["nome"], "content": conteudo}


class Avaliacao:
    def __init__(self, config, diretorio, provedor=None, origem="simulada",
                 persona=None, pesquisa=None):
        self.config = config
        self.diretorio = Path(diretorio)
        self.provedor_real = provedor
        self.origem = origem
        self.persona = persona or Persona.carregar(config.persona)
        self.pesquisa = pesquisa

    # ---------------------------------------------------------------- setup
    def _montar(self, pasta, relogio, modelo):
        store = Store(pasta)
        ferramentas = Ferramentas(store, relogio, **(
            {"pesquisa": self.pesquisa} if self.pesquisa is not None else {}))
        canal = CanalMemoria()
        zeus = Zeus(store, modelo, self.persona, ferramentas, self.config, canal, relogio)
        return store, zeus, canal

    def _ferramentas_disponiveis(self, store, relogio):
        catalogo = Ferramentas(store, relogio).catalogo()
        return {item["function"]["name"] for item in catalogo}

    # -------------------------------------------------------------- execução
    def rodar(self, jornadas):
        relatorio = {
            "origem": self.origem,
            "em": datetime.now(timezone.utc).isoformat(),
            "modelo": getattr(self.provedor_real, "modelo", "dublê-roteirizado"),
            "jornadas": [],
        }
        for jornada in jornadas.get("jornadas", []):
            relatorio["jornadas"].append(self._rodar_jornada(jornada))
        relatorio["resumo"] = self._resumir(relatorio["jornadas"])
        return relatorio

    def _rodar_jornada(self, jornada):
        resultado = {"id": jornada.get("id", "sem-id"),
                     "titulo": jornada.get("titulo", ""),
                     "dimensoes": jornada.get("dimensoes", []),
                     "passos": [], "latencias": []}

        if jornada.get("status") == "pendente":
            resultado["situacao"] = "pendente"
            resultado["motivo"] = jornada.get("motivo", "jornada ainda não implementável")
            return resultado

        pasta = self.diretorio / resultado["id"]
        pasta.mkdir(parents=True, exist_ok=True)
        relogio = RelogioDeTeste(datetime.now(timezone.utc).replace(microsecond=0))

        modelo = self.provedor_real or ModeloRoteirizado()
        store, zeus, canal = self._montar(pasta, relogio, modelo)

        exigidas = set(jornada.get("requer_ferramentas", []))
        if exigidas - self._ferramentas_disponiveis(store, relogio):
            store.close()
            resultado["situacao"] = "pulada"
            resultado["motivo"] = ("ferramenta ausente nesta versão: "
                                   + ", ".join(sorted(exigidas)))
            return resultado

        try:
            for indice, passo in enumerate(jornada.get("passos", []), start=1):
                if passo.get("reiniciar"):
                    store.close()
                    store, zeus, canal_novo = self._montar(pasta, relogio, modelo)
                    canal.enviados.extend(canal_novo.enviados)
                    canal_novo.enviados = canal.enviados
                    canal = canal_novo
                    zeus.canal = canal
                resultado["passos"].append(
                    self._rodar_passo(indice, passo, zeus, store, canal, relogio, modelo))
        finally:
            store.close()

        falhas = [p for p in resultado["passos"] if p["falhas"]]
        resultado["situacao"] = "falhou" if falhas else "passou"
        if jornada.get("vale_em") == "real" and self.origem == "simulada":
            # O dublê diz o que a jornada mandou dizer. Passar aqui não prova
            # que o modelo real se comporta assim.
            resultado["observacao"] = ("jornada só tem valor com modelo real; "
                                       "o resultado simulado não comprova nada")
        medidas = [p["segundos"] for p in resultado["passos"]
                   if p.get("segundos") is not None]
        resultado["latencias"] = medidas
        if medidas:
            ordenadas = sorted(medidas)
            indice95 = max(0, int(round(0.95 * len(ordenadas))) - 1)
            resultado["latencia_p50"] = round(statistics.median(ordenadas), 2)
            resultado["latencia_p95"] = round(ordenadas[indice95], 2)
        return resultado

    def _rodar_passo(self, indice, passo, zeus, store, canal, relogio, modelo):
        registro = {"passo": indice, "falhas": [], "segundos": None}

        if "canal_fora" in passo:
            # Falha de canal não é detalhe: o combinado não pode se perder
            # porque o Telegram caiu no minuto do envio.
            canal.falhar = bool(passo["canal_fora"])
            registro["acao"] = ("canal fora do ar" if canal.falhar
                                else "canal de volta")

        if passo.get("avancar"):
            relogio.avancar_para(passo["avancar"])
            registro["acao"] = f"avançou para {passo['avancar']}"

        antes_de_enviar = len(canal.enviados)
        usadas = []

        if "nicolas" in passo:
            registro["acao"] = f"Nicolas: {passo['nicolas']}"
            if isinstance(modelo, ModeloRoteirizado):
                modelo.enfileirar(passo.get("modelo", []))
            original = zeus.ferramentas.executar

            def espiar(nome, argumentos):
                usadas.append(nome)
                return original(nome, argumentos)

            zeus.ferramentas.executar = espiar
            inicio = time.perf_counter()
            registro["resposta"] = zeus.conversar(passo["nicolas"], canal="avaliacao")
            registro["segundos"] = round(time.perf_counter() - inicio, 2)
            zeus.ferramentas.executar = original
            registro["ferramentas"] = usadas

        entregues = zeus.tick()
        registro["entregas"] = len(entregues)
        registro["entregue"] = [e["texto"] for e in entregues]

        self._conferir(passo.get("espera", {}), registro, store, canal, antes_de_enviar)
        return registro

    # ---------------------------------------------------------- verificações
    def _conferir(self, espera, registro, store, canal, antes):
        texto = " ".join([registro.get("resposta", "")] + registro.get("entregue", [])).lower()

        for nome in espera.get("usou", []):
            if nome not in registro.get("ferramentas", []):
                registro["falhas"].append(f"esperava usar {nome}")
        for nome in espera.get("nao_usou", []):
            if nome in registro.get("ferramentas", []):
                registro["falhas"].append(f"não podia usar {nome}")
        for trecho in espera.get("contem", []):
            if trecho.lower() not in texto:
                registro["falhas"].append(f"esperava encontrar '{trecho}'")
        for trecho in espera.get("nao_contem", []):
            if trecho.lower() in texto:
                registro["falhas"].append(f"não podia aparecer '{trecho}'")
        if "entregas" in espera and registro["entregas"] != espera["entregas"]:
            registro["falhas"].append(
                f"esperava {espera['entregas']} entrega(s), houve {registro['entregas']}")
        if espera.get("pergunta_respondida"):
            respondidas = store.connection.execute(
                "SELECT COUNT(*) FROM perguntas WHERE situacao='respondida'").fetchone()[0]
            if not respondidas:
                registro["falhas"].append("esperava pergunta marcada como respondida")
        for chave, valor in (espera.get("lembra") or {}).items():
            fato = store.recall(chave)
            if fato is None:
                registro["falhas"].append(f"esperava lembrar '{chave}'")
            elif valor and valor.lower() not in fato["value"].lower():
                registro["falhas"].append(f"'{chave}' deveria conter '{valor}'")
        for chave in espera.get("esqueceu", []):
            if store.recall(chave) is not None:
                registro["falhas"].append(f"'{chave}' deveria ter sido esquecido")

    def _resumir(self, jornadas):
        por_dimensao = {}
        for jornada in jornadas:
            for dimensao in jornada.get("dimensoes", ["sem dimensão"]):
                contagem = por_dimensao.setdefault(
                    dimensao, {"passou": 0, "falhou": 0, "pulada": 0, "pendente": 0})
                contagem[jornada.get("situacao", "pendente")] += 1
        return {
            "total": len(jornadas),
            "passou": sum(1 for j in jornadas if j.get("situacao") == "passou"),
            "falhou": sum(1 for j in jornadas if j.get("situacao") == "falhou"),
            "pulada": sum(1 for j in jornadas if j.get("situacao") == "pulada"),
            "pendente": sum(1 for j in jornadas if j.get("situacao") == "pendente"),
            "por_dimensao": por_dimensao,
        }


def carregar_jornadas(caminho=None) -> dict:
    alvo = Path(caminho or JORNADAS_PADRAO)
    if not alvo.exists():
        raiz = Path(__file__).resolve().parents[2]
        alvo = raiz / (caminho or JORNADAS_PADRAO)
    return json.loads(alvo.read_text(encoding="utf-8"))


def em_texto(relatorio: dict) -> str:
    """Relatório legível, com a origem da evidência em cada linha."""
    origem = ("dublê roteirizado — não vale como evidência de hardware"
              if relatorio["origem"] == "simulada"
              else f"modelo real {relatorio['modelo']} no equipamento desta execução")
    linhas = [f"Avaliação por jornadas — evidência {relatorio['origem']}",
              f"Origem: {origem}", f"Em: {relatorio['em']}", ""]
    for jornada in relatorio["jornadas"]:
        marca = {"passou": "ok", "falhou": "FALHOU",
                 "pulada": "pulada", "pendente": "pendente"}.get(
                     jornada.get("situacao", "pendente"), "?")
        linhas.append(f"[{marca}] {jornada['id']} — {jornada['titulo']}")
        if jornada.get("motivo"):
            linhas.append(f"        {jornada['motivo']}")
        if jornada.get("observacao"):
            linhas.append(f"        aviso: {jornada['observacao']}")
        if jornada.get("latencia_p50") is not None:
            linhas.append(f"        latência p50 {jornada['latencia_p50']}s, "
                          f"p95 {jornada['latencia_p95']}s")
        for passo in jornada.get("passos", []):
            for falha in passo["falhas"]:
                linhas.append(f"        passo {passo['passo']}: {falha}")
    resumo = relatorio["resumo"]
    linhas += ["", f"{resumo['passou']} passaram, {resumo['falhou']} falharam, "
                   f"{resumo['pulada']} puladas, {resumo['pendente']} pendentes"]
    return "\n".join(linhas)
