"""Iniciativa (#86): quando falar, por onde, e quando ficar quieto.

Nenhuma decisão aqui chama modelo. A política de interrupção é uma conta
explícita, testável, e a primeira pergunta dela é sempre "precisa mesmo?":

    pontos = U · V^0,7 · C^1,5 · H(hora, U) · (1 − K) · peso do feedback

- U, urgência; V, utilidade; C, confiança no que vai ser dito (0..1);
- H, o horário: dia cheio, noite pela metade, madrugada quase nada; o
  crítico (U ≥ 0,9) ignora o horário;
- K, o custo de interromper agora: ele está falando, já foi interrompido
  várias vezes na última hora;
- peso do feedback: o "útil" e o "não precisava" do Nicolas, do banco da
  autonomia, entre 0,2 e 1,5.

Saída: "falar" (sala, se a sala estiver ligada e livre), "grupo", "resumo"
(guardado para o briefing ou o fechamento) ou "quieto". Não perturbe deixa
passar só o crítico. A fórmula veio do estudo do OpenJarvis
(/srv/zeus-build/07-pesquisa-autonomia.md), que não tinha nada disso.

Também aqui: fila de fala com prioridade (ideia do VISOR), gatilho com borda
(avisa na transição, rearma depois de voltar) e escalonamento sala → grupo →
repetição, cancelado quando Nicolas responde em qualquer canal.
"""

import heapq
import itertools
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FALAR, GRUPO, RESUMO, QUIETO = "falar", "grupo", "resumo", "quieto"
LIMIAR_FALAR = 0.45
LIMIAR_GRUPO = 0.25
LIMIAR_RESUMO = 0.08
CRITICO = 0.9


@dataclass
class Aviso:
    """Algo que o Zeus poderia dizer. `chave` é o tipo canônico (para o
    feedback e a deduplicação), `texto` é o que seria dito."""
    chave: str
    texto: str
    urgencia: float = 0.3
    utilidade: float = 0.5
    confianca: float = 0.9
    escalar: bool = False          # se ninguém responder, sobe de canal
    referencia: str = ""           # id da coisa (aprovação, objetivo...)


@dataclass
class Contexto:
    agora: datetime
    nao_perturbe: bool = False
    conversando: bool = False      # ele falou com o Zeus no último minuto
    interrupcoes_ultima_hora: int = 0
    sala: bool = True              # falar na sala está ligado e há alto-falante
    grupo: bool = True
    peso: float = 1.0              # do feedback do Nicolas


def horario(agora: datetime, urgencia: float) -> float:
    if urgencia >= CRITICO:
        return 1.0
    h = agora.hour + agora.minute / 60
    if 8 <= h < 20:
        return 1.0
    if 20 <= h < 23:
        return 0.5
    if 6.5 <= h < 8:
        return 0.4
    return 0.05          # 23h–6h30: o sono dele


def pontuar(aviso: Aviso, ctx: Contexto) -> float:
    custo = min(0.8, 0.1 * ctx.interrupcoes_ultima_hora + (0.3 if ctx.conversando else 0.0))
    base = (max(0.0, aviso.urgencia) * max(0.0, aviso.utilidade) ** 0.7
            * max(0.0, aviso.confianca) ** 1.5 * horario(ctx.agora, aviso.urgencia) * (1 - custo))
    return round(base * max(0.2, min(1.5, ctx.peso)), 4)


def decidir(aviso: Aviso, ctx: Contexto):
    """(canal, pontos, motivo). O motivo vai para a trilha: decisão de ficar
    quieto também precisa ser explicável."""
    critico = aviso.urgencia >= CRITICO
    pontos = pontuar(aviso, ctx)
    if ctx.nao_perturbe and not critico:
        return (RESUMO if pontos >= LIMIAR_RESUMO else QUIETO), pontos, "não perturbe"
    if pontos >= LIMIAR_FALAR or critico:
        if ctx.sala and not ctx.conversando:
            return FALAR, pontos, "importante e a sala está livre"
        if ctx.grupo:
            return GRUPO, pontos, "importante; sala indisponível ou ocupada"
        return RESUMO, pontos, "importante, mas sem canal ligado"
    if pontos >= LIMIAR_GRUPO and ctx.grupo:
        return GRUPO, pontos, "útil, sem pressa de voz"
    if pontos >= LIMIAR_RESUMO:
        return RESUMO, pontos, "pode esperar o resumo"
    return QUIETO, pontos, "não vale a interrupção"


# ── fila de fala ──────────────────────────────────────────────────────────

@dataclass(order=True)
class _ItemDeFala:
    prioridade: float
    ordem: int
    texto: str = field(compare=False)
    critico: bool = field(compare=False, default=False)
    chave: str = field(compare=False, default="")


class FilaDeFala:
    """Prioridade maior primeiro; na mesma, o mais antigo. Mesma chave na fila
    não entra de novo. `pode_falar()` diz se a sala está livre (escuta dormindo,
    alto-falante parado); o crítico fala mesmo em não perturbe."""

    def __init__(self, falar, pode_falar=lambda: True, nao_perturbe=lambda: False):
        self.falar = falar
        self.pode_falar = pode_falar
        self.nao_perturbe = nao_perturbe
        self._heap = []
        self._ordem = itertools.count()
        self._trava = threading.Lock()

    def por(self, texto, prioridade=0.5, critico=False, chave=""):
        with self._trava:
            if chave and any(i.chave == chave for i in self._heap):
                return False
            heapq.heappush(self._heap, _ItemDeFala(-prioridade, next(self._ordem), texto, critico, chave))
            return True

    def tamanho(self):
        with self._trava:
            return len(self._heap)

    def rodar_uma(self):
        """Fala o primeiro da fila se der agora. Devolve o texto falado ou None."""
        with self._trava:
            if not self._heap:
                return None
            item = self._heap[0]
            livre = self.pode_falar()
            if self.nao_perturbe() and not item.critico:
                return None
            if not livre and not item.critico:
                return None
            heapq.heappop(self._heap)
        self.falar(item.texto)
        return item.texto


# ── gatilho com borda ─────────────────────────────────────────────────────

class Bordas:
    """Avisa na transição falso→verdadeiro; rearma depois de `rearme_s`
    seguidos em falso. Estado em arquivo próprio: sobrevive a reinício."""

    def __init__(self, arquivo, rearme_s=300, relogio=None):
        self.arquivo = Path(arquivo)
        self.rearme_s = rearme_s
        self.relogio = relogio or time.time
        self._trava = threading.Lock()

    def _ler(self):
        try:
            return json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _gravar(self, dados):
        self.arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=self.arquivo.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as saida:
            json.dump(dados, saida)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.arquivo)

    def observar(self, chave, condicao: bool) -> bool:
        """True só no instante em que a condição vira verdadeira (armada)."""
        agora = self.relogio()
        with self._trava:
            dados = self._ler()
            estado = dados.get(chave, {"armado": True, "falso_desde": None})
            disparou = False
            if condicao:
                estado["falso_desde"] = None
                if estado["armado"]:
                    estado["armado"] = False
                    estado["ultimo_disparo"] = agora
                    disparou = True
            else:
                if estado.get("falso_desde") is None:
                    estado["falso_desde"] = agora
                if not estado["armado"] and agora - estado["falso_desde"] >= self.rearme_s:
                    estado["armado"] = True
            dados[chave] = estado
            self._gravar(dados)
        return disparou


# ── escalonamento ─────────────────────────────────────────────────────────

DEGRAUS = (("sala", 0), ("grupo", 600), ("grupo_urgente", 1800))


class Escalonamento:
    """Alerta que precisa de resposta sobe de canal até alguém responder.

    sala agora → grupo depois de 10 min → repetição urgente depois de 30 min
    (no máximo três degraus). Qualquer resposta do Nicolas, em qualquer canal,
    chama `respondeu()` e cancela o resto. Ligação telefônica é o degrau que
    a #13 do Codex vai acrescentar (`canal_ligacao`)."""

    def __init__(self, entregar, relogio=None, degraus=DEGRAUS, canal_ligacao=None):
        self.entregar = entregar            # entregar(canal, aviso) -> bool
        self.relogio = relogio or time.time
        self.degraus = degraus
        self.canal_ligacao = canal_ligacao  # ponto de extensão, sem implementação
        self._abertos = {}
        self._trava = threading.Lock()

    def abrir(self, aviso: Aviso, comecar_em="sala"):
        with self._trava:
            if aviso.chave in self._abertos:
                return False
            nomes = [d[0] for d in self.degraus]
            inicio = nomes.index(comecar_em) if comecar_em in nomes else 0
            self._abertos[aviso.chave] = {"aviso": aviso, "aberto_em": self.relogio(),
                                          "proximo": inicio, "base": self.degraus[inicio][1]}
        self.rodar()
        return True

    def respondeu(self, chave=None):
        """Sem chave: Nicolas apareceu, cancela tudo que estava subindo."""
        with self._trava:
            if chave is None:
                cancelados = list(self._abertos)
                self._abertos.clear()
            else:
                cancelados = [chave] if self._abertos.pop(chave, None) else []
        return cancelados

    def abertos(self):
        with self._trava:
            return list(self._abertos)

    def rodar(self):
        agora = self.relogio()
        entregas = []
        with self._trava:
            for chave, estado in list(self._abertos.items()):
                if estado["proximo"] >= len(self.degraus):
                    self._abertos.pop(chave)
                    continue
                canal, apos = self.degraus[estado["proximo"]]
                if agora - estado["aberto_em"] >= apos - estado["base"]:
                    estado["proximo"] += 1
                    entregas.append((canal, estado["aviso"]))
        for canal, aviso in entregas:
            try:
                self.entregar(canal, aviso)
            except Exception:
                pass
        return entregas
