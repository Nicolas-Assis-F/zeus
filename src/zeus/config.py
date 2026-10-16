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
    # Ligada por padrão. Desligada, o Zeus não sabe nada do mundo depois do
    # treino e responde de memória com cara de certeza — foi assim que ele
    # pareceu burro na primeira conversa de verdade. Quem quiser um Zeus sem
    # rede escreve "nenhum" aqui: é uma linha. A barreira contra página que
    # tenta mandar continua valendo de qualquer jeito.
    pesquisa_provedor: str = "duckduckgo"
    pesquisa_url: str = ""
    pesquisa_timeout: int = 10
    pesquisa_cache_minutos: int = 30
    pesquisa_max_fontes: int = 4
    pesquisa_max_bytes: int = 1_000_000
    pesquisa_max_paginas: int = 3
    # Pastas que o Zeus pode olhar. Vazio desliga as ações no computador.
    # A lista é dele por escolha de Nicolas, não por descoberta: o Zeus nunca
    # sai procurando o que mais existe na máquina.
    # Mapa de localização. O centro padrão é Goiânia; troque para a sua casa e
    # o mapa abre já olhando para o lugar certo.
    # Uma saudação por ligada da máquina, não por subida do processo.
    saudacao_ao_ligar: bool = True
    mapa_ativo: bool = True
    mapa_centro_lat: float = -16.6869
    mapa_centro_lon: float = -49.2648
    mapa_zoom: int = 13
    mapa_telas_url: str = ""
    mapa_busca_url: str = ""
    mapa_cache_mb: int = 200
    acoes_pastas: tuple = ()
    acoes_abrir: bool = False
    acoes_max_bytes: int = 200_000
    acoes_max_itens: int = 200
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
    # O Ollama assume 2048 tokens de contexto quando ninguém diz o contrário, e
    # corta o prompt pela frente sem avisar. A persona vive no começo, então o
    # que ele descartava era justamente a identidade -- e sobrava um assistente
    # genérico. Com 13 ferramentas no catálogo o prompt passa de 2900 tokens, o
    # que fazia isso acontecer em toda conversa.
    contexto_tokens: int = 8192
    # Amostragem. Temperatura sozinha não tira a rigidez: sem penalidade de
    # repetição o modelo pequeno cai nas mesmas construções toda resposta.
    topo_p: float = 0.92
    topo_k: int = 40
    penalidade_de_repeticao: float = 1.15
    temperatura_conversa: float = 0.75
    temperatura_decisao: float = 0.0
    turnos_de_conversa: int = 12
    teto_de_contexto: int = 600
    intervalo_agenda: int = 30
    atraso_maximo_lembrete: int = 86400
    monitorar_modelo: bool = False
    intervalo_monitor: int = 30
    intervalo_recuperacao_modelo: int = 30
    espera_telegram: int = 25
    # Canal de conversa: "telegram", "whatsapp" ou vazio (Telegram, se
    # configurado). Um canal de conversa por vez; a HUD vale sempre.
    canal: str = ""
    # WhatsApp pelo número do Zeus (ponte B): a API local da ponte, o banco
    # que ela grava, o grupo com Nicolas e quem nele pode dar ordem. Em grupo o
    # WhatsApp identifica o remetente pelo LID, não pelo telefone: use
    # `./zeus whatsapp` para descobrir os valores certos.
    whatsapp_ponte_url: str = "http://127.0.0.1:8081"
    whatsapp_banco: str = ""
    whatsapp_grupo: str = ""
    whatsapp_remetentes: tuple = ()
    # Número principal de Nicolas (ponte A), só leitura. Cada item é `jid` ou
    # `jid=Rótulo`; lista vazia desliga o vigia. O rótulo é o nome que o Zeus
    # usa no aviso, para não depender do nome que o próprio contato escolheu.
    principal_banco: str = ""
    principal_acompanhados: tuple = ()
    intervalo_principal: int = 15
    # Preenchido por carregar(): dizer de onde a configuração veio evita a
    # confusão de editar um arquivo que o programa nunca lê.
    origem: str = "nenhum arquivo lido"

    @property
    def canal_escolhido(self) -> str:
        whatsapp = bool(self.whatsapp_banco and self.whatsapp_grupo and self.whatsapp_remetentes)
        telegram = bool(self.telegram_token and self.telegram_chat_id)
        if self.canal == "whatsapp":
            return "whatsapp" if whatsapp else ""
        if self.canal in ("", "telegram"):
            return "telegram" if telegram else ""
        return ""

    @property
    def canal_configurado(self) -> bool:
        return bool(self.canal_escolhido)

    @property
    def vigia_configurado(self) -> bool:
        return bool(self.principal_banco and self.principal_acompanhados)

    def sem_segredos(self) -> dict:
        """Representação segura para log: nenhum token aparece."""
        dados = {}
        for campo in fields(self):
            valor = getattr(self, campo.name)
            if campo.name in ("openrouter_chave", "telegram_token", "telegram_chat_id",
                              "chave_hud", "whatsapp_grupo", "whatsapp_remetentes",
                              "principal_acompanhados"):
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
