"""Prova de presença: o menor fluxo que mostra iniciativa e continuidade.

Sem comando imediato, Zeus percebe que falta um dado, agenda uma pergunta,
entrega no momento certo por um canal, incorpora a resposta e não cobra a
mesma coisa duas vezes, inclusive depois de reiniciar o processo.
"""

import tempfile
import unittest
from pathlib import Path

from apoio import ProvedorFalso, Relogio, config_de_teste, em
from zeus.canais import CanalMemoria
from zeus.ferramentas import Ferramentas
from zeus.llm import Resposta
from zeus.nucleo import Zeus
from zeus.persona import Persona
from zeus.store import Store


def chamada(nome, **argumentos):
    return {"id": "c1", "nome": nome, "argumentos": argumentos}


def montar(diretorio, relogio, canal, roteiro):
    store = Store(Path(diretorio))
    provedor = ProvedorFalso(roteiro)
    zeus = Zeus(store, provedor, Persona.carregar("nao/existe.md"),
                Ferramentas(store, relogio), config_de_teste(), canal, relogio)
    return store, provedor, zeus


class ProvaDePresenca(unittest.TestCase):
    def test_pergunta_agendada_entrega_resposta_e_nao_duplica(self):
        relogio = Relogio(em(2026, 9, 18, 18, 0))
        canal = CanalMemoria()
        with tempfile.TemporaryDirectory() as temp:
            roteiro = [
                Resposta("", [chamada("agendar_pergunta",
                                      texto="Antes do treino: quer que eu lembre da creatina?",
                                      motivo="não sei se esse lembrete já está combinado",
                                      quando="+30m")], "modelo-falso"),
                Resposta("Bom treino, senhor. Volto a falar daqui a pouco.", [], "modelo-falso"),
            ]
            store, provedor, zeus = montar(temp, relogio, canal, roteiro)

            resposta = zeus.conversar("vou pra academia mais tarde", canal="telegram")
            self.assertIn("Bom treino", resposta)
            pendentes = store.perguntas_abertas()
            self.assertEqual(len(pendentes), 1)
            self.assertEqual(pendentes[0]["situacao"], "agendada")

            # Antes da hora, nada é enviado.
            relogio.avancar(minutes=10)
            self.assertEqual(zeus.tick(), [])
            self.assertEqual(canal.enviados, [])

            # Na hora, a pergunta chega uma única vez.
            relogio.avancar(minutes=25)
            enviados = zeus.tick()
            self.assertEqual(len(enviados), 1)
            self.assertEqual(len(canal.enviados), 1)
            self.assertIn("creatina", canal.enviados[0])
            self.assertEqual(store.perguntas_abertas()[0]["situacao"], "perguntada")

            # Uma nova revisão no mesmo processo não repete o aviso.
            self.assertEqual(zeus.tick(), [])
            self.assertEqual(len(canal.enviados), 1)

            # Reinício do processo: o estado está no disco, o aviso não volta.
            store.close()
            store, provedor, zeus = montar(temp, relogio, canal, [
                Resposta("", [chamada("agendar_lembrete",
                                      texto="creatina antes do treino",
                                      quando="+2h")], "modelo-falso"),
                Resposta("Combinado. Falo com você às 21h.", [], "modelo-falso"),
            ])
            relogio.avancar(minutes=5)
            self.assertEqual(zeus.tick(), [])
            self.assertEqual(len(canal.enviados), 1)

            # A resposta entra no mesmo episódio e vira um combinado.
            zeus.conversar("pode lembrar sim", canal="telegram")
            pergunta = store.connection.execute(
                "SELECT situacao, resposta FROM perguntas WHERE id=1").fetchone()
            self.assertEqual(pergunta["situacao"], "respondida")
            self.assertEqual(pergunta["resposta"], "pode lembrar sim")
            self.assertEqual(len(store.agenda_pendente()), 1)

            # O lembrete combinado chega no horário, uma vez só.
            relogio.avancar(hours=2, minutes=1)
            enviados = zeus.tick()
            self.assertEqual(len(enviados), 1)
            self.assertEqual(canal.enviados[-1], "creatina antes do treino")
            self.assertEqual(store.agenda_pendente(), [])
            self.assertEqual(zeus.tick(), [])
            store.close()

    def test_canal_fora_do_ar_nao_perde_a_pendencia(self):
        relogio = Relogio(em(2026, 9, 18, 18, 0))
        canal = CanalMemoria(falhar=True)
        with tempfile.TemporaryDirectory() as temp:
            store, provedor, zeus = montar(temp, relogio, canal, [])
            store.agendar("lembrete", "tomar água", relogio())
            self.assertEqual(zeus.tick(), [])
            self.assertEqual(len(store.agenda_pendente()), 1)

            canal.falhar = False
            self.assertEqual(zeus.tick(), [])  # respeita o backoff
            relogio.avancar(seconds=31)
            enviados = zeus.tick()
            self.assertEqual(len(enviados), 1)
            self.assertEqual(canal.enviados, ["tomar água"])
            store.close()

    def test_persona_expoe_fato_confirmado_e_hipotese_separados(self):
        relogio = Relogio(em(2026, 9, 18, 18, 0))
        with tempfile.TemporaryDirectory() as temp:
            store, provedor, zeus = montar(temp, relogio, CanalMemoria(), [])
            store.remember("tratamento", "senhor", "nicolas", "confirmado")
            store.remember("saida", "por volta das 7h", "observacao", "hipotese")
            contexto = zeus._sistema()
            self.assertIn("Fatos confirmados", contexto)
            self.assertIn("Hipóteses ainda não confirmadas", contexto)
            self.assertIn("Sem câmera", contexto)
            store.close()


if __name__ == "__main__":
    unittest.main()
