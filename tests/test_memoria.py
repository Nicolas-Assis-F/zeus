import tempfile
import unittest
from datetime import timezone
from pathlib import Path

from apoio import Relogio, em
from zeus.ferramentas import Ferramentas
from zeus.guarda import MemoriaRecusada, parece_financeiro
from zeus.store import Store
from zeus.tempo import MomentoInvalido, interpretar


class CamadasDeMemoria(unittest.TestCase):
    def test_estado_epistemico_e_correcao(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            store.remember("saida_de_casa", "por volta das 7h", "observacao", "hipotese")
            self.assertEqual(store.recall("saida_de_casa")["estado"], "hipotese")
            store.remember("saida_de_casa", "7h10", "nicolas", "confirmado")
            self.assertEqual(store.recall("saida_de_casa")["estado"], "confirmado")
            self.assertEqual([f["key"] for f in store.fatos("confirmado")], ["saida_de_casa"])
            self.assertEqual(store.fatos("hipotese"), [])
            with self.assertRaises(ValueError):
                store.remember("x", "y", "user", "chute")
            store.close()

    def test_episodio_agrupa_eventos_e_fecha(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            episodio = store.abrir_episodio("entrada", "movimento na entrada", simulado=True)
            store.registrar_evento(episodio, "simulado", "pessoa_detectada", {"zona": "portao"})
            self.assertEqual(len(store.episodios_abertos()), 1)
            store.fechar_episodio(episodio, "visita esperada")
            self.assertEqual(store.episodios_abertos(), [])
            store.close()

    def test_migracao_preserva_dados_da_fundacao(self):
        with tempfile.TemporaryDirectory() as temp:
            primeiro = Store(Path(temp))
            primeiro.remember("tratamento", "senhor")
            primeiro.close()
            segundo = Store(Path(temp))
            self.assertEqual(segundo.recall("tratamento")["value"], "senhor")
            self.assertEqual(segundo.recall("tratamento")["estado"], "confirmado")
            segundo.close()


class RegraFinanceira(unittest.TestCase):
    def test_reconhece_valores(self):
        self.assertTrue(parece_financeiro("R$ 1200 na conta"))
        self.assertTrue(parece_financeiro("saldo de 2.340,55"))
        self.assertFalse(parece_financeiro("treino às 19:30"))

    def test_ferramenta_recusa_valor_financeiro(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            ferramentas = Ferramentas(store, Relogio(em(2026, 9, 18, 12)))
            resultado = ferramentas.executar("lembrar_fato",
                                             {"chave": "saldo", "valor": "R$ 4.320,00"})
            self.assertIn("erro", resultado)
            self.assertIsNone(store.recall("saldo"))
            ok = ferramentas.executar("lembrar_fato",
                                      {"chave": "tratamento", "valor": "senhor"})
            self.assertEqual(ok["guardado"], "tratamento")
            store.close()

    def test_guarda_direta_levanta(self):
        with self.assertRaises(MemoriaRecusada):
            from zeus.guarda import checar_memoria
            checar_memoria("gasto", "paguei 300 reais")


class FerramentaDesconhecida(unittest.TestCase):
    def test_nada_fora_do_catalogo_executa(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            ferramentas = Ferramentas(store, Relogio(em(2026, 9, 18, 12)))
            resultado = ferramentas.executar("destrancar_porta", {"porta": "entrada"})
            self.assertIn("erro", resultado)
            self.assertIn("não existe", resultado["erro"])
            store.close()


class Momentos(unittest.TestCase):
    def test_formatos_aceitos(self):
        agora = em(2026, 9, 18, 12)
        self.assertEqual(interpretar("+30m", agora).astimezone(timezone.utc).hour, 12)
        self.assertEqual(interpretar("+2h", agora).astimezone(timezone.utc).hour, 14)
        alvo = interpretar("2026-09-19T07:00:00+00:00", agora)
        self.assertEqual(alvo.day, 19)

    def test_texto_ambiguo_e_recusado(self):
        with self.assertRaises(MomentoInvalido):
            interpretar("mais tarde", em(2026, 9, 18, 12))


if __name__ == "__main__":
    unittest.main()
