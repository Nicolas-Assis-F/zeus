"""HUD do Zeus: uma página servida pelo próprio processo, sem dependência.

O X99 roda sem monitor. A interface vive no navegador de qualquer máquina da
rede, o que também resolve o problema de "ver" o Zeus sem instalar nada. O
transporte é SSE: o navegador abre um fluxo e o servidor empurra estado,
mensagem e áudio. É menos poderoso que WebSocket e dispensa implementar
protocolo à mão, o que mantém a promessa de biblioteca padrão.

Segurança: sem sessão, nenhuma rota de dado responde. A chave (`chave_hud`)
ou, na falta dela, um código de pareamento de uso único é enviado uma vez por
POST e trocado por um cookie HttpOnly e SameSite=Strict. A chave nunca viaja
na URL — URL fica em histórico, favorito e log — e nunca é impressa no log do
serviço. Tentativas erradas têm limite por endereço e no total.
"""

import hashlib
import hmac
import http.cookies
import json
import os
import queue
import re
import time
from collections import OrderedDict, deque
import shutil
import socket
import ssl
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ..mapa import MapaIndisponivel
from ..saude import Saude

PAGINA = Path(__file__).resolve().parent / "index.html"
# Arquivos estáticos da interface: só o que está nesta pasta, só .js e .css,
# só nomes simples. Nenhum caminho vindo da URL chega ao disco sem passar aqui.
ESTATICO = Path(__file__).resolve().parent / "estatico"
NOME_ESTATICO = re.compile(r"^[a-z0-9][a-z0-9-]*\.(js|css)$")
TIPO_ESTATICO = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}
ID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
HISTORICO_DE_EVENTOS = 1500
TURNOS_LEMBRADOS = 80

# Etapa publicada pelo núcleo -> estado da mensagem na interface. HTTP 202 é
# "aceita"; processada é outra coisa, e só o núcleo diz quando.
ESTADO_DA_ETAPA = {
    "em_fila": "em_fila", "transcrevendo": "processando",
    "montando_contexto": "processando", "consultando_modelo": "processando",
    "escrevendo": "processando", "executando_ferramenta": "processando",
    "sintetizando_voz": "processando", "concluida": "concluida",
    "falhou": "falhou", "interrompida": "interrompida",
}
ACOES_DE_PENDENCIA = {
    "pergunta": {"cancelar"}, "lembrete": {"cancelar"},
    "entrega": {"confirmar", "reenviar", "descartar"},
    "entrada": {"reprocessar", "descartar"},
}


def arquivos_estaticos():
    """Nomes servíveis, para a rota e para quem testa a página."""
    if not ESTATICO.is_dir():
        return []
    return sorted(a.name for a in ESTATICO.iterdir() if NOME_ESTATICO.match(a.name))


class _Assinante:
    """Uma conexão SSE. Fila cheia não bloqueia ninguém: marca que perdeu, e a
    próxima escrita manda ressincronizar em vez de fingir que nada faltou."""

    def __init__(self):
        self.fila = queue.Queue(maxsize=256)
        self.perdeu = False

    def entregar(self, seq, pacote):
        try:
            self.fila.put_nowait((seq, pacote))
        except queue.Full:
            self.perdeu = True
LIMITE_DE_MENSAGEM = 4000
LIMITE_DE_AUDIO = 12 * 1024 * 1024

COOKIE = "zeus_sessao"
DURACAO_DA_SESSAO = 30 * 24 * 3600
DURACAO_DO_CODIGO = 15 * 60
JANELA_DE_FALHAS = 60
FALHAS_POR_ENDERECO = 5
FALHAS_NO_TOTAL = 30


def _resumo(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def endereco_local() -> str:
    """Descobre o IP que a casa enxerga, sem depender de configuração."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tomada:
            # UDP não envia nada ao conectar: isto só pergunta ao sistema qual
            # interface sairia pela rota padrão, e lê o endereço dela.
            tomada.connect(("8.8.8.8", 80))
            return tomada.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def garantir_certificado(diretorio: Path, ip: str = ""):
    """Gera um certificado próprio quando não existe.

    O navegador só libera o microfone em origem segura. Sem TLS, o botão de
    falar simplesmente não existe fora de localhost, e o Zeus fica sem ouvidos
    justamente no aparelho que tem microfone. O certificado é autoassinado: o
    navegador avisa uma vez, você aceita, e a chave nunca sai da máquina."""
    diretorio = Path(diretorio)
    diretorio.mkdir(parents=True, exist_ok=True, mode=0o700)
    certificado = diretorio / "zeus-cert.pem"
    chave = diretorio / "zeus-chave.pem"
    if certificado.exists() and chave.exists():
        return certificado, chave
    openssl = shutil.which("openssl")
    if not openssl:
        return None, None
    ip = ip or endereco_local()
    try:
        subprocess.run([
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(chave), "-out", str(certificado),
            "-days", "3650", "-subj", "/CN=zeus",
            "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:zeus,DNS:localhost",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True)
    except (subprocess.SubprocessError, OSError):
        return None, None
    chave.chmod(0o600)
    return certificado, chave


class ServidorHUD:
    def __init__(self, enfileirar, voz=None, chave: str = "",
                 host: str = "0.0.0.0", porta: int = 8770, estado=None,
                 pasta_de_escuta=None, certificado=None, chave_tls=None,
                 saude=None, mapa=None, codigo_unico: str = "",
                 arquivo_de_sessoes=None, relogio=None, telemetria=None):
        if not chave and not codigo_unico:
            raise ValueError("A HUD exige uma chave de acesso ou um código de pareamento.")
        self._relogio = relogio or time.time
        self._codigo = codigo_unico or ""
        self._codigo_expira = self._relogio() + DURACAO_DO_CODIGO
        self.arquivo_de_sessoes = Path(arquivo_de_sessoes) if arquivo_de_sessoes else None
        self._sessoes = self._carregar_sessoes()
        self._falhas = {}
        self._falhas_no_total = deque()
        # Sequência de eventos desta subida do servidor. A página guarda o
        # último que viu; na reconexão recebe o que faltou, ou é avisada de
        # que precisa recarregar o estado — nunca completa texto adivinhando.
        self.sessao_servidor = uuid.uuid4().hex[:12]
        self._seq = 0
        self._historico = deque(maxlen=HISTORICO_DE_EVENTOS)
        self._turnos = OrderedDict()
        self.enfileirar = enfileirar    # callable(dict)
        self._retrato = dict(estado or {"tipo": "estado"})
        self.pasta_de_escuta = Path(pasta_de_escuta) if pasta_de_escuta else None
        if self.pasta_de_escuta:
            self.pasta_de_escuta.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.certificado = certificado
        self.chave_tls = chave_tls
        # O painel de saúde lê /proc a cada pedido: é barato e não toca o
        # banco, então pode viver na thread do HTTP sem fila nem cache.
        self.saude = saude if saude is not None else Saude(pasta_de_escuta)
        # O navegador nunca fala com o servidor de telas: ele pede ao Zeus, que
        # busca uma vez e guarda. Assim o mapa funciona sem rede depois da
        # primeira olhada, e só um agente aparece no servidor público.
        self.mapa = mapa
        self.telemetria = telemetria
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
            retrato = dict(self._retrato)
            retrato.update(sessao_servidor=self.sessao_servidor, seq=self._seq,
                           turnos_hud=list(self._turnos.values())[-40:])
            return retrato

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
        with self.trava:
            self._seq += 1
            seq = self._seq
            if tipo == "turno":
                self._atualizar_turno(campos, seq)
            pacote = json.dumps({"tipo": tipo, **campos, "seq": seq,
                                 "sessao": self.sessao_servidor}, ensure_ascii=False)
            self._historico.append((seq, pacote))
            alvos = list(self.assinantes)
        for assinante in alvos:
            assinante.entregar(seq, pacote)

    def _atualizar_turno(self, campos, seq):
        identificador = campos.get("turno")
        if not identificador:
            return
        registro = self._turnos.pop(identificador, None) or {
            "id": identificador, "canal": campos.get("canal"), "origem": campos.get("origem")}
        etapa = campos.get("etapa")
        registro.update(etapa=etapa, estado=ESTADO_DA_ETAPA.get(etapa, registro.get("estado")),
                        detalhe=campos.get("detalhe") or {}, decorrido_ms=campos.get("decorrido_ms"),
                        seq=seq)
        self._turnos[identificador] = registro
        while len(self._turnos) > TURNOS_LEMBRADOS:
            self._turnos.popitem(last=False)

    def turno(self, identificador):
        with self.trava:
            registro = self._turnos.get(identificador)
            return dict(registro) if registro else None

    def desde(self, seq):
        """Eventos depois de `seq`, ou None quando o buraco já saiu do histórico."""
        with self.trava:
            if not self._historico:
                return [] if seq >= self._seq else None
            if seq < self._historico[0][0] - 1:
                return None
            return [(s, p) for s, p in self._historico if s > seq]

    def _assinar(self):
        assinante = _Assinante()
        with self.trava:
            self.assinantes.append(assinante)
        return assinante

    def _cancelar(self, assinante):
        with self.trava:
            if assinante in self.assinantes:
                self.assinantes.remove(assinante)

    def aceitar(self, pedido: dict) -> dict:
        """Registra a mensagem com a identidade do cliente e põe na fila.

        O mesmo id duas vezes é a mesma mensagem: reenviar depois de uma
        queda de rede não duplica. Devolve (código HTTP, corpo)."""
        identificador = pedido["id"]
        with self.trava:
            existente = self._turnos.get(identificador)
        if existente is not None:
            return 200, {"id": identificador, "estado": existente.get("estado"),
                         "duplicada": True}
        self.publicar("turno", turno=identificador, canal="hud", origem=pedido.get("origem"),
                      etapa="em_fila", detalhe={}, decorrido_ms=None)
        try:
            self.enfileirar(pedido)
        except queue.Full:
            self.publicar("turno", turno=identificador, canal="hud", etapa="falhou",
                          detalhe={"motivo": "fila cheia"}, decorrido_ms=None)
            return 503, {"id": identificador, "estado": "falhou",
                         "erro": "fila cheia; tente novamente em instantes"}
        return 202, {"id": identificador, "estado": "em_fila"}

    def autorizado(self, chave: str) -> bool:
        """Chave por cabeçalho, para cliente de linha de comando e testes."""
        return bool(chave) and bool(self.chave) and hmac.compare_digest(str(chave), self.chave)

    # -------------------------------------------------------------- sessão
    def _carregar_sessoes(self):
        if not self.arquivo_de_sessoes or not self.arquivo_de_sessoes.exists():
            return {}
        try:
            dados = json.loads(self.arquivo_de_sessoes.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        agora = self._relogio()
        return {k: v for k, v in dados.items() if isinstance(v, (int, float)) and v > agora}

    def _gravar_sessoes(self):
        """Só o hash do token vai para o disco: o arquivo não abre a HUD."""
        if not self.arquivo_de_sessoes:
            return
        self.arquivo_de_sessoes.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporario = self.arquivo_de_sessoes.with_suffix(".tmp")
        fd = os.open(temporario, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as saida:
            json.dump(self._sessoes, saida)
        os.replace(temporario, self.arquivo_de_sessoes)

    def _limite(self, endereco):
        agora = self._relogio()
        falhas = [t for t in self._falhas.get(endereco, []) if agora - t < JANELA_DE_FALHAS]
        self._falhas[endereco] = falhas
        while self._falhas_no_total and agora - self._falhas_no_total[0] >= JANELA_DE_FALHAS:
            self._falhas_no_total.popleft()
        return len(falhas) >= FALHAS_POR_ENDERECO or len(self._falhas_no_total) >= FALHAS_NO_TOTAL

    def entrar(self, segredo: str, endereco: str):
        """Troca chave ou código de pareamento por uma sessão.

        Devolve ("ok", token), ("negado", None) ou ("limite", segundos)."""
        with self.trava:
            if self._limite(endereco):
                return "limite", JANELA_DE_FALHAS
            agora = self._relogio()
            valido = self.autorizado(segredo)
            if not valido and self._codigo and agora < self._codigo_expira:
                valido = bool(segredo) and hmac.compare_digest(str(segredo), self._codigo)
                if valido:
                    self._codigo = ""       # uso único: o log antigo não abre mais nada
            if not valido:
                self._falhas.setdefault(endereco, []).append(agora)
                self._falhas_no_total.append(agora)
                return "negado", None
            token = secrets_token()
            self._sessoes[_resumo(token)] = agora + DURACAO_DA_SESSAO
            self._sessoes = {k: v for k, v in self._sessoes.items() if v > agora}
            self._gravar_sessoes()
            return "ok", token

    def sessao_valida(self, token: str) -> bool:
        if not token:
            return False
        with self.trava:
            expira = self._sessoes.get(_resumo(token))
            return bool(expira and expira > self._relogio())

    def sair(self, token: str):
        with self.trava:
            if self._sessoes.pop(_resumo(token or ""), None) is not None:
                self._gravar_sessoes()

    # ------------------------------------------------------------ operação
    @property
    def seguro(self) -> bool:
        return bool(self.certificado and self.chave_tls)

    def iniciar(self):
        servidor = ThreadingHTTPServer((self.host, self.porta), _construir(self))
        servidor.daemon_threads = True
        if self.seguro:
            contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            contexto.load_cert_chain(str(self.certificado), str(self.chave_tls))
            servidor.socket = contexto.wrap_socket(servidor.socket, server_side=True)
        self._servidor = servidor
        self._thread = threading.Thread(target=servidor.serve_forever, daemon=True)
        self._thread.start()
        return servidor.server_address[1]

    def parar(self):
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
            self._servidor = None


def secrets_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)


def _construir(hud: ServidorHUD):
    class Manipulador(BaseHTTPRequestHandler):
        server_version = "Zeus"
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass  # o log do Zeus é o fluxo de eventos, não o do http.server

        # ---------------------------------------------------------- apoio
        def _token(self):
            biscoitos = http.cookies.SimpleCookie()
            try:
                biscoitos.load(self.headers.get("Cookie") or "")
            except http.cookies.CookieError:
                return ""
            return biscoitos[COOKIE].value if COOKIE in biscoitos else ""

        def _liberado(self):
            """Sessão por cookie, ou chave por cabeçalho. Nunca por URL."""
            return (hud.sessao_valida(self._token())
                    or hud.autorizado(self.headers.get("X-Zeus-Chave", "")))

        def _origem_ok(self):
            """Mutação vinda de outra origem é recusada. Sem Origin (curl,
            teste), vale a sessão — o cookie SameSite=Strict já não viaja
            em pedido de outro site."""
            origem = self.headers.get("Origin")
            return not origem or urlparse(origem).netloc == (self.headers.get("Host") or "")

        def _biscoito(self, token, duracao):
            partes = [f"{COOKIE}={token}", "Path=/", "HttpOnly", "SameSite=Strict",
                      f"Max-Age={duracao}"]
            if hud.seguro:
                partes.append("Secure")
            return "; ".join(partes)

        def _responder(self, codigo, corpo=b"", tipo="application/json; charset=utf-8",
                       extras=None):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            for nome, valor in (extras or {}).items():
                self.send_header(nome, valor)
            self.end_headers()
            if corpo:
                self.wfile.write(corpo)

        def _json(self, codigo, dados, extras=None):
            self._responder(codigo, json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                            extras=extras)

        def _tamanho(self, limite):
            try:
                tamanho = int(self.headers.get("Content-Length") or 0)
                if tamanho < 0:
                    raise ValueError
            except ValueError:
                self.close_connection = True
                self._json(400, {"erro": "tamanho inválido"})
                return None
            if tamanho > limite:
                self.close_connection = True
                self._json(413, {"erro": "conteúdo longo demais"})
                return None
            return tamanho

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
            if caminho.startswith("/estatico/"):
                return self._estatico(caminho[len("/estatico/"):])
            if caminho == "/sessao":
                return self._json(200, {"autenticado": self._liberado(),
                                        "pareamento": bool(hud._codigo)})
            if not self._liberado():
                return self._json(401, {"erro": "sessão ausente ou vencida"})
            if caminho == "/estado":
                return self._json(200, hud.estado())
            if caminho == "/saude":
                return self._json(200, hud.saude.medir())
            if caminho == "/mapa":
                if hud.mapa is None:
                    return self._json(503, {"erro": "mapa desligado"})
                return self._json(200, {"tipo": "mapa", **hud.mapa.inicio(),
                                        "situacao": hud.mapa.diagnostico(),
                                        "ativo": hud.mapa.disponivel()})
            if caminho.startswith("/mapa/tela/"):
                return self._tela(caminho[len("/mapa/tela/"):])
            if caminho == "/fluxo":
                return self._fluxo()
            if caminho == "/diagnostico":
                if hud.telemetria is None:
                    return self._json(503, {"erro": "telemetria desligada"})
                return self._json(200, {"tipo": "diagnostico",
                                        "turnos": hud.telemetria.recentes("turno", 15),
                                        "voz": hud.telemetria.recentes("voz", 10),
                                        "falhas_de_gravacao": hud.telemetria.falhas,
                                        "gravando": hud.telemetria.gravar})
            if caminho.startswith("/audio/"):
                return self._audio(caminho.rsplit("/", 1)[-1])
            return self._json(404, {"erro": "rota desconhecida"})

        def do_POST(self):
            caminho = urlparse(self.path).path
            if not self._origem_ok():
                return self._json(403, {"erro": "origem não permitida"})
            if caminho == "/sessao":
                return self._entrar()
            if not self._liberado():
                return self._json(401, {"erro": "sessão ausente ou vencida"})
            if caminho == "/sessao/sair":
                hud.sair(self._token())
                return self._json(200, {"saiu": True},
                                  extras={"Set-Cookie": self._biscoito("", 0)})
            if caminho == "/escuta":
                return self._escuta()
            if caminho == "/pendencia":
                return self._pendencia()
            if caminho != "/mensagem":
                return self._json(404, {"erro": "rota desconhecida"})
            tamanho = self._tamanho(LIMITE_DE_MENSAGEM + 512)
            if tamanho is None:
                return
            try:
                dados = json.loads(self.rfile.read(tamanho) or b"{}")
                if not isinstance(dados, dict) or not isinstance(dados.get("texto", ""), str):
                    raise ValueError
                texto = dados.get("texto", "").strip()
                identificador = self._identificador(dados.get("id"))
                responde_a = dados.get("responde_a")
                if responde_a is not None and (isinstance(responde_a, bool)
                                               or not isinstance(responde_a, int)):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"erro": "corpo inválido"})
            if not texto:
                return self._json(400, {"erro": "mensagem vazia"})
            if len(texto) > LIMITE_DE_MENSAGEM:
                return self._json(413, {"erro": "conteúdo longo demais"})
            pedido = {"tipo": "texto", "texto": texto, "id": identificador, "origem": "texto"}
            if responde_a is not None:
                pedido["responde_a"] = responde_a
            return self._json(*hud.aceitar(pedido))

        def _identificador(self, bruto):
            if bruto is None:
                return uuid.uuid4().hex
            if not isinstance(bruto, str) or not ID_VALIDO.match(bruto):
                raise ValueError
            return bruto

        def _pendencia(self):
            tamanho = self._tamanho(1024)
            if tamanho is None:
                return
            try:
                dados = json.loads(self.rfile.read(tamanho) or b"{}")
                tipo, acao, alvo = dados.get("tipo"), dados.get("acao"), dados.get("alvo")
                if acao not in ACOES_DE_PENDENCIA.get(tipo, set()):
                    raise ValueError
                if tipo == "entrega":
                    if not isinstance(alvo, str) or not 0 < len(alvo) <= 200:
                        raise ValueError
                elif isinstance(alvo, bool) or not isinstance(alvo, int):
                    raise ValueError
                identificador = self._identificador(dados.get("id"))
            except (ValueError, UnicodeDecodeError, AttributeError):
                return self._json(400, {"erro": "ação de pendência inválida"})
            try:
                hud.enfileirar({"tipo": "pendencia", "id": identificador, "alvo_tipo": tipo,
                                "alvo": alvo, "acao": acao})
            except queue.Full:
                return self._json(503, {"erro": "fila cheia; tente novamente em instantes"})
            return self._json(202, {"id": identificador, "estado": "em_fila"})

        def _estatico(self, nome):
            if not NOME_ESTATICO.match(nome) or nome not in arquivos_estaticos():
                return self._json(404, {"erro": "arquivo desconhecido"})
            corpo = (ESTATICO / nome).read_bytes()
            return self._responder(200, corpo, TIPO_ESTATICO[nome.rsplit(".", 1)[1]],
                                   extras={"X-Content-Type-Options": "nosniff"})

        def _entrar(self):
            tamanho = self._tamanho(512)
            if tamanho is None:
                return
            try:
                dados = json.loads(self.rfile.read(tamanho) or b"{}")
                segredo = dados.get("chave", "") if isinstance(dados, dict) else ""
                if not isinstance(segredo, str):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"erro": "corpo inválido"})
            resultado, valor = hud.entrar(segredo.strip(), self.client_address[0])
            if resultado == "limite":
                return self._json(429, {"erro": "tentativas demais; espere um minuto"},
                                  extras={"Retry-After": str(valor)})
            if resultado != "ok":
                return self._json(401, {"erro": "chave ou código inválido"})
            return self._json(200, {"autenticado": True},
                              extras={"Set-Cookie": self._biscoito(valor, DURACAO_DA_SESSAO)})

        def _escuta(self):
            if hud.pasta_de_escuta is None:
                return self._json(503, {"erro": "escuta desligada"})
            tamanho = self._tamanho(LIMITE_DE_AUDIO)
            if tamanho is None:
                return
            if tamanho <= 0:
                return self._json(400, {"erro": "áudio vazio"})
            arquivo = hud.pasta_de_escuta / f"{uuid.uuid4().hex}.webm"
            corpo = self.rfile.read(tamanho)
            if len(corpo) != tamanho:
                self.close_connection = True
                return self._json(400, {"erro": "áudio incompleto"})
            try:
                identificador = self._identificador(self.headers.get("X-Zeus-Turno"))
            except ValueError:
                return self._json(400, {"erro": "identificador de turno inválido"})
            arquivo.write_bytes(corpo)
            arquivo.chmod(0o600)
            # A transcrição acontece no laço principal: o modelo de escuta é
            # um só e não deve ser usado por duas threads ao mesmo tempo.
            codigo, resposta = hud.aceitar({"tipo": "audio", "arquivo": str(arquivo),
                                            "id": identificador, "origem": "voz"})
            if codigo != 202:
                arquivo.unlink(missing_ok=True)
            return self._json(codigo, resposta)

        def _fluxo(self):
            """SSE com id em cada evento. Na reconexão o navegador manda o
            último id; se ele ainda está no histórico, o que faltou é
            reenviado; se não, a página é mandada recarregar o estado."""
            assinante = hud._assinar()
            ultimo = self.headers.get("Last-Event-ID", "")
            atraso = None
            if ultimo:
                sessao, _, seq = ultimo.partition(":")
                if sessao == hud.sessao_servidor and seq.isdigit():
                    atraso = hud.desde(int(seq))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            def escrever(seq, pacote):
                self.wfile.write(f"id: {hud.sessao_servidor}:{seq}\n".encode()
                                 + b"data: " + pacote.encode("utf-8") + b"\n\n")

            def ressincronizar():
                self.wfile.write(b"data: " + json.dumps(
                    {"tipo": "ressincronizar", "sessao": hud.sessao_servidor}).encode() + b"\n\n")

            try:
                self.wfile.write(b"retry: 3000\n: conectado\n\n")
                if ultimo and atraso is None:
                    ressincronizar()
                for seq, pacote in atraso or []:
                    escrever(seq, pacote)
                self.wfile.flush()
                while True:
                    try:
                        seq, pacote = assinante.fila.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": pulso\n\n")  # mantém a conexão viva
                        self.wfile.flush()
                        continue
                    if assinante.perdeu:
                        assinante.perdeu = False
                        ressincronizar()
                    escrever(seq, pacote)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hud._cancelar(assinante)

        def _tela(self, resto):
            """/mapa/tela/z/x/y.png — do disco quando a tela já foi vista."""
            if hud.mapa is None:
                return self._json(503, {"erro": "mapa desligado"})
            partes = resto.split("/")
            if len(partes) != 3 or not partes[2].endswith(".png"):
                return self._json(404, {"erro": "endereço de tela inválido"})
            try:
                dados = hud.mapa.tela(partes[0], partes[1], partes[2][:-4])
            except MapaIndisponivel as erro:
                return self._json(502, {"erro": str(erro)})
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(dados)))
            # Uma tela nunca muda para o mesmo z/x/y: o navegador pode guardar.
            self.send_header("Cache-Control", "public, max-age=604800")
            self.end_headers()
            self.wfile.write(dados)

        def _audio(self, nome):
            if hud.voz is None or not nome.endswith(".wav"):
                return self._json(404, {"erro": "sem áudio"})
            arquivo = (hud.voz.destino / nome).resolve()
            if arquivo.parent != hud.voz.destino.resolve() or not arquivo.exists():
                return self._json(404, {"erro": "sem áudio"})
            return self._responder(200, arquivo.read_bytes(), "audio/wav")

    return Manipulador
