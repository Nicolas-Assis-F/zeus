"""Canais de contato. Mesma identidade, mesma situação, formatos diferentes."""

from .memoria import CanalMemoria
from .telegram import CanalTelegram, ErroDeCanal
from .whatsapp import CanalWhatsApp


def montar_canal(config, store=None):
    """O canal de conversa escolhido na configuração, ou None."""
    escolhido = config.canal_escolhido
    if escolhido == "whatsapp":
        return CanalWhatsApp(config.whatsapp_ponte_url, config.whatsapp_banco,
                             config.whatsapp_grupo, config.whatsapp_remetentes, store)
    if escolhido == "telegram":
        return CanalTelegram(config.telegram_token, config.telegram_chat_id, store,
                             espera=config.espera_telegram)
    return None


__all__ = ["CanalMemoria", "CanalTelegram", "CanalWhatsApp", "ErroDeCanal", "montar_canal"]
