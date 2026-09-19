"""A HUD é a porta do Zeus na rede de casa: rota errada e chave frouxa importam."""

import json
import queue
import tempfile
from pathlib import Path
import threading
import unittest
import urllib.error
import urllib.request

from zeus.hud import ServidorHUD
from zeus.voz import Voz

RETRATO = {"tipo": "estado", "fatos": [], "perguntas": [], "lembretes": [],
           "turnos": [], "modelo": "modelo-falso", "voz": False}


class Servidor(unittest.TestCase):
    def setUp(self):
        self.recebidas = []
        self.hud = ServidorHUD(enfileirar=self.recebidas.append, voz=Voz(),
                               chave="chave-secreta", host="127.0.0.1", porta=0,
                               estado=RETRATO)
        self.porta = self.hud.iniciar()

    def tearDown(self):
        self.hud.parar()

    def pedir(self, caminho, dados=None, chave="chave-secreta", corpo_bruto=None):
        url = f"http://127.0.0.1:{self.porta}{caminho}"
        if chave is not None:
            url += f"?chave={chave}"
        corpo = corpo_bruto if corpo_bruto is not None else (
            json.dumps(dados).encode("utf-8") if dados is not None else None)
        pedido = urllib.request.Request(url, data=corpo,
                                        method="POST" if corpo is not None else "GET")
        try:
            with urllib.request.urlopen(pedido, timeout=5) as resposta:
                return resposta.status, resposta.read()
        except urllib.error.HTTPError as erro:
            return erro.code, erro.read()

    def test_exige_chave_para_dado_e_nao_para_a_pagina(self):
        self.assertEqual(self.pedir("/", chave=None)[0], 200)
        self.assertEqual(self.pedir("/estado", chave="errada")[0], 401)
        self.assertEqual(self.pedir("/estado", chave=None)[0], 401)
        codigo, corpo = self.pedir("/estado")
        self.assertEqual(codigo, 200)
        self.assertEqual(json.loads(corpo)["modelo"], "modelo-falso")

    def test_mensagem_entra_na_fila_do_laco_principal(self):
        self.assertEqual(self.pedir("/mensagem", {"texto": "bom dia"})[0], 202)
        self.assertEqual(self.recebidas, [{"tipo": "texto", "texto": "bom dia"}])
        self.assertEqual(self.pedir("/mensagem", {"texto": "   "})[0], 400)
        self.assertEqual(self.pedir("/mensagem", corpo_bruto=b"nao e json")[0], 400)
        self.assertEqual(self.pedir("/mensagem", {"texto": "x" * 5000})[0], 413)
        self.assertEqual(self.recebidas, [{"tipo": "texto", "texto": "bom dia"}])

    def test_corpo_sem_objeto_ou_texto_nao_string_e_recusado(self):
        for corpo in (b'[]', b'null', b'{"texto":42}'):
            self.assertEqual(self.pedir("/mensagem", corpo_bruto=corpo)[0], 400)
        self.assertFalse(self.recebidas)

    def test_fila_cheia_devolve_503_sem_manter_gravacao(self):
        def cheia(_):
            raise queue.Full
        self.hud.enfileirar = cheia
        self.assertEqual(self.pedir("/mensagem", {"texto": "oi"})[0], 503)
        with tempfile.TemporaryDirectory() as pasta:
            self.hud.pasta_de_escuta = Path(pasta)
            self.assertEqual(self.pedir("/escuta", corpo_bruto=b'audio')[0], 503)
            self.assertEqual(list(Path(pasta).iterdir()), [])

    def test_rotas_desconhecidas_e_audio_inexistente(self):
        self.assertEqual(self.pedir("/qualquer")[0], 404)
        self.assertEqual(self.pedir("/audio/nao_existe.wav")[0], 404)
        self.assertEqual(self.pedir("/audio/../../etc/passwd")[0], 404)
        self.assertEqual(self.pedir("/favicon.ico", chave=None)[0], 204)

    def test_retrato_atualizado_chega_a_quem_esta_ouvindo(self):
        recebido = []

        def ouvir():
            url = f"http://127.0.0.1:{self.porta}/fluxo?chave=chave-secreta"
            with urllib.request.urlopen(url, timeout=8) as fluxo:
                for linha in fluxo:
                    if linha.startswith(b"data: "):
                        recebido.append(json.loads(linha[6:].decode("utf-8")))
                        return

        ouvinte = threading.Thread(target=ouvir, daemon=True)
        ouvinte.start()
        for _ in range(40):
            threading.Event().wait(0.05)
            if self.hud.assinantes:
                break
        self.hud.atualizar({**RETRATO, "modelo": "outro-modelo"})
        ouvinte.join(timeout=5)
        self.assertEqual(recebido[0]["modelo"], "outro-modelo")
        self.assertEqual(self.hud.estado()["modelo"], "outro-modelo")


class VozAusente(unittest.TestCase):
    def test_sem_piper_o_zeus_continua_escrevendo(self):
        voz = Voz(binario="piper-que-nao-existe")
        self.assertFalse(voz.disponivel())
        self.assertIn("não encontrado", voz.diagnostico())
        self.assertIsNone(voz.falar("qualquer coisa"))


if __name__ == "__main__":
    unittest.main()
