"""Esquecer e desfazer pela HUD (#79)."""

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from zeus.hud import ServidorHUD
from zeus.memoria_hud import MemoriaDaHUD
from zeus.store import Store


class Relogio:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


class TestMemoriaDaHUD(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()))
        self.store.remember("academia", "18h", "user", "confirmado")
        self.relogio = Relogio()
        self.memoria = MemoriaDaHUD(self.store, relogio=self.relogio)

    def tearDown(self):
        self.store.close()

    def test_esquecer_e_desfazer_restaura_igual(self):
        antes = self.store.recall("academia")
        self.assertTrue(self.memoria.executar("esquecer", "academia")["ok"])
        self.assertIsNone(self.store.recall("academia"))
        resultado = self.memoria.executar("desfazer", "academia")
        self.assertEqual(resultado["acao"], "restaurada")
        depois = self.store.recall("academia")
        self.assertEqual((depois["value"], depois["source"], depois["estado"]),
                         (antes["value"], antes["source"], antes["estado"]))

    def test_desfazer_expira(self):
        self.memoria.esquecer("academia")
        self.relogio.agora = 301
        self.assertFalse(self.memoria.desfazer("academia")["ok"])
        self.assertIsNone(self.store.recall("academia"))

    def test_desfazer_sem_ter_esquecido_nao_escreve(self):
        self.assertFalse(self.memoria.desfazer("inventado")["ok"])
        self.assertIsNone(self.store.recall("inventado"))

    def test_fato_inexistente(self):
        self.assertFalse(self.memoria.esquecer("nada")["ok"])

    def test_fica_registrado_como_episodio(self):
        self.memoria.esquecer("academia")
        tipos = [l[0] for l in self.store.connection.execute("SELECT tipo FROM episodios")]
        self.assertIn("memoria_esquecida", tipos)


class TestRota(unittest.TestCase):
    def setUp(self):
        self.recebidas = []
        self.hud = ServidorHUD(enfileirar=self.recebidas.append, chave="segredo",
                               host="127.0.0.1", porta=0, estado={"tipo": "estado"})
        self.porta = self.hud.iniciar()

    def tearDown(self):
        self.hud.parar()

    def postar(self, dados, chave="segredo"):
        pedido = urllib.request.Request(
            f"http://127.0.0.1:{self.porta}/memoria?chave={chave}",
            data=json.dumps(dados).encode(), method="POST")
        try:
            with urllib.request.urlopen(pedido, timeout=5) as resposta:
                return resposta.status
        except urllib.error.HTTPError as erro:
            return erro.code

    def test_enfileira_sem_mexer_no_banco(self):
        self.assertEqual(self.postar({"acao": "esquecer", "fato": "academia"}), 202)
        self.assertEqual(self.recebidas, [{"tipo": "memoria", "acao": "esquecer",
                                           "fato": "academia"}])

    def test_exige_chave_e_acao_conhecida(self):
        self.assertEqual(self.postar({"acao": "esquecer", "fato": "x"}, chave="errada"), 401)
        self.assertEqual(self.postar({"acao": "lembrar", "fato": "x"}), 400)
        self.assertEqual(self.postar({"acao": "esquecer", "fato": "  "}), 400)
        self.assertEqual(self.recebidas, [])


if __name__ == "__main__":
    unittest.main()
