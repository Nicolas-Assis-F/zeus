import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from zeus.ouvidos import Ouvidos


class EscutaLocal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        self.motor = Mock()
        self.motor.transcribe.return_value = (
            iter([SimpleNamespace(text=' Bom treino. ')]), SimpleNamespace(duration=2.5))
        self.modulo = SimpleNamespace(WhisperModel=Mock(return_value=self.motor))
        self.substituicao = patch.dict(sys.modules, {'faster_whisper': self.modulo})
        self.substituicao.start()
        self.addCleanup(self.substituicao.stop)
        self.ouvidos = Ouvidos(destino=self.pasta, vocabulario='Zeus, Nicolas')

    def audio(self):
        arquivo = self.pasta / 'gravacao.webm'
        arquivo.write_bytes(b'pequeno mas valido para o decoder falso')
        return arquivo

    def test_carrega_uma_vez_cpu_e_aplica_filtro_e_vocabulario(self):
        for _ in range(2):
            self.motor.transcribe.return_value = (iter([SimpleNamespace(text='Bom treino.')]),
                                                   SimpleNamespace(duration=2.5))
            arquivo = self.audio()
            self.assertEqual(self.ouvidos.transcrever(arquivo), 'Bom treino.')
            self.assertFalse(arquivo.exists())
        self.modulo.WhisperModel.assert_called_once_with('small', device='cpu',
                                                        compute_type='int8', cpu_threads=4)
        opcoes = self.motor.transcribe.call_args.kwargs
        self.assertTrue(opcoes['vad_filter'])
        self.assertEqual(opcoes['language'], 'pt')
        self.assertFalse(opcoes['condition_on_previous_text'])
        self.assertEqual(opcoes['initial_prompt'], 'Zeus, Nicolas')
        self.assertEqual(self.ouvidos.ultima_medicao['audio_s'], 2.5)

    def test_falha_de_audio_nao_desliga_escuta_e_limpa_arquivo(self):
        self.motor.transcribe.side_effect = ValueError('formato inválido')
        arquivo = self.audio()
        self.assertEqual(self.ouvidos.transcrever(arquivo), '')
        self.assertFalse(arquivo.exists())
        self.assertTrue(self.ouvidos.disponivel())
        self.motor.transcribe.side_effect = None
        self.assertEqual(self.ouvidos.transcrever(self.audio()), 'Bom treino.')
        self.assertNotIn('falhou', self.ouvidos.diagnostico())

    def test_falha_de_carga_pode_ser_repetida_sem_reiniciar(self):
        self.modulo.WhisperModel.side_effect = [RuntimeError('download indisponível'), self.motor]
        arquivo = self.audio()
        self.assertEqual(self.ouvidos.transcrever(arquivo), '')
        self.assertFalse(arquivo.exists())
        self.assertEqual(self.ouvidos.transcrever(self.audio()), 'Bom treino.')

    def test_audio_longo_nao_consume_gerador(self):
        def proibido():
            raise AssertionError('não deve iniciar geração')
            yield
        self.motor.transcribe.return_value = (proibido(), SimpleNamespace(duration=100))
        self.assertEqual(self.ouvidos.transcrever(self.audio()), '')
        self.assertIn('excede', self.ouvidos.diagnostico())

    def test_silencio_nao_inventa_texto_e_medicao_preserva_original(self):
        self.motor.transcribe.return_value = (iter([]), SimpleNamespace(duration=2))
        arquivo = self.audio()
        self.assertEqual(self.ouvidos.transcrever(arquivo, remover=False), '')
        self.assertTrue(arquivo.exists())
        self.assertFalse(self.ouvidos.ultima_medicao['com_fala'])

    def test_vazio_e_dependencia_ausente_nao_deixam_gravacao(self):
        arquivo = self.audio()
        arquivo.write_bytes(b'')
        self.ouvidos.transcrever(arquivo)
        self.assertFalse(arquivo.exists())
        with patch.dict(sys.modules, {'faster_whisper': None}):
            arquivo = self.audio()
            self.ouvidos.transcrever(arquivo)
            self.assertFalse(arquivo.exists())
            self.assertFalse(self.ouvidos.disponivel())
