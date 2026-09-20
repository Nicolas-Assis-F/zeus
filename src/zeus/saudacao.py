"""A primeira frase quando a máquina liga.

Nicolas quis que o Zeus já estivesse de pé, com uma saudação, quando o
computador acende. A parte difícil não é falar: é falar uma vez.

Um serviço reinicia. Reinicia por atualização, por falha do modelo, por queda
de rede, e — quando algo está errado — reinicia muitas vezes seguidas. Um
"bom dia, senhor" a cada reinício é a diferença entre presença e alarme.

O freio é o identificador de boot do kernel: ele muda quando a máquina liga e
não muda quando um serviço reinicia. Usado como chave da fila de saída — que
já é idempotente por chave e já sabe reenviar o que não foi confirmado — ele
dá exatamente a regra que se quer: uma saudação por ligada da máquina, não por
subida do processo, e ainda assim entregue de verdade.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

ARQUIVO_DE_BOOT = Path("/proc/sys/kernel/random/boot_id")
PEDIDO = ("A máquina acabou de ligar e você está de pé. Cumprimente Nicolas em "
          "uma ou duas frases, do jeito que você fala, dizendo que está pronto. "
          "Se houver pendência importante no contexto, mencione em meia frase. "
          "Nada de listar capacidades nem de se apresentar.")


def identificador_de_boot(arquivo: Path = ARQUIVO_DE_BOOT) -> str:
    """Muda quando a máquina liga; não muda quando o serviço reinicia."""
    try:
        return arquivo.read_text(encoding="utf-8").strip()[:64]
    except OSError:
        return ""


def parte_do_dia(agora: datetime) -> str:
    hora = agora.hour
    if hora < 5:
        return "Boa madrugada"
    if hora < 12:
        return "Bom dia"
    if hora < 18:
        return "Boa tarde"
    return "Boa noite"


def frase_reserva(agora: datetime, pendentes: int = 0) -> str:
    """Quando o modelo não está de pé, a saudação ainda acontece.

    Uma máquina que liga sem dizer nada parece quebrada. Dizer a verdade —
    de pé, sem modelo — é melhor que silêncio e melhor que fingir."""
    inicio = f"{parte_do_dia(agora)}, senhor. Estou de pé."
    if pendentes == 1:
        return inicio + " Tem uma pendência esperando."
    if pendentes > 1:
        return inicio + f" Tem {pendentes} pendências esperando."
    return inicio


def chave_do_boot(boot: str) -> str:
    return f"saudacao:{boot}"


def deve_saudar(reservar, boot: str, ligada: bool = True) -> bool:
    """Uma saudação por ligada da máquina.

    `reservar(chave)` devolve True só na primeira vez — é a fila de saída, que
    já é idempotente por chave. Sem identificador de boot, em sistema que não
    expõe o arquivo, a saudação fica de fora em vez de virar a cada reinício:
    falar demais é pior que não falar."""
    if not ligada or not boot:
        return False
    return bool(reservar(chave_do_boot(boot)))


def compor(store, reservar, responder, agora: datetime, boot: str,
           ligada: bool = True, canal: str = "hud"):
    """Devolve a saudação, ou None quando não é hora de saudar.

    `responder` é o que fala com o modelo. Se ele falhar por qualquer motivo,
    a frase de reserva entra: a saudação não pode depender de o modelo estar
    pronto no primeiro segundo depois do boot."""
    if not deve_saudar(reservar, boot, ligada):
        return None
    pendentes = len(store.perguntas_abertas()) + len(store.agenda_pendente())
    try:
        texto = (responder(PEDIDO, canal) or "").strip()
    except Exception:
        texto = ""
    return texto or frase_reserva(agora, pendentes)
