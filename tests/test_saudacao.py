"""A saudação ao ligar, e o freio que impede ela de virar alarme.

Um serviço reinicia — por atualização, por falha do modelo, por queda de rede,
e muitas vezes seguidas quando algo está errado. "Bom dia, senhor" a cada
reinício é a diferença entre presença e alarme, e é esse o teste central aqui.
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from zeus.saudacao import (compor, deve_saudar, frase_reserva,
                           identificador_de_boot, parte_do_dia)
from zeus.store import Store


class Freio(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.pasta.name))

    def tearDown(self):
        self.store.connection.close()
        self.pasta.cleanup()

    def test_uma_saudacao_por_ligada_da_maquina(self):
        reservar = self.store.marcar_envio
        self.assertTrue(deve_saudar(reservar, "boot-1"))
        self.assertFalse(deve_saudar(reservar, "boot-1"))   # reinício do serviço
        self.assertFalse(deve_saudar(reservar, "boot-1"))
        self.assertTrue(deve_saudar(reservar, "boot-2"))    # a máquina ligou de novo

    def test_sem_identificador_de_boot_ela_fica_de_fora(self):
        """Sem o freio, ela viraria a cada reinício. Falar demais é pior."""
        self.assertFalse(deve_saudar(self.store.marcar_envio, ""))

    def test_desligada_na_configuracao_nao_gasta_nem_a_marca(self):
        self.assertFalse(deve_saudar(self.store.marcar_envio, "boot-3", ligada=False))
        self.assertTrue(deve_saudar(self.store.marcar_envio, "boot-3"))

    def test_o_modelo_so_e_chamado_quando_ha_o_que_falar(self):
        """O portão é barato de propósito: reinício não gasta uma geração."""
        chamadas = []

        def responder(pedido, canal):
            chamadas.append(pedido)
            return "De pé, senhor."

        agora = datetime(2026, 9, 20, 9, 0)
        primeira = compor(self.store, self.store.marcar_envio, responder, agora, "b")
        segunda = compor(self.store, self.store.marcar_envio, responder, agora, "b")
        self.assertEqual(primeira, "De pé, senhor.")
        self.assertIsNone(segunda)
        self.assertEqual(len(chamadas), 1)

    def test_modelo_fora_do_ar_ainda_rende_saudacao(self):
        """Máquina que liga sem dizer nada parece quebrada."""
        def cai(pedido, canal):
            raise RuntimeError("modelo ainda subindo")

        texto = compor(self.store, self.store.marcar_envio, cai,
                       datetime(2026, 9, 20, 7, 30), "b")
        self.assertIn("Bom dia", texto)
        self.assertIn("de pé", texto.lower())

    def test_resposta_vazia_tambem_cai_na_reserva(self):
        texto = compor(self.store, self.store.marcar_envio,
                       lambda p, c: "   ", datetime(2026, 9, 20, 20, 0), "b")
        self.assertIn("Boa noite", texto)

    def test_a_reserva_conta_as_pendencias(self):
        from datetime import timezone
        self.store.criar_pergunta("confirmo o treino?", "faltou dado",
                                  datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc))
        texto = compor(self.store, self.store.marcar_envio,
                       lambda p, c: "", datetime(2026, 9, 20, 9, 0), "b")
        self.assertIn("uma pendência", texto)


class Relogio(unittest.TestCase):
    def test_a_parte_do_dia_cobre_as_vinte_e_quatro_horas(self):
        esperado = {0: "Boa madrugada", 4: "Boa madrugada", 5: "Bom dia",
                    11: "Bom dia", 12: "Boa tarde", 17: "Boa tarde",
                    18: "Boa noite", 23: "Boa noite"}
        for hora, frase in esperado.items():
            self.assertEqual(parte_do_dia(datetime(2026, 9, 20, hora)), frase)

    def test_a_reserva_muda_com_o_numero_de_pendencias(self):
        agora = datetime(2026, 9, 20, 15, 0)
        self.assertNotIn("pendência", frase_reserva(agora, 0))
        self.assertIn("uma pendência", frase_reserva(agora, 1))
        self.assertIn("3 pendências", frase_reserva(agora, 3))


class Boot(unittest.TestCase):
    def test_arquivo_ausente_devolve_vazio_em_vez_de_quebrar(self):
        self.assertEqual(identificador_de_boot(Path("/nao/existe/boot_id")), "")

    def test_no_linux_o_identificador_existe_e_e_estavel(self):
        atual = identificador_de_boot()
        if not atual:
            self.skipTest("este sistema não expõe boot_id")
        self.assertEqual(atual, identificador_de_boot())
        self.assertLessEqual(len(atual), 64)


if __name__ == "__main__":
    unittest.main()
