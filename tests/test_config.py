import re
import json
import tempfile
import unittest
from pathlib import Path

from zeus.config import carregar


class Origem(unittest.TestCase):
    def test_arquivo_ausente_e_dito_em_voz_alta(self):
        with tempfile.TemporaryDirectory() as temp:
            config = carregar(Path(temp) / "config.json")
        self.assertIn("não existe", config.origem)
        self.assertFalse(config.canal_configurado)

    def test_arquivo_lido_aparece_na_origem_e_segredo_nao_vaza(self):
        with tempfile.TemporaryDirectory() as temp:
            caminho = Path(temp) / "config.json"
            caminho.write_text(json.dumps({"telegram_token": "abc", "telegram_chat_id": "7"}),
                               encoding="utf-8")
            config = carregar(caminho)
        self.assertEqual(config.origem, str(caminho))
        self.assertTrue(config.canal_configurado)
        self.assertEqual(config.sem_segredos()["telegram_token"], "definido")
        self.assertNotIn("abc", json.dumps(config.sem_segredos()))


if __name__ == "__main__":
    unittest.main()


class ExemploNaoGuardaSegredo(unittest.TestCase):
    """`config/config.example.json` está no git, e o Zeus nunca lê dele.

    Mesmo assim ele já foi preenchido com valores de verdade duas vezes — é o
    arquivo que aparece primeiro quando alguém procura onde configurar. Aqui o
    erro deixa de ser silencioso: um token no exemplo derruba a suíte antes de
    virar commit."""

    PADROES = [
        ("chave de API", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
        ("token do Telegram", re.compile(r"\b\d{8,}:[A-Za-z0-9_\-]{30,}")),
        ("segredo hexadecimal longo", re.compile(r"\b[0-9a-f]{32,}\b")),
        ("chave do Hugging Face", re.compile(r"\bhf_[A-Za-z0-9]{20,}")),
    ]

    def test_o_exemplo_no_git_nao_tem_valor_de_verdade(self):
        from zeus.persona import Persona           # só para achar a raiz do repo
        raiz = Path(Persona.resolver("config/config.example.json"))
        texto = raiz.read_text(encoding="utf-8")
        for nome, padrao in self.PADROES:
            achado = padrao.search(texto)
            self.assertIsNone(
                achado,
                f"{nome} dentro de config/config.example.json — esse arquivo vai "
                f"para o GitHub. Revogue o valor e escreva em "
                f"~/.config/zeus/config.json.")

    def test_os_campos_de_segredo_continuam_vazios_no_exemplo(self):
        from zeus.persona import Persona
        raiz = Path(Persona.resolver("config/config.example.json"))
        dados = json.loads(raiz.read_text(encoding="utf-8"))
        for campo in ("telegram_token", "telegram_chat_id", "openrouter_chave",
                      "chave_hud"):
            self.assertEqual(dados.get(campo, ""), "",
                             f"{campo} preenchido no exemplo que está no git")

    def test_o_aviso_dentro_do_arquivo_continua_la(self):
        from zeus.persona import Persona
        raiz = Path(Persona.resolver("config/config.example.json"))
        dados = json.loads(raiz.read_text(encoding="utf-8"))
        self.assertIn("EXEMPLO", dados.get("_leia_me", "").upper())
