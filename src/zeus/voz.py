"""Voz local do Zeus, com Piper.

Escolha honesta para o hardware que existe: o 8B ocupa a VRAM, então a síntese
fica na CPU, e o Xeon de 24 threads dá conta. Piper roda como binário próprio,
com modelo em disco, sem depender de nuvem e sem microfone — falar não exige
ouvir, e é o lado da voz que dá para entregar hoje inteiro em casa.

Se o Piper não estiver instalado, nada quebra: o Zeus continua escrevendo. Uma
capacidade ausente é dita em voz alta, nunca simulada.
"""

import hashlib
import shutil
import subprocess
import tempfile
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
        nome = hashlib.sha256((str(self.modelo) + recorte).encode("utf-8")).hexdigest()[:24]
        arquivo = self.destino / f"{nome}.wav"
        if arquivo.exists():
            return arquivo
        try:
            subprocess.run(
                [self.binario, "--model", str(self.modelo), "--output_file", str(arquivo)],
                input=recorte.encode("utf-8"),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=120, check=True,
            )
        except (subprocess.SubprocessError, OSError):
            if arquivo.exists():
                arquivo.unlink()
            return None
        return arquivo if arquivo.exists() else None
