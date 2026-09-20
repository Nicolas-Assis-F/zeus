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


class PersonaQueAge(unittest.TestCase):
    """Nicolas: 'sempre fica falando pra eu confirmar'.

    Os exemplos de voz entram na conversa como turnos reais, então um exemplo
    que pede licença ensina o modelo a pedir licença. Este teste guarda o
    arquivo contra a volta desse hábito numa edição futura."""

    ABERTURAS_QUE_PEDEM_LICENCA = (
        "posso ", "devo ", "quer que eu", "deseja que eu", "gostaria que eu",
        "vou guardar", "vou registrar", "vou anotar", "vou pesquisar",
        "vou procurar", "vou agendar", "vou conferir",
    )

    def setUp(self):
        from zeus.persona import Persona
        self.persona = Persona.carregar("config/persona.md")
        self.texto = self.persona.texto

    def test_nenhum_exemplo_de_voz_abre_pedindo_licenca(self):
        falas = [l.split(":", 1)[1].strip().lower()
                 for l in self.texto.splitlines()
                 if l.strip().lower().startswith("- zeus:")]
        self.assertGreater(len(falas), 5, "os exemplos de voz sumiram")
        for fala in falas:
            for abertura in self.ABERTURAS_QUE_PEDEM_LICENCA:
                self.assertFalse(
                    fala.startswith(abertura),
                    f"exemplo abre com '{abertura}': {fala[:70]}")

    def test_a_regra_de_agir_primeiro_esta_escrita(self):
        baixo = self.texto.lower()
        self.assertIn("age primeiro", baixo)
        self.assertIn("reversível", baixo)

    def test_a_excecao_do_efeito_fora_da_conversa_continua(self):
        """Agir sozinho não vale para o que sai da conversa."""
        self.assertIn("irreversível", self.texto.lower())
        self.assertIn("abrir", self.texto.lower())

    def test_os_pares_de_exemplo_continuam_virando_turnos(self):
        exemplos = self.persona.exemplos()
        self.assertTrue(exemplos)
        self.assertEqual(len(exemplos) % 2, 0)
        self.assertEqual(exemplos[0]["role"], "user")
        self.assertEqual(exemplos[1]["role"], "assistant")

    def test_a_persona_anterior_fica_guardada_para_comparacao(self):
        anterior = Path("avaliacao/personas/anterior.md")
        self.assertTrue(anterior.exists())
        self.assertIn("persona-cega", anterior.read_text(encoding="utf-8"))
