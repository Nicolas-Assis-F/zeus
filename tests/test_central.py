"""Central do Zeus (#84): sessão, admissão, eventos e escrita mínima.

Os testes de admissão e de eventos são os bloqueadores da reauditoria da #45
(A01–A03, A07–A10) escritos como exigência do comportamento corrigido."""

import http.client
import json
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path

from zeus.hud import ServidorHUD
from zeus.hud.central import Central, Controles


class Base(unittest.TestCase):
    def setUp(self):
        self.fila = queue.Queue(maxsize=200)
        self.hud = ServidorHUD(enfileirar=self.fila.put_nowait, chave="chave-secreta",
                               host="127.0.0.1", porta=0,
                               estado={"tipo": "estado", "fatos": [], "turnos": []},
                               pasta_de_escuta=tempfile.mkdtemp())
        self.pasta = Path(tempfile.mkdtemp())
        self.central = Central(self.hud, controles=Controles(self.pasta / "controles.json"))
        self.hud.central = self.central
        self.porta = self.hud.iniciar()
        self.cookie = ""

    def tearDown(self):
        self.hud.parar()

    def pedir(self, metodo, caminho, corpo=None, cabecalhos=None, cookie=None, bruto=None):
        conexao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        h = {"X-Zeus": "1", "Origin": f"http://127.0.0.1:{self.porta}", "Host": f"127.0.0.1:{self.porta}"}
        if cookie if cookie is not None else self.cookie:
            h["Cookie"] = cookie if cookie is not None else self.cookie
        if corpo is not None:
            bruto = json.dumps(corpo).encode()
            h["Content-Type"] = "application/json"
        h.update(cabecalhos or {})
        conexao.request(metodo, caminho, body=bruto, headers=h)
        r = conexao.getresponse()
        dados = r.read()
        conexao.close()
        try:
            dados = json.loads(dados)
        except ValueError:
            pass
        return r.status, dados, r.getheader("Set-Cookie") or ""

    def entrar(self):
        status, _, cookie = self.pedir("POST", "/central/api/sessao", {"chave": "chave-secreta"})
        self.assertEqual(status, 200)
        self.cookie = cookie.split(";")[0]
        return cookie


class TestSessao(Base):
    def test_pagina_e_publica_e_dado_exige_sessao(self):
        status, corpo, _ = self.pedir("GET", "/central/")
        self.assertEqual(status, 200)
        self.assertIn(b"Central", corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode())
        self.assertEqual(self.pedir("GET", "/central/api/retrato")[0], 401)

    def test_cookie_seguro_e_unico_caminho(self):
        cookie = self.entrar()
        for parte in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(parte, cookie)
        self.assertEqual(self.pedir("GET", "/central/api/retrato")[0], 200)
        # A07: chave em cabeçalho ou na URL não abre a Central.
        self.assertEqual(self.pedir("GET", "/central/api/retrato?chave=chave-secreta", cookie="")[0], 401)
        self.assertEqual(self.pedir("GET", "/central/api/retrato", cookie="",
                                    cabecalhos={"X-Zeus-Chave": "chave-secreta"})[0], 401)

    def test_limite_de_tentativas(self):
        for _ in range(5):
            self.assertEqual(self.pedir("POST", "/central/api/sessao", {"chave": "errada"})[0], 401)
        # Até a chave certa é recusada enquanto o limite vale.
        self.assertEqual(self.pedir("POST", "/central/api/sessao", {"chave": "chave-secreta"})[0], 429)

    def test_sair_invalida(self):
        self.entrar()
        self.assertEqual(self.pedir("POST", "/central/api/sair", {})[0], 200)
        self.assertEqual(self.pedir("GET", "/central/api/retrato")[0], 401)

    def test_csrf(self):
        self.entrar()
        self.assertEqual(self.pedir("POST", "/central/api/mensagem", {"id": "x" * 10, "texto": "oi"},
                                    cabecalhos={"X-Zeus": "0"})[0], 403)
        self.assertEqual(self.pedir("POST", "/central/api/mensagem", {"id": "x" * 10, "texto": "oi"},
                                    cabecalhos={"Origin": "http://mal.exemplo"})[0], 403)

    def test_estaticos_sem_fuga_da_pasta(self):
        self.assertEqual(self.pedir("GET", "/central/js/app.js")[0], 200)
        self.assertEqual(self.pedir("GET", "/central/../servidor.py")[0], 404)
        self.assertEqual(self.pedir("GET", "/central/%2e%2e/central.py")[0], 404)

    def test_hud_classica_continua(self):
        self.assertEqual(self.pedir("GET", "/estado?chave=chave-secreta", cookie="")[0], 200)


class TestAdmissao(Base):
    def test_a01_concorrencia_mesmo_id_entra_uma_vez(self):
        self.entrar()
        resultados = []
        def enviar():
            resultados.append(self.pedir("POST", "/central/api/mensagem", {"id": "mesmo-id-123", "texto": "oi"})[0])
        threads = [threading.Thread(target=enviar) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.fila.qsize(), 1)
        self.assertEqual(resultados.count(202), 1)
        self.assertEqual(resultados.count(200), 99)

    def test_a02_fila_cheia_e_repetivel(self):
        self.entrar()
        cheia = queue.Queue(maxsize=1)
        cheia.put("ocupada")
        self.hud.enfileirar = cheia.put_nowait
        status, corpo, _ = self.pedir("POST", "/central/api/mensagem", {"id": "repetivel-1", "texto": "oi"})
        self.assertEqual((status, corpo.get("repetivel")), (503, True))
        cheia.get()
        self.assertEqual(self.pedir("POST", "/central/api/mensagem", {"id": "repetivel-1", "texto": "oi"})[0], 202)
        self.assertEqual(cheia.qsize(), 1)
        self.assertEqual(self.pedir("POST", "/central/api/mensagem", {"id": "repetivel-1", "texto": "oi"})[0], 200)
        self.assertEqual(cheia.qsize(), 1)

    def test_a03_identidade_nao_depende_do_historico(self):
        self.entrar()
        self.pedir("POST", "/central/api/mensagem", {"id": "primeiro-id", "texto": "oi"})
        for i in range(120):
            self.pedir("POST", "/central/api/mensagem", {"id": f"outro-id-{i:04}", "texto": "oi"})
        self.assertEqual(self.pedir("POST", "/central/api/mensagem", {"id": "primeiro-id", "texto": "oi"})[0], 200)
        self.assertEqual(self.fila.qsize(), 121)

    def test_mesmo_id_outro_conteudo_e_conflito(self):
        self.entrar()
        self.pedir("POST", "/central/api/mensagem", {"id": "conflito-1", "texto": "oi"})
        self.assertEqual(self.pedir("POST", "/central/api/mensagem", {"id": "conflito-1", "texto": "tchau"})[0], 409)

    def test_audio_com_id(self):
        self.entrar()
        status, _, _ = self.pedir("POST", "/central/api/escuta", bruto=b"\0" * 2000,
                                  cabecalhos={"Content-Type": "audio/webm", "X-Zeus-Turno": "audio-id-1"})
        self.assertEqual(status, 202)
        pedido = self.fila.get_nowait()
        self.assertEqual((pedido["tipo"], pedido["id"]), ("audio", "audio-id-1"))
        self.assertTrue(Path(pedido["arquivo"]).is_file())


class TestEventos(Base):
    def ler_fluxo(self, caminho, quantos, cookie=None):
        conexao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        conexao.request("GET", caminho, headers={"Cookie": cookie or self.cookie})
        r = conexao.getresponse()
        pacotes, atual = [], {}
        while len(pacotes) < quantos:
            linha = r.fp.readline().decode().rstrip("\n")
            if linha.startswith("data: "):
                atual["data"] = json.loads(linha[6:])
            elif linha.startswith("id: "):
                atual["id"] = int(linha[4:])
            elif linha.startswith("event: "):
                atual["event"] = linha[7:]
            elif linha == "" and atual:
                pacotes.append(atual)
                atual = {}
        conexao.close()
        return pacotes

    def test_a10_primeiro_e_ola_e_a09_replay_depois_do_retrato(self):
        self.entrar()
        self.hud.publicar("mensagem", de="zeus", texto="antes")
        _, retrato, _ = self.pedir("GET", "/central/api/retrato")
        marca = retrato["seq"]
        # Chegam eventos entre o retrato e a abertura do fluxo:
        self.hud.publicar("mensagem", de="zeus", texto="entre 1")
        self.hud.publicar("mensagem", de="zeus", texto="entre 2")
        pacotes = self.ler_fluxo(f"/central/api/eventos?desde={marca}&boot={retrato['boot']}", 3)
        self.assertEqual(pacotes[0]["data"]["tipo"], "ola")
        self.assertEqual([p["data"]["texto"] for p in pacotes[1:]], ["entre 1", "entre 2"])
        self.assertEqual([p["id"] for p in pacotes[1:]], [marca + 1, marca + 2])

    def test_outra_subida_manda_ressincronizar(self):
        self.entrar()
        pacotes = self.ler_fluxo("/central/api/eventos?desde=5&boot=antigo", 1)
        self.assertTrue(pacotes[0]["data"]["ressincronizar"])

    def test_a08_sair_encerra_o_fluxo(self):
        import zeus.hud.central as central
        original = central.BATIDA_S
        central.BATIDA_S = 0.3
        try:
            self.entrar()
            resultado = []
            leitor = threading.Thread(target=lambda: resultado.extend(
                self.ler_fluxo("/central/api/eventos?desde=0", 2)))
            leitor.start()
            time.sleep(0.2)
            self.pedir("POST", "/central/api/sair", {})
            leitor.join(timeout=5)
            self.assertFalse(leitor.is_alive())
            self.assertEqual(resultado[-1]["event"], "sessao")
        finally:
            central.BATIDA_S = original

    def test_sem_sessao_nao_assina(self):
        self.assertEqual(self.pedir("GET", "/central/api/eventos")[0], 401)


class TestControles(Base):
    def test_ajustes_validados_e_persistidos(self):
        self.entrar()
        status, corpo, _ = self.pedir("POST", "/central/api/controles", {"mudo": True, "autonomia": "conservadora",
                                                                         "nao_perturbe_minutos": 30})
        self.assertEqual(status, 200)
        self.assertTrue(corpo["mudo"])
        self.assertTrue(corpo["nao_perturbe"])
        self.assertEqual(json.loads((self.pasta / "controles.json").read_text())["autonomia"], "conservadora")
        self.assertEqual(self.pedir("POST", "/central/api/controles", {"autonomia": "sem_freio"})[0], 400)
        self.assertEqual(self.pedir("POST", "/central/api/controles", {"qualquer": 1})[0], 400)

    def test_volume_chama_o_pipewire(self):
        chamadas = []
        controles = Controles(self.pasta / "c2.json", aplicar_volume=lambda v, m: chamadas.append((v, m)))
        controles.aplicar({"volume": 0.4})
        self.assertEqual(chamadas, [(0.4, False)])


if __name__ == "__main__":
    unittest.main()
