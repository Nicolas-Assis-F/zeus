import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apoio import ProvedorFalso, config_de_teste
from zeus.canais import CanalMemoria, CanalWhatsApp
from zeus.ferramentas import Ferramentas
from zeus.llm import Resposta
from zeus.nucleo import Zeus
from zeus.orcamento import (OrcamentoRecusado, Orcamentos, brl, desenhar, largura,
                            nome_do_arquivo, quebrar)
from zeus.persona import Persona
from zeus.store import Store

PRECOS = {"itens": [
    {"sku": "LE-CAB80", "rotulo": "Cabeçote hidráulico 80 m",
     "descricao": "Cabeçote (caixa redutora) para perfuração de poços artesianos.",
     "preco_centavos": 1050000, "status": "APROVADO", "data": "06/10/2026", "origem": "Brasil",
     "fonte": "catalogo-e-precos.md, praticado"},
    {"sku": "LE-HASTE-238-3M", "rotulo": "Haste 2 3/8″ × 3 m", "descricao": "Haste.",
     "preco_centavos": 78000, "status": "APROVADO", "data": "06/10/2026", "origem": "Brasil",
     "fonte": "catalogo-e-precos.md, praticado"},
    {"sku": "LE-CIR110-B", "rotulo": "Bit 110 mm", "descricao": "", "preco_centavos": 0,
     "status": "INCERTO", "origem": "China"},
]}
CLIENTE = {"nome": "Ítalo Poços", "razao_social": "Cliente Teste", "doc": "12.345.678/0001-90",
           "ie": "123", "endereco": "Av. Exemplo, 100", "cidade": "Água Branca", "uf": "PI",
           "cep": "64460-000"}
PEDIDO = {"cliente": CLIENTE, "ref_cliente": "Italo P",
          "itens": [{"sku": "LE-CAB80"}, {"sku": "le-haste-238-3m", "quantidade": 10}],
          "pagamento_extenso": "entrada e o restante na entrega do material",
          "termos_pagamento": "Entrada + restante na entrega"}
INICIO = datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)


class Relogio:
    def __init__(self):
        self.agora = INICIO

    def __call__(self):
        return self.agora


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        raiz = Path(self.temp.name)
        self.pasta = raiz / "orcamentos"
        self.pasta.mkdir()
        self.precos = raiz / "precos.json"
        self.precos.write_text(json.dumps(PRECOS), encoding="utf-8")
        self.relogio = Relogio()
        self.orcamentos = Orcamentos(str(self.pasta), str(self.precos), self.relogio)

    def tearDown(self):
        self.temp.cleanup()

    def depois(self, segundos=60):
        self.relogio.agora += timedelta(seconds=segundos)
        return self.relogio.agora


class Formato(unittest.TestCase):
    def test_dinheiro_no_formato_do_modelo(self):
        self.assertEqual([brl(0), brl(65000), brl(1000000), brl(100000000)],
                         ["0,00", "650,00", "10 000,00", "1 000 000,00"])

    def test_largura_da_helvetica(self):
        # No modelo, "Pedido SO2609-0004" em Helvetica-Bold 17 vai de x = 386,03
        # a 553,28 (pdftotext -bbox): 167,246 pt.
        self.assertAlmostEqual(largura("Pedido SO2609-0004", "F2", 17), 167.246, places=2)

    def test_quebra_respeita_a_largura(self):
        for linha in quebrar("palavra " * 80, "F1", 8.3, 318):
            self.assertLessEqual(largura(linha, "F1", 8.3), 318)

    def test_nome_do_arquivo_so_com_a_referencia(self):
        self.assertEqual(nome_do_arquivo("Ítalo P./../x"), "ItaloPx")


class Preparo(Base):
    def test_preco_vem_do_catalogo_e_resumo_mostra_a_fonte(self):
        resumo = self.orcamentos.preparar(PEDIDO)
        self.assertEqual(resumo["numero"], "ZT2610-0001")
        texto = resumo["resumo"]
        self.assertIn("1 × LE-CAB80 Cabeçote hidráulico 80 m", texto)
        self.assertIn("R$ 10.500,00 cada (catalogo-e-precos.md, praticado, 06/10/2026)", texto)
        self.assertIn("10 × LE-HASTE-238-3M", texto)
        self.assertIn("Total: R$ 18.300,00 (ICMS 0%)", texto)
        self.assertIn("Código: ZC2610-00001", texto)

    def test_preco_inventado_nao_passa(self):
        pedido = dict(PEDIDO, itens=[{"sku": "LE-CAB80", "preco_centavos": 1}])
        rascunho = self.orcamentos.preparar(pedido)
        self.assertIn("R$ 10.500,00", rascunho["resumo"])

    def test_item_incerto_ou_desconhecido_e_recusado(self):
        for sku in ("LE-CIR110-B", "BOMBA-X"):
            with self.assertRaises(OrcamentoRecusado, msg=sku) as erro:
                self.orcamentos.preparar(dict(PEDIDO, itens=[{"sku": sku}]))
            self.assertIn("não tem preço aprovado", str(erro.exception))

    def test_valor_informado_por_nicolas_fica_marcado(self):
        pedido = dict(PEDIDO, itens=[{"sku": "LE-PISTAO", "rotulo": "Pistão",
                                      "preco_informado_centavos": 320000}])
        texto = self.orcamentos.preparar(pedido)["resumo"]
        self.assertIn("R$ 3.200,00 cada (valor que você informou)", texto)

    def test_cliente_incompleto_vira_aviso_e_sem_nome_recusa(self):
        # Snapshot de produção (#82): orçamento preliminar só com o nome; o
        # que falta sai como aviso no resumo, em vez de bloquear.
        resumo = self.orcamentos.preparar(dict(PEDIDO, cliente={"nome": "Ítalo"}))["resumo"]
        self.assertIn("Cadastro incompleto", resumo)
        self.assertIn("CPF ou CNPJ", resumo)
        with self.assertRaises(OrcamentoRecusado) as erro:
            self.orcamentos.preparar(dict(PEDIDO, cliente={"razao_social": "X"}))
        self.assertIn("nome do cliente", str(erro.exception))

    def test_codigo_oficial_inventado_vira_teste(self):
        texto = self.orcamentos.preparar(dict(PEDIDO, codigo_cliente="CU-qualquer"))["resumo"]
        self.assertIn("Código: ZC2610-", texto)
        texto = self.orcamentos.preparar(dict(PEDIDO, codigo_cliente="CU2609-00004"))["resumo"]
        self.assertIn("Código: CU2609-00004", texto)

    def test_numero_nao_volta_e_e_mensal(self):
        self.assertEqual(self.orcamentos.preparar(PEDIDO)["numero"], "ZT2610-0001")
        self.assertEqual(self.orcamentos.preparar(PEDIDO)["numero"], "ZT2610-0002")
        self.relogio.agora = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        self.assertEqual(self.orcamentos.preparar(PEDIDO)["numero"], "ZT2611-0001")


class Geracao(Base):
    def test_mesma_resposta_nao_gera(self):
        numero = self.orcamentos.preparar(PEDIDO)["numero"]
        with self.assertRaises(OrcamentoRecusado) as erro:
            self.orcamentos.gerar(numero, self.relogio(), "ok")
        self.assertIn("mensagem nova", str(erro.exception))

    def test_mensagem_que_nao_confirma_nao_gera(self):
        numero = self.orcamentos.preparar(PEDIDO)["numero"]
        with self.assertRaises(OrcamentoRecusado):
            self.orcamentos.gerar(numero, self.depois(), "e o frete, quanto fica?")

    def test_confirmado_gera_pdf_e_registro_fora_do_git(self):
        numero = self.orcamentos.preparar(PEDIDO)["numero"]
        gerado = self.orcamentos.gerar(numero, self.depois(), "pode gerar")
        pdf = Path(gerado["arquivo"])
        self.assertEqual(pdf.name, "Orcamento_ZT2610-0001_ItaloP.pdf")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF-1.4"))
        self.assertEqual(pdf.stat().st_mode & 0o777, 0o600)
        registro = json.loads((self.pasta / f"{numero}.json").read_text(encoding="utf-8"))
        self.assertTrue(registro["gerado"])
        with self.assertRaises(OrcamentoRecusado):
            self.orcamentos.gerar(numero, self.depois(), "gera de novo")

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext não instalado")
    def test_pdf_tem_as_linhas_do_modelo(self):
        numero = self.orcamentos.preparar(PEDIDO)["numero"]
        pdf = self.orcamentos.gerar(numero, self.depois(), "ok")["arquivo"]
        texto = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True,
                               text=True, check=True).stdout
        for esperado in ("Pedido ZT2610-0001", "Ref. Cliente : Italo P", "Data Pedido : 16/10/2026",
                         "Pagamento: entrada e o restante na entrega do material.",
                         "Valores Apresentados em Brazil Real", "LE-CAB80 - Cabeçote hidráulico 80 m",
                         "10 500,00", "7 800,00", "18 300,00", "(País de Origem: Brasil)",
                         'Haste 2 3/8" × 3 m', "Termos de pagamento:", "A combinar",
                         "Telefone: (62) 98601-8386", "Capital de 100 000 R$", "1/1"):
            self.assertIn(esperado, texto)
        self.assertNotIn("69286018386", texto)

    def test_muitos_itens_abrem_outra_pagina(self):
        pedido = dict(PEDIDO, itens=[{"sku": "LE-CAB80"}] * 12)
        numero = self.orcamentos.preparar(pedido)["numero"]
        pdf = Path(self.orcamentos.gerar(numero, self.depois(), "ok")["arquivo"]).read_bytes()
        self.assertIn(b"/Count 2", pdf)
        self.assertIn(b"(2 / 2)", pdf)


class NoGrupo(Base):
    def test_arquivo_vai_sempre_para_o_grupo(self):
        chamadas = []

        def transporte(url, corpo, timeout=30):
            chamadas.append(corpo)
            return 200, {"success": True, "message": "ok"}

        canal = CanalWhatsApp("http://127.0.0.1:8081", str(Path(self.temp.name) / "x.db"),
                              "120363000000000001@g.us", ["111"], None, transporte)
        canal.enviar_arquivo("/tmp/a.pdf", "pronto")
        self.assertEqual(chamadas[0]["recipient"], "120363000000000001@g.us")
        self.assertEqual(chamadas[0]["media_path"], "/tmp/a.pdf")

    def conversa(self, roteiro, enviados):
        store = Store(Path(self.temp.name) / "zeus")
        self.addCleanup(store.close)
        ferramentas = Ferramentas(store, orcamentos=self.orcamentos,
                                  enviar_arquivo=lambda c, l: enviados.append((c, l)))
        provedor = ProvedorFalso(roteiro)
        zeus = Zeus(store, provedor, Persona.carregar("config/persona.md"), ferramentas,
                    config_de_teste(), CanalMemoria(), self.relogio)
        return zeus

    def test_preparar_e_gerar_na_mesma_resposta_e_recusado(self):
        enviados = []
        zeus = self.conversa([
            Resposta("", [{"id": "1", "nome": "preparar_orcamento", "argumentos": PEDIDO}], "m"),
            Resposta("", [{"id": "2", "nome": "gerar_orcamento",
                           "argumentos": {"numero": "ZT2610-0001"}}], "m"),
            Resposta("Resumo acima; posso gerar?", [], "m"),
        ], enviados)
        zeus.conversar("orçamento pro Ítalo de um cabeçote 80, gera direto", canal="whatsapp")
        self.assertEqual(enviados, [])

    def test_confirmacao_numa_mensagem_nova_gera_e_manda_no_grupo(self):
        enviados = []
        zeus = self.conversa([
            Resposta("", [{"id": "1", "nome": "preparar_orcamento", "argumentos": PEDIDO}], "m"),
            Resposta("Resumo acima; posso gerar?", [], "m"),
            Resposta("", [{"id": "2", "nome": "gerar_orcamento",
                           "argumentos": {"numero": "ZT2610-0001"}}], "m"),
            Resposta("Mandei no grupo.", [], "m"),
        ], enviados)
        zeus.conversar("orçamento pro Ítalo de um cabeçote 80", canal="whatsapp")
        self.depois()
        zeus.conversar("confirmo, pode gerar", canal="whatsapp")
        self.assertEqual(len(enviados), 1)
        self.assertTrue(enviados[0][0].endswith("Orcamento_ZT2610-0001_ItaloP.pdf"))
        self.assertIn("Só vai pro cliente se você mandar", enviados[0][1])

    def test_desenho_sem_logo_ainda_e_pdf(self):
        o = json.loads(json.dumps(self.orcamentos.preparar(PEDIDO)))
        rascunho = json.loads((self.pasta / "rascunhos" / f"{o['numero']}.json").read_text())
        self.assertTrue(desenhar(rascunho).startswith(b"%PDF"))
