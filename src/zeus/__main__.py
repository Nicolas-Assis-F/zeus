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
from .llm import ErroDeModelo, criar_provedor
from .nucleo import Zeus
from .persona import Persona
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
    ferramentas = Ferramentas(store)
    canal = None
    if config.canal_configurado:
        from .canais import CanalTelegram
        canal = CanalTelegram(config.telegram_token, config.telegram_chat_id, store,
                              espera=config.espera_telegram)
    return config, store, Zeus(store, None, persona, ferramentas, config, canal)


def montar_voz(config):
    return Voz(config.voz_binario, config.voz_modelo)


def montar_ouvidos(config, estado):
    return Ouvidos(config.escuta_modelo, config.escuta_computo, config.escuta_idioma,
                   destino=Path(estado) / "escuta")


def retrato(store, config, voz, modelo="", ouvidos=None):
    """O que a HUD mostra: memória confirmada, pendências e conversa recente."""
    return {
        "tipo": "estado",
        "fatos": store.fatos("confirmado"),
        "perguntas": store.perguntas_abertas(),
        "lembretes": store.agenda_pendente(),
        "turnos": store.turnos(20),
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

    medicao = commands.add_parser("medir", help="Comparar modelos com números, não com palpite")
    medicao.add_argument("--modelos", default="",
                         help="Lista separada por vírgula; sem isso, mede o configurado")
    medicao.add_argument("--repeticoes", type=int, default=3)
    commands.add_parser("persona", help="Mostrar o contexto que o modelo recebe")

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
            if args.modelo:
                try:
                    modelo = ligar_modelo(zeus, config)
                except ErroDeModelo as erro:
                    modelo = f"falhou: {erro}"
            if args.canal:
                canal = "ausente" if zeus.canal is None else zeus.canal.verificar()
            voz = montar_voz(config)
            ouvidos = montar_ouvidos(config, args.state_dir.expanduser())
            emit("storage_check", version=__version__, storage=integrity,
                 modelo=modelo, canal=canal, voz=voz.diagnostico(),
                 ouvidos=ouvidos.diagnostico(),
                 hud="configurada" if config.chave_hud else "sem chave definida",
                 config=config.sem_segredos())
            return 0 if integrity == "ok" else 1

        if args.command == "remember":
            store.remember(args.key, args.value, args.source, args.estado)
            emit("remembered", key=args.key, estado=args.estado)
        elif args.command == "recall":
            fact = store.recall(args.key)
            emit("recalled", key=args.key, fact=fact)
            return 0 if fact is not None else 1
        elif args.command == "forget":
            emit("forgotten", key=args.key, removed=store.forget(args.key))
        elif args.command == "agenda":
            emit("agenda", perguntas=store.perguntas_abertas(),
                 lembretes=store.agenda_pendente())
        elif args.command == "persona":
            print(zeus.persona.sistema(store.fatos(), store.perguntas_abertas(),
                                       store.agenda_pendente(), datetime.now(timezone.utc)))
        elif args.command == "evento":
            episodio = zeus.perceber(args.tipo, args.resumo, simulado=args.simulado)
            emit("episodio_aberto", id=episodio, simulado=args.simulado)
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
    stopped = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())

    modelo_ok = False
    try:
        servido = ligar_modelo(zeus, config)
        modelo_ok = True
    except ErroDeModelo as erro:
        servido = f"indisponível: {erro}"

    voz = montar_voz(config)
    estado_local = Path(store.path).parent
    ouvidos = montar_ouvidos(config, estado_local)
    recebidas_da_hud = queue.Queue(maxsize=32)
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

    espera = min(config.espera_telegram, 10)
    ultimo_batimento = 0.0
    while not stopped.is_set():
        try:
            if zeus.canal is not None:
                # Mensagens que chegaram juntas viram um turno só. Responder
                # "opa" e "bom?" separadamente gasta duas gerações e entrega as
                # respostas fora de ordem, como se ele estivesse atrasado.
                recebidas = zeus.canal.receber(espera)
                if recebidas:
                    texto = "\n".join(m["texto"] for m in recebidas)
                    anunciar("nicolas", texto)
                    resposta = com_aviso_de_digitacao(
                        zeus.canal, lambda: responder(texto, "telegram"))
                    zeus.canal.enviar(resposta)
                    for mensagem in recebidas:
                        zeus.canal.confirmar(mensagem["id"])
                    anunciar("zeus", resposta)

            while True:
                try:
                    pedido = recebidas_da_hud.get_nowait()
                except queue.Empty:
                    break
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
                arquivo = voz.falar(resposta)
                anunciar("zeus", resposta,
                         audio=f"/audio/{arquivo.name}" if arquivo else None)

            for aviso in zeus.tick():
                emit("aviso_enviado", **aviso)
                anunciar("zeus", aviso["texto"])
        except Exception as erro:  # o ciclo não morre por falha de rede
            emit("falha_no_ciclo", detalhe=str(erro)[:200])
            stopped.wait(5)
        if zeus.canal is None:
            stopped.wait(min(config.intervalo_agenda, 5))
        agora = datetime.now(timezone.utc).timestamp()
        if agora - ultimo_batimento >= 30:
            store.connection.execute("SELECT 1").fetchone()
            emit("heartbeat", storage="ok")
            ultimo_batimento = agora

    if hud is not None:
        hud.parar()
    emit("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
