"""Resposta em fluxo e provedor híbrido."""

import tempfile
import unittest
from pathlib import Path

from apoio import ProvedorFalso, Relogio, config_de_teste, em, transporte_roteirizado
from zeus.canais import CanalMemoria
from zeus.ferramentas import Ferramentas
from zeus.config import Config
from zeus.llm import (ErroDeModelo, ProvedorHibrido, ProvedorOllama, ProvedorOpenRouter, Resposta,
                      contabilizar, criar_provedor, uso_da_chave)
from zeus.nucleo import Zeus
from zeus.persona import Persona
from zeus.store import Store


def fluxo_falso(pacotes):
    def transporte(metodo, url, corpo=None, cabecalhos=None, timeout=None):
        transporte.corpos.append(corpo)
        for pacote in pacotes:
            yield pacote
    transporte.corpos = []
    return transporte


class RespostaEmFluxo(unittest.TestCase):
    def test_pedacos_chegam_conforme_o_modelo_escreve(self):
        provedor = ProvedorOllama("http://x", "zeus")
        provedor.transporte_de_fluxo = fluxo_falso([
            {"model": "zeus", "message": {"content": "Marquei "}},
            {"model": "zeus", "message": {"content": "para "}},
            {"model": "zeus", "message": {"content": "as 19:30."}, "done": True,
             "eval_count": 12, "eval_duration": 1_200_000_000,
             "prompt_eval_count": 400, "prompt_eval_duration": 12_500_000_000},
        ])
        vistos = []
        resposta = provedor.conversar_em_fluxo([], ao_receber=vistos.append)
        self.assertEqual(vistos, ["Marquei ", "para ", "as 19:30."])
        self.assertEqual(resposta.texto, "Marquei para as 19:30.")
        self.assertEqual(resposta.estatisticas["eval_count"], 12)
        self.assertTrue(provedor.transporte_de_fluxo.corpos[0]["stream"])

    def test_modelo_trocado_no_meio_do_fluxo_e_recusado(self):
        provedor = ProvedorOllama("http://x", "zeus")
        provedor.transporte_de_fluxo = fluxo_falso([{"model": "llava:7b", "message": {"content": "oi"}}])
        with self.assertRaises(ErroDeModelo):
            provedor.conversar_em_fluxo([])

    def test_chamada_de_ferramenta_tambem_vem_pelo_fluxo(self):
        provedor = ProvedorOllama("http://x", "zeus")
        provedor.transporte_de_fluxo = fluxo_falso([
            {"model": "zeus", "message": {"content": "", "tool_calls": [
                {"function": {"name": "agendar_lembrete",
                              "arguments": {"texto": "água", "quando": "+30m"}}}]},
             "done": True},
        ])
        resposta = provedor.conversar_em_fluxo([], ferramentas=[{}])
        self.assertEqual(resposta.chamadas[0]["nome"], "agendar_lembrete")


class FluxoNoNucleo(unittest.TestCase):
    def montar(self, temp, roteiro):
        relogio = Relogio(em(2026, 9, 19, 20, 0))
        store = Store(Path(temp))
        provedor = ProvedorFalso(roteiro)

        def em_fluxo(mensagens, ferramentas=None, temperatura=0.0, ao_receber=None):
            resposta = provedor.conversar(mensagens, ferramentas, temperatura)
            if ao_receber and resposta.texto:
                for palavra in resposta.texto.split(" "):
                    ao_receber(palavra + " ")
            return resposta

        provedor.conversar_em_fluxo = em_fluxo
        zeus = Zeus(store, provedor, Persona.carregar("config/persona.md"),
                    Ferramentas(store, relogio), config_de_teste(), CanalMemoria(), relogio)
        return store, zeus

    def test_rascunho_descartado_quando_o_modelo_decide_usar_ferramenta(self):
        with tempfile.TemporaryDirectory() as temp:
            store, zeus = self.montar(temp, [
                Resposta("deixa eu ver", [{"id": "c", "nome": "listar_pendencias",
                                           "argumentos": {}}], "m"),
                Resposta("Nada pendente por aqui.", [], "m"),
            ])
            sinais = []
            final = zeus.conversar("o que tá pendente?", ao_receber=sinais.append)
            self.assertIn(None, sinais)                      # mandou descartar o rascunho
            self.assertEqual(final, "Nada pendente por aqui.")
            store.close()

    def test_sem_ferramenta_o_texto_sai_inteiro_em_pedacos(self):
        with tempfile.TemporaryDirectory() as temp:
            # Frase neutra: "Marquei" sem ferramenta agora ganha correção (#78),
            # coberta em test_recibo.
            store, zeus = self.montar(temp, [Resposta("O treino é às 19:30.", [], "m")])
            pedacos = []
            final = zeus.conversar("que horas é o treino?", ao_receber=pedacos.append)
            self.assertEqual("".join(p for p in pedacos if p).strip(), final)
            store.close()


class Hibrido(unittest.TestCase):
    def test_ferramenta_fica_no_local_e_conversa_vai_para_o_remoto(self):
        local = ProvedorFalso([
            Resposta("", [{"id": "c", "nome": "agendar_lembrete", "argumentos": {}}], "local"),
            Resposta("", [], "local"),
        ])
        remoto = ProvedorFalso([Resposta("Marquei, senhor.", [], "remoto")])
        hibrido = ProvedorHibrido(local, remoto)

        com_ferramenta = hibrido.conversar([], ferramentas=[{}], temperatura=0.7)
        self.assertEqual(com_ferramenta.chamadas[0]["nome"], "agendar_lembrete")
        self.assertEqual(len(remoto.recebidas), 0)  # o remoto nem foi acionado

        conversa = hibrido.conversar([], ferramentas=[{}], temperatura=0.7)
        self.assertEqual(conversa.texto, "Marquei, senhor.")
        self.assertEqual(len(remoto.recebidas), 1)

    def test_verificacao_cobra_os_dois_modelos(self):
        local, remoto = ProvedorFalso([]), ProvedorFalso([])
        local.modelo, remoto.modelo = "llama-local", "hermes-remoto"
        self.assertEqual(ProvedorHibrido(local, remoto).verificar(),
                         "llama-local + hermes-remoto")


if __name__ == "__main__":
    unittest.main()


class ModeloPorPapel(unittest.TestCase):
    def config(self, **ajustes):
        base = dict(provedor="openrouter", modelo="anthropic/claude-sonnet-5.5",
                    openrouter_chave="teste")
        base.update(ajustes)
        return Config(**base)

    def test_um_modelo_so_e_uma_chamada(self):
        provedor = criar_provedor(self.config())
        self.assertIsInstance(provedor, ProvedorOpenRouter)
        self.assertIsInstance(criar_provedor(self.config(
            modelo_ferramentas="anthropic/claude-sonnet-5.5")), ProvedorOpenRouter)

    def test_modelo_de_ferramentas_diferente_decide(self):
        transporte = transporte_roteirizado([("chat/completions", {
            "model": "anthropic/claude-haiku-5.5",
            "choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "consultar_fato", "arguments": "{}"}}]}}]})])
        provedor = criar_provedor(self.config(modelo_ferramentas="anthropic/claude-haiku-5.5"),
                                  transporte)
        resposta = provedor.conversar([{"role": "user", "content": "oi"}], [{"type": "function"}])
        self.assertEqual(resposta.chamadas[0]["nome"], "consultar_fato")
        self.assertEqual(transporte.chamadas[0]["corpo"]["model"], "anthropic/claude-haiku-5.5")

    def test_uso_de_cada_chamada_e_contabilizado(self):
        transporte = transporte_roteirizado([("chat/completions", {
            "model": "anthropic/claude-sonnet-5.5",
            "choices": [{"message": {"content": "Olá."}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 40, "cost": 0.0028}})])
        provedor = criar_provedor(self.config(), transporte)
        usos = []
        contabilizar(provedor, usos.append)
        provedor.conversar([{"role": "user", "content": "oi"}])
        self.assertEqual(transporte.chamadas[0]["corpo"]["usage"], {"include": True})
        self.assertEqual(usos, [{"modelo": "anthropic/claude-sonnet-5.5", "entrada": 1200,
                                 "saida": 40, "custo": 0.0028}])

    def test_contabilidade_com_defeito_nao_derruba_a_conversa(self):
        transporte = transporte_roteirizado([("chat/completions", {
            "model": "anthropic/claude-sonnet-5.5", "choices": [{"message": {"content": "Olá."}}],
            "usage": {"prompt_tokens": 1}})])
        provedor = criar_provedor(self.config(), transporte)

        def quebra(uso):
            raise RuntimeError("log fora do ar")

        contabilizar(provedor, quebra)
        self.assertEqual(provedor.conversar([{"role": "user", "content": "oi"}]).texto, "Olá.")

    def test_uso_da_chave(self):
        transporte = transporte_roteirizado([("/key", {"data": {
            "usage": 3.5, "usage_daily": 0.42, "usage_weekly": 1.1, "usage_monthly": 3.5}})])
        self.assertEqual(uso_da_chave(self.config(), transporte),
                         {"hoje": 0.42, "semana": 1.1, "mes": 3.5, "total": 3.5})


class ExemplosDaPersona(unittest.TestCase):
    def test_modelo_local_aprende_por_turno(self):
        persona = Persona.carregar("config/persona.md")
        self.assertEqual(persona.exemplos_para("ollama"), persona.exemplos())
        self.assertEqual(persona.exemplos_para("hibrido"), persona.exemplos())

    def test_modelo_grande_recebe_exemplos_ditos_ficticios(self):
        persona = Persona.carregar("config/persona.md")
        mensagens = persona.exemplos_para("openrouter")
        self.assertEqual([m["role"] for m in mensagens], ["system"])
        self.assertIn("fictícios", mensagens[0]["content"])
        self.assertIn("14h32", mensagens[0]["content"])
        # Nenhum turno de exemplo se passa por conversa.
        self.assertNotIn("assistant", [m["role"] for m in mensagens])
