"""O laço principal fala o contrato da HUD v1: turno identificado, etapas
reais, fluxo e resposta com o mesmo id, e só as ações de pendência que o
backend suporta. HUD falsa, modelo falso: prova o encanamento, não o X99."""

import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class LacoComHud(unittest.TestCase):
    def test_turno_etapas_resposta_e_pendencia(self):
        from test_conversa import montar
        from zeus.__main__ import executar
        from zeus.llm import Resposta
        from zeus.store import agora_utc
        with tempfile.TemporaryDirectory() as temp:
            store, provedor, zeus = montar(temp, [Resposta("Tudo certo por aqui.", [], "m")])
            self.addCleanup(store.close)
            lembrete = store.agendar("lembrete", "regar as plantas", agora_utc() + timedelta(hours=2))
            zeus.canal = None
            zeus.config.hud_tls = False
            zeus.config.saudacao_ao_ligar = False
            parado = threading.Event()
            pacotes = []

            class HudFalsa:
                def __init__(self, enfileirar, **kwargs):
                    self.enfileirar = enfileirar
                    self.seguro = False

                def iniciar(self):
                    self.enfileirar({"tipo": "texto", "texto": "oi", "id": "h-turno-0001"})
                    self.enfileirar({"tipo": "pendencia", "id": "h-pend-00001", "alvo_tipo": "lembrete",
                                     "alvo": lembrete, "acao": "cancelar"})
                    return 8770

                def publicar(self, tipo, **campos):
                    pacotes.append((tipo, campos))
                    if tipo == "pendencia_resultado":
                        parado.set()

                def estado(self):
                    return {}

                def atualizar(self, *_, **__):
                    pass

                def parar(self):
                    pass

            voz = SimpleNamespace(disponivel=lambda: False, diagnostico=lambda: "ausente", falar=lambda _: None)
            ouvidos = SimpleNamespace(disponivel=lambda: False, diagnostico=lambda: "ausente", destino=Path(temp))
            vigia = threading.Timer(5, parado.set)
            vigia.start()
            try:
                with patch("zeus.__main__.Event", return_value=parado), \
                     patch("zeus.__main__.signal.signal"), \
                     patch("zeus.__main__.ligar_modelo", return_value="m"), \
                     patch("zeus.__main__.montar_voz", return_value=voz), \
                     patch("zeus.__main__.montar_ouvidos", return_value=ouvidos), \
                     patch("zeus.__main__.emit"), \
                     patch("zeus.hud.endereco_local", return_value="127.0.0.1"), \
                     patch("zeus.hud.ServidorHUD", HudFalsa):
                    self.assertEqual(executar(zeus, store, zeus.config), 0)
            finally:
                vigia.cancel()

            etapas = [c["etapa"] for t, c in pacotes if t == "turno" and c.get("turno") == "h-turno-0001"]
            self.assertEqual(etapas[0], "montando_contexto")
            self.assertIn("consultando_modelo", etapas)
            self.assertEqual(etapas[-1], "concluida")
            respostas = [c for t, c in pacotes if t == "mensagem" and c.get("de") == "zeus"]
            self.assertEqual(respostas[0]["turno"], "h-turno-0001")
            self.assertEqual(respostas[0]["detalhes"]["rodadas"], 1)
            self.assertEqual(respostas[0]["detalhes"]["ferramentas"], [])
            fluxos = [c for t, c in pacotes if t == "fluxo" and c.get("pedaco")]
            self.assertTrue(all(c["turno"] == "h-turno-0001" for c in fluxos))
            resultado = [c for t, c in pacotes if t == "pendencia_resultado"][0]
            self.assertTrue(resultado["ok"])
            self.assertEqual(store.agenda_pendente(), [])


if __name__ == "__main__":
    unittest.main()
