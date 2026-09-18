"""Memória persistente do Zeus, separada do código versionado.

Camadas desta entrega: fatos (com estado epistêmico), turnos de conversa,
episódios com seus eventos, fila de perguntas e agenda. O esquema evolui por
migrações numeradas; nenhuma migração apaga dado do usuário.

Regra dura herdada do escopo: a memória narrativa não guarda valor financeiro.
O bloqueio vive em `guarda.py` e é aplicado onde o risco existe, que é a
escrita feita pelo modelo.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ESTADOS = ("confirmado", "hipotese", "observacao")

MIGRACOES = [
    # 1 — fundação original, preservada.
    """
    CREATE TABLE IF NOT EXISTS facts (
        key TEXT PRIMARY KEY, value TEXT NOT NULL,
        source TEXT NOT NULL, updated_at TEXT NOT NULL);
    """,
    # 2 — camadas de presença.
    """
    ALTER TABLE facts ADD COLUMN estado TEXT NOT NULL DEFAULT 'confirmado';
    ALTER TABLE facts ADD COLUMN validade TEXT;

    CREATE TABLE IF NOT EXISTS turnos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        em TEXT NOT NULL, canal TEXT NOT NULL,
        papel TEXT NOT NULL, texto TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS episodios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL, resumo TEXT NOT NULL,
        aberto_em TEXT NOT NULL, fechado_em TEXT, resultado TEXT,
        simulado INTEGER NOT NULL DEFAULT 0);

    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episodio INTEGER REFERENCES episodios(id),
        em TEXT NOT NULL, origem TEXT NOT NULL,
        tipo TEXT NOT NULL, dados TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS perguntas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        texto TEXT NOT NULL, motivo TEXT NOT NULL,
        episodio INTEGER REFERENCES episodios(id),
        situacao TEXT NOT NULL DEFAULT 'agendada',
        criada_em TEXT NOT NULL, vence_em TEXT NOT NULL,
        perguntada_em TEXT, respondida_em TEXT, resposta TEXT);

    CREATE TABLE IF NOT EXISTS agenda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL, texto TEXT NOT NULL,
        vence_em TEXT NOT NULL, situacao TEXT NOT NULL DEFAULT 'pendente',
        concluida_em TEXT);

    CREATE TABLE IF NOT EXISTS envios (
        chave TEXT PRIMARY KEY, em TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS kv (
        chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
    """,
]


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def texto_de(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).isoformat()


class Store:
    def __init__(self, directory: Path):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "zeus.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.path.chmod(0o600)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrar()

    def _migrar(self):
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (versao INTEGER NOT NULL)"
        )
        linha = self.connection.execute("SELECT versao FROM schema_version").fetchone()
        atual = linha["versao"] if linha else 0
        if not linha:
            self.connection.execute("INSERT INTO schema_version VALUES (0)")
        for indice, script in enumerate(MIGRACOES, start=1):
            if indice <= atual:
                continue
            self.connection.executescript(script)
            self.connection.execute("UPDATE schema_version SET versao=?", (indice,))
        self.connection.commit()

    def close(self):
        self.connection.close()

    # ---------------------------------------------------------------- fatos
    def remember(self, key: str, value: str, source: str = "user",
                 estado: str = "confirmado", validade: str = None):
        if not str(key).strip() or not str(value).strip() or not str(source).strip():
            raise ValueError("Chave, valor e origem precisam estar preenchidos.")
        if estado not in ESTADOS:
            raise ValueError("Estado precisa ser confirmado, hipotese ou observacao.")
        now = texto_de(agora_utc())
        with self.connection:
            self.connection.execute(
                "INSERT INTO facts (key, value, source, updated_at, estado, validade) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "source=excluded.source, updated_at=excluded.updated_at, "
                "estado=excluded.estado, validade=excluded.validade",
                (key, value, source, now, estado, validade),
            )

    def recall(self, key: str):
        linha = self.connection.execute(
            "SELECT value, source, updated_at, estado, validade FROM facts WHERE key=?",
            (key,),
        ).fetchone()
        return dict(linha) if linha else None

    def forget(self, key: str) -> bool:
        with self.connection:
            resultado = self.connection.execute("DELETE FROM facts WHERE key=?", (key,))
        return resultado.rowcount > 0

    def fatos(self, estado: str = None):
        if estado:
            linhas = self.connection.execute(
                "SELECT key, value, source, estado, updated_at FROM facts "
                "WHERE estado=? ORDER BY key", (estado,)).fetchall()
        else:
            linhas = self.connection.execute(
                "SELECT key, value, source, estado, updated_at FROM facts "
                "ORDER BY key").fetchall()
        return [dict(linha) for linha in linhas]

    # --------------------------------------------------------------- turnos
    def registrar_turno(self, canal: str, papel: str, texto: str, em: datetime = None):
        with self.connection:
            self.connection.execute(
                "INSERT INTO turnos (em, canal, papel, texto) VALUES (?, ?, ?, ?)",
                (texto_de(em or agora_utc()), canal, papel, texto),
            )

    def turnos(self, limite: int = 12):
        linhas = self.connection.execute(
            "SELECT em, canal, papel, texto FROM turnos ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
        return [dict(linha) for linha in reversed(linhas)]

    # ------------------------------------------------------------ episódios
    def abrir_episodio(self, tipo: str, resumo: str, simulado: bool = False,
                       em: datetime = None) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO episodios (tipo, resumo, aberto_em, simulado) "
                "VALUES (?, ?, ?, ?)",
                (tipo, resumo, texto_de(em or agora_utc()), 1 if simulado else 0),
            )
        return cursor.lastrowid

    def registrar_evento(self, episodio, origem: str, tipo: str, dados: dict = None,
                         em: datetime = None):
        with self.connection:
            self.connection.execute(
                "INSERT INTO eventos (episodio, em, origem, tipo, dados) "
                "VALUES (?, ?, ?, ?, ?)",
                (episodio, texto_de(em or agora_utc()), origem, tipo,
                 json.dumps(dados or {}, ensure_ascii=False)),
            )

    def fechar_episodio(self, episodio: int, resultado: str, em: datetime = None):
        with self.connection:
            self.connection.execute(
                "UPDATE episodios SET fechado_em=?, resultado=? WHERE id=?",
                (texto_de(em or agora_utc()), resultado, episodio),
            )

    def episodios_abertos(self):
        linhas = self.connection.execute(
            "SELECT id, tipo, resumo, aberto_em, simulado FROM episodios "
            "WHERE fechado_em IS NULL ORDER BY id").fetchall()
        return [dict(linha) for linha in linhas]

    # ------------------------------------------------------------ perguntas
    def criar_pergunta(self, texto: str, motivo: str, vence_em: datetime,
                       episodio: int = None, em: datetime = None) -> int:
        if not texto.strip() or not motivo.strip():
            raise ValueError("Pergunta precisa de texto e motivo.")
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO perguntas (texto, motivo, episodio, criada_em, vence_em) "
                "VALUES (?, ?, ?, ?, ?)",
                (texto, motivo, episodio, texto_de(em or agora_utc()),
                 texto_de(vence_em)),
            )
        return cursor.lastrowid

    def perguntas_vencidas(self, agora: datetime):
        linhas = self.connection.execute(
            "SELECT id, texto, motivo, episodio, vence_em FROM perguntas "
            "WHERE situacao='agendada' AND vence_em<=? ORDER BY vence_em",
            (texto_de(agora),)).fetchall()
        return [dict(linha) for linha in linhas]

    def perguntas_abertas(self):
        linhas = self.connection.execute(
            "SELECT id, texto, motivo, situacao, vence_em FROM perguntas "
            "WHERE situacao IN ('agendada', 'perguntada') ORDER BY vence_em").fetchall()
        return [dict(linha) for linha in linhas]

    def marcar_perguntada(self, identificador: int, em: datetime = None):
        with self.connection:
            self.connection.execute(
                "UPDATE perguntas SET situacao='perguntada', perguntada_em=? "
                "WHERE id=? AND situacao='agendada'",
                (texto_de(em or agora_utc()), identificador))

    def responder_pergunta(self, identificador: int, resposta: str, em: datetime = None) -> bool:
        with self.connection:
            resultado = self.connection.execute(
                "UPDATE perguntas SET situacao='respondida', resposta=?, respondida_em=? "
                "WHERE id=? AND situacao IN ('agendada', 'perguntada')",
                (resposta, texto_de(em or agora_utc()), identificador))
        return resultado.rowcount > 0

    def cancelar_pergunta(self, identificador: int) -> bool:
        with self.connection:
            resultado = self.connection.execute(
                "UPDATE perguntas SET situacao='cancelada' WHERE id=? "
                "AND situacao IN ('agendada', 'perguntada')", (identificador,))
        return resultado.rowcount > 0

    # --------------------------------------------------------------- agenda
    def agendar(self, tipo: str, texto: str, vence_em: datetime) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO agenda (tipo, texto, vence_em) VALUES (?, ?, ?)",
                (tipo, texto, texto_de(vence_em)))
        return cursor.lastrowid

    def agenda_vencida(self, agora: datetime):
        linhas = self.connection.execute(
            "SELECT id, tipo, texto, vence_em FROM agenda "
            "WHERE situacao='pendente' AND vence_em<=? ORDER BY vence_em",
            (texto_de(agora),)).fetchall()
        return [dict(linha) for linha in linhas]

    def agenda_pendente(self):
        linhas = self.connection.execute(
            "SELECT id, tipo, texto, vence_em FROM agenda WHERE situacao='pendente' "
            "ORDER BY vence_em").fetchall()
        return [dict(linha) for linha in linhas]

    def concluir_agenda(self, identificador: int, em: datetime = None):
        with self.connection:
            self.connection.execute(
                "UPDATE agenda SET situacao='concluida', concluida_em=? WHERE id=?",
                (texto_de(em or agora_utc()), identificador))

    def cancelar_agenda(self, identificador: int) -> bool:
        with self.connection:
            resultado = self.connection.execute(
                "UPDATE agenda SET situacao='cancelada' WHERE id=? AND situacao='pendente'",
                (identificador,))
        return resultado.rowcount > 0

    # --------------------------------------------------------- envios e kv
    def ja_enviado(self, chave: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM envios WHERE chave=?", (chave,)).fetchone() is not None

    def marcar_envio(self, chave: str, em: datetime = None) -> bool:
        """Retorna False quando a chave já existia: é o freio do aviso duplicado."""
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO envios (chave, em) VALUES (?, ?)",
                    (chave, texto_de(em or agora_utc())))
            return True
        except sqlite3.IntegrityError:
            return False

    def desmarcar_envio(self, chave: str):
        """Usado quando o envio falhou: a pendência volta a valer."""
        with self.connection:
            self.connection.execute("DELETE FROM envios WHERE chave=?", (chave,))

    def kv_get(self, chave: str, padrao=None):
        linha = self.connection.execute(
            "SELECT valor FROM kv WHERE chave=?", (chave,)).fetchone()
        return linha["valor"] if linha else padrao

    def kv_set(self, chave: str, valor: str):
        with self.connection:
            self.connection.execute(
                "INSERT INTO kv (chave, valor) VALUES (?, ?) "
                "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                (chave, str(valor)))
