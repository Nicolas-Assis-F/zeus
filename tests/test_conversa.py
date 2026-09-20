"""Defeitos vistos na primeira conversa real pelo Telegram."""

import tempfile
import unittest
from pathlib import Path

from apoio import ProvedorFalso, Relogio, config_de_teste, em
from zeus.canais import CanalMemoria
from zeus.ferramentas import Ferramentas
from zeus.guarda import limpar_resposta
from zeus.llm import Resposta
from zeus.nucleo import SEM_RESPOSTA, Zeus
from zeus.persona import Persona
from zeus.store import Store

PERSONA = Path(__file__).resolve().parents[1] / "config" / "persona.md"


def montar(temp, roteiro):
    relogio = Relogio(em(2026, 9, 18, 18, 0))
    store = Store(Path(temp))
    provedor = ProvedorFalso(roteiro)
    canal = CanalMemoria()
    zeus = Zeus(store, provedor, Persona.carregar(PERSONA),
                Ferramentas(store, relogio), config_de_teste(), canal, relogio)
    return store, provedor, zeus


class ChamadaVazada(unittest.TestCase):
    def test_json_de_ferramenta_nao_chega_ao_usuario(self):
        sujo = ('Acho que encontramos o problema!\n\n'
                '{"name": "chamar_ferramenta", "parameters": {"ferramenta": "melhoria"}}')
        self.assertEqual(limpar_resposta(sujo), "Acho que encontramos o problema!")

    def test_resposta_que_era_so_json_vira_frase_honesta(self):
        with tempfile.TemporaryDirectory() as temp:
            store, _, zeus = montar(temp, [
                Resposta('{"name": "chamar_ferramenta", "parameters": {}}', [], "m"),
            ])
            self.assertEqual(zeus.conversar("onde podemos melhorar?"), SEM_RESPOSTA)
            store.close()

    def test_json_legitimo_no_texto_e_preservado(self):
        self.assertIn('"temperatura"', limpar_resposta('Olha: {"temperatura": 21}'))


class PapelVazado(unittest.TestCase):
    """Nicolas recebeu mensagens começando com a palavra "assistant".

    Uma delas era só isso, sem resposta nenhuma. É o gabarito do formato de
    chat escapando para dentro do conteúdo, não algo que ele escreveu."""

    def test_palavra_do_papel_sai_do_inicio(self):
        self.assertEqual(limpar_resposta("assistant\n\nOpa, senhor."), "Opa, senhor.")
        self.assertEqual(limpar_resposta("Assistant: tudo certo"), "tudo certo")
        self.assertEqual(limpar_resposta("<|im_start|>assistant\nOi"), "Oi")

    def test_resposta_que_era_so_o_papel_vira_frase_honesta(self):
        with tempfile.TemporaryDirectory() as temp:
            store, _, zeus = montar(temp, [Resposta("assistant", [], "m")])
            self.assertEqual(zeus.conversar("e aí?"), SEM_RESPOSTA)
            store.close()

    def test_a_palavra_no_meio_do_texto_nao_e_tocada(self):
        self.assertIn("assistant", limpar_resposta("o papel assistant do modelo"))


class TomDaConversa(unittest.TestCase):
    def test_exemplos_de_voz_entram_como_turnos_reais(self):
        with tempfile.TemporaryDirectory() as temp:
            store, provedor, zeus = montar(temp, [Resposta("Opa, senhor.", [], "m")])
            zeus.conversar("opa")
            enviadas = provedor.recebidas[0]
            self.assertEqual(enviadas[0]["role"], "system")
            self.assertEqual(enviadas[1]["role"], "user")
            self.assertEqual(enviadas[2]["role"], "assistant")
            self.assertGreaterEqual(len([m for m in enviadas if m["role"] == "assistant"]), 4)
            store.close()

    def test_persona_instrui_a_nao_consultar_memoria_por_saudacao(self):
        persona = Persona.carregar(PERSONA)
        contexto = persona.sistema()
        self.assertIn("responda", contexto.lower())
        self.assertIn("opa", contexto.lower())
        self.assertIn("sem busca na internet", contexto.lower())


if __name__ == "__main__":
    unittest.main()
