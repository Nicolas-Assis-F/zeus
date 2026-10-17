"""Voz do Zeus: ElevenLabs pelo OpenRouter, com o Piper local de reserva.

Escolha honesta para o hardware que existe: o 8B ocupa a VRAM, então a síntese
fica na CPU, e o Xeon de 24 threads dá conta. Piper roda como binário próprio,
com modelo em disco, sem depender de nuvem e sem microfone — falar não exige
ouvir, e é o lado da voz que dá para entregar hoje inteiro em casa.

Se o Piper não estiver instalado, nada quebra: o Zeus continua escrevendo. Uma
capacidade ausente é dita em voz alta, nunca simulada.

A voz natural vem da ElevenLabs, pelo endpoint de áudio do OpenRouter (#68):
mesma chave do modelo, só `urllib`. Falta de rede, de chave, de saldo ou o teto
diário fazem a fala cair para o Piper sozinha, e a troca vai para o log.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path


class Voz:
    def __init__(self, binario: str = "piper", modelo: str = "", destino: Path = None,
                 limite_de_caracteres: int = 600):
        self.binario = shutil.which(binario) if binario else None
        self.modelo = Path(modelo).expanduser() if modelo else None
        self.destino = Path(destino) if destino else Path(tempfile.gettempdir()) / "zeus-voz"
        self.limite = limite_de_caracteres
        self.destino.mkdir(parents=True, exist_ok=True, mode=0o700)

    def disponivel(self) -> bool:
        return bool(self.binario and self.modelo and self.modelo.exists())

    def diagnostico(self) -> str:
        if not self.binario:
            return "piper não encontrado no PATH"
        if not self.modelo:
            return "nenhum modelo de voz configurado"
        if not self.modelo.exists():
            return f"modelo não existe em {self.modelo}"
        return "pronta"

    def falar(self, texto: str) -> Path:
        """Sintetiza e devolve o caminho do WAV, ou None quando indisponível."""
        if not self.disponivel() or not texto.strip():
            return None
        recorte = texto.strip()[: self.limite]
        nome = hashlib.sha256((str(self.modelo) + str(self.modelo.stat().st_mtime_ns) + recorte).encode("utf-8")).hexdigest()[:24]
        arquivo = self.destino / f"{nome}.wav"
        if arquivo.exists() and arquivo.stat().st_size > 44:
            return arquivo
        fd, nome_temporario = tempfile.mkstemp(suffix=".wav", dir=self.destino)
        os.close(fd)
        temporario = Path(nome_temporario)
        try:
            subprocess.run(
                [self.binario, "--model", str(self.modelo), "--output_file", str(temporario)],
                input=recorte.encode("utf-8"),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=120, check=True,
            )
            if temporario.stat().st_size <= 44:
                return None
            os.replace(temporario, arquivo)
            return arquivo
        except (subprocess.SubprocessError, OSError):
            return None
        finally:
            temporario.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# ElevenLabs pelo OpenRouter.
#
# Medido no X99 em 17/10/2026: o primeiro byte chega em 1,5 a 2 s e o resto logo
# depois, então o arquivo inteiro sai quase no mesmo instante do primeiro som.
# O áudio vem em PCM 16 bits mono a 24 kHz e vira WAV aqui, no formato que a HUD
# já toca. O OpenRouter não devolve custo no TTS; a estimativa é por caractere.

TAXA_PCM = 24000

# Quanto tempo o provedor remoto fica de lado depois de cada tipo de falha.
# Erro do próprio texto (400) não tira a voz do ar; chave recusada tira por horas.
DESCANSO = {401: 6 * 3600, 403: 6 * 3600, 402: 3600, 429: 300}
DESCANSO_SERVIDOR = 120
DESCANSO_REDE = 60


class ErroDeVoz(RuntimeError):
    def __init__(self, motivo: str, descanso: float = 0):
        super().__init__(motivo)
        self.descanso = descanso


def transporte_audio(url, corpo: bytes, cabecalhos: dict, timeout: float):
    """POST que devolve (status, bytes); falha de rede vira ErroDeVoz."""
    pedido = urllib.request.Request(url, data=corpo, headers=cabecalhos, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read()[:500]
    except (urllib.error.URLError, OSError) as erro:
        raise ErroDeVoz(f"sem rede: {getattr(erro, 'reason', erro)}"[:200], DESCANSO_REDE) from None


def descanso_por_status(status: int) -> float:
    if status in DESCANSO:
        return DESCANSO[status]
    return DESCANSO_SERVIDOR if status >= 500 else 0


def pcm_para_wav(pcm: bytes, arquivo: Path, taxa: int = TAXA_PCM):
    with wave.open(str(arquivo), "wb") as saida:
        saida.setnchannels(1)
        saida.setsampwidth(2)
        saida.setframerate(taxa)
        saida.writeframes(pcm)


class VozElevenLabs:
    nome = "elevenlabs"

    def __init__(self, chave: str, url: str = "https://openrouter.ai/api/v1",
                 modelo: str = "elevenlabs/eleven-v4-turbo",
                 modelo_caprichado: str = "elevenlabs/eleven-v4", voz: str = "brian",
                 caprichada_acima: int = 400, destino: Path = None, gasto=None,
                 transporte=None, timeout: float = 20, limite_de_caracteres: int = 1500,
                 relogio=None):
        self.chave = chave or ""
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.modelo_caprichado = modelo_caprichado or modelo
        self.voz = voz
        self.caprichada_acima = caprichada_acima
        self.destino = Path(destino) if destino else Path(tempfile.gettempdir()) / "zeus-voz"
        self.destino.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.gasto = gasto
        self.transporte = transporte or transporte_audio
        self.timeout = timeout
        self.limite = limite_de_caracteres
        self.relogio = relogio or time.monotonic
        self._descansa_ate = 0.0
        self._erro = ""
        self.ultima_medicao = {}

    def escolher_modelo(self, texto: str, caprichada: bool = False) -> str:
        """Turbo na conversa; o v4, com emoção, no briefing e no texto longo."""
        if caprichada or len(texto) > self.caprichada_acima:
            return self.modelo_caprichado
        return self.modelo

    def disponivel(self) -> bool:
        return bool(self.chave and self.voz) and self.relogio() >= self._descansa_ate

    def diagnostico(self) -> str:
        if not self.chave:
            return "sem chave do OpenRouter"
        if not self.voz:
            return "nenhuma voz configurada"
        restante = self._descansa_ate - self.relogio()
        if restante > 0:
            return f"em descanso por {int(restante)} s depois de: {self._erro}"
        return f"pronta ({self.modelo}, voz {self.voz})"

    def _arquivo(self, modelo, recorte):
        nome = hashlib.sha256(f"{modelo}\0{self.voz}\0{recorte}".encode("utf-8")).hexdigest()[:24]
        return self.destino / f"el-{nome}.wav"

    def falar(self, texto: str, caprichada: bool = False) -> Path:
        """WAV sintetizado, ou None. Falha de provedor sobe como ErroDeVoz."""
        recorte = (texto or "").strip()[: self.limite]
        if not recorte or not self.disponivel():
            return None
        modelo = self.escolher_modelo(recorte, caprichada)
        arquivo = self._arquivo(modelo, recorte)
        if arquivo.exists() and arquivo.stat().st_size > 44:
            return arquivo
        if self.gasto is not None and not self.gasto.pode(caracteres=len(recorte)):
            raise ErroDeVoz("teto diário de caracteres atingido")
        corpo = json.dumps({"model": modelo, "input": recorte, "voice": self.voz,
                            "response_format": "pcm"}).encode("utf-8")
        cabecalhos = {"Authorization": f"Bearer {self.chave}",
                      "Content-Type": "application/json"}
        inicio = time.perf_counter()
        try:
            status, dados = self.transporte(self.url + "/audio/speech", corpo, cabecalhos,
                                            self.timeout)
        except ErroDeVoz as erro:
            self._descansar(str(erro), erro.descanso)
            raise
        if status != 200 or len(dados) < 2:
            motivo = f"OpenRouter respondeu {status}"
            self._descansar(motivo, descanso_por_status(status))
            raise ErroDeVoz(motivo)
        self.ultima_medicao = {"modelo": modelo, "sintese_s": round(time.perf_counter() - inicio, 3),
                               "audio_s": round(len(dados) / (2 * TAXA_PCM), 3)}
        fd, nome_temporario = tempfile.mkstemp(suffix=".wav", dir=self.destino)
        os.close(fd)
        temporario = Path(nome_temporario)
        try:
            pcm_para_wav(dados[: len(dados) // 2 * 2], temporario)
            os.replace(temporario, arquivo)
        finally:
            temporario.unlink(missing_ok=True)
        if self.gasto is not None:
            from .gasto_voz import PRECO_POR_CARACTERE
            self.gasto.registrar(caracteres=len(recorte),
                                 usd=len(recorte) * PRECO_POR_CARACTERE.get(modelo, 0))
        return arquivo

    def _descansar(self, motivo, segundos):
        self._erro = motivo
        if segundos:
            self._descansa_ate = self.relogio() + segundos


class VozComReserva:
    """A voz remota primeiro; o Piper quando ela não puder. Mesma interface de
    `Voz`, então a HUD, a fala em segundo plano e os canais não mudam."""

    def __init__(self, principal, reserva, ao_trocar=None):
        self.principal = principal
        self.reserva = reserva
        self.destino = reserva.destino
        self.ao_trocar = ao_trocar
        self.ultima_origem = ""

    def disponivel(self) -> bool:
        return self.principal.disponivel() or self.reserva.disponivel()

    def diagnostico(self) -> str:
        return (f"{self.principal.nome}: {self.principal.diagnostico()}; "
                f"reserva piper: {self.reserva.diagnostico()}")

    def falar(self, texto: str, caprichada: bool = False) -> Path:
        motivo = ""
        if self.principal.disponivel():
            try:
                arquivo = self.principal.falar(texto, caprichada=caprichada)
                if arquivo is not None:
                    self._origem(self.principal.nome, "")
                    return arquivo
            except ErroDeVoz as erro:
                motivo = str(erro)
        else:
            motivo = self.principal.diagnostico()
        arquivo = self.reserva.falar(texto)
        if arquivo is not None:
            self._origem("piper", motivo)
        return arquivo

    def _origem(self, origem, motivo):
        if origem != self.ultima_origem and self.ao_trocar is not None:
            try:
                self.ao_trocar(origem, motivo)
            except Exception:
                pass
        self.ultima_origem = origem


def nota_de_voz(wav: Path, destino: Path = None) -> Path:
    """OGG/Opus mono, o formato que o WhatsApp mostra como nota de voz.
    Sem ffmpeg, None: a resposta segue só em texto."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or wav is None or not Path(wav).is_file():
        return None
    saida = Path(destino or Path(wav).parent) / (Path(wav).stem + ".ogg")
    if saida.exists() and saida.stat().st_size > 0:
        return saida
    try:
        subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(wav),
                        "-c:a", "libopus", "-b:a", "32k", "-ac", "1", str(saida)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60, check=True)
    except (subprocess.SubprocessError, OSError):
        saida.unlink(missing_ok=True)
        return None
    return saida if saida.exists() and saida.stat().st_size > 0 else None
