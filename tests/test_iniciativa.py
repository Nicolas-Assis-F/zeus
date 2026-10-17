"""Política de interrupção, fila de fala, bordas e escalonamento (#86)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from zeus.iniciativa import (FALAR, GRUPO, QUIETO, RESUMO, Aviso, Bordas, Contexto, Escalonamento,
                             FilaDeFala, decidir, pontuar)

DIA = datetime(2026, 10, 19, 15, 0)
MADRUGADA = datetime(2026, 10, 19, 3, 0)


class Relogio:
    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora


class TestPolitica(unittest.TestCase):
    def test_importante_de_dia_fala_na_sala(self):
        canal, _, _ = decidir(Aviso("x", "t", urgencia=0.8, utilidade=0.9), Contexto(DIA))
        self.assertEqual(canal, FALAR)

    def test_conversando_vai_para_o_grupo_em_vez_de_falar_por_cima(self):
        canal, _, _ = decidir(Aviso("x", "t", urgencia=0.8, utilidade=0.9), Contexto(DIA, conversando=True))
        self.assertEqual(canal, GRUPO)

    # --- quando NÃO falar -------------------------------------------------
    def test_madrugada_nao_acorda_por_coisa_comum(self):
        canal, pontos, _ = decidir(Aviso("x", "t", urgencia=0.6, utilidade=0.8), Contexto(MADRUGADA))
        self.assertIn(canal, (RESUMO, QUIETO))
        self.assertLess(pontos, 0.1)

    def test_trivial_fica_quieto(self):
        self.assertEqual(decidir(Aviso("x", "t", urgencia=0.05, utilidade=0.2), Contexto(DIA))[0], QUIETO)

    def test_nao_perturbe_segura_tudo_que_nao_e_critico(self):
        canal, _, motivo = decidir(Aviso("x", "t", urgencia=0.85, utilidade=1), Contexto(DIA, nao_perturbe=True))
        self.assertEqual((canal, motivo), (RESUMO, "não perturbe"))

    def test_baixa_confianca_nao_interrompe(self):
        canal, _, _ = decidir(Aviso("x", "t", urgencia=0.7, utilidade=0.8, confianca=0.2), Contexto(DIA))
        self.assertIn(canal, (RESUMO, QUIETO))

    def test_muitas_interrupcoes_na_hora_baixam_a_prioridade(self):
        aviso = Aviso("x", "t", urgencia=0.6, utilidade=0.8)
        self.assertGreater(pontuar(aviso, Contexto(DIA)), pontuar(aviso, Contexto(DIA, interrupcoes_ultima_hora=6)))

    def test_feedback_nao_precisava_rebaixa(self):
        aviso = Aviso("x", "t", urgencia=0.75, utilidade=0.8)
        self.assertEqual(decidir(aviso, Contexto(DIA, peso=1.0))[0], FALAR)
        self.assertNotEqual(decidir(aviso, Contexto(DIA, peso=0.3))[0], FALAR)

    # --- o crítico passa -----------------------------------------------
    def test_critico_fura_madrugada_e_nao_perturbe(self):
        canal, _, _ = decidir(Aviso("x", "t", urgencia=0.95, utilidade=1), Contexto(MADRUGADA, nao_perturbe=True))
        self.assertEqual(canal, FALAR)

    def test_sem_sala_usa_o_grupo(self):
        self.assertEqual(decidir(Aviso("x", "t", urgencia=0.8, utilidade=0.9), Contexto(DIA, sala=False))[0], GRUPO)


class TestFilaDeFala(unittest.TestCase):
    def test_prioridade_e_ordem(self):
        ditos = []
        fila = FilaDeFala(ditos.append)
        fila.por("baixa", 0.2); fila.por("alta", 0.9); fila.por("media", 0.5); fila.por("alta 2", 0.9)
        while fila.rodar_uma():
            pass
        self.assertEqual(ditos, ["alta", "alta 2", "media", "baixa"])

    def test_espera_a_sala_livre_mas_critico_passa(self):
        ditos, livre, np = [], [False], [True]
        fila = FilaDeFala(ditos.append, pode_falar=lambda: livre[0], nao_perturbe=lambda: np[0])
        fila.por("comum", 0.6)
        self.assertIsNone(fila.rodar_uma())
        fila.por("crítico", 1.0, critico=True)
        self.assertEqual(fila.rodar_uma(), "crítico")
        self.assertIsNone(fila.rodar_uma())   # o comum ainda espera
        livre[0], np[0] = True, False
        self.assertEqual(fila.rodar_uma(), "comum")

    def test_mesma_chave_nao_entra_duas_vezes(self):
        fila = FilaDeFala(lambda t: None)
        self.assertTrue(fila.por("a", chave="k"))
        self.assertFalse(fila.por("a de novo", chave="k"))


class TestBordas(unittest.TestCase):
    def test_dispara_na_transicao_e_rearma_depois(self):
        relogio = Relogio()
        b = Bordas(Path(tempfile.mkdtemp()) / "b.json", rearme_s=300, relogio=relogio)
        self.assertTrue(b.observar("cpu", True))
        self.assertFalse(b.observar("cpu", True))     # continua alto: não repete
        b.observar("cpu", False); relogio.agora += 100
        b.observar("cpu", False)
        self.assertFalse(b.observar("cpu", True))     # voltou cedo demais: não rearmou
        b.observar("cpu", False); relogio.agora += 301
        b.observar("cpu", False)
        self.assertTrue(b.observar("cpu", True))

    def test_sobrevive_a_reinicio(self):
        arquivo = Path(tempfile.mkdtemp()) / "b.json"
        self.assertTrue(Bordas(arquivo).observar("prazo:1", True))
        self.assertFalse(Bordas(arquivo).observar("prazo:1", True))


class TestEscalonamento(unittest.TestCase):
    def test_sobe_de_canal_e_para_quando_ele_responde(self):
        relogio, entregas = Relogio(), []
        e = Escalonamento(lambda canal, aviso: entregas.append(canal), relogio=relogio)
        e.abrir(Aviso("aprovacao:1", "preciso de você", escalar=True))
        self.assertEqual(entregas, ["sala"])
        relogio.agora += 300; e.rodar()
        self.assertEqual(entregas, ["sala"])
        relogio.agora += 301; e.rodar()
        self.assertEqual(entregas, ["sala", "grupo"])
        self.assertEqual(e.respondeu(), ["aprovacao:1"])
        relogio.agora += 3600; e.rodar()
        self.assertEqual(entregas, ["sala", "grupo"])   # cancelado: não repetiu

    def test_maximo_tres_degraus(self):
        relogio, entregas = Relogio(), []
        e = Escalonamento(lambda canal, aviso: entregas.append(canal), relogio=relogio)
        e.abrir(Aviso("k", "t", escalar=True))
        for _ in range(10):
            relogio.agora += 1000; e.rodar()
        self.assertEqual(entregas, ["sala", "grupo", "grupo_urgente"])
        self.assertEqual(e.abertos(), [])

    def test_comecar_no_grupo(self):
        relogio, entregas = Relogio(), []
        e = Escalonamento(lambda canal, aviso: entregas.append(canal), relogio=relogio)
        e.abrir(Aviso("k", "t", escalar=True), comecar_em="grupo")
        relogio.agora += 1200; e.rodar()
        self.assertEqual(entregas, ["grupo", "grupo_urgente"])


if __name__ == "__main__":
    unittest.main()
