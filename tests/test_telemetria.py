"""A medida do turno diz onde o tempo foi e nunca guarda o que foi dito."""

import json
import tempfile
import unittest
from pathlib import Path

from apoio import ProvedorFalso, Relogio, config_de_teste, em
from zeus.execucao import CaixaDeEntrada, FalaEmSegundoPlano
from zeus.ferramentas import Ferramentas
from zeus.llm import ProvedorHibrido, ProvedorOllama, ProvedorOpenRouter, Resposta
from zeus.nucleo import Zeus
from zeus.persona import Persona
from zeus.store import Store
from zeus.telemetria import Medida, Telemetria, estatisticas_do_ollama, resumir

SEGREDO = "rua-das-palmeiras-42"


class RelogioManual:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def andar(self, segundos):
        self.t += segundos


def chamada(nome, **argumentos):
    return {"id": nome, "nome": nome, "argumentos": argumentos}


class EstatisticasDoProvedor(unittest.TestCase):
    def test_duracoes_viram_ms_e_ausentes_ficam_nulos(self):
        estat = estatisticas_do_ollama({"prompt_eval_count": 2400,
                                        "prompt_eval_duration": 1_500_000_000,
                                        "eval_count": 30})
        self.assertEqual(estat["prompt_eval_count"], 2400)
        self.assertEqual(estat["prompt_eval_ms"], 1500.0)
        self.assertEqual(estat["eval_count"], 30)
        # O servidor não mandou: fica None, nunca zero.
        self.assertIsNone(estat["eval_ms"])
        self.assertIsNone(estat["load_ms"])

    def test_ollama_sem_fluxo_tambem_preserva_as_estatisticas(self):
        def transporte(metodo, url, corpo=None, cabecalhos=None, timeout=None):
            return {"model": "m", "message": {"content": "oi"},
                    "prompt_eval_count": 10, "prompt_eval_duration": 2_000_000,
                    "load_duration": 5_000_000}
        resposta = ProvedorOllama("http://x", "m", transporte).conversar([])
        self.assertEqual(resposta.medidas[0]["provedor"], "ollama")
        self.assertFalse(resposta.medidas[0]["fluxo"])
        self.assertEqual(resposta.medidas[0]["prompt_eval_ms"], 2.0)
        self.assertEqual(resposta.medidas[0]["load_ms"], 5.0)

    def test_openrouter_so_informa_contagens(self):
        def transporte(metodo, url, corpo=None, cabecalhos=None, timeout=None):
            return {"model": "r", "choices": [{"message": {"content": "oi"}}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 4}}
        resposta = ProvedorOpenRouter("http://x", "r", "k", transporte).conversar([])
        self.assertEqual(resposta.medidas[0]["prompt_eval_count"], 50)
        self.assertIsNone(resposta.medidas[0]["prompt_eval_ms"])

    def test_hibrido_nao_esconde_a_decisao_local_descartada(self):
        local = ProvedorFalso([Resposta("rascunho local", [], "l",
                                        medidas=[{"provedor": "ollama", "eval_count": 80}])])
        remoto = ProvedorFalso([Resposta("resposta remota", [], "r",
                                         medidas=[{"provedor": "openrouter", "eval_count": 9}])])
        hibrido = ProvedorHibrido(local, remoto)
        resposta = hibrido.conversar([{"role": "user", "content": "oi"}],
                                     ferramentas=[{"x": 1}])
        self.assertEqual([m["provedor"] for m in resposta.medidas], ["ollama", "openrouter"])


class MedidaDoTurno(unittest.TestCase):
    def test_fila_e_etapas_usam_relogio_monotonico(self):
        relogio = RelogioManual()
        etapas = []
        medida = Medida(canal="hud", recebido_em=relogio(), relogio=relogio,
                        ao_mudar=lambda e, d, ms: etapas.append((e, ms)))
        relogio.andar(0.25)
        medida.inicio = relogio()
        medida.etapa("montando_contexto")
        relogio.andar(0.5)
        medida.concluir("concluida")
        linha = medida.como_linha()
        self.assertEqual(linha["espera_fila_ms"], 250.0)
        self.assertEqual(linha["total_ms"], 500.0)
        self.assertEqual(etapas, [("montando_contexto", 250.0), ("concluida", 750.0)])

    def test_sem_carimbo_de_chegada_a_espera_e_nula_com_motivo(self):
        linha = Medida().como_linha()
        self.assertIsNone(linha["espera_fila_ms"])
        self.assertIn("espera_fila_ms", linha["ausentes"])


class ConversaMedida(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.store.remember("endereco", SEGREDO, "user")
        self.relogio = Relogio(em(2026, 9, 23, 20))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def zeus(self, roteiro):
        provedor = ProvedorFalso(roteiro)
        return Zeus(self.store, provedor, Persona.carregar("config/persona.md"),
                    Ferramentas(self.store, relogio=self.relogio), config_de_teste(),
                    relogio=self.relogio)

    def test_rodadas_ferramentas_e_estatisticas_ficam_na_medida(self):
        zeus = self.zeus([
            Resposta("", [chamada("consultar_fato", chave="endereco")], "modelo-falso",
                     medidas=[{"provedor": "ollama", "prompt_eval_count": 1900}]),
            Resposta("Está na memória.", [], "modelo-falso",
                     medidas=[{"provedor": "ollama", "prompt_eval_count": 60}]),
        ])
        medida = Medida(canal="hud")
        zeus.conversar(f"qual é meu endereço? {SEGREDO}", canal="hud", medida=medida)
        linha = medida.como_linha()
        self.assertEqual(linha["resultado"], "concluida")
        self.assertEqual(len(linha["rodadas"]), 2)
        self.assertEqual(linha["rodadas"][0]["chamadas"], ["consultar_fato"])
        self.assertEqual(linha["rodadas"][0]["servidor"][0]["prompt_eval_count"], 1900)
        self.assertEqual(linha["ferramentas"][0]["nome"], "consultar_fato")
        self.assertEqual(linha["ferramentas"][0]["efeito"], "nenhum")
        self.assertGreaterEqual(linha["contexto"]["fatos"], 1)
        self.assertIsNotNone(linha["contexto_ms"])

    def test_nenhum_texto_de_conversa_chega_a_medida_nem_ao_arquivo(self):
        zeus = self.zeus([
            Resposta("", [chamada("lembrar_fato", chave="cor", valor=SEGREDO)], "modelo-falso"),
            Resposta(f"Guardei {SEGREDO}.", [], "modelo-falso"),
        ])
        medida = Medida(canal="hud")
        zeus.conversar(f"guarda isto: {SEGREDO}", canal="hud", medida=medida)
        with tempfile.TemporaryDirectory() as pasta:
            telemetria = Telemetria(pasta, gravar=True)
            telemetria.registrar(medida.como_linha())
            arquivos = list((Path(pasta) / "medidas").glob("*.jsonl"))
            self.assertEqual(len(arquivos), 1)
            conteudo = arquivos[0].read_text(encoding="utf-8")
            self.assertEqual(oct(arquivos[0].stat().st_mode & 0o777), "0o600")
        self.assertNotIn(SEGREDO, conteudo)
        self.assertNotIn("guarda isto", conteudo)
        self.assertNotIn("Guardei", conteudo)
        self.assertNotIn('"cor"', conteudo)

    def test_falha_do_modelo_fica_registrada_como_falhou(self):
        class Quebrado(ProvedorFalso):
            def conversar(self, mensagens, ferramentas=None, temperatura=0.0):
                raise RuntimeError("caiu")
        zeus = Zeus(self.store, Quebrado([]), Persona.carregar("config/persona.md"),
                    Ferramentas(self.store), config_de_teste(), relogio=self.relogio)
        medida = Medida()
        with self.assertRaises(RuntimeError):
            zeus.conversar("oi", medida=medida)
        linha = medida.como_linha()
        self.assertEqual(linha["resultado"], "falhou")
        self.assertEqual(linha["erro"], "RuntimeError")
        self.assertEqual(linha["rodadas"][0]["erro"], "RuntimeError")


class FilaEVoz(unittest.TestCase):
    def test_caixa_de_entrada_carimba_a_chegada(self):
        caixa = CaixaDeEntrada()
        caixa.put_nowait({"tipo": "texto", "texto": "oi"})
        self.assertIsInstance(caixa.get_nowait()["recebido_em"], float)

    def test_sintese_mede_tempo_sem_guardar_o_texto(self):
        import threading
        from types import SimpleNamespace
        medidas, pronto = [], threading.Event()

        def medir(linha):
            medidas.append(linha)
            pronto.set()
        fala = FalaEmSegundoPlano(SimpleNamespace(falar=lambda t: Path("a.wav")),
                                  lambda *a, **k: None, ao_medir=medir)
        try:
            fala.falar(SEGREDO, fala.invalidar(), "t1")
            self.assertTrue(pronto.wait(2))
        finally:
            fala.parar()
        self.assertEqual(medidas[0]["turno"], "t1")
        self.assertEqual(medidas[0]["caracteres"], len(SEGREDO))
        self.assertNotIn(SEGREDO, json.dumps(medidas[0]))


class Resumo(unittest.TestCase):
    def test_p50_p95_declaram_amostra_e_ausentes(self):
        linhas = [{"tipo": "turno", "total_ms": v, "espera_fila_ms": None,
                   "rodadas": [{"servidor": [{"prompt_eval_count": v}]}], "resultado": "concluida"}
                  for v in (100, 200, 300, 400)]
        resumo = resumir(linhas)
        self.assertEqual(resumo["turnos"], 4)
        self.assertEqual(resumo["campos"]["total_ms"]["n"], 4)
        self.assertEqual(resumo["campos"]["total_ms"]["p50"], 300)
        self.assertEqual(resumo["campos"]["espera_fila_ms"]["ausentes"], 4)
        self.assertIsNone(resumo["campos"]["espera_fila_ms"]["p50"])


if __name__ == "__main__":
    unittest.main()
