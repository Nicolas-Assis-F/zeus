"""Estados honestos: o que o Zeus diz tem que bater com o que ele fez.

Cada teste aqui nasceu de um defeito reproduzido na base b3a8afb."""

import tempfile
import unittest
from pathlib import Path

from apoio import ProvedorFalso, Relogio, config_de_teste, em
from zeus.ferramentas import Ferramentas
from zeus.llm import Resposta
from zeus.nucleo import Zeus
from zeus.persona import Persona
from zeus.store import Store
from zeus.telemetria import Medida


def chamada(nome, **argumentos):
    return {"id": nome, "nome": nome, "argumentos": argumentos}


def pedir(nome, **argumentos):
    return Resposta("", [chamada(nome, **argumentos)], "modelo-falso")


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.relogio = Relogio(em(2026, 9, 23, 20))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def zeus(self, roteiro, provedor=None):
        self.provedor = provedor or ProvedorFalso(roteiro)
        return Zeus(self.store, self.provedor, Persona.carregar("config/persona.md"),
                    Ferramentas(self.store, relogio=self.relogio), config_de_teste(),
                    relogio=self.relogio)

    def perguntada(self):
        identificador = self.store.criar_pergunta("Quer que eu lembre da creatina?",
                                                  "combinado de treino", self.relogio(),
                                                  em=self.relogio())
        self.store.marcar_perguntada(identificador, self.relogio())
        return identificador


class UltimaRodada(Base):
    def test_ultima_rodada_nao_oferece_ferramenta_e_nao_executa_pedido_tardio(self):
        """Defeito C1: na 3ª rodada o lembrete era criado e a resposta dizia
        que o Zeus não soube responder. Nicolas repetia e o efeito duplicava."""
        zeus = self.zeus([pedir("listar_pendencias"), pedir("listar_pendencias"),
                          pedir("agendar_lembrete", texto="dentista", quando="+30m")])
        resposta = zeus.conversar("me lembra do dentista")
        self.assertEqual(self.provedor.catalogos[-1], [])
        self.assertEqual(self.store.agenda_pendente(), [])
        self.assertIn("não executei", resposta.lower())
        linha = zeus.ultima_medida.como_linha()
        self.assertEqual(linha["ferramentas"][-1]["resultado"], "nao_executada")

    def test_efeito_feito_nao_some_quando_a_redacao_falha(self):
        zeus = self.zeus([pedir("agendar_lembrete", texto="dentista", quando="+30m"),
                          Resposta("", [], "modelo-falso")])
        resposta = zeus.conversar("me lembra do dentista")
        self.assertEqual(len(self.store.agenda_pendente()), 1)
        # Não é "não soube responder": o lembrete existe e a resposta diz isso.
        self.assertIn("lembrete #1", resposta.lower())

    def test_efeito_fica_registrado_mesmo_se_o_modelo_cair_depois(self):
        class CaiNaSegunda(ProvedorFalso):
            def conversar(self, mensagens, ferramentas=None, temperatura=0.0):
                if self.roteiro:
                    return super().conversar(mensagens, ferramentas, temperatura)
                raise RuntimeError("modelo caiu")
        zeus = self.zeus(None, CaiNaSegunda([pedir("agendar_lembrete", texto="água",
                                                   quando="+30m")]))
        medida = Medida(turno="turno-x")
        with self.assertRaises(RuntimeError):
            zeus.conversar("me lembra de beber água", medida=medida)
        episodio = self.store.connection.execute(
            "SELECT id, fechado_em, resultado FROM episodios WHERE tipo='efeitos_do_turno' "
            "AND resumo='turno:turno-x'").fetchone()
        self.assertIsNotNone(episodio)
        fases = [r["dados"] for r in self.store.connection.execute(
            "SELECT dados FROM eventos WHERE episodio=? ORDER BY id", (episodio["id"],))]
        self.assertEqual(len(fases), 2)
        self.assertIn('"iniciada"', fases[0])
        self.assertIn('"concluida"', fases[1])
        self.assertEqual(episodio["resultado"], "falhou")

    def test_leitura_nao_abre_registro_de_efeito(self):
        zeus = self.zeus([pedir("listar_pendencias"), Resposta("Nada pendente.", [], "m")])
        zeus.conversar("o que tem pendente?")
        self.assertIsNone(self.store.connection.execute(
            "SELECT 1 FROM episodios WHERE tipo='efeitos_do_turno'").fetchone())


class PerguntaVinculada(Base):
    def test_mensagem_nao_relacionada_nao_encerra_a_pergunta(self):
        """Defeito C3: com uma pergunta em aberto, qualquer frase virava resposta."""
        identificador = self.perguntada()
        zeus = self.zeus([Resposta("Amanhã deve chover.", [], "modelo-falso")])
        zeus.conversar("vai chover amanhã?")
        situacao = self.store.connection.execute(
            "SELECT situacao, resposta FROM perguntas WHERE id=?", (identificador,)).fetchone()
        self.assertEqual(situacao["situacao"], "perguntada")
        self.assertIsNone(situacao["resposta"])

    def test_resposta_explicita_por_id_vincula(self):
        identificador = self.perguntada()
        zeus = self.zeus([Resposta("Combinado.", [], "modelo-falso")])
        zeus.conversar("pode lembrar sim", responde_a=identificador)
        situacao = self.store.connection.execute(
            "SELECT situacao, resposta FROM perguntas WHERE id=?", (identificador,)).fetchone()
        self.assertEqual(situacao["situacao"], "respondida")
        self.assertEqual(situacao["resposta"], "pode lembrar sim")
        # O modelo fica sabendo, para não perguntar de novo.
        conteudo = " ".join(m["content"] for m in self.provedor.recebidas[0])
        self.assertIn(f"#{identificador}", conteudo)

    def test_resposta_explicita_para_pergunta_encerrada_nao_finge_vinculo(self):
        identificador = self.perguntada()
        self.store.cancelar_pergunta(identificador)
        zeus = self.zeus([Resposta("Certo.", [], "modelo-falso")])
        zeus.conversar("sim", responde_a=identificador)
        conteudo = " ".join(m["content"] for m in self.provedor.recebidas[0])
        self.assertNotIn(f"responde sua pergunta #{identificador}", conteudo)

    def test_o_modelo_vincula_com_id_explicito_pela_ferramenta(self):
        identificador = self.perguntada()
        zeus = self.zeus([pedir("responder_pergunta", pergunta=identificador,
                                resposta="pode lembrar sim"),
                          Resposta("Combinado.", [], "modelo-falso")])
        zeus.conversar("pode lembrar sim")
        self.assertEqual(self.store.connection.execute(
            "SELECT situacao FROM perguntas WHERE id=?", (identificador,)).fetchone()[0],
            "respondida")

    def test_ferramenta_recusa_pergunta_que_nao_esta_aberta(self):
        ferramentas = Ferramentas(self.store, relogio=self.relogio)
        resultado = ferramentas.executar("responder_pergunta", {"pergunta": 99, "resposta": "x"})
        self.assertIn("erro", resultado)


if __name__ == "__main__":
    unittest.main()


class RetratoDoModelo(Base):
    def test_modelo_indisponivel_nao_aparece_como_pronto(self):
        """Defeito C4: com o modelo fora, o nome configurado acendia o chip."""
        from zeus.__main__ import retrato
        from zeus.config import Config
        indisponivel = retrato(self.store, Config(), None, modelo="")
        self.assertEqual(indisponivel["modelo"], "")
        self.assertEqual(indisponivel["modelo_estado"], "indisponivel")
        self.assertEqual(indisponivel["modelo_configurado"], Config().modelo)
        pronto = retrato(self.store, Config(), None, modelo="llama")
        self.assertEqual(pronto["modelo_estado"], "pronta")
