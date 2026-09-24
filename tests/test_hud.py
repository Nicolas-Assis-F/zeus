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

    def pedir(self, caminho, dados=None, chave="chave-secreta", corpo_bruto=None,
              cabecalhos=None, com_resposta=False):
        # A chave vai por cabeçalho: pela URL ela não vale mais (ficava em
        # histórico, favorito e log).
        url = f"http://127.0.0.1:{self.porta}{caminho}"
        corpo = corpo_bruto if corpo_bruto is not None else (
            json.dumps(dados).encode("utf-8") if dados is not None else None)
        pedido = urllib.request.Request(url, data=corpo,
                                        method="POST" if corpo is not None else "GET")
        if chave is not None:
            pedido.add_header("X-Zeus-Chave", chave)
        for nome, valor in (cabecalhos or {}).items():
            pedido.add_header(nome, valor)
        try:
            with urllib.request.urlopen(pedido, timeout=5) as resposta:
                saida = (resposta.status, resposta.read())
                return saida + (resposta.headers,) if com_resposta else saida
        except urllib.error.HTTPError as erro:
            saida = (erro.code, erro.read())
            return saida + (erro.headers,) if com_resposta else saida

    def test_exige_chave_para_dado_e_nao_para_a_pagina(self):
        self.assertEqual(self.pedir("/", chave=None)[0], 200)
        self.assertEqual(self.pedir("/estado", chave="errada")[0], 401)
        self.assertEqual(self.pedir("/estado", chave=None)[0], 401)
        codigo, corpo = self.pedir("/estado")
        self.assertEqual(codigo, 200)
        self.assertEqual(json.loads(corpo)["modelo"], "modelo-falso")

    def test_saude_responde_medida_e_exige_a_mesma_chave(self):
        """O painel de saúde é dado: sem chave, ninguém mede o X99 de fora."""
        self.assertEqual(self.pedir("/saude", chave="errada")[0], 401)
        self.assertEqual(self.pedir("/saude", chave=None)[0], 401)
        codigo, corpo = self.pedir("/saude")
        self.assertEqual(codigo, 200)
        medida = json.loads(corpo)
        self.assertEqual(medida["tipo"], "saude")
        self.assertIn("percentual", medida["memoria"])
        self.assertEqual(len(medida["cpu"]["por_nucleo"]), medida["cpu"]["nucleos"])

    def test_mapa_serve_tela_e_exige_a_mesma_chave(self):
        """A tela vem pelo Zeus: o navegador nunca fala com o servidor público."""
        import tempfile
        from pathlib import Path as _Path
        from zeus.mapa import Mapa
        with tempfile.TemporaryDirectory() as pasta:
            self.hud.mapa = Mapa(destino=_Path(pasta),
                                 transporte=lambda url, timeout=None: b"\x89PNG-tela")
            self.assertEqual(self.pedir("/mapa/tela/13/2974/4481.png", chave="errada")[0], 401)
            codigo, corpo = self.pedir("/mapa/tela/13/2974/4481.png")
            self.assertEqual(codigo, 200)
            self.assertTrue(corpo.startswith(b"\x89PNG"))
            self.assertEqual(self.pedir("/mapa/tela/13/2974.png")[0], 404)
            self.assertEqual(self.pedir("/mapa/tela/13/9999999/1.png")[0], 502)
            codigo, corpo = self.pedir("/mapa")
            self.assertEqual(codigo, 200)
            self.assertTrue(json.loads(corpo)["ativo"])

    def test_sem_mapa_as_rotas_dizem_que_esta_desligado(self):
        self.assertEqual(self.pedir("/mapa")[0], 503)
        self.assertEqual(self.pedir("/mapa/tela/1/0/0.png")[0], 503)

    def test_a_pagina_nao_manda_imagem_da_camera_para_lugar_nenhum(self):
        """A promessa dos gestos é que o vídeo não sai do navegador.

        É uma promessa que só vale se ninguém, um dia, acrescentar um envio
        por engano. Este teste lê a página atrás disso."""
        from zeus.hud.servidor import PAGINA
        pagina = PAGINA.read_text(encoding="utf-8")
        for proibido in ("toBlob", "toDataURL", "canvas.toDataURL",
                         "MediaRecorder(TRILHA_DE_VIDEO", "/visao", "/camera"):
            self.assertNotIn(proibido, pagina, proibido)
        # O único envio de mídia que existe é o do áudio da escuta, que é
        # explícito, com botão próprio, e vai para a transcrição local.
        self.assertEqual(pagina.count('"/escuta"'), 1)

    def test_a_camera_comeca_desligada_e_avisa_enquanto_estiver_ligada(self):
        from zeus.hud.servidor import PAGINA
        pagina = PAGINA.read_text(encoding="utf-8")
        self.assertIn("let CAMERA = null", pagina)
        self.assertIn("luzDaCamera", pagina)
        # Aba escondida com a câmera ligada é o que ninguém quer ver.
        self.assertIn("document.hidden && CAMERA", pagina)

    def test_aceno_nao_finge_que_o_microfone_esta_ouvindo(self):
        """Defeito C5: o aceno punha o orbe em "ouvindo" sem captura nenhuma."""
        from zeus.hud.servidor import PAGINA
        pagina = PAGINA.read_text(encoding="utf-8")
        inicio = pagina.index("function aplicarGesto(")
        corpo = pagina[inicio:pagina.index("\n}\n", inicio)]
        self.assertNotIn('mudarEstado("ouvindo"', corpo)

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
            pedido = urllib.request.Request(f"http://127.0.0.1:{self.porta}/fluxo",
                                            headers={"X-Zeus-Chave": "chave-secreta"})
            with urllib.request.urlopen(pedido, timeout=8) as fluxo:
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


class Sessao(unittest.TestCase):
    """Achado S4: a chave viajava na URL, era impressa no log e não tinha
    limite de tentativas. Agora vira sessão por cookie, uma vez."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.arquivo = Path(self.temp.name) / "hud" / "sessoes.json"
        self.agora = [1_000_000.0]
        self.hud = self.novo()

    def novo(self, **extras):
        opcoes = dict(enfileirar=lambda _: None, chave="chave-secreta", host="127.0.0.1",
                      porta=0, estado=RETRATO, arquivo_de_sessoes=self.arquivo,
                      relogio=lambda: self.agora[0])
        opcoes.update(extras)
        hud = ServidorHUD(**opcoes)
        hud.porta_real = hud.iniciar()
        return hud

    def tearDown(self):
        self.hud.parar()
        self.temp.cleanup()

    def pedir(self, caminho, dados=None, biscoito=None, cabecalhos=None, hud=None):
        hud = hud or self.hud
        corpo = json.dumps(dados).encode() if dados is not None else None
        pedido = urllib.request.Request(f"http://127.0.0.1:{hud.porta_real}{caminho}", data=corpo,
                                        method="POST" if corpo is not None else "GET")
        if biscoito:
            pedido.add_header("Cookie", biscoito)
        for nome, valor in (cabecalhos or {}).items():
            pedido.add_header(nome, valor)
        try:
            with urllib.request.urlopen(pedido, timeout=5) as resposta:
                return resposta.status, json.loads(resposta.read() or b"{}"), resposta.headers
        except urllib.error.HTTPError as erro:
            return erro.code, json.loads(erro.read() or b"{}"), erro.headers

    def entrar(self, chave="chave-secreta", hud=None):
        codigo, _, cabecalhos = self.pedir("/sessao", {"chave": chave}, hud=hud)
        biscoito = (cabecalhos.get("Set-Cookie") or "").split(";")[0]
        return codigo, biscoito, cabecalhos.get("Set-Cookie") or ""

    def test_chave_na_url_nao_abre_mais_rota_de_dado(self):
        self.assertEqual(self.pedir("/estado?chave=chave-secreta")[0], 401)

    def test_chave_certa_vira_cookie_httponly_e_strict(self):
        codigo, biscoito, completo = self.entrar()
        self.assertEqual(codigo, 200)
        self.assertIn("HttpOnly", completo)
        self.assertIn("SameSite=Strict", completo)
        self.assertNotIn("chave-secreta", completo)
        self.assertEqual(self.pedir("/estado", biscoito=biscoito)[0], 200)
        self.assertTrue(self.pedir("/sessao", biscoito=biscoito)[1]["autenticado"])

    def test_sair_revoga_a_sessao(self):
        _, biscoito, _ = self.entrar()
        self.assertEqual(self.pedir("/sessao/sair", {}, biscoito=biscoito)[0], 200)
        self.assertEqual(self.pedir("/estado", biscoito=biscoito)[0], 401)

    def test_tentativas_erradas_tem_limite_mesmo_para_a_chave_certa(self):
        for _ in range(5):
            self.assertEqual(self.entrar("errada")[0], 401)
        codigo, _, _ = self.pedir("/sessao", {"chave": "chave-secreta"})[:3]
        self.assertEqual(codigo, 429)
        self.agora[0] += 61
        self.assertEqual(self.entrar()[0], 200)

    def test_mutacao_de_outra_origem_e_recusada(self):
        _, biscoito, _ = self.entrar()
        codigo = self.pedir("/mensagem", {"texto": "oi"}, biscoito=biscoito,
                            cabecalhos={"Origin": "https://outro.exemplo"})[0]
        self.assertEqual(codigo, 403)

    def test_sessao_sobrevive_ao_reinicio_e_o_arquivo_so_tem_hash(self):
        _, biscoito, _ = self.entrar()
        token = biscoito.split("=", 1)[1]
        self.hud.parar()
        self.hud = self.novo()
        self.assertEqual(self.pedir("/estado", biscoito=biscoito)[0], 200)
        conteudo = self.arquivo.read_text()
        self.assertNotIn(token, conteudo)
        self.assertEqual(oct(self.arquivo.stat().st_mode & 0o777), "0o600")
        self.agora[0] += 31 * 24 * 3600
        self.assertEqual(self.pedir("/estado", biscoito=biscoito)[0], 401)

    def test_codigo_de_pareamento_vale_uma_vez_e_expira(self):
        self.hud.parar()
        self.hud = self.novo(chave="", codigo_unico="codigo-de-teste")
        self.assertEqual(self.entrar("codigo-de-teste")[0], 200)
        self.assertEqual(self.entrar("codigo-de-teste")[0], 401)
        outro = self.novo(chave="", codigo_unico="outro-codigo")
        try:
            self.agora[0] += 16 * 60
            self.assertEqual(self.entrar("outro-codigo", hud=outro)[0], 401)
        finally:
            outro.parar()

    def test_a_chave_nao_vai_para_o_log_nem_para_o_navegador(self):
        from zeus.hud.servidor import PAGINA
        principal = (Path(__file__).resolve().parents[1] / "src/zeus/__main__.py").read_text()
        self.assertNotIn("?chave={chave}", principal)
        pagina = PAGINA.read_text(encoding="utf-8")
        self.assertNotIn('sessionStorage.setItem("zeus_chave"', pagina)
        self.assertNotIn("chave=\" + encodeURIComponent(CHAVE)", pagina)


class VozAusente(unittest.TestCase):
    def test_sem_piper_o_zeus_continua_escrevendo(self):
        voz = Voz(binario="piper-que-nao-existe")
        self.assertFalse(voz.disponivel())
        self.assertIn("não encontrado", voz.diagnostico())
        self.assertIsNone(voz.falar("qualquer coisa"))


if __name__ == "__main__":
    unittest.main()
