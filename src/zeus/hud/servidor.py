"""HUD do Zeus: uma página servida pelo próprio processo, sem dependência.

O X99 roda sem monitor. A interface vive no navegador de qualquer máquina da
rede, o que também resolve o problema de "ver" o Zeus sem instalar nada. O
transporte é SSE: o navegador abre um fluxo e o servidor empurra estado,
mensagem e áudio. É menos poderoso que WebSocket e dispensa implementar
protocolo à mão, o que mantém a promessa de biblioteca padrão.

Segurança: a chave é obrigatória. Sem ela, qualquer um na mesma rede
conversaria com a memória de Nicolas. A comparação é de tempo constante e a
página só recebe a chave que já estava na URL que ele abriu.
"""

import hmac
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGINA = Path(__file__).resolve().parent / "index.html"
LIMITE_DE_MENSAGEM = 4000


class ServidorHUD:
    def __init__(self, enfileirar, voz=None, chave: str = "",
                 host: str = "0.0.0.0", porta: int = 8770, estado=None):
        if not chave:
            raise ValueError("A HUD exige uma chave de acesso.")
        self.enfileirar = enfileirar    # callable(texto)
        self._retrato = dict(estado or {"tipo": "estado"})
        self.voz = voz
        self.chave = chave
        self.host = host
        self.porta = porta
        self.assinantes = []
        self.trava = threading.Lock()
        self._servidor = None
        self._thread = None

    def estado(self) -> dict:
        with self.trava:
            return dict(self._retrato)

    def atualizar(self, retrato: dict, difundir: bool = True):
        """Recebe o retrato pronto de quem é dono do banco.

        A conexão SQLite pertence a uma thread só. Deixar o manipulador HTTP
        consultar o banco quebra o processo no primeiro acesso à página, então
        o laço principal entrega o retrato e a rota devolve o que está em cache."""
        with self.trava:
            self._retrato = dict(retrato)
        if difundir:
            self.publicar(**retrato)

    # ------------------------------------------------------------- difusão
    def publicar(self, tipo: str = "estado", **campos):
        pacote = json.dumps({"tipo": tipo, **campos}, ensure_ascii=False)
        with self.trava:
            alvos = list(self.assinantes)
        for fila in alvos:
            try:
                fila.put_nowait(pacote)
            except queue.Full:
                pass

    def _assinar(self):
        fila = queue.Queue(maxsize=64)
        with self.trava:
            self.assinantes.append(fila)
        return fila

    def _cancelar(self, fila):
        with self.trava:
            if fila in self.assinantes:
                self.assinantes.remove(fila)

    def autorizado(self, chave: str) -> bool:
        return bool(chave) and hmac.compare_digest(str(chave), self.chave)

    # ------------------------------------------------------------ operação
    def iniciar(self):
        servidor = ThreadingHTTPServer((self.host, self.porta), _construir(self))
        servidor.daemon_threads = True
        self._servidor = servidor
        self._thread = threading.Thread(target=servidor.serve_forever, daemon=True)
        self._thread.start()
        return servidor.server_address[1]

    def parar(self):
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
            self._servidor = None


def _construir(hud: ServidorHUD):
    class Manipulador(BaseHTTPRequestHandler):
        server_version = "Zeus"
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass  # o log do Zeus é o fluxo de eventos, não o do http.server

        # ---------------------------------------------------------- apoio
        def _chave(self):
            consulta = parse_qs(urlparse(self.path).query)
            return (self.headers.get("X-Zeus-Chave")
                    or (consulta.get("chave") or [""])[0])

        def _responder(self, codigo, corpo=b"", tipo="application/json; charset=utf-8"):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if corpo:
                self.wfile.write(corpo)

        def _json(self, codigo, dados):
            self._responder(codigo, json.dumps(dados, ensure_ascii=False).encode("utf-8"))

        # ----------------------------------------------------------- rotas
        def do_GET(self):
            caminho = urlparse(self.path).path
            if caminho in ("/", "/index.html"):
                # A página em si não é segredo: ela só pede a chave e, sem uma
                # chave válida, nenhuma rota de dado responde.
                corpo = PAGINA.read_bytes()
                return self._responder(200, corpo, "text/html; charset=utf-8")
            if caminho == "/favicon.ico":
                # O navegador pede sozinho; negar com 401 só suja o console.
                return self._responder(204, b"", "image/x-icon")
            if not hud.autorizado(self._chave()):
                return self._json(401, {"erro": "chave inválida"})
            if caminho == "/estado":
                return self._json(200, hud.estado())
            if caminho == "/fluxo":
                return self._fluxo()
            if caminho.startswith("/audio/"):
                return self._audio(caminho.rsplit("/", 1)[-1])
            return self._json(404, {"erro": "rota desconhecida"})

        def do_POST(self):
            caminho = urlparse(self.path).path
            if not hud.autorizado(self._chave()):
                return self._json(401, {"erro": "chave inválida"})
            if caminho != "/mensagem":
                return self._json(404, {"erro": "rota desconhecida"})
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho > LIMITE_DE_MENSAGEM:
                return self._json(413, {"erro": "mensagem longa demais"})
            try:
                dados = json.loads(self.rfile.read(tamanho) or b"{}")
                texto = str(dados.get("texto", "")).strip()
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"erro": "corpo inválido"})
            if not texto:
                return self._json(400, {"erro": "mensagem vazia"})
            hud.enfileirar(texto[:LIMITE_DE_MENSAGEM])
            return self._json(202, {"recebido": True})

        def _fluxo(self):
            fila = hud._assinar()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                self.wfile.write(b": conectado\n\n")
                self.wfile.flush()
                while True:
                    try:
                        pacote = fila.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": pulso\n\n")  # mantém a conexão viva
                        self.wfile.flush()
                        continue
                    self.wfile.write(b"data: " + pacote.encode("utf-8") + b"\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hud._cancelar(fila)

        def _audio(self, nome):
            if hud.voz is None or not nome.endswith(".wav"):
                return self._json(404, {"erro": "sem áudio"})
            arquivo = (hud.voz.destino / nome).resolve()
            if arquivo.parent != hud.voz.destino.resolve() or not arquivo.exists():
                return self._json(404, {"erro": "sem áudio"})
            return self._responder(200, arquivo.read_bytes(), "audio/wav")

    return Manipulador
