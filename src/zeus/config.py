"""Configuração do Zeus.

Segredos nunca entram no Git. A configuração vive em ~/.config/zeus/config.json
ou em variáveis de ambiente com prefixo ZEUS_. O arquivo de exemplo em
config/config.example.json documenta as chaves sem conter valores reais.
"""

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

CAMINHO_PADRAO = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "zeus" / "config.json"


@dataclass
class Config:
    provedor: str = "ollama"
    modelo: str = "llama3.1:8b-instruct-q4_K_M"
    ollama_url: str = "http://127.0.0.1:11434"
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_chave: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    modelo_conversa: str = ""
    keep_alive: str = "30m"
    limite_de_resposta: int = 320
    pesquisa_provedor: str = "nenhum"
    pesquisa_url: str = ""
    pesquisa_timeout: int = 10
    pesquisa_cache_minutos: int = 30
    pesquisa_max_fontes: int = 4
    persona: str = "config/persona.md"
    hud_host: str = "0.0.0.0"
    hud_porta: int = 8770
    chave_hud: str = ""
    voz_binario: str = "piper"
    voz_modelo: str = ""
    hud_tls: bool = True
    escuta_modelo: str = "small"
    escuta_computo: str = "int8"
    escuta_idioma: str = "pt"
    escuta_threads: int = 4
    escuta_beam: int = 1
    escuta_silencio_ms: int = 500
    escuta_vocabulario: str = ""
    temperatura_conversa: float = 0.75
    temperatura_decisao: float = 0.0
    turnos_de_conversa: int = 12
    intervalo_agenda: int = 30
    atraso_maximo_lembrete: int = 86400
    monitorar_modelo: bool = False
    intervalo_monitor: int = 30
    intervalo_recuperacao_modelo: int = 30
    espera_telegram: int = 25
    # Preenchido por carregar(): dizer de onde a configuração veio evita a
    # confusão de editar um arquivo que o programa nunca lê.
    origem: str = "nenhum arquivo lido"

    @property
    def canal_configurado(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)

    def sem_segredos(self) -> dict:
        """Representação segura para log: nenhum token aparece."""
        dados = {}
        for campo in fields(self):
            valor = getattr(self, campo.name)
            if campo.name in ("openrouter_chave", "telegram_token", "telegram_chat_id",
                              "chave_hud"):
                dados[campo.name] = "definido" if valor else "ausente"
            else:
                dados[campo.name] = valor
        return dados


def carregar(caminho: Path = None) -> Config:
    """Lê o arquivo, depois o ambiente. O ambiente tem prioridade."""
    caminho = Path(caminho) if caminho else CAMINHO_PADRAO
    dados = {}
    existe = caminho.exists()
    if existe:
        conteudo = json.loads(caminho.read_text(encoding="utf-8") or "{}")
        conhecidos = {campo.name for campo in fields(Config)}
        dados = {k: v for k, v in conteudo.items() if k in conhecidos}
    for campo in fields(Config):
        bruto = os.environ.get("ZEUS_" + campo.name.upper())
        if bruto is None or bruto == "":
            continue
        # O tipo vem do valor padrão, não da anotação: em Python 3.14 a
        # anotação pode chegar como texto, e um int viraria string em silêncio.
        padrao = campo.default
        if isinstance(padrao, bool):
            dados[campo.name] = bruto.strip().lower() in ("1", "true", "sim")
        elif isinstance(padrao, int):
            dados[campo.name] = int(bruto)
        elif isinstance(padrao, float):
            dados[campo.name] = float(bruto)
        else:
            dados[campo.name] = bruto
    dados.pop("origem", None)
    config = Config(**dados)
    config.origem = str(caminho) if existe else f"{caminho} (não existe; usando padrões)"
    return config
