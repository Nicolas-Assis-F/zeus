"""Central do Zeus (#84): a interface nova, montada em /central.

A HUD clássica continua em "/". A Central traz o que ela não tinha e o que a
reauditoria da #45 cobrou da HUD v1:

- **Sessão de verdade.** A chave da HUD entra uma vez, por POST, e vira cookie
  `HttpOnly; Secure; SameSite=Strict`. É o único caminho de entrada e tem limite
  de tentativas por IP (A07). Aparelho pareado por QR entra pelo cookie dele.
  Revogar a sessão fecha o fluxo de eventos dela na próxima batida (A08).
- **Eventos com sequência.** Todo evento ganha `seq` sob a mesma trava que
  guarda o buffer de replay. O retrato inicial sai com a marca d'água tirada
  sob essa trava, e o navegador pede só o que veio depois (`Last-Event-ID`).
  Assim nada some entre o retrato e o fluxo (A09). O primeiro pacote de todo
  fluxo é sempre `ola`, com a subida do servidor (A10).
- **Admissão atômica.** Mensagem e áudio vêm com um id do navegador. Reservar o
  id, tentar a fila e consolidar acontecem na mesma seção crítica: o mesmo id
  entra uma vez só (A01). Fila cheia desfaz a reserva e devolve 503 repetível
  (A02). O registro de ids é próprio, com prazo, e não depende do que a tela
  mostra (A03). Durável entre reinícios ele ainda não é; isso é a Z05.
- **Escrita mínima.** POST exige `X-Zeus: 1` e Origin da própria casa (CSRF).
  Quem mexe no banco do Zeus continua sendo o laço principal; a Central só
  enfileira. O banco da autonomia é próprio e seguro entre threads, então a
  Central o lê direto.

Ideias de interface do OpenJarvis (frontend, Apache-2.0) e do Mark-LV (só
ideias); o código é próprio. Ver /srv/zeus-build/06-pesquisa-interface.md.
"""

import hashlib
import hmac
import json
import mimetypes
import queue
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from collections import OrderedDict, deque
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PASTA = Path(__file__).resolve().parent / "central"
COOKIE_SESSAO = "zeus_sessao"
COOKIE_APARELHO = "zeus_aparelho"
SESSAO_S = 12 * 3600
TENTATIVAS = 5
JANELA_TENTATIVAS_S = 15 * 60
REPLAY = 600
ADMISSAO_S = 24 * 3600
ADMISSAO_MAX = 5000
BATIDA_S = 15
LIMITE_DE_MENSAGEM = 4000
LIMITE_DE_AUDIO = 12 * 1024 * 1024
TIPOS_ESTATICOS = {".html", ".css", ".js", ".svg", ".webmanifest", ".png", ".json"}
SERVICOS = ("zeus", "ponte-principal", "ponte-zeus", "zeus-vigia.timer")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Central:
    def __init__(self, hud, autonomia=None, pareamento=None, controles=None,
                 gasto=None, relogio=None, servicos=SERVICOS):
        self.hud = hud
        self.autonomia = autonomia
        self.pareamento = pareamento
        self.controles = controles
        self.gasto = gasto
        self.relogio = relogio or time.time
        self.servicos = servicos
        self.boot = uuid.uuid4().hex[:12]
        self._trava = threading.Lock()
        self._seq = 0
        self._replay = deque(maxlen=REPLAY)
        self._assinantes = {}           # fila -> (tipo_de_sessao, id_da_sessao)
        self._sessoes = {}              # hash do token -> {criada, expira}
        self._tentativas = {}           # ip -> [instantes]
        self._admitidos = OrderedDict()  # id -> {digest, estado, em}
        self._servicos_cache = (0.0, {})

    # ------------------------------------------------------------- eventos
    def publicar(self, tipo, **campos):
        """Recebe tudo que a HUD difunde e o que só a Central tem."""
        with self._trava:
            self._seq += 1
            pacote = {"tipo": tipo, "seq": self._seq, "boot": self.boot, **campos}
            texto = json.dumps(pacote, ensure_ascii=False, default=str)
            self._replay.append((self._seq, texto))
            alvos = list(self._assinantes)
        for fila in alvos:
            try:
                fila.put_nowait((pacote["seq"], texto))
            except queue.Full:
                # Assinante lento perde o fio e é obrigado a ressincronizar,
                # em vez de receber um buraco silencioso.
                try:
                    fila.put_nowait((None, "ressincronizar"))
                except queue.Full:
                    pass

    def marca_dagua(self):
        with self._trava:
            return self._seq

    def _assinar(self, sessao, desde):
        """Fila nova e o replay do que veio depois de `desde`, atômicos."""
        fila = queue.Queue(maxsize=256)
        with self._trava:
            atrasados = [item for item in self._replay if item[0] > desde]
            buraco = bool(self._replay) and desde and self._replay[0][0] > desde + 1
            self._assinantes[fila] = sessao
        return fila, atrasados, buraco

    def _cancelar(self, fila):
        with self._trava:
            self._assinantes.pop(fila, None)

    # ------------------------------------------------------------- sessões
    def _limite_excedido(self, ip):
        agora = self.relogio()
        with self._trava:
            recentes = [t for t in self._tentativas.get(ip, []) if agora - t < JANELA_TENTATIVAS_S]
            self._tentativas[ip] = recentes
            return len(recentes) >= TENTATIVAS

    def _falhou(self, ip):
        with self._trava:
            self._tentativas.setdefault(ip, []).append(self.relogio())

    def entrar(self, chave, ip):
        """('ok', token) | ('limite', None) | ('invalida', None)."""
        if self._limite_excedido(ip):
            return "limite", None
        if not self.hud.autorizado(chave):
            self._falhou(ip)
            return "invalida", None
        token = secrets.token_urlsafe(32)
        agora = self.relogio()
        with self._trava:
            self._tentativas.pop(ip, None)
            self._sessoes[_hash(token)] = {"criada": agora, "expira": agora + SESSAO_S}
        return "ok", token

    def sair(self, token):
        with self._trava:
            self._sessoes.pop(_hash(token or ""), None)

    def sessao(self, cookies, ip=None):
        """('chave', id) | ('aparelho', id) | None. Renova a sessão em uso."""
        token = cookies.get(COOKIE_SESSAO, "")
        if token:
            chave = _hash(token)
            agora = self.relogio()
            with self._trava:
                dados = self._sessoes.get(chave)
                if dados and dados["expira"] > agora:
                    dados["expira"] = agora + SESSAO_S
                    return ("chave", chave)
                self._sessoes.pop(chave, None)
        aparelho = cookies.get(COOKIE_APARELHO, "")
        if aparelho and self.pareamento is not None:
            dados = self.pareamento.validar(aparelho, ip)
            if dados:
                return ("aparelho", dados.get("id"))
        return None

    def ainda_valida(self, sessao) -> bool:
        tipo, ident = sessao
        if tipo == "chave":
            with self._trava:
                dados = self._sessoes.get(ident)
                return bool(dados and dados["expira"] > self.relogio())
        if tipo == "aparelho" and self.pareamento is not None:
            return any(a.get("id") == ident and not a.get("revogado")
                       for a in self.pareamento.aparelhos())
        return False

    def revogar_aparelho(self, aparelho_id):
        """Chamado pelo pareamento: derruba o fluxo do aparelho já."""
        with self._trava:
            alvos = [f for f, s in self._assinantes.items() if s == ("aparelho", aparelho_id)]
        for fila in alvos:
            try:
                fila.put_nowait((None, "revogado"))
            except queue.Full:
                pass

    # ------------------------------------------------------------ admissão
    def admitir(self, pedido_id, digest, pedido, enfileirar):
        """(status, corpo). Reserva, fila e consolidação na mesma seção."""
        agora = self.relogio()
        with self._trava:
            while self._admitidos and (len(self._admitidos) > ADMISSAO_MAX or
                                       next(iter(self._admitidos.values()))["em"] < agora - ADMISSAO_S):
                self._admitidos.popitem(last=False)
            anterior = self._admitidos.get(pedido_id)
            if anterior is not None:
                if anterior["digest"] != digest:
                    return 409, {"erro": "id já usado com outro conteúdo"}
                return 200, {"recebido": True, "repetido": True, "id": pedido_id}
            try:
                enfileirar(pedido)
            except queue.Full:
                return 503, {"erro": "fila cheia; tente de novo", "repetivel": True}
            self._admitidos[pedido_id] = {"digest": digest, "em": agora}
        return 202, {"recebido": True, "id": pedido_id}

    # -------------------------------------------------------------- dados
    def servicos_estado(self):
        """systemctl --user is-active, em cache de 10 s: a tela pede muito."""
        agora = self.relogio()
        instante, cache = self._servicos_cache
        if agora - instante < 10:
            return cache
        estado = {}
        systemctl = shutil.which("systemctl")
        for nome in self.servicos:
            if not systemctl:
                estado[nome] = "desconhecido"
                continue
            try:
                saida = subprocess.run([systemctl, "--user", "is-active", nome],
                                       capture_output=True, text=True, timeout=3).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                saida = "desconhecido"
            estado[nome] = saida or "desconhecido"
        self._servicos_cache = (agora, estado)
        return estado

    def retrato(self):
        """Tudo que a tela precisa para abrir, com a marca d'água do fluxo."""
        seq = self.marca_dagua()
        estado = self.hud.estado()
        corpo = {"tipo": "retrato", "seq": seq, "boot": self.boot, "estado": estado,
                 "controles": self.controles.ler() if self.controles else {},
                 "voz_amostra": bool(self.hud.voz)}
        if self.autonomia is not None:
            corpo["autonomia"] = self.retrato_autonomia()
        if self.gasto is not None:
            try:
                corpo["gasto_voz"] = self.gasto.hoje_gasto()
            except Exception:
                pass
        return corpo

    def retrato_autonomia(self):
        a = self.autonomia
        try:
            from ..autonomia.niveis import classificar
            objetivos = a.objetivos.listar()
            titulos = {o["id"]: o["titulo"] for o in objetivos}
            aprovacoes = []
            for pedido in a.aprovacoes.pendentes(self.relogio()):
                # Irreversível vem do catálogo do código, nunca do modelo.
                regra = classificar(pedido["acao"], pedido.get("args"))
                aprovacoes.append({k: v for k, v in pedido.items() if k not in ("args_json", "args_hash")}
                                  | {"irreversivel": bool(getattr(regra, "irreversivel", True)),
                                     "objetivo_titulo": titulos.get(pedido.get("objetivo_id"))})
            return {"aprovacoes": aprovacoes, "objetivos": objetivos,
                    "atividade": a.trilha.listar(limite=60)}
        except Exception as erro:  # banco próprio indisponível não derruba a tela
            return {"erro": str(erro)[:200]}

    def sistema(self):
        return {"servicos": self.servicos_estado(), "saude": self.hud.saude.medir(),
                "gasto_voz": self.gasto.hoje_gasto() if self.gasto else None,
                "estado": {k: self.hud.estado().get(k) for k in
                           ("modelo", "degrau", "custo_hoje", "voz_origem", "escuta_origem")}}


def ler_cookies(cabecalho: str) -> dict:
    cookies = {}
    for parte in (cabecalho or "").split(";"):
        nome, _, valor = parte.strip().partition("=")
        if nome:
            cookies[nome] = valor
    return cookies


def cookie(nome, valor, max_age, seguro=True):
    partes = [f"{nome}={valor}", "Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={int(max_age)}"]
    if seguro:
        partes.append("Secure")
    return "; ".join(partes)


def atender(manipulador, central, metodo):
    """Despacho de /central/*. Devolve True quando a rota era da Central."""
    url = urlparse(manipulador.path)
    caminho = url.path
    if not (caminho == "/central" or caminho.startswith("/central/")):
        return False
    m = _Rotas(manipulador, central, url)
    try:
        if metodo == "GET":
            m.get(caminho)
        else:
            m.post(caminho)
    except BrokenPipeError:
        pass
    return True


class _Rotas:
    def __init__(self, m, central, url):
        self.m, self.c, self.url = m, central, url
        self.consulta = parse_qs(url.query)
        self.cookies = ler_cookies(m.headers.get("Cookie", ""))

    # ----------------------------------------------------------- respostas
    def _enviar(self, codigo, corpo=b"", tipo="application/json; charset=utf-8", extra=None,
                cache="no-store"):
        m = self.m
        m.send_response(codigo)
        m.send_header("Content-Type", tipo)
        m.send_header("Content-Length", str(len(corpo)))
        m.send_header("Cache-Control", cache)
        m.send_header("X-Content-Type-Options", "nosniff")
        m.send_header("Referrer-Policy", "no-referrer")
        if tipo.startswith("text/html"):
            m.send_header("Content-Security-Policy",
                          "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                          "style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        for nome, valor in (extra or []):
            m.send_header(nome, valor)
        m.end_headers()
        if corpo:
            m.wfile.write(corpo)

    def _json(self, codigo, dados, extra=None):
        self._enviar(codigo, json.dumps(dados, ensure_ascii=False, default=str).encode("utf-8"),
                     extra=extra)

    def _corpo_json(self, limite=LIMITE_DE_MENSAGEM):
        try:
            tamanho = int(self.m.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = -1
        if tamanho < 0 or tamanho > limite:
            self.m.close_connection = True
            self._json(413 if tamanho > limite else 400, {"erro": "tamanho inválido"})
            return None
        try:
            dados = json.loads(self.m.rfile.read(tamanho) or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"erro": "corpo inválido"})
            return None
        if not isinstance(dados, dict):
            self._json(400, {"erro": "corpo inválido"})
            return None
        return dados

    def _ip(self):
        return self.m.client_address[0] if self.m.client_address else ""

    def _sessao(self):
        return self.c.sessao(self.cookies, self._ip())

    def _mesma_origem(self):
        """CSRF: o navegador manda Origin em POST; outro site não consegue
        forjar o cabeçalho X-Zeus sem um preflight que não autorizamos."""
        if self.m.headers.get("X-Zeus") != "1":
            return False
        origem = self.m.headers.get("Origin", "")
        host = self.m.headers.get("Host", "")
        if not origem:
            return True  # navegador antigo ou ferramenta local; o cookie Strict já não vai
        return urlparse(origem).netloc == host

    # ----------------------------------------------------------------- GET
    def get(self, caminho):
        if caminho in ("/central", "/central/"):
            return self._estatico("index.html")
        if caminho == "/central/parear":
            return self._estatico("parear.html")
        if caminho.startswith("/central/api/"):
            return self._api_get(caminho[len("/central/api/"):])
        return self._estatico(caminho[len("/central/"):])

    def _estatico(self, nome):
        alvo = (PASTA / nome).resolve()
        if (PASTA.resolve() not in alvo.parents and alvo != PASTA.resolve()) or not alvo.is_file() \
                or alvo.suffix not in TIPOS_ESTATICOS:
            return self._json(404, {"erro": "não existe"})
        tipo = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml",
                ".webmanifest": "application/manifest+json", ".json": "application/json"}.get(
                    alvo.suffix, mimetypes.guess_type(alvo.name)[0] or "application/octet-stream")
        extra = [("Service-Worker-Allowed", "/central/")] if alvo.name == "sw.js" else None
        # Recarregar sempre: no X99 a Central muda junto com o código; o cache
        # offline é papel do service worker, não do HTTP.
        self._enviar(200, alvo.read_bytes(), tipo, extra=extra, cache="no-cache")

    def _api_get(self, rota):
        if rota == "sessao":
            sessao = self._sessao()
            return self._json(200, {"autenticado": bool(sessao),
                                    "tipo": sessao[0] if sessao else None,
                                    "seguro": bool(self.c.hud.seguro)})
        sessao = self._sessao()
        if not sessao:
            return self._json(401, {"erro": "sessão necessária"})
        if rota == "retrato":
            return self._json(200, self.c.retrato())
        if rota == "eventos":
            return self._eventos(sessao)
        if rota == "sistema":
            return self._json(200, self.c.sistema())
        if rota == "autonomia":
            if self.c.autonomia is None:
                return self._json(503, {"erro": "autonomia desligada"})
            return self._json(200, self.c.retrato_autonomia())
        if rota == "atividade":
            if self.c.autonomia is None:
                return self._json(503, {"erro": "autonomia desligada"})
            tipos = [t for t in (self.consulta.get("tipo") or [""])[0].split(",") if t] or None
            return self._json(200, {"itens": self.c.autonomia.trilha.listar(tipos=tipos, limite=300)})
        if rota.startswith("objetivos/"):
            if self.c.autonomia is None:
                return self._json(503, {"erro": "autonomia desligada"})
            try:
                objetivo = self.c.autonomia.objetivos.obter(int(rota.split("/")[1]))
            except (ValueError, KeyError, LookupError):
                objetivo = None
            if objetivo is None:
                return self._json(404, {"erro": "objetivo não existe"})
            return self._json(200, objetivo)
        if rota == "aparelhos":
            if self.c.pareamento is None or sessao[0] != "chave":
                return self._json(403, {"erro": "só pelo PC"})
            return self._json(200, {"aparelhos": self.c.pareamento.aparelhos()})
        if rota.startswith("audio/"):
            return self._audio(rota.split("/", 1)[1])
        return self._json(404, {"erro": "rota desconhecida"})

    def _audio(self, nome):
        voz = self.c.hud.voz
        if voz is None or not nome.endswith(".wav") or "/" in nome:
            return self._json(404, {"erro": "sem áudio"})
        arquivo = (Path(voz.destino) / nome).resolve()
        if arquivo.parent != Path(voz.destino).resolve() or not arquivo.is_file():
            return self._json(404, {"erro": "sem áudio"})
        self._enviar(200, arquivo.read_bytes(), "audio/wav", cache="private, max-age=3600")

    def _eventos(self, sessao):
        try:
            desde = int(self.m.headers.get("Last-Event-ID") or
                        (self.consulta.get("desde") or ["0"])[0] or 0)
        except ValueError:
            desde = 0
        boot = (self.consulta.get("boot") or [""])[0]
        if boot and boot != self.c.boot:
            desde = 0  # outra subida: a sequência recomeçou
        fila, atrasados, buraco = self.c._assinar(sessao, desde)
        m = self.m
        try:
            m.send_response(200)
            m.send_header("Content-Type", "text/event-stream; charset=utf-8")
            m.send_header("Cache-Control", "no-store")
            m.send_header("X-Accel-Buffering", "no")
            m.end_headers()
            m.close_connection = True
            ola = {"tipo": "ola", "boot": self.c.boot, "seq": self.c.marca_dagua(),
                   "ressincronizar": bool(buraco or (boot and boot != self.c.boot))}
            m.wfile.write(f"retry: 3000\ndata: {json.dumps(ola)}\n\n".encode("utf-8"))
            for seq, texto in atrasados:
                m.wfile.write(f"id: {seq}\ndata: {texto}\n\n".encode("utf-8"))
            m.wfile.flush()
            while True:
                try:
                    seq, texto = fila.get(timeout=BATIDA_S)
                except queue.Empty:
                    if not self.c.ainda_valida(sessao):
                        m.wfile.write(b'event: sessao\ndata: {"tipo":"sessao_encerrada"}\n\n')
                        m.wfile.flush()
                        return
                    m.wfile.write(b": batida\n\n")
                    m.wfile.flush()
                    continue
                if seq is None:
                    if texto == "revogado" or not self.c.ainda_valida(sessao):
                        m.wfile.write(b'event: sessao\ndata: {"tipo":"sessao_encerrada"}\n\n')
                        m.wfile.flush()
                        return
                    m.wfile.write(b'data: {"tipo":"ressincronizar"}\n\n')
                    m.wfile.flush()
                    return
                m.wfile.write(f"id: {seq}\ndata: {texto}\n\n".encode("utf-8"))
                m.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.c._cancelar(fila)

    # ---------------------------------------------------------------- POST
    def post(self, caminho):
        if not caminho.startswith("/central/api/"):
            return self._json(404, {"erro": "rota desconhecida"})
        rota = caminho[len("/central/api/"):]
        if not self._mesma_origem():
            return self._json(403, {"erro": "origem não permitida"})
        if rota == "sessao":
            return self._entrar()
        if rota == "pareamento/reivindicar":
            return self._reivindicar()
        sessao = self._sessao()
        if not sessao:
            return self._json(401, {"erro": "sessão necessária"})
        if rota == "sair":
            self.c.sair(self.cookies.get(COOKIE_SESSAO))
            return self._json(200, {"ok": True}, extra=[
                ("Set-Cookie", cookie(COOKIE_SESSAO, "", 0, self.c.hud.seguro))])
        if rota == "mensagem":
            return self._mensagem()
        if rota == "escuta":
            return self._escuta()
        if rota == "memoria":
            return self._encaminhar({"acao": ("esquecer", "desfazer"), "fato": str},
                                    "memoria")
        if rota.startswith("aprovacoes/"):
            return self._decidir(rota.split("/", 1)[1])
        if rota.startswith("objetivos/"):
            return self._objetivo(rota.split("/", 1)[1])
        if rota.startswith("atividade/") and rota.endswith("/desfazer"):
            return self._desfazer(rota.split("/")[1])
        if rota == "controles":
            return self._controles()
        if rota == "voz/amostra":
            return self._amostra()
        if rota.startswith("pareamento/") or rota.startswith("aparelhos/"):
            return self._pareamento_pc(rota, sessao)
        return self._json(404, {"erro": "rota desconhecida"})

    def _entrar(self):
        dados = self._corpo_json(512)
        if dados is None:
            return
        resultado, token = self.c.entrar(str(dados.get("chave") or ""), self._ip())
        if resultado == "limite":
            return self._json(429, {"erro": "tentativas demais; espere 15 minutos"})
        if resultado != "ok":
            return self._json(401, {"erro": "chave inválida"})
        return self._json(200, {"ok": True}, extra=[
            ("Set-Cookie", cookie(COOKIE_SESSAO, token, SESSAO_S, self.c.hud.seguro))])

    def _mensagem(self):
        dados = self._corpo_json()
        if dados is None:
            return
        pedido_id, texto = dados.get("id"), dados.get("texto")
        if not isinstance(pedido_id, str) or not 8 <= len(pedido_id) <= 64 \
                or not isinstance(texto, str) or not texto.strip():
            return self._json(400, {"erro": "id e texto obrigatórios"})
        texto = texto.strip()[:LIMITE_DE_MENSAGEM]
        digest = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        status, corpo = self.c.admitir(pedido_id, digest, {"tipo": "texto", "texto": texto,
                                                          "id": pedido_id}, self.c.hud.enfileirar)
        return self._json(status, corpo)

    def _escuta(self):
        hud = self.c.hud
        pedido_id = self.m.headers.get("X-Zeus-Turno", "")
        if hud.pasta_de_escuta is None:
            return self._json(503, {"erro": "escuta desligada"})
        if not 8 <= len(pedido_id) <= 64:
            return self._json(400, {"erro": "id obrigatório"})
        try:
            tamanho = int(self.m.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = -1
        if not 0 < tamanho <= LIMITE_DE_AUDIO:
            self.m.close_connection = True
            return self._json(413 if tamanho > 0 else 400, {"erro": "áudio inválido"})
        corpo = self.m.rfile.read(tamanho)
        digest = hashlib.sha256(corpo).hexdigest()
        arquivo = hud.pasta_de_escuta / f"{uuid.uuid4().hex}.webm"
        arquivo.write_bytes(corpo)
        arquivo.chmod(0o600)
        status, resposta = self.c.admitir(pedido_id, digest, {"tipo": "audio", "arquivo": str(arquivo),
                                                              "id": pedido_id}, hud.enfileirar)
        if status != 202:
            arquivo.unlink(missing_ok=True)
        return self._json(status, resposta)

    def _encaminhar(self, esquema, tipo):
        dados = self._corpo_json()
        if dados is None:
            return
        pedido = {"tipo": tipo}
        for campo, regra in esquema.items():
            valor = dados.get(campo)
            if isinstance(regra, tuple):
                if valor not in regra:
                    return self._json(400, {"erro": f"{campo} inválido"})
            elif not isinstance(valor, regra) or not str(valor).strip():
                return self._json(400, {"erro": f"{campo} inválido"})
            pedido[campo] = valor[:200] if isinstance(valor, str) else valor
        try:
            self.c.hud.enfileirar(pedido)
        except queue.Full:
            return self._json(503, {"erro": "fila cheia; tente de novo", "repetivel": True})
        return self._json(202, {"recebido": True})

    def _decidir(self, ident):
        if self.c.autonomia is None:
            return self._json(503, {"erro": "autonomia desligada"})
        dados = self._corpo_json(512)
        if dados is None:
            return
        if not isinstance(dados.get("aprovar"), bool):
            return self._json(400, {"erro": "aprovar precisa ser verdadeiro ou falso"})
        try:
            resultado = self.c.autonomia.aprovacoes.decidir(
                int(ident), dados["aprovar"], por="nicolas", canal="central")
        except (ValueError, LookupError) as erro:
            return self._json(409, {"erro": str(erro)[:200]})
        if not resultado.get("ok"):
            return self._json(409, {"erro": resultado.get("motivo") or "pedido não está mais pendente"})
        return self._json(200, resultado)

    def _objetivo(self, resto):
        if self.c.autonomia is None:
            return self._json(503, {"erro": "autonomia desligada"})
        dados = self._corpo_json(1024)
        if dados is None:
            return
        try:
            ident, acao = resto.split("/", 1)
            ident = int(ident)
        except ValueError:
            return self._json(404, {"erro": "rota desconhecida"})
        if acao != "estado" or dados.get("estado") not in ("ativo", "abandonado", "bloqueado"):
            return self._json(400, {"erro": "estado inválido"})
        # Mexer no objetivo acorda o motor, que é do laço principal.
        try:
            self.c.hud.enfileirar({"tipo": "objetivo_estado", "objetivo": ident,
                                   "estado": dados["estado"], "motivo": str(dados.get("motivo") or "")[:200]})
        except queue.Full:
            return self._json(503, {"erro": "fila cheia; tente de novo", "repetivel": True})
        return self._json(202, {"recebido": True})

    def _desfazer(self, ident):
        try:
            ident = int(ident)
        except ValueError:
            return self._json(404, {"erro": "rota desconhecida"})
        try:
            self.c.hud.enfileirar({"tipo": "desfazer", "registro": ident})
        except queue.Full:
            return self._json(503, {"erro": "fila cheia; tente de novo", "repetivel": True})
        return self._json(202, {"recebido": True})

    def _controles(self):
        if self.c.controles is None:
            return self._json(503, {"erro": "controles indisponíveis"})
        dados = self._corpo_json(2048)
        if dados is None:
            return
        try:
            novo = self.c.controles.aplicar(dados)
        except ValueError as erro:
            return self._json(400, {"erro": str(erro)[:200]})
        self.c.publicar("controles", controles=novo)
        return self._json(200, novo)

    def _amostra(self):
        voz = self.c.hud.voz
        if voz is None or not voz.disponivel():
            return self._json(503, {"erro": "sem voz disponível"})
        try:
            arquivo = voz.falar("Às suas ordens, senhor. É assim que eu soo hoje.")
        except Exception as erro:
            return self._json(502, {"erro": str(erro)[:200]})
        if arquivo is None:
            return self._json(502, {"erro": "a síntese falhou"})
        return self._json(200, {"audio": f"/central/api/audio/{Path(arquivo).name}",
                                "origem": getattr(voz, "ultima_origem", "") or "piper"})

    # ---------------------------------------------------------- pareamento
    def _pareamento_pc(self, rota, sessao):
        p = self.c.pareamento
        if p is None:
            return self._json(503, {"erro": "pareamento indisponível"})
        if sessao[0] != "chave":
            return self._json(403, {"erro": "pareamento só pelo PC, com a chave"})
        dados = self._corpo_json(512)
        if dados is None:
            return
        if rota == "pareamento/iniciar":
            host = self.m.headers.get("Host", "")
            esquema = "https" if self.c.hud.seguro else "http"
            return self._json(200, p.iniciar(f"{esquema}://{host}/central"))
        if rota.startswith("pareamento/") and rota.endswith("/aprovar"):
            reivindicacao = rota.split("/")[1]
            try:
                resultado = p.aprovar(reivindicacao, bool(dados.get("aprovar")))
            except Exception as erro:
                return self._json(409, {"erro": str(erro)[:200]})
            # O token sai daqui uma vez, para a página do celular que está
            # esperando; ele nunca aparece no PC nem no fluxo.
            token = resultado.pop("token", None)
            resultado.pop("set_cookie", None)
            if token:
                self._entregues_pendentes()[reivindicacao] = token
            return self._json(200, resultado)
        if rota.startswith("aparelhos/") and rota.endswith("/revogar"):
            return self._json(200, {"revogado": p.revogar(rota.split("/")[1])})
        return self._json(404, {"erro": "rota desconhecida"})

    def _entregues_pendentes(self):
        """Token aprovado esperando o celular buscar. Some depois de 5 min."""
        if not hasattr(self.c, "_tokens_para_entregar"):
            self.c._tokens_para_entregar = _PrazoCurto(300, self.c.relogio)
        return self.c._tokens_para_entregar

    def _reivindicar(self):
        """Celular sem sessão: reivindica com o nonce do QR e depois espera."""
        p = self.c.pareamento
        if p is None:
            return self._json(503, {"erro": "pareamento indisponível"})
        dados = self._corpo_json(512)
        if dados is None:
            return
        if dados.get("buscar"):
            token = self._entregues_pendentes().pop(str(dados["buscar"]), None)
            if not token:
                return self._json(202, {"aguardando": True})
            return self._json(200, {"ok": True}, extra=[
                ("Set-Cookie", cookie(COOKIE_APARELHO, token, 30 * 86400, self.c.hud.seguro))])
        try:
            resultado = p.reivindicar(str(dados.get("nonce") or ""), str(dados.get("nome") or "celular")[:60],
                                      self._ip())
        except Exception as erro:
            motivo = getattr(erro, "motivo", "")
            return self._json(429 if motivo in ("limite", "bloqueado") else 400,
                              {"erro": str(erro)[:200], "motivo": motivo})
        self.c.publicar("pareamento", reivindicacao=resultado.get("reivindicacao_id"),
                        nome=str(dados.get("nome") or "celular")[:60],
                        codigo=resultado.get("codigo_conferencia"))
        return self._json(200, resultado)


class _PrazoCurto(dict):
    def __init__(self, prazo_s, relogio):
        super().__init__()
        self.prazo_s, self.relogio, self._em = prazo_s, relogio, {}

    def __setitem__(self, chave, valor):
        self._limpar()
        self._em[chave] = self.relogio()
        super().__setitem__(chave, valor)

    def pop(self, chave, padrao=None):
        self._limpar()
        self._em.pop(chave, None)
        return super().pop(chave, padrao)

    def _limpar(self):
        agora = self.relogio()
        for chave in [c for c, em in self._em.items() if agora - em > self.prazo_s]:
            self._em.pop(chave, None)
            super().pop(chave, None)


class Controles:
    """Ajustes de uso diário guardados fora da config: o que a Central muda
    sem reiniciar. Cada campo tem validação; o resto é recusado."""

    PADRAO = {"mudo": False, "volume": None, "nao_perturbe_ate": 0, "palavra_ativacao": False,
              "autonomia": "normal", "teto_voz_caracteres": None, "teto_modelo_usd": None,
              "canais": {"sala": True, "grupo": True}}

    def __init__(self, arquivo, aplicar_volume=None, relogio=None):
        self.arquivo = Path(arquivo)
        self.aplicar_volume = aplicar_volume
        self.relogio = relogio or time.time
        self._trava = threading.Lock()

    def ler(self):
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        atual = {**self.PADRAO, **{k: v for k, v in dados.items() if k in self.PADRAO}}
        atual["nao_perturbe"] = atual["nao_perturbe_ate"] > self.relogio()
        return atual

    def aplicar(self, mudancas):
        with self._trava:
            atual = {k: v for k, v in self.ler().items() if k in self.PADRAO}
            for chave, valor in mudancas.items():
                if chave == "mudo" and isinstance(valor, bool):
                    atual["mudo"] = valor
                elif chave == "volume" and isinstance(valor, (int, float)) and 0 <= valor <= 1:
                    atual["volume"] = round(float(valor), 2)
                elif chave == "nao_perturbe_minutos" and isinstance(valor, int) and 0 <= valor <= 24 * 60:
                    atual["nao_perturbe_ate"] = self.relogio() + valor * 60 if valor else 0
                elif chave == "palavra_ativacao" and isinstance(valor, bool):
                    atual["palavra_ativacao"] = valor
                elif chave == "autonomia" and valor in ("conservadora", "normal", "ousada"):
                    atual["autonomia"] = valor
                elif chave in ("teto_voz_caracteres", "teto_modelo_usd") and (
                        valor is None or (isinstance(valor, (int, float)) and valor >= 0)):
                    atual[chave] = valor
                elif chave == "canais" and isinstance(valor, dict) and set(valor) <= {"sala", "grupo"} \
                        and all(isinstance(v, bool) for v in valor.values()):
                    atual["canais"] = {**atual["canais"], **valor}
                else:
                    raise ValueError(f"ajuste não permitido: {chave}")
            if "volume" in mudancas or "mudo" in mudancas:
                if self.aplicar_volume is not None:
                    self.aplicar_volume(atual["volume"], atual["mudo"])
            self.arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporario = self.arquivo.with_suffix(".tmp")
            temporario.write_text(json.dumps(atual, ensure_ascii=False), encoding="utf-8")
            temporario.chmod(0o600)
            temporario.replace(self.arquivo)
        return self.ler()


def volume_pelo_pipewire(volume, mudo):
    """wpctl no alto-falante padrão. Sem PipeWire, só não muda."""
    wpctl = shutil.which("wpctl")
    if not wpctl:
        return
    try:
        if volume is not None:
            subprocess.run([wpctl, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{volume:.2f}"],
                           timeout=3, check=False, capture_output=True)
        subprocess.run([wpctl, "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if mudo else "0"],
                       timeout=3, check=False, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass
