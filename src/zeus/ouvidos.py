"""Transcrição local em CPU, sem ocupar a GPU do modelo de conversa.

O modelo é reutilizado entre falas. Os diagnósticos distinguem pacote ausente,
carregamento pendente e erro recuperável; instalar o pacote não prova que um
microfone real já foi testado. O primeiro carregamento pode baixar o modelo.

`OuvidosScribe` transcreve pelo Scribe da ElevenLabs, via OpenRouter (#68), e
`OuvidosComReserva` cai para o faster-whisper quando falta rede, chave, saldo
ou teto diário. Com o Scribe na frente, o modelo local só carrega na primeira
falha: não ocupa a RAM à toa.
"""

import base64
import json
import os
import time
from pathlib import Path

TAMANHOS = ("tiny", "base", "small", "medium", "large-v3")


class Ouvidos:
    def __init__(self, modelo="small", computo="int8", idioma="pt", threads=4,
                 destino=None, beam_size=1, silencio_ms=500, vocabulario="",
                 limite_segundos=65):
        if threads < 0 or not 1 <= beam_size <= 5 or silencio_ms < 100:
            raise ValueError("Escuta exige threads >= 0, beam de 1 a 5 e silêncio >= 100 ms.")
        self.modelo = modelo
        self.computo = computo
        self.idioma = idioma
        # Automático também é conservador: a CPU é compartilhada com o LLM.
        self.threads = threads or min(4, os.cpu_count() or 1)
        self.destino = Path(destino) if destino else Path("/tmp/zeus-escuta")
        self.destino.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.beam_size = beam_size
        self.silencio_ms = silencio_ms
        self.vocabulario = vocabulario.strip()[:500]
        self.limite_segundos = limite_segundos
        self._motor = None
        self._erro = ""
        self.ultima_medicao = {}

    def instalado(self):
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    def disponivel(self):
        # Erro de um arquivo não deve desativar o próximo uso do microfone.
        return self.instalado()

    def diagnostico(self):
        if not self.instalado():
            return "faster-whisper não instalado; instale no ambiente virtual do Zeus"
        if self._erro:
            return f"última tentativa falhou: {self._erro}; pode tentar novamente"
        estado = "carregado" if self._motor is not None else "ainda não carregado"
        return f"modelo {self.modelo} {estado}, CPU com {self.threads} threads"

    def _carregar(self):
        if self._motor is not None:
            return self._motor
        try:
            from faster_whisper import WhisperModel
            self._motor = WhisperModel(self.modelo, device="cpu",
                                       compute_type=self.computo,
                                       cpu_threads=self.threads)
            self._erro = ""
        except Exception as erro:
            self._erro = str(erro)[:200]
        return self._motor

    def preparar(self):
        """Carga explícita antes do primeiro uso; não é feita no boot."""
        return self._carregar() is not None

    def transcrever(self, arquivo, remover=True):
        caminho = Path(arquivo)
        inicio = time.perf_counter()
        self._erro = ""
        self.ultima_medicao = {}
        try:
            if not caminho.is_file() or caminho.stat().st_size == 0:
                self._erro = "áudio vazio ou ausente"
                return ""
            motor = self._carregar()
            carregado = time.perf_counter()
            if motor is None:
                return ""
            trechos, info = motor.transcribe(
                str(caminho), language=self.idioma, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": self.silencio_ms},
                beam_size=self.beam_size, temperature=0.0,
                condition_on_previous_text=False,
                initial_prompt=self.vocabulario or None,
            )
            duracao = float(getattr(info, "duration", 0) or 0)
            if duracao > self.limite_segundos:
                self._erro = f"áudio excede {self.limite_segundos} segundos"
                return ""
            # O trabalho de reconhecimento ocorre ao consumir o gerador.
            texto = " ".join(t.text.strip() for t in trechos if t.text.strip()).strip()
            fim = time.perf_counter()
            self.ultima_medicao = {
                "carga_s": round(carregado - inicio, 4),
                "transcricao_s": round(fim - carregado, 4),
                "total_s": round(fim - inicio, 4),
                "audio_s": round(duracao, 4),
                "com_fala": bool(texto),
            }
            return texto
        except Exception as erro:
            self._erro = str(erro)[:200]
            return ""
        finally:
            if remover:
                try:
                    caminho.unlink(missing_ok=True)
                except OSError:
                    pass


FORMATOS = {".wav": "wav", ".ogg": "ogg", ".oga": "ogg", ".opus": "ogg", ".webm": "webm",
            ".mp3": "mp3", ".m4a": "m4a", ".flac": "flac", ".aac": "aac"}
MAXIMO_BYTES = 25 * 1024 * 1024


class OuvidosScribe:
    nome = "scribe"

    def __init__(self, chave, url="https://openrouter.ai/api/v1",
                 modelo="elevenlabs/scribe-v2", idioma="pt", gasto=None,
                 transporte=None, timeout=120, limite_segundos=65, relogio=None):
        self.chave = chave or ""
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.idioma = idioma
        self.gasto = gasto
        self.transporte = transporte
        self.timeout = timeout
        self.limite_segundos = limite_segundos
        self.relogio = relogio or time.monotonic
        self._descansa_ate = 0.0
        self._erro = ""
        self.palavras = []
        self.ultima_medicao = {}

    def assinatura(self):
        return (self.nome, self.modelo, self.idioma, self.limite_segundos)

    def instalado(self):
        return bool(self.chave)

    def disponivel(self):
        if not self.chave or self.relogio() < self._descansa_ate:
            return False
        # Teto de escuta já estourado hoje: nem tenta.
        return self.gasto is None or self.gasto.pode(segundos=1)

    def diagnostico(self):
        if not self.chave:
            return "sem chave do OpenRouter"
        restante = self._descansa_ate - self.relogio()
        if restante > 0:
            return f"em descanso por {int(restante)} s depois de: {self._erro}"
        if self.gasto is not None and not self.gasto.pode(segundos=1):
            return "teto diário de segundos de escuta atingido"
        if self._erro:
            return f"última tentativa falhou: {self._erro}"
        return f"pronta ({self.modelo})"

    def preparar(self):
        return self.disponivel()

    def transcrever(self, arquivo, remover=True):
        from .voz import ErroDeVoz, descanso_por_status, transporte_audio
        caminho = Path(arquivo)
        inicio = time.perf_counter()
        self._erro, self.palavras, self.ultima_medicao = "", [], {}
        try:
            if not caminho.is_file() or caminho.stat().st_size == 0:
                self._erro = "áudio vazio ou ausente"
                return ""
            if caminho.stat().st_size > MAXIMO_BYTES:
                self._erro = "áudio acima de 25 MB"
                return ""
            corpo = json.dumps({
                "model": self.modelo,
                "input_audio": {"data": base64.b64encode(caminho.read_bytes()).decode("ascii"),
                                "format": FORMATOS.get(caminho.suffix.lower(), "wav")},
                "language": self.idioma, "response_format": "verbose_json",
                "timestamp_granularities": ["word"],
            }).encode("utf-8")
            cabecalhos = {"Authorization": f"Bearer {self.chave}",
                          "Content-Type": "application/json"}
            try:
                status, bruto = (self.transporte or transporte_audio)(
                    self.url + "/audio/transcriptions", corpo, cabecalhos, self.timeout)
            except ErroDeVoz as erro:
                self._descansar(str(erro), erro.descanso)
                return ""
            if status != 200:
                self._descansar(f"OpenRouter respondeu {status}", descanso_por_status(status))
                return ""
            dados = json.loads(bruto)
            uso = dados.get("usage") or {}
            duracao = float(uso.get("seconds") or dados.get("duration") or 0)
            if self.gasto is not None:
                self.gasto.registrar(segundos=duracao, usd=float(uso.get("cost") or 0))
            if duracao > self.limite_segundos:
                self._erro = f"áudio excede {self.limite_segundos} segundos"
                return ""
            texto = str(dados.get("text") or "").strip()
            self.palavras = [p for p in dados.get("words") or [] if isinstance(p, dict)]
            self.ultima_medicao = {"total_s": round(time.perf_counter() - inicio, 4),
                                   "audio_s": round(duracao, 4), "com_fala": bool(texto),
                                   "custo_usd": uso.get("cost")}
            return texto
        except (OSError, ValueError) as erro:
            self._erro = str(erro)[:200]
            return ""
        finally:
            if remover:
                try:
                    caminho.unlink(missing_ok=True)
                except OSError:
                    pass

    def _descansar(self, motivo, segundos):
        self._erro = motivo
        if segundos:
            self._descansa_ate = self.relogio() + segundos


class OuvidosComReserva:
    """Scribe primeiro, faster-whisper quando ele não puder. Mesma interface
    de `Ouvidos`: quem chama não sabe, nem precisa saber, quem transcreveu."""

    def __init__(self, principal, reserva, ao_trocar=None):
        self.principal = principal
        self.reserva = reserva
        self.ao_trocar = ao_trocar
        self.ultima_origem = ""
        self.ultima_medicao = {}

    @property
    def limite_segundos(self):
        return self.reserva.limite_segundos

    @property
    def destino(self):
        return self.reserva.destino

    def assinatura(self):
        return (self.principal.assinatura(), self.reserva.assinatura()
                if hasattr(self.reserva, "assinatura") else ())

    def instalado(self):
        return self.principal.instalado() or self.reserva.instalado()

    def disponivel(self):
        return self.principal.disponivel() or self.reserva.disponivel()

    def diagnostico(self):
        return (f"{self.principal.nome}: {self.principal.diagnostico()}; "
                f"reserva local: {self.reserva.diagnostico()}")

    def preparar(self):
        # O modelo local só é carregado se o remoto não estiver de pé.
        return self.principal.preparar() or self.reserva.preparar()

    def transcrever(self, arquivo, remover=True):
        motivo = ""
        try:
            if self.principal.disponivel():
                texto = self.principal.transcrever(arquivo, remover=False)
                if texto:
                    self.ultima_medicao = self.principal.ultima_medicao
                    self._origem(self.principal.nome, "")
                    return texto
                if not self.principal._erro or "excede" in self.principal._erro:
                    return ""  # silêncio de verdade, ou longo demais: a reserva não ajuda
                motivo = self.principal.diagnostico()
            else:
                motivo = self.principal.diagnostico()
            if not self.reserva.disponivel():
                return ""
            texto = self.reserva.transcrever(arquivo, remover=False)
            self.ultima_medicao = self.reserva.ultima_medicao
            if texto:
                self._origem("faster-whisper", motivo)
            return texto
        finally:
            if remover:
                try:
                    Path(arquivo).unlink(missing_ok=True)
                except OSError:
                    pass

    def _origem(self, origem, motivo):
        if origem != self.ultima_origem and self.ao_trocar is not None:
            try:
                self.ao_trocar(origem, motivo)
            except Exception:
                pass
        self.ultima_origem = origem


def com_escuta_remota(config, estado, local, ao_trocar=None):
    """Scribe na frente do faster-whisper, quando configurado (#68)."""
    if config.escuta_provedor != "scribe" or not config.openrouter_chave:
        return local
    from .gasto_voz import do_estado
    remota = OuvidosScribe(config.openrouter_chave, config.openrouter_url,
                           config.escuta_scribe_modelo, config.escuta_idioma,
                           gasto=do_estado(config, estado),
                           limite_segundos=local.limite_segundos)
    return OuvidosComReserva(remota, local, ao_trocar=ao_trocar)
