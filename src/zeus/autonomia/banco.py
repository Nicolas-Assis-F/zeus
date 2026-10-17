"""Banco próprio da autonomia: um arquivo SQLite fora do `store.py`.

A autonomia guarda objetivos, aprovações, trilha e feedback num arquivo só
dela (`~/.local/state/zeus/autonomia.db`). O banco da conversa não muda: se
esta camada der problema, apagar o arquivo devolve o Zeus ao que era, sem
migração nenhuma no banco principal.

Uma conexão compartilhada entre threads, protegida por uma trava reentrante.
Toda escrita passa por `transacao()`, que abre `BEGIN IMMEDIATE`: a trava de
escrita do SQLite é pega no começo, e não no primeiro UPDATE. Isso serializa
também processos diferentes no mesmo arquivo (o serviço e um comando de
terminal, por exemplo), porque WAL deixa ler enquanto um escreve, mas só um
escreve por vez.

O relógio é injetável e devolve epoch em float. Comparar instantes como
número evita o erro do agendador do OpenJarvis, que comparava ISO como texto e
quebrava com o fuso -03:00. O "dia" dos contadores é o dia LOCAL de Nicolas,
calculado com o fuso injetado.
"""

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CAMINHO_PADRAO = Path("~/.local/state/zeus/autonomia.db")
VERSAO_DO_ESQUEMA = 1


def fuso_padrao():
    """America/Sao_Paulo; sem a base de fusos na máquina, UTC-3 fixo.

    O Brasil não tem horário de verão desde 2019, então o UTC-3 fixo só erra
    se a regra mudar de novo, e aí a base de fusos estará instalada.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Sao_Paulo")
    except Exception:
        return timezone(timedelta(hours=-3), "UTC-3")


def dia_local(instante: float, fuso) -> str:
    return datetime.fromtimestamp(instante, fuso).date().isoformat()


def limites_do_dia(dia, fuso) -> tuple:
    """Epoch do início do dia local e do início do dia seguinte."""
    if isinstance(dia, str):
        dia = date.fromisoformat(dia)
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=fuso)
    # O fim sai da data seguinte, e não de "início + 24 h": em dia de mudança
    # de horário o dia local não tem 24 horas.
    seguinte = dia + timedelta(days=1)
    fim = datetime(seguinte.year, seguinte.month, seguinte.day, tzinfo=fuso)
    return inicio.timestamp(), fim.timestamp()


def json_canonico(valor) -> str:
    """JSON estável: mesma entrada, mesmos bytes. Base dos hashes."""
    return json.dumps(valor, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def args_hash(acao: str, args) -> str:
    """Identidade de uma chamada: nome da ação mais argumentos canônicos.

    É o que a guarda compara para achar repetição e o que amarra uma
    aprovação ao payload exato que Nicolas viu.
    """
    texto = f"{acao}\n{json_canonico(args if args is not None else {})}"
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def cortar(texto, limite=500):
    if texto is None:
        return None
    if not isinstance(texto, str):
        texto = json_canonico(texto)
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


ESQUEMA = """
CREATE TABLE IF NOT EXISTS objetivos (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    pedido_original TEXT NOT NULL DEFAULT '',
    dono TEXT NOT NULL DEFAULT 'nicolas',
    estado TEXT NOT NULL DEFAULT 'ativo',
    motivo TEXT NOT NULL DEFAULT '',
    proxima_acao TEXT NOT NULL DEFAULT '',
    prazo REAL,
    evidencia TEXT,
    estado_json TEXT NOT NULL DEFAULT '{}',
    taint TEXT NOT NULL DEFAULT '[]',
    acordar_em REAL,
    acordar_por TEXT,
    evento_recebido TEXT,
    passos_hoje INTEGER NOT NULL DEFAULT 0,
    dia_dos_passos TEXT NOT NULL DEFAULT '',
    sem_progresso INTEGER NOT NULL DEFAULT 0,
    custo_usd_total REAL NOT NULL DEFAULT 0,
    custo_usd_hoje REAL NOT NULL DEFAULT 0,
    teto_passos_dia INTEGER NOT NULL DEFAULT 30,
    teto_usd_dia REAL NOT NULL DEFAULT 1.0,
    dono_lock TEXT,
    lock_ate REAL,
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS objetivos_estado ON objetivos (estado, acordar_em);
CREATE INDEX IF NOT EXISTS objetivos_evento ON objetivos (acordar_por);

CREATE TABLE IF NOT EXISTS passos (
    id INTEGER PRIMARY KEY,
    objetivo_id INTEGER NOT NULL REFERENCES objetivos(id),
    ordem INTEGER NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    acao TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '{}',
    args_hash TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendente',
    tentativas INTEGER NOT NULL DEFAULT 0,
    resultado TEXT,
    verificacao TEXT,
    desfazer_json TEXT,
    custo_usd REAL NOT NULL DEFAULT 0,
    criado_em REAL NOT NULL,
    terminado_em REAL,
    UNIQUE (objetivo_id, ordem)
);
CREATE INDEX IF NOT EXISTS passos_hash ON passos (objetivo_id, args_hash);

CREATE TABLE IF NOT EXISTS aprovacoes (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL,
    acao TEXT NOT NULL,
    alvo TEXT NOT NULL,
    args_json TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    porque TEXT NOT NULL DEFAULT '',
    objetivo_id INTEGER REFERENCES objetivos(id),
    origem TEXT NOT NULL DEFAULT 'nicolas',
    nivel INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendente',
    criada_em REAL NOT NULL,
    expira_em REAL NOT NULL,
    decidida_em REAL,
    decidida_por TEXT,
    canal_da_decisao TEXT,
    consumida_em REAL
);
CREATE INDEX IF NOT EXISTS aprovacoes_codigo ON aprovacoes (codigo, estado);
CREATE INDEX IF NOT EXISTS aprovacoes_estado ON aprovacoes (estado, expira_em);

CREATE TABLE IF NOT EXISTS trilha (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    tipo TEXT NOT NULL,
    objetivo_id INTEGER,
    acao TEXT,
    alvo TEXT,
    resultado TEXT,
    custo_usd REAL NOT NULL DEFAULT 0,
    nivel INTEGER,
    desfazer_json TEXT,
    desfeito_em REAL,
    prev_hash TEXT NOT NULL DEFAULT '',
    row_hash TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS trilha_ts ON trilha (ts);
CREATE INDEX IF NOT EXISTS trilha_objetivo ON trilha (objetivo_id, ts);

CREATE TABLE IF NOT EXISTS feedback (
    chave_do_aviso TEXT PRIMARY KEY,
    util INTEGER NOT NULL DEFAULT 0,
    nao_precisava INTEGER NOT NULL DEFAULT 0,
    mais_tarde INTEGER NOT NULL DEFAULT 0,
    atualizado REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_eventos (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    chave_do_aviso TEXT NOT NULL,
    tipo TEXT NOT NULL,
    canal TEXT,
    desfeito_em REAL
);
"""


class Banco:
    """Conexão, relógio e fuso compartilhados pelas partes da autonomia."""

    def __init__(self, caminho=None, relogio=None, fuso=None):
        self.caminho = Path(caminho).expanduser() if caminho else CAMINHO_PADRAO.expanduser()
        self.relogio = relogio or time.time
        self.fuso = fuso or fuso_padrao()
        self._trava = threading.RLock()
        self._profundidade = 0
        novo = not self.caminho.exists()
        self.caminho.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # check_same_thread=False é seguro aqui porque nenhum acesso à conexão
        # acontece fora de `self._trava`.
        self.conexao = sqlite3.connect(str(self.caminho), timeout=30,
                                       isolation_level=None, check_same_thread=False)
        self.conexao.row_factory = sqlite3.Row
        if novo:
            try:
                self.caminho.chmod(0o600)
            except OSError:
                pass
        with self._trava:
            self.conexao.execute("PRAGMA journal_mode=WAL")
            self.conexao.execute("PRAGMA foreign_keys=ON")
            self.conexao.execute("PRAGMA busy_timeout=30000")
            # executescript faz COMMIT implícito; por isso roda fora de transação.
            self.conexao.executescript(ESQUEMA)
            self.conexao.execute(f"PRAGMA user_version={VERSAO_DO_ESQUEMA}")

    def agora(self) -> float:
        return float(self.relogio())

    def dia(self, instante=None) -> str:
        return dia_local(self.agora() if instante is None else instante, self.fuso)

    @contextmanager
    def transacao(self):
        """BEGIN IMMEDIATE no nível de fora; níveis de dentro reaproveitam.

        Os métodos públicos chamam uns aos outros (mudar estado registra na
        trilha, decidir aprovação acorda objetivo). Tudo entra na mesma
        transação: ou a mudança e o registro dela ficam, ou nenhum fica.
        """
        with self._trava:
            if self._profundidade:
                self._profundidade += 1
                try:
                    yield self.conexao
                finally:
                    self._profundidade -= 1
                return
            self.conexao.execute("BEGIN IMMEDIATE")
            self._profundidade = 1
            try:
                yield self.conexao
            except BaseException:
                self._profundidade = 0
                self.conexao.execute("ROLLBACK")
                raise
            self._profundidade = 0
            self.conexao.execute("COMMIT")

    def ler(self, sql, parametros=()):
        with self._trava:
            return [dict(linha) for linha in self.conexao.execute(sql, parametros)]

    def ler_um(self, sql, parametros=()):
        with self._trava:
            linha = self.conexao.execute(sql, parametros).fetchone()
            return dict(linha) if linha else None

    def fechar(self):
        with self._trava:
            self.conexao.close()
