"""Afirmação vazia (#78): "anotei" sem ter anotado ganha correção."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from apoio import ProvedorFalso, config_de_teste
from zeus.ferramentas import Ferramentas
from zeus.llm import Resposta
from zeus.nucleo import Zeus
from zeus.persona import Persona
from zeus.recibo import CORRECAO, afirma_memoria, conferir
from zeus.store import Store


class TestTexto(unittest.TestCase):
    def test_reconhece_afirmacoes(self):
        for frase in ("Anotei, senhor.", "Pronto, vou te lembrar às 18h.", "Agendei para amanhã.",
                      "Lembrete criado.", "Deixei anotado.", "Esqueci isso, como pediu.",
                      # ditas de verdade pelo llama 8B no X99, sem gravar nada:
                      "Registrado para as 18h.",
                      "Vou anotar para você ligar para o contador amanhã às 9h.",
                      "Agora está guardada a preferência do Henrique para áudio."):
            self.assertTrue(afirma_memoria(frase), frase)

    def test_ignora_negacao_e_conversa_comum(self):
        for frase in ("Não anotei nada ainda.", "Você quer que eu anote?", "Boa noite.",
                      "Não está agendado nada para hoje.",
                      "Esqueci de dizer: o Henrique ligou."):
            self.assertFalse(afirma_memoria(frase), frase)

    def test_conferir(self):
        self.assertEqual(conferir("Anotei.", "a", "b"), ("Anotei.", False))  # mudou: verdade
        self.assertEqual(conferir("Oi.", "a", "a"), ("Oi.", False))
        texto, vazia = conferir("Anotei.", "a", "a")
        self.assertTrue(vazia)
        self.assertTrue(texto.endswith(CORRECAO))


class TestNoNucleo(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()))
        self.vazias = []

    def tearDown(self):
        self.store.close()

    def zeus(self, roteiro):
        relogio = lambda: datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        zeus = Zeus(self.store, ProvedorFalso(roteiro), Persona.carregar("config/persona.md"),
                    Ferramentas(self.store, relogio=relogio), config_de_teste(), relogio=relogio)
        zeus.ao_afirmacao_vazia = lambda: self.vazias.append(1)
        return zeus

    def test_anotei_sem_ferramenta_ganha_correcao(self):
        final = self.zeus([Resposta("Anotei, senhor: academia às 18h.")]).conversar("anota aí")
        self.assertIn(CORRECAO, final)
        self.assertEqual(self.vazias, [1])

    def test_anotei_com_ferramenta_fica_como_esta(self):
        chamada = {"id": "1", "nome": "lembrar_fato",
                   "argumentos": {"chave": "academia", "valor": "18h", "estado": "confirmado"}}
        final = self.zeus([Resposta("", [chamada]), Resposta("Anotei, senhor.")]).conversar("anota")
        self.assertEqual(final, "Anotei, senhor.")
        self.assertEqual(self.vazias, [])


if __name__ == "__main__":
    unittest.main()
