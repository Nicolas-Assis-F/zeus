"""Comandos da fundação do Zeus. Ainda sem modelo de IA conectado."""

import argparse
import json
import os
import signal
import sys
from pathlib import Path
from threading import Event

from . import __version__
from .store import Store


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Fundação do Zeus")
    default_state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "zeus"
    parser.add_argument("--state-dir", type=Path, default=default_state)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Verificar armazenamento local")
    commands.add_parser("run", help="Manter o processo base em execução")
    remember = commands.add_parser("remember", help="Registrar um fato explícito")
    remember.add_argument("key")
    remember.add_argument("value")
    remember.add_argument("--source", default="user")
    recall = commands.add_parser("recall", help="Consultar um fato")
    recall.add_argument("key")
    forget = commands.add_parser("forget", help="Remover um fato da memória ativa")
    forget.add_argument("key")
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(args.state_dir.expanduser())
    try:
        if args.command == "check":
            integrity = store.connection.execute("PRAGMA quick_check").fetchone()[0]
            emit("storage_check", version=__version__, storage=integrity, ai_connected=False)
            return 0 if integrity == "ok" else 1
        if args.command == "remember":
            store.remember(args.key, args.value, args.source)
            emit("remembered", key=args.key)
        elif args.command == "recall":
            fact = store.recall(args.key)
            emit("recalled", key=args.key, fact=fact)
            return 0 if fact is not None else 1
        elif args.command == "forget":
            emit("forgotten", key=args.key, removed=store.forget(args.key))
        elif args.command == "run":
            stopped = Event()
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda *_: stopped.set())
            emit("started", version=__version__, ai_connected=False)
            while not stopped.wait(30):
                store.connection.execute("SELECT 1").fetchone()
                emit("heartbeat", storage="ok")
            emit("stopped")
        return 0
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
