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
        # O relógio é a última linha que muda a cada turno: nada volátil pode
        # vir antes dele, senão o prefixo estável quebra e o servidor
        # reprocessa a persona inteira a cada mensagem.
        self.assertTrue(linhas[-2].startswith("Momento atual:"))
        # Depois dele vem uma única linha fixa, que reancora a voz. Ser fixa é
        # o que a deixa sair de graça: ela não muda de turno para turno.
        self.assertTrue(linhas[-1].startswith("Agora responda como Zeus fala"))
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


class PromptSemMetatexto(unittest.TestCase):
    """O modelo lê o prompt inteiro como instrução.

    Uma linha explicando que o arquivo é editável, ou que os pares de fala
    viram turnos reais, ensina o registro de documento técnico — e a resposta
    sai com cara de documentação. Foi parte do "ainda muito robótico"."""

    def setUp(self):
        self.persona = Persona.carregar("config/persona.md")

    def test_o_aviso_sobre_o_arquivo_nao_vai_para_o_modelo(self):
        instrucao = self.persona.instrucao()
        self.assertIn("editável", self.persona.texto)
        self.assertNotIn("editável", instrucao)
        self.assertNotIn("sem novo deploy", instrucao)

    def test_a_secao_que_explica_os_exemplos_sai_inteira(self):
        instrucao = self.persona.instrucao()
        self.assertNotIn("Exemplos de voz", instrucao)
        self.assertNotIn("Edite à vontade", instrucao)

    def test_mas_os_exemplos_continuam_chegando_como_turnos(self):
        """Tirar a explicação não pode tirar a voz junto."""
        exemplos = self.persona.exemplos()
        self.assertGreaterEqual(len(exemplos), 10)
        self.assertIn("Opa", exemplos[1]["content"])

    def test_a_instrucao_comeca_na_primeira_secao(self):
        self.assertTrue(self.persona.instrucao().startswith("## Identidade"))

    def test_as_secoes_de_comportamento_continuam_inteiras(self):
        instrucao = self.persona.instrucao()
        for esperado in ("## Identidade", "## Como você fala",
                         "## Agir, e depois contar", "## Limites que você respeita"):
            self.assertIn(esperado, instrucao)

    def test_persona_sem_secao_nenhuma_vale_inteira(self):
        """A persona mínima embutida é uma frase só; não há o que separar."""
        curta = Persona("Você é Zeus.", "teste")
        self.assertEqual(curta.instrucao(), "Você é Zeus.")

    def test_comentario_de_html_nao_chega_ao_modelo(self):
        com_nota = Persona("## Voz\n<!-- lembrar de revisar -->\nFale curto.", "teste")
        self.assertNotIn("revisar", com_nota.instrucao())
        self.assertIn("Fale curto.", com_nota.instrucao())
