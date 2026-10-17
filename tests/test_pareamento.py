"""Pareamento do celular por QR (zeus.pareamento)."""

import json
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path

from qr_decodificar import decodificar
from zeus import pareamento as p
from zeus.pareamento import ErroDePareamento, Pareamento

BASE = "https://192.168.100.221:8770"
DIA = 86400


class Relogio:
    def __init__(self):
        self.agora = 1_800_000_000.0

    def __call__(self):
        return self.agora


def matriz_do_svg(svg):
    """Reconstrói a matriz a partir do <path> (borda padrão de 4 módulos)."""
    lado = int(re.search(r'viewBox="0 0 (\d+) ', svg).group(1)) - 8
    matriz = [[False] * lado for _ in range(lado)]
    for x, y, largura in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\d+z", svg):
        for dx in range(int(largura)):
            matriz[int(y) - 4][int(x) - 4 + dx] = True
    return matriz


class BasePareamento(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.arquivo = self.pasta / "estado" / "pareamento.json"
        self.relogio = Relogio()
        self.revogados = []
        self.par = Pareamento(self.arquivo, relogio=self.relogio,
                              ao_revogar=self.revogados.append)

    def nonce(self, inicio):
        return inicio["url"].split("#n=", 1)[1]

    def parear(self, nome="Pixel do Nicolas", ip="192.168.100.50"):
        inicio = self.par.iniciar(BASE)
        pedido = self.par.reivindicar(self.nonce(inicio), nome, ip)
        return inicio, pedido, self.par.aprovar(pedido["reivindicacao_id"], True)


class TestFluxo(BasePareamento):
    def test_fluxo_feliz(self):
        inicio = self.par.iniciar(BASE + "/")
        self.assertEqual(set(inicio), {"id", "url", "qr_svg", "codigo_manual", "expira_em"})
        self.assertRegex(inicio["url"], r"^https://192\.168\.100\.221:8770/parear#n=[\w-]{22}$")
        self.assertRegex(inicio["codigo_manual"], r"^\d{8}$")
        self.assertEqual(inicio["expira_em"], self.relogio.agora + 120)
        self.assertEqual(self.par.situacao()["estado"], "ativa")

        pedido = self.par.reivindicar(self.nonce(inicio), "Pixel do Nicolas", "192.168.100.50")
        self.assertRegex(pedido["codigo_conferencia"], r"^\d{4}$")
        # O celular chega aos mesmos 4 dígitos com o que escaneou.
        self.assertEqual(pedido["codigo_conferencia"],
                         p.codigo_de_conferencia(self.nonce(inicio), pedido["reivindicacao_id"]))
        situacao = self.par.situacao()
        self.assertEqual(situacao["estado"], "aguardando_aprovacao")
        self.assertEqual(situacao["codigo_conferencia"], pedido["codigo_conferencia"])
        self.assertEqual(situacao["nome_aparelho"], "Pixel do Nicolas")

        aprovado = self.par.aprovar(pedido["reivindicacao_id"], True)
        self.assertTrue(aprovado["aprovado"])
        self.assertGreaterEqual(len(aprovado["token"]), 43)
        self.assertEqual(aprovado["max_age"], 30 * DIA)
        self.assertIn(aprovado["token"], aprovado["set_cookie"])
        self.assertIsNone(self.par.situacao())

        aparelho = self.par.validar(aprovado["token"])
        self.assertEqual(aparelho["nome"], "Pixel do Nicolas")
        self.assertEqual(aparelho["escopo"], "celular")
        self.assertEqual(aparelho["ip"], "192.168.100.50")
        self.assertNotIn("token_sha256", aparelho)
        self.assertIsNone(self.par.validar("outro" + aprovado["token"]))
        self.assertIsNone(self.par.validar(""))

    def test_codigo_manual_tambem_pareia(self):
        inicio = self.par.iniciar(BASE)
        pedido = self.par.reivindicar(inicio["codigo_manual"], "iPhone", "192.168.100.51")
        self.assertEqual(pedido["codigo_conferencia"],
                         p.codigo_de_conferencia(inicio["codigo_manual"], pedido["reivindicacao_id"]))
        self.assertTrue(self.par.aprovar(pedido["reivindicacao_id"], True)["aprovado"])

    def test_qr_contem_a_url_com_fragmento(self):
        inicio = self.par.iniciar(BASE)
        self.assertEqual(decodificar(matriz_do_svg(inicio["qr_svg"])), inicio["url"])
        self.assertIn("#n=", inicio["url"])

    def test_expira_em_120_s(self):
        inicio = self.par.iniciar(BASE)
        self.relogio.agora += 121
        self.assertEqual(self.par.situacao()["estado"], "expirada")
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.reivindicar(self.nonce(inicio), "x", "10.0.0.1")
        self.assertEqual(erro.exception.motivo, "expirado")

    def test_vale_ate_o_ultimo_segundo(self):
        inicio = self.par.iniciar(BASE)
        self.relogio.agora += 120
        self.par.reivindicar(self.nonce(inicio), "x", "10.0.0.1")

    def test_uso_unico(self):
        inicio = self.par.iniciar(BASE)
        self.par.reivindicar(self.nonce(inicio), "a", "10.0.0.1")
        for segredo in (self.nonce(inicio), inicio["codigo_manual"]):
            with self.assertRaises(ErroDePareamento) as erro:
                self.par.reivindicar(segredo, "b", "10.0.0.2")
            self.assertEqual(erro.exception.motivo, "usado")

    def test_segunda_tentativa_invalida_a_primeira(self):
        primeira = self.par.iniciar(BASE)
        segunda = self.par.iniciar(BASE)
        self.assertNotEqual(primeira["url"], segunda["url"])
        for segredo in (self.nonce(primeira), primeira["codigo_manual"]):
            with self.assertRaises(ErroDePareamento) as erro:
                self.par.reivindicar(segredo, "a", "10.0.0.1")
            self.assertEqual(erro.exception.motivo, "invalido")
        self.par.reivindicar(self.nonce(segunda), "a", "10.0.0.1")

    def test_iniciar_de_novo_derruba_pedido_pendente(self):
        inicio = self.par.iniciar(BASE)
        pedido = self.par.reivindicar(self.nonce(inicio), "a", "10.0.0.1")
        self.par.iniciar(BASE)
        with self.assertRaises(ErroDePareamento):
            self.par.aprovar(pedido["reivindicacao_id"], True)

    def test_sem_tentativa(self):
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.reivindicar("12345678", "a", "10.0.0.1")
        self.assertEqual(erro.exception.motivo, "sem_tentativa")

    def test_limite_por_ip(self):
        self.par.iniciar(BASE)
        for _ in range(5):
            with self.assertRaises(ErroDePareamento) as erro:
                self.par.reivindicar("nonce-errado-qualquer", "a", "10.0.0.9")
            self.assertEqual(erro.exception.motivo, "invalido")
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.reivindicar("nonce-errado-qualquer", "a", "10.0.0.9")
        self.assertEqual(erro.exception.motivo, "limite")
        # Outro IP não é afetado, e o mesmo IP volta depois de um minuto.
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.reivindicar("nonce-errado-qualquer", "a", "10.0.0.10")
        self.assertEqual(erro.exception.motivo, "invalido")
        self.relogio.agora += 61
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.reivindicar("nonce-errado-qualquer", "a", "10.0.0.9")
        self.assertEqual(erro.exception.motivo, "invalido")

    def test_limite_vale_ate_para_o_segredo_certo(self):
        inicio = self.par.iniciar(BASE)
        for _ in range(5):
            with self.assertRaises(ErroDePareamento):
                self.par.reivindicar("errado", "a", "10.0.0.9")
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.reivindicar(self.nonce(inicio), "a", "10.0.0.9")
        self.assertEqual(erro.exception.motivo, "limite")

    def test_codigo_manual_bloqueia_apos_5_erros(self):
        inicio = self.par.iniciar(BASE)
        certo = inicio["codigo_manual"]
        errado = f"{(int(certo) + 1) % 10 ** 8:08d}"
        for i in range(5):
            with self.assertRaises(ErroDePareamento) as erro:
                self.par.reivindicar(errado, "a", f"10.0.1.{i}")  # IPs diferentes
            self.assertEqual(erro.exception.motivo, "invalido")
        self.assertTrue(self.par.situacao()["codigo_bloqueado"])
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.reivindicar(certo, "a", "10.0.2.1")
        self.assertEqual(erro.exception.motivo, "bloqueado")
        # O QR continua valendo: só o código digitável ficou bloqueado.
        self.par.reivindicar(self.nonce(inicio), "a", "10.0.2.1")

    def test_reivindicacao_negada_nao_gera_token(self):
        inicio = self.par.iniciar(BASE)
        pedido = self.par.reivindicar(self.nonce(inicio), "intruso", "10.0.0.66")
        self.assertEqual(self.par.aprovar(pedido["reivindicacao_id"], False), {"aprovado": False})
        self.assertEqual(self.par.aparelhos(), [])
        with self.assertRaises(ErroDePareamento):
            self.par.aprovar(pedido["reivindicacao_id"], True)
        self.assertNotIn("token", self.arquivo.read_text())

    def test_pedido_sem_aprovacao_nao_gera_token_e_expira(self):
        inicio = self.par.iniciar(BASE)
        pedido = self.par.reivindicar(self.nonce(inicio), "a", "10.0.0.1")
        self.assertEqual(self.par.aparelhos(), [])
        self.relogio.agora += 121
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.aprovar(pedido["reivindicacao_id"], True)
        self.assertEqual(erro.exception.motivo, "expirado")
        self.assertEqual(self.par.aparelhos(), [])

    def test_aprovar_id_errado(self):
        inicio = self.par.iniciar(BASE)
        self.par.reivindicar(self.nonce(inicio), "a", "10.0.0.1")
        with self.assertRaises(ErroDePareamento) as erro:
            self.par.aprovar("0000000000000000", True)
        self.assertEqual(erro.exception.motivo, "reivindicacao_desconhecida")


class TestSegredosNoDisco(BasePareamento):
    def test_nada_em_claro_no_arquivo_e_permissao_0600(self):
        inicio, pedido, aprovado = self.parear()
        texto = self.arquivo.read_text()
        for segredo in (self.nonce(inicio), inicio["codigo_manual"], aprovado["token"]):
            self.assertNotIn(segredo, texto)
        dados = json.loads(texto)
        self.assertEqual(len(dados["aparelhos"]), 1)
        self.assertRegex(dados["aparelhos"][0]["token_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(stat.S_IMODE(os.stat(self.arquivo).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.arquivo.parent).st_mode), 0o700)
        self.assertEqual([f for f in os.listdir(self.arquivo.parent) if f.endswith(".tmp")], [])

    def test_hash_da_tentativa_no_arquivo(self):
        inicio = self.par.iniciar(BASE)
        texto = self.arquivo.read_text()
        self.assertNotIn(self.nonce(inicio), texto)
        self.assertNotIn(inicio["codigo_manual"], texto)
        self.assertEqual(stat.S_IMODE(os.stat(self.arquivo).st_mode), 0o600)

    def test_token_aparece_uma_vez_so(self):
        _, _, aprovado = self.parear()
        for aparelho in self.par.aparelhos():
            self.assertNotIn("token", aparelho)
            self.assertNotIn("token_sha256", aparelho)
        self.assertNotIn(aprovado["token"], repr(self.par.validar(aprovado["token"])))
        self.assertNotIn(aprovado["token"], repr(self.par.situacao()))

    def test_estado_sobrevive_a_reinicio(self):
        _, _, aprovado = self.parear()
        outro = Pareamento(self.arquivo, relogio=self.relogio)
        self.assertIsNotNone(outro.validar(aprovado["token"]))

    def test_arquivo_corrompido_vira_estado_vazio(self):
        self.arquivo.parent.mkdir(parents=True)
        self.arquivo.write_text("{lixo")
        self.assertEqual(self.par.aparelhos(), [])
        self.assertIsNone(self.par.validar("qualquer"))


class TestValidade(BasePareamento):
    def test_validade_deslizante_de_30_dias(self):
        _, _, aprovado = self.parear()
        token = aprovado["token"]
        self.relogio.agora += 29 * DIA
        self.assertIsNotNone(self.par.validar(token))   # renova até +30 a partir daqui
        self.relogio.agora += 29 * DIA
        self.assertIsNotNone(self.par.validar(token))
        self.relogio.agora += 30 * DIA + 1               # 30 dias parado
        self.assertIsNone(self.par.validar(token))
        self.assertEqual(self.par.aparelhos(), [])

    def test_sem_uso_expira_em_30_dias(self):
        _, _, aprovado = self.parear()
        self.relogio.agora += 30 * DIA + 1
        self.assertIsNone(self.par.validar(aprovado["token"]))

    def test_teto_de_90_dias_mesmo_com_uso(self):
        _, _, aprovado = self.parear()
        token = aprovado["token"]
        criado = self.relogio.agora
        for _ in range(17):  # usa a cada 5 dias até 85 dias
            self.relogio.agora += 5 * DIA
            aparelho = self.par.validar(token)
            self.assertIsNotNone(aparelho)
            self.assertLessEqual(aparelho["expira_em"], criado + 90 * DIA)
        self.assertEqual(aparelho["expira_em"], criado + 90 * DIA)
        self.relogio.agora = criado + 90 * DIA
        self.assertIsNotNone(self.par.validar(token))
        self.relogio.agora = criado + 90 * DIA + 1
        self.assertIsNone(self.par.validar(token))

    def test_uso_frequente_nao_grava_a_cada_requisicao(self):
        _, _, aprovado = self.parear()
        antes = self.arquivo.stat().st_mtime_ns
        self.relogio.agora += 5
        self.par.validar(aprovado["token"], ip="192.168.100.50")
        self.assertEqual(self.arquivo.stat().st_mtime_ns, antes)


class TestRevogacao(BasePareamento):
    def test_revogar_um(self):
        _, _, primeiro = self.parear("Pixel")
        _, _, segundo = self.parear("Tablet", ip="192.168.100.60")
        self.assertTrue(self.par.revogar(primeiro["aparelho_id"]))
        self.assertEqual(self.revogados, [primeiro["aparelho_id"]])
        self.assertIsNone(self.par.validar(primeiro["token"]))
        self.assertIsNotNone(self.par.validar(segundo["token"]))
        self.assertFalse(self.par.revogar(primeiro["aparelho_id"]))
        self.assertEqual(len(self.revogados), 1)

    def test_revogar_todos(self):
        _, _, primeiro = self.parear("Pixel")
        _, _, segundo = self.parear("Tablet", ip="192.168.100.60")
        self.assertEqual(self.par.revogar_todos(), 2)
        self.assertEqual(sorted(self.revogados),
                         sorted([primeiro["aparelho_id"], segundo["aparelho_id"]]))
        self.assertIsNone(self.par.validar(primeiro["token"]))
        self.assertIsNone(self.par.validar(segundo["token"]))
        self.assertEqual(self.par.aparelhos(), [])

    def test_callback_com_erro_nao_impede_revogacao(self):
        _, _, aprovado = self.parear()

        def explode(_):
            raise RuntimeError("SSE já caiu")

        self.par.ao_revogar = explode
        self.assertTrue(self.par.revogar(aprovado["aparelho_id"]))
        self.assertIsNone(self.par.validar(aprovado["token"]))


class TestCookie(unittest.TestCase):
    def test_cabecalho_cookie(self):
        valor = p.cabecalho_cookie("abc-_DEF123", 2592000)
        self.assertTrue(valor.startswith("zeus_aparelho=abc-_DEF123; "))
        for atributo in ("Path=/", "Max-Age=2592000", "HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(atributo, valor.split("; "))

    def test_cookie_de_apagar(self):
        self.assertIn("Max-Age=0", p.cabecalho_cookie("", 0))

    def test_token_estranho_recusado(self):
        for ruim in ("a;b", "a b", "a\r\nSet-Cookie: x=1", "ação"):
            with self.assertRaises(ValueError):
                p.cabecalho_cookie(ruim, 10)

    def test_token_do_cookie(self):
        self.assertEqual(p.token_do_cookie("a=1; zeus_aparelho=XYZ; b=2"), "XYZ")
        self.assertEqual(p.token_do_cookie("zeus_aparelhox=1"), "")
        self.assertEqual(p.token_do_cookie(None), "")


class TestOrigemEHost(unittest.TestCase):
    PERMITIDOS = p.hosts_padrao("192.168.100.221", 8770)

    def test_host(self):
        for bom in ("192.168.100.221:8770", "LOCALHOST:8770", "zeus:8770", "127.0.0.1:8770"):
            self.assertTrue(p.host_permitido(bom, self.PERMITIDOS), bom)
        for ruim in ("", None, "192.168.100.221", "192.168.100.221:8771", "evil.com:8770",
                     "192.168.100.221:8770@evil.com", "evil.com/192.168.100.221:8770",
                     "192.168.100.221:87a0", "zeus:8770 extra"):
            self.assertFalse(p.host_permitido(ruim, self.PERMITIDOS), ruim)

    def test_host_ipv6_e_porta_padrao(self):
        self.assertTrue(p.host_permitido("[::1]:8770", {"[::1]:8770"}))
        self.assertFalse(p.host_permitido("[::1:8770", {"[::1]:8770"}))
        self.assertTrue(p.host_permitido("zeus.local:443", {"zeus.local"}))
        self.assertTrue(p.host_permitido("zeus.local.", {"zeus.local"}))

    def test_origem(self):
        self.assertTrue(p.origem_permitida("https://192.168.100.221:8770", self.PERMITIDOS))
        self.assertTrue(p.origem_permitida("https://zeus:8770", self.PERMITIDOS))
        self.assertTrue(p.origem_permitida("http://localhost:8770", self.PERMITIDOS))
        for ruim in ("", None, "null", "https://evil.com", "https://192.168.100.221:8771",
                     "http://192.168.100.221:8770", "ftp://zeus:8770",
                     "https://192.168.100.221:8770/caminho", "https://x@zeus:8770",
                     "https://192.168.100.221:porta", "https://192.168.100.221.evil.com:8770"):
            self.assertFalse(p.origem_permitida(ruim, self.PERMITIDOS), ruim)


if __name__ == "__main__":
    unittest.main()
