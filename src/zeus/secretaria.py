"""Estado operacional e comandos exatos que dispensam uma chamada ao modelo."""
import json
import re

from .conversas import normalizar
from .envios_whatsapp import CONFIRMA, CONFIRMA_ENVIO
from .custos import ferramenta, rota

GERAR_PDF = re.compile(
    r'^(?:(?:ok|sim|confirmo|confirmado|pode|pode sim) )?'
    r'(?:gere|gera|gerar)(?: o)? pdf(?: por favor)?$')


def pendente(ferramentas, tipo, numero):
    ferramentas.store.kv_set('secretaria_pendente', json.dumps({'tipo': tipo, 'numero': numero}))


def concluir(ferramentas, tipo, numero):
    try:
        atual = json.loads(ferramentas.store.kv_get('secretaria_pendente') or '{}')
    except ValueError:
        return
    if atual == {'tipo': tipo, 'numero': numero}:
        ferramentas.store.kv_set('secretaria_pendente', '{}')


def plano_atalho(f, texto):
    """Só frases fechadas; instrução composta ou correção segue para o modelo."""
    texto = str(texto).removeprefix('[áudio de Nicolas, transcrito] ')
    texto = normalizar(texto)
    try:
        atual = json.loads(f.store.kv_get('secretaria_pendente') or '{}')
    except ValueError:
        atual = {}
    comando, argumentos = None, {}
    confirma = bool(CONFIRMA.fullmatch(texto))
    if f.envios_whatsapp is not None and atual.get('tipo') != 'orcamento' and (CONFIRMA_ENVIO.fullmatch(texto) or
                                         (confirma and atual.get('tipo') == 'envio')):
        numero = (atual.get('numero') if atual.get('tipo') == 'envio'
                  else f.store.kv_get('ultimo_envio_whatsapp'))
        if numero:
            comando, argumentos = 'enviar_whatsapp', {'numero': numero}
    elif f.orcamentos is not None and (GERAR_PDF.fullmatch(texto) or
                                       (confirma and atual.get('tipo') == 'orcamento')):
        numero = (atual.get('numero') if atual.get('tipo') == 'orcamento'
                  else f.store.kv_get('ultimo_orcamento_preparado'))
        if numero:
            comando, argumentos = 'gerar_orcamento', {'numero': numero}
    return (comando, argumentos, texto) if comando is not None else None


def executar_atalho(f, texto):
    plano = plano_atalho(f, texto)
    if plano is None:
        return None
    comando, argumentos, texto = plano
    rota('comando_local')
    if comando == 'gerar_orcamento':
        consulta = f.executar('consultar_orcamento', argumentos)
        if consulta.get('gerado'):
            concluir(f, 'orcamento', argumentos['numero'])
            return f"O PDF {argumentos['numero']} já foi gerado. Não gerei outra cópia."
    original = f.mensagem_do_turno
    f.mensagem_do_turno = texto
    try:
        resultado = f.executar(comando, argumentos)
    finally:
        f.mensagem_do_turno = original
    ferramenta(comando, bool(resultado.get('erro')))
    if resultado.get('erro'):
        return str(resultado['erro'])
    if comando == 'enviar_whatsapp':
        if resultado.get('duplicado_evitado'):
            return f"O envio a {resultado['contato']} já estava confirmado. Não enviei de novo."
        anexo = f", com o {resultado['orcamento']} anexado" if resultado.get('orcamento') else ''
        return f"Enviado a {resultado['contato']}{anexo}. A ponte confirmou o envio."
    return f"PDF {resultado['numero']} gerado e enviado no grupo."


def estado_operacional(f, compacto=False):
    """Dados verificados nos próprios registros; não deduz estado pelo histórico."""
    estado = {}
    documentos = getattr(f, 'documentos', None)
    ultimo_documento = f.store.kv_get('ultimo_documento_gerado')
    if documentos and ultimo_documento:
        try:
            d = documentos.consultar(ultimo_documento)
            estado['ultimo_documento'] = {k: d[k] for k in ('numero', 'titulo', 'gerado')}
            estado['ultimo_documento']['entrega'] = f.store.kv_get('documento_entrega:' + ultimo_documento)
        except (ValueError, OSError):
            pass
    if f.orcamentos is not None:
        try:
            numero = f.store.kv_get('ultimo_orcamento_preparado') or ''
            o = f.orcamentos.consultar(numero)
            estado['orcamento_em_foco'] = {k: o[k] for k in (
                'numero', 'gerado', 'cliente', 'itens', 'total_centavos',
                'desconto_centavos', 'pagamento_extenso', 'entrega')}
            if compacto:
                foco = estado['orcamento_em_foco']
                foco['cliente'] = {'nome': o['cliente']['nome']}
                campos = ('sku', 'rotulo', 'descricao', 'quantidade', 'preco_centavos', 'variante', 'observacao')
                foco['itens'] = [{k: item[k] for k in campos if item.get(k) not in (None, '')}
                                 for item in o['itens'][:4]]
            if compacto and len(o['itens']) > 4:
                estado['orcamento_em_foco']['itens_omitidos'] = len(o['itens']) - 4
                estado['orcamento_em_foco']['instrucao_dos_dados'] = 'Consulte o orçamento para ver todos os itens.'
        except (ValueError, OSError):
            pass
    if f.envios_whatsapp is not None:
        numero = f.store.kv_get('ultimo_envio_whatsapp')
        if numero:
            try:
                envio = f.envios_whatsapp._registro(numero)
                estado['ultimo_envio'] = {k: envio.get(k) for k in (
                    'numero', 'contato', 'mensagem', 'orcamento', 'situacao', 'enviado_em')}
                if compacto and envio.get('situacao') == 'enviado':
                    estado['ultimo_envio'].pop('mensagem', None)
            except (ValueError, OSError):
                pass
    return estado
