"""Avaliação cega de persona: o que a máquina garante sem modelo real.

O modelo aqui é um dublê que ecoa uma marca da persona, para as variantes
saírem distinguíveis e os testes poderem provar quatro coisas: as variantes de
fato mudam a saída, a folha entregue ao juiz não liga rótulo a variante, a
ordem é embaralhada, e a revelação agrega certo por variante. O que o dublê não
prova — a qualidade do tom — é justamente o que exige a rodada real no X99.
"""

import tempfile
import unittest
from pathlib import Path

from apoio import config_de_teste
from zeus.llm import Resposta
from zeus.persona_cega import (AvaliacaoCegaDePersona, folha_cega, gravar_historico,
                               revelar, versao_da_persona)

JORNADAS = {"jornadas": [
    {"id": "apresentacao", "titulo": "Quem é você",
     "dimensoes": ["companhia"], "turnos": ["quem é você?", "e se eu sumir?"]},
    {"id": "correcao", "titulo": "Ser corrigido",
     "dimensoes": ["lealdade"], "turnos": ["você errou o horário"]},
]}


class ModeloEco:
    """Ecoa uma marca tirada da persona: variantes diferentes, saídas diferentes."""

    modelo = "eco"

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0):
        persona = (mensagens[0]["content"] if mensagens else "").upper()
        marca = ("SERIO" if "SERIO" in persona else
                 "BRINCALHAO" if "BRINCALHAO" in persona else "NEUTRO")
        ultima = next((m["content"] for m in reversed(mensagens)
                       if m.get("role") == "user"), "")
        return Resposta(f"[{marca}] sobre '{ultima[:20]}'", [], self.modelo)

    def mensagem_do_assistente(self, resposta):
        return {"role": "assistant", "content": resposta.texto}

    def mensagem_de_ferramenta(self, chamada, conteudo):
        return {"role": "tool", "name": chamada["nome"], "content": conteudo}


def escrever_personas(pasta):
    seria = Path(pasta) / "persona_seria.md"
    viva = Path(pasta) / "persona_viva.md"
    seria.write_text("Você é o Zeus. Tom SERIO e contido.\n", encoding="utf-8")
    viva.write_text("Você é o Zeus. Tom BRINCALHAO e leve.\n", encoding="utf-8")
    return str(seria), str(viva)


def sem_embaralhar(itens):
    """Dublê de embaralhamento: mantém a ordem, para o teste ser determinístico."""
    return None


class MaquinaCega(unittest.TestCase):
    def gerar(self, temp, embaralhar=sem_embaralhar):
        seria, viva = escrever_personas(temp)
        aval = AvaliacaoCegaDePersona(
            config_de_teste(), Path(temp) / "estado", [seria, viva],
            provedor=ModeloEco(), origem="simulada", embaralhar=embaralhar)
        return aval.gerar(JORNADAS), seria, viva

    def test_variantes_produzem_respostas_diferentes(self):
        with tempfile.TemporaryDirectory() as temp:
            rodada, _, _ = self.gerar(temp)
            textos = [f["zeus"] for r in rodada["itens"][0]["respostas"]
                      for f in r["falas"]]
            self.assertTrue(any("SERIO" in t for t in textos))
            self.assertTrue(any("BRINCALHAO" in t for t in textos))

    def test_folha_cega_nao_liga_rotulo_a_variante(self):
        with tempfile.TemporaryDirectory() as temp:
            rodada, _, _ = self.gerar(temp)
            folha = folha_cega(rodada)
            texto = repr(folha)
            self.assertNotIn("_gabarito", texto)
            self.assertNotIn("persona_seria", texto)
            self.assertNotIn("persona_viva", texto)
            for item in folha["itens"]:
                for resposta in item["respostas"]:
                    self.assertEqual(set(resposta.keys()), {"rotulo", "falas"})

    def test_ordem_e_embaralhada_por_jornada(self):
        with tempfile.TemporaryDirectory() as temp:
            # Embaralhador que inverte a ordem das variantes fornecidas.
            rodada, seria, viva = self.gerar(temp,
                                             embaralhar=lambda itens: itens.reverse())
            primeiro = rodada["itens"][0]
            rotulos = [r["rotulo"] for r in primeiro["respostas"]]
            self.assertEqual(rotulos, ["A", "B"])
            # Como a ordem foi invertida, o rótulo A ficou com a segunda variante
            # (viva), não a primeira (séria): a posição não denuncia a variante.
            self.assertEqual(primeiro["_gabarito"]["A"], versao_da_persona(viva))
            self.assertEqual(primeiro["_gabarito"]["B"], versao_da_persona(seria))

    def test_revelacao_agrega_por_variante_so_depois_do_julgamento(self):
        with tempfile.TemporaryDirectory() as temp:
            rodada, seria, viva = self.gerar(temp)
            v_seria, v_viva = versao_da_persona(seria), versao_da_persona(viva)
            # Julga alto quem for a variante séria, baixo a viva, em cada jornada.
            julgamento = {}
            for item in rodada["itens"]:
                notas = {}
                for resposta in item["respostas"]:
                    variante = item["_gabarito"][resposta["rotulo"]]
                    valor = 5 if variante == v_seria else 2
                    notas[resposta["rotulo"]] = {c: valor for c in rodada["criterios"]}
                julgamento[item["jornada"]] = notas

            revelacao = revelar(rodada, julgamento)
            self.assertEqual(revelacao["por_variante"][v_seria]["media_geral"], 5.0)
            self.assertEqual(revelacao["por_variante"][v_viva]["media_geral"], 2.0)
            self.assertGreater(revelacao["por_variante"][v_seria]["media_geral"],
                               revelacao["por_variante"][v_viva]["media_geral"])

    def test_versao_muda_quando_o_conteudo_muda(self):
        with tempfile.TemporaryDirectory() as temp:
            alvo = Path(temp) / "p.md"
            alvo.write_text("Você é o Zeus. SERIO.\n", encoding="utf-8")
            antes = versao_da_persona(str(alvo))
            alvo.write_text("Você é o Zeus. BRINCALHAO.\n", encoding="utf-8")
            depois = versao_da_persona(str(alvo))
            self.assertTrue(antes.startswith("p.md@"))
            self.assertNotEqual(antes, depois)

    def test_historico_guarda_a_revelacao(self):
        with tempfile.TemporaryDirectory() as temp:
            revelacao = {"em": "2026-09-19", "modelo": "eco", "origem": "simulada",
                         "criterios": [], "por_variante": {}}
            arquivo = gravar_historico(Path(temp) / "hist", revelacao)
            gravar_historico(Path(temp) / "hist", revelacao)
            linhas = arquivo.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(linhas), 2)

    def test_ensaio_sem_modelo_marca_a_saida_como_nao_valida(self):
        with tempfile.TemporaryDirectory() as temp:
            seria, viva = escrever_personas(temp)
            aval = AvaliacaoCegaDePersona(
                config_de_teste(), Path(temp) / "estado", [seria, viva],
                embaralhar=sem_embaralhar)  # sem provedor: dublê de ensaio
            rodada = aval.gerar(JORNADAS)
            textos = [f["zeus"] for it in rodada["itens"]
                      for r in it["respostas"] for f in r["falas"]]
            self.assertTrue(all("ensaio" in t for t in textos))
            self.assertEqual(rodada["origem"], "simulada")


if __name__ == "__main__":
    unittest.main()
