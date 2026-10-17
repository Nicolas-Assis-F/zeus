"""Uso real por turno, sem guardar texto privado nem estimar cobrança ausente."""
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4
from time import perf_counter

_ATUAL = ContextVar('zeus_uso_turno', default=None)


def registrar(uso):
    atual = _ATUAL.get()
    if atual is not None:
        atual['chamadas'].append(dict(uso))
        uso['turno'] = atual['turno']
    return uso


def ferramenta(nome, erro=False, reutilizada=False):
    atual = _ATUAL.get()
    if atual is not None:
        atual['ferramentas'].append({'nome': nome, 'erro': bool(erro),
                                    'reutilizada': bool(reutilizada)})


def rota(nome):
    atual = _ATUAL.get()
    if atual is not None:
        atual['rota'] = nome


@contextmanager
def medir(store, canal):
    atual = {'turno': uuid4().hex, 'canal': canal, 'chamadas': [], 'ferramentas': []}
    token = _ATUAL.set(atual)
    inicio = perf_counter()
    try:
        yield atual
    finally:
        _ATUAL.reset(token)
        chamadas = atual['chamadas']
        atual['duracao_ms'] = round((perf_counter() - inicio) * 1000, 1)
        atual['custo_usd'] = round(sum(c.get('custo') or 0 for c in chamadas), 8)
        atual['custos_ausentes'] = sum(c.get('custo') is None for c in chamadas)
        # Só há evento quando houve consulta paga ou ferramenta; conversa com
        # provedor falso e testes puramente locais não inventa custo financeiro.
        if chamadas or atual['ferramentas']:
            store.registrar_evento(None, 'llm', 'custo_turno', atual)
