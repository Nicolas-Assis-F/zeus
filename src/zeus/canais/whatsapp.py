"""WhatsApp por duas pontes `whatsapp-bridge` locais, apenas com a biblioteca padrão.

Cada ponte é um "aparelho conectado" de um número e grava tudo que chega num
SQLite próprio. O Zeus nunca fala com o WhatsApp direto: ele lê esse banco em
modo somente leitura e, quando precisa mandar algo, pede à ponte pela API local.

- Ponte B, do número do Zeus, é o canal de conversa: só o grupo configurado,
  e só os remetentes autorizados, contam como entrada.
- Ponte A, do número principal de Nicolas, é só leitura. Nesta entrega o Zeus
  não tem como mandar nada por ela: `LeituraDaPonte` não sabe enviar.

O banco da ponte é a entrada durável: uma mensagem que chegou com o Zeus
desligado continua lá quando ele volta. O cursor no `kv` diz até onde já foi
lido, e a tabela `entradas` guarda o que ainda aguarda resposta, como no
Telegram. Nenhuma tabela nova.
"""

import hashlib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..store import texto_de
from .telegram import ErroDeCanal, RecusaDoCanal

# Identificadores do Telegram são inteiros de até 32 bits. Os do WhatsApp são
# texto; o canal os converte num inteiro estável a partir de 2^40, para que a
# mesma mensagem caia sempre na mesma linha de `entradas` sem colidir com o
# Telegram, mesmo depois de a ponte regravar a mensagem com outro rowid.
BASE_DE_IDS = 1 << 40
MIDIAS = {"image": "imagem", "audio": "áudio", "video": "vídeo",
          "document": "documento", "sticker": "figurinha"}


# Prefixo do pedido que veio por áudio: a resposta volta também em áudio (#68).
MARCA_AUDIO_DE_NICOLAS = "[áudio de Nicolas, transcrito]"


def lista(valor) -> tuple:
    """Aceita lista do JSON ou texto separado por vírgula vindo do ambiente."""
    if not valor:
        return ()
    if isinstance(valor, str):
        valor = valor.split(",")
    return tuple(str(v).strip() for v in valor if str(v).strip())


def id_estavel(chat: str, mensagem: str) -> int:
    resumo = hashlib.sha256(f"{chat}\0{mensagem}".encode("utf-8")).digest()
    return BASE_DE_IDS + int.from_bytes(resumo[:7], "big")


def instante(bruto) -> datetime:
    """A ponte grava `2026-10-16 10:40:29-03:00`, às vezes com nanossegundos."""
    texto = re.sub(r"(\.\d{6})\d+", r"\1", str(bruto or "").strip())
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def texto_da_mensagem(linha) -> str:
    conteudo = (linha["content"] or "").strip()
    midia = MIDIAS.get(linha["media_type"] or "", linha["media_type"] or "")
    if midia and conteudo:
        return f"[{midia}] {conteudo}"
    if midia:
        return f"[{midia} sem legenda]"
    return conteudo


def extras_da_midia(linha) -> dict:
    """Tipo cru, nome do arquivo e legenda: o que `midia.py` precisa para ler."""
    return {"tipo_midia": linha["media_type"] or "", "arquivo": linha["filename"] or "",
            "legenda": (linha["content"] or "").strip()}


class LeituraDaPonte:
    """Lê o banco de uma ponte sem nunca escrever nele."""

    def __init__(self, banco: str):
        if not banco:
            raise ErroDeCanal("A ponte do WhatsApp exige o caminho do banco de mensagens.")
        self.banco = banco

    def _abrir(self):
        try:
            conexao = sqlite3.connect(f"file:{self.banco}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error as erro:
            raise ErroDeCanal(f"Não consegui abrir o banco da ponte: {erro}") from None
        conexao.row_factory = sqlite3.Row
        return conexao

    def novas(self, depois_de: int, chats=(), desde: datetime = None, limite: int = 200):
        """Mensagens recebidas (não as que este número mandou), em ordem de chegada."""
        filtros, parametros = ["rowid > ?", "is_from_me = 0"], [int(depois_de)]
        if chats:
            filtros.append("chat_jid IN (%s)" % ",".join("?" for _ in chats))
            parametros.extend(chats)
        sql = ("SELECT rowid AS linha, id, chat_jid, sender, content, timestamp, media_type, filename "
               "FROM messages WHERE " + " AND ".join(filtros) + " ORDER BY rowid LIMIT ?")
        parametros.append(limite)
        conexao = self._abrir()
        try:
            linhas = conexao.execute(sql, parametros).fetchall()
        except sqlite3.Error as erro:
            raise ErroDeCanal(f"O banco da ponte não respondeu: {erro}") from None
        finally:
            conexao.close()
        mensagens = []
        for linha in linhas:
            em = instante(linha["timestamp"])
            item = {"linha": linha["linha"], "id": linha["id"], "chat": linha["chat_jid"],
                    "remetente": linha["sender"] or "", "texto": texto_da_mensagem(linha),
                    "midia": bool(linha["media_type"]), **extras_da_midia(linha), "em": em, "antiga": bool(desde and em < desde)}
            mensagens.append(item)
        return mensagens

    def ultimas(self, chat: str, limite: int = 8):
        """As últimas mensagens recebidas numa conversa, da mais velha à mais nova."""
        conexao = self._abrir()
        try:
            linhas = conexao.execute(
                "SELECT rowid AS linha, id, chat_jid, sender, content, timestamp, media_type, filename "
                "FROM messages WHERE chat_jid=? AND is_from_me=0 ORDER BY timestamp DESC, rowid DESC "
                "LIMIT ?", (chat, int(limite))).fetchall()
        except sqlite3.Error as erro:
            raise ErroDeCanal(f"O banco da ponte não respondeu: {erro}") from None
        finally:
            conexao.close()
        mensagens = []
        for linha in reversed(linhas):
            texto = texto_da_mensagem(linha)
            if texto:
                mensagens.append({"linha": linha["linha"], "id": linha["id"], "chat": linha["chat_jid"],
                                  "remetente": linha["sender"] or "", "texto": texto,
                                  "midia": bool(linha["media_type"]), **extras_da_midia(linha),
                                  "em": instante(linha["timestamp"]),
                                  "antiga": False})
        return mensagens

    def conversa(self, chats, limite: int = 10):
        """As últimas mensagens de uma conversa nos dois sentidos, da mais velha à
        mais nova. `meu` diz se saiu deste número."""
        chats = tuple(chats)
        if not chats:
            return []
        conexao = self._abrir()
        try:
            linhas = conexao.execute(
                "SELECT rowid AS linha, id, chat_jid, sender, content, timestamp, media_type, filename, "
                "is_from_me FROM messages WHERE chat_jid IN (%s) "
                "ORDER BY timestamp DESC, rowid DESC LIMIT ?" % ",".join("?" for _ in chats),
                chats + (int(limite),)).fetchall()
        except sqlite3.Error as erro:
            raise ErroDeCanal(f"O banco da ponte não respondeu: {erro}") from None
        finally:
            conexao.close()
        return [{"id": l["id"], "chat": l["chat_jid"], "texto": texto_da_mensagem(l) or "(vazia)",
                 "midia": bool(l["media_type"]), **extras_da_midia(l), "em": instante(l["timestamp"]),
                 "meu": bool(l["is_from_me"])} for l in reversed(linhas)]

    def midia(self, mensagem: str, chat: str = ""):
        """Os dados de uma mensagem com mídia, para baixar e ler. None se não há."""
        sql = ("SELECT id, chat_jid, content, media_type, filename, file_length FROM messages "
               "WHERE id=? AND media_type != ''")
        parametros = [mensagem]
        if chat:
            sql += " AND chat_jid=?"
            parametros.append(chat)
        conexao = self._abrir()
        try:
            linha = conexao.execute(sql + " ORDER BY rowid DESC LIMIT 1", parametros).fetchone()
        except sqlite3.Error as erro:
            raise ErroDeCanal(f"O banco da ponte não respondeu: {erro}") from None
        finally:
            conexao.close()
        if linha is None:
            return None
        return {"id": linha["id"], "chat": linha["chat_jid"], "tipo": linha["media_type"],
                "arquivo": linha["filename"] or "", "legenda": (linha["content"] or "").strip(),
                "tamanho": int(linha["file_length"] or 0)}

    def ultima_linha(self) -> int:
        conexao = self._abrir()
        try:
            return int(conexao.execute("SELECT COALESCE(MAX(rowid), 0) FROM messages").fetchone()[0])
        finally:
            conexao.close()

    def conversas(self, limite: int = 30):
        """Para configurar: quais conversas existem, com nome e último remetente."""
        conexao = self._abrir()
        try:
            chats = conexao.execute(
                "SELECT jid, name, last_message_time FROM chats "
                "ORDER BY last_message_time DESC LIMIT ?", (limite,)).fetchall()
            resultado = []
            for chat in chats:
                remetentes = [r[0] for r in conexao.execute(
                    "SELECT DISTINCT sender FROM messages WHERE chat_jid=? AND is_from_me=0 "
                    "ORDER BY rowid DESC LIMIT 5", (chat["jid"],))]
                resultado.append({"jid": chat["jid"], "nome": chat["name"] or "",
                                  "ultima": str(chat["last_message_time"] or ""),
                                  "remetentes": remetentes})
            return resultado
        finally:
            conexao.close()


def transporte_da_ponte(url: str, corpo: dict, timeout: int = 30):
    """POST na ponte. Devolve (status, json). Erro de conexão sobe como OSError."""
    dados = json.dumps(corpo).encode("utf-8")
    pedido = urllib.request.Request(url, data=dados, method="POST")
    pedido.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            return resposta.status, json.loads(resposta.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as erro:
        bruto = erro.read().decode("utf-8", "replace")
        try:
            return erro.code, json.loads(bruto or "{}")
        except ValueError:
            return erro.code, {"message": bruto[:200]}


class CanalWhatsApp:
    """Conversa com Nicolas num grupo, pelo número do Zeus.

    Mesmo contrato do `CanalTelegram`: `receber` devolve o que aguarda resposta,
    `confirmar` encerra, `enviar` entrega. Mensagem de qualquer outro grupo ou
    de remetente fora da lista não entra no sistema.
    """

    nome = "whatsapp"
    CURSOR = "whatsapp_cursor"

    def __init__(self, ponte_url: str, banco: str, grupo: str, remetentes,
                 store=None, transporte=None, intervalo: float = 2.0, midia=None):
        remetentes = lista(remetentes)
        if not ponte_url or not grupo or not remetentes:
            raise ErroDeCanal("WhatsApp exige ponte, grupo e ao menos um remetente autorizado.")
        self.ponte_url = ponte_url.rstrip("/")
        self.leitura = LeituraDaPonte(banco)
        self.grupo = grupo
        self.remetentes = set(remetentes)
        self.store = store
        self.transporte = transporte or transporte_da_ponte
        self.intervalo = intervalo
        self.midia = midia

    def verificar(self) -> str:
        self.leitura.ultima_linha()
        # Sem o grupo: ele é identificador pessoal e não vai para log.
        return f"ponte em {self.ponte_url}, banco legível"

    def digitando(self):
        # A ponte não expõe "digitando". Fica mudo em vez de fingir.
        pass

    def enviar(self, texto: str):
        return self._postar({"message": texto})

    def enviar_arquivo(self, caminho: str, legenda: str = ""):
        """Um arquivo (o PDF do orçamento) para o grupo. O destinatário não é
        parâmetro: nada escrito na conversa consegue mandar o arquivo a outro."""
        return self._postar({"message": legenda, "media_path": str(caminho)})

    def _postar(self, corpo: dict):
        try:
            status, dados = self.transporte(self.ponte_url + "/api/send",
                                            {**corpo, "recipient": self.grupo})
        except (ConnectionRefusedError, urllib.error.URLError) as erro:
            motivo = getattr(erro, "reason", erro)
            if isinstance(motivo, ConnectionRefusedError):
                # Ponte desligada: a mensagem com certeza não saiu.
                raise RecusaDoCanal("Ponte do WhatsApp fora do ar.") from None
            raise ErroDeCanal("Falha de comunicação com a ponte do WhatsApp.") from None
        except Exception:
            raise ErroDeCanal("Falha de comunicação com a ponte do WhatsApp.") from None
        if status == 400:
            raise RecusaDoCanal(f"A ponte recusou o envio: {dados.get('message', 'sem motivo')}")
        if not dados.get("success"):
            # A ponte tentou e falhou. Pode ter saído do aparelho sem
            # confirmação do servidor: é incerto, não "não enviado".
            raise ErroDeCanal(f"A ponte não confirmou o envio: {dados.get('message', 'sem motivo')}")
        return {"destino": "whatsapp", "detalhe": dados.get("message", "")}

    def _cursor(self):
        if self.store is None:
            return None
        bruto = self.store.kv_get(self.CURSOR)
        return int(bruto) if bruto else None

    def _pendentes(self):
        if self.store is None:
            return []
        return [dict(r) for r in self.store.connection.execute(
            "SELECT id,texto FROM entradas WHERE situacao='pendente' AND id>=? "
            "ORDER BY recebida_em, id LIMIT 32", (BASE_DE_IDS,))]

    def receber(self, espera: float = None):
        if self.store is None:
            raise ErroDeCanal("Receber pelo WhatsApp exige a memória para guardar o cursor.")
        pendentes = self._pendentes()
        if pendentes:
            return pendentes
        cursor = self._cursor()
        if cursor is None:
            # Primeira vez: o que já estava no grupo é passado, não pedido.
            self.store.kv_set(self.CURSOR, self.leitura.ultima_linha())
            return []
        novas = self.leitura.novas(cursor, chats=(self.grupo,))
        validas = []
        for m in novas:
            if m["remetente"] not in self.remetentes:
                continue
            if not m["midia"]:
                if m["texto"]:
                    validas.append(m)
            elif self.midia is not None:
                # Sem leitor de mídia, o Zeus responderia a "[áudio sem
                # legenda]" como se fosse texto: aí a mídia fica de fora.
                validas.append(dict(m, texto=self._texto_da_midia(m)))
        if not novas:
            time.sleep(self.intervalo if espera is None else espera)
            return []
        maior = max(m["linha"] for m in novas)
        db = self.store.connection
        with db:
            for m in validas:
                # A hora da própria mensagem mantém a ordem dentro do lote.
                db.execute("INSERT OR IGNORE INTO entradas (id,texto,recebida_em) VALUES (?,?,?)",
                           (id_estavel(m["chat"], m["id"]), m["texto"], texto_de(m["em"])))
            # Só avançar depois que todas as mensagens válidas estão no disco.
            db.execute("INSERT INTO kv (chave,valor) VALUES (?,?) ON CONFLICT(chave) "
                       "DO UPDATE SET valor=excluded.valor", (self.CURSOR, str(maior)))
        return self._pendentes()

    def _texto_da_midia(self, m) -> str:
        """O áudio de Nicolas é a voz dele: vira o pedido. Documento, foto e
        vídeo podem trazer texto de terceiro, então ficam como marcador e são
        lidos por `ler_midia`, que marca o resultado como externo."""
        from ..midia import MidiaIndisponivel, marcador
        if m.get("tipo_midia") != "audio":
            return marcador(m, "grupo")
        try:
            return MARCA_AUDIO_DE_NICOLAS + " " + self.midia.ler("grupo", m["id"], m["chat"])["texto"]
        except MidiaIndisponivel as erro:
            return f"[Nicolas mandou um áudio que não consegui transcrever: {erro}]"

    def confirmar(self, identificador):
        if self.store is None or identificador is None:
            return
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE entradas SET situacao='respondida' WHERE id=? AND situacao='pendente'",
                (identificador,))
