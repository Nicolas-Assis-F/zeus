"""O avaliador precisa reprovar quando deve; senão ele é decoração.

Cada teste aqui quebra o Zeus de um jeito conhecido e exige que a jornada
correspondente falhe. Um avaliador que só sabe dizer "passou" não mede nada.
"""

import json
import tempfile
import unittest
from pathlib import Path

from apoio import config_de_teste
from zeus.avaliacao import Avaliacao, carregar_jornadas, em_texto

RAIZ = Path(__file__).resolve().parents[1]


def rodar(jornadas, origem="simulada"):
    with tempfile.TemporaryDirectory() as temporario:
        avaliacao = Avaliacao(config_de_teste(persona=str(RAIZ / "config" / "persona.md")),
                              temporario, origem=origem)
        return avaliacao.rodar({"jornadas": jornadas})


UMA_JORNADA = {
    "id": "lembrete",
    "titulo": "Lembrete entregue uma vez",
    "dimensoes": ["utilidade"],
    "passos": [
        {"nicolas": "me lembra de beber água em 10 minutos",
         "modelo": [{"ferramenta": "agendar_lembrete",
                     "argumentos": {"texto": "beber água", "quando": "+10m"}},
                    {"texto": "Marcado."}],
         "espera": {"usou": ["agendar_lembrete"]}},
        {"avancar": "+11m", "espera": {"entregas": 1, "contem": ["água"]}},
        {"espera": {"entregas": 0}},
    ],
}


class OAvaliadorReprova(unittest.TestCase):
    def test_jornada_correta_passa(self):
        relatorio = rodar([UMA_JORNADA])
        self.assertEqual(relatorio["jornadas"][0]["situacao"], "passou")
        self.assertEqual(relatorio["resumo"]["falhou"], 0)

    def test_expectativa_de_entrega_errada_reprova(self):
        quebrada = json.loads(json.dumps(UMA_JORNADA))
        quebrada["passos"][2]["espera"]["entregas"] = 1   # exige aviso duplicado
        relatorio = rodar([quebrada])
        self.assertEqual(relatorio["jornadas"][0]["situacao"], "falhou")
        falhas = [f for p in relatorio["jornadas"][0]["passos"] for f in p["falhas"]]
        self.assertTrue(any("entrega" in f for f in falhas))

    def test_ferramenta_nao_usada_reprova(self):
        quebrada = json.loads(json.dumps(UMA_JORNADA))
        quebrada["passos"][0]["modelo"] = [{"texto": "Tá bom."}]  # o modelo não agenda
        relatorio = rodar([quebrada])
        self.assertEqual(relatorio["jornadas"][0]["situacao"], "falhou")

    def test_ferramenta_proibida_reprova(self):
        quebrada = json.loads(json.dumps(UMA_JORNADA))
        quebrada["passos"][0]["espera"] = {"nao_usou": ["agendar_lembrete"]}
        self.assertEqual(rodar([quebrada])["jornadas"][0]["situacao"], "falhou")

    def test_memoria_ausente_reprova(self):
        jornada = {"id": "memoria", "titulo": "lembra", "dimensoes": ["memoria"],
                   "passos": [{"nicolas": "meu tratamento é senhor",
                               "modelo": [{"texto": "Certo."}],
                               "espera": {"lembra": {"tratamento": "senhor"}}}]}
        self.assertEqual(rodar([jornada])["jornadas"][0]["situacao"], "falhou")


class OrigemDaEvidencia(unittest.TestCase):
    def test_relatorio_simulado_avisa_que_nao_vale_como_hardware(self):
        texto = em_texto(rodar([UMA_JORNADA]))
        self.assertIn("evidência simulada", texto)
        self.assertIn("não vale como evidência de hardware", texto)

    def test_jornada_que_so_vale_no_real_carrega_o_aviso(self):
        jornada = json.loads(json.dumps(UMA_JORNADA))
        jornada["vale_em"] = "real"
        relatorio = rodar([jornada])
        self.assertIn("não comprova nada", relatorio["jornadas"][0]["observacao"])

    def test_pendente_e_pulada_nao_contam_como_aprovacao(self):
        pendente = {"id": "x", "titulo": "y", "status": "pendente", "motivo": "depende de #7"}
        pulada = {"id": "z", "titulo": "w", "requer_ferramentas": ["ferramenta_inexistente"],
                  "passos": []}
        resumo = rodar([pendente, pulada])["resumo"]
        self.assertEqual(resumo["passou"], 0)
        self.assertEqual(resumo["pendente"], 1)
        self.assertEqual(resumo["pulada"], 1)


class JornadasDoProjeto(unittest.TestCase):
    def test_o_arquivo_de_jornadas_roda_inteiro(self):
        jornadas = carregar_jornadas(RAIZ / "avaliacao" / "jornadas.json")
        relatorio = rodar(jornadas["jornadas"])
        self.assertEqual(relatorio["resumo"]["falhou"], 0, em_texto(relatorio))
        identificadores = {j["id"] for j in relatorio["jornadas"]}
        self.assertIn("academia", identificadores)
        self.assertIn("falha-de-canal", identificadores)

    def test_resumo_agrupa_por_dimensao(self):
        resumo = rodar([UMA_JORNADA])["resumo"]
        self.assertIn("utilidade", resumo["por_dimensao"])


if __name__ == "__main__":
    unittest.main()
