import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from zeus.execucao import CaixaDeEntrada, FalaEmSegundoPlano, RecepcaoTelegram
from zeus.voz import Voz


class ExecucaoConcorrente(unittest.TestCase):
    def test_entrada_acorda_sem_esperar_intervalo(self):
        entrada = CaixaDeEntrada()
        terminou = threading.Event()
        thread = threading.Thread(target=lambda: (entrada.aguardar(10), terminou.set()))
        thread.start()
        entrada.put_nowait({'tipo': 'texto'})
        self.assertTrue(terminou.wait(1))
        thread.join(1)
        self.assertEqual(entrada.get_nowait()['tipo'], 'texto')

    def test_polling_lento_nao_bloqueia_hud_e_so_repete_apos_confirmacao(self):
        entrada, parado, liberar = CaixaDeEntrada(), threading.Event(), threading.Event()
        iniciou, segunda = threading.Event(), threading.Event()
        chamadas = []
        criadores = []
        store = Mock()
        def receber():
            chamadas.append(1)
            if len(chamadas) == 1:
                iniciou.set()
                liberar.wait(2)
                return [{'id': 1, 'texto': 'oi'}]
            segunda.set()
            parado.wait(2)
            return []
        def criar():
            criadores.append(threading.get_ident())
            return SimpleNamespace(receber=receber, store=store)
        receptor = RecepcaoTelegram(criar, entrada, parado)
        receptor.iniciar()
        try:
            self.assertTrue(iniciou.wait(1))
            entrada.put_nowait({'tipo': 'texto', 'texto': 'HUD continua'})
            self.assertEqual(entrada.get(timeout=1)['tipo'], 'texto')
            liberar.set()
            lote = entrada.get(timeout=1)
            self.assertFalse(segunda.wait(0.05))
            lote['terminado'].set()
            self.assertTrue(segunda.wait(1))
        finally:
            liberar.set()
            parado.set()
            receptor.thread.join(2)
        self.assertNotEqual(criadores[0], threading.get_ident())
        store.close.assert_called_once()

    def test_receptor_tem_store_proprio_e_le_offset_confirmado_pelo_nucleo(self):
        from zeus.store import Store
        from zeus.canais.telegram import CanalTelegram
        with tempfile.TemporaryDirectory() as temp:
            dono = Store(Path(temp))
            self.addCleanup(dono.close)
            entrada, parado, leu = CaixaDeEntrada(), threading.Event(), threading.Event()
            offsets = []
            def transporte(metodo, url, corpo, cabecalhos, timeout):
                offsets.append(corpo.get('offset'))
                if len(offsets) == 1:
                    return {'ok': True, 'result': [{'update_id': 41,
                        'message': {'chat': {'id': 1}, 'text': 'oi'}}]}
                leu.set()
                parado.wait(1)
                return {'ok': True, 'result': []}
            receptor = RecepcaoTelegram(lambda: CanalTelegram(
                'teste', '1', Store(Path(temp)), transporte), entrada, parado)
            receptor.iniciar()
            try:
                lote = entrada.get(timeout=2)
                CanalTelegram('teste', '1', dono).confirmar(41)
                lote['terminado'].set()
                self.assertTrue(leu.wait(1))
                self.assertEqual(offsets[:2], [None, 42])
            finally:
                parado.set()
                receptor.thread.join(2)

    def test_fala_lenta_nao_bloqueia_e_resposta_antiga_e_descartada(self):
        iniciou, liberar, terminou = threading.Event(), threading.Event(), threading.Event()
        def sintetizar(texto):
            if texto == 'antiga':
                iniciou.set()
                liberar.wait(2)
            return Path(texto + '.wav')
        publicados = []
        def publicar(tipo, **campos):
            publicados.append((tipo, campos))
            terminou.set()
        fala = FalaEmSegundoPlano(SimpleNamespace(falar=sintetizar), publicar)
        try:
            antiga = fala.invalidar()
            fala.falar('antiga', antiga)
            self.assertTrue(iniciou.wait(1))
            atual = fala.invalidar()
            fala.falar('nova', atual)
            liberar.set()
            self.assertTrue(terminou.wait(1))
            self.assertEqual(publicados, [('audio', {'audio': '/audio/nova.wav', 'geracao': atual})])
        finally:
            liberar.set()
            fala.parar()

    def test_cache_de_voz_so_aparece_depois_de_arquivo_completo(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            modelo = pasta / 'pt.onnx'
            modelo.write_bytes(b'modelo')
            voz = Voz(modelo=str(modelo), destino=pasta / 'audios')
            voz.binario = 'piper-falso'
            def sintetizar(args, **kwargs):
                alvo = Path(args[-1])
                self.assertFalse(any(p.name != alvo.name for p in voz.destino.glob('*.wav')))
                alvo.write_bytes(b'RIFF' + b'0' * 100)
            with patch('zeus.voz.subprocess.run', side_effect=sintetizar) as chamada:
                arquivo = voz.falar('olá')
                self.assertEqual(arquivo, voz.falar('olá'))
                self.assertEqual(chamada.call_count, 1)
                self.assertEqual(list(voz.destino.iterdir()), [arquivo])

    def test_falha_de_sintese_nao_deixa_wav_incompleto(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            modelo = pasta / 'pt.onnx'
            modelo.write_bytes(b'modelo')
            voz = Voz(modelo=str(modelo), destino=pasta / 'audios')
            voz.binario = 'piper-falso'
            with patch('zeus.voz.subprocess.run', side_effect=OSError('falha')):
                self.assertIsNone(voz.falar('olá'))
            self.assertEqual(list(voz.destino.iterdir()), [])

class CicloIntegrado(unittest.TestCase):
    def test_texto_chega_antes_de_sintese_e_capacidades_chegam_ao_modelo(self):
        from test_conversa import montar
        from zeus.__main__ import executar
        from zeus.llm import Resposta
        with tempfile.TemporaryDirectory() as temp:
            store, provedor, zeus = montar(temp, [Resposta('Bom treino, senhor.', [], 'm')])
            self.addCleanup(store.close)
            zeus.canal = None
            zeus.config.hud_tls = False
            stopped = threading.Event()
            final = threading.Event()
            ordem = []
            pacotes = []
            class HudFalsa:
                def __init__(self, enfileirar, **kwargs):
                    self.enfileirar = enfileirar
                    self.seguro = False
                def iniciar(self):
                    self.enfileirar({'tipo': 'texto', 'texto': 'indo treinar'})
                    return 8770
                def publicar(self, tipo, **campos):
                    pacotes.append((tipo, campos))
                    if tipo == 'mensagem' and campos.get('de') == 'zeus':
                        ordem.append('texto')
                        final.set()
                def estado(self):
                    return {}
                def atualizar(self, *_, **__):
                    pass
                def parar(self):
                    pass
            def sintetizar(_):
                ordem.append('audio')
                stopped.set()
                return None
            voz = SimpleNamespace(disponivel=lambda: True, diagnostico=lambda: 'pronta', falar=sintetizar)
            ouvidos = SimpleNamespace(disponivel=lambda: True, diagnostico=lambda: 'pronta', destino=Path(temp))
            watchdog = threading.Timer(3, stopped.set)
            watchdog.start()
            try:
                with patch('zeus.__main__.Event', return_value=stopped), \
                     patch('zeus.__main__.signal.signal'), \
                     patch('zeus.__main__.ligar_modelo', return_value='m'), \
                     patch('zeus.__main__.montar_voz', return_value=voz), \
                     patch('zeus.__main__.montar_ouvidos', return_value=ouvidos), \
                     patch('zeus.__main__.emit'), \
                     patch('zeus.hud.endereco_local', return_value='127.0.0.1'), \
                     patch('zeus.hud.ServidorHUD', HudFalsa):
                    self.assertEqual(executar(zeus, store, zeus.config), 0)
            finally:
                watchdog.cancel()
            self.assertEqual(ordem, ['texto', 'audio'])
            self.assertTrue(final.is_set())
            self.assertIn('Voz local disponível', provedor.recebidas[0][-2]['content'])
