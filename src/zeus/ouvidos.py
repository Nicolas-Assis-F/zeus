"""Escuta local com faster-whisper.

O microfone é o do aparelho que abre a interface: o navegador grava, manda o
áudio para o X99 e a transcrição acontece aqui, na CPU. O áudio não sai da rede
de casa em momento algum, que é a diferença entre isto e o ditado do navegador.

A GPU fica com o modelo de conversa. Com 24 threads, o Whisper small em int8
transcreve uma frase curta em poucos segundos, e é o suficiente para falar com
o Zeus sem teclado.

Como todo o resto, a ausência é dita: sem o pacote instalado, o botão de falar
aparece desligado com o motivo, em vez de gravar no vazio.
"""

import os
from pathlib import Path

TAMANHOS = ("tiny", "base", "small", "medium", "large-v3")


class Ouvidos:
    def __init__(self, modelo: str = "small", computo: str = "int8",
                 idioma: str = "pt", threads: int = 0, destino: Path = None):
        self.modelo = modelo
        self.computo = computo
        self.idioma = idioma
        self.threads = threads or (os.cpu_count() or 4)
        self.destino = Path(destino) if destino else Path("/tmp/zeus-escuta")
        self.destino.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._motor = None
        self._erro = ""

    # ------------------------------------------------------------ situação
    def instalado(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    def disponivel(self) -> bool:
        return self.instalado() and not self._erro

    def diagnostico(self) -> str:
        if not self.instalado():
            return ("faster-whisper não instalado "
                    "(pip install faster-whisper --break-system-packages)")
        if self._erro:
            return f"falhou ao carregar: {self._erro}"
        if self._motor is None:
            return f"pronta, modelo {self.modelo} ainda não carregado"
        return f"pronta, modelo {self.modelo} carregado"

    # ------------------------------------------------------------ operação
    def _carregar(self):
        """O modelo é carregado na primeira fala, não no início do processo.

        Na primeira vez ele é baixado, o que demora; começar o Zeus não pode
        depender disso."""
        if self._motor is not None or self._erro:
            return self._motor
        try:
            from faster_whisper import WhisperModel
            self._motor = WhisperModel(self.modelo, device="cpu",
                                       compute_type=self.computo,
                                       cpu_threads=self.threads)
        except Exception as erro:
            self._erro = str(erro)[:200]
            self._motor = None
        return self._motor

    def transcrever(self, arquivo) -> str:
        caminho = Path(arquivo)
        if not caminho.exists() or caminho.stat().st_size < 1024:
            return ""
        motor = self._carregar()
        if motor is None:
            return ""
        try:
            trechos, _ = motor.transcribe(str(caminho), language=self.idioma,
                                          vad_filter=True, beam_size=1)
            return " ".join(t.text.strip() for t in trechos).strip()
        except Exception as erro:
            self._erro = str(erro)[:200]
            return ""
        finally:
            try:
                caminho.unlink()
            except OSError:
                pass
