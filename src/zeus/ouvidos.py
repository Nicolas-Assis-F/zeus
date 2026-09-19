"""Transcrição local em CPU, sem ocupar a GPU do modelo de conversa.

O modelo é reutilizado entre falas. Os diagnósticos distinguem pacote ausente,
carregamento pendente e erro recuperável; instalar o pacote não prova que um
microfone real já foi testado. O primeiro carregamento pode baixar o modelo.
"""

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
