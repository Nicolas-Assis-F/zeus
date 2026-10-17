import os
import tempfile
import unittest
from pathlib import Path

from apoio import ProvedorFalso, config_de_teste
from zeus.base import Base, BaseRecusada, sem_colunas_internas
from zeus.canais import CanalMemoria
from zeus.ferramentas import Ferramentas
from zeus.llm import Resposta
from zeus.nucleo import Zeus
from zeus.persona import Persona
from zeus.store import Store

CATALOGO = """# Catálogo

## 5. Martelo e bit (importados)

| Item | Preço praticado | Revenda |
| --- | --- | --- |
| Martelo CIR110 | R$ 4.900 (APROVADO, 16/10/2026) | R$ 4.100 (SUGESTÃO) |

## 8. Custos internos

> **INTERNO, nunca enviar a cliente.**

- Custo do martelo CIR110: R$ 2.731,40

### 8.1 Detalhe

- Frete rateado do CIR110: R$ 312,00
"""

IMPORTACAO = """# Importação

## 3. Preços de venda

### 3.2 Tabela por item

| Item | Custo un. (INTERNO, estimativa) | Consumidor |
| --- | --- | --- |
| Martelo CIR110 | R$ 2.731,40 | R$ 4.900 |

### 4.3 Lote sugerido

- Custo por peça do martelo CIR110: R$ 2.500
"""

LEIA_ME = "# Base\n\nPreço vem do catalogo-e-precos.md.\n"


class Base_(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.temp.name) / "conhecimento"
        self.pasta.mkdir()
        (self.pasta / "catalogo-e-precos.md").write_text(CATALOGO, encoding="utf-8")
        (self.pasta / "importacao.md").write_text(IMPORTACAO, encoding="utf-8")
        (self.pasta / "LEIA-ME.md").write_text(LEIA_ME, encoding="utf-8")
        self.base = Base(str(self.pasta))

    def tearDown(self):
        self.temp.cleanup()

    def textos(self, resultado):
        return "\n".join(s["texto"] for s in resultado["secoes"])


class Leitura(Base_):
    def test_preco_vem_com_valor_e_fonte(self):
        resultado = self.base.consultar("martelo CIR110 preço")
        primeira = resultado["secoes"][0]
        self.assertEqual(primeira["arquivo"], "catalogo-e-precos.md")
        self.assertIn("5. Martelo e bit", primeira["secao"])
        self.assertIn("R$ 4.900 (APROVADO, 16/10/2026)", primeira["texto"])

    def test_item_sem_preco_nao_encontra(self):
        resultado = self.base.consultar("bomba submersa")
        self.assertFalse(resultado["encontrado"])
        saida = Ferramentas(Store(Path(self.temp.name) / "z"), base=self.base).executar(
            "consultar_base", {"busca": "bomba submersa"})
        self.assertIn("não tenho o preço", saida["instrucao"])

    def test_consulta_de_nicolas_traz_o_interno_marcado(self):
        resultado = self.base.consultar("custo martelo CIR110")
        internas = [s for s in resultado["secoes"] if s.get("interno")]
        self.assertTrue(internas)
        self.assertIn("R$ 2.731,40", self.textos(resultado))

    def test_orcamento_nao_traz_custo_interno(self):
        resultado = self.base.consultar("martelo CIR110 custo", finalidade="orcamento")
        texto = self.textos(resultado)
        self.assertIn("R$ 4.900", texto)
        for custo in ("2.731,40", "312,00", "2.500", "INTERNO"):
            self.assertNotIn(custo, texto)
        self.assertEqual({s["arquivo"] for s in resultado["secoes"]}, {"catalogo-e-precos.md"})

    def test_orcamento_recusa_arquivo_de_custo(self):
        with self.assertRaises(BaseRecusada):
            self.base.consultar("martelo", arquivo="importacao.md", finalidade="orcamento")

    def test_coluna_interna_sai_da_tabela(self):
        tabela = "| Item | Custo (INTERNO) | Preço |\n| --- | --- | --- |\n| A | 10 | 20 |"
        self.assertEqual(sem_colunas_internas(tabela),
                         "| Item | Preço |\n| --- | --- |\n| A | 20 |")

    def test_livro_interno_nao_e_custo(self):
        (self.pasta / "clientes.md").write_text(
            "# C\n\n### O livro interno: a conversa com o Pai\n\nParcelas do Ivomar.\n",
            encoding="utf-8")
        self.assertFalse(self.base.secoes("clientes.md")[0]["interno"])

    def test_indice_e_o_leia_me(self):
        self.assertIn("catalogo-e-precos.md", self.base.indice())


class Fronteira(Base_):
    def test_caminho_fora_da_pasta(self):
        for nome in ("../segredo.md", "/etc/passwd", "sub/arquivo.md", ".oculto.md", "notas.txt"):
            with self.assertRaises(BaseRecusada, msg=nome):
                self.base.consultar("martelo", arquivo=nome)

    def test_link_simbolico_e_recusado(self):
        fora = Path(self.temp.name) / "fora.md"
        fora.write_text("# Fora\n\n## Martelo\n\nconteúdo de terceiro", encoding="utf-8")
        os.symlink(fora, self.pasta / "atalho.md")
        with self.assertRaises(BaseRecusada):
            self.base.consultar("martelo", arquivo="atalho.md")
        self.assertNotIn("atalho.md", self.base.arquivos())
        self.assertNotIn("terceiro", self.textos(self.base.consultar("martelo")))

    def test_pasta_que_e_link_simbolico_fica_desligada(self):
        atalho = Path(self.temp.name) / "atalho"
        os.symlink(self.pasta, atalho)
        base = Base(str(atalho))
        self.assertFalse(base.disponivel())
        self.assertIn("link simbólico", base.diagnostico())

    def test_sem_base_e_erro_claro(self):
        saida = Ferramentas(Store(Path(self.temp.name) / "z"), base=Base("")).executar(
            "consultar_base", {"busca": "martelo"})
        self.assertIn("indisponível", saida["erro"])


class NaConversa(Base_):
    def zeus(self, roteiro):
        store = Store(Path(self.temp.name) / "zeus")
        self.addCleanup(store.close)
        provedor = ProvedorFalso(roteiro)
        ferramentas = Ferramentas(store, base=self.base)
        zeus = Zeus(store, provedor, Persona.carregar("config/persona.md"), ferramentas,
                    config_de_teste(), CanalMemoria())
        return zeus, provedor, store

    def test_consultar_a_base_nao_desliga_as_acoes(self):
        zeus, provedor, store = self.zeus([
            Resposta("", [{"id": "1", "nome": "consultar_base",
                           "argumentos": {"busca": "martelo CIR110"}}], "m"),
            Resposta("", [{"id": "2", "nome": "agendar_lembrete",
                           "argumentos": {"texto": "mandar preço do martelo", "quando": "+1h"}}], "m"),
            Resposta("R$ 4.900, aprovado em 16/10. Lembrete marcado.", [], "m"),
        ])
        zeus.conversar("quanto é o martelo? me lembra de mandar o preço daqui 1h", canal="cli")
        self.assertEqual(len(store.agenda_pendente()), 1)
        oferecidas = {f["function"]["name"] for f in provedor.catalogos[1] or []}
        self.assertIn("agendar_lembrete", oferecidas)

    def test_indice_entra_no_sistema(self):
        zeus, provedor, _ = self.zeus([Resposta("Oi.", [], "m")])
        zeus.conversar("oi", canal="cli")
        sistemas = [m["content"] for m in provedor.recebidas[0] if m["role"] == "system"]
        self.assertTrue(any("Preço vem do catalogo-e-precos.md" in s for s in sistemas))

    def test_limite_de_consultas_fecha_com_resposta(self):
        busca = {"id": "x", "nome": "consultar_base", "argumentos": {"busca": "bomba submersa"}}
        # #82: a segunda chamada idêntica já encerra as consultas (sem
        # informação nova), e a rodada final, sem ferramentas, responde.
        zeus, provedor, _ = self.zeus([Resposta("", [busca], "m")] * 2 +
                                      [Resposta("Não tenho o preço da bomba submersa.", [], "m")])
        resposta = zeus.conversar("quanto custa uma bomba submersa?", canal="cli")
        self.assertEqual(resposta, "Não tenho o preço da bomba submersa.")
        self.assertIsNone(provedor.catalogos[-1])
