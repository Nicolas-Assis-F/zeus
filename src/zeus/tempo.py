"""Interpretação de momentos declarados em português.

Aceita ISO 8601, relógio do dia ("19:30", "amanhã 07:00") e deslocamento
relativo ("+30m", "+2h"). Um texto que não casa com nenhuma dessas formas é
recusado: adivinhar horário produz lembrete no momento errado, que é pior do
que perguntar de novo.
"""

import re
from datetime import datetime, timedelta, timezone

RELATIVO = re.compile(r"^\+(\d+)\s*(m|min|minutos?|h|horas?|d|dias?)$", re.IGNORECASE)
RELOGIO = re.compile(r"^(?:(hoje|amanh[ãa])\s+)?([01]?\d|2[0-3])[:h]([0-5]\d)$", re.IGNORECASE)


class MomentoInvalido(ValueError):
    pass


def interpretar(texto: str, agora: datetime) -> datetime:
    if not isinstance(texto, str) or not texto.strip():
        raise MomentoInvalido("Informe quando: ISO 8601, 'HH:MM', 'amanhã HH:MM' ou '+30m'.")
    bruto = texto.strip()
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=timezone.utc)

    casou = RELATIVO.match(bruto)
    if casou:
        quantidade = int(casou.group(1))
        unidade = casou.group(2).lower()
        if unidade.startswith("m"):
            return agora + timedelta(minutes=quantidade)
        if unidade.startswith("h"):
            return agora + timedelta(hours=quantidade)
        return agora + timedelta(days=quantidade)

    casou = RELOGIO.match(bruto)
    if casou:
        dia, hora, minuto = casou.groups()
        local = agora.astimezone()
        alvo = local.replace(hour=int(hora), minute=int(minuto), second=0, microsecond=0)
        if dia and dia.lower().startswith("amanh"):
            alvo = alvo + timedelta(days=1)
        elif alvo <= local:
            alvo = alvo + timedelta(days=1)
        return alvo.astimezone(timezone.utc)

    try:
        momento = datetime.fromisoformat(bruto)
    except ValueError:
        raise MomentoInvalido(
            f"Não consegui interpretar '{texto}'. Use ISO 8601, 'HH:MM', 'amanhã HH:MM' ou '+30m'."
        )
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=agora.astimezone().tzinfo)
    return momento.astimezone(timezone.utc)


def humano(momento: datetime) -> str:
    return momento.astimezone().strftime("%d/%m às %H:%M")
