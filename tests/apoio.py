"""Dublês de teste. Nenhum teste desta suíte fala com rede, modelo ou Telegram."""

import json
from datetime import datetime, timedelta, timezone

from zeus.config import Config


class Relogio:
    def __init__(self, inicio: datetime):
        self.agora = inicio

    def __call__(self):
        return self.agora

    def avancar(self, **kwargs):
        self.agora = self.agora + timedelta(**kwargs)
        return self.agora


class ProvedorFalso:
    """Reproduz o contrato do provedor sem modelo nenhum por trás."""

    nome = "falso"

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.recebidas = []
        # Guarda o catálogo de cada rodada: é assim que um teste prova que as
        # ferramentas saíram da conversa depois de entrar dado externo.
        self.catalogos = []
        self.modelo = "modelo-falso"

    def verificar(self):
        return self.modelo

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0):
        self.recebidas.append(mensagens)
        self.catalogos.append(ferramentas)
        if not self.roteiro:
            from zeus.llm import Resposta
            return Resposta("Sem mais nada a dizer.", [], self.modelo)
        return self.roteiro.pop(0)

    def mensagem_do_assistente(self, resposta):
        return {"role": "assistant", "content": resposta.texto}

    def mensagem_de_ferramenta(self, chamada, conteudo):
        return {"role": "tool", "name": chamada["nome"], "content": conteudo}


def transporte_roteirizado(rotas):
    """Devolve respostas fixas por (método, trecho da url), registrando as chamadas."""
    chamadas = []

    def transporte(metodo, url, corpo=None, cabecalhos=None, timeout=None):
        chamadas.append({"metodo": metodo, "url": url, "corpo": corpo})
        for trecho, resposta in rotas:
            if trecho in url:
                return json.loads(json.dumps(resposta))
        raise AssertionError(f"Rota não prevista no teste: {metodo} {url}")

    transporte.chamadas = chamadas
    return transporte


def config_de_teste(**ajustes):
    base = dict(provedor="ollama", modelo="modelo-falso", turnos_de_conversa=6,
                temperatura_conversa=0.5, temperatura_decisao=0.0)
    base.update(ajustes)
    return Config(**base)


def em(ano, mes, dia, hora, minuto=0):
    return datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)
