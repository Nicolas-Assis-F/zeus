"""Fila de saída durável. Resultado incerto não autoriza reenvio automático."""

import json
from datetime import datetime, timedelta

from .store import agora_utc, texto_de


# Marca de que o turno foi iniciado por uma versão que registra a intenção de
# cada efeito antes de executar. Sem ela, uma entrada interrompida é tratada
# como incerta: versões antigas não deixavam esse rastro.
MARCA_DE_EFEITOS = "efeitos_rastreados:"
TENTATIVAS_SEM_EFEITO = 2


class NaoEnviado(RuntimeError):
    """O canal sabe que a mensagem não foi aceita; repetir é seguro."""


class Entregas:
    def __init__(self, store):
        self.store = store
        self.db = store.connection

    def listar(self, limite=50):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM saidas ORDER BY "
            "CASE WHEN situacao IN ('incerta','falhou','expirada') THEN 0 ELSE 1 END, "
            "atualizada_em DESC, chave LIMIT ?", (limite,))]

    def preparar(self, chave, canal, texto, tipo='aviso', referencia=None,
                 agora=None, expira=None):
        agora = agora or agora_utc()
        with self.db:
            return self._inserir(chave, canal, texto, tipo, referencia, agora, expira)

    def _inserir(self, chave, canal, texto, tipo, referencia, agora, expira=None):
        if not texto.strip():
            raise ValueError('Saída precisa de texto.')
        return self.db.execute(
            "INSERT OR IGNORE INTO saidas "
            "(chave,canal,tipo,referencia,texto,criada_em,atualizada_em,tentar_em,expira_em) "
            "VALUES (?,?,?,?,?,?,?,?,?)", (chave, canal, tipo, referencia, texto,
            texto_de(agora), texto_de(agora), texto_de(agora), texto_de(expira) if expira else None)
        ).rowcount == 1

    def recuperar(self, agora=None):
        """Executar uma vez, sob trava de instância, após reinício do serviço.

        Entrada interrompida só volta sozinha para a fila quando dá para
        provar que nada com efeito chegou a começar: o turno foi iniciado por
        uma versão que registra intenção de efeito (marca em kv) e nenhuma
        intenção foi registrada. Qualquer outro caso fica incerto, para
        revisão — repetir pode duplicar um lembrete ou uma ação."""
        with self.db:
            self.db.execute("UPDATE saidas SET situacao='incerta', motivo='processo interrompido durante envio', "
                            "atualizada_em=? WHERE situacao='em_envio'", (texto_de(agora or agora_utc()),))
            chaves = {r[0] for r in self.db.execute(
                "SELECT resposta FROM entradas WHERE situacao='processando'")}
            for chave in chaves:
                seguro = chave is not None and self._sem_efeito(chave)
                self.db.execute(
                    "UPDATE entradas SET situacao=?, resposta=CASE WHEN ? THEN NULL ELSE resposta END "
                    "WHERE situacao='processando' AND resposta IS ?",
                    ('pendente' if seguro else 'incerta', seguro, chave))

    def _sem_efeito(self, chave) -> bool:
        rastreado = self.db.execute("SELECT 1 FROM kv WHERE chave=?",
                                    (MARCA_DE_EFEITOS + chave,)).fetchone()
        if not rastreado:
            return False
        return self.db.execute(
            "SELECT 1 FROM episodios WHERE tipo='efeitos_do_turno' AND resumo=?",
            ("turno:" + chave,)).fetchone() is None

    def registrar_agenda(self, canal, agora, atraso_maximo=86400):
        itens = [('pergunta', p) for p in self.store.perguntas_vencidas(agora)]
        itens += [('lembrete', p) for p in self.store.agenda_vencida(agora)]
        with self.db:
            for tipo, item in itens:
                chave = f"{tipo}:{item['id']}"
                expira = datetime.fromisoformat(item['vence_em']) + timedelta(seconds=atraso_maximo)
                nova = self._inserir(chave, canal, item['texto'], tipo, item['id'], agora, expira)
                # Marca legada sem conclusão pode ser uma queda após disparar.
                if nova and self.store.ja_enviado(chave):
                    self.db.execute("UPDATE saidas SET situacao='incerta', motivo='marca de envio legada sem confirmação' WHERE chave=?", (chave,))

    def _fonte_pendente(self, linha):
        tipo, ref = linha['tipo'], linha['referencia']
        if tipo not in ('pergunta', 'lembrete'):
            return True
        tabela = 'perguntas' if tipo == 'pergunta' else 'agenda'
        esperado = 'agendada' if tipo == 'pergunta' else 'pendente'
        fonte = self.db.execute(f"SELECT situacao FROM {tabela} WHERE id=?", (ref,)).fetchone()
        return bool(fonte and fonte[0] == esperado)

    def _concluir(self, linha, agora, recibo=None):
        self.db.execute("UPDATE saidas SET situacao='enviada', atualizada_em=?, motivo='', recibo=? WHERE chave=?",
                        (texto_de(agora), json.dumps(recibo, ensure_ascii=False) if recibo else None, linha['chave']))
        if linha['tipo'] == 'pergunta':
            self.db.execute("UPDATE perguntas SET situacao='perguntada', perguntada_em=? WHERE id=? AND situacao='agendada'",
                            (texto_de(agora), linha['referencia']))
        elif linha['tipo'] == 'lembrete':
            self.db.execute("UPDATE agenda SET situacao='concluida', concluida_em=? WHERE id=? AND situacao='pendente'",
                            (texto_de(agora), linha['referencia']))
        # Respostas já foram registradas pelo núcleo antes de entrar na fila.
        if linha['tipo'] != 'resposta':
            self.db.execute("INSERT INTO turnos (em,canal,papel,texto) VALUES (?,?,'zeus',?)",
                            (texto_de(agora), 'saida', linha['texto']))

    def enviar_pendentes(self, canais, agora=None, limite=8):
        agora = agora or agora_utc()
        entregues = []
        if not canais:
            return []
        nomes = list(canais)
        marcadores = ','.join('?' for _ in nomes)
        linhas = self.db.execute("SELECT * FROM saidas WHERE situacao='pendente' AND tentar_em<=? "
                                 + f"AND canal IN ({marcadores}) ORDER BY criada_em, chave LIMIT ?",
                                 [texto_de(agora), *nomes, limite]).fetchall()
        for registro in linhas:
            linha = dict(registro)
            canal = canais.get(linha['canal'])
            with self.db:
                # CAS impede dois consumidores de adquirir a mesma saída.
                if not self._fonte_pendente(linha):
                    self.db.execute("UPDATE saidas SET situacao='cancelada', motivo='origem encerrada' WHERE chave=? AND situacao='pendente'", (linha['chave'],))
                    continue
                if linha['expira_em'] and linha['expira_em'] < texto_de(agora):
                    self.db.execute("UPDATE saidas SET situacao='expirada', motivo='prazo de entrega excedido', atualizada_em=? WHERE chave=? AND situacao='pendente'",
                                    (texto_de(agora), linha['chave']))
                    continue
                if canal is None:
                    continue
                adquirido = self.db.execute("UPDATE saidas SET situacao='em_envio', tentativas=tentativas+1, atualizada_em=? "
                                             "WHERE chave=? AND situacao='pendente'", (texto_de(agora), linha['chave'])).rowcount
            if not adquirido:
                continue
            try:
                recibo = canal.enviar(linha['texto'])
            except NaoEnviado:
                tentativas = linha['tentativas'] + 1
                estado = 'falhou' if tentativas >= 3 else 'pendente'
                with self.db:
                    self.db.execute("UPDATE saidas SET situacao=?, motivo='canal confirmou que não enviou', tentar_em=?, atualizada_em=? WHERE chave=?",
                                    (estado, texto_de(agora + timedelta(seconds=30 * 2 ** (tentativas-1))), texto_de(agora), linha['chave']))
            except Exception:
                with self.db:
                    self.db.execute("UPDATE saidas SET situacao='incerta', motivo='sem confirmação do resultado externo', atualizada_em=? WHERE chave=?",
                                    (texto_de(agora), linha['chave']))
            else:
                with self.db:
                    self._concluir(linha, agora, recibo)
                entregues.append({'tipo': linha['tipo'], 'id': linha['referencia'],
                                  'texto': linha['texto'], 'canal': linha['canal'], 'chave': linha['chave']})
        return entregues

    def resolver(self, chave, acao, agora=None):
        agora = agora or agora_utc()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            linha = self.db.execute("SELECT * FROM saidas WHERE chave=?", (chave,)).fetchone()
            if not linha or linha['situacao'] not in ('incerta', 'falhou', 'expirada'):
                raise ValueError('Somente saída incerta, falha ou expirada pode ser resolvida.')
            if acao == 'confirmar':
                self._concluir(linha, agora)
            elif acao == 'reenviar':
                if not self._fonte_pendente(linha):
                    raise ValueError('A origem foi encerrada; não será reenviada.')
                self.db.execute("UPDATE saidas SET situacao='pendente', tentativas=0, motivo='reenvio solicitado pelo usuário', tentar_em=?, expira_em=?, atualizada_em=? WHERE chave=?",
                                (texto_de(agora), texto_de(agora + timedelta(days=1)), texto_de(agora), chave))
            elif acao == 'descartar':
                self.db.execute("UPDATE saidas SET situacao='cancelada', motivo='descartada pelo usuário', atualizada_em=? WHERE chave=?", (texto_de(agora), chave))
                if linha['tipo'] in ('pergunta', 'lembrete'):
                    tabela = 'perguntas' if linha['tipo'] == 'pergunta' else 'agenda'
                    self.db.execute(f"UPDATE {tabela} SET situacao='cancelada' WHERE id=? AND situacao IN ('agendada','pendente')", (linha['referencia'],))
            else:
                raise ValueError('Ação inválida.')

    def iniciar_resposta(self, mensagens):
        ids = sorted({int(m['id']) for m in mensagens})
        if not ids:
            return None
        chave = 'resposta:telegram:' + ','.join(map(str, ids))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            linhas = [self.db.execute('SELECT situacao FROM entradas WHERE id=?', (i,)).fetchone() for i in ids]
            if not all(r and r[0] == 'pendente' for r in linhas):
                return None
            for i in ids:
                self.db.execute("UPDATE entradas SET situacao='processando', resposta=? WHERE id=?", (chave, i))
            self.db.execute("INSERT OR IGNORE INTO kv (chave, valor) VALUES (?, '1')",
                            (MARCA_DE_EFEITOS + chave,))
        return chave

    def concluir_resposta(self, chave, texto, agora=None):
        with self.db:
            self._inserir(chave, 'telegram', texto, 'resposta', None, agora or agora_utc())
            self.db.execute("UPDATE entradas SET situacao='respondida' WHERE resposta=? AND situacao='processando'", (chave,))

    def resposta_incerta(self, chave):
        with self.db:
            self.db.execute("UPDATE entradas SET situacao='incerta' WHERE resposta=? AND situacao='processando'", (chave,))

    def resposta_interrompida(self, chave, houve_efeito: bool) -> str:
        """Falha no meio da resposta: reprocessar só quando é seguro.

        Sem nenhum efeito iniciado, a mensagem volta para a fila (no máximo
        duas vezes) e a próxima tentativa responde de novo — ou diz que o
        modelo está fora. Com efeito, fica incerta para revisão explícita."""
        tentativas = int(self.store.kv_get("tentativas:" + chave, "0") or 0) + 1
        self.store.kv_set("tentativas:" + chave, tentativas)
        if houve_efeito or not self._sem_efeito(chave) or tentativas > TENTATIVAS_SEM_EFEITO:
            self.resposta_incerta(chave)
            return "incerta"
        with self.db:
            self.db.execute("UPDATE entradas SET situacao='pendente', resposta=NULL "
                            "WHERE resposta=? AND situacao='processando'", (chave,))
        return "pendente"

    def pergunta_respondida(self, mensagens):
        """Pergunta que Nicolas respondeu usando "responder" no Telegram.

        O canal guarda a qual mensagem do Zeus a entrada responde; aqui essa
        mensagem é ligada à saída da pergunta pelo recibo. Sem resposta
        explícita, ou com respostas a perguntas diferentes, não há vínculo."""
        achadas = set()
        for mensagem in mensagens:
            alvo = self.store.kv_get(f"telegram_responde_a:{mensagem.get('id')}")
            if not alvo:
                continue
            for linha in self.db.execute("SELECT referencia, recibo FROM saidas "
                                         "WHERE tipo='pergunta' AND recibo IS NOT NULL"):
                try:
                    recibo = json.loads(linha["recibo"])
                except (TypeError, ValueError):
                    continue
                if str(recibo.get("message_id")) == str(alvo):
                    achadas.add(linha["referencia"])
        return achadas.pop() if len(achadas) == 1 else None

    def entradas(self):
        return [dict(r) for r in self.db.execute("SELECT id, situacao, recebida_em, resposta FROM entradas WHERE situacao!='respondida' ORDER BY id LIMIT 50")]

    def resolver_entrada(self, identificador, acao):
        if acao not in ('reprocessar', 'descartar'):
            raise ValueError('Ação inválida.')
        with self.db:
            n = self.db.execute("UPDATE entradas SET situacao=?, resposta=NULL WHERE id=? AND situacao='incerta'",
                                ('pendente' if acao == 'reprocessar' else 'respondida', identificador)).rowcount
        if not n:
            raise ValueError('Entrada não está incerta.')
