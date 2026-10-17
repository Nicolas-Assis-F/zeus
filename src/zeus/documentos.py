"""Documentos PDF gerais, locais e versionados, sem executar conteúdo recebido."""
import hashlib
import json
import os
import re
from pathlib import Path

from .orcamento import Pagina, montar_pdf, largura

AZUL = (.08, .17, .26)


def renderizar(titulo, conteudo):
    paginas, y = [], 0
    def nova():
        nonlocal y
        p = Pagina()
        p.retangulo(0, 818, 595.28, 24, preencher=AZUL)
        p.texto(44, 25, f'{titulo[:85]}  |  {len(paginas)+1}', tamanho=8)
        paginas.append(p)
        y = 786
    def linha(texto, fonte='F1', tamanho=10, recuo=0):
        nonlocal y
        if y < 58:
            nova()
        paginas[-1].texto(44+recuo, y, texto, fonte=fonte, tamanho=tamanho, cor=AZUL)
        y -= tamanho*1.45
    def paragrafo(texto, fonte='F1', tamanho=10, recuo=0):
        # Também quebra identificadores e URLs longos, sem cortar conteúdo.
        atual = ''
        for palavra in texto.split():
            if atual and largura(atual+' '+palavra, fonte, tamanho) > 507-recuo:
                linha(atual, fonte, tamanho, recuo); atual = ''
            for caractere in palavra:
                if largura(atual+caractere, fonte, tamanho) > 507-recuo:
                    linha(atual, fonte, tamanho, recuo); atual = ''
                atual += caractere
            atual += ' '
        if atual.strip():
            linha(atual.rstrip(), fonte, tamanho, recuo)
    nova()
    paragrafo(titulo, 'F2', 23)
    y -= 14
    for texto in conteudo.splitlines():
        texto = texto.strip()
        if not texto:
            y -= 8
            continue
        cab = re.match(r'^#{1,6}\s+(.+)', texto)
        if cab:
            if y < 110:
                nova()
            y -= 8
            paragrafo(cab[1], 'F2', 13)
            y -= 4
        elif re.fullmatch(r'[| :\-]+', texto):
            continue
        else:
            texto = re.sub(r'\*\*(.*?)\*\*', r'\1', texto)
            paragrafo(texto, recuo=8 if texto.startswith(('- ', '* ')) else 0)
    return montar_pdf(paginas)


class Documentos:
    def __init__(self, pasta):
        self.pasta = Path(pasta).expanduser()

    def gerar(self, titulo, conteudo):
        titulo, conteudo = str(titulo or '').strip(), str(conteudo or '').strip()
        if not titulo or not conteudo:
            raise ValueError('Informe título e conteúdo completo do documento.')
        # Acentos portugueses suportados; nunca substituir silenciosamente caracteres.
        try:
            (titulo+conteudo).encode('cp1252')
        except UnicodeEncodeError:
            raise ValueError('Este layout local precisa de fonte Unicode para esses caracteres. Use uma tarefa no Orca para criar o layout solicitado sem remover conteúdo.') from None
        numero = 'ZD-' + hashlib.sha256((titulo+'\n'+conteudo).encode()).hexdigest()[:16]
        self.pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
        alvo = self.pasta / (numero+'.pdf')
        if not alvo.exists():
            temporario = alvo.with_suffix('.tmp')
            temporario.write_bytes(renderizar(titulo, conteudo))
            os.chmod(temporario, 0o600)
            os.replace(temporario, alvo)
        registro = {'numero': numero, 'titulo': titulo, 'conteudo': conteudo,
                    'arquivo': str(alvo), 'gerado': True}
        self.pasta.joinpath(numero+'.json').write_text(json.dumps(registro, ensure_ascii=False))
        os.chmod(self.pasta / (numero+'.json'), 0o600)
        return registro

    def consultar(self, numero):
        if not re.fullmatch(r'ZD-[a-f0-9]{16}', str(numero)):
            raise ValueError('Documento desconhecido.')
        r = json.loads((self.pasta / (numero+'.json')).read_text())
        alvo = Path(r['arquivo']).resolve()
        if alvo.parent != self.pasta.resolve() or not alvo.is_file():
            raise ValueError('Arquivo de documento indisponível.')
        return r
