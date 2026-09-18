"""Comandos do Zeus.

Esta versão conversa com persona, guarda memória explícita, agenda perguntas e
lembretes e entrega no Telegram quando o canal está configurado. Nada além
disso: sem visão, sem telefonia, sem dispositivo doméstico.
"""

import argparse
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from . import __version__
from .config import carregar as carregar_config
from .ferramentas import Ferramentas
from .llm import ErroDeModelo, criar_provedor
from .nucleo import Zeus
from .persona import Persona
from .store import Store

SEM_MODELO = (
    "Não consigo falar agora: o modelo não respondeu à verificação. "
    "Sua mensagem foi registrada e nada foi inventado."
)


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
            emit("storage_check", version=__version__, storage=integrity,
                 modelo=modelo, canal=canal, config=config.sem_segredos())
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

    emit("started", version=__version__, modelo=servido, modelo_ok=modelo_ok,
         canal=(zeus.canal.nome if zeus.canal else "nenhum"))

    espera = min(config.espera_telegram, 10)
    ultimo_batimento = 0.0
    while not stopped.is_set():
        try:
            if zeus.canal is not None:
                for mensagem in zeus.canal.receber(espera):
                    if modelo_ok:
                        resposta = zeus.conversar(mensagem["texto"], canal="telegram")
                    else:
                        store.registrar_turno("telegram", "nicolas", mensagem["texto"])
                        resposta = SEM_MODELO
                    zeus.canal.enviar(resposta)
                    zeus.canal.confirmar(mensagem["id"])
            for aviso in zeus.tick():
                emit("aviso_enviado", **aviso)
        except Exception as erro:  # o ciclo não morre por falha de rede
            emit("falha_no_ciclo", detalhe=str(erro)[:200])
            stopped.wait(5)
        if zeus.canal is None:
            stopped.wait(config.intervalo_agenda)
        agora = datetime.now(timezone.utc).timestamp()
        if agora - ultimo_batimento >= 30:
            store.connection.execute("SELECT 1").fetchone()
            emit("heartbeat", storage="ok")
            ultimo_batimento = agora
    emit("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
