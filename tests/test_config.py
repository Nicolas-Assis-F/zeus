import json
import tempfile
import unittest
from pathlib import Path

from zeus.config import carregar


class Origem(unittest.TestCase):
    def test_arquivo_ausente_e_dito_em_voz_alta(self):
        with tempfile.TemporaryDirectory() as temp:
            config = carregar(Path(temp) / "config.json")
        self.assertIn("não existe", config.origem)
        self.assertFalse(config.canal_configurado)

    def test_arquivo_lido_aparece_na_origem_e_segredo_nao_vaza(self):
        with tempfile.TemporaryDirectory() as temp:
            caminho = Path(temp) / "config.json"
            caminho.write_text(json.dumps({"telegram_token": "abc", "telegram_chat_id": "7"}),
                               encoding="utf-8")
            config = carregar(caminho)
        self.assertEqual(config.origem, str(caminho))
        self.assertTrue(config.canal_configurado)
        self.assertEqual(config.sem_segredos()["telegram_token"], "definido")
        self.assertNotIn("abc", json.dumps(config.sem_segredos()))


if __name__ == "__main__":
    unittest.main()
