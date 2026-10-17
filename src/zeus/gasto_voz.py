"""Teto diário de gasto com voz remota (ElevenLabs pelo OpenRouter).

Falar e ouvir pela nuvem custa por caractere e por segundo, e um laço errado
(uma resposta repetida, um microfone aberto) gasta sem ninguém ver. O contador
fica num arquivo próprio do estado do Zeus, fora do banco, e zera à meia-noite
local. Passou do teto, a voz cai para o Piper e a escuta para o faster-whisper:
o Zeus não fica mudo, só volta a soar como antes.

Aos 80% de qualquer um dos dois, `registrar` devolve um aviso, uma vez por dia
e por medida, para quem chamou entregar a Nicolas.
"""

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

ALERTA = 0.8

# Preço de tabela por unidade, sem o desconto de lançamento (que termina em
# 19/10/2026). Serve para estimar; o custo de verdade é o do OpenRouter.
PRECO_POR_CARACTERE = {
    "elevenlabs/eleven-v4-turbo": 40 / 1_000_000,
    "elevenlabs/eleven-v4": 80 / 1_000_000,
}
PRECO_POR_SEGUNDO = {"elevenlabs/scribe-v2": 0.000061}


class GastoDeVoz:
    def __init__(self, arquivo, teto_caracteres: int = 60000, teto_segundos: int = 3600,
                 avisar=None, hoje=None):
        self.arquivo = Path(arquivo)
        self.teto = {"caracteres": max(0, int(teto_caracteres)),
                     "segundos": max(0, int(teto_segundos))}
        self.avisar = avisar
        self.hoje = hoje or (lambda: datetime.now().date().isoformat())
        self._trava = threading.Lock()

    def _ler(self):
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        if dados.get("dia") != self.hoje():
            dados = {"dia": self.hoje(), "caracteres": 0, "segundos": 0.0,
                     "usd_estimado": 0.0, "avisos": []}
        return dados

    def _gravar(self, dados):
        self.arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporario = tempfile.mkstemp(dir=self.arquivo.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as saida:
            json.dump(dados, saida)
        os.chmod(temporario, 0o600)
        os.replace(temporario, self.arquivo)

    def hoje_gasto(self) -> dict:
        with self._trava:
            return self._ler()

    def pode(self, caracteres: int = 0, segundos: float = 0) -> bool:
        """Cabe no teto de hoje? Teto zero significa voz remota desligada."""
        with self._trava:
            dados = self._ler()
        if caracteres and dados["caracteres"] + caracteres > self.teto["caracteres"]:
            return False
        if segundos and dados["segundos"] + segundos > self.teto["segundos"]:
            return False
        return True

    def registrar(self, caracteres: int = 0, segundos: float = 0, usd: float = 0.0):
        """Soma o uso e devolve o texto do aviso de 80%, quando cruzou agora."""
        aviso = None
        with self._trava:
            dados = self._ler()
            dados["caracteres"] += int(caracteres)
            dados["segundos"] = round(dados["segundos"] + float(segundos), 3)
            dados["usd_estimado"] = round(dados["usd_estimado"] + float(usd), 6)
            for medida in ("caracteres", "segundos"):
                teto = self.teto[medida]
                if teto and dados[medida] >= ALERTA * teto and medida not in dados["avisos"]:
                    dados["avisos"].append(medida)
                    unidade = "caracteres de fala" if medida == "caracteres" else "segundos de escuta"
                    aviso = (f"Senhor, a voz remota já usou {int(dados[medida])} de "
                             f"{teto} {unidade} hoje (80%). Ao chegar no teto, volto "
                             "para a voz local até amanhã.")
            self._gravar(dados)
        if aviso and self.avisar is not None:
            try:
                self.avisar(aviso)
            except Exception:
                pass  # o aviso é cortesia; a contagem já está no disco
        return aviso


_POR_ESTADO = {}


def do_estado(config, estado, avisar=None) -> GastoDeVoz:
    """Um contador por diretório de estado, compartilhado por voz e escuta."""
    chave = str(Path(estado).expanduser())
    if chave not in _POR_ESTADO:
        _POR_ESTADO[chave] = GastoDeVoz(Path(chave) / "voz-gasto.json",
                                        config.voz_teto_caracteres_dia,
                                        config.escuta_teto_segundos_dia)
    gasto = _POR_ESTADO[chave]
    if avisar is not None:
        gasto.avisar = avisar
    return gasto
