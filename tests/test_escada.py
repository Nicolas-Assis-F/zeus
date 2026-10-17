"""Escada de modelos (#72): desce no erro, descansa e registra quem respondeu."""

import unittest

from zeus.config import Config
from zeus.llm import (ErroDeModelo, ProvedorEmEscada, ProvedorOllama, ProvedorOpenRouter,
                      Resposta, adaptar_mensagens, criar_provedor, descanso_do_erro)


class Relogio:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


class Degrau:
    def __init__(self, modelo, falhas=(), chamadas=None):
        self.modelo = modelo
        self.falhas = list(falhas)
        self.chamadas = 0
        self.recebidas = []
        self.resposta_chamadas = chamadas

    def _talvez_falhar(self):
        self.chamadas += 1
        if self.falhas:
            erro = self.falhas.pop(0)
            if erro:
                raise erro

    def verificar(self):
        self._talvez_falhar()
        return self.modelo

    def conversar(self, mensagens, ferramentas=None, temperatura=0.0):
        self._talvez_falhar()
        self.recebidas.append(mensagens)
        return Resposta(f"resposta de {self.modelo}", self.resposta_chamadas, self.modelo)

    def conversar_em_fluxo(self, mensagens, ferramentas=None, temperatura=0.0, ao_receber=None):
        ao_receber("rascunho ")
        self._talvez_falhar()
        ao_receber("final")
        return Resposta(f"fluxo de {self.modelo}", None, self.modelo)

    def mensagem_do_assistente(self, resposta):
        return {"role": "assistant", "content": resposta.texto, "de": self.modelo}

    def mensagem_de_ferramenta(self, chamada, conteudo):
        return {"role": "tool", "content": conteudo, "de": self.modelo}


REDE = ErroDeModelo("Não consegui falar com https://openrouter.ai/api/v1: timed out")
SALDO = ErroDeModelo("POST https://openrouter.ai/api/v1/chat/completions respondeu 402: sem saldo")


class TestEscada(unittest.TestCase):
    def setUp(self):
        self.relogio = Relogio()
        self.trocas = []

    def escada(self, *degraus):
        return ProvedorEmEscada(degraus, relogio=self.relogio,
                                ao_trocar=lambda *t: self.trocas.append(t))

    def test_tudo_de_pe_responde_o_primeiro_sem_registro(self):
        escada = self.escada(Degrau("sonnet"), Degrau("ollama"))
        self.assertEqual(escada.conversar([]).modelo, "sonnet")
        self.assertEqual(self.trocas, [])

    def test_rede_caida_desce_e_registra_motivo(self):
        sonnet, ollama = Degrau("sonnet", [REDE]), Degrau("ollama")
        escada = self.escada(sonnet, ollama)
        self.assertEqual(escada.conversar([]).modelo, "ollama")
        degrau, modelo, motivo = self.trocas[0]
        self.assertEqual((degrau, modelo), (2, "ollama"))
        self.assertIn("timed out", motivo)

    def test_degrau_caido_descansa_conforme_o_erro(self):
        sonnet, haiku = Degrau("sonnet", [SALDO]), Degrau("haiku")
        escada = self.escada(sonnet, haiku)
        escada.conversar([])
        self.relogio.agora = 3599
        escada.conversar([])
        self.assertEqual(sonnet.chamadas, 1)  # em descanso, nem tentou
        self.relogio.agora = 3601
        self.assertEqual(escada.conversar([]).modelo, "sonnet")
        self.assertEqual([t[0] for t in self.trocas], [2, 1])  # desceu e voltou

    def test_todos_caidos_levanta_erro(self):
        escada = self.escada(Degrau("a", [REDE]), Degrau("b", [SALDO]))
        with self.assertRaises(ErroDeModelo) as erro:
            escada.conversar([])
        self.assertIn("Todos os degraus", str(erro.exception))

    def test_todos_descansando_tenta_mesmo_assim(self):
        a = Degrau("a", [REDE])
        escada = self.escada(a)
        with self.assertRaises(ErroDeModelo):
            escada.conversar([])
        self.assertEqual(escada.conversar([]).modelo, "a")

    def test_fluxo_descarta_rascunho_do_degrau_caido(self):
        recebidos = []
        escada = self.escada(Degrau("sonnet", [REDE]), Degrau("ollama"))
        resposta = escada.conversar_em_fluxo([], ao_receber=recebidos.append)
        self.assertEqual(resposta.modelo, "ollama")
        self.assertEqual(recebidos, ["rascunho ", None, "rascunho ", "final"])

    def test_verificar_aceita_degrau_de_baixo(self):
        escada = self.escada(Degrau("sonnet", [SALDO]), Degrau("ollama"))
        self.assertIn("degrau 2", escada.verificar())
        escada.conversar([])
        self.assertEqual(escada.ultimo_degrau, 1)
        self.assertIn("em descanso", self.trocas[0][2])
        self.assertIn("402", self.trocas[0][2])

    def test_verificar_sem_nenhum(self):
        with self.assertRaises(ErroDeModelo):
            self.escada(Degrau("a", [REDE])).verificar()

    def test_mensagens_de_ferramenta_seguem_quem_respondeu(self):
        chamadas = [{"id": "x1", "nome": "consultar_fato", "argumentos": {"chave": "a"}}]
        escada = self.escada(Degrau("sonnet", [REDE], chamadas), Degrau("ollama", (), chamadas))
        resposta = escada.conversar([])
        self.assertEqual(escada.mensagem_do_assistente(resposta)["de"], "ollama")


class TestFormatos(unittest.TestCase):
    def test_adaptar_do_ollama_para_o_openrouter_e_de_volta(self):
        ollama = ProvedorOllama("http://x", "llama")
        remoto = ProvedorOpenRouter("http://y", "sonnet", "chave")
        chamada = {"function": {"name": "consultar_fato", "arguments": {"chave": "a"}}}
        mensagens = [{"role": "user", "content": "oi"},
                     {"role": "assistant", "content": "", "tool_calls": [chamada]},
                     {"role": "tool", "content": "{}", "name": "consultar_fato"}]
        para_remoto = adaptar_mensagens(mensagens, remoto)
        self.assertEqual(para_remoto[1]["tool_calls"][0]["id"], "chamada-0")
        self.assertIsInstance(para_remoto[1]["tool_calls"][0]["function"]["arguments"], str)
        self.assertEqual(para_remoto[2]["tool_call_id"], "chamada-0")
        de_volta = adaptar_mensagens(para_remoto, ollama)
        self.assertEqual(de_volta[1]["tool_calls"][0]["function"]["arguments"], {"chave": "a"})
        self.assertEqual(de_volta[2]["name"], "consultar_fato")
        self.assertEqual(de_volta[0], mensagens[0])

    def test_descanso_por_erro(self):
        self.assertEqual(descanso_do_erro(REDE), 60)
        self.assertEqual(descanso_do_erro(SALDO), 3600)
        self.assertEqual(descanso_do_erro(ErroDeModelo("... respondeu 503: x")), 120)
        self.assertEqual(descanso_do_erro(ErroDeModelo("... respondeu 429: x")), 300)
        self.assertEqual(descanso_do_erro(ErroDeModelo("... respondeu 400: x")), 0)


class TestMontagem(unittest.TestCase):
    def test_sem_reserva_continua_igual(self):
        provedor = criar_provedor(Config(provedor="openrouter", openrouter_chave="k",
                                         modelo="anthropic/claude-sonnet-5.5"))
        self.assertIsInstance(provedor, ProvedorOpenRouter)

    def test_reserva_monta_degraus(self):
        config = Config(provedor="openrouter", openrouter_chave="k",
                        modelo="anthropic/claude-sonnet-5.5", escada_timeout_s=30,
                        escada_reserva=("openrouter:anthropic/claude-haiku-5.5",
                                        "ollama:llama3.1:8b-instruct-q4_K_M"))
        escada = criar_provedor(config)
        self.assertIsInstance(escada, ProvedorEmEscada)
        self.assertEqual([d.modelo for d in escada.degraus],
                         ["anthropic/claude-sonnet-5.5", "anthropic/claude-haiku-5.5",
                          "llama3.1:8b-instruct-q4_K_M"])
        self.assertEqual(escada.degraus[0].timeout, 30)
        self.assertIsInstance(escada.degraus[2], ProvedorOllama)

    def test_reserva_em_texto_do_ambiente(self):
        config = Config(provedor="ollama", escada_reserva="ollama:a, ollama:b")
        self.assertEqual([d.modelo for d in criar_provedor(config).degraus][1:], ["a", "b"])

    def test_degrau_invalido(self):
        with self.assertRaises(ErroDeModelo):
            criar_provedor(Config(provedor="ollama", escada_reserva=("gemini:x",)))


if __name__ == "__main__":
    unittest.main()
