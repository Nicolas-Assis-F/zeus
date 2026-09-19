"""Canal Telegram por long polling, apenas com a biblioteca padrão.

Duas garantias importam aqui. A primeira é o offset persistido: depois de um
reinício, o Zeus não reprocessa mensagem antiga e não responde duas vezes. A
segunda é o filtro de conversa: só a conversa configurada é aceita, então uma
mensagem de terceiro não vira entrada do sistema.

O token nunca aparece em log. Ele vive na configuração, fora do Git.
"""

from ..llm import transporte_http

CHAVE_OFFSET = "telegram_offset"


class ErroDeCanal(RuntimeError):
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
        dados = self.transporte("POST" if corpo is not None else "GET",
                                self._url(metodo), corpo, None,
                                timeout or (self.espera + 15))
        if not dados.get("ok", False):
            raise ErroDeCanal(f"Telegram recusou {metodo}: {dados.get('description', 'sem motivo')}")
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
        self._chamar("sendMessage", {"chat_id": self.chat_id, "text": texto}, timeout=30)

    def _offset(self):
        if self.store is None:
            return None
        bruto = self.store.kv_get(CHAVE_OFFSET)
        return int(bruto) if bruto else None

    def receber(self, espera: int = None):
        corpo = {"timeout": self.espera if espera is None else espera,
                 "allowed_updates": ["message"]}
        offset = self._offset()
        if offset is not None:
            corpo["offset"] = offset
        mensagens = []
        for atualizacao in self._chamar("getUpdates", corpo) or []:
            mensagem = atualizacao.get("message") or {}
            chat = str((mensagem.get("chat") or {}).get("id", ""))
            texto = mensagem.get("text", "")
            if chat != self.chat_id or not texto:
                # Conversa não autorizada ou conteúdo sem texto: descartada,
                # mas o offset avança para não travar a fila.
                self.confirmar(atualizacao.get("update_id"))
                continue
            mensagens.append({"id": atualizacao.get("update_id"), "texto": texto})
        return mensagens

    def confirmar(self, identificador):
        if self.store is None or identificador is None:
            return
        atual = self._offset() or 0
        if identificador + 1 > atual:
            self.store.kv_set(CHAVE_OFFSET, identificador + 1)
