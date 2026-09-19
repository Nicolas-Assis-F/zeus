import tempfile
import unittest

from test_conversa import montar
from test_fluxo import fluxo_falso
from zeus.llm import ErroDeModelo, ProvedorOllama, ProvedorOpenRouter, ProvedorHibrido, Resposta
from zeus.persona import Persona


class Contexto(unittest.TestCase):
    def test_turno_atual_aparece_uma_vez_e_memoria_e_persona_permanecem(self):
        with tempfile.TemporaryDirectory() as temp:
            store, provedor, zeus = montar(temp, [Resposta('Bom treino!', [], 'm')])
            self.addCleanup(store.close)
            store.remember('treino', 'academia', 'user')
            zeus.capacidades = {'voz': True, 'ouvidos': True}
            zeus.conversar('Vou treinar agora, Zeus!')
            mensagens = provedor.recebidas[0]
            self.assertEqual(sum(m['content'] == 'Vou treinar agora, Zeus!' for m in mensagens), 1)
            self.assertIn('academia', mensagens[-2]['content'])
            self.assertIn('Voz local disponível', mensagens[-2]['content'])
            self.assertNotIn('Sem voz disponível', mensagens[-2]['content'])
            self.assertFalse(any(l.startswith('- Nicolas:') for l in mensagens[0]['content'].splitlines()))
            self.assertEqual(len(store.turnos()), 2)

    def test_prefixo_de_persona_e_exemplos_nao_muda_com_o_relogio(self):
        with tempfile.TemporaryDirectory() as temp:
            store, _, zeus = montar(temp, [])
            self.addCleanup(store.close)
            antes = zeus._historico()
            zeus.relogio.avancar(minutes=2)
            depois = zeus._historico()
            self.assertEqual(antes[:-1], depois[:-1])
            self.assertNotEqual(antes[-1], depois[-1])


class FluxosVerificados(unittest.TestCase):
    def provedores(self):
        return [ProvedorOllama('http://teste', 'zeus'),
                ProvedorOpenRouter('http://teste', 'zeus', 'teste')]

    def pacote(self, provedor, texto, **extra):
        if isinstance(provedor, ProvedorOllama):
            return {'model': 'zeus', 'message': {'content': texto}, **extra}
        return {'model': 'zeus', 'choices': [{'delta': {'content': texto}}], **extra}

    def test_troca_de_modelo_e_recusada_antes_de_expor_o_fragmento(self):
        for provedor in self.provedores():
            with self.subTest(provedor=provedor.nome):
                vistos = []
                provedor.transporte_de_fluxo = fluxo_falso([
                    self.pacote(provedor, 'início'),
                    self.pacote(provedor, 'não mostrar', model='errado')])
                with self.assertRaises(ErroDeModelo):
                    provedor.conversar_em_fluxo([], ao_receber=vistos.append)
                self.assertEqual(vistos, ['início'])

    def test_sem_modelo_sem_conclusao_ou_com_erro_nao_vira_sucesso(self):
        for provedor in self.provedores():
            for pacotes in ([], [{'error': 'falha'}],
                            [self.pacote(provedor, 'parcial')],
                            [self.pacote(provedor, 'texto', model='')]):
                with self.subTest(provedor=provedor.nome, pacotes=pacotes):
                    provedor.transporte_de_fluxo = fluxo_falso(pacotes)
                    with self.assertRaises(ErroDeModelo):
                        provedor.conversar_em_fluxo([])

    def test_ferramenta_openrouter_montada_de_fragmentos(self):
        provedor = self.provedores()[1]
        provedor.transporte_de_fluxo = fluxo_falso([
            {'model': 'zeus', 'choices': [{'delta': {'tool_calls': [
                {'index': 0, 'id': 'id1', 'function': {'name': 'agendar_lembrete',
                                                    'arguments': '{"texto":'}}]}}]},
            {'model': 'zeus', 'choices': [{'delta': {'tool_calls': [
                {'index': 0, 'function': {'arguments': '"água", "quando":"+30m"}'}}]},
                'finish_reason': 'tool_calls'}]},
        ])
        resposta = provedor.conversar_em_fluxo([], ferramentas=[{}])
        self.assertEqual(resposta.chamadas[0]['argumentos'], {'texto': 'água', 'quando': '+30m'})
        self.assertEqual(resposta.chamadas[0]['id'], 'id1')

    def test_hibrido_converte_resultado_local_para_contrato_remoto(self):
        local, remoto = self.provedores()
        hibrido = ProvedorHibrido(local, remoto)
        resposta = Resposta('', [{'nome': 'listar_pendencias', 'argumentos': {}, 'id': 'x'}])
        mensagens = [local.mensagem_do_assistente(resposta),
                     local.mensagem_de_ferramenta(resposta.chamadas[0], '{}')]
        convertidas = hibrido._mensagens_remotas(mensagens)
        chamada = convertidas[0]['tool_calls'][0]
        self.assertEqual(chamada['function']['arguments'], '{}')
        self.assertEqual(convertidas[1]['tool_call_id'], chamada['id'])
        self.assertIsInstance(mensagens[0]['tool_calls'][0]['function']['arguments'], dict)
