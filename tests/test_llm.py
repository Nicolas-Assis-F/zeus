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

    def test_temperatura_vai_no_corpo(self):
        transporte = transporte_roteirizado([("/api/chat", {"model": "zeus", "message": {"content": "ok"}})])
        ProvedorOllama("http://x", "zeus", transporte).conversar([], temperatura=0.0)
        self.assertEqual(transporte.chamadas[-1]["corpo"]["options"]["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main()
