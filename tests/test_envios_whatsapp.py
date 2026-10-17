"""Travas do envio pelo número principal (#82): só com comando, sem duplicar."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zeus.envios_whatsapp import EnvioRecusado, EnviosWhatsApp, confirmacao_de_envio
from zeus.store import Store

ANTES = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
DEPOIS = ANTES + timedelta(minutes=1)


class Leitor:
    def achar(self, busca):
        if busca.lower().startswith("henr"):
            return "5562999990000@s.whatsapp.net", "Henrique"
        if busca.lower().startswith("grupo"):
            return "123@g.us", "Grupo"
        raise ValueError("não achei")


class Ponte:
    def __init__(self, *respostas):
        self.respostas = list(respostas) or [(200, {"success": True, "message": "ok"})]
        self.envios = []

    def __call__(self, url, corpo):
        self.envios.append(corpo)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


class TestEnvios(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()))

    def tearDown(self):
        self.store.close()

    def envios(self, ponte):
        return EnviosWhatsApp("http://ponte", Leitor(), self.store, transporte=ponte)

    def test_sem_comando_nao_envia(self):
        ponte = Ponte()
        e = self.envios(ponte)
        r = e.preparar("Henrique", "Oi, tudo certo?", inicio=ANTES)
        with self.assertRaises(EnvioRecusado):
            e.enviar(r["numero"], DEPOIS, "o que você acha?")
        self.assertEqual(ponte.envios, [])

    def test_comando_com_destinatario_envia_uma_vez(self):
        ponte = Ponte()
        e = self.envios(ponte)
        r = e.preparar("Henrique", "Oi, tudo certo?", inicio=ANTES)
        self.assertTrue(e.enviar(r["numero"], DEPOIS, "manda pro Henrique")["enviado"])
        self.assertTrue(e.enviar(r["numero"], DEPOIS, "manda pro Henrique")["duplicado_evitado"])
        self.assertEqual(len(ponte.envios), 1)

    def test_negacao_recusa(self):
        ponte = Ponte()
        e = self.envios(ponte)
        r = e.preparar("Henrique", "Oi", inicio=ANTES)
        with self.assertRaises(EnvioRecusado):
            e.enviar(r["numero"], DEPOIS, "não manda pro Henrique ainda")
        self.assertEqual(ponte.envios, [])

    def test_confirmacao_curta_so_vale_para_rascunho_anterior(self):
        ponte = Ponte()
        e = self.envios(ponte)
        r = e.preparar("Henrique", "Oi", inicio=ANTES)
        with self.assertRaises(EnvioRecusado):  # mesmo turno em que preparou
            e.enviar(r["numero"], ANTES, "manda")
        self.assertTrue(e.enviar(r["numero"], DEPOIS, "manda")["enviado"])
        self.assertTrue(confirmacao_de_envio("Pode mandar"))
        self.assertFalse(confirmacao_de_envio("manda o orçamento pro outro cliente"))

    def test_resposta_ambigua_fica_incerta_e_nao_repete(self):
        ponte = Ponte(TimeoutError())
        e = self.envios(ponte)
        r = e.preparar("Henrique", "Oi", inicio=ANTES)
        with self.assertRaises(EnvioRecusado):
            e.enviar(r["numero"], DEPOIS, "manda pro Henrique")
        with self.assertRaises(EnvioRecusado) as erro:
            e.enviar(r["numero"], DEPOIS, "manda pro Henrique")
        self.assertIn("incerto", str(erro.exception))
        self.assertEqual(len(ponte.envios), 1)

    def test_so_contato_individual(self):
        with self.assertRaises(EnvioRecusado):
            self.envios(Ponte()).preparar("grupo da família", "Oi", inicio=ANTES)


if __name__ == "__main__":
    unittest.main()
