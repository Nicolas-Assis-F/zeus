"""Comandos do Zeus.

Esta versão conversa com persona, guarda memória explícita, agenda perguntas e
lembretes e entrega no Telegram quando o canal está configurado. Nada além
disso: sem visão, sem telefonia, sem dispositivo doméstico.
"""

import argparse
import json
import os
import queue
import secrets
import signal
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

from . import __version__
from .config import carregar as carregar_config
from .ferramentas import Ferramentas
from .execucao import (CaixaDeEntrada, FalaEmSegundoPlano, RecepcaoTelegram,
                       InstanciaUnica, EstadoOperacao, SupervisorPresenca)
from .entregas import Entregas
from .llm import ErroDeModelo, criar_provedor
from .nucleo import Zeus
from .persona import Persona
from .pesquisa import Pesquisa
from .ouvidos import Ouvidos
from .store import Store
from .voz import Voz

SEM_MODELO = (
    "Não consigo falar agora: o modelo não respondeu à verificação. "
    "Sua mensagem foi registrada e nada foi inventado."
)


def com_aviso_de_digitacao(canal, tarefa):
    """Mantém o aviso de digitação vivo enquanto a resposta é gerada.

    O Telegram apaga o aviso depois de poucos segundos, e uma resposta local
    demora mais que isso. Sem a repetição, o silêncio parece travamento."""
    aviso = getattr(canal, "digitando", None)
    if aviso is None:
        return tarefa()
    parar = Event()

    def bater():
        while not parar.is_set():
            aviso()
            parar.wait(4)

    pulso = Thread(target=bater, daemon=True)
    pulso.start()
    try:
        return tarefa()
    finally:
        parar.set()
        pulso.join(timeout=2)


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def montar(args):
    config = carregar_config(getattr(args, "config", None))
    store = Store(args.state_dir.expanduser())
    persona = Persona.carregar(config.persona)
    pesquisa = montar_pesquisa(config, args.state_dir.expanduser())
    ferramentas = Ferramentas(store, pesquisa=pesquisa)
    canal = None
    if config.canal_configurado:
        from .canais import CanalTelegram
        canal = CanalTelegram(config.telegram_token, config.telegram_chat_id, store,
                              espera=config.espera_telegram)
    return config, store, Zeus(store, None, persona, ferramentas, config, canal)


def montar_pesquisa(config, estado):
    """Pesquisa é escolha explícita: sem provedor configurado, ela não existe."""
    return Pesquisa(provedor=config.pesquisa_provedor, url_base=config.pesquisa_url,
                    timeout=config.pesquisa_timeout,
                    cache_minutos=config.pesquisa_cache_minutos,
                    maximo_de_fontes=config.pesquisa_max_fontes,
                    maximo_de_bytes=config.pesquisa_max_bytes,
                    maximo_de_paginas=config.pesquisa_max_paginas,
                    destino=Path(estado) / "pesquisa")


def montar_voz(config):
    return Voz(config.voz_binario, config.voz_modelo)


def montar_ouvidos(config, estado):
    return Ouvidos(config.escuta_modelo, config.escuta_computo, config.escuta_idioma,
                   threads=config.escuta_threads, destino=Path(estado) / "escuta",
                   beam_size=config.escuta_beam, silencio_ms=config.escuta_silencio_ms,
                   vocabulario=config.escuta_vocabulario)


def retrato(store, config, voz, modelo="", ouvidos=None):
    """O que a HUD mostra: memória confirmada, pendências e conversa recente."""
    return {
        "tipo": "estado",
        "fatos": store.fatos("confirmado"),
        "perguntas": store.perguntas_abertas(),
        "lembretes": store.agenda_pendente(),
        "turnos": store.turnos(20),
        "entregas": Entregas(store).listar(20),
        "entradas": Entregas(store).entradas(),
        "modelo": modelo or config.modelo,
        "voz": voz.disponivel() if voz else False,
        "ouvidos": ouvidos.disponivel() if ouvidos else False,
        "motivo_ouvidos": ouvidos.diagnostico() if ouvidos else "desligada",
    }


def ligar_modelo(zeus, config):
    """Verificação obrigatória antes de usar o modelo em qualquer conversa."""
    provedor = criar_provedor(config)
    servido = provedor.verificar()
    zeus.provedor = provedor
    return servido


def main():
    parser = argparse.ArgumentParser(description="Zeus")
    default_state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "zeus"
    parser.add_argument("--state-dir", type=Path, default=default_state)
    parser.add_argument("--config", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)

    verificacao = commands.add_parser("check", help="Verificar armazenamento, modelo e canal")
    verificacao.add_argument("--modelo", action="store_true", help="Também verificar o modelo")
    verificacao.add_argument("--canal", action="store_true", help="Também verificar o Telegram")

    commands.add_parser("run", help="Manter o Zeus em execução")
    commands.add_parser("agenda", help="Listar perguntas e lembretes pendentes")
    commands.add_parser("entregas", help="Mostrar estados de saída e entradas incertas")
    backup = commands.add_parser("backup", help="Criar cópia consistente sem sobrescrever")
    backup.add_argument("destino", type=Path)
    resolver = commands.add_parser("resolver-entrega", help="Resolver saída incerta conscientemente")
    resolver.add_argument("chave")
    resolver.add_argument("acao", choices=['confirmar', 'reenviar', 'descartar'])
    entrada = commands.add_parser("resolver-entrada", help="Reprocessar pode repetir ações; use após conferir")
    entrada.add_argument("id", type=int)
    entrada.add_argument("acao", choices=['reprocessar', 'descartar'])

    avaliacao_cmd = commands.add_parser(
        "avaliar", help="Rodar as jornadas de avaliação e dizer a origem da evidência")
    avaliacao_cmd.add_argument("--jornadas", default=None)
    avaliacao_cmd.add_argument("--real", action="store_true",
                               help="Falar com o modelo instalado em vez do dublê")
    avaliacao_cmd.add_argument("--relatorio", default=None,
                               help="Onde gravar o relatório em JSON")

    persona_cega_cmd = commands.add_parser(
        "avaliar-persona",
        help="Comparar variantes de persona.md com julgamento cego")
    persona_cega_cmd.add_argument("--variantes", default="",
                                  help="Arquivos de persona separados por vírgula")
    persona_cega_cmd.add_argument("--jornadas", default=None)
    persona_cega_cmd.add_argument("--real", action="store_true",
                                  help="Falar com o modelo instalado em vez do dublê")
    persona_cega_cmd.add_argument("--folha", default=None,
                                  help="Onde gravar a folha cega para julgar")
    persona_cega_cmd.add_argument("--rodada", default=None,
                                  help="Onde gravar (ou de onde ler) a rodada com o gabarito selado")
    persona_cega_cmd.add_argument("--revelar", action="store_true",
                                  help="Revelar o agregado a partir de --rodada e --julgamento")
    persona_cega_cmd.add_argument("--julgamento", default=None,
                                  help="JSON com as notas por rótulo, para revelar")

    medicao = commands.add_parser("medir", help="Comparar modelos com números, não com palpite")
    medicao.add_argument("--modelos", default="",
                         help="Lista separada por vírgula; sem isso, mede o configurado")
    medicao.add_argument("--repeticoes", type=int, default=3)
    commands.add_parser("preparar-escuta", help="Baixar e verificar o modelo de escuta")
    escuta = commands.add_parser("medir-escuta", help="Medir um áudio local sem apagá-lo")
    escuta.add_argument("arquivo", type=Path)
    escuta.add_argument("--repeticoes", type=int, default=2)
    contexto_cmd = commands.add_parser(
        "persona", help="Mostrar o contexto que o modelo recebe e o que ficou de fora")
    contexto_cmd.add_argument("--mensagem", default="",
                              help="Simula uma mensagem, para ver o que ela traria da memória")

    remember = commands.add_parser("remember", help="Registrar um fato explícito")
    remember.add_argument("key")
    remember.add_argument("value")
    remember.add_argument("--source", default="user")
    remember.add_argument("--estado", default="confirmado",
                          choices=["confirmado", "hipotese", "observacao"])
    recall = commands.add_parser("recall", help="Consultar um fato")
    recall.add_argument("key")
    forget = commands.add_parser("forget", help="Remover um fato da memória ativa")
    forget.add_argument("key")

    conversa = commands.add_parser("conversar", help="Uma troca pelo terminal")
    conversa.add_argument("texto")

    evento = commands.add_parser("evento", help="Registrar um acontecimento observado")
    evento.add_argument("tipo")
    evento.add_argument("resumo")
    evento.add_argument("--simulado", action="store_true",
                        help="Marca o episódio como simulado, para teste honesto")

    args = parser.parse_args()
    os.umask(0o077)
    config, store, zeus = montar(args)

    try:
        if args.command == "check":
            integrity = store.connection.execute("PRAGMA quick_check").fetchone()[0]
            modelo, canal = "não verificado", "não verificado"
            modelo_verificado = True
            if args.modelo:
                try:
                    modelo = ligar_modelo(zeus, config)
                except ErroDeModelo as erro:
                    modelo = f"falhou: {erro}"
                    modelo_verificado = False
            if args.canal:
                canal = "ausente" if zeus.canal is None else zeus.canal.verificar()
            voz = montar_voz(config)
            ouvidos = montar_ouvidos(config, args.state_dir.expanduser())
            emit("storage_check", version=__version__, storage=integrity,
                 modelo=modelo, canal=canal, voz=voz.diagnostico(),
                 ouvidos=ouvidos.diagnostico(),
                 pesquisa=montar_pesquisa(config, args.state_dir.expanduser()).diagnostico(),
                 hud="configurada" if config.chave_hud else "sem chave definida",
                 config=config.sem_segredos())
            return 0 if integrity == "ok" and modelo_verificado else 1

        if args.command == "remember":
            store.remember(args.key, args.value, args.source, args.estado)
            emit("remembered", key=args.key, estado=args.estado)
        elif args.command == "recall":
            fact = store.recall(args.key)
            emit("recalled", key=args.key, fact=fact)
            return 0 if fact is not None else 1
        elif args.command == "forget":
            emit("forgotten", key=args.key, removed=store.forget(args.key))
        elif args.command == "entregas":
            fila = Entregas(store)
            emit('entregas', saidas=fila.listar(), entradas=fila.entradas())
        elif args.command == "backup":
            emit('backup', arquivo=str(store.backup(args.destino)))
        elif args.command == "resolver-entrega":
            Entregas(store).resolver(args.chave, args.acao)
            emit('entrega_resolvida', chave=args.chave, acao=args.acao)
        elif args.command == "resolver-entrada":
            Entregas(store).resolver_entrada(args.id, args.acao)
            emit('entrada_resolvida', id=args.id, acao=args.acao)
        elif args.command == "agenda":
            emit("agenda", perguntas=store.perguntas_abertas(),
                 lembretes=store.agenda_pendente())
        elif args.command in ("preparar-escuta", "medir-escuta"):
            ouvidos = montar_ouvidos(config, args.state_dir.expanduser())
            if args.command == "preparar-escuta":
                pronto = ouvidos.preparar()
                emit("escuta_preparada", pronta=pronto, detalhe=ouvidos.diagnostico())
                return 0 if pronto else 3
            if not args.arquivo.is_file():
                raise ValueError("Arquivo de áudio não encontrado.")
            falhou = False
            for tentativa in range(max(1, args.repeticoes)):
                ouvidos.transcrever(args.arquivo, remover=False)
                medicao = ouvidos.ultima_medicao
                falhou = falhou or not bool(medicao)
                emit("medicao_escuta", tentativa=tentativa + 1, modelo=ouvidos.modelo,
                     threads=ouvidos.threads, beam=ouvidos.beam_size,
                     detalhe=ouvidos.diagnostico(), **medicao)
            return 3 if falhou else 0
        elif args.command == "persona":
            montado = zeus.persona.montar(
                store.fatos(), store.perguntas_abertas(), store.agenda_pendente(),
                datetime.now(timezone.utc), capacidades=zeus.capacidades, mensagem=args.mensagem,
                teto=config.teto_de_contexto)
            print(montado["texto"])
            escolha = montado["escolha"]
            print()
            emit("contexto", teto=escolha["teto"], tokens=escolha["tokens"],
                 nucleo=len(escolha["nucleo"]), hipoteses=len(escolha["hipoteses"]),
                 trazidos_pela_mensagem=len(escolha["trazidos"]),
                 fora=[f["key"] for f in escolha["fora"]])
        elif args.command == "evento":
            episodio = zeus.perceber(args.tipo, args.resumo, simulado=args.simulado)
            emit("episodio_aberto", id=episodio, simulado=args.simulado)
        elif args.command == "avaliar":
            return avaliar(config, args)
        elif args.command == "avaliar-persona":
            return avaliar_persona(config, args)
        elif args.command == "medir":
            return medir(config, zeus, args)
        elif args.command == "conversar":
            ligar_modelo(zeus, config)
            print(zeus.conversar(args.texto, canal="cli"))
        elif args.command == "run":
            return executar(zeus, store, config)
        return 0
    except ErroDeModelo as erro:
        print(str(erro), file=sys.stderr)
        return 3
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        store.close()


def avaliar(config, args):
    """Roda as jornadas e diz, em toda linha, de onde veio a evidência."""
    import tempfile

    from .avaliacao import Avaliacao, carregar_jornadas, em_texto

    jornadas = carregar_jornadas(args.jornadas)
    provedor, origem = None, "simulada"
    if args.real:
        provedor = criar_provedor(config)
        provedor.verificar()
        origem = "hardware"

    with tempfile.TemporaryDirectory() as temporario:
        avaliacao = Avaliacao(config, temporario, provedor=provedor, origem=origem,
                              pesquisa=montar_pesquisa(config, temporario)
                              if "montar_pesquisa" in globals() else None)
        relatorio = avaliacao.rodar(jornadas)

    print(em_texto(relatorio))
    if args.relatorio:
        Path(args.relatorio).write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
        emit("relatorio_gravado", arquivo=args.relatorio)
    return 1 if relatorio["resumo"]["falhou"] else 0


def avaliar_persona(config, args):
    """Duas fases num comando. Sem --revelar: roda as variantes e grava a folha
    cega para Nicolas julgar. Com --revelar: liga rótulo a variante e agrega."""
    import tempfile

    from .persona_cega import (AvaliacaoCegaDePersona, carregar_jornadas_de_persona,
                               em_texto_revelacao, folha_cega, gravar_historico,
                               revelar)

    if args.revelar:
        if not (args.rodada and args.julgamento):
            emit("erro", detalhe="--revelar precisa de --rodada e --julgamento")
            return 2
        rodada = json.loads(Path(args.rodada).read_text(encoding="utf-8"))
        julgamento = json.loads(Path(args.julgamento).read_text(encoding="utf-8"))
        revelacao = revelar(rodada, julgamento)
        print(em_texto_revelacao(revelacao))
        destino = gravar_historico(
            args.state_dir.expanduser() / "persona_cega", revelacao)
        emit("revelacao_gravada", arquivo=str(destino))
        return 0

    variantes = [v.strip() for v in (args.variantes or "").split(",") if v.strip()]
    if len(variantes) < 2:
        emit("erro", detalhe="informe ao menos duas variantes em --variantes")
        return 2

    jornadas = carregar_jornadas_de_persona(args.jornadas)
    provedor, origem = None, "simulada"
    if args.real:
        provedor = criar_provedor(config)
        provedor.verificar()
        origem = "hardware"

    with tempfile.TemporaryDirectory() as temporario:
        avaliacao = AvaliacaoCegaDePersona(config, temporario, variantes,
                                           provedor=provedor, origem=origem)
        rodada = avaliacao.gerar(jornadas)

    folha = folha_cega(rodada)
    caminho_folha = args.folha or "persona-cega-folha.json"
    Path(caminho_folha).write_text(
        json.dumps(folha, ensure_ascii=False, indent=1), encoding="utf-8")
    caminho_rodada = args.rodada or "persona-cega-rodada.json"
    Path(caminho_rodada).write_text(
        json.dumps(rodada, ensure_ascii=False, indent=1), encoding="utf-8")
    emit("folha_cega_gravada", folha=caminho_folha, rodada=caminho_rodada,
         origem=origem, variantes=len(variantes),
         aviso=("dublê: não vale como evidência de tom; rode --real no X99"
                if origem == "simulada" else "modelo real"))
    return 0


PROVA_DE_CONVERSA = "Me conta em duas frases o que você faz por mim."
PROVA_DE_FERRAMENTA = "me lembra de tomar água daqui 30 minutos"


def medir(config, zeus, args):
    """Compara modelos com números do próprio servidor.

    Três coisas decidem a escolha e nenhuma delas é impressão: quanto tempo até
    a primeira palavra, quantos tokens por segundo depois dela, e se o modelo
    consegue usar uma ferramenta quando a frase pede uma. Um modelo veloz que
    erra a chamada não serve; um modelo certeiro que demora meio minuto também
    não."""
    from .llm import ProvedorOllama

    modelos = [m.strip() for m in args.modelos.split(",") if m.strip()] or [config.modelo]
    sistema = zeus.persona.sistema(agora=datetime.now(timezone.utc))
    catalogo = zeus.ferramentas.catalogo()

    for nome in modelos:
        provedor = ProvedorOllama(config.ollama_url, nome, keep_alive=config.keep_alive,
                                  limite_de_resposta=config.limite_de_resposta)
        try:
            provedor.verificar()
        except ErroDeModelo as erro:
            emit("medicao", modelo=nome, erro=str(erro)[:160])
            continue

        primeiras, geracoes, leituras, acertos = [], [], [], 0
        for _ in range(max(1, args.repeticoes)):
            marca = {"inicio": time.perf_counter(), "primeira": None}

            def cronometrar(_pedaco):
                if marca["primeira"] is None:
                    marca["primeira"] = time.perf_counter() - marca["inicio"]

            conversa = provedor.conversar_em_fluxo(
                [{"role": "system", "content": sistema},
                 {"role": "user", "content": PROVA_DE_CONVERSA}],
                temperatura=config.temperatura_conversa, ao_receber=cronometrar)
            if marca["primeira"] is not None:
                primeiras.append(marca["primeira"])
            estatisticas = conversa.estatisticas
            if estatisticas.get("eval_duration"):
                geracoes.append(estatisticas["eval_count"] * 1e9 / estatisticas["eval_duration"])
            if estatisticas.get("prompt_eval_duration"):
                leituras.append(estatisticas["prompt_eval_count"] * 1e9
                                / estatisticas["prompt_eval_duration"])

            uso = provedor.conversar(
                [{"role": "system", "content": sistema},
                 {"role": "user", "content": PROVA_DE_FERRAMENTA}],
                ferramentas=catalogo, temperatura=0.0)
            nomes = {c["nome"] for c in uso.chamadas}
            if nomes & {"agendar_lembrete", "agendar_pergunta"}:
                acertos += 1

        def media(valores):
            return round(sum(valores) / len(valores), 2) if valores else None

        emit("medicao", modelo=nome,
             primeira_palavra_s=media(primeiras),
             geracao_tokens_s=media(geracoes),
             leitura_tokens_s=media(leituras),
             ferramenta_acertos=f"{acertos}/{max(1, args.repeticoes)}")
    return 0


def executar(zeus, store, config):
    with InstanciaUnica(Path(store.path).parent):
        return _executar(zeus, store, config)


def _executar(zeus, store, config):
    stopped = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())

    operacao = EstadoOperacao()
    fila_de_saida = Entregas(store)
    modelo_ok = False
    try:
        servido = ligar_modelo(zeus, config)
        modelo_ok = True
    except ErroDeModelo as erro:
        servido = f"indisponível: {erro}"

    operacao.atualizar('modelo', estado='pronta' if modelo_ok else 'indisponivel')
    proxima_recuperacao = time.monotonic() + max(5, config.intervalo_recuperacao_modelo)
    voz = montar_voz(config)
    estado_local = Path(store.path).parent
    ouvidos = montar_ouvidos(config, estado_local)
    recebidas_da_hud = CaixaDeEntrada(maxsize=32)
    hud, endereco = None, None
    chave = config.chave_hud or secrets.token_urlsafe(12)
    try:
        from .hud import ServidorHUD, endereco_local, garantir_certificado
        certificado, chave_tls = (None, None)
        if config.hud_tls:
            # Sem origem segura o navegador não libera o microfone, e o Zeus
            # ficaria sem ouvidos justamente no aparelho que tem microfone.
            certificado, chave_tls = garantir_certificado(estado_local / "tls")
            if certificado is None:
                emit("tls_indisponivel", detalhe="openssl ausente; a HUD sobe sem TLS")
        hud = ServidorHUD(
            enfileirar=recebidas_da_hud.put_nowait, voz=voz, chave=chave,
            host=config.hud_host, porta=config.hud_porta,
            estado=retrato(store, config, voz, servido if modelo_ok else "", ouvidos),
            pasta_de_escuta=ouvidos.destino,
            certificado=certificado, chave_tls=chave_tls)
        porta = hud.iniciar()
        esquema = "https" if hud.seguro else "http"
        endereco = f"{esquema}://{endereco_local()}:{porta}/?chave={chave}"
    except Exception as erro:
        emit("hud_indisponivel", detalhe=str(erro)[:200])

    emit("started", version=__version__, modelo=servido, modelo_ok=modelo_ok,
         canal=(zeus.canal.nome if zeus.canal else "nenhum"),
         voz=voz.diagnostico(), ouvidos=ouvidos.diagnostico(),
         hud=endereco or "desligada")

    def anunciar(de, texto, audio=None):
        if hud is None:
            return
        hud.publicar("mensagem", de=de, texto=texto, audio=audio,
                     hora=datetime.now().strftime("%H:%M"))
        hud.atualizar(retrato(store, config, voz, servido if modelo_ok else "", ouvidos))

    def responder(texto, canal, em_fluxo=False):
        """Uma pergunta, uma resposta, a mesma identidade em qualquer canal."""
        if not modelo_ok:
            store.registrar_turno(canal, "nicolas", texto)
            return SEM_MODELO
        if not (em_fluxo and hud is not None):
            return zeus.conversar(texto, canal=canal)

        def empurrar(pedaco):
            if pedaco is None:
                hud.publicar("fluxo", reiniciar=True)
            else:
                hud.publicar("fluxo", pedaco=pedaco)

        return zeus.conversar(texto, canal=canal, ao_receber=empurrar)

    fala = FalaEmSegundoPlano(voz, hud.publicar) if hud is not None else None
    supervisor = SupervisorPresenca(estado_local, config, stopped, hud, operacao)
    supervisor.iniciar()
    if not supervisor.pronto.wait(5) or operacao.retrato().get('agenda', {}).get('estado') == 'indisponivel':
        stopped.set()
        supervisor.parar()
        if fala:
            fala.parar()
        if hud:
            hud.parar()
        raise ValueError('Não foi possível iniciar a agenda persistente.')
    recepcao = None
    if zeus.canal is not None:
        def criar_receptor():
            from .canais import CanalTelegram
            return CanalTelegram(config.telegram_token, config.telegram_chat_id,
                                 Store(estado_local), espera=config.espera_telegram)
        recepcao = RecepcaoTelegram(criar_receptor, recebidas_da_hud, stopped)
        recepcao.iniciar()
    ultimo_batimento = 0.0
    while not stopped.is_set():
        try:
            if not modelo_ok and time.monotonic() >= proxima_recuperacao:
                try:
                    servido = ligar_modelo(zeus, config)
                    modelo_ok = True
                    operacao.atualizar('modelo', estado='pronta')
                except ErroDeModelo:
                    operacao.atualizar('modelo', estado='indisponivel')
                proxima_recuperacao = time.monotonic() + max(5, config.intervalo_recuperacao_modelo)
            for _ in range(4):
                try:
                    pedido = recebidas_da_hud.get_nowait()
                except queue.Empty:
                    break
                geracao = fala.invalidar() if fala else 0
                if hud is not None:
                    hud.publicar("situacao", estado="pensando", detalhe="recebido", geracao=geracao)
                zeus.capacidades = {"voz": voz.disponivel(), "ouvidos": ouvidos.disponivel(),
                                    "pesquisa": zeus.ferramentas.pesquisa.disponivel()
                                    if zeus.ferramentas.pesquisa else False}
                if pedido.get("tipo") == "telegram":
                    recebidas = pedido["mensagens"]
                    chave_resposta = fila_de_saida.iniciar_resposta(recebidas)
                    try:
                        if chave_resposta is None:
                            continue
                        texto = "\n".join(m["texto"] for m in recebidas)
                        anunciar("nicolas", texto)
                        resposta = com_aviso_de_digitacao(
                            zeus.canal, lambda: responder(texto, "telegram"))
                        fila_de_saida.concluir_resposta(chave_resposta, resposta)
                        anunciar("zeus", resposta)
                    except Exception:
                        if chave_resposta:
                            fila_de_saida.resposta_incerta(chave_resposta)
                        raise
                    finally:
                        pedido["terminado"].set()
                    continue
                texto = pedido.get("texto", "")
                if pedido.get("tipo") == "audio":
                    if hud is not None:
                        hud.publicar("situacao", estado="ouvindo",
                                     detalhe="transcrevendo aqui mesmo")
                    texto = ouvidos.transcrever(pedido.get("arquivo", ""))
                    if not texto:
                        if hud is not None:
                            hud.publicar("mensagem", de="sistema",
                                         texto="Não entendi o áudio. " + ouvidos.diagnostico())
                            hud.publicar("situacao", estado="ocioso", detalhe="—")
                        continue
                    if hud is not None:
                        hud.publicar("mensagem", de="nicolas", texto=texto,
                                     hora=datetime.now().strftime("%H:%M"))
                if not texto:
                    continue
                if hud is not None:
                    hud.publicar("situacao", estado="pensando", detalhe="gerando resposta")
                resposta = responder(texto, "hud", em_fluxo=True)
                anunciar("zeus", resposta)
                if fala and voz.disponivel():
                    fala.falar(resposta, geracao)

        except Exception as erro:  # o ciclo não morre por falha de rede
            if isinstance(erro, ErroDeModelo):
                modelo_ok = False
                proxima_recuperacao = time.monotonic() + max(5, config.intervalo_recuperacao_modelo)
                operacao.atualizar('modelo', estado='degradada')
            emit("falha_no_ciclo", detalhe=str(erro)[:200])
            if hud is not None:
                hud.publicar("fluxo", reiniciar=True)
                hud.publicar("mensagem", de="sistema",
                             texto="Não consegui concluir esta resposta. Pode tentar novamente.")
            stopped.wait(0.5)
        recebidas_da_hud.aguardar(min(max(config.intervalo_agenda, 0.1), 1))
        agora = datetime.now(timezone.utc).timestamp()
        if agora - ultimo_batimento >= 30:
            store.connection.execute("SELECT 1").fetchone()
            emit("heartbeat", storage="ok")
            ultimo_batimento = agora

    supervisor.parar()
    if fala is not None:
        fala.parar()
    if hud is not None:
        hud.parar()
    emit("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
