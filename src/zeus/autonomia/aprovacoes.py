"""Caixa de aprovações: o que precisa do "ok" de Nicolas, com código de 4 dígitos.

Cada pedido mostra a ação, o alvo exato (destinatário, arquivo, serviço) e o
porquê, e recebe um código como `4821`. Nicolas responde "ok 4821" ou
"não 4821" em qualquer canal (sala, grupo, HUD); `decidir` vale uma vez e os
assinantes de `ao_mudar` apagam o pedido nos outros canais.

Correções em relação ao `tools/proactive_tools.py` do OpenJarvis:

- lá uma ação já executada voltava a `approved` e rodava de novo, porque a
  leitura não conferia o estado. Aqui `consumir` é um UPDATE condicional
  `WHERE estado='aprovada' AND args_hash=?`: devolve True uma única vez, e só
  para o payload exato que Nicolas aprovou. Se o modelo trocar o destinatário
  depois do "ok", o hash muda e o consumo falha;
- lá "yes all" aprovava tudo. Aqui não existe aprovação em lote: cada código
  precisa da sua palavra, e "sim para todos" não aprova nada;
- lá qualquer remetente aprovava. Aqui só `por='nicolas'` decide; o canal é
  quem garante que a mensagem veio dele, e esta camada recusa o resto.

O código é único entre os pendentes e também não repete um código usado nos
últimos `QUARENTENA_DE_CODIGO_S`. Sem isso, um "ok 4821" repetido por engano
poderia aprovar um pedido novo que herdou o mesmo número.

Partes adaptadas de OpenJarvis, commit 091068cb, arquivos
src/openjarvis/tools/proactive_tools.py, Apache-2.0; modificado.
"""

import json
import re
import secrets
import unicodedata

from .banco import args_hash, json_canonico
from .niveis import Nivel

VALIDADE_PADRAO_S = 24 * 3600
QUARENTENA_DE_CODIGO_S = 7 * 24 * 3600
ESTADOS = ("pendente", "aprovada", "negada", "expirada", "consumida")


def _aprovacao(linha):
    if linha is None:
        return None
    linha = dict(linha)
    linha["args"] = json.loads(linha["args_json"] or "{}")
    return linha


class Aprovacoes:
    def __init__(self, banco, trilha, objetivos=None, validade_s=VALIDADE_PADRAO_S):
        self.banco = banco
        self.trilha = trilha
        self.objetivos = objetivos
        self.validade_s = validade_s
        self._assinantes = []

    # ── assinantes ─────────────────────────────────────────────────────────

    def ao_mudar(self, callback):
        """Registra `callback(aprovacao)` chamado depois de cada mudança gravada.

        Devolve uma função que cancela a assinatura. Erro no callback não
        desfaz a decisão: ela já está no banco.
        """
        self._assinantes.append(callback)
        return lambda: self._assinantes.remove(callback) if callback in self._assinantes else None

    def _avisar(self, aprovacoes):
        for aprovacao in aprovacoes:
            for callback in list(self._assinantes):
                try:
                    callback(aprovacao)
                except Exception:
                    pass

    # ── leitura ────────────────────────────────────────────────────────────

    def obter(self, id_aprovacao):
        return _aprovacao(self.banco.ler_um("SELECT * FROM aprovacoes WHERE id=?",
                                            (int(id_aprovacao),)))

    def _expirar(self, db, agora):
        vencidas = db.execute("SELECT * FROM aprovacoes WHERE estado='pendente' AND expira_em<=?",
                              (agora,)).fetchall()
        mudadas = []
        for linha in vencidas:
            if db.execute("UPDATE aprovacoes SET estado='expirada', decidida_em=? "
                          "WHERE id=? AND estado='pendente'", (agora, linha["id"])).rowcount:
                self.trilha.registrar("expiracao", objetivo_id=linha["objetivo_id"],
                                      acao=linha["acao"], alvo=linha["alvo"],
                                      resultado=f"pedido {linha['codigo']} expirou sem resposta",
                                      nivel=linha["nivel"], ts=agora)
                if self.objetivos is not None and linha["objetivo_id"] is not None:
                    self.objetivos.acordar_por_evento(f"aprovacao:{linha['id']}")
                mudadas.append(linha["id"])
        return mudadas

    def pendentes(self, agora=None) -> list:
        """Pedidos em aberto, depois de expirar os vencidos."""
        agora = self.banco.agora() if agora is None else float(agora)
        with self.banco.transacao() as db:
            expiradas = self._expirar(db, agora)
            linhas = db.execute("SELECT * FROM aprovacoes WHERE estado='pendente' "
                                "ORDER BY criada_em, id").fetchall()
            resultado = [_aprovacao(l) for l in linhas]
        self._avisar([self.obter(i) for i in expiradas])
        return resultado

    # ── pedido ─────────────────────────────────────────────────────────────

    def _codigo_novo(self, db, agora):
        ocupados = {r[0] for r in db.execute(
            "SELECT codigo FROM aprovacoes WHERE estado='pendente' OR criada_em>?",
            (agora - QUARENTENA_DE_CODIGO_S,))}
        if len(ocupados) >= 9000:
            raise RuntimeError("Pedidos demais em aberto para gerar código de 4 dígitos.")
        while True:
            # 1000 a 9999: código sem zero à esquerda, que a fala e o teclado
            # do celular às vezes comem.
            codigo = str(1000 + secrets.randbelow(9000))
            if codigo not in ocupados:
                return codigo

    def pedir(self, acao, alvo, args=None, porque="", objetivo_id=None, origem="nicolas",
              nivel=Nivel.PEDE_ANTES, validade_s=None) -> dict:
        """Abre um pedido. Devolve {'id', 'codigo', 'expira_em', 'novo'}.

        O mesmo pedido (ação, argumentos e objetivo iguais) ainda pendente é
        devolvido em vez de duplicado, para um laço não encher a caixa.
        """
        if not str(alvo or "").strip():
            raise ValueError("Pedido de aprovação precisa do alvo exato.")
        if origem != "nicolas" and not str(origem).startswith("externo:"):
            raise ValueError("Origem precisa ser 'nicolas' ou 'externo:<fonte>'.")
        args = args or {}
        identidade = args_hash(acao, args)
        agora = self.banco.agora()
        with self.banco.transacao() as db:
            self._expirar(db, agora)
            igual = db.execute(
                "SELECT * FROM aprovacoes WHERE estado='pendente' AND args_hash=? "
                "AND objetivo_id IS ?", (identidade, objetivo_id)).fetchone()
            if igual:
                return {"id": igual["id"], "codigo": igual["codigo"],
                        "expira_em": igual["expira_em"], "novo": False}
            codigo = self._codigo_novo(db, agora)
            expira = agora + float(validade_s if validade_s is not None else self.validade_s)
            id_aprovacao = db.execute(
                "INSERT INTO aprovacoes (codigo,acao,alvo,args_json,args_hash,porque,objetivo_id,"
                "origem,nivel,criada_em,expira_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (codigo, acao, str(alvo).strip(), json_canonico(args), identidade, porque,
                 objetivo_id, origem, int(nivel), agora, expira)).lastrowid
            self.trilha.registrar("pedido", objetivo_id=objetivo_id, acao=acao, alvo=alvo,
                                  resultado=f"código {codigo}: {porque}", nivel=int(nivel), ts=agora)
        self._avisar([self.obter(id_aprovacao)])
        return {"id": id_aprovacao, "codigo": codigo, "expira_em": expira, "novo": True}

    # ── decisão ────────────────────────────────────────────────────────────

    def _achar(self, db, codigo_ou_id):
        if isinstance(codigo_ou_id, int):
            return db.execute("SELECT * FROM aprovacoes WHERE id=?", (codigo_ou_id,)).fetchone()
        codigo = str(codigo_ou_id).strip()
        # Pendente primeiro; senão a decisão mais recente com esse código, para
        # a repetição do mesmo "ok" ser reconhecida como repetição.
        return db.execute("SELECT * FROM aprovacoes WHERE codigo=? "
                          "ORDER BY estado='pendente' DESC, id DESC LIMIT 1", (codigo,)).fetchone()

    def decidir(self, codigo_ou_id, aprovar: bool, por: str, canal: str) -> dict:
        """Aprova ou nega. Devolve {'ok', 'repetida', 'motivo', 'aprovacao'}.

        Idempotente: decidir de novo o mesmo devolve o resultado anterior sem
        efeito. Decidir o contrário do que já foi decidido é recusado.
        """
        agora = self.banco.agora()
        mudadas = []

        def resposta(ok, motivo, linha, repetida=False):
            return {"ok": ok, "repetida": repetida, "motivo": motivo,
                    "aprovacao": _aprovacao(linha) if linha is not None else None}

        with self.banco.transacao() as db:
            linha = self._achar(db, codigo_ou_id)
            if linha is None:
                return resposta(False, "não há pedido com esse código", None)
            if por != "nicolas":
                self.trilha.registrar("aviso", objetivo_id=linha["objetivo_id"], acao=linha["acao"],
                                      alvo=linha["alvo"], ts=agora,
                                      resultado=f"decisão recusada: veio de {por!r} pelo canal {canal}")
                return resposta(False, "só Nicolas decide aprovações", linha)
            if linha["estado"] == "pendente" and linha["expira_em"] <= agora:
                mudadas = self._expirar(db, agora)
                linha = db.execute("SELECT * FROM aprovacoes WHERE id=?", (linha["id"],)).fetchone()
            pedido = "aprovada" if aprovar else "negada"
            if linha["estado"] == "expirada":
                resultado = resposta(False, "o pedido expirou; peça de novo", linha)
            elif linha["estado"] != "pendente":
                anterior = "aprovada" if linha["estado"] == "consumida" else linha["estado"]
                if anterior == pedido:
                    resultado = resposta(True, f"já estava {linha['estado']}", linha, repetida=True)
                else:
                    resultado = resposta(False, f"já foi {linha['estado']}; não muda", linha)
            else:
                db.execute("UPDATE aprovacoes SET estado=?, decidida_em=?, decidida_por=?, "
                           "canal_da_decisao=? WHERE id=? AND estado='pendente'",
                           (pedido, agora, por, canal, linha["id"]))
                self.trilha.registrar("aprovacao" if aprovar else "negacao",
                                      objetivo_id=linha["objetivo_id"], acao=linha["acao"],
                                      alvo=linha["alvo"], nivel=linha["nivel"], ts=agora,
                                      resultado=f"código {linha['codigo']} {pedido} por {por} via {canal}")
                if self.objetivos is not None and linha["objetivo_id"] is not None:
                    self.objetivos.acordar_por_evento(f"aprovacao:{linha['id']}")
                linha = db.execute("SELECT * FROM aprovacoes WHERE id=?", (linha["id"],)).fetchone()
                mudadas.append(linha["id"])
                resultado = resposta(True, pedido, linha)
        self._avisar([self.obter(i) for i in mudadas])
        return resultado

    def consumir(self, id_aprovacao, args_hash_atual) -> bool:
        """aprovada -> consumida, só uma vez e só para o mesmo payload.

        Quem executa chama logo antes de agir, com o hash dos argumentos que vai
        usar de fato. False quer dizer: não execute.
        """
        agora = self.banco.agora()
        with self.banco.transacao() as db:
            consumiu = db.execute(
                "UPDATE aprovacoes SET estado='consumida', consumida_em=? "
                "WHERE id=? AND estado='aprovada' AND args_hash=? AND expira_em>?",
                (agora, int(id_aprovacao), args_hash_atual, agora)).rowcount == 1
        if consumiu:
            self._avisar([self.obter(id_aprovacao)])
        return consumiu


# ── leitura da resposta de Nicolas ─────────────────────────────────────────

SIM = {"ok", "okay", "sim", "aprovo", "aprovado", "aprova", "aprovar", "pode", "confirmo",
       "autorizo", "manda"}
NAO = {"nao", "nega", "negar", "negado", "nego", "recuso", "cancela", "veto"}
LOTE = {"todos", "todas", "tudo", "all", "geral", "everything", "qualquer"}
CODIGO = re.compile(r"^\d{4}$")


def _normalizar(texto):
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                         if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z]+|\d+", sem_acento.lower())


def _parear(fichas, verbo_antes):
    """Pareia cada código com a palavra vizinha numa orientação só."""
    pares, usadas = [], set()
    for i, ficha in enumerate(fichas):
        if not CODIGO.match(ficha):
            continue
        j = i - 1 if verbo_antes else i + 1
        if not 0 <= j < len(fichas) or j in usadas or fichas[j] not in SIM | NAO:
            return None
        aprovar = fichas[j] in SIM
        # "não aprovo 4821" é negação, não aprovação.
        if aprovar and verbo_antes and j > 0 and fichas[j - 1] == "nao":
            aprovar = False
        usadas.add(j)
        pares.append((ficha, aprovar))
    return pares


def interpretar_resposta(texto) -> list:
    """Lista de (codigo, aprovar) lida de uma resposta de Nicolas.

    Cada código precisa de uma palavra de sim ou de não colada nele, antes
    ("ok 4821") ou depois ("4821 ok"). Na dúvida, devolve lista vazia, e o
    Zeus pergunta de novo: errar para o lado de não aprovar é barato.
    Nunca aprova em lote nem aceita "ok" sem código.
    """
    fichas = _normalizar(texto)
    if not fichas or LOTE & set(fichas):
        return []
    if not any(CODIGO.match(f) for f in fichas):
        return []
    for verbo_antes in (True, False):
        pares = _parear(fichas, verbo_antes)
        if pares:
            break
    else:
        return []
    decisoes = {}
    for codigo, aprovar in pares:
        decisoes.setdefault(codigo, set()).add(aprovar)
    # O mesmo código com sim e não na mesma mensagem não decide nada.
    return [(codigo, valores.pop()) for codigo, valores in decisoes.items() if len(valores) == 1]
