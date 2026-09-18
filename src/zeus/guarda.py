"""Barreiras que não dependem do bom comportamento do modelo.

A primeira nasce de um erro real já cometido: um valor financeiro alucinado foi
salvo na memória e voltou como fato em toda sessão seguinte. Desde então a
memória narrativa não guarda número financeiro. Consulta a domínio financeiro,
quando existir, lê o registro de origem em vez de repetir um resumo do modelo.
"""

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
