"""Canais de contato. Mesma identidade, mesma situação, formatos diferentes."""

from .memoria import CanalMemoria
from .telegram import CanalTelegram, ErroDeCanal

__all__ = ["CanalMemoria", "CanalTelegram", "ErroDeCanal"]
