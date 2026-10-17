"""Vigia do serviço (#70): só avisa quando o estado muda."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zeus.vigia_servico import comparar, mensagem, problemas_do_check, rodada

SAUDAVEL = json.dumps({"event": "storage_check", "storage": "ok",
                       "modelo": "anthropic/claude-sonnet-5.5", "canal": "banco legível"})


class Maquina:
    def __init__(self, check=SAUDAVEL):
        self.check = check
        self.unidades = {"zeus": "active", "ponte-principal": "active", "ponte-zeus": "active"}
        self.reinicios = []
        self.volta_ao_reiniciar = True

    def __call__(self, comando, timeout=0):
        if comando[:3] == ["systemctl", "--user", "restart"]:
            self.reinicios.append(comando[-1])
            if self.volta_ao_reiniciar:
                self.unidades[comando[-1]] = "active"
            return 0, ""
        if comando[0] == "systemctl":
            return 0, self.unidades[comando[-1]] + "\n"
        return 0, "ruído\n" + self.check + "\n"


class TestVigia(unittest.TestCase):
    def setUp(self):
        self.estado = Path(tempfile.mkdtemp()) / "vigia.json"
        self.config = SimpleNamespace(whatsapp_grupo="grupo", whatsapp_ponte_url="http://ponte")
        self.enviados = []
        self.maquina = Maquina()

    def rodar(self, entrega=True, recuperar=False):
        def enviar(url, grupo, texto):
            self.enviados.append((grupo, texto))
            return entrega
        return rodada(Path("/repo"), self.config, self.estado, executar=self.maquina,
                      enviar=enviar, recuperar_unidades=recuperar)

    def test_tudo_saudavel_fica_quieto(self):
        for _ in range(3):
            self.assertEqual(self.rodar()["problemas"], {})
        self.assertEqual(self.enviados, [])

    def test_ponte_parada_avisa_uma_vez_depois_de_confirmar_e_volta(self):
        self.maquina.unidades["ponte-principal"] = "inactive"
        self.assertEqual(self.rodar()["caiu"], [])  # primeira vez: pode ser passageiro
        self.assertEqual(self.rodar()["caiu"], ["ponte-principal"])
        self.rodar()
        self.assertEqual(len(self.enviados), 1)
        self.assertEqual(self.enviados[0][0], "grupo")
        self.assertIn("ponte-principal: unidade inactive", self.enviados[0][1])
        self.maquina.unidades["ponte-principal"] = "active"
        self.assertEqual(self.rodar()["voltou"], ["ponte-principal"])
        self.assertIn("Voltou ao normal: ponte-principal", self.enviados[1][1])

    def test_problema_passageiro_nao_avisa(self):
        self.maquina.unidades["zeus"] = "activating"
        self.rodar()
        self.maquina.unidades["zeus"] = "active"
        self.rodar()
        self.assertEqual(self.enviados, [])

    def test_aviso_nao_entregue_tenta_de_novo(self):
        self.maquina.unidades["ponte-zeus"] = "failed"
        self.rodar(entrega=False)
        self.rodar(entrega=False)
        self.rodar(entrega=True)
        self.assertEqual(len(self.enviados), 2)

    def test_modelo_recusado_vira_problema(self):
        self.maquina.check = json.dumps({"event": "storage_check", "storage": "ok",
                                         "modelo": "falhou: 401 chave recusada", "canal": "ok"})
        self.rodar()
        self.assertIn("modelo", self.rodar()["caiu"])

    def test_falha_recupera_sozinho_e_conta(self):
        self.maquina.unidades["ponte-zeus"] = "inactive"
        self.rodar(recuperar=True)
        r = self.rodar(recuperar=True)
        self.assertEqual(self.maquina.reinicios, ["ponte-zeus"])
        self.assertIn("reiniciei", self.enviados[-1][1])
        self.rodar(recuperar=True)
        self.assertIn("Voltou depois do reinício: ponte-zeus", self.enviados[-1][1])
        self.assertEqual(self.maquina.reinicios, ["ponte-zeus"])

    def test_nao_voltou_pede_ajuda_e_nao_insiste(self):
        self.maquina.volta_ao_reiniciar = False
        self.maquina.unidades["ponte-principal"] = "failed"
        for _ in range(5):
            self.rodar(recuperar=True)
        self.assertEqual(self.maquina.reinicios, ["ponte-principal"])   # uma tentativa só
        self.assertTrue(any("Precisa de você" in t for _, t in self.enviados))

    def test_check_sem_resposta(self):
        self.assertEqual(problemas_do_check(""), {"check": "o check não respondeu"})

    def test_comparar_e_mensagem(self):
        estado, caiu, voltou = comparar({}, {"zeus": "unidade failed"}, confirmacoes=1)
        self.assertEqual(caiu, [("zeus", "unidade failed")])
        self.assertTrue(estado["zeus"]["avisado"])
        self.assertIn("- zeus: unidade failed", mensagem(caiu, voltou))


if __name__ == "__main__":
    unittest.main()
