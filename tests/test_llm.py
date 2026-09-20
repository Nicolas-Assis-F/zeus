import unittest

from apoio import transporte_roteirizado
from zeus.llm import ErroDeModelo, ProvedorOllama


class VerificacaoDeModelo(unittest.TestCase):
    def test_modelo_ausente_falha_com_instrucao(self):
        transporte = transporte_roteirizado([
            ("/api/tags", {"models": [{"name": "qwen2.5:3b"}]}),
        ])
        provedor = ProvedorOllama("http://x", "llama3.1:8b-instruct-q4_K_M", transporte)
        with self.assertRaises(ErroDeModelo) as erro:
            provedor.verificar()
        self.assertIn("ollama pull", str(erro.exception))

    def test_latest_conta_como_o_mesmo_modelo(self):
        transporte = transporte_roteirizado([("/api/tags", {"models": [{"name": "zeus:latest"}]})])
        self.assertEqual(ProvedorOllama("http://x", "zeus", transporte).verificar(), "zeus")

    def test_resposta_de_outro_modelo_e_recusada(self):
        transporte = transporte_roteirizado([
            ("/api/chat", {"model": "llava:7b", "message": {"content": "oi"}}),
        ])
        provedor = ProvedorOllama("http://x", "llama3.1:8b-instruct-q4_K_M", transporte)
        with self.assertRaises(ErroDeModelo) as erro:
            provedor.conversar([{"role": "user", "content": "oi"}])
        self.assertIn("llava", str(erro.exception))

    def test_chamada_de_ferramenta_normalizada(self):
        transporte = transporte_roteirizado([
            ("/api/chat", {"model": "zeus", "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "agendar_lembrete",
                                             "arguments": {"texto": "creatina", "quando": "+30m"}}}],
            }}),
        ])
        resposta = ProvedorOllama("http://x", "zeus", transporte).conversar([], ferramentas=[{}])
        self.assertEqual(len(resposta.chamadas), 1)
        self.assertEqual(resposta.chamadas[0]["nome"], "agendar_lembrete")
        self.assertEqual(resposta.chamadas[0]["argumentos"]["texto"], "creatina")

    def test_modelo_fica_carregado_entre_mensagens(self):
        transporte = transporte_roteirizado([("/api/chat", {"model": "zeus", "message": {"content": "ok"}})])
        ProvedorOllama("http://x", "zeus", transporte, keep_alive="1h").conversar([])
        self.assertEqual(transporte.chamadas[-1]["corpo"]["keep_alive"], "1h")

    def test_temperatura_vai_no_corpo(self):
        transporte = transporte_roteirizado([("/api/chat", {"model": "zeus", "message": {"content": "ok"}})])
        ProvedorOllama("http://x", "zeus", transporte).conversar([], temperatura=0.0)
        self.assertEqual(transporte.chamadas[-1]["corpo"]["options"]["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main()


class JanelaDeContexto(unittest.TestCase):
    """O Ollama assume 2048 tokens quando ninguém diz o contrário, e corta o
    prompt pela frente sem avisar. O começo do prompt é a persona: com 13
    ferramentas no catálogo o prompt passa de 2900 tokens, então a identidade
    era descartada em toda conversa e a resposta saía genérica."""

    def _capturar(self):
        enviados = []

        def transporte(metodo, url, corpo=None, cabecalhos=None, timeout=None):
            enviados.append(corpo)
            return {"model": "m", "message": {"content": "oi"}}

        from zeus.llm import ProvedorOllama
        provedor = ProvedorOllama("http://x", "m", transporte, contexto_tokens=8192)
        provedor.conversar([{"role": "user", "content": "opa"}], None, 0.7)
        return enviados[0]["options"]

    def test_a_janela_vai_explicita_no_pedido(self):
        self.assertEqual(self._capturar()["num_ctx"], 8192)

    def test_a_amostragem_nao_e_so_temperatura(self):
        """Sem penalidade de repetição o modelo pequeno repete construção."""
        opcoes = self._capturar()
        self.assertEqual(opcoes["temperature"], 0.7)
        self.assertEqual(opcoes["repeat_penalty"], 1.15)
        self.assertIn("top_p", opcoes)
        self.assertIn("top_k", opcoes)

    def test_o_hibrido_monta_o_local_com_as_mesmas_opcoes(self):
        """Eram duas construções quase iguais; um parâmetro novo entrava numa
        e esquecia a outra."""
        from zeus.llm import criar_provedor
        from apoio import config_de_teste
        config = config_de_teste()
        config.provedor = "hibrido"
        config.modelo_conversa = "remoto/modelo"
        config.openrouter_chave = "chave"
        config.contexto_tokens = 4096
        hibrido = criar_provedor(config, lambda *a, **k: {})
        self.assertEqual(hibrido.local.contexto_tokens, 4096)
        self.assertEqual(hibrido.local.penalidade_de_repeticao,
                         config.penalidade_de_repeticao)
