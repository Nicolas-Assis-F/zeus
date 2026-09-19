"""Orçamento de contexto: o custo de uma resposta não pode crescer com a memória."""

import unittest

from zeus.contexto import estimar_tokens, selecionar
from zeus.persona import Persona


def fatos_sinteticos(quantidade, estado="confirmado"):
    return [{"key": f"fato_{i:03d}", "value": f"valor registrado numero {i}",
             "estado": estado, "updated_at": f"2026-09-{(i % 28) + 1:02d}T10:00:00+00:00"}
            for i in range(quantidade)]


class OTetoSegura(unittest.TestCase):
    def test_custo_para_de_crescer_com_a_memoria(self):
        medidas = {}
        for quantidade in (10, 100, 500):
            escolha = selecionar(fatos_sinteticos(quantidade), "", teto=600)
            medidas[quantidade] = escolha["tokens"]
            self.assertLessEqual(escolha["tokens"], 600)
        # Entre 100 e 500 fatos o contexto não cresce: o teto já foi atingido.
        self.assertEqual(medidas[100], medidas[500])
        self.assertLess(medidas[10], medidas[500])

    def test_sem_teto_o_comportamento_antigo_continua(self):
        escolha = selecionar(fatos_sinteticos(50), "", teto=0)
        self.assertEqual(len(escolha["nucleo"]), 50)
        self.assertEqual(escolha["fora"], [])

    def test_nada_sai_em_silencio(self):
        escolha = selecionar(fatos_sinteticos(300), "", teto=200)
        dentro = len(escolha["nucleo"]) + len(escolha["hipoteses"]) + len(escolha["trazidos"])
        self.assertEqual(dentro + len(escolha["fora"]), 300)
        self.assertGreater(len(escolha["fora"]), 0)


class ARelevanciaTrazDeVolta(unittest.TestCase):
    def test_fato_antigo_volta_quando_a_mensagem_fala_dele(self):
        fatos = fatos_sinteticos(200)
        antigo = {"key": "treino", "value": "academia no fim da tarde",
                  "estado": "confirmado", "updated_at": "2026-01-01T10:00:00+00:00"}
        fatos.append(antigo)

        sem_assunto = selecionar(fatos, "bom dia", teto=300)
        self.assertNotIn("treino", [f["key"] for f in sem_assunto["nucleo"]])
        self.assertIn("treino", [f["key"] for f in sem_assunto["fora"]])

        com_assunto = selecionar(fatos, "vou treinar hoje na academia", teto=300)
        self.assertIn("treino", [f["key"] for f in com_assunto["trazidos"]])
        self.assertLessEqual(com_assunto["tokens"], 300)

    def test_o_que_a_mensagem_traz_fica_no_fim_do_contexto(self):
        """O começo do prompt precisa continuar estável entre turnos."""
        fatos = fatos_sinteticos(50) + [
            {"key": "treino", "value": "academia no fim da tarde",
             "estado": "confirmado", "updated_at": "2026-01-01T10:00:00+00:00"}]
        persona = Persona("Você é Zeus.", "teste")
        texto = persona.sistema(fatos, mensagem="vou treinar na academia", teto=300)
        posicao_do_bloco = texto.index("Da memória, por causa do que ele acabou de dizer")
        self.assertGreater(posicao_do_bloco, texto.index("Fatos confirmados na memória"))


class HipoteseNaoSomeSozinha(unittest.TestCase):
    def test_hipotese_tem_reserva_propria_mesmo_sem_a_mensagem_citar(self):
        fatos = fatos_sinteticos(200) + [
            {"key": "saida_de_casa", "value": "por volta das 7h", "estado": "hipotese",
             "updated_at": "2026-02-01T10:00:00+00:00"}]
        escolha = selecionar(fatos, "bom dia", teto=400)
        self.assertIn("saida_de_casa", [f["key"] for f in escolha["hipoteses"]])

    def test_hipotese_nunca_aparece_como_fato_confirmado(self):
        fatos = [{"key": "saida", "value": "por volta das 7h", "estado": "hipotese",
                  "updated_at": "2026-02-01T10:00:00+00:00"}]
        persona = Persona("Você é Zeus.", "teste")
        texto = persona.sistema(fatos, mensagem="que horas eu saio?", teto=300)
        self.assertIn("Hipóteses ainda não confirmadas", texto)
        posicao = texto.index("- saida: por volta das 7h")
        self.assertGreater(posicao, texto.index("Hipóteses ainda não confirmadas"))


class Estimativa(unittest.TestCase):
    def test_a_estimativa_e_declaradamente_aproximada(self):
        self.assertEqual(estimar_tokens("abcd"), 1)
        self.assertEqual(estimar_tokens("abcde"), 2)
        self.assertEqual(estimar_tokens(""), 1)


if __name__ == "__main__":
    unittest.main()
