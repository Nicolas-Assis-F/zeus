"""Pareamento do celular com a HUD por QR, com token de aparelho.

A HUD já atende na rede local em HTTPS, mas até aqui só quem tinha a chave da
HUD entrava. Digitar chave no celular é ruim e mandar a chave por QR seria
pior: ela é eterna e vale para tudo. O pareamento troca isso por um aperto de
mão curto, aprovado por quem já está no PC:

1. No PC, `iniciar` cria uma tentativa: um nonce de 128 bits (vai no QR) e um
   código de 8 dígitos (para digitar se a câmera falhar), válidos por 120 s e
   uma vez só. O nonce viaja no fragmento (`#n=`), que o navegador não manda
   ao servidor nem deixa em log de acesso.
2. O celular apresenta o nonce (ou o código) em `reivindicar`. Os dois lados
   mostram o mesmo número de 4 dígitos, derivado por HMAC: se alguém
   fotografou o QR e reivindicou antes, os números não batem e Nicolas nega.
3. No PC, `aprovar` emite o token do aparelho. Ele é entregue uma única vez,
   para virar cookie `HttpOnly; Secure; SameSite=Strict` (o EventSource do
   SSE não manda cabeçalho próprio, só cookie). No disco fica só o sha256.
4. O token vale 30 dias e renova com o uso, mas nunca passa de 90 dias desde a
   criação: um celular perdido e esquecido para de entrar sozinho.

Nada aqui fala HTTP: o servidor da HUD chama estas funções e decide os
códigos de resposta. O estado fica num arquivo próprio (0600, gravação
atômica), fora do banco, como o contador de gasto de voz.
"""

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .qr import qr_svg

VALIDADE_TENTATIVA_S = 120
JANELA_APROVACAO_S = 120        # depois de reivindicar, quanto o PC tem para aprovar
VALIDADE_TOKEN_S = 30 * 86400   # janela deslizante
TETO_TOKEN_S = 90 * 86400       # desde a criação, não renova além disso
LIMITE_POR_IP = 5               # reivindicações por minuto por IP
JANELA_LIMITE_S = 60
ERROS_ATE_BLOQUEAR_CODIGO = 5
# Gravar o último uso a cada requisição seria uma escrita em disco por
# requisição (e o SSE reconecta sozinho). Um minuto de precisão basta.
PRECISAO_ULTIMO_USO_S = 60

NOME_COOKIE = "zeus_aparelho"
ESCOPO = "celular"


class ErroDePareamento(ValueError):
    """Reivindicação ou aprovação recusada; `motivo` é estável para o servidor.

    Motivos: invalido, expirado, usado, bloqueado, limite, sem_tentativa,
    reivindicacao_desconhecida."""

    def __init__(self, motivo: str, texto: str):
        super().__init__(texto)
        self.motivo = motivo
        self.texto = texto


def _hash(segredo: str) -> str:
    return hashlib.sha256(segredo.encode("utf-8")).hexdigest()


def _iguais(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))


def codigo_de_conferencia(segredo: str, reivindicacao_id: str) -> str:
    """4 dígitos que o celular e o PC mostram juntos.

    Só quem tem o segredo apresentado (nonce ou código) e o id da reivindicação
    chega ao mesmo número, então o celular calcula do lado dele com o que
    escaneou e o PC mostra o que o servidor calculou."""
    resumo = hmac.new(segredo.encode("utf-8"), reivindicacao_id.encode("utf-8"),
                      hashlib.sha256).digest()
    return f"{int.from_bytes(resumo[:8], 'big') % 10000:04d}"


class Pareamento:
    def __init__(self, arquivo_json, relogio=None, ao_revogar=None):
        self.arquivo = Path(arquivo_json)
        # Relógio de parede (epoch): as validades de 30 e 90 dias precisam
        # sobreviver a reinício do processo, o que o monotônico não faz.
        self.relogio = relogio or time.time
        self.ao_revogar = ao_revogar
        self._trava = threading.Lock()
        self._tentativas_por_ip = {}

    # --- disco ---

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        if not isinstance(dados, dict):
            dados = {}
        dados.setdefault("tentativa", None)
        dados.setdefault("aparelhos", [])
        return dados

    def _gravar(self, dados: dict):
        self.arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporario = tempfile.mkstemp(dir=self.arquivo.parent, suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)  # antes de escrever: o token não fica legível nem por um instante
            with os.fdopen(fd, "w", encoding="utf-8") as saida:
                json.dump(dados, saida, ensure_ascii=False, indent=1)
            os.replace(temporario, self.arquivo)
        except BaseException:
            try:
                os.unlink(temporario)
            except OSError:
                pass
            raise

    # --- tentativa (PC) ---

    def iniciar(self, endereco_base: str) -> dict:
        """Cria a tentativa e devolve o QR. Iniciar de novo invalida a anterior,
        inclusive uma que já esperava aprovação."""
        agora = self.relogio()
        nonce = secrets.token_urlsafe(16)
        codigo = f"{secrets.randbelow(10 ** 8):08d}"
        tentativa = {
            "id": secrets.token_hex(8),
            "nonce_sha256": _hash(nonce),
            "codigo_sha256": _hash(codigo),
            "criada_em": agora,
            "expira_em": agora + VALIDADE_TENTATIVA_S,
            "estado": "ativa",
            "erros": 0,
            "reivindicacao": None,
        }
        with self._trava:
            dados = self._ler()
            dados["tentativa"] = tentativa
            self._gravar(dados)
        url = f"{endereco_base.rstrip('/')}/parear#n={nonce}"
        return {"id": tentativa["id"], "url": url, "qr_svg": qr_svg(url),
                "codigo_manual": codigo, "expira_em": tentativa["expira_em"]}

    def cancelar(self):
        with self._trava:
            dados = self._ler()
            dados["tentativa"] = None
            self._gravar(dados)

    def situacao(self):
        """O que o PC mostra: estado da tentativa e, se reivindicada, quem pediu
        e os 4 dígitos para conferir. Nunca devolve hash nem segredo."""
        with self._trava:
            tentativa = self._ler()["tentativa"]
        if tentativa is None:
            return None
        estado = tentativa["estado"]
        if estado == "ativa" and self.relogio() > tentativa["expira_em"]:
            estado = "expirada"
        saida = {"id": tentativa["id"], "estado": estado, "expira_em": tentativa["expira_em"],
                 "codigo_bloqueado": tentativa["erros"] >= ERROS_ATE_BLOQUEAR_CODIGO}
        pedido = tentativa.get("reivindicacao")
        if pedido:
            saida.update({"reivindicacao_id": pedido["id"], "nome_aparelho": pedido["nome"],
                          "ip": pedido["ip"], "codigo_conferencia": pedido["conferencia"]})
        return saida

    # --- reivindicação (celular) ---

    def _contar_tentativa_do_ip(self, ip: str, agora: float):
        recentes = [t for t in self._tentativas_por_ip.get(ip, []) if agora - t < JANELA_LIMITE_S]
        # Limpa IPs parados, para o dicionário não crescer com a rede inteira.
        self._tentativas_por_ip = {k: v for k, v in self._tentativas_por_ip.items()
                                   if v and agora - v[-1] < JANELA_LIMITE_S}
        if len(recentes) >= LIMITE_POR_IP:
            self._tentativas_por_ip[ip] = recentes
            raise ErroDePareamento("limite", "Muitas tentativas deste aparelho; espere um minuto.")
        recentes.append(agora)
        self._tentativas_por_ip[ip] = recentes

    def reivindicar(self, nonce_ou_codigo: str, nome_aparelho: str, ip: str) -> dict:
        agora = self.relogio()
        segredo = (nonce_ou_codigo or "").strip()
        eh_codigo = len(segredo) == 8 and segredo.isdigit()
        nome = " ".join(str(nome_aparelho or "").split())[:60] or "celular"
        with self._trava:
            self._contar_tentativa_do_ip(str(ip), agora)
            dados = self._ler()
            tentativa = dados["tentativa"]
            if tentativa is None:
                raise ErroDePareamento("sem_tentativa", "Nenhum pareamento aberto no PC.")
            recebido = _hash(segredo)
            # As duas comparações sempre acontecem, em tempo constante: o tempo
            # de resposta não diz se o erro foi no nonce ou no código.
            bate_nonce = _iguais(recebido, tentativa["nonce_sha256"])
            bate_codigo = _iguais(recebido, tentativa["codigo_sha256"])
            if eh_codigo and tentativa["erros"] >= ERROS_ATE_BLOQUEAR_CODIGO:
                raise ErroDePareamento("bloqueado", "Código bloqueado por erros; "
                                       "escaneie o QR ou gere outro no PC.")
            if not (bate_nonce or (bate_codigo and eh_codigo)):
                if eh_codigo:
                    tentativa["erros"] += 1
                    self._gravar(dados)
                raise ErroDePareamento("invalido", "Código de pareamento inválido.")
            if tentativa["estado"] != "ativa":
                raise ErroDePareamento("usado", "Este pareamento já foi usado; gere outro no PC.")
            if agora > tentativa["expira_em"]:
                raise ErroDePareamento("expirado", "O pareamento expirou; gere outro no PC.")
            reivindicacao_id = secrets.token_hex(8)
            conferencia = codigo_de_conferencia(segredo, reivindicacao_id)
            tentativa["estado"] = "aguardando_aprovacao"
            tentativa["reivindicacao"] = {"id": reivindicacao_id, "nome": nome, "ip": str(ip),
                                          "em": agora, "conferencia": conferencia}
            self._gravar(dados)
        return {"reivindicacao_id": reivindicacao_id, "codigo_conferencia": conferencia}

    # --- aprovação (PC, já autenticado) ---

    def aprovar(self, reivindicacao_id: str, aprovar: bool) -> dict:
        agora = self.relogio()
        with self._trava:
            dados = self._ler()
            tentativa = dados["tentativa"]
            pedido = (tentativa or {}).get("reivindicacao")
            if (tentativa is None or pedido is None or tentativa["estado"] != "aguardando_aprovacao"
                    or not _iguais(_hash(str(reivindicacao_id)), _hash(pedido["id"]))):
                raise ErroDePareamento("reivindicacao_desconhecida",
                                       "Não há pedido de pareamento com esse id.")
            if agora - pedido["em"] > JANELA_APROVACAO_S:
                dados["tentativa"] = None
                self._gravar(dados)
                raise ErroDePareamento("expirado", "O pedido esperou demais; pareie de novo.")
            dados["tentativa"] = None  # aprovada ou negada, a tentativa acabou
            if not aprovar:
                self._gravar(dados)
                return {"aprovado": False}
            token = secrets.token_urlsafe(32)
            aparelho = {
                "id": secrets.token_hex(6),
                "token_sha256": _hash(token),
                "nome": pedido["nome"],
                "ip": pedido["ip"],
                "escopo": ESCOPO,
                "criado_em": agora,
                "ultimo_uso": agora,
                "expira_em": agora + VALIDADE_TOKEN_S,
            }
            dados["aparelhos"].append(aparelho)
            self._gravar(dados)
        max_age = VALIDADE_TOKEN_S
        return {"aprovado": True, "aparelho_id": aparelho["id"], "nome": aparelho["nome"],
                "token": token, "expira_em": aparelho["expira_em"], "max_age": max_age,
                "set_cookie": cabecalho_cookie(token, max_age)}

    # --- uso do token ---

    @staticmethod
    def _publico(aparelho: dict) -> dict:
        return {k: v for k, v in aparelho.items() if k != "token_sha256"}

    def _vivo(self, aparelho: dict, agora: float) -> bool:
        return agora <= aparelho["expira_em"] and agora <= aparelho["criado_em"] + TETO_TOKEN_S

    def validar(self, token: str, ip: str = None):
        """Devolve o aparelho (sem hash) se o token vale, e empurra a validade.

        A janela de 30 dias recomeça a cada uso, mas o teto de 90 dias desde a
        criação não se move: depois dele só pareando de novo."""
        if not token:
            return None
        agora = self.relogio()
        recebido = _hash(token)
        with self._trava:
            dados = self._ler()
            achado = None
            for aparelho in dados["aparelhos"]:  # percorre todos, sem atalho
                if _iguais(recebido, aparelho["token_sha256"]):
                    achado = aparelho
            if achado is None:
                return None
            if not self._vivo(achado, agora):
                dados["aparelhos"].remove(achado)
                self._gravar(dados)
                return None
            nova_validade = min(agora + VALIDADE_TOKEN_S, achado["criado_em"] + TETO_TOKEN_S)
            if (agora - achado["ultimo_uso"] >= PRECISAO_ULTIMO_USO_S
                    or (ip and ip != achado["ip"])):
                achado["ultimo_uso"] = agora
                achado["expira_em"] = nova_validade
                if ip:
                    achado["ip"] = str(ip)
                self._gravar(dados)
            return self._publico(achado)

    def aparelhos(self) -> list:
        agora = self.relogio()
        with self._trava:
            dados = self._ler()
        return [self._publico(a) for a in dados["aparelhos"] if self._vivo(a, agora)]

    # --- revogação ---

    def _avisar_revogacao(self, ids):
        if self.ao_revogar is None:
            return
        for aparelho_id in ids:
            try:
                self.ao_revogar(aparelho_id)
            except Exception:
                pass  # derrubar o SSE é cortesia; o token já não vale no disco

    def revogar(self, aparelho_id: str) -> bool:
        with self._trava:
            dados = self._ler()
            restantes = [a for a in dados["aparelhos"] if a["id"] != aparelho_id]
            if len(restantes) == len(dados["aparelhos"]):
                return False
            dados["aparelhos"] = restantes
            self._gravar(dados)
        self._avisar_revogacao([aparelho_id])
        return True

    def revogar_todos(self) -> int:
        with self._trava:
            dados = self._ler()
            ids = [a["id"] for a in dados["aparelhos"]]
            dados["aparelhos"] = []
            dados["tentativa"] = None
            self._gravar(dados)
        self._avisar_revogacao(ids)
        return len(ids)


# --- auxiliares para o servidor ---

def cabecalho_cookie(token: str, max_age: int) -> str:
    """Valor do Set-Cookie do aparelho. `max_age` 0 com token vazio apaga.

    HttpOnly: script da página não lê (um XSS não leva o token). Secure: só
    vai por HTTPS. SameSite=Strict: outro site não faz o navegador do celular
    mandar o cookie junto (CSRF)."""
    token = token or ""
    if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
           for c in token):
        raise ValueError("token com caractere inválido para cookie")
    return (f"{NOME_COOKIE}={token}; Path=/; Max-Age={max(0, int(max_age))}; "
            "HttpOnly; Secure; SameSite=Strict")


def token_do_cookie(cabecalho: str) -> str:
    """Extrai o token do cabeçalho Cookie da requisição ('' se não houver)."""
    for pedaco in (cabecalho or "").split(";"):
        nome, _, valor = pedaco.strip().partition("=")
        if nome == NOME_COOKIE:
            return valor.strip()
    return ""


def _normalizar_host(host: str):
    """'Exemplo.local.:443' -> 'exemplo.local'; None se não parece Host válido."""
    host = (host or "").strip().lower()
    if not host or any(c in host for c in "/@?# \\\t"):
        return None
    if host.startswith("["):  # IPv6 entre colchetes
        fim = host.find("]")
        if fim < 0:
            return None
        nome, resto = host[1:fim], host[fim + 1:]
        try:
            ipaddress.IPv6Address(nome)
        except ValueError:
            return None
        nome = f"[{nome}]"
        porta = resto[1:] if resto.startswith(":") else ("" if not resto else None)
    else:
        nome, _, porta = host.partition(":")
        nome = nome.rstrip(".")
    if porta is None or (porta and not porta.isdigit()) or not nome:
        return None
    if porta in ("", "443"):
        return nome
    return f"{nome}:{int(porta)}"


def host_permitido(host: str, permitidos: set) -> bool:
    """Confere o cabeçalho Host contra a lista do servidor.

    É a defesa contra DNS rebinding: um site malicioso pode apontar o próprio
    nome para o IP da HUD, mas o navegador continua mandando o nome dele no
    Host, que não está na lista."""
    normalizado = _normalizar_host(host)
    if normalizado is None:
        return False
    return normalizado in {_normalizar_host(p) for p in permitidos} - {None}


def origem_permitida(origin: str, hosts_permitidos: set) -> bool:
    """Confere o cabeçalho Origin (contra CSRF): esquema e host da própria HUD.

    Origin 'null' ou ausente é recusado: quem chama decide se uma requisição
    sem Origin (GET simples) passa por outra regra. HTTP puro só vale em
    loopback, onde o navegador também considera a origem segura."""
    origin = (origin or "").strip()
    if not origin or origin == "null":
        return False
    try:
        partes = urlsplit(origin)
        _ = partes.port  # levanta ValueError se a porta for lixo
    except ValueError:
        return False
    if partes.path not in ("", "/") or partes.query or partes.fragment or partes.username:
        return False
    if partes.scheme == "http":
        if (partes.hostname or "") not in ("localhost", "127.0.0.1", "::1"):
            return False
        # Em http a porta padrão é 80; o Host equivalente leva a porta explícita.
        netloc = partes.netloc if partes.port else f"{partes.netloc}:80"
        return host_permitido(netloc, hosts_permitidos)
    if partes.scheme != "https":
        return False
    return host_permitido(partes.netloc, hosts_permitidos)


def hosts_padrao(ip: str, porta: int) -> set:
    """Os nomes pelos quais a HUD é alcançada: os mesmos do certificado."""
    return {f"{ip}:{porta}", f"127.0.0.1:{porta}", f"localhost:{porta}", f"zeus:{porta}"}
