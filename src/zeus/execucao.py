"""Trabalho de rede e síntese fora da thread que possui a memória do Zeus."""

import queue
from threading import Event, Lock, Thread


class CaixaDeEntrada(queue.Queue):
    """Enfileirar também acorda o laço, sem esperar o intervalo da agenda."""
    def __init__(self, maxsize=32):
        super().__init__(maxsize=maxsize)
        self.acordar = Event()

    def put(self, item, block=True, timeout=None):
        super().put(item, block, timeout)
        self.acordar.set()

    def aguardar(self, timeout):
        self.acordar.clear()
        if self.empty():
            self.acordar.wait(timeout)


class RecepcaoTelegram:
    """Uma conexão SQLite própria na thread de polling, confirmação no núcleo.

    Só busca o lote seguinte depois que o núcleo terminou o anterior. Assim
    uma consulta rápida não repete mensagens que ainda aguardam resposta.
    """
    def __init__(self, criar_canal, entrada, parado):
        self.criar_canal, self.entrada, self.parado = criar_canal, entrada, parado
        self.thread = Thread(target=self._rodar, daemon=True, name="zeus-telegram")

    def iniciar(self):
        self.thread.start()

    def _entregar(self, pacote):
        while not self.parado.is_set():
            try:
                self.entrada.put(pacote, timeout=0.25)
                return True
            except queue.Full:
                continue
        return False

    def _rodar(self):
        canal = None
        try:
            canal = self.criar_canal()
            while not self.parado.is_set():
                try:
                    mensagens = canal.receber()
                    if not mensagens:
                        self.parado.wait(0.1)
                        continue
                    terminado = Event()
                    if not self._entregar({"tipo": "telegram", "mensagens": mensagens,
                                           "terminado": terminado}):
                        break
                    while not self.parado.is_set() and not terminado.wait(0.25):
                        pass
                except Exception:
                    self.parado.wait(2)
        finally:
            if canal is not None and canal.store is not None:
                canal.store.close()


class FalaEmSegundoPlano:
    """Publica WAV depois do texto; descarta fala ultrapassada por novo turno."""
    def __init__(self, voz, publicar):
        self.voz, self.publicar = voz, publicar
        self._trava = Lock()
        self._acordar = Event()
        self._parado = Event()
        self._geracao = 0
        self._pendente = None
        self.thread = Thread(target=self._rodar, daemon=True, name="zeus-voz")
        self.thread.start()

    def invalidar(self):
        with self._trava:
            self._geracao += 1
            self._pendente = None
            return self._geracao

    def falar(self, texto, geracao):
        with self._trava:
            if geracao == self._geracao and not self._parado.is_set():
                self._pendente = (texto, geracao)
                self._acordar.set()

    def _rodar(self):
        while not self._parado.is_set():
            self._acordar.wait(0.25)
            with self._trava:
                self._acordar.clear()
                pedido, self._pendente = self._pendente, None
            if pedido is None:
                continue
            texto, geracao = pedido
            try:
                arquivo = self.voz.falar(texto)
                with self._trava:
                    if arquivo and geracao == self._geracao and not self._parado.is_set():
                        self.publicar("audio", audio=f"/audio/{arquivo.name}", geracao=geracao)
            except Exception:
                # Texto já foi entregue; falha opcional não mata o próximo áudio.
                continue

    def parar(self):
        self._parado.set()
        self.invalidar()
        self._acordar.set()
        self.thread.join(timeout=0.5)
