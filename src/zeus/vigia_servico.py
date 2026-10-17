"""Vigia do serviço: roda num timer, fora do processo do Zeus (#70).

O `Restart=on-failure` cuida de queda rápida. O que ele não cobre é o que fica
quebrado em silêncio: a unidade em `failed` depois do teto de reinícios, a
chave do OpenRouter recusada, a ponte deslogada. Este vigia confere a cada
rodada e avisa Nicolas no grupo só quando algo **muda**. Um problema precisa
aparecer em `confirmacoes` rodadas seguidas para virar aviso; a volta é
avisada na primeira.

O aviso sai direto pela ponte B, sem passar pelo Zeus, porque o caso que mais
importa é justamente o Zeus fora do ar. O destino é sempre `whatsapp_grupo`.
Sem a ponte B de pé, fica só o registro no journal.

    python3 -m zeus.vigia_servico --repo ~/zeus
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

UNIDADES = ("zeus", "ponte-principal", "ponte-zeus")


def rodar(comando, timeout=120):
    try:
        feito = subprocess.run(comando, capture_output=True, text=True, timeout=timeout)
        return feito.returncode, feito.stdout
    except (OSError, subprocess.SubprocessError) as erro:
        return 1, str(erro)


def problemas_do_check(saida: str) -> dict:
    """Do JSON do `./zeus check --modelo --canal`, o que está quebrado."""
    dados = None
    for linha in reversed(saida.strip().splitlines()):
        try:
            dados = json.loads(linha)
            break
        except ValueError:
            continue
    if not isinstance(dados, dict) or dados.get("event") != "storage_check":
        return {"check": "o check não respondeu"}
    problemas = {}
    if dados.get("storage") != "ok":
        problemas["banco"] = f"integridade: {dados.get('storage')}"
    for campo in ("modelo", "canal"):
        valor = str(dados.get(campo, ""))
        if valor.startswith("falhou") or valor == "ausente":
            problemas[campo] = valor[:160]
    return problemas


def problemas_das_unidades(unidades, executar=rodar) -> dict:
    problemas = {}
    for unidade in unidades:
        _, saida = executar(["systemctl", "--user", "is-active", unidade], timeout=10)
        estado = saida.strip() or "desconhecido"
        if estado != "active":
            problemas[unidade] = f"unidade {estado}"
    return problemas


def comparar(anterior: dict, atuais: dict, confirmacoes: int = 2):
    """Novo estado e avisos. `anterior` guarda, por problema, quantas rodadas
    seguidas ele apareceu e se já foi avisado."""
    estado, caiu, voltou = {}, [], []
    for nome, detalhe in atuais.items():
        visto = anterior.get(nome, {})
        vezes = visto.get("vezes", 0) + 1
        avisado = visto.get("avisado", False)
        if not avisado and vezes >= confirmacoes:
            caiu.append((nome, detalhe))
            avisado = True
        estado[nome] = {"vezes": vezes, "avisado": avisado, "detalhe": detalhe}
    for nome, visto in anterior.items():
        if nome not in atuais and visto.get("avisado"):
            voltou.append(nome)
    return estado, caiu, voltou


def mensagem(caiu, voltou) -> str:
    linhas = []
    if caiu:
        linhas.append("Senhor, o vigia do X99 encontrou problema:")
        linhas += [f"- {nome}: {detalhe}" for nome, detalhe in caiu]
    if voltou:
        linhas.append("Voltou ao normal: " + ", ".join(voltou) + ".")
    return "\n".join(linhas)


def enviar_pela_ponte(url: str, grupo: str, texto: str, timeout=15) -> bool:
    corpo = json.dumps({"recipient": grupo, "message": texto}).encode("utf-8")
    pedido = urllib.request.Request(url.rstrip("/") + "/api/send", data=corpo,
                                    headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            return bool(json.loads(resposta.read() or b"{}").get("success"))
    except (OSError, ValueError):
        return False


def ler_estado(arquivo: Path) -> dict:
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_estado(arquivo: Path, estado: dict):
    arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporario = tempfile.mkstemp(dir=arquivo.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as saida:
        json.dump(estado, saida)
    os.replace(temporario, arquivo)


def recuperar(estado, caiu, unidades, executar):
    """Faz e avisa (fase 2): unidade da lista que caiu é reiniciada uma vez.
    Devolve as linhas do que foi tentado. Nada fora da lista é tocado."""
    linhas = []
    for nome, detalhe in caiu:
        if nome not in unidades or estado[nome].get("reiniciado"):
            continue
        codigo, _ = executar(["systemctl", "--user", "restart", nome], timeout=60)
        estado[nome]["reiniciado"] = True
        linhas.append(f"- {nome}: reiniciei" + ("" if codigo == 0 else f" (o systemctl devolveu {codigo})")
                      + "; confiro na próxima rodada.")
    return linhas


def depois_do_reinicio(anterior, estado, voltou):
    """Quem voltou depois do reinício, e quem continua caído mesmo assim."""
    voltaram = [n for n in voltou if anterior.get(n, {}).get("reiniciado")]
    insistentes = []
    for nome, dados in estado.items():
        if dados.get("reiniciado") and anterior.get(nome, {}).get("reiniciado") and not dados.get("insistente"):
            dados["insistente"] = True
            insistentes.append(nome)
    return voltaram, insistentes


def rodada(repo: Path, config, arquivo_de_estado: Path, executar=rodar,
           enviar=enviar_pela_ponte, unidades=UNIDADES, confirmacoes=2, recuperar_unidades=True) -> dict:
    _, saida = executar([str(repo / "zeus"), "check", "--modelo", "--canal"], timeout=120)
    atuais = {**problemas_das_unidades(unidades, executar), **problemas_do_check(saida)}
    anterior = ler_estado(arquivo_de_estado)
    estado, caiu, voltou = comparar(anterior, atuais, confirmacoes)
    for nome in estado:  # o reinício já tentado continua lembrado enquanto durar a queda
        if anterior.get(nome, {}).get("reiniciado"):
            estado[nome]["reiniciado"] = True
            estado[nome]["insistente"] = anterior[nome].get("insistente", False)
    voltaram, insistentes = depois_do_reinicio(anterior, estado, voltou)
    tentativas = recuperar(estado, caiu, unidades, executar) if recuperar_unidades else []
    texto = mensagem(caiu, [v for v in voltou if v not in voltaram])
    if tentativas:
        texto += "\nTentei recuperar sozinho:\n" + "\n".join(tentativas)
    if voltaram:
        texto = (texto + "\n" if texto else "") + "Voltou depois do reinício: " + ", ".join(voltaram) + "."
    if insistentes:
        texto = (texto + "\n" if texto else "") + ("Não voltou mesmo depois do reinício: " + ", ".join(insistentes)
                                                    + ". Precisa de você.")
    texto = texto.strip()
    enviado = None
    if texto:
        enviado = bool(config.whatsapp_grupo) and enviar(config.whatsapp_ponte_url,
                                                         config.whatsapp_grupo, texto)
        if not enviado:
            # Sem aviso entregue, a próxima rodada tenta de novo.
            for nome, _ in caiu:
                estado[nome]["avisado"] = False
    gravar_estado(arquivo_de_estado, estado)
    return {"event": "vigia_servico", "problemas": atuais,
            "caiu": [n for n, _ in caiu], "voltou": voltou, "reiniciou": [l.split(":")[0][2:] for l in tentativas],
            "aviso_enviado": enviado}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Vigia do serviço do Zeus")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--confirmacoes", type=int, default=2)
    args = parser.parse_args(argv)
    from .config import carregar
    config = carregar()
    estado = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    resultado = rodada(args.repo.expanduser(), config, estado / "zeus" / "vigia-servico.json",
                       confirmacoes=max(1, args.confirmacoes))
    print(json.dumps(resultado, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
