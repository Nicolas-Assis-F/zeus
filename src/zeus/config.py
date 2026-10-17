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
    # Modelo por papel no OpenRouter. `modelo` conduz a conversa; vazio aqui é
    # o mesmo modelo. Um `modelo_ferramentas` diferente decide as ferramentas
    # e custa uma chamada a mais quando não há ferramenta a usar. A visão
    # descreve foto e vídeo recebidos.
    modelo_ferramentas: str = ""
    # Escada de modelos (#72): degraus de reserva depois do provedor acima,
    # como "openrouter:anthropic/claude-haiku-5.5" ou "ollama:llama3.1:8b-...".
    # Vazio é sem escada. O timeout vale para os degraus remotos.
    escada_reserva: tuple = ()
    escada_timeout_s: int = 60
    modelo_visao: str = ""
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
    # Voz e escuta remotas pela ElevenLabs no OpenRouter (#68), com a mesma
    # `openrouter_chave`. "piper"/"local" mantêm tudo em casa. A voz é um nome
    # da lista do OpenRouter (brian, george...) ou um voice_id da Voice Library.
    voz_provedor: str = "piper"
    voz_eleven_modelo: str = "elevenlabs/eleven-v4-turbo"
    voz_eleven_modelo_caprichado: str = "elevenlabs/eleven-v4"
    voz_eleven_voz: str = "brian"
    voz_caprichada_acima: int = 400
    # Teto diário; passou, cai para o local até a meia-noite. Aviso aos 80%.
    voz_teto_caracteres_dia: int = 60000
    escuta_teto_segundos_dia: int = 3600
    # Áudio de Nicolas no WhatsApp volta também como nota de voz.
    voz_resposta_em_audio: bool = True
    escuta_provedor: str = "local"
    escuta_scribe_modelo: str = "elevenlabs/scribe-v2"
    # Mídia do WhatsApp inclui áudio de terceiros (clientes, Henrique). Ligar
    # manda essas vozes ao Scribe; o texto delas já vai ao modelo remoto.
    escuta_scribe_midia: bool = False
    # Briefing da manhã (#74): "07:30" liga; vazio desliga. Só sai dentro da
    # janela depois da hora, uma vez por dia, em texto e (se houver voz) áudio.
    briefing_hora: str = ""
    briefing_janela_horas: int = 3
    briefing_audio: bool = True
    # Vigia de hardware (#76): avisa no grupo (e na sala, com a escuta no
    # ambiente ligada) quando o X99 passa dos limites por 3 leituras seguidas.
    hardware_vigia: bool = False
    hardware_cpu_celsius: int = 85
    hardware_gpu_celsius: int = 85
    hardware_ram_pct: int = 92
    hardware_disco_livre_pct: int = 10
    # Escuta no ambiente, pelo microfone da própria máquina (#68). Desligada
    # por padrão: microfone ouvindo a casa é decisão de Nicolas. Fonte e saída
    # são nomes de nó do PipeWire (`wpctl status`); vazio é o padrão do sistema.
    escuta_ambiente: bool = False
    escuta_ambiente_fonte: str = ""
    escuta_ambiente_saida: str = ""
    escuta_palavra: str = "hey_jarvis"
    escuta_palavra_limiar: float = 0.5
    escuta_fim_silencio_ms: int = 800
    escuta_continuacao_s: float = 6.0
    escuta_reconhecimento: str = "Deixa comigo, senhor."
    escuta_reconhecimento_apos_s: float = 1.5
    escuta_ao_acordar: str = ""
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
    # Só abrevia respostas antigas do assistente no prompt. Registros e falas
    # do dono permanecem íntegros; pedidos em foco vêm dos dados estruturados.
    historico_resposta_caracteres: int = 2000
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
    # Pontos quentes: conversa 1:1 no número principal de alguém do CRM da LE
    # (`leads.json`). A sessão da ponte A (`whatsapp.db`) liga LID a telefone;
    # vazio, usa a que fica ao lado de `principal_banco`. Os níveis listados
    # viram aviso no grupo, e Nicolas libera ou bloqueia o contato.
    principal_crm: str = ""
    principal_ponte_url: str = "http://127.0.0.1:8080"
    # Habilitado por Nicolas para atuar como secretário no número principal.
    # O executor ainda exige comando de envio e registra resultado incerto.
    principal_envio_ativo: bool = False
    # Mídia do WhatsApp (#60): teto antes de baixar, duração máxima de áudio
    # (o microfone da HUD tem o dele) e threads da transcrição. A visão usa
    # `modelo_visao`, ou o próprio modelo do OpenRouter.
    midia_max_mb: int = 25
    midia_audio_segundos: int = 900
    midia_threads: int = 8
    # Orçamentos de teste (#62): PDF, registro e sequência, fora de qualquer git.
    # Os preços vêm de precos.json, na base de conhecimento.
    orcamentos_pasta: str = "~/.local/share/zeus/orcamentos"
    # Repasse para o Claude Code do X99 (#64): `nome=caminho` de cada
    # repositório, limite de tempo e de gasto por tarefa. Vazio desliga.
    documentos_pasta: str = "~/.local/share/zeus/documentos"
    tarefas_orca_bin: str = "/home/zeus/.local/bin/orca-ide"
    tarefas_agentes: tuple = ("codex", "claude")
    tarefas_coordenador: str = ""
    tarefas_projetos: tuple = ()
    tarefas_pasta: str = "~/.local/share/zeus/tarefas"
    tarefas_minutos: int = 45
    tarefas_usd: float = 5.0
    # Base de conhecimento (preços, importação, clientes), fora de qualquer
    # repositório. Escrita só por Nicolas e pelo Claude: é fonte confiável.
    base_conhecimento: str = "~/.local/share/zeus/conhecimento"
    principal_sessao: str = ""
    quentes_niveis: tuple = ("quente", "morno")
    quentes_tipos_ignorados: tuple = ("fornecedor", "concorrente", "transportadora")
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

    @property
    def quentes_configurado(self) -> bool:
        return bool(self.principal_banco and self.principal_crm)

    @property
    def sessao_principal(self) -> str:
        if self.principal_sessao or not self.principal_banco:
            return self.principal_sessao
        return os.path.join(os.path.dirname(self.principal_banco), "whatsapp.db")

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
