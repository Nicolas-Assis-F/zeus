"""Briefing da manhã (#74): fatos do dia, janela, uma vez só, sem ferramentas."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zeus.briefing import (chave_do_dia, coletar, escrever, ja_enviado, na_janela,
                           texto_reserva)
from zeus.entregas import Entregas
from zeus.llm import Resposta
from zeus.store import Store

FUSO = timezone(timedelta(hours=-3))
MANHA = datetime(2026, 10, 19, 7, 40, tzinfo=FUSO)  # segunda-feira


class Persona:
    def instrucao(self):
        return "Você é o Zeus."


class Modelo:
    def __init__(self, texto="Bom dia, senhor. Segunda com reunião às 10h.", falha=None):
        self.texto, self.falha = texto, falha
        self.pedidos = []

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0):
        self.pedidos.append((mensagens, ferramentas))
        if self.falha:
            raise self.falha
        return Resposta(self.texto)


class Tarefas:
    def situacao(self):
        return [{"numero": 3, "titulo": "Filtro na dash", "situacao": "rodando"},
                {"numero": 2, "titulo": "Antiga", "situacao": "concluída"},
                {"numero": 1, "titulo": "Quebrou", "situacao": "falhou"}]


class Base:
    def consultar(self, busca):
        return {"secoes": [{"secao": "A receber", "texto": "Cliente X: parcela 2 vence dia 20."}]}


class TestBriefing(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()))

    def tearDown(self):
        self.store.close()

    def test_janela_depois_da_hora(self):
        self.assertTrue(na_janela(MANHA, "07:30"))
        self.assertFalse(na_janela(MANHA.replace(hour=7, minute=29), "07:30"))
        self.assertFalse(na_janela(MANHA.replace(hour=15), "07:30"))  # não é bom-dia às 15h
        self.assertFalse(na_janela(MANHA, ""))
        self.assertFalse(na_janela(MANHA, "25:00"))

    def test_coleta_so_o_que_e_de_hoje(self):
        self.store.agendar("lembrete", "Reunião com o Henrique", MANHA.replace(hour=10, minute=0))
        self.store.agendar("lembrete", "Coisa de amanhã", MANHA + timedelta(days=1))
        Entregas(self.store).preparar("vigia:1", "whatsapp", "Henrique pediu o filtro novo",
                                      tipo="aviso_terceiro", agora=MANHA - timedelta(hours=2))
        Entregas(self.store).preparar("vigia:0", "whatsapp", "Aviso velho",
                                      tipo="aviso_terceiro", agora=MANHA - timedelta(days=2))
        dados = coletar(self.store, MANHA, Tarefas(), Base())
        self.assertEqual(dados["agora"], "segunda-feira, 19/10 07:40")
        self.assertEqual(dados["agenda_de_hoje"], [{"quando": "10:00",
                                                    "texto": "Reunião com o Henrique"}])
        self.assertEqual(dados["avisos_das_ultimas_24h"], ["Henrique pediu o filtro novo"])
        self.assertEqual([t["numero"] for t in dados["tarefas_de_codigo"]], [3])
        self.assertIn("parcela 2", dados["pendencias_da_base"][0])

    def test_fonte_que_falha_fica_de_fora(self):
        class Quebrada:
            def situacao(self):
                raise OSError("sem orca")
        dados = coletar(self.store, MANHA, Quebrada(), None)
        self.assertNotIn("tarefas_de_codigo", dados)

    def test_escreve_sem_ferramentas(self):
        modelo = Modelo()
        texto = escrever(modelo, Persona(), coletar(self.store, MANHA))
        self.assertEqual(texto, "Bom dia, senhor. Segunda com reunião às 10h.")
        mensagens, ferramentas = modelo.pedidos[0]
        self.assertIsNone(ferramentas)
        self.assertIn("No máximo 180 palavras", mensagens[1]["content"])

    def test_modelo_fora_usa_reserva_com_os_fatos(self):
        self.store.agendar("lembrete", "Dentista", MANHA.replace(hour=9, minute=0))
        dados = coletar(self.store, MANHA)
        texto = escrever(Modelo(falha=RuntimeError("caiu")), Persona(), dados)
        self.assertIn("09:00 Dentista", texto)
        self.assertEqual(escrever(None, Persona(), dados), texto)

    def test_dia_limpo(self):
        self.assertIn("limpo", texto_reserva(coletar(self.store, MANHA)))

    def test_uma_vez_por_dia(self):
        chave = chave_do_dia(MANHA)
        self.assertEqual(chave, "briefing:2026-10-19")
        self.assertFalse(ja_enviado(self.store, chave))
        Entregas(self.store).preparar(chave, "whatsapp", "Bom dia.", tipo="aviso_terceiro")
        self.assertTrue(ja_enviado(self.store, chave))
        # O próprio briefing não entra como aviso no briefing seguinte.
        self.assertEqual(coletar(self.store, MANHA + timedelta(hours=1))["avisos_das_ultimas_24h"], [])


if __name__ == "__main__":
    unittest.main()
