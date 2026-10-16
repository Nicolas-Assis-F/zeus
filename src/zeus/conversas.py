"""Ler sob pedido uma conversa do número principal.

O vigia avisa o que chega; aqui Nicolas pergunta ("qual a última mensagem que
o Henrique me mandou?") e o Zeus lê. Só leitura: a ponte A não envia nada, e o
banco da sessão é aberto em modo somente leitura, só nas tabelas de contato.

Achar o contato segue a ordem de confiança dos nomes:

1. o rótulo que Nicolas deu nos acompanhados (configuração ou liberados);
2. o nome no CRM da LE, escrito por ele;
3. o nome salvo na agenda, e por último o nome de perfil, que o próprio
   contato escolhe.

Mais de um candidato no mesmo degrau não vira palpite: a ferramenta devolve os
nomes e não lê nada. O que ela devolve é conversa de terceiro, então sai
marcado como externo (a barreira da #9).
"""

import json
import sqlite3
import unicodedata
from datetime import timedelta, timezone

from .canais.whatsapp import LeituraDaPonte
from .principal import LIBERADOS, acompanhados
from .quentes import Crm

PADRAO = 10
MAXIMO = 30
MAXIMO_DE_CANDIDATOS = 8
MAXIMO_DE_AUDIOS = 4
BRASILIA = timezone(timedelta(hours=-3))


class ContatoNaoEncontrado(ValueError):
    pass


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto or ""))
    # Sem acento e sem emoji: "Pai👊🏾" e "pai" são o mesmo nome.
    limpo = "".join(c if c.isalnum() else " " for c in sem_acento if not unicodedata.combining(c))
    return " ".join(limpo.lower().split())


def casa(busca: str, nome: str) -> bool:
    """Cada palavra da busca começa uma palavra do nome, em qualquer ordem."""
    palavras = normalizar(busca).split()
    alvo = normalizar(nome).split()
    return bool(palavras) and all(any(w.startswith(p) for w in alvo) for p in palavras)


class LeitorDeConversas:
    def __init__(self, banco: str, sessao: str, store, acompanhados_config=(), crm: str = "",
                 midia=None):
        self.leitura = LeituraDaPonte(banco)
        self.sessao = sessao
        self.store = store
        self.acompanhados = acompanhados(acompanhados_config)
        self.crm = Crm(crm) if crm else None
        self.midia = midia

    # ------------------------------------------------------------- sessão
    def _sessao(self, sql, parametros=()):
        try:
            conexao = sqlite3.connect(f"file:{self.sessao}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            return []
        try:
            return conexao.execute(sql, parametros).fetchall()
        except sqlite3.Error:
            return []
        finally:
            conexao.close()

    def _jids(self, jid: str) -> tuple:
        """O mesmo contato pode estar gravado pelo LID ou pelo telefone."""
        usuario, _, dominio = jid.partition("@")
        if dominio == "lid":
            linhas = self._sessao("SELECT pn FROM whatsmeow_lid_map WHERE lid=?", (usuario,))
            return (jid,) + tuple(f"{l[0].split('@')[0]}@s.whatsapp.net" for l in linhas if l[0])
        if dominio == "s.whatsapp.net":
            linhas = self._sessao("SELECT lid FROM whatsmeow_lid_map WHERE pn=?", (usuario,))
            return (jid,) + tuple(f"{l[0].split('@')[0]}@lid" for l in linhas if l[0])
        return (jid,)

    # ------------------------------------------------------------- achar
    def _rotulos(self) -> dict:
        try:
            liberados = json.loads(self.store.kv_get(LIBERADOS) or "{}")
        except ValueError:
            liberados = {}
        return {**liberados, **self.acompanhados}

    def achar(self, busca: str):
        """Devolve (jid, nome). Ambíguo ou ausente levanta ContatoNaoEncontrado."""
        busca = str(busca or "").strip()
        if not busca:
            raise ContatoNaoEncontrado("Diga de quem é a conversa.")
        degraus = [
            [(jid, rotulo) for jid, rotulo in self._rotulos().items() if rotulo and casa(busca, rotulo)],
            self._no_crm(busca),
            self._na_agenda(busca, "full_name"),
            self._na_agenda(busca, "push_name"),
        ]
        # Nome exato vale mais que começo de palavra, em qualquer degrau:
        # "Pai" é o pai, não o Paiva do CRM.
        alvo = normalizar(busca)
        for candidatos in degraus:
            exatos = {jid: nome for jid, nome in candidatos if normalizar(nome) == alvo}
            if len(exatos) == 1:
                return next(iter(exatos.items()))
        for candidatos in degraus:
            unicos = {}
            for jid, nome in candidatos:
                unicos.setdefault(jid, nome)
            if len(unicos) == 1:
                return next(iter(unicos.items()))
            if len(unicos) > 1:
                nomes = sorted(set(unicos.values()))[:MAXIMO_DE_CANDIDATOS]
                raise ContatoNaoEncontrado(
                    "Mais de um contato com esse nome: " + "; ".join(nomes) +
                    ". Pergunte a Nicolas qual deles.")
        raise ContatoNaoEncontrado(f"Não achei ninguém chamado {busca} no seu número principal.")

    def _no_crm(self, busca):
        if self.crm is None:
            return []
        self.crm._carregar()
        achados = []
        for telefone, lead in self.crm._por_telefone.items():
            nome = lead.get("savedName") or lead.get("name") or ""
            if nome and casa(busca, nome):
                achados.append((f"{telefone}@s.whatsapp.net", " ".join(str(nome).split())))
        return achados

    def _na_agenda(self, busca, coluna):
        linhas = self._sessao(f"SELECT their_jid, {coluna} FROM whatsmeow_contacts "
                              f"WHERE {coluna} IS NOT NULL AND {coluna} != ''")
        return [(jid, nome) for jid, nome in linhas if casa(busca, nome)]

    # ------------------------------------------------------------- ler
    def ler(self, busca: str, quantidade=PADRAO) -> dict:
        try:
            quantidade = max(1, min(MAXIMO, int(quantidade or PADRAO)))
        except (TypeError, ValueError):
            quantidade = PADRAO
        jid, nome = self.achar(busca)
        mensagens = self.leitura.conversa(self._jids(jid), quantidade)
        if self.midia is not None:
            # Só os áudios mais recentes são transcritos aqui: cada um leva
            # segundos. Os outros, e toda outra mídia, levam o id para ler_midia.
            from .midia import marcador
            audios = [m for m in mensagens if m.get("tipo_midia") == "audio"][-MAXIMO_DE_AUDIOS:]
            mensagens = [dict(m, texto=self.midia.transcricao("principal", m) if m in audios
                              else marcador(m, "principal")) if m["midia"] else m
                         for m in mensagens]
        linhas = [{"quando": m["em"].astimezone(BRASILIA).strftime("%d/%m %H:%M"),
                   "quem": "Nicolas" if m["meu"] else nome,
                   "texto": m["texto"]} for m in mensagens]
        return {"contato": nome, "mensagens": linhas, "total": len(linhas)}
