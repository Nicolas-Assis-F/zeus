import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from apoio import Relogio, em, config_de_teste, transporte_roteirizado
from zeus.canais import CanalMemoria, CanalTelegram
from zeus.entregas import Entregas, NaoEnviado
from zeus.execucao import SupervisorPresenca, InstanciaUnica
from zeus.store import Store, MIGRACOES


class FilaDuravel(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.addCleanup(lambda: self.store.close())
        self.fila = Entregas(self.store)
        self.agora = em(2026, 9, 19, 20)
        self.canal = CanalMemoria()

    def agendar(self, quando=None):
        self.store.agendar('lembrete', 'água', quando or self.agora)
        self.fila.registrar_agenda('memoria', self.agora)

    def enviar(self):
        return self.fila.enviar_pendentes({'memoria': self.canal}, self.agora)

    def test_pendente_resiste_reinicio_e_entrega_uma_vez(self):
        self.agendar()
        self.store.close()
        self.store = Store(Path(self.temp.name))
        self.fila = Entregas(self.store)
        self.fila.recuperar(self.agora)
        self.assertEqual(len(self.enviar()), 1)
        self.assertEqual(self.enviar(), [])
        self.assertEqual(self.canal.enviados, ['água'])
        self.assertEqual(self.store.agenda_pendente(), [])
        self.assertEqual(len(self.store.turnos()), 1)

    def test_envio_ambiguo_nao_repete_sem_decisao(self):
        self.agendar()
        def aceitou_sem_recibo(texto):
            self.canal.enviados.append(texto)
            raise TimeoutError('resposta perdida')
        self.canal.enviar = aceitou_sem_recibo
        self.assertEqual(self.enviar(), [])
        self.assertEqual(self.fila.listar()[0]['situacao'], 'incerta')
        self.assertEqual(self.enviar(), [])
        self.fila.resolver('lembrete:1', 'confirmar', self.agora)
        self.assertEqual(self.store.agenda_pendente(), [])
        self.assertEqual(self.canal.enviados, ['água'])

    def test_crash_em_envio_se_torna_incerto_na_recuperacao(self):
        self.agendar()
        with self.store.connection:
            self.store.connection.execute("UPDATE saidas SET situacao='em_envio'")
        self.fila.recuperar(self.agora)
        self.assertEqual(self.enviar(), [])
        self.fila.resolver('lembrete:1', 'reenviar', self.agora)
        self.assertEqual(len(self.enviar()), 1)

    def test_falha_certa_tem_backoff_e_limite(self):
        self.agendar()
        self.canal.falhar = True
        self.enviar()
        self.enviar()
        self.assertEqual(self.fila.listar()[0]['tentativas'], 1)
        self.agora += timedelta(seconds=31)
        self.enviar()
        self.agora += timedelta(seconds=61)
        self.enviar()
        self.assertEqual(self.fila.listar()[0]['situacao'], 'falhou')
        self.agora += timedelta(days=1)
        self.enviar()
        self.assertEqual(self.fila.listar()[0]['tentativas'], 3)

    def test_cancelar_ou_expirar_nao_envia_aviso_antigo(self):
        self.agendar(self.agora-timedelta(days=2))
        self.assertEqual(self.enviar(), [])
        self.assertEqual(self.fila.listar()[0]['situacao'], 'expirada')
        self.fila.resolver('lembrete:1', 'reenviar', self.agora)
        self.store.cancelar_agenda(1)
        self.assertEqual(self.enviar(), [])
        self.assertEqual(self.fila.listar()[0]['situacao'], 'cancelada')

    def test_marca_legada_nao_e_falsa_confirmacao(self):
        self.store.agendar('lembrete', 'água', self.agora)
        self.store.marcar_envio('lembrete:1', self.agora)
        self.fila.registrar_agenda('memoria', self.agora)
        self.assertEqual(self.fila.listar()[0]['situacao'], 'incerta')
        self.assertEqual(self.enviar(), [])

    def test_respostas_persistem_sem_gerar_de_novo_apos_falha(self):
        atualizacoes = {'ok': True, 'result': [
            {'update_id': 41, 'message': {'chat': {'id': 7}, 'text': 'oi'}},
            {'update_id': 42, 'message': {'chat': {'id': 999}, 'text': 'ignorar'}}]}
        canal = CanalTelegram('token', '7', self.store,
                               transporte_roteirizado([('getUpdates', atualizacoes)]))
        mensagens = canal.receber(0)
        self.assertEqual(self.store.kv_get('telegram_offset'), '43')
        # Válida fica no disco mesmo com o offset após a ignorada.
        outro = CanalTelegram('token', '7', self.store, Mock(side_effect=AssertionError('não buscar')))
        self.assertEqual(outro.receber(), mensagens)
        chave = self.fila.iniciar_resposta(mensagens)
        self.assertIsNone(self.fila.iniciar_resposta(mensagens))
        self.fila.concluir_resposta(chave, 'Opa, senhor.', self.agora)
        self.assertEqual(self.fila.entradas(), [])
        self.assertEqual(self.fila.listar()[0]['texto'], 'Opa, senhor.')

    def _entrada(self, identificador=1):
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO entradas (id,texto,recebida_em) VALUES (?,'oi','agora')", (identificador,))
        return [{'id': identificador, 'texto': 'oi'}]

    def test_crash_com_efeito_iniciado_pede_revisao_para_nao_repetir_ferramenta(self):
        mensagens = self._entrada()
        chave = self.fila.iniciar_resposta(mensagens)
        # A intenção do efeito foi registrada antes de a ferramenta rodar.
        self.store.abrir_episodio('efeitos_do_turno', 'turno:' + chave)
        self.fila.recuperar()
        self.assertIsNone(self.fila.iniciar_resposta(mensagens))
        self.assertEqual(self.fila.entradas()[0]['situacao'], 'incerta')
        self.fila.resolver_entrada(1, 'reprocessar')
        self.assertEqual(self.fila.iniciar_resposta(mensagens), chave)

    def test_crash_sem_efeito_volta_para_a_fila_sozinho(self):
        """Nada com efeito começou: responder de novo é seguro, e deixar a
        mensagem parada esperando a CLI era deixar Nicolas sem resposta."""
        mensagens = self._entrada()
        chave = self.fila.iniciar_resposta(mensagens)
        self.fila.recuperar()
        self.assertEqual(self.fila.iniciar_resposta(mensagens), chave)

    def test_entrada_de_versao_antiga_sem_rastro_continua_incerta(self):
        mensagens = self._entrada()
        chave = self.fila.iniciar_resposta(mensagens)
        with self.store.connection:
            self.store.connection.execute("DELETE FROM kv WHERE chave=?",
                                          ('efeitos_rastreados:' + chave,))
        self.fila.recuperar()
        self.assertEqual(self.fila.entradas()[0]['situacao'], 'incerta')

    def test_falha_sem_efeito_reprocessa_no_maximo_duas_vezes(self):
        mensagens = self._entrada()
        for esperado in ('pendente', 'pendente', 'incerta'):
            chave = self.fila.iniciar_resposta(mensagens)
            self.assertEqual(self.fila.resposta_interrompida(chave, False), esperado)

    def test_falha_com_efeito_fica_incerta_na_primeira(self):
        chave = self.fila.iniciar_resposta(self._entrada())
        self.assertEqual(self.fila.resposta_interrompida(chave, True), 'incerta')

    def test_responder_no_telegram_vincula_a_pergunta_pelo_recibo(self):
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO saidas (chave,canal,tipo,referencia,texto,situacao,criada_em,"
                "atualizada_em,tentar_em,recibo) VALUES ('pergunta:7','telegram','pergunta',7,"
                "'Quer que eu lembre?','enviada','a','a','a','{\"message_id\": 555}')")
        transporte = Mock(return_value={'ok': True, 'result': [
            {'update_id': 90, 'message': {'chat': {'id': 7}, 'text': 'sim',
                                          'reply_to_message': {'message_id': 555}}},
            {'update_id': 91, 'message': {'chat': {'id': 7}, 'text': 'e outra coisa'}}]})
        mensagens = CanalTelegram('token', '7', self.store, transporte).receber(0)
        self.assertEqual(self.fila.pergunta_respondida(mensagens), 7)
        self.assertIsNone(self.fila.pergunta_respondida([m for m in mensagens if m['id'] == 91]))

    def test_canal_ausente_nao_bloqueia_as_outras_saidas(self):
        for i in range(10):
            self.fila.preparar(str(i), 'ausente', 'x', agora=self.agora)
        self.agendar()
        self.assertEqual(len(self.enviar()), 1)

    def test_queda_apos_envio_antes_de_commit_nao_repete(self):
        self.agendar()
        with patch.object(self.fila, '_concluir', side_effect=sqlite3.OperationalError('disco')):
            with self.assertRaises(sqlite3.OperationalError):
                self.enviar()
        self.assertEqual(self.canal.enviados, ['água'])
        self.fila.recuperar(self.agora)
        self.assertEqual(self.fila.listar()[0]['situacao'], 'incerta')
        self.assertEqual(self.enviar(), [])

    def test_consumidores_concorrentes_so_disparam_uma_vez(self):
        self.agendar()
        barreira = threading.Barrier(2)
        erros = []
        def consumir():
            local = Store(Path(self.temp.name))
            try:
                barreira.wait(timeout=2)
                Entregas(local).enviar_pendentes({'memoria': self.canal}, self.agora)
            except Exception as erro:
                erros.append(erro)
            finally:
                local.close()
        threads = [threading.Thread(target=consumir) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(3)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(erros, [])
        self.assertEqual(self.canal.enviados, ['água'])

    def test_pendencia_antiga_nao_some_da_lista_com_novas_entregas(self):
        self.agendar()
        with self.store.connection:
            self.store.connection.execute("UPDATE saidas SET situacao='incerta'")
        self.agora += timedelta(days=1)
        for i in range(30):
            self.fila.preparar('recente:' + str(i), 'memoria', 'aviso', agora=self.agora)
        self.assertEqual(self.fila.listar(20)[0]['chave'], 'lembrete:1')


class Operacao(unittest.TestCase):
    def test_backup_consistente_inclui_wal_e_nao_sobrescreve(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp)/'estado')
            self.addCleanup(store.close)
            store.remember('teste', 'gravado')
            destino = store.backup(Path(temp)/'copia.sqlite3')
            with sqlite3.connect(destino) as copia:
                self.assertEqual(copia.execute('SELECT value FROM facts').fetchone()[0], 'gravado')
            self.assertEqual(destino.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                store.backup(destino)

    def test_migracao_preserva_dados_e_backup_do_esquema_anterior(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            with sqlite3.connect(pasta/'zeus.sqlite3') as banco:
                for sql in MIGRACOES[:2]:
                    banco.executescript(sql)
                banco.execute('CREATE TABLE schema_version (versao INTEGER NOT NULL)')
                banco.execute('INSERT INTO schema_version VALUES (2)')
                banco.execute("INSERT INTO facts (key,value,source,updated_at) VALUES ('nome','teste','user','agora')")
            store = Store(pasta)
            self.addCleanup(store.close)
            self.assertEqual(store.recall('nome')['value'], 'teste')
            backups = list((pasta/'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups), 1)
            with sqlite3.connect(backups[0]) as copia:
                self.assertEqual(copia.execute('SELECT versao FROM schema_version').fetchone()[0], 2)
                self.assertEqual(copia.execute('SELECT value FROM facts').fetchone()[0], 'teste')

    def test_uma_instancia_por_estado(self):
        with tempfile.TemporaryDirectory() as temp:
            with InstanciaUnica(temp):
                with self.assertRaises(ValueError):
                    with InstanciaUnica(temp):
                        pass
            with InstanciaUnica(temp):
                pass

    def test_agenda_entrega_enquanto_a_conversa_esta_bloqueada(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            self.addCleanup(store.close)
            store.agendar('lembrete', 'água', datetime.now(timezone.utc))
            parado, entregue = threading.Event(), threading.Event()
            class Hud:
                def estado(self): return {}
                def atualizar(self, *_, **__): pass
                def publicar(self, tipo, **campos):
                    if tipo == 'aviso' and campos.get('texto') == 'água': entregue.set()
            supervisor = SupervisorPresenca(Path(temp), config_de_teste(), parado, Hud())
            supervisor.iniciar()
            try:
                # Thread do núcleo não roda tick nem conversa: a agenda é independente.
                self.assertTrue(entregue.wait(2))
                self.assertEqual(store.agenda_pendente(), [])
            finally:
                supervisor.parar()

    def test_migracao_falha_reverte_tabelas_e_versao(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            self.addCleanup(store.close)
            ruim = 'CREATE TABLE parcial (id INTEGER); INSERT INTO inexistente VALUES (1);'
            with patch('zeus.store.MIGRACOES', MIGRACOES + [ruim]):
                with self.assertRaises(sqlite3.OperationalError):
                    store._migrar()
            self.assertEqual(store.connection.execute('SELECT versao FROM schema_version').fetchone()[0], 3)
            self.assertIsNone(store.connection.execute("SELECT name FROM sqlite_master WHERE name='parcial'").fetchone())
