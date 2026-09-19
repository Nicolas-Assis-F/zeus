"""Interface do Zeus no navegador, servida pelo próprio processo."""

from .servidor import ServidorHUD, endereco_local, garantir_certificado

__all__ = ["ServidorHUD", "endereco_local", "garantir_certificado"]
