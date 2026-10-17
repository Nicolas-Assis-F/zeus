"""Tarefas supervisionadas pelo Orca; nunca invoca claude/codex diretamente."""
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .orcamento import CONFIRMACAO
from .tarefas import Tarefas, TarefaRecusada, REGRAS, REGRAS_DA_BASE


class TarefasOrca(Tarefas):
    def __init__(self, *args, orca='/home/zeus/.local/bin/orca-ide',
                 agentes=('codex', 'claude'), coordenador='', executar=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.orca = orca
        self.agentes = tuple(x.strip() for x in agentes.split(',') if x.strip()) if isinstance(agentes, str) else tuple(agentes)
        self.coordenador = coordenador
        self.executar_cli = executar or subprocess.run
        self.enviar_arquivo = None

    def _cli(self, *args):
        try:
            p = self.executar_cli([self.orca, *map(str, args), '--json'],
                capture_output=True, text=True, timeout=90,
                cwd=next(iter(self.repositorios.values())))
            d = json.loads(p.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise TarefaRecusada('Orca não confirmou a operação. Estado preservado; não relançar automaticamente.') from None
        self.ultimo_recibo = d
        if not d.get('ok') or p.returncode:
            erro = d.get('error') or {}
            raise TarefaRecusada('Orca: '+str(erro.get('code') or 'operação não confirmada')+
                                '. Consulte a tarefa antes de repetir.')
        return d['result']

    def diagnostico(self):
        try:
            self._cli('status')
            return 'Orca conectado; agentes preferidos: '+', '.join(self.agentes)
        except TarefaRecusada as e:
            return str(e)

    def preparar(self, *args, **kwargs):
        r = super().preparar(*args, **kwargs)
        t = self._ler(r['numero'])
        t['branch'] = f"zeus-{t['numero']}"
        t['executor'] = 'orca'
        self._gravar(t)
        r['resumo'] = (f"Tarefa #{t['numero']} no {t['projeto']}: {t['titulo']}\n\n{t['pedido']}\n\n"
            'Execução pelo Orca em workspace separado, com agente disponível. '
            'Merge e deploy ficam com você. O custo depende da conta do agente; '
            'o Orca não oferece teto financeiro por esta integração.\n\nPosso começar?')
        return r

    def preparar_base(self, *args, **kwargs):
        r = super().preparar_base(*args, **kwargs)
        r['resumo'] = r['resumo'].replace('O Claude aplica', 'Um agente pelo Orca aplica')
        t = self._ler(r['numero']); t['executor'] = 'orca'; self._gravar(t)
        return r

    def _agente(self):
        contas = self._cli('account', 'list')
        limites = contas.get('rateLimits') or {}
        agora = self.relogio().timestamp()*1000
        for agente in self.agentes:
            conta, limite = contas.get(agente) or {}, limites.get(agente) or {}
            autenticado = bool((conta.get('systemDefault') or {}).get('hasAuth') or
                               conta.get('accounts') or limite.get('status') == 'ok')
            if not autenticado or limite.get('status') == 'unavailable':
                continue
            esgotado = any((limite.get(j) or {}).get('usedPercent', 0) >= 100 and
                ((limite.get(j) or {}).get('resetsAt') or float('inf')) > agora
                for j in ('session', 'weekly', 'monthly'))
            if not esgotado:
                return agente
        raise TarefaRecusada('Nenhum agente configurado está autenticado com disponibilidade no Orca. Não iniciei tarefa paga.')

    def iniciar(self, numero, inicio_do_turno, mensagem):
        t = self._ler(numero)
        if t['situacao'] != 'aguardando':
            raise TarefaRecusada(f"Tarefa #{numero}: {t['situacao']}. Não iniciei outra execução.")
        if (inicio_do_turno is None or datetime.fromisoformat(t['criada_em']) >= inicio_do_turno
                or not CONFIRMACAO.search(mensagem or '')):
            raise TarefaRecusada('Mostre a tarefa e aguarde a confirmação de Nicolas numa mensagem nova.')
        if any(x['situacao'] in ('rodando', 'iniciando', 'incerta') for x in self.todas()):
            raise TarefaRecusada('Há uma tarefa ativa ou de início incerto. Confira antes de abrir outra.')
        if not self.coordenador:
            raise TarefaRecusada('Terminal coordenador exclusivo do Zeus não configurado no Orca.')
        agente = self._agente()
        repos = self._cli('repo', 'list')['repos']
        projeto = t['projeto'] if t.get('tipo') != 'base' else next(iter(self.repositorios))
        alvo = self.repositorios[projeto].resolve()
        repo = next((r for r in repos if str(alvo) == r['path']), None)
        if not repo:
            raise TarefaRecusada('Cadastre esse projeto no Orca antes de iniciar.')
        # Grave antes da primeira mutação: uma resposta perdida não pode duplicar cobrança.
        t.update(executor='orca', situacao='iniciando', agente=agente,
                 iniciada_em=self.relogio().isoformat(), custo_usd=None)
        self._gravar(t)
        try:
            run = self._cli('orchestration', 'run-create', '--objective', t['titulo'],
                            '--from', self.coordenador)['run']['id']
            t['orca_run'] = run; self._gravar(t)
            if t.get('tipo') == 'base':
                copia = self.pasta / f"base-{numero}-copia"
                shutil.copytree(self.base, copia, symlinks=True)
                t['copia'] = str(copia); self._gravar(t)
                regras = REGRAS_DA_BASE.format(data=self.relogio().strftime('%d/%m/%Y'))
                regras += f'\nA base alvo está em {self.base}. Edite somente o arquivo {t["arquivo"]} dessa base.'
            else:
                regras = REGRAS.format(branch='a branch criada pelo Orca')
            regras = regras.replace('Você é o Claude Code no X99', 'Você é um agente supervisionado pelo Orca')
            spec = (f"Target: {alvo}.\nChange: {t['titulo']}\n{t['pedido']}\n"
                f"Constraints e Ownership: {regras}\nObservable acceptance: valide o resultado "
                'com os testes adequados e informe evidências e caminhos dos arquivos criados. '
                'Documentos podem ter qualquer tipo de conteúdo e layout solicitado. '
                'Não invente dados nem exponha informações privadas em PR pública. '
                'Não inicie outros agentes. Custo importa: reutilize fontes; evite trabalho redundante. '
                'Se precisar de decisão, use ask do preâmbulo e aguarde. '
                f'Antes de concluir, grave {self.pasta / (str(numero)+".resultado.json")} como JSON '
                'com resumo (texto) e arquivos (lista de caminhos absolutos dos PDFs finais nesta worktree). '
                'Para PDFs, renderize e confira visualmente todas as páginas antes de entregar. '
                'Ao concluir, envie worker_done exatamente como o preâmbulo determina.')
            r = self._cli('orchestration', 'worker-start', '--run', run, '--from', self.coordenador,
                '--spec', spec, '--task-title', t['titulo'], '--worktree', 'new-top-level',
                '--repo', 'id:'+repo['id'], '--name', f"zeus-{numero}", '--agent', agente)
            t.update(orca_dispatch=r['dispatchId'], orca_task=r['taskId'],
                     situacao='rodando', branch=f'zeus-{numero}')
            self._gravar(t)
        except (TarefaRecusada, OSError, KeyError):
            t['situacao'] = 'incerta'
            t['recibo_orca'] = getattr(self, 'ultimo_recibo', {})
            self._gravar(t)
            raise TarefaRecusada('Início pelo Orca não confirmado. Registro preservado; confira no Orca antes de repetir.') from None
        return {'numero': t['numero'], 'branch': t['branch'], 'agente': agente, 'executor': 'orca'}

    def verificar(self):
        avisos = []
        for t in self.todas():
            if t.get('executor') != 'orca' or not t.get('orca_dispatch'):
                continue
            # A liberação pendente também é recuperada após reinício do serviço.
            if t['situacao'] not in ('rodando', 'concluída', 'falhou') or t.get('orca_liberado'):
                continue
            try:
                r = self._cli('orchestration', 'worker-show', '--dispatch', t['orca_dispatch'])
                outcome = (r.get('projection') or {}).get('outcome')
                caixa = self._cli('orchestration', 'check', '--terminal', self.coordenador,
                                  '--run', t['orca_run'])
                mensagens = caixa.get('messages') or []
                if caixa.get('deliveryId'):
                    t['orca_delivery'] = caixa['deliveryId']
                for m in mensagens:
                    if m.get('type') in ('question', 'escalation') and m['id'] not in t.get('mensagens_vistas', []):
                        t.setdefault('mensagens_vistas', []).append(m['id'])
                        t['pergunta_orca'] = m['id']
                        self._gravar(t)
                        avisos.append((t, f"Tarefa #{t['numero']} precisa de resposta: {m.get('body', '')[:1800]}"))
                if outcome not in ('succeeded', 'failed'):
                    passou = (self.relogio()-datetime.fromisoformat(t['iniciada_em'])).total_seconds() > self.limite_minutos*60
                    if passou and not t.get('aviso_tempo'):
                        t['aviso_tempo'] = True; self._gravar(t)
                        avisos.append((t, f"Tarefa #{t['numero']} passou de {self.limite_minutos} minutos. Confira no Orca; não abri outra execução."))
                    espera = (r.get('observation') or {}).get('agentWait')
                    if espera and not t.get('aviso_espera'):
                        t['aviso_espera'] = True; self._gravar(t)
                        avisos.append((t, f"Tarefa #{t['numero']} aguarda uma resposta no Orca. Confira a aba da tarefa."))
                    if caixa.get('deliveryId') and not any(m.get('type') in ('question', 'escalation', 'worker_done') for m in mensagens):
                        self._cli('orchestration', 'check', '--terminal', self.coordenador,
                                  '--run', t['orca_run'], '--ack', caixa['deliveryId'])
                    continue
                if t['situacao'] == 'rodando':
                    saida = self._cli('orchestration', 'worker-read', '--dispatch', t['orca_dispatch'], '--limit', '80')
                    resumo = next((m.get('body', '') for m in mensagens if m.get('type') == 'worker_done'), '')
                    pasta_worker = (r.get('terminal') or {}).get('worktreePath')
                    if not pasta_worker:
                        identidade = (r.get('worker') or {}).get('worktreeId', '')
                        pasta_worker = identidade.partition('::')[2]
                    if outcome == 'succeeded' and pasta_worker and self.enviar_arquivo:
                        relatorio = self.pasta / (str(t['numero'])+'.resultado.json')
                        if relatorio.is_file():
                            dados = json.loads(relatorio.read_text())
                            raiz = Path(pasta_worker).resolve()
                            for nome in dados.get('arquivos', []):
                                arquivo = Path(nome).resolve()
                                if (arquivo.is_relative_to(raiz) and arquivo.suffix.lower() == '.pdf'
                                        and arquivo.is_file() and arquivo.stat().st_size <= 25*1024*1024
                                        and arquivo.read_bytes().startswith(b'%PDF-')):
                                    chave = str(arquivo)
                                    if chave not in t.get('entregas', {}):
                                        t.setdefault('entregas', {})[chave] = 'incerta'
                                        self._gravar(t)
                                        self.enviar_arquivo(str(arquivo), t['titulo'])
                                        t['entregas'][chave] = 'enviado'; self._gravar(t)
                            resumo = dados.get('resumo') or resumo
                    t.update(situacao='concluída' if outcome == 'succeeded' else 'falhou',
                        resultado=saida, concluida_em=self.relogio().isoformat())
                    self._gravar(t)
                    # A notificação inclui saída real, sem deduzir sucesso de terminal ocioso.
                    avisos.append((t, f"Tarefa #{t['numero']} {t['situacao']} pelo Orca ({t['agente']}).\n"+
                        str(resumo or 'Resultado disponível na aba da tarefa no Orca.')[:1800]+
                        '\nCusto em dólares não informado pelo Orca; consulte a conta do agente.'))
                liberacao = self._cli('orchestration', 'worker-release', '--dispatch', t['orca_dispatch'])
                if caixa.get('deliveryId') and all(m.get('type') not in ('question', 'escalation') for m in mensagens):
                    self._cli('orchestration', 'check', '--terminal', self.coordenador,
                              '--run', t['orca_run'], '--ack', caixa['deliveryId'])
                if liberacao.get('state') in ('released', 'already_released', 'retained'):
                    t['orca_liberado'] = liberacao
                self._gravar(t)
            except (TarefaRecusada, OSError, ValueError, TypeError):
                continue
        return avisos

    def responder(self, numero, mensagem):
        t = self._ler(numero)
        if not t.get('pergunta_orca') or not str(mensagem or '').strip():
            raise TarefaRecusada('Não há pergunta pendente ou resposta vazia.')
        self._cli('orchestration', 'reply', '--id', t['pergunta_orca'], '--body', mensagem,
                  '--run', t['orca_run'], '--from', self.coordenador)
        if t.get('orca_delivery'):
            self._cli('orchestration', 'check', '--terminal', self.coordenador,
                      '--run', t['orca_run'], '--ack', t['orca_delivery'])
        t.pop('pergunta_orca', None); self._gravar(t)
        return {'numero': numero, 'respondida': True}

    def situacao(self):
        return [{k: t.get(k) for k in ('numero', 'projeto', 'titulo', 'situacao', 'agente',
                 'orca_dispatch', 'entregas', 'pergunta_orca', 'custo_usd')} for t in self.todas()[-10:]]
