"""Barreiras que não dependem do bom comportamento do modelo.

A primeira nasce de um erro real já cometido: um valor financeiro alucinado foi
salvo na memória e voltou como fato em toda sessão seguinte. Desde então a
memória narrativa não guarda número financeiro. Consulta a domínio financeiro,
quando existir, lê o registro de origem em vez de repetir um resumo do modelo.
"""

import json
import re

PADROES_FINANCEIROS = [
    re.compile(r"r\$\s*\d", re.IGNORECASE),
    re.compile(r"\b\d[\d.]*,\d{2}\b"),
    re.compile(r"\b\d+\s*(reais|mil reais|brl|usd|d[óo]lares)\b", re.IGNORECASE),
    re.compile(r"\b(saldo|fatura|extrato|sal[áa]rio|d[íi]vida|rendimento)\b[^\n]*\d",
               re.IGNORECASE),
]


class MemoriaRecusada(ValueError):
    pass


def parece_financeiro(texto: str) -> bool:
    alvo = str(texto)
    return any(padrao.search(alvo) for padrao in PADROES_FINANCEIROS)


def checar_memoria(chave: str, valor: str):
    if parece_financeiro(chave) or parece_financeiro(valor):
        raise MemoriaRecusada(
            "Recusado: valor financeiro não entra na memória narrativa. "
            "Esse dado pertence ao domínio financeiro, com registro de origem."
        )


# --------------------------------------------------------------------------
# Chamada de ferramenta que vaza como texto.
#
# Um modelo pequeno às vezes "imagina" uma ferramenta e escreve o JSON dela na
# resposta em vez de chamar de verdade. Para Nicolas isso aparece como um bloco
# de código no meio do Telegram. O texto é limpo antes de sair, e uma resposta
# que era só isso vira uma frase honesta.

CHAVES_DE_CHAMADA = ("name", "parameters", "arguments", "function", "tool",
                     "ferramenta", "nome")


# Marcas do modelo de chat que vazam para dentro do conteúdo. Um modelo pequeno
# às vezes escreve o próprio papel antes de responder, e Nicolas recebeu
# mensagens começando com a palavra "assistant" — uma delas era só isso, sem
# resposta nenhuma. Não é conteúdo: é o gabarito do formato escapando.
PAPEL_VAZADO = re.compile(
    r"^\s*(?:<\|im_start\|>)?\s*(?:assistant|assistente|ai|system|user)\s*[:\-–]?\s*\n?",
    re.IGNORECASE)
MARCAS_DE_FORMATO = re.compile(
    r"<\|(?:im_start|im_end|eot_id|start_header_id|end_header_id|begin_of_text)\|>|</s>|<s>",
    re.IGNORECASE)


def limpar_resposta(texto: str) -> str:
    """Remove chamada de ferramenta vazada e marcas do formato de chat."""
    texto = MARCAS_DE_FORMATO.sub("", texto or "")
    anterior = None
    while anterior != texto:                # "assistant\nassistant\n..." acontece
        anterior = texto
        texto = PAPEL_VAZADO.sub("", texto, count=1)
    if not texto or "{" not in texto:
        return (texto or "").strip()
    decodificador = json.JSONDecoder()
    limpo, posicao = [], 0
    while posicao < len(texto):
        if texto[posicao] != "{":
            limpo.append(texto[posicao])
            posicao += 1
            continue
        try:
            objeto, fim = decodificador.raw_decode(texto, posicao)
        except ValueError:
            limpo.append(texto[posicao])
            posicao += 1
            continue
        if isinstance(objeto, dict) and any(c in objeto for c in CHAVES_DE_CHAMADA):
            posicao = fim
            continue
        limpo.append(texto[posicao:fim])
        posicao = fim
    resultado = "".join(limpo)
    resultado = re.sub(r"```(?:json)?\s*```", "", resultado)
    resultado = re.sub(r"\n{3,}", "\n\n", resultado)
    return resultado.strip()
