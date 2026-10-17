"""Objetivos persistentes, seus passos e a guarda contra laço.

Um objetivo é um pedido de Nicolas que atravessa mais de um turno: "vê com o
Henrique se o frete chegou e me avisa". Ele mora no banco, não na memória do
processo, para sobreviver a reinício. No OpenJarvis o estado entre ticks se
perdia porque a gravação dava TypeError engolido (`operative.py`); aqui toda
mudança passa por uma transação e por uma linha na trilha.

Estados e transições:

    ativo ──────────────► aguardando_nicolas ──► ativo
      │  ▲                        │
      ▼  │                        ▼
    bloqueado ──────────────► abandonado
      │
      └── concluir(evidência) ──► concluido

`concluido` e `abandonado` são finais. Concluir exige evidência: "feito" sem
prova é o jeito mais comum de um agente mentir sem querer.

Quem executa um objetivo pega a trava (`travar`) com UPDATE condicional, o
que funciona entre threads e entre processos. Trava sem dono vivo expira
sozinha em `lock_zumbi_s` (600 s), como no `agents/manager.py` do OpenJarvis.

A guarda (`avaliar_passo`) é a reescrita do `loop_guard.py` do OpenJarvis sem
os defeitos achados no estudo: lá o bloqueio por chamada idêntica nunca
disparava (a chave do aviso incluía a contagem), o aviso era ignorado pelos
chamadores, e o ping-pong olhava só o nome da ferramenta, de modo que quatro
buscas diferentes contavam como laço. Aqui a identidade é `args_hash`, a
memória é por objetivo e persistida, e o veredito é uma decisão, não um aviso.

Partes adaptadas de OpenJarvis, commit 091068cb, arquivos
src/openjarvis/agents/loop_guard.py e src/openjarvis/agents/manager.py,
Apache-2.0; modificado.
"""

import json
from dataclasses import dataclass

from .banco import args_hash, cortar, json_canonico

ESTADOS = ("ativo", "aguardando_nicolas", "bloqueado", "concluido", "abandonado")
TRANSICOES = {
    "ativo": {"aguardando_nicolas", "bloqueado", "abandonado"},
    "aguardando_nicolas": {"ativo", "bloqueado", "abandonado"},
    "bloqueado": {"ativo", "aguardando_nicolas", "abandonado"},
    "concluido": set(),
    "abandonado": set(),
}
ESTADOS_DE_PASSO = ("pendente", "executando", "feito", "falhou", "aguardando")

TETO_PASSOS_DIA = 30
TETO_USD_DIA = 1.00
LOCK_ZUMBI_S = 600
MAX_REPETICOES = 2
JANELA_DE_LACO = 6
SEM_PROGRESSO_MAXIMO = 3

CAMPOS_EDITAVEIS = {"titulo", "proxima_acao", "prazo", "estado_json", "acordar_em",
                    "acordar_por", "teto_passos_dia", "teto_usd_dia"}


class TransicaoInvalida(ValueError):
    """Mudança de estado que o modelo de objetivos não permite."""


@dataclass(frozen=True)
class Veredito:
    decisao: str  # 'permitir' ou 'bloquear'
    motivo: str

    @property
    def permitido(self) -> bool:
        return self.decisao == "permitir"

    def __bool__(self):
        return self.permitido


PERMITIR = Veredito("permitir", "")


def _periodico(sequencia, periodo) -> bool:
    return all(sequencia[i] == sequencia[i % periodo] for i in range(len(sequencia)))


def _objetivo(linha):
    if linha is None:
        return None
    linha = dict(linha)
    linha["estado_json"] = json.loads(linha["estado_json"] or "{}")
    linha["taint"] = json.loads(linha["taint"] or "[]")
    return linha


def _passo(linha):
    linha = dict(linha)
    linha["args"] = json.loads(linha["args_json"] or "{}")
    linha["desfazer"] = json.loads(linha["desfazer_json"]) if linha["desfazer_json"] else None
    return linha


class Objetivos:
    def __init__(self, banco, trilha, lock_zumbi_s=LOCK_ZUMBI_S):
        self.banco = banco
        self.trilha = trilha
        self.lock_zumbi_s = lock_zumbi_s

    # ── leitura ────────────────────────────────────────────────────────────

    def _linha(self, db, objetivo_id):
        linha = db.execute("SELECT * FROM objetivos WHERE id=?", (int(objetivo_id),)).fetchone()
        if linha is None:
            raise KeyError(f"Objetivo {objetivo_id} não existe.")
        return linha

    def _virar_dia(self, db, linha, agora):
        """Zera os contadores diários quando o dia local mudou desde o último passo."""
        hoje = self.banco.dia(agora)
        if linha["dia_dos_passos"] != hoje:
            db.execute("UPDATE objetivos SET passos_hoje=0, custo_usd_hoje=0, dia_dos_passos=? "
                       "WHERE id=? AND dia_dos_passos=?", (hoje, linha["id"], linha["dia_dos_passos"]))
            return self._linha(db, linha["id"])
        return linha

    def obter(self, objetivo_id, com_passos=True):
        with self.banco.transacao() as db:
            try:
                linha = self._linha(db, objetivo_id)
            except KeyError:
                return None
            objetivo = _objetivo(self._virar_dia(db, linha, self.banco.agora()))
            if com_passos:
                objetivo["passos"] = [_passo(p) for p in db.execute(
                    "SELECT * FROM passos WHERE objetivo_id=? ORDER BY ordem", (int(objetivo_id),))]
            return objetivo

    def listar(self, estado=None) -> list:
        if estado is not None and estado not in ESTADOS:
            raise ValueError(f"Estado desconhecido: {estado}")
        if estado:
            linhas = self.banco.ler("SELECT * FROM objetivos WHERE estado=? ORDER BY id", (estado,))
        else:
            linhas = self.banco.ler("SELECT * FROM objetivos ORDER BY id")
        return [_objetivo(l) for l in linhas]

    def devidos(self, agora=None) -> list:
        """Ativos cuja hora chegou ou cujo evento esperado já veio, sem trava viva."""
        agora = self.banco.agora() if agora is None else float(agora)
        linhas = self.banco.ler(
            "SELECT * FROM objetivos WHERE estado='ativo' "
            "AND ((acordar_em IS NOT NULL AND acordar_em<=?) OR evento_recebido IS NOT NULL) "
            "AND (dono_lock IS NULL OR lock_ate<?) ORDER BY COALESCE(acordar_em, 0), id",
            (agora, agora))
        return [_objetivo(l) for l in linhas]

    # ── criação e edição ───────────────────────────────────────────────────

    def criar(self, titulo, pedido_original="", proxima_acao="", prazo=None,
              estado_json=None, taint=(), acordar_em=None, acordar_por=None,
              teto_passos_dia=TETO_PASSOS_DIA, teto_usd_dia=TETO_USD_DIA) -> int:
        """Cria um objetivo ativo. Sem `acordar_em` nem `acordar_por`, já nasce devido."""
        if not str(titulo).strip():
            raise ValueError("Objetivo precisa de título.")
        agora = self.banco.agora()
        if acordar_em is None and acordar_por is None:
            acordar_em = agora
        with self.banco.transacao() as db:
            objetivo_id = db.execute(
                "INSERT INTO objetivos (titulo,pedido_original,dono,estado,proxima_acao,prazo,"
                "estado_json,taint,acordar_em,acordar_por,dia_dos_passos,teto_passos_dia,"
                "teto_usd_dia,criado_em,atualizado_em) "
                "VALUES (?,?,'nicolas','ativo',?,?,?,?,?,?,?,?,?,?,?)",
                (str(titulo).strip(), pedido_original, proxima_acao, prazo,
                 json_canonico(estado_json or {}), json_canonico(sorted(set(taint))),
                 acordar_em, acordar_por, self.banco.dia(agora), int(teto_passos_dia),
                 float(teto_usd_dia), agora, agora)).lastrowid
            self.trilha.registrar("objetivo", objetivo_id=objetivo_id, alvo=titulo,
                                  resultado="criado", ts=agora)
            for fonte in sorted(set(taint)):
                self.trilha.registrar("taint", objetivo_id=objetivo_id, alvo=fonte,
                                      resultado="nasceu com conteúdo externo", ts=agora)
            return objetivo_id

    def atualizar(self, objetivo_id, **campos):
        desconhecidos = set(campos) - CAMPOS_EDITAVEIS
        if desconhecidos:
            # Estado, evidência, taint e contadores têm caminho próprio, com regra.
            raise ValueError(f"Campos não editáveis por aqui: {', '.join(sorted(desconhecidos))}")
        if not campos:
            return self.obter(objetivo_id, com_passos=False)
        if "estado_json" in campos:
            campos["estado_json"] = json_canonico(campos["estado_json"] or {})
        with self.banco.transacao() as db:
            self._linha(db, objetivo_id)
            nomes = sorted(campos)
            db.execute(f"UPDATE objetivos SET {', '.join(f'{n}=?' for n in nomes)}, atualizado_em=? "
                       "WHERE id=?", (*[campos[n] for n in nomes], self.banco.agora(), int(objetivo_id)))
        return self.obter(objetivo_id, com_passos=False)

    def adicionar_taint(self, objetivo_id, fonte):
        """Une uma fonte externa ao taint do objetivo. Taint só cresce."""
        with self.banco.transacao() as db:
            linha = self._linha(db, objetivo_id)
            atual = set(json.loads(linha["taint"] or "[]"))
            if fonte in atual:
                return sorted(atual)
            atual.add(fonte)
            db.execute("UPDATE objetivos SET taint=?, atualizado_em=? WHERE id=?",
                       (json_canonico(sorted(atual)), self.banco.agora(), int(objetivo_id)))
            self.trilha.registrar("taint", objetivo_id=objetivo_id, alvo=fonte,
                                  resultado="conteúdo externo entrou no objetivo")
            return sorted(atual)

    # ── estados ────────────────────────────────────────────────────────────

    def mudar_estado(self, objetivo_id, novo, motivo=""):
        if novo not in ESTADOS:
            raise ValueError(f"Estado desconhecido: {novo}")
        if novo == "concluido":
            raise TransicaoInvalida("Para concluir, use concluir(id, evidencia).")
        with self.banco.transacao() as db:
            linha = self._linha(db, objetivo_id)
            atual = linha["estado"]
            if atual == novo:
                return _objetivo(linha)
            if novo not in TRANSICOES[atual]:
                raise TransicaoInvalida(f"Objetivo {objetivo_id}: {atual} não vai para {novo}.")
            agora = self.banco.agora()
            db.execute("UPDATE objetivos SET estado=?, motivo=?, atualizado_em=? WHERE id=?",
                       (novo, motivo, agora, int(objetivo_id)))
            if novo == "ativo":
                # Voltar a ativo é decisão nova: zera a contagem de rodadas
                # vazias (senão rebloqueia no primeiro tick) e acorda já.
                db.execute("UPDATE objetivos SET sem_progresso=0, "
                           "acordar_em=COALESCE(acordar_em, ?) WHERE id=?", (agora, int(objetivo_id)))
            elif novo == "abandonado":
                db.execute("UPDATE objetivos SET dono_lock=NULL, lock_ate=NULL, acordar_em=NULL, "
                           "acordar_por=NULL, evento_recebido=NULL WHERE id=?", (int(objetivo_id),))
            self.trilha.registrar("objetivo", objetivo_id=objetivo_id, alvo=linha["titulo"],
                                  resultado=f"{atual} -> {novo}" + (f": {motivo}" if motivo else ""),
                                  ts=agora)
            return _objetivo(self._linha(db, objetivo_id))

    def bloquear(self, objetivo_id, motivo):
        """Atalho para o chamador que recebeu um veredito de bloqueio da guarda."""
        if not str(motivo).strip():
            raise ValueError("Bloqueio precisa de motivo.")
        with self.banco.transacao():
            self.trilha.registrar("laco", objetivo_id=objetivo_id, resultado=motivo)
            return self.mudar_estado(objetivo_id, "bloqueado", motivo)

    def concluir(self, objetivo_id, evidencia):
        if evidencia is None or (isinstance(evidencia, str) and not evidencia.strip()) \
                or (isinstance(evidencia, (dict, list, tuple)) and not evidencia):
            raise ValueError("Concluir exige evidência: o que mostra que ficou feito.")
        texto = evidencia.strip() if isinstance(evidencia, str) else json_canonico(evidencia)
        with self.banco.transacao() as db:
            linha = self._linha(db, objetivo_id)
            if linha["estado"] in ("concluido", "abandonado"):
                raise TransicaoInvalida(f"Objetivo {objetivo_id} já está {linha['estado']}.")
            agora = self.banco.agora()
            db.execute("UPDATE objetivos SET estado='concluido', evidencia=?, motivo='', "
                       "dono_lock=NULL, lock_ate=NULL, acordar_em=NULL, acordar_por=NULL, "
                       "evento_recebido=NULL, atualizado_em=? WHERE id=?",
                       (texto, agora, int(objetivo_id)))
            self.trilha.registrar("objetivo", objetivo_id=objetivo_id, alvo=linha["titulo"],
                                  resultado=f"{linha['estado']} -> concluido: {texto}", ts=agora)
            return _objetivo(self._linha(db, objetivo_id))

    def acordar_por_evento(self, evento) -> list:
        """Marca o evento como recebido nos objetivos que o esperavam; devolve os ids.

        Quem esperava Nicolas (`aguardando_nicolas`) volta a ativo: a resposta
        dele, seja sim ou não, é o que o objetivo precisava para seguir.
        """
        with self.banco.transacao() as db:
            linhas = db.execute("SELECT id, estado, titulo FROM objetivos WHERE acordar_por=? "
                                "AND estado IN ('ativo','aguardando_nicolas')", (evento,)).fetchall()
            agora = self.banco.agora()
            for linha in linhas:
                db.execute("UPDATE objetivos SET evento_recebido=?, acordar_por=NULL, "
                           "atualizado_em=? WHERE id=?", (evento, agora, linha["id"]))
                if linha["estado"] == "aguardando_nicolas":
                    self.mudar_estado(linha["id"], "ativo", f"evento {evento}")
            return [linha["id"] for linha in linhas]

    # ── trava de execução ──────────────────────────────────────────────────

    def travar(self, objetivo_id, dono, duracao_s=None) -> bool:
        """Pega a trava do objetivo; True só para um dono por vez.

        O UPDATE condicional é a trava: duas threads ou dois processos podem
        tentar ao mesmo tempo, o SQLite serializa, e só um vê rowcount 1.
        """
        agora = self.banco.agora()
        ate = agora + float(duracao_s if duracao_s is not None else self.lock_zumbi_s)
        with self.banco.transacao() as db:
            return db.execute(
                "UPDATE objetivos SET dono_lock=?, lock_ate=? WHERE id=? "
                "AND (dono_lock IS NULL OR lock_ate<? OR dono_lock=?)",
                (dono, ate, int(objetivo_id), agora, dono)).rowcount == 1

    def liberar(self, objetivo_id, dono, acordar_em=None, acordar_por=None) -> bool:
        """Solta a trava e agenda o próximo despertar; o evento recebido é consumido aqui."""
        with self.banco.transacao() as db:
            return db.execute(
                "UPDATE objetivos SET dono_lock=NULL, lock_ate=NULL, evento_recebido=NULL, "
                "acordar_em=?, acordar_por=COALESCE(?, acordar_por), atualizado_em=? "
                "WHERE id=? AND dono_lock=?",
                (acordar_em, acordar_por, self.banco.agora(), int(objetivo_id), dono)).rowcount == 1

    # ── passos ─────────────────────────────────────────────────────────────

    def adicionar_passo(self, objetivo_id, acao, args=None, descricao="", desfazer=None) -> int:
        args = args or {}
        with self.banco.transacao() as db:
            self._linha(db, objetivo_id)
            ordem = db.execute("SELECT COALESCE(MAX(ordem), 0) + 1 FROM passos WHERE objetivo_id=?",
                               (int(objetivo_id),)).fetchone()[0]
            return db.execute(
                "INSERT INTO passos (objetivo_id,ordem,descricao,acao,args_json,args_hash,"
                "desfazer_json,criado_em) VALUES (?,?,?,?,?,?,?,?)",
                (int(objetivo_id), ordem, descricao, acao, json_canonico(args),
                 args_hash(acao, args), json_canonico(desfazer) if desfazer is not None else None,
                 self.banco.agora())).lastrowid

    def iniciar_passo(self, passo_id) -> bool:
        """pendente/aguardando -> executando. Conta no teto diário do objetivo."""
        with self.banco.transacao() as db:
            passo = db.execute("SELECT * FROM passos WHERE id=?", (int(passo_id),)).fetchone()
            if passo is None:
                raise KeyError(f"Passo {passo_id} não existe.")
            mudou = db.execute("UPDATE passos SET estado='executando', tentativas=tentativas+1 "
                               "WHERE id=? AND estado IN ('pendente','aguardando')",
                               (int(passo_id),)).rowcount
            if not mudou:
                return False
            agora = self.banco.agora()
            self._virar_dia(db, self._linha(db, passo["objetivo_id"]), agora)
            db.execute("UPDATE objetivos SET passos_hoje=passos_hoje+1, atualizado_em=? WHERE id=?",
                       (agora, passo["objetivo_id"]))
            return True

    def terminar_passo(self, passo_id, estado, resultado="", verificacao=None,
                       custo_usd=0.0, desfazer=None, nivel=None) -> bool:
        """executando -> feito/falhou/aguardando, somando custo e registrando na trilha."""
        if estado not in ("feito", "falhou", "aguardando"):
            raise ValueError(f"Estado final de passo inválido: {estado}")
        custo = max(0.0, float(custo_usd or 0.0))
        with self.banco.transacao() as db:
            passo = db.execute("SELECT * FROM passos WHERE id=?", (int(passo_id),)).fetchone()
            if passo is None:
                raise KeyError(f"Passo {passo_id} não existe.")
            agora = self.banco.agora()
            desfazer_json = json_canonico(desfazer) if desfazer is not None else passo["desfazer_json"]
            mudou = db.execute(
                "UPDATE passos SET estado=?, resultado=?, verificacao=?, custo_usd=custo_usd+?, "
                "desfazer_json=?, terminado_em=? WHERE id=? AND estado='executando'",
                (estado, cortar(resultado, 8000), cortar(verificacao, 2000), custo,
                 desfazer_json, agora if estado != "aguardando" else None, int(passo_id))).rowcount
            if not mudou:
                return False
            self._virar_dia(db, self._linha(db, passo["objetivo_id"]), agora)
            db.execute("UPDATE objetivos SET custo_usd_total=custo_usd_total+?, "
                       "custo_usd_hoje=custo_usd_hoje+?, atualizado_em=? WHERE id=?",
                       (custo, custo, agora, passo["objetivo_id"]))
            if estado != "aguardando":
                self.trilha.registrar(
                    "execucao" if estado == "feito" else "falha", objetivo_id=passo["objetivo_id"],
                    acao=passo["acao"], alvo=passo["descricao"] or None, resultado=resultado,
                    custo_usd=custo, nivel=nivel,
                    desfazer=json.loads(desfazer_json) if desfazer_json else None, ts=agora)
            return True

    def recuperar_passos_interrompidos(self) -> int:
        """Após reinício: passo que estava executando tem resultado incerto.

        Não repete sozinho (o efeito pode já ter acontecido, como na fila de
        entregas); fica `aguardando` com a marca, para quem retomar decidir.
        """
        with self.banco.transacao() as db:
            return db.execute("UPDATE passos SET estado='aguardando', "
                              "verificacao='incerto: processo interrompido durante a execução' "
                              "WHERE estado='executando'").rowcount

    # ── guarda contra laço ─────────────────────────────────────────────────

    def avaliar_passo(self, objetivo_id, acao, args=None) -> Veredito:
        """Pode este passo rodar agora? Bloqueia teto, repetição e ping-pong.

        Mudar o objetivo para bloqueado é decisão de quem chamou (use
        `bloquear`); aqui só se decide se este passo roda.
        """
        identidade = args_hash(acao, args or {})
        with self.banco.transacao() as db:
            linha = self._linha(db, objetivo_id)
            linha = self._virar_dia(db, linha, self.banco.agora())
            if linha["estado"] != "ativo":
                return Veredito("bloquear", f"objetivo está {linha['estado']}, não ativo")
            if linha["passos_hoje"] >= linha["teto_passos_dia"]:
                return Veredito("bloquear", f"teto de {linha['teto_passos_dia']} passos por dia atingido")
            if linha["custo_usd_hoje"] >= linha["teto_usd_dia"]:
                return Veredito("bloquear", f"teto de US$ {linha['teto_usd_dia']:.2f} por dia atingido")
            repetidas = db.execute(
                "SELECT COUNT(*) FROM passos WHERE objetivo_id=? AND args_hash=? "
                "AND estado IN ('feito','falhou')", (int(objetivo_id), identidade)).fetchone()[0]
            if repetidas >= MAX_REPETICOES:
                return Veredito("bloquear", f"{acao} com os mesmos argumentos já rodou {repetidas} vezes")
            anteriores = [r[0] for r in db.execute(
                "SELECT args_hash FROM passos WHERE objetivo_id=? ORDER BY ordem DESC LIMIT ?",
                (int(objetivo_id), JANELA_DE_LACO - 1))]
            sequencia = list(reversed(anteriores)) + [identidade]
            if len(sequencia) == JANELA_DE_LACO:
                for periodo in (2, 3):
                    if _periodico(sequencia, periodo) and len(set(sequencia)) > 1:
                        return Veredito("bloquear", f"laço: padrão de período {periodo} "
                                                    f"nas últimas {JANELA_DE_LACO} ações")
            return PERMITIR

    def registrar_progresso(self, objetivo_id, houve_progresso: bool) -> str:
        """Conta rodadas sem avanço; na terceira seguida, bloqueia o objetivo. Devolve o estado."""
        with self.banco.transacao() as db:
            linha = self._linha(db, objetivo_id)
            if houve_progresso:
                db.execute("UPDATE objetivos SET sem_progresso=0, atualizado_em=? WHERE id=?",
                           (self.banco.agora(), int(objetivo_id)))
                return linha["estado"]
            vazias = linha["sem_progresso"] + 1
            db.execute("UPDATE objetivos SET sem_progresso=?, atualizado_em=? WHERE id=?",
                       (vazias, self.banco.agora(), int(objetivo_id)))
            if vazias >= SEM_PROGRESSO_MAXIMO and linha["estado"] in TRANSICOES and \
                    "bloqueado" in TRANSICOES[linha["estado"]]:
                return self.bloquear(objetivo_id, f"{vazias} rodadas seguidas sem progresso")["estado"]
            return linha["estado"]
