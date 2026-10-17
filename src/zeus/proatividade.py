"""Proatividade (#86): o Zeus que puxa o assunto, cobra e sabe ficar quieto.

Junta as peças sem modelo nenhum: a política de interrupção decide o canal,
a fila de fala espera a sala ficar livre, o escalonamento sobe de canal
quando ninguém responde, as bordas avisam prazos na transição e o
fechamento do dia conta o que andou. O motor dos objetivos (#85) roda daqui,
no ritmo do laço principal.

Tudo que o Zeus decide contar (ou não) passa por `comunicar`, e a decisão vai
para a trilha com o motivo, inclusive "quieto". Quem chama é o laço principal,
dono do banco do Zeus: a fila durável de saída é a mesma de sempre.
"""

import time
from datetime import datetime, timedelta

from .iniciativa import (FALAR, GRUPO, QUIETO, RESUMO, Aviso, Bordas, Contexto, Escalonamento,
                         FilaDeFala, decidir)

PRAZO_AVISO_S = 12 * 3600


def chave_base(chave: str) -> str:
    """'aprovacao:12' e 'aprovacao:13' contam como o mesmo tipo de aviso."""
    return chave.split(":", 1)[0]


class Proatividade:
    def __init__(self, autonomia, controles, fila_de_saida, nome_do_canal, anunciar=None,
                 falar_na_sala=None, sala_livre=lambda: True, motor=None, emit=None,
                 estado_dir=None, store=None, fechamento_hora="", relogio=None, agora_local=None):
        self.a = autonomia
        self.controles = controles
        self.fila_de_saida = fila_de_saida
        self.nome_do_canal = nome_do_canal          # None: sem canal de grupo
        self.anunciar = anunciar or (lambda *a, **k: None)
        self.falar_na_sala = falar_na_sala
        self.motor = motor
        self.emit = emit or (lambda *a, **k: None)
        self.store = store
        self.fechamento_hora = fechamento_hora
        self.relogio = relogio or time.time
        self.agora_local = agora_local or (lambda: datetime.now().astimezone())
        self.ultimo_contato = 0.0
        self.interrupcoes = []
        self.fala = FilaDeFala(self._dizer, pode_falar=sala_livre,
                               nao_perturbe=lambda: self._controles().get("nao_perturbe", False))
        self.escalonamento = Escalonamento(self._entregar_escalado, relogio=self.relogio)
        self.bordas = Bordas(f"{estado_dir}/bordas.json", relogio=self.relogio) if estado_dir else None
        self._proximo_motor = 0.0

    # ----------------------------------------------------------- contexto
    def _controles(self):
        try:
            return self.controles.ler() if self.controles else {}
        except Exception:
            return {}

    def _contexto(self, aviso):
        c = self._controles()
        agora = self.relogio()
        self.interrupcoes = [t for t in self.interrupcoes if agora - t < 3600]
        canais = c.get("canais") or {}
        peso = 1.0
        if self.a is not None:
            try:
                peso = self.a.feedback.peso(chave_base(aviso.chave))
            except Exception:
                peso = 1.0
        return Contexto(agora=self.agora_local(), nao_perturbe=bool(c.get("nao_perturbe")),
                        conversando=agora - self.ultimo_contato < 60,
                        interrupcoes_ultima_hora=len(self.interrupcoes),
                        sala=bool(self.falar_na_sala) and canais.get("sala", True) and not c.get("mudo"),
                        grupo=bool(self.nome_do_canal) and canais.get("grupo", True), peso=peso)

    # ----------------------------------------------------------- comunicar
    def comunicar(self, aviso: Aviso):
        canal, pontos, motivo = decidir(aviso, self._contexto(aviso))
        if self.a is not None:
            self.a.trilha.registrar("aviso", acao=aviso.chave, alvo=canal, resultado=f"{pontos}: {motivo} — {aviso.texto}"[:500])
        self.emit("aviso", chave=aviso.chave, canal=canal, pontos=pontos, motivo=motivo)
        if canal in (FALAR, GRUPO):
            self.interrupcoes.append(self.relogio())
            if self.store is not None:
                self.store.kv_set("ultimo_aviso_chave", chave_base(aviso.chave))
        if aviso.escalar and canal in (FALAR, GRUPO):
            self.escalonamento.abrir(aviso, comecar_em="sala" if canal == FALAR else "grupo")
        elif canal == FALAR:
            self.fala.por(aviso.texto, prioridade=pontos, critico=aviso.urgencia >= 0.9, chave=aviso.chave)
            self.anunciar("zeus", aviso.texto)
        elif canal == GRUPO:
            self._grupo(aviso)
        return canal

    def _grupo(self, aviso, prefixo=""):
        self.anunciar("zeus", prefixo + aviso.texto)
        if not self.nome_do_canal:
            return False
        sufixo = "urgente" if prefixo else "grupo"
        return self.fila_de_saida.preparar(f"aviso:{aviso.chave}:{sufixo}", self.nome_do_canal,
                                           prefixo + aviso.texto, tipo="aviso")

    def _entregar_escalado(self, canal, aviso):
        if canal == "sala":
            if self._contexto(aviso).sala:
                self.fala.por(aviso.texto, prioridade=0.8, critico=aviso.urgencia >= 0.9, chave=aviso.chave)
                self.anunciar("zeus", aviso.texto)
            else:  # sala indisponível: o primeiro degrau vira o grupo
                self._grupo(aviso)
        elif canal == "grupo":
            self._grupo(aviso)
        elif canal == "grupo_urgente":
            self._grupo(aviso, "⚠️ Ainda preciso de você: ")
        self.emit("escalonamento", chave=aviso.chave, canal=canal)

    def _dizer(self, texto):
        if self.falar_na_sala is not None:
            self.falar_na_sala(texto)

    def nicolas_apareceu(self, chave=None):
        """Qualquer mensagem dele, em qualquer canal, cancela o que estava subindo."""
        self.ultimo_contato = self.relogio()
        cancelados = self.escalonamento.respondeu(chave)
        if cancelados:
            self.emit("escalonamento_cancelado", chaves=cancelados)
        return cancelados

    # ----------------------------------------------------------------- ciclo
    def tick(self, modelo_ok=True, intervalo_motor=20):
        self.escalonamento.rodar()
        self.fala.rodar_uma()
        if self.a is None:
            return
        if self.motor is not None and modelo_ok and self.relogio() >= self._proximo_motor:
            self._proximo_motor = self.relogio() + intervalo_motor
            self.motor.tick()
        self._prazos()
        self._fechamento()

    def _prazos(self):
        if self.bordas is None:
            return
        agora = self.relogio()
        for o in self.a.objetivos.listar():
            if o["estado"] not in ("ativo", "aguardando_nicolas", "bloqueado") or not o.get("prazo"):
                continue
            perto = 0 < o["prazo"] - agora <= PRAZO_AVISO_S
            if self.bordas.observar(f"prazo:{o['id']}", perto):
                horas = max(1, round((o["prazo"] - agora) / 3600))
                self.comunicar(Aviso(f"prazo:{o['id']}", f"Senhor, “{o['titulo']}” vence em cerca de {horas} h "
                                     f"e ainda está {o['estado'].replace('_', ' ')}. Próxima ação: {o.get('proxima_acao') or '—'}.",
                                     urgencia=0.65, utilidade=0.8, referencia=str(o["id"])))

    # ------------------------------------------------------------- fechamento
    def texto_do_fechamento(self, dia=None):
        """Sem modelo: o fechamento é contagem e fatos da trilha, não redação."""
        r = self.a.trilha.resumo_do_dia(dia)
        feitos = [f"{x['acao']} → {x['alvo']}" for x in r["feito"] if not x["desfeito"]][:6]
        pendentes = self.a.aprovacoes.pendentes(self.relogio())
        objetivos = self.a.objetivos.listar()
        travados = [o for o in objetivos if o["estado"] == "bloqueado"]
        andando = [o for o in objetivos if o["estado"] in ("ativo", "aguardando_nicolas")]
        guardados = [x["resultado"].split(" — ", 1)[-1] for x in self.a.trilha.listar(
            desde=self.relogio() - 86400, tipos=["aviso"], limite=50) if x["alvo"] == RESUMO][:5]
        partes = ["Fechamento do dia, senhor."]
        partes.append(f"Fiz sozinho {len(r['feito'])} coisa(s)" + (": " + "; ".join(feitos) + "." if feitos else "."))
        if r["falhas"]:
            partes.append(f"{len(r['falhas'])} falha(s) registrada(s).")
        if andando:
            partes.append("Em andamento: " + "; ".join(f"{o['titulo']} (próxima: {o.get('proxima_acao') or '—'})"
                                                       for o in andando[:4]) + ".")
        if travados:
            partes.append("Travado: " + "; ".join(o["titulo"] for o in travados[:3]) + ".")
        if pendentes:
            partes.append("Esperando sua aprovação: " + "; ".join(f"{p['acao']} → {p['alvo']} (ok {p['codigo']})"
                                                                for p in pendentes[:4]) + ".")
        if guardados:
            partes.append("Guardei para agora: " + " / ".join(guardados) + ".")
        if len(partes) == 2 and not r["feito"]:
            partes = ["Fechamento do dia, senhor: nada andou sozinho hoje e nada espera você."]
        if r["custo_usd"]:
            partes.append(f"Custo dos objetivos hoje: US$ {r['custo_usd']:.3f}.")
        return " ".join(partes)

    def _fechamento(self):
        if not self.fechamento_hora or not self.nome_do_canal:
            return
        from .briefing import hora_e_minuto, ja_enviado
        alvo = hora_e_minuto(self.fechamento_hora)
        agora = self.agora_local()
        if alvo is None:
            return
        inicio = agora.replace(hour=alvo[0], minute=alvo[1], second=0, microsecond=0)
        if not inicio <= agora < inicio + timedelta(hours=1):
            return
        chave = f"fechamento:{agora.date().isoformat()}"
        if self.store is not None and ja_enviado(self.store, chave):
            return
        texto = self.texto_do_fechamento()
        if self.fila_de_saida.preparar(chave, self.nome_do_canal, texto, tipo="aviso"):
            self.anunciar("zeus", texto)
            self.emit("fechamento", caracteres=len(texto))
