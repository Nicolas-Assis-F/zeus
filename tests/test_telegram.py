import tempfile
import unittest
from pathlib import Path

from apoio import transporte_roteirizado
from zeus.canais.telegram import CanalTelegram, ErroDeCanal
from zeus.store import Store


class Canal(unittest.TestCase):
    def test_exige_configuracao(self):
        with self.assertRaises(ErroDeCanal):
            CanalTelegram("", "", None)

    def test_offset_persiste_entre_reinicios(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            atualizacoes = {"ok": True, "result": [
                {"update_id": 41, "message": {"chat": {"id": 7}, "text": "oi"}},
            ]}
            transporte = transporte_roteirizado([("getUpdates", atualizacoes)])
            canal = CanalTelegram("token", "7", store, transporte)
            mensagens = canal.receber(0)
            self.assertEqual(mensagens[0]["texto"], "oi")
            canal.confirmar(mensagens[0]["id"])

            outro = CanalTelegram("token", "7", Store(Path(temp)), transporte)
            outro.receber(0)
            self.assertEqual(transporte.chamadas[-1]["corpo"]["offset"], 42)
            store.close()

    def test_conversa_de_terceiro_e_descartada(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            atualizacoes = {"ok": True, "result": [
                {"update_id": 10, "message": {"chat": {"id": 999}, "text": "quem é você"}},
            ]}
            canal = CanalTelegram("token", "7", store, transporte_roteirizado([("getUpdates", atualizacoes)]))
            self.assertEqual(canal.receber(0), [])
            self.assertEqual(store.kv_get("telegram_offset"), "11")
            store.close()

    def test_falha_do_telegram_vira_erro_claro(self):
        transporte = transporte_roteirizado([("sendMessage", {"ok": False, "description": "chat not found"})])
        canal = CanalTelegram("token", "7", None, transporte)
        with self.assertRaises(ErroDeCanal) as erro:
            canal.enviar("teste")
        self.assertIn("chat not found", str(erro.exception))


if __name__ == "__main__":
    unittest.main()
