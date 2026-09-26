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
from .acoes import Acoes
from .mapa import Mapa
from .saudacao import compor as compor_saudacao
from .saudacao import identificador_de_boot
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
from .telemetria import Medida, Telemetria, ler_medidas, resumir
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
    ferramentas = Ferramentas(store, pesquisa=pesquisa,
                              acoes=montar_acoes(config, store),
                              mapa=montar_mapa(config, args.state_dir.expanduser()))
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


def montar_mapa(config, estado):
    """As telas ficam no estado, não no repositório: são cache, não código."""
    from .mapa import BUSCA_PADRAO, TELAS_PADRAO
    return Mapa(ativo=bool(config.mapa_ativo),
                telas_url=config.mapa_telas_url or TELAS_PADRAO,
                busca_url=config.mapa_busca_url or BUSCA_PADRAO,
                centro_lat=config.mapa_centro_lat,
                centro_lon=config.mapa_centro_lon,
                zoom=config.mapa_zoom,
                cache_maximo_mb=config.mapa_cache_mb,
                destino=Path(estado) / "mapa")


def persona_de(config):
    return Persona.carregar(config.persona)


def diagnostico_do_contexto(config, persona):
    """Compara o tamanho do prompt com a janela pedida ao modelo.

    O Ollama corta pela frente, em silêncio, quando o prompt não cabe. O que
    vive na frente é a persona. Foi assim que o Zeus respondeu sem identidade
    sem nada no log dizer por quê, então o `check` passa a dizer antes."""
    import json as _json
    from .ferramentas import CATALOGO
    from .contexto import estimar_tokens
    partes = persona.instrucao()
    partes += "".join(m["content"] for m in persona.exemplos())
    partes += _json.dumps(CATALOGO, ensure_ascii=False)
    estimado = estimar_tokens(partes) + 400      # folga para memória e turnos
    janela = getattr(config, "contexto_tokens", 8192)
    situacao = "cabe" if estimado < janela * 0.8 else "apertado"
    if estimado >= janela:
        situacao = ("NÃO CABE: o modelo vai descartar o começo do prompt, que é "
                    "a persona. Aumente contexto_tokens.")
    return f"{situacao} ({estimado} tokens estimados para janela de {janela})"


def montar_acoes(config, store=None):
    """As ações no computador existem só sobre as pastas que Nicolas apontou.

    O registro vai para `eventos`: toda vez que o Zeus olhou alguma coisa fica
    escrito, e `./zeus agenda` e a HUD mostram. Confiança que não deixa rastro
    não é confiança, é esquecimento."""
    def registrar(acao, alvo, resumo):
        episodio = store.abrir_episodio("acao_no_computador", f"{acao}: {alvo}"[:300])
        store.registrar_evento(episodio, "acoes", acao,
                               {"alvo": alvo[:500], "resumo": resumo})
        store.fechar_episodio(episodio, resumo[:200])

    return Acoes(raizes=tuple(config.acoes_pastas or ()),
                 maximo_de_bytes=config.acoes_max_bytes,
                 maximo_de_itens=config.acoes_max_itens,
                 permitir_abrir=bool(config.acoes_abrir),
                 registrar=registrar if store is not None else None)


def montar_voz(config):
    return Voz(config.voz_binario, config.voz_modelo)


def montar_ouvidos(config, estado):
    return Ouvidos(config.escuta_modelo, config.escuta_computo, config.escuta_idioma,
                   threads=config.escuta_threads, destino=Path(estado) / "escuta",
                   beam_size=config.escuta_beam, silencio_ms=config.escuta_silencio_ms,
                   vocabulario=config.escuta_vocabulario)


def retrato(store, config, voz, modelo="", ouvidos=None, capacidades=None):
    """O que a HUD mostra: memória confirmada, pendências e conversa recente.

    `modelo` é o que respondeu à verificação; vazio quer dizer indisponível.
    O nome configurado vai à parte: mostrá-lo no lugar do verificado fazia a
    interface acender o modelo justamente quando ele estava fora."""
    entradas = Entregas(store).entradas()
    return {
        "tipo": "estado",
        "fatos": store.fatos("confirmado"),
        "perguntas": store.perguntas_abertas(),
        "lembretes": store.agenda_pendente(),
        "turnos": store.turnos(20),
        "entregas": Entregas(store).listar(20),
        "entradas": entradas,
        "modelo": modelo,
        "modelo_configurado": config.modelo,
        "modelo_estado": "pronta" if modelo else "indisponivel",
        "voz": voz.disponivel() if voz else False,
        "ouvidos": ouvidos.disponivel() if ouvidos else False,
        "motivo_ouvidos": ouvidos.diagnostico() if ouvidos else "desligada",
        "capacidades": capacidades or {},
    }


def situacao_da_chave(chave: str) -> str:
    """Diz se a chave da HUD é fraca, sem nunca mostrar a chave."""
    if not chave:
        return "sem chave definida: um código de pareamento de uso único a cada início"
    if len(chave) < 20:
        return ("configurada, mas curta: use 24 ou mais caracteres aleatórios "
                "(python3 -c \"import secrets;print(secrets.token_urlsafe(24))\")")
    return "configurada"


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

    busca = commands.add_parser(
        "pesquisar", help="Rodar uma busca e ver as fontes, sem passar pelo modelo")
    busca.add_argument("consulta")
    busca.add_argument("--cru", action="store_true",
                       help="Sem resultado, mostra o começo da página recebida")
    busca.add_argument("--diagnostico", action="store_true",
                       help="Testa cada endereço e método e diz onde a busca para")

    conversa = commands.add_parser("conversar", help="Uma troca pelo terminal")
    conversa.add_argument("texto")

    medidas_cmd = commands.add_parser(
        "medidas", help="Resumir as medidas de turno gravadas, com p50/p95 e amostra")
    medidas_cmd.add_argument("--pasta", type=Path, default=None,
                             help="Pasta com os .jsonl; padrão: medidas do estado")
    bancada_cmd = commands.add_parser(
        "bancada", help="Repetir um roteiro sintético contra o modelo real, em estado isolado")
    bancada_cmd.add_argument("--roteiro", type=Path, default=None)
    bancada_cmd.add_argument("--repeticoes", type=int, default=3)
    bancada_cmd.add_argument("--sem-fluxo", action="store_true",
                             help="Medir a rota sem fluxo, como a do Telegram")
    bancada_cmd.add_argument("--com-pesquisa", action="store_true",
                             help="Permitir a busca na internet durante o roteiro")

    evento = commands.add_parser("evento", help="Registrar um acontecimento observado")
    evento.add_argument("tipo")
    evento.add_argument("resumo")
    evento.add_argument("--simulado", action="store_true",
                        help="Marca o episódio como simulado, para teste honesto")

    args = parser.parse_args()
    os.umask(0o077)
    # Estes dois não abrem o banco do estado: a bancada exige pasta vazia e o
    # resumo só lê arquivos de medida.
    if args.command == "medidas":
        pasta = args.pasta or (args.state_dir.expanduser() / "medidas")
        linhas = ler_medidas(pasta) if Path(pasta).is_dir() else []
        emit("medidas", pasta=str(pasta), **resumir(linhas))
        return 0 if linhas else 1
    if args.command == "bancada":
        try:
            return bancada(args, default_state)
        except (ErroDeModelo, ValueError) as erro:
            print(str(erro), file=sys.stderr)
            return 2
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
                 acoes=montar_acoes(config).diagnostico(),
                 contexto=diagnostico_do_contexto(config, persona_de(config)),
                 mapa=montar_mapa(config, args.state_dir.expanduser()).diagnostico(),
                 hud=situacao_da_chave(config.chave_hud),
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
        elif args.command == "pesquisar":
            # Diagnóstico direto: "não encontrei fonte confiável" pode ser
            # ausência real ou leitor quebrado, e do lado de fora os dois se
            # parecem. Aqui dá para ver qual dos dois é.
            pesquisa = montar_pesquisa(config, args.state_dir.expanduser())
            if args.diagnostico:
                relato = pesquisa.conferir(args.consulta)
                emit("pesquisa_diagnostico", disponivel=relato.get("disponivel"),
                     provedor=relato.get("provedor", ""),
                     alguma_funcionou=relato.get("alguma_funcionou", False),
                     motivo=relato.get("motivo", ""))
                for linha in relato.get("tentativas", []):
                    print(f"- {linha['tentativa']:<10} {linha.get('metodo','')}"
                          f"  {linha.get('bytes', '—')} bytes"
                          f"  {linha.get('fontes', 0)} fontes"
                          f"  forma={linha.get('forma') or '—'}")
                    detalhe = linha.get("erro") or linha.get("leitura", "")
                    if detalhe and not linha.get("fontes"):
                        print(f"  {detalhe}")
                    if linha.get("primeira"):
                        print(f"  {linha['primeira']}")
                return 0 if relato.get("alguma_funcionou") else 3
            if not pesquisa.disponivel():
                emit("pesquisa", situacao=pesquisa.diagnostico())
                return 3
            try:
                resultado = pesquisa.buscar(args.consulta)
            except Exception as erro:
                emit("pesquisa", consulta=args.consulta, erro=str(erro)[:300])
                return 3
            emit("pesquisa", consulta=resultado.get("consulta"),
                 provedor=resultado.get("provedor"),
                 fontes=len(resultado.get("fontes", [])),
                 sem_resultado=bool(resultado.get("sem_resultado")),
                 forma=resultado.get("forma", ""),
                 motivo=resultado.get("motivo", ""),
                 aviso=resultado.get("aviso", ""))
            for fonte in resultado.get("fontes", []):
                print(f"- {fonte.get('titulo', '')}\n  {fonte.get('url', '')}"
                      f"\n  {fonte.get('trecho', '')[:200]}")
            if args.cru and not resultado.get("fontes"):
                print("\n--- começo do que o buscador devolveu ---")
                print(getattr(pesquisa, "ultima_pagina", "")[:1200] or "(nada)")
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


def versao_do_codigo():
    """Commit em execução, quando o clone tem Git. Sem Git, None: não inventar."""
    import subprocess
    raiz = Path(__file__).resolve().parents[2]
    try:
        saida = subprocess.run(["git", "-C", str(raiz), "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=2, check=True)
        return saida.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def linha_de_sessao(config, origem):
    """Ambiente da medida: sem ele, dois números não são comparáveis."""
    return {"tipo": "sessao", "v": 1, "origem": origem, "versao": __version__,
            "commit": versao_do_codigo(), "provedor": config.provedor,
            "modelo": config.modelo, "modelo_conversa": config.modelo_conversa or None,
            "contexto_tokens": config.contexto_tokens,
            "limite_de_resposta": config.limite_de_resposta,
            "teto_de_contexto": config.teto_de_contexto,
            "turnos_de_conversa": config.turnos_de_conversa,
            "registrado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}


ROTEIRO_DA_BANCADA = Path(__file__).resolve().parents[2] / "avaliacao" / "bancada.json"


def bancada(args, estado_padrao):
    """Linha de base comparável: o mesmo roteiro, a rota real, estado isolado.

    Nada aqui toca o estado de produção nem canal nenhum. A pasta precisa ser
    nova ou vazia, para que memória antiga não entre no prompt e mude o
    número. O roteiro é sintético: nenhum dado pessoal é necessário."""
    config = carregar_config(getattr(args, "config", None))
    destino = args.state_dir.expanduser()
    if destino.resolve() == Path(estado_padrao).expanduser().resolve():
        raise ValueError("A bancada exige --state-dir próprio, fora do estado do Zeus.")
    if destino.exists() and any(destino.iterdir()):
        raise ValueError(f"{destino} não está vazio. Use uma pasta nova para a bancada.")
    roteiro = json.loads((args.roteiro or ROTEIRO_DA_BANCADA).read_text(encoding="utf-8"))
    turnos = [t for t in roteiro.get("turnos", []) if isinstance(t, str) and t.strip()]
    if not turnos:
        raise ValueError("Roteiro sem turnos.")
    destino.mkdir(parents=True, exist_ok=True, mode=0o700)
    telemetria = Telemetria(destino, gravar=True, dias=365)
    telemetria.registrar({**linha_de_sessao(config, "bancada"),
                          "roteiro": roteiro.get("id", "sem-id"), "turnos": len(turnos),
                          "repeticoes": args.repeticoes, "fluxo": not args.sem_fluxo,
                          "pesquisa": bool(args.com_pesquisa)})
    persona = Persona.carregar(config.persona)
    for repeticao in range(1, max(1, args.repeticoes) + 1):
        pasta = destino / f"rodada-{repeticao}"
        store = Store(pasta)
        try:
            pesquisa = montar_pesquisa(config, pasta) if args.com_pesquisa else None
            ferramentas = Ferramentas(store, pesquisa=pesquisa)
            zeus = Zeus(store, None, persona, ferramentas, config, canal=None)
            zeus.capacidades = {"voz": False, "ouvidos": False,
                                "pesquisa": bool(pesquisa and pesquisa.disponivel())}
            ligar_modelo(zeus, config)
            for passo, texto in enumerate(turnos, start=1):
                medida = Medida(canal="bancada", origem="texto", recebido_em=time.monotonic())
                try:
                    zeus.conversar(texto, canal="bancada", medida=medida,
                                   ao_receber=None if args.sem_fluxo else (lambda _p: None))
                except ErroDeModelo as erro:
                    emit("bancada_falha", repeticao=repeticao, passo=passo,
                         erro=type(erro).__name__)
                linha = medida.como_linha()
                linha["bancada"] = {"repeticao": repeticao, "passo": passo}
                telemetria.registrar(linha)
                emit("bancada_turno", repeticao=repeticao, passo=passo,
                     resultado=linha["resultado"], total_ms=linha["total_ms"],
                     rodadas=len(linha["rodadas"]))
        finally:
            store.close()
    resumo = resumir(ler_medidas(destino / "medidas"))
    emit("bancada", pasta=str(destino), **resumo)
    return 0


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
    telemetria = Telemetria(Path(store.path).parent, gravar=config.telemetria_arquivo,
                            dias=config.telemetria_dias)
    telemetria.registrar(linha_de_sessao(config, "run"))
    zeus.telemetria = telemetria
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

    def capacidades_atuais():
        """Cada capacidade com estado e motivo próprios. Disponibilidade do
        modelo, captura do microfone e saúde da máquina são coisas diferentes."""
        pesquisa = zeus.ferramentas.pesquisa
        mapa = zeus.ferramentas.mapa
        return {
            "modelo": {"estado": "pronta" if modelo_ok else "indisponivel",
                       "nome": config.modelo,
                       "motivo": "" if modelo_ok else str(servido)[:200]},
            "voz": {"estado": "pronta" if voz.disponivel() else "ausente",
                    "motivo": voz.diagnostico()},
            "escuta": {"estado": "pronta" if ouvidos.disponivel() else "ausente",
                       "motivo": ouvidos.diagnostico()},
            "pesquisa": {"estado": "configurada" if pesquisa and pesquisa.disponivel() else "ausente",
                         "motivo": pesquisa.diagnostico() if pesquisa else "não configurada"},
            "telegram": {"estado": "configurado" if zeus.canal is not None else "ausente",
                         "motivo": "" if zeus.canal is not None else "sem token e chat_id"},
            "mapa": {"estado": "ativo" if mapa and mapa.ativo else "ausente",
                     "motivo": mapa.diagnostico() if mapa else "não configurado"},
        }

    # Sem chave configurada, um código de pareamento de uso único, válido por
    # quinze minutos. Ele aparece no log uma vez; depois de usado, o log antigo
    # não abre mais nada. A chave configurada nunca é impressa.
    chave = config.chave_hud
    codigo = "" if chave else secrets.token_urlsafe(9)
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
            codigo_unico=codigo, arquivo_de_sessoes=estado_local / "hud" / "sessoes.json",
            host=config.hud_host, porta=config.hud_porta,
            estado=retrato(store, config, voz, servido if modelo_ok else "", ouvidos,
                           capacidades_atuais()),
            pasta_de_escuta=ouvidos.destino,
            mapa=montar_mapa(config, estado_local),
            certificado=certificado, chave_tls=chave_tls, telemetria=telemetria)
        porta = hud.iniciar()
        esquema = "https" if hud.seguro else "http"
        endereco = f"{esquema}://{endereco_local()}:{porta}/"
    except Exception as erro:
        emit("hud_indisponivel", detalhe=str(erro)[:200])

    if hud is not None and codigo:
        emit("hud_pareamento", codigo=codigo, validade_min=15, uso="único",
             detalhe="Digite o código na página. Para não depender dele, defina chave_hud.")
    emit("started", version=__version__, modelo=servido, modelo_ok=modelo_ok,
         canal=(zeus.canal.nome if zeus.canal else "nenhum"),
         voz=voz.diagnostico(), ouvidos=ouvidos.diagnostico(),
         hud=endereco or "desligada")

    def anunciar(de, texto, audio=None, turno=None, detalhes=None, canal=None):
        if hud is None:
            return
        hud.publicar("mensagem", de=de, texto=texto, audio=audio, turno=turno,
                     detalhes=detalhes, canal=canal, hora=datetime.now().strftime("%H:%M"))
        atualizar_retrato()

    def atualizar_retrato():
        if hud is not None:
            hud.atualizar(retrato(store, config, voz, servido if modelo_ok else "", ouvidos,
                                  capacidades_atuais()))

    def detalhes_do_turno(medida):
        """O que a interface mostra em "Como chegou a isso?": só o que houve.

        Ferramentas usadas, rodadas, tempo medido e fontes do turno. Nenhuma
        explicação inventada do raciocínio do modelo."""
        linha = medida.como_linha()
        fontes = []
        if hasattr(zeus.ferramentas, "fontes_para_mostrar"):
            fontes = zeus.ferramentas.fontes_para_mostrar()
        return {"ferramentas": [{"nome": f["nome"], "resultado": f["resultado"]}
                                for f in linha["ferramentas"]],
                "rodadas": len(linha["rodadas"]), "total_ms": linha["total_ms"],
                "resultado": linha["resultado"], "fontes": fontes,
                "modelo": servido if modelo_ok else None}

    def executar_pendencia(pedido):
        """Só as ações que o backend suporta, no dono do banco."""
        tipo, alvo, acao = pedido.get("alvo_tipo"), pedido.get("alvo"), pedido.get("acao")
        try:
            if tipo == "pergunta" and acao == "cancelar":
                ok = store.cancelar_pergunta(int(alvo))
                return ok, ("Pergunta cancelada." if ok else "A pergunta já não estava aberta.")
            if tipo == "lembrete" and acao == "cancelar":
                ok = store.cancelar_agenda(int(alvo))
                return ok, ("Lembrete cancelado. Um envio já iniciado pode chegar."
                            if ok else "O lembrete já não estava pendente.")
            if tipo == "entrega":
                fila_de_saida.resolver(str(alvo), acao)
                return True, {"confirmar": "Marcada como entregue.",
                              "reenviar": "Volta para a fila e pode duplicar se já tiver chegado.",
                              "descartar": "Descartada."}[acao]
            if tipo == "entrada":
                fila_de_saida.resolver_entrada(int(alvo), acao)
                return True, ("Volta para a fila. Efeitos já feitos podem se repetir."
                              if acao == "reprocessar" else "Mensagem descartada.")
        except ValueError as erro:
            return False, str(erro)
        return False, "Ação não suportada."

    def contar_lugares():
        """Quando o Zeus localiza algo, o mapa da interface vai junto."""
        achados = getattr(zeus.ferramentas, "ultimos_lugares", None)
        if hud is not None and achados:
            hud.publicar("lugares", lugares=achados[:5])
        if achados is not None:
            zeus.ferramentas.ultimos_lugares = []

    def responder(texto, canal, em_fluxo=False, medida=None, responde_a=None):
        """Uma pergunta, uma resposta, a mesma identidade em qualquer canal."""
        if not modelo_ok:
            store.registrar_turno(canal, "nicolas", texto)
            if medida is not None:
                medida.ausentes["rodadas"] = "modelo indisponível; nenhuma chamada feita"
                medida.concluir("falhou", "modelo_indisponivel")
            return SEM_MODELO
        if not (em_fluxo and hud is not None):
            try:
                return zeus.conversar(texto, canal=canal, medida=medida,
                                      responde_a=responde_a)
            finally:
                contar_lugares()

        turno = medida.turno if medida is not None else None

        def empurrar(pedaco):
            if pedaco is None:
                hud.publicar("fluxo", reiniciar=True, turno=turno)
            else:
                hud.publicar("fluxo", pedaco=pedaco, turno=turno)

        try:
            return zeus.conversar(texto, canal=canal, ao_receber=empurrar, medida=medida,
                                  responde_a=responde_a)
        finally:
            contar_lugares()

    def nova_medida(pedido, canal, origem, geracao, turno=None):
        """Um turno identificado, com a etapa real publicada para a interface."""
        medida = Medida(canal=canal, origem=origem, geracao=geracao,
                        turno=turno or pedido.get("id") or None,
                        recebido_em=pedido.get("recebido_em"))
        if hud is not None:
            def publicar_etapa(etapa, detalhe, decorrido_ms):
                hud.publicar("turno", turno=medida.turno, canal=canal, etapa=etapa,
                             detalhe=detalhe, decorrido_ms=decorrido_ms, geracao=geracao)
            medida.ao_mudar = publicar_etapa
        return medida

    def registrar_medida(medida):
        if medida.fim is None:
            medida.concluir("interrompida")
        telemetria.registrar(medida.como_linha())

    fala = (FalaEmSegundoPlano(voz, hud.publicar, ao_medir=telemetria.registrar)
            if hud is not None else None)
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
    # A saudação vem depois de tudo estar de pé: canal, HUD e agenda. Falar
    # antes disso seria prometer presença que ainda não existe.
    boot = identificador_de_boot()
    canal_da_saudacao = zeus.canal.nome if zeus.canal else "hud"
    # Duas marcas, dois trabalhos. `marcar_envio` é o portão barato: ele decide
    # antes de gastar uma geração do modelo, e só deixa passar uma vez por
    # ligada da máquina. A fila de saída é a entrega, com reenvio e recibo.
    def gerar_saudacao(pedido, canal):
        """Fala uma vez, sem passar pelo ciclo de conversa.

        `zeus.conversar` registraria o pedido como se Nicolas tivesse digitado
        "a máquina acabou de ligar", e esse turno apareceria no histórico da
        interface como fala dele. A saudação nasce do Zeus: só a resposta é
        registrada, e nenhuma ferramenta entra na mesa."""
        from .guarda import limpar_resposta
        sistema = zeus.persona.sistema(
            fatos=store.fatos("confirmado"), perguntas=store.perguntas_abertas(),
            agenda=store.agenda_pendente(), agora=datetime.now(timezone.utc),
            capacidades=zeus.capacidades)
        mensagens = [{"role": "system", "content": sistema}]
        mensagens += zeus.persona.exemplos()
        mensagens.append({"role": "user", "content": pedido})
        resposta = zeus.provedor.conversar(mensagens, None, config.temperatura_conversa)
        texto = limpar_resposta(resposta.texto)
        if texto:
            store.registrar_turno(canal, "zeus", texto)
        return texto

    saudacao = compor_saudacao(store, store.marcar_envio, gerar_saudacao,
                               datetime.now(), boot,
                               ligada=bool(config.saudacao_ao_ligar),
                               canal=canal_da_saudacao)
    if saudacao:
        fila_de_saida.preparar(f"saudacao-envio:{boot}", canal_da_saudacao,
                               saudacao, tipo="saudacao")
        emit("saudacao", boot=boot[:8], canal=canal_da_saudacao)
        anunciar("zeus", saudacao)
        if fala and voz.disponivel():
            fala.falar(saudacao, 0)

    ultimo_batimento = 0.0
    while not stopped.is_set():
        try:
            if not modelo_ok and time.monotonic() >= proxima_recuperacao:
                try:
                    servido = ligar_modelo(zeus, config)
                    modelo_ok = True
                    operacao.atualizar('modelo', estado='pronta')
                    atualizar_retrato()     # o sinal da interface volta junto
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
                if pedido.get("tipo") == "pendencia":
                    ok, mensagem = executar_pendencia(pedido)
                    if hud is not None:
                        hud.publicar("pendencia_resultado", pedido=pedido.get("id"), ok=ok,
                                     mensagem=mensagem, alvo_tipo=pedido.get("alvo_tipo"),
                                     alvo=pedido.get("alvo"), acao=pedido.get("acao"))
                    atualizar_retrato()
                    continue
                if pedido.get("tipo") == "telegram":
                    recebidas = pedido["mensagens"]
                    chave_resposta = fila_de_saida.iniciar_resposta(recebidas)
                    medida = None
                    try:
                        if chave_resposta is None:
                            continue
                        # O turno do Telegram tem a identidade da entrada: é
                        # por ela que a recuperação acha o registro de efeitos.
                        medida = nova_medida(pedido, "telegram", "texto", geracao,
                                             turno=chave_resposta)
                        texto = "\n".join(m["texto"] for m in recebidas)
                        responde_a = fila_de_saida.pergunta_respondida(recebidas)
                        anunciar("nicolas", texto, canal="telegram", turno=medida.turno)
                        resposta = com_aviso_de_digitacao(
                            zeus.canal, lambda: responder(texto, "telegram", medida=medida,
                                                          responde_a=responde_a))
                        fila_de_saida.concluir_resposta(chave_resposta, resposta)
                        anunciar("zeus", resposta, turno=medida.turno, canal="telegram",
                                 detalhes=detalhes_do_turno(medida))
                    except Exception:
                        if chave_resposta:
                            situacao = fila_de_saida.resposta_interrompida(
                                chave_resposta, bool(zeus.efeitos_do_ultimo_turno()))
                            emit("entrada_interrompida", situacao=situacao)
                        raise
                    finally:
                        pedido["terminado"].set()
                        if medida is not None:
                            registrar_medida(medida)
                    continue
                texto = pedido.get("texto", "")
                origem = "voz" if pedido.get("tipo") == "audio" else "texto"
                medida = nova_medida(pedido, "hud", origem, geracao)
                try:
                    if pedido.get("tipo") == "audio":
                        if hud is not None:
                            hud.publicar("situacao", estado="ouvindo",
                                         detalhe="transcrevendo aqui mesmo")
                        medida.etapa("transcrevendo")
                        texto = ouvidos.transcrever(pedido.get("arquivo", ""))
                        # Só números: a transcrição em si nunca entra na medida.
                        medida.escuta = {k: ouvidos.ultima_medicao.get(k) for k in
                                         ("carga_s", "transcricao_s", "audio_s", "com_fala")}
                        if not texto:
                            medida.concluir("falhou", "sem_transcricao")
                            if hud is not None:
                                hud.publicar("mensagem", de="sistema",
                                             texto="Não entendi o áudio. " + ouvidos.diagnostico())
                                hud.publicar("situacao", estado="ocioso", detalhe="—")
                            continue
                        if hud is not None:
                            hud.publicar("mensagem", de="nicolas", texto=texto,
                                         turno=medida.turno, canal="hud",
                                         hora=datetime.now().strftime("%H:%M"))
                    if not texto:
                        medida.concluir("falhou", "mensagem_vazia")
                        continue
                    if hud is not None:
                        hud.publicar("situacao", estado="pensando", detalhe="gerando resposta")
                    resposta = responder(texto, "hud", em_fluxo=True, medida=medida,
                                         responde_a=pedido.get("responde_a"))
                    anunciar("zeus", resposta, turno=medida.turno, canal="hud",
                             detalhes=detalhes_do_turno(medida))
                    if fala and voz.disponivel():
                        fala.falar(resposta, geracao, medida.turno)
                finally:
                    registrar_medida(medida)

        except Exception as erro:  # o ciclo não morre por falha de rede
            if isinstance(erro, ErroDeModelo):
                modelo_ok = False
                servido = f"indisponível: {erro}"
                proxima_recuperacao = time.monotonic() + max(5, config.intervalo_recuperacao_modelo)
                operacao.atualizar('modelo', estado='degradada')
                atualizar_retrato()         # o sinal apaga na hora, não na próxima mensagem
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
