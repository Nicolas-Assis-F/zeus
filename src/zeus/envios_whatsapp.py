"""Envios pelo número principal sob comando de Nicolas, com recibo e deduplicação.

Não compartilha a fila do grupo: o destino de cada envio é registrado antes do
POST. Uma resposta ambígua fica incerta e nunca é repetida automaticamente.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from .canais.whatsapp import transporte_da_ponte
from .conversas import normalizar

PEDIDO_DE_ENVIO = re.compile(
    r"\b(envi\w*|mand\w*|dispar\w*|respond[ae]\w*|avis[ae]\w*|fale|diga)\b")
NEGACAO = re.compile(r"\b(nao|nunca|nem)\s+(?:\w+\s+){0,2}(envi\w*|mand\w*|dispar\w*|respond\w*|avis\w*)\b")
CONFIRMA = re.compile(r"^(?:sim|ok|confirmado|confirmo|pode|pode sim)[.! ]*$")
CONFIRMA_ENVIO = re.compile(
    r"^(?:pode |confirmo )?(?:manda|mande|mandar|envia|envie|enviar|dispare|disparar)"
    r"(?: agora| a mensagem| o orcamento| pra ele| para ele| pra ela| para ela)?$")


def confirmacao_de_envio(pedido):
    texto = normalizar(pedido)
    return bool(CONFIRMA.fullmatch(texto) or CONFIRMA_ENVIO.fullmatch(texto))


class EnvioRecusado(ValueError):
    pass


class EnviosWhatsApp:
    def __init__(self, url, leitor, store, orcamentos=None, transporte=None, documentos=None):
        self.url = url.rstrip('/')
        self.leitor = leitor
        self.store = store
        self.orcamentos = orcamentos
        self.documentos = documentos
        self.transporte = transporte or transporte_da_ponte

    def _registro(self, numero):
        bruto = self.store.kv_get('envio_whatsapp:' + str(numero))
        if not bruto:
            raise EnvioRecusado('Envio não encontrado. Prepare a mensagem primeiro.')
        return json.loads(bruto)

    def _salvar(self, r):
        self.store.kv_set('envio_whatsapp:' + r['numero'], json.dumps(r, ensure_ascii=False))

    def _arquivo(self, numero):
        if not numero:
            return None, None
        if str(numero).startswith('ZD-') and self.documentos is not None:
            from pathlib import Path
            return Path(self.documentos.consultar(numero)['arquivo']), None
        if self.orcamentos is None or not re.fullmatch(r'ZT\d{4}-\d{4,}', str(numero)):
            raise EnvioRecusado('Número de orçamento inválido.')
        pasta = self.orcamentos.pasta.resolve()
        try:
            o = json.loads((pasta / (str(numero) + '.json')).read_text())
            arquivo = (pasta / o['arquivo']).resolve()
        except (OSError, ValueError, KeyError):
            raise EnvioRecusado('O PDF ainda não foi gerado. Gere o orçamento antes.') from None
        if not o.get('gerado') or arquivo.parent != pasta or not arquivo.is_file():
            raise EnvioRecusado('Arquivo de orçamento indisponível.')
        return arquivo, o

    def preparar(self, contato, texto, orcamento='', inicio=None):
        contato, texto = str(contato or '').strip(), str(texto or '').strip()
        if not texto or len(texto) > 6000:
            raise EnvioRecusado('Mensagem precisa ter entre 1 e 6000 caracteres.')
        # Telefones explícitos são aceitos; nomes usam a mesma resolução sem
        # ambiguidades da leitura (agenda, CRM e acompanhados).
        digitos = re.sub(r'\D', '', contato)
        if re.fullmatch(r'[+\d ().-]+', contato) and 10 <= len(digitos) <= 15:
            jid, nome = digitos + '@s.whatsapp.net', contato
        else:
            jid, nome = self.leitor.achar(contato)
        if jid.partition('@')[2] not in ('s.whatsapp.net', 'lid'):
            raise EnvioRecusado('O destinatário precisa ser um contato individual.')
        arquivo, o = self._arquivo(orcamento)
        if o:
            # Não encaminhar por engano o orçamento de outro cliente.
            cliente = normalizar(o['cliente']['nome'])
            razao = normalizar(o['cliente'].get('razao_social', ''))
            nomes = [normalizar(contato), normalizar(nome)]
            if not any(n and (n in cliente or cliente in n or n in razao) for n in nomes):
                raise EnvioRecusado('O cliente do PDF não corresponde ao destinatário.')
        payload = {'jid': jid, 'contato': nome, 'busca': contato, 'mensagem': texto,
                   'orcamento': str(orcamento or ''), 'arquivo': str(arquivo or ''),
                   'sha256': hashlib.sha256(arquivo.read_bytes()).hexdigest() if arquivo else '',
                   'criado_em': (inicio or datetime.now(timezone.utc)).isoformat()}
        ultimo = self.store.kv_get('ultimo_envio_whatsapp')
        if ultimo:
            anterior = self._registro(ultimo)
            campos = ('jid', 'mensagem', 'orcamento', 'arquivo', 'sha256')
            if all(anterior.get(c) == payload.get(c) for c in campos):
                # O mesmo rascunho não vira um novo pedido de confirmação a
                # cada mensagem. Mantém também o recibo de um envio já feito.
                return {'numero': anterior['numero'], 'contato': anterior['contato'],
                        'mensagem': anterior['mensagem'], 'orcamento': anterior['orcamento'],
                        'situacao': anterior['situacao']}
        numero = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]
        r = {'numero': numero, **payload, 'situacao': 'preparado'}
        anterior = self.store.kv_get('envio_whatsapp:' + numero)
        if anterior:
            r = json.loads(anterior)
        else:
            self._salvar(r)
        self.store.kv_set('ultimo_envio_whatsapp', numero)
        return {'numero': numero, 'contato': nome, 'mensagem': texto,
                'orcamento': r['orcamento'], 'situacao': r['situacao']}

    def enviar(self, numero, inicio, pedido):
        r = self._registro(numero)
        if r['situacao'] == 'enviado':
            return {'enviado': True, 'duplicado_evitado': True, 'contato': r['contato']}
        if r['situacao'] != 'preparado':
            raise EnvioRecusado('Envio incerto; confira no WhatsApp antes de pedir outro envio.')
        texto = normalizar(pedido)
        if NEGACAO.search(texto):
            raise EnvioRecusado('Nicolas pediu para não enviar.')
        posterior = inicio is not None and r['criado_em'] < inicio.isoformat()
        confirma_rascunho = (posterior and self.store.kv_get('ultimo_envio_whatsapp') == numero
                            and confirmacao_de_envio(texto))
        menciona = any(normalizar(n) and normalizar(n) in texto for n in (r['contato'], r['busca']))
        # "mande para o cliente" só vale com o PDF cujo cliente foi conferido.
        cliente_do_pdf = r['orcamento'] and re.search(r'\bcliente\b', texto)
        if r['orcamento'] and re.search(r'\b(ele|ela)\b', texto):
            foco = self.store.kv_get('ultimo_orcamento_gerado')
            if not foco and self.orcamentos:
                gerados = sorted(self.orcamentos.pasta.glob('ZT*.json'),
                                 key=lambda p: p.stat().st_mtime, reverse=True)
                if gerados:
                    foco = gerados[0].stem
            cliente_do_pdf = cliente_do_pdf or r['orcamento'] == foco
        if not confirma_rascunho and not (PEDIDO_DE_ENVIO.search(texto) and (menciona or cliente_do_pdf)):
            raise EnvioRecusado('Mostre o destinatário e a mensagem e aguarde Nicolas mandar enviar.')
        if r['arquivo']:
            arquivo, _ = self._arquivo(r['orcamento'])
            if hashlib.sha256(arquivo.read_bytes()).hexdigest() != r['sha256']:
                raise EnvioRecusado('O PDF mudou depois de preparar o envio. Prepare novamente.')
        r['situacao'] = 'em_envio'
        self._salvar(r)
        corpo = {'recipient': r['jid'], 'message': r['mensagem']}
        if r['arquivo']:
            corpo['media_path'] = r['arquivo']
        try:
            status, dados = self.transporte(self.url + '/api/send', corpo)
        except Exception as erro:
            r.update(situacao='incerto', motivo=type(erro).__name__)
            self._salvar(r)
            raise EnvioRecusado('A ponte não confirmou o envio; não repeti para evitar duplicidade.') from None
        if status == 400:
            r.update(situacao='preparado', motivo=str(dados.get('message', 'recusado'))[:200])
            self._salvar(r)
            raise EnvioRecusado('A ponte recusou o envio: ' + r['motivo'])
        if status != 200 or not dados.get('success'):
            r.update(situacao='incerto', motivo=str(dados.get('message', status))[:200])
            self._salvar(r)
            raise EnvioRecusado('Envio incerto. Confira no WhatsApp; não houve repetição automática.')
        r.update(situacao='enviado', enviado_em=datetime.now(timezone.utc).isoformat(),
                 recibo=str(dados.get('message', 'confirmado pela ponte'))[:300])
        self._salvar(r)
        return {'enviado': True, 'contato': r['contato'], 'orcamento': r['orcamento'],
                'recibo': r['recibo']}
