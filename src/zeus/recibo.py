"""Afirmação vazia (#78): dizer que anotou sem ter anotado.

Um modelo às vezes escreve "anotei" ou "vou te lembrar" sem chamar a
ferramenta. Para Nicolas isso é pior que não anotar: ele confia e esquece. Por
isso a memória é fotografada antes e depois do turno, só por leitura. Se a
resposta afirma uma ação de memória e nada mudou, o próprio Zeus corrige na
mesma resposta. A ideia vem do javis-os (memory_receipt, MIT); o código é
próprio.
"""

import hashlib
import json
import re

AFIRMACAO = re.compile(
    r"\b("
    r"anotei|anotad[oa]|guardei|guardad[oa]|registrei|registrad[oa]|salvei|salv[oa]|"
    r"vou (?:te |lhe )?lembrar|te lembro|lembrete (?:criad|agendad|marcad)[oa]|"
    r"vou (?:anotar|guardar|registrar|agendar|salvar|marcar)|"
    r"agendei|agendad[oa]|marquei|deixei (?:anotad|agendad|marcad|registrad)[oa]|"
    r"esqueci (?:isso|esse|essa|o fato|a informação)|apaguei da memória|removi da memória"
    r")\b", re.IGNORECASE)

CORRECAO = ("Pequena correção, senhor: não cheguei a gravar isso. "
            "Quer que eu anote de verdade?")


def fotografar(store) -> str:
    """Impressão digital do que a memória guarda: fatos, agenda e perguntas."""
    estado = {"fatos": store.fatos(), "agenda": store.agenda_pendente(),
              "perguntas": store.perguntas_abertas()}
    return hashlib.sha256(json.dumps(estado, sort_keys=True, default=str,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


NEGACAO = re.compile(r"\b(não|nao|nunca|nem|nada)\b", re.IGNORECASE)


def afirma_memoria(texto: str) -> bool:
    """Afirma ação de memória? "Não está agendado" e "não anotei" não contam:
    a negação nos 20 caracteres anteriores, na mesma frase, desfaz."""
    texto = texto or ""
    for achado in AFIRMACAO.finditer(texto):
        antes = re.split(r"[.!?\n]", texto[max(0, achado.start() - 20):achado.start()])[-1]
        if not NEGACAO.search(antes):
            return True
    return False


def conferir(texto: str, antes: str, depois: str):
    """Texto final e se a afirmação era vazia."""
    if antes != depois or not afirma_memoria(texto):
        return texto, False
    return f"{texto.rstrip()}\n\n{CORRECAO}", True
