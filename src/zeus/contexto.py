"""Orçamento de contexto: escolher o que entra no prompt, e dizer o que ficou fora.

A leitura do prompt no X99 foi medida em 32 tokens por segundo. Como todos os
fatos confirmados entravam no contexto a cada turno, cada coisa nova que o Zeus
aprendia tornava toda resposta futura mais lenta: ele ficava mais devagar quanto
mais conhecia Nicolas, que é o oposto do que deveria acontecer.

A seleção tem duas camadas, e a divisão existe por causa do cache do servidor:

- **Núcleo estável**: os fatos confirmados mais recentes, em ordem determinística.
  Só muda quando a memória muda, então continua fazendo parte do prefixo que o
  servidor reaproveita entre turnos.
- **Trazidos pela mensagem**: poucos fatos que casam com o que Nicolas acabou de
  dizer. Esses mudam a cada turno, então vão para o fim do contexto, junto com o
  relógio, onde já não havia cache a perder.

Nada sai em silêncio: o que não coube é contado e aparece no comando `persona`.
"""

import re
import unicodedata

# Aproximação deliberada: em português, com este vocabulário, quatro caracteres
# por token ficou perto o bastante para orçar. Não substitui medir no servidor.
CARACTERES_POR_TOKEN = 4

FRACAO_DO_NUCLEO = 0.6          # fatos confirmados mais recentes
FRACAO_DE_HIPOTESES = 0.2       # reserva própria, explicada em selecionar()
                                # o que sobrar vai para o que a mensagem trouxer
PALAVRA = re.compile(r"[a-z0-9]{3,}")

VAZIAS = {
    "que", "com", "para", "por", "uma", "meu", "minha", "você", "voce", "the",
    "dos", "das", "nos", "nas", "mais", "mas", "isso", "isto", "aqui", "hoje",
    "amanha", "amanhã", "ontem", "agora", "quando", "onde", "como", "qual",
    "quais", "sobre", "ser", "estar", "tem", "ter", "faz", "fazer", "vai",
}


def estimar_tokens(texto: str) -> int:
    return max(1, (len(texto or "") + CARACTERES_POR_TOKEN - 1) // CARACTERES_POR_TOKEN)


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def termos(texto: str) -> set:
    return {p for p in PALAVRA.findall(_sem_acento(texto)) if p not in VAZIAS}


def linha_do_fato(fato: dict) -> str:
    return f"- {fato['key']}: {fato['value']}"


def _custo(fato: dict) -> int:
    return estimar_tokens(linha_do_fato(fato))


def _recencia(fato: dict) -> str:
    return str(fato.get("updated_at") or "")


def pontuar(fato: dict, procurados: set) -> int:
    """Quantos termos da mensagem aparecem na chave ou no valor do fato."""
    if not procurados:
        return 0
    return len(procurados & termos(f"{fato.get('key', '')} {fato.get('value', '')}"))


def selecionar(fatos, mensagem: str = "", teto: int = 600) -> dict:
    """Divide a memória em núcleo estável, trazidos pela mensagem e o que ficou fora."""
    fatos = list(fatos or [])
    confirmados = [f for f in fatos if f.get("estado") == "confirmado"]
    hipoteses = [f for f in fatos if f.get("estado") == "hipotese"]

    if teto <= 0:                      # orçamento desligado: tudo entra, como antes
        return {"nucleo": confirmados, "hipoteses": hipoteses, "trazidos": [],
                "fora": [], "tokens": sum(_custo(f) for f in fatos + hipoteses),
                "teto": 0}

    # Ordem determinística: mais recente primeiro, empate resolvido pela chave.
    # Sem isso o núcleo mudaria de ordem entre turnos e o cache se perderia.
    ordenados = sorted(confirmados, key=lambda f: (_recencia(f), f.get("key", "")),
                       reverse=True)

    orcamento_do_nucleo = int(teto * FRACAO_DO_NUCLEO)
    nucleo, gasto_nucleo = [], 0
    for fato in ordenados:
        custo = _custo(fato)
        if gasto_nucleo + custo > orcamento_do_nucleo:
            continue
        nucleo.append(fato)
        gasto_nucleo += custo

    # Hipóteses têm reserva própria, e não é generosidade: é o que faz o Zeus
    # perguntar. Uma hipótese sobre a rotina que caia do contexto vira uma
    # pergunta que ele nunca faz, e a rotina nunca se confirma. Deixá-las
    # competindo por casamento de palavra com a mensagem apagava justamente as
    # que ele ainda não tinha assunto para trazer.
    orcamento_de_hipoteses = int(teto * FRACAO_DE_HIPOTESES)
    hipoteses_ordenadas = sorted(hipoteses, key=lambda f: (_recencia(f), f.get("key", "")),
                                 reverse=True)
    hipoteses_dentro, gasto_hipoteses = [], 0
    for fato in hipoteses_ordenadas:
        custo = _custo(fato)
        if gasto_hipoteses + custo > orcamento_de_hipoteses:
            continue
        hipoteses_dentro.append(fato)
        gasto_hipoteses += custo

    dentro = {id(f) for f in nucleo} | {id(f) for f in hipoteses_dentro}
    candidatos = [f for f in ordenados + hipoteses_ordenadas if id(f) not in dentro]
    procurados = termos(mensagem)
    pontuados = sorted(((pontuar(f, procurados), _recencia(f), f) for f in candidatos),
                       key=lambda t: (t[0], t[1]), reverse=True)

    trazidos, gasto = [], gasto_nucleo + gasto_hipoteses
    for pontos, _, fato in pontuados:
        if pontos <= 0:
            continue
        custo = _custo(fato)
        if gasto + custo > teto:
            break
        trazidos.append(fato)
        gasto += custo

    escolhidos = dentro | {id(f) for f in trazidos}
    fora = [f for f in confirmados + hipoteses if id(f) not in escolhidos]

    # Uma hipótese trazida pela mensagem continua sendo hipótese: ela nunca
    # aparece no bloco de fatos confirmados.
    hipoteses_trazidas = [f for f in trazidos if f.get("estado") == "hipotese"]
    trazidos_confirmados = [f for f in trazidos if f.get("estado") != "hipotese"]

    return {"nucleo": nucleo, "hipoteses": hipoteses_dentro + hipoteses_trazidas,
            "trazidos": trazidos_confirmados, "fora": fora,
            "tokens": gasto, "teto": teto}
