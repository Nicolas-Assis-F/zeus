"""Canal Telegram por long polling, apenas com a biblioteca padrão.

Mensagens válidas ficam no disco antes de avançar o offset. Saídas têm estados
próprios: um envio sem confirmação fica incerto e exige decisão explícita.
Só a conversa configurada é aceita como entrada do sistema.

O token nunca aparece em log. Ele vive na configuração, fora do Git.
"""

from ..llm import transporte_http
from ..entregas import NaoEnviado
from ..store import agora_utc, texto_de

CHAVE_OFFSET = "telegram_offset"


class ErroDeCanal(RuntimeError):
    pass


class RecusaDoCanal(ErroDeCanal, NaoEnviado):
    pass


class CanalTelegram:
    nome = "telegram"

    def __init__(self, token: str, chat_id: str, store=None, transporte=None,
                 espera: int = 25):
        if not token or not chat_id:
            raise ErroDeCanal("Telegram exige token e chat_id configurados.")
        self.token = token
        self.chat_id = str(chat_id)
        self.store = store
        self.transporte = transporte or transporte_http
        self.espera = espera

    def _url(self, metodo: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{metodo}"

    def _chamar(self, metodo: str, corpo=None, timeout=None):
        try:
            dados = self.transporte("POST" if corpo is not None else "GET",
                                    self._url(metodo), corpo, None,
                                    timeout or (self.espera + 15))
        except Exception:
            # O transporte inclui a URL no erro e a URL do Telegram contém o
            # token. A fronteira do canal remove esse detalhe antes dos logs.
            raise ErroDeCanal(f"Falha de comunicação com Telegram em {metodo}.") from None
        if not dados.get("ok", False):
            raise RecusaDoCanal(f"Telegram recusou {metodo}: {dados.get('description', 'sem motivo')}")
        return dados.get("result")

    def verificar(self) -> str:
        eu = self._chamar("getMe", timeout=20) or {}
        return eu.get("username", "desconhecido")

    def digitando(self):
        """Mostra "digitando..." enquanto o modelo gera.

        Não acelera nada, mas separa "pensando" de "travado", que a 9,8 tokens
        por segundo é a diferença entre esperar e desistir. Uma falha aqui é
        irrelevante e não pode derrubar a resposta."""
        try:
            self._chamar("sendChatAction", {"chat_id": self.chat_id, "action": "typing"},
                         timeout=10)
        except Exception:
            pass

    def enviar(self, texto: str):
        resposta = self._chamar("sendMessage", {"chat_id": self.chat_id, "text": texto}, timeout=30)
        return {"message_id": resposta.get("message_id")} if isinstance(resposta, dict) else None

    def _offset(self):
        if self.store is None:
            return None
        bruto = self.store.kv_get(CHAVE_OFFSET)
        return int(bruto) if bruto else None

    def _pendentes(self):
        if self.store is None:
            return []
        return [dict(r) for r in self.store.connection.execute(
            "SELECT id,texto FROM entradas WHERE situacao='pendente' ORDER BY id LIMIT 32")]

    def receber(self, espera: int = None):
        # O offset confirma posse durável, não resposta humana ou entrega de saída.
        pendentes = self._pendentes()
        if pendentes:
            return pendentes
        corpo = {"timeout": self.espera if espera is None else espera,
                 "allowed_updates": ["message"]}
        offset = self._offset()
        if offset is not None:
            corpo["offset"] = offset
        mensagens, maior = [], offset or 0
        for atualizacao in self._chamar("getUpdates", corpo) or []:
            identificador = atualizacao.get("update_id")
            if not isinstance(identificador, int):
                continue
            if offset is not None and identificador < offset:
                continue
            maior = max(maior, identificador + 1)
            mensagem = atualizacao.get("message") or {}
            chat = str((mensagem.get("chat") or {}).get("id", ""))
            texto = mensagem.get("text", "")
            if chat == self.chat_id and isinstance(texto, str) and texto.strip():
                mensagens.append({"id": identificador, "texto": texto})
        if self.store is None:
            return mensagens
        db = self.store.connection
        with db:
            for m in mensagens:
                db.execute("INSERT OR IGNORE INTO entradas (id,texto,recebida_em) VALUES (?,?,?)",
                           (m['id'], m['texto'], texto_de(agora_utc())))
            # Só avançar depois que todas as mensagens válidas estão no disco.
            if maior:
                db.execute("INSERT INTO kv (chave,valor) VALUES (?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                           (CHAVE_OFFSET, str(maior)))
        return self._pendentes()

    def confirmar(self, identificador):
        if self.store is None or identificador is None:
            return
        with self.store.connection:
            self.store.connection.execute("UPDATE entradas SET situacao='respondida' WHERE id=? AND situacao='pendente'", (identificador,))
        atual = self._offset() or 0
        if identificador + 1 > atual:
            self.store.kv_set(CHAVE_OFFSET, identificador + 1)
