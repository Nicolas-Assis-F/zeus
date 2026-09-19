"""Eventos com origem e validade; primeira fonte: disponibilidade do modelo local."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .entregas import Entregas
from .store import agora_utc, texto_de


@dataclass(frozen=True)
class Evento:
    id: str
    origem: str
    tipo: str
    resumo: str
    observado_em: datetime
    valido_ate: datetime
    confianca: float = 1.0
    simulado: bool = False
    dados: dict = field(default_factory=dict)


def registrar(store, evento, canal='hud', agora=None):
    agora = agora or agora_utc()
    if not evento.id or not evento.origem or not evento.resumo.strip():
        raise ValueError('Evento exige identidade, origem e resumo.')
    if not 0 <= evento.confianca <= 1 or not isinstance(evento.dados, dict):
        raise ValueError('Confiança ou dados inválidos.')
    if any(d.tzinfo is None for d in (evento.observado_em, evento.valido_ate, agora)):
        raise ValueError('Horários precisam de fuso.')
    if evento.observado_em > agora + timedelta(seconds=30) or evento.valido_ate < evento.observado_em:
        raise ValueError('Horários inconsistentes.')
    if evento.valido_ate < agora:
        return False
    dados = json.dumps(evento.dados, ensure_ascii=False)
    if len(dados) > 16000:
        raise ValueError('Evento longo demais.')
    db = store.connection
    resumo = ('[Simulação] ' if evento.simulado else '') + evento.resumo
    with db:
        novo = db.execute("INSERT OR IGNORE INTO percepcoes "
            "(id,origem,observado_em,recebido_em,valido_ate,confianca,simulado,tipo,resumo,dados) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", (evento.id, evento.origem, texto_de(evento.observado_em),
            texto_de(agora), texto_de(evento.valido_ate), evento.confianca, int(evento.simulado),
            evento.tipo, resumo, dados)).rowcount
        if not novo:
            return False
        episodio = db.execute("INSERT INTO episodios (tipo,resumo,aberto_em,simulado) VALUES (?,?,?,?)",
                              (evento.tipo, resumo, texto_de(agora), int(evento.simulado))).lastrowid
        db.execute("UPDATE percepcoes SET episodio=? WHERE id=?", (episodio, evento.id))
        db.execute("INSERT INTO eventos (episodio,em,origem,tipo,dados) VALUES (?,?,?,?,?)",
                   (episodio, texto_de(agora), evento.origem, evento.tipo, dados))
        Entregas(store)._inserir('evento:' + evento.id, canal, resumo, 'aviso', episodio, agora, evento.valido_ate)
    return True


class MonitorModelo:
    """Duas amostras e cooldown. Persistência impede tempestade após reinício."""
    def __init__(self, store, verificar, canal='hud', amostras=2, cooldown=60):
        self.store, self.verificar, self.canal = store, verificar, canal
        self.amostras, self.cooldown = amostras, cooldown

    def observar(self, agora=None):
        agora = agora or agora_utc()
        try:
            disponivel = bool(self.verificar())
        except Exception:
            disponivel = False
        anterior = json.loads(self.store.kv_get('monitor_modelo', '{}'))
        estado = 'disponivel' if disponivel else 'indisponivel'
        quantidade = anterior.get('amostras', 0) + 1 if anterior.get('observado') == estado else 1
        publicado = anterior.get('publicado')
        quando = datetime.fromisoformat(anterior['publicado_em']) if anterior.get('publicado_em') else None
        evento = None
        if quantidade >= self.amostras and publicado != estado:
            if publicado is None and disponivel:
                publicado = estado  # partida saudável não merece interromper
            elif quando is None or (agora - quando).total_seconds() >= self.cooldown:
                resumo = ('O modelo local voltou a estar disponível. Vou tentar retomar a conversa.'
                          if disponivel else
                          'Não consegui confirmar o modelo local. Os lembretes continuam ativos; a conversa pode ficar indisponível.')
                evento = Evento(uuid.uuid4().hex, 'monitor:ollama', 'modelo:' + estado,
                                resumo, agora, agora + timedelta(minutes=10), dados={'estado': estado})
                # Evento, saída e estado do debounce na mesma transação lógica:
                # registrar faz commit; gravar a referência primeiro evita repetir
                # UUID quando houver reinício entre os dois passos.
                anterior['evento_pendente'] = {
                    'id': evento.id, 'estado': estado, 'resumo': resumo,
                    'em': texto_de(agora), 'valido_ate': texto_de(evento.valido_ate)}
                publicado, quando = estado, agora
        anterior.update(observado=estado, amostras=min(quantidade, self.amostras), publicado=publicado,
                        publicado_em=texto_de(quando) if quando else None)
        self.store.kv_set('monitor_modelo', json.dumps(anterior))
        pendente = anterior.get('evento_pendente')
        if pendente:
            e = Evento(pendente['id'], 'monitor:ollama', 'modelo:' + pendente['estado'],
                       pendente['resumo'], datetime.fromisoformat(pendente['em']),
                       datetime.fromisoformat(pendente['valido_ate']), dados={'estado': pendente['estado']})
            registrar(self.store, e, self.canal, agora)
            anterior.pop('evento_pendente')
            self.store.kv_set('monitor_modelo', json.dumps(anterior))
        return estado
