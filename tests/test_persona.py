import os
import tempfile
import unittest
from pathlib import Path

from apoio import em
from zeus.persona import PERSONA_MINIMA, Persona


class CarregamentoDaPersona(unittest.TestCase):
    def test_caminho_relativo_vale_a_partir_da_raiz_do_repositorio(self):
        anterior = os.getcwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                persona = Persona.carregar("config/persona.md")
            finally:
                os.chdir(anterior)
        self.assertNotEqual(persona.texto, PERSONA_MINIMA)
        self.assertTrue(persona.origem.endswith("config/persona.md"))

    def test_arquivo_ausente_cai_na_persona_minima(self):
        persona = Persona.carregar("config/nao_existe.md")
        self.assertEqual(persona.texto, PERSONA_MINIMA)

    def test_o_que_muda_a_cada_turno_fica_no_fim_do_contexto(self):
        persona = Persona("Você é Zeus.", "teste")
        contexto = persona.sistema(fatos=[{"key": "tratamento", "value": "senhor",
                                           "estado": "confirmado"}],
                                   agora=em(2026, 9, 18, 20, 30))
        linhas = [linha for linha in contexto.splitlines() if linha.strip()]
        self.assertTrue(linhas[-1].startswith("Momento atual:"))
        self.assertTrue(contexto.startswith("Você é Zeus."))


if __name__ == "__main__":
    unittest.main()
