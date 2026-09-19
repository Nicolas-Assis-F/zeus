import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from apoio import em
from zeus.entregas import Entregas
from zeus.percepcao import Evento, MonitorModelo, registrar
from zeus.store import Store


class Percepcao(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.addCleanup(self.store.close)
        self.agora = em(2026,9,19,21)

    def test_evento_tem_origem_validade_episodio_e_deduplicacao(self):
        evento = Evento('id1','teste:fonte','servico','Serviço em teste',self.agora,
                        self.agora+timedelta(minutes=1),simulado=True)
        self.assertTrue(registrar(self.store,evento,agora=self.agora))
        self.assertFalse(registrar(self.store,evento,agora=self.agora))
        self.assertEqual(len(self.store.episodios_abertos()), 1)
        self.assertEqual(len(Entregas(self.store).listar()), 1)
        self.assertTrue(Entregas(self.store).listar()[0]['texto'].startswith('[Simulação]'))

    def test_expirado_e_futuro_nao_viram_evento_atual(self):
        velho = Evento('id1','teste','x','antigo',self.agora-timedelta(hours=2), self.agora-timedelta(hours=1))
        self.assertFalse(registrar(self.store,velho,agora=self.agora))
        futuro = Evento('id2','teste','x','futuro',self.agora+timedelta(hours=2),self.agora+timedelta(hours=3))
        with self.assertRaises(ValueError): registrar(self.store,futuro,agora=self.agora)

    def test_monitor_debounce_recuperacao_e_reinicio_sem_tempestade(self):
        disponivel = [True]
        monitor = MonitorModelo(self.store,lambda:disponivel[0])
        for _ in range(3): monitor.observar(self.agora)
        self.assertEqual(Entregas(self.store).listar(), [])
        disponivel[0] = False
        monitor.observar(self.agora)
        self.assertEqual(Entregas(self.store).listar(), [])
        monitor.observar(self.agora)
        self.assertEqual(len(Entregas(self.store).listar()), 1)
        outro = MonitorModelo(self.store,lambda:disponivel[0])
        for _ in range(5): outro.observar(self.agora)
        self.assertEqual(len(Entregas(self.store).listar()), 1)
        disponivel[0] = True
        for _ in range(3): outro.observar(self.agora+timedelta(seconds=10))
        self.assertEqual(len(Entregas(self.store).listar()), 1)  # cooldown
        outro.observar(self.agora+timedelta(seconds=61))
        self.assertEqual(len(Entregas(self.store).listar()), 2)
