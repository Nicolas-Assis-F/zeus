"""Orçamento em PDF no formato da LE, sem banco e sem dependência nova.

O modelo (o pedido SO2609-0004 de 14/09/2026) usa Helvetica e Helvetica-Bold,
as Type 1 padrão do PDF em WinAnsi, desenhadas em coordenadas absolutas. Por
isso o PDF é escrito aqui direto, com a biblioteca padrão: as mesmas fontes,
as coordenadas de `orcamentos.md` (seção 1) e as larguras da Helvetica para
alinhar à direita e quebrar linha.

O fluxo tem três travas que são do código, não do prompt:

1. **Preço** vem de `precos.json`, na base de conhecimento, que só tem preço
   praticado APROVADO. Item fora dele só entra com o valor que Nicolas deu,
   e o resumo diz isso.
2. **Confirmação**: `gerar` recusa o rascunho criado na mesma resposta e exige
   que a mensagem de Nicolas que pediu a geração confirme.
3. **Destino**: o PDF vai para o grupo pelo canal, que fixa o destinatário.

Nada vai para o banco do sistemale nem para a memória do Zeus: rascunho, PDF,
registro e sequência ficam na pasta de orçamentos, fora de qualquer git. A
numeração é de teste, `ZT{AAMM}-NNNN`, e não colide com o `SO` oficial.
"""

import fcntl
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRASILIA = timezone(timedelta(hours=-3))
LARGURA_DA_PAGINA, ALTURA_DA_PAGINA = 595.28, 841.89
CONFIRMACAO = re.compile(
    r"\b(ok|okay|pode|confirm\w*|ger[ae]\w*|manda|mande|sim|isso|beleza|blz|fechado|"
    r"positivo|bora|certo|perfeito|segue)\b", re.IGNORECASE)

# Larguras em milésimos de em para os bytes 32 a 255 em WinAnsi (cp1252).
# Extraídas da Liberation Sans, que tem as métricas da Helvetica, e conferidas
# contra o AFM da Nimbus Sans (o clone da Helvetica) em todo o ASCII.
_REGULAR = """
278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278
556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556
1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778
667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556
333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556
556 556 333 500 278 556 500 722 500 500 500 334 260 334 584 750
556 0 222 556 333 1000 556 556 333 1000 667 333 1000 0 611 0
0 222 222 333 333 350 556 1000 333 1000 500 333 944 0 500 667
278 333 556 556 556 556 260 556 333 737 370 556 584 333 737 552
400 549 333 333 333 576 537 333 333 333 365 556 834 834 834 611
667 667 667 667 667 667 1000 722 667 667 667 667 278 278 278 278
722 722 778 778 778 778 778 584 778 722 722 722 722 667 667 611
556 556 556 556 556 556 889 500 556 556 556 556 278 278 278 278
556 556 556 556 556 556 556 549 611 556 556 556 556 500 556 500
"""
_NEGRITO = """
278 333 474 556 556 889 722 238 333 333 389 584 278 333 278 278
556 556 556 556 556 556 556 556 556 556 333 333 584 584 584 611
975 722 722 722 722 667 611 778 722 278 556 722 611 833 722 778
667 778 722 667 611 722 667 944 667 667 611 333 278 333 584 556
333 556 611 556 611 556 333 611 611 278 278 556 278 889 611 611
611 611 389 556 333 611 556 778 556 556 500 389 280 389 584 750
556 0 278 556 500 1000 556 556 333 1000 667 333 1000 0 611 0
0 278 278 500 500 350 556 1000 333 1000 556 333 944 0 500 667
278 333 556 556 556 556 280 556 333 737 370 556 584 333 737 552
400 549 333 333 333 576 556 333 333 333 365 556 834 834 834 611
722 722 722 722 722 722 1000 722 667 667 667 667 278 278 278 278
722 722 778 778 778 778 778 584 778 722 722 722 722 667 667 611
556 556 556 556 556 556 889 556 556 556 556 556 278 278 278 278
611 611 611 611 611 611 611 549 611 611 611 611 611 556 611 556
"""
LARGURAS = {"F1": [int(n) for n in _REGULAR.split()],
            "F2": [int(n) for n in _NEGRITO.split()]}

COR_TITULO = (.09, .11, .29)
COR_CABECALHO = (.2, .2, .2)
COR_ROTULO = (.35, .35, .35)
COR_BLOCO = (.15, .15, .15)
COR_TABELA = (.1, .1, .1)
COR_ITEM = (.12, .12, .12)
COR_SEM_IMPOSTO = (.3, .3, .3)
COR_RODAPE = (.4, .4, .4)
COR_LINHA = (.75, .75, .78)
FUNDO_DE = (.945, .945, .95)
FUNDO_TOTAL = (.9, .93, .97)

# Versão limpa do bloco "De" (orcamentos.md, seção 4): o modelo antigo traz o
# telefone 69286018386, que faria o cliente ligar para o número errado.
EMITENTE = [
    "Rua X 13, s/n, Quadra 12, Lote 19",
    "American Park, Aparecida de Goiânia - GO",
    "CEP 74953-140",
    "",
    "Telefone: (62) 98601-8386",
    "E-mail: letorneadora@gmail.com",
]
RODAPE = ("Capital de 100 000 R$ - CNPJ: 44.492.124/0001-07 - "
          "Inscrição Estadual: 10.875.250-0")
OBRIGATORIOS = {"nome": "nome comercial", "razao_social": "razão social ou titular",
                "doc": "CPF ou CNPJ", "endereco": "endereço", "cidade": "cidade",
                "uf": "UF", "cep": "CEP"}


class OrcamentoRecusado(ValueError):
    pass


# ----------------------------------------------------------------- texto
def brl(centavos: int) -> str:
    """Formato do modelo: espaço comum como milhar, vírgula decimal, sem R$."""
    inteiro, cent = divmod(int(centavos), 100)
    return f"{inteiro:,}".replace(",", " ") + f",{cent:02d}"


def reais(centavos: int) -> str:
    """Formato da conversa: R$ 10.500,00."""
    inteiro, cent = divmod(int(centavos), 100)
    return "R$ " + f"{inteiro:,}".replace(",", ".") + f",{cent:02d}"


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto))


def winansi(texto: str) -> bytes:
    # A Helvetica padrão não tem o duplo primo: "2 3/8″" vira "2 3/8\"".
    texto = str(texto).replace("″", '"').replace("′", "'")
    return texto.encode("cp1252", errors="replace")


def largura(texto: str, fonte: str, tamanho: float) -> float:
    tabela = LARGURAS[fonte]
    return sum(tabela[b - 32] if b >= 32 else 0 for b in winansi(texto)) * tamanho / 1000


def quebrar(texto: str, fonte: str, tamanho: float, maximo: float) -> list:
    linhas = []
    for paragrafo in str(texto).split("\n"):
        atual = ""
        for palavra in paragrafo.split():
            tentativa = f"{atual} {palavra}".strip()
            if atual and largura(tentativa, fonte, tamanho) > maximo:
                linhas.append(atual)
                atual = palavra
            else:
                atual = tentativa
        linhas.append(atual)
    return linhas


def _cor(rgb) -> str:
    return " ".join(f"{c:g}" for c in rgb)


def _escapar(dados: bytes) -> bytes:
    return dados.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class Pagina:
    def __init__(self):
        self.ops = []

    def texto(self, x, y, conteudo, fonte="F1", tamanho=8.3, cor=COR_BLOCO, alinhar="esq"):
        if alinhar == "dir":
            x -= largura(conteudo, fonte, tamanho)
        elif alinhar == "centro":
            x -= largura(conteudo, fonte, tamanho) / 2
        self.ops.append(f"BT /{fonte} {tamanho:g} Tf {_cor(cor)} rg {x:.2f} {y:.2f} Td (".encode()
                        + _escapar(winansi(conteudo)) + b") Tj ET")

    def retangulo(self, x, y, w, h, preencher=None, borda=None, espessura=0.7):
        if preencher:
            self.ops.append(f"{_cor(preencher)} rg {x:g} {y:g} {w:g} {h:g} re f".encode())
        if borda:
            self.ops.append(f"{espessura:g} w {_cor(borda)} RG {x:g} {y:g} {w:g} {h:g} re S".encode())

    def linha(self, x1, y1, x2, y2, cor=COR_LINHA, espessura=0.7):
        self.ops.append(f"{espessura:g} w {_cor(cor)} RG {x1:g} {y1:g} m {x2:g} {y2:g} l S".encode())

    def imagem(self, x, y, w, h):
        self.ops.append(f"q {w:g} 0 0 {h:g} {x:g} {y:g} cm /Im1 Do Q".encode())


def tamanho_do_jpeg(dados: bytes):
    i = 2
    while i + 9 < len(dados):
        if dados[i] != 0xFF:
            i += 1
            continue
        marca = dados[i + 1]
        if marca in (0xC0, 0xC1, 0xC2):
            altura = int.from_bytes(dados[i + 5:i + 7], "big")
            largura_ = int.from_bytes(dados[i + 7:i + 9], "big")
            return largura_, altura, dados[i + 9]
        i += 2 + int.from_bytes(dados[i + 2:i + 4], "big")
    raise OrcamentoRecusado("O logo não é um JPEG legível.")


def montar_pdf(paginas, logo: bytes = b"") -> bytes:
    """PDF 1.4 mínimo: catálogo, páginas, duas fontes padrão e o logo."""
    objetos = []

    def novo(corpo: bytes) -> int:
        objetos.append(corpo)
        return len(objetos)

    catalogo = novo(b"")
    raiz = novo(b"")
    f1 = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
              b"/Encoding /WinAnsiEncoding >>")
    recursos = b"/Font << /F1 %d 0 R /F2 %d 0 R >>" % (f1, f2)
    if logo:
        w, h, componentes = tamanho_do_jpeg(logo)
        espaco = b"/DeviceGray" if componentes == 1 else b"/DeviceRGB"
        imagem = novo(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s "
                      b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n" % (
                          w, h, espaco, len(logo)) + logo + b"\nendstream")
        recursos += b" /XObject << /Im1 %d 0 R >>" % imagem
    filhas = []
    for pagina in paginas:
        conteudo = b"\n".join(op for op in pagina.ops if logo or b"/Im1" not in op)
        fluxo = novo(b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"\nendstream")
        filhas.append(novo(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595.28 841.89] "
                           b"/Resources << %s >> /Contents %d 0 R >>" % (raiz, recursos, fluxo)))
    objetos[catalogo - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % raiz
    objetos[raiz - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % f for f in filhas), len(filhas))
    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posicoes = []
    for numero, corpo in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % numero + corpo + b"\nendobj\n"
    inicio = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for posicao in posicoes:
        saida += b"%010d 00000 n \n" % posicao
    saida += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objetos) + 1, catalogo, inicio)
    return bytes(saida)


# ----------------------------------------------------------------- layout
def _cabecalho(p, o, numero_da_pagina, total_de_paginas):
    p.imagem(42, 741.89, 58, 58)
    p.texto(553.28, 779.89, f"Pedido {o['numero']}", "F2", 17, COR_TITULO, "dir")
    p.texto(553.28, 763.89, f"Ref. Cliente : {o['ref_cliente']}", "F1", 8.5, COR_CABECALHO, "dir")
    p.texto(553.28, 751.89, f"Data Pedido : {o['data_br']}", "F1", 8.5, COR_CABECALHO, "dir")
    p.texto(553.28, 739.89, f"Código de Cliente : {o['codigo_cliente']}", "F1", 8.5,
            COR_CABECALHO, "dir")
    p.texto(553.28, 727.89, "ORÇAMENTO, SEM VALOR DE PEDIDO", "F2", 8.5, COR_ROTULO, "dir")
    p.texto(LARGURA_DA_PAGINA / 2, 44, RODAPE, "F1", 7, COR_RODAPE, "centro")
    p.texto(LARGURA_DA_PAGINA / 2, 35, f"CNPJ/CPF: {o['cliente']['doc']}", "F1", 7,
            COR_RODAPE, "centro")
    p.texto(553.28, 35, f"{numero_da_pagina} / {total_de_paginas}", "F1", 7, COR_RODAPE, "dir")


def _blocos(p, o):
    p.texto(42, 703.89, "De", "F1", 8.5, COR_ROTULO)
    p.retangulo(42, 577.89, 240, 118, preencher=FUNDO_DE)
    p.texto(50, 679.89, "LE TORNEADORA LTDA", "F2", 10, COR_TITULO)
    for i, linha in enumerate(EMITENTE):
        p.texto(50, 666.89 - 12 * i, linha)
    c = o["cliente"]
    p.texto(310, 703.89, "Para", "F1", 8.5, COR_ROTULO)
    p.retangulo(310, 577.89, 243, 118, borda=COR_LINHA)
    p.texto(318, 679.89, c["nome"], "F2", 10, COR_TITULO)
    rotulo = "CPF: " if len(so_digitos(c["doc"])) == 11 else "CNPJ: "
    linhas = quebrar(c["razao_social"], "F1", 8.3, 227) + [rotulo + c["doc"]]
    if c.get("ie"):
        linhas.append(f"Inscrição Estadual: {c['ie']}")
    linhas += quebrar(c["endereco"], "F1", 8.3, 227)
    linhas.append(f"{c['cidade']} - {c['uf']}, CEP {so_digitos(c['cep']) or c['cep']}")
    if c.get("email"):
        linhas.append(c["email"])
    for i, linha in enumerate(linhas[:8]):
        p.texto(318, 666.89 - 12 * i, linha)
    p.retangulo(42, 543.89, 511.28, 20, borda=COR_LINHA)
    p.texto(48, 550.39, f"Pagamento: {o['pagamento_extenso']}.")
    p.texto(553.28, 529.89, "Valores Apresentados em Brazil Real", "F1", 8, COR_ROTULO, "dir")


def _moldura(p):
    p.linha(42, 523.89, 553.28, 523.89)
    p.linha(42, 505.89, 553.28, 505.89)
    p.texto(44, 511.39, "Designação", "F1", 8.5, COR_TABELA)
    p.texto(368, 511.39, "ICMS", "F1", 8.5, COR_TABELA)
    p.texto(457, 511.39, "Preço Unit.", "F1", 8.5, COR_TABELA, "dir")
    p.texto(503, 511.39, "Quant.", "F1", 8.5, COR_TABELA, "dir")
    p.texto(551.3, 511.39, "Total (liq.)", "F1", 8.5, COR_TABELA, "dir")
    for x in (42, 365, 410, 462, 505, 553.28):
        p.linha(x, 505.89, x, 132)
    p.linha(42, 132, 553.28, 132)


def _linhas_do_item(item) -> list:
    linhas = [(l, "F1") for l in quebrar(f"{item['sku']} - {item['rotulo']}", "F1", 8.3, 318)]
    linhas += [(l, "F1") for l in quebrar(item.get("descricao", ""), "F1", 8.3, 318) if l]
    if item.get("variante"):
        linhas += [(l, "F2") for l in quebrar(item["variante"], "F2", 8.3, 318)]
    if item.get("observacao"):
        linhas += [(l, "F1") for l in quebrar(item["observacao"], "F1", 8.3, 318)]
    linhas.append((f"(País de Origem: {item.get('origem', 'Brasil')})", "F1"))
    return linhas


def _altura(linhas) -> float:
    return sum(12 if fonte == "F2" else 11 for _, fonte in linhas) + 6


def desenhar(o, logo: bytes = b"") -> bytes:
    """O orçamento confirmado vira PDF. Itens que não cabem abrem outra página
    com o mesmo cabeçalho e a mesma tabela; termos e totais só na última."""
    grupos, atual, y = [], [], 493.89
    for item in o["itens"]:
        altura = _altura(_linhas_do_item(item))
        if atual and y - altura < 140:
            grupos.append(atual)
            atual, y = [], 493.89
        atual.append(item)
        y -= altura
    grupos.append(atual)
    paginas = []
    for indice, itens in enumerate(grupos, 1):
        p = Pagina()
        _cabecalho(p, o, indice, len(grupos))
        if indice == 1:
            _blocos(p, o)
        _moldura(p)
        y = 493.89
        for item in itens:
            total = item["preco_centavos"] * item["quantidade"]
            p.texto(367, y, f"{item.get('icms', 0)}%", "F1", 8.3, COR_ITEM)
            p.texto(457, y, brl(item["preco_centavos"]), "F1", 8.3, COR_ITEM, "dir")
            p.texto(500, y, str(item["quantidade"]), "F1", 8.3, COR_ITEM, "dir")
            p.texto(550.3, y, brl(total), "F1", 8.3, COR_ITEM, "dir")
            for texto, fonte in _linhas_do_item(item):
                p.texto(44, y, texto, fonte, 8.3, COR_ITEM)
                y -= 12 if fonte == "F2" else 11
            y -= 6
        if indice == len(grupos):
            p.texto(42, 116, "Termos de pagamento:", "F2", 8.3, COR_TABELA)
            p.texto(160, 116, o["termos_pagamento"], "F1", 8.3, COR_TABELA)
            p.texto(42, 96, "Data prevista para a entrega:", "F2", 8.3, COR_TABELA)
            p.texto(187, 96, o["entrega"], "F1", 8.3, COR_TABELA)
            p.texto(372, 116, "Total (sem imposto)", "F1", 8.5, COR_SEM_IMPOSTO)
            p.texto(550.3, 116, brl(o.get("subtotal_centavos", o["total_centavos"])), "F1", 8.5, COR_SEM_IMPOSTO, "dir")
            p.retangulo(368, 96, 185.28, 15, preencher=FUNDO_TOTAL)
            p.texto(372, 100, "Total", "F1", 8.5, COR_TABELA)
            p.texto(550.3, 100, brl(o["total_centavos"]), "F1", 8.5, COR_TABELA, "dir")
        if indice == len(grupos) and o.get("desconto_centavos"):
            p.texto(372, 82, "Desconto", "F1", 8.5, COR_TABELA)
            p.texto(550.3, 82, brl(o["desconto_centavos"]), "F1", 8.5, COR_TABELA, "dir")
        paginas.append(p)
    return montar_pdf(paginas, logo)


# ----------------------------------------------------------------- fluxo
def _gravar(caminho: Path, dados):
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    if isinstance(dados, bytes):
        temporario.write_bytes(dados)
    else:
        temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(temporario, 0o600)
    os.replace(temporario, caminho)


def nome_do_arquivo(ref: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(ref))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]+", "", sem_acento)[:30] or "Cliente"


class Orcamentos:
    def __init__(self, pasta: str, precos: str, relogio=None):
        self.pasta = Path(os.path.expanduser(pasta))
        self.precos = Path(os.path.expanduser(precos))
        self.relogio = relogio or (lambda: datetime.now(timezone.utc))

    def disponivel(self) -> bool:
        return self.pasta.is_dir() and self.precos.is_file()

    def diagnostico(self) -> str:
        if not self.precos.is_file():
            return "sem precos.json na base"
        if not self.pasta.is_dir():
            return "pasta de orçamentos não existe"
        logo = "com logo" if (self.pasta / "LOGO.jpg").is_file() else "sem logo"
        return f"{len(self._catalogo())} itens com preço, {logo}"

    def _catalogo(self) -> dict:
        dados = json.loads(self.precos.read_text(encoding="utf-8"))
        return {i["sku"].upper(): i for i in dados.get("itens", []) if i.get("status") == "APROVADO"}

    def _proximo_numero(self, agora) -> str:
        """Lê o maior do mês e soma 1, com trava de arquivo. Número usado não volta."""
        mes = agora.astimezone(BRASILIA).strftime("%y%m")
        caminho = self.pasta / "sequencia.json"
        with open(self.pasta / "sequencia.trava", "w") as trava:
            fcntl.flock(trava, fcntl.LOCK_EX)
            try:
                sequencia = json.loads(caminho.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                sequencia = {}
            sequencia[mes] = int(sequencia.get(mes, 0)) + 1
            _gravar(caminho, sequencia)
        return f"ZT{mes}-{sequencia[mes]:04d}"

    def _item(self, bruto, catalogo) -> tuple:
        sku = str(bruto.get("sku", "")).strip().upper()
        valor_quantidade = bruto.get("quantidade", 1)
        if valor_quantidade is None or valor_quantidade == "":
            valor_quantidade = 1
        try:
            quantidade = int(valor_quantidade)
            if isinstance(valor_quantidade, bool) or (isinstance(valor_quantidade, float)
                                                     and not valor_quantidade.is_integer()):
                quantidade = 0
        except (TypeError, ValueError):
            quantidade = 0
        if quantidade < 1:
            raise OrcamentoRecusado(f"Quantidade inválida em {sku or 'um item'}.")
        base = catalogo.get(sku)
        informado = bruto.get("preco_informado_centavos")
        if base is None and not informado:
            raise OrcamentoRecusado(
                f"{sku or 'Item sem SKU'} não tem preço aprovado na base. Diga a Nicolas que não "
                "tem o preço e pergunte o valor; nunca estime.")
        item = dict(base or {"sku": sku, "rotulo": str(bruto.get("rotulo") or sku),
                             "descricao": str(bruto.get("descricao") or ""),
                             "origem": str(bruto.get("origem") or "Brasil")})
        # Correção técnica de Nicolas prevalece sobre a descrição do catálogo.
        # A ausência da chave preserva a base; string vazia remove o texto antigo.
        for campo in ("rotulo", "descricao"):
            if campo in bruto:
                item[campo] = str(bruto[campo] or "")
        aviso = ""
        if informado:
            try:
                item["preco_centavos"] = int(informado)
                if isinstance(informado, bool) or (isinstance(informado, float)
                                                 and not informado.is_integer()):
                    raise ValueError()
            except (TypeError, ValueError):
                raise OrcamentoRecusado(f"Preço informado inválido em {sku}.") from None
            if item["preco_centavos"] <= 0:
                raise OrcamentoRecusado(f"Preço informado inválido em {sku}.")
            item["fonte"] = "valor que você informou"
            item.pop("data", None)
            aviso = f"{sku}: valor que você informou"
        item.update(quantidade=quantidade, icms=0, variante=str(bruto.get("variante") or ""),
                    observacao=str(bruto.get("observacao") or ""))
        return item, aviso

    def preparar(self, pedido: dict) -> dict:
        if not self.disponivel():
            raise OrcamentoRecusado("Orçamento indisponível: " + self.diagnostico() + ".")
        cliente = {k: " ".join(str(v or "").split())
                   for k, v in (pedido.get("cliente") or {}).items()}
        if not cliente.get("nome"):
            raise OrcamentoRecusado("Falta o nome do cliente.")
        faltam = [rotulo for campo, rotulo in OBRIGATORIOS.items() if not cliente.get(campo)]
        for campo in OBRIGATORIOS:
            if not cliente.get(campo):
                cliente[campo] = "Não informado"
        catalogo = self._catalogo()
        itens, avisos = [], []
        for bruto in pedido.get("itens") or []:
            item, aviso = self._item(bruto, catalogo)
            itens.append(item)
            if aviso:
                avisos.append(aviso)
        if not itens:
            raise OrcamentoRecusado("O orçamento precisa de ao menos um item.")
        subtotal = sum(i["preco_centavos"] * i["quantidade"] for i in itens)
        desconto = pedido.get("desconto_centavos", 0)
        if type(desconto) is not int or not 0 <= desconto <= subtotal:
            raise OrcamentoRecusado("Desconto inválido: informe centavos entre zero e o subtotal.")
        if faltam:
            avisos.append("Cadastro incompleto: " + ", ".join(faltam) + ".")
        agora = self.relogio()
        numero = self._proximo_numero(agora)
        codigo = str(pedido.get("codigo_cliente") or "").strip()
        if not re.fullmatch(r"(CU\d{4}-\d{5}|ZC\d{4}-\d{5})", codigo):
            # Nunca inventar um CU: sem o código oficial, vai o de teste.
            codigo = f"ZC{numero[2:6]}-{numero[-4:].zfill(5)}"
        orcamento = {
            "numero": numero, "criado_em": agora.isoformat(), "gerado": False,
            "data_br": agora.astimezone(BRASILIA).strftime("%d/%m/%Y"),
            "ref_cliente": str(pedido.get("ref_cliente") or cliente["nome"].split()[0]),
            "codigo_cliente": codigo, "cliente": cliente,
            "pagamento_extenso": str(pedido.get("pagamento_extenso") or "a combinar").rstrip("."),
            "termos_pagamento": str(pedido.get("termos_pagamento") or "A combinar"),
            "entrega": str(pedido.get("entrega") or "A combinar"),
            "itens": itens,
            "subtotal_centavos": subtotal, "desconto_centavos": desconto,
            "total_centavos": subtotal - desconto,
            "avisos": avisos,
        }
        (self.pasta / "rascunhos").mkdir(mode=0o700, exist_ok=True)
        _gravar(self.pasta / "rascunhos" / f"{numero}.json", orcamento)
        return {"numero": numero, "resumo": self.resumo(orcamento)}

    def resumo(self, o) -> str:
        c = o["cliente"]
        documento = "CPF" if len(so_digitos(c["doc"])) == 11 else "CNPJ"
        linhas = [f"Orçamento {o['numero']} (teste), pra confirmar:", "",
                  f"Cliente: {c['nome']} · {c['razao_social']}",
                  f"{documento} {c['doc']}" + (f" · IE {c['ie']}" if c.get("ie") else "")
                  + f" · {c['cidade']}-{c['uf']}",
                  f"Ref.: {o['ref_cliente']} · Código: {o['codigo_cliente']}", ""]
        for i in o["itens"]:
            linhas.append(f"{i['quantidade']} × {i['sku']} {i['rotulo']}"
                          + (f" ({i['variante']})" if i.get("variante") else ""))
            origem = i.get("fonte", "") + (f", {i['data']}" if i.get("data") else "")
            linhas.append(f"    {reais(i['preco_centavos'])} cada ({origem})")
            for campo in ("descricao", "variante", "observacao"):
                if i.get(campo):
                    linhas.append(f"    {campo.capitalize()}: {i[campo]}")
        if o.get("desconto_centavos"):
            linhas += [f"Subtotal: {reais(o['subtotal_centavos'])}",
                       f"Desconto: {reais(o['desconto_centavos'])}"]
        linhas.extend(o.get("avisos", []))
        linhas += [f"Total: {reais(o['total_centavos'])} (ICMS 0%)", "",
                   f"Pagamento: {o['pagamento_extenso']}", f"Entrega: {o['entrega']}",
                   "Frete: por conta do cliente (não entra no orçamento)", "",
                   "Posso gerar o PDF?"]
        return "\n".join(linhas)

    def _ler_rascunho(self, numero=""):
        if not numero:
            arquivos = list((self.pasta / "rascunhos").glob("ZT*.json"))
            if not arquivos:
                raise OrcamentoRecusado("Não há orçamento preparado.")
            numero = max(arquivos, key=lambda p: p.stat().st_mtime).stem
        if not re.fullmatch(r"ZT\d{4}-\d{4,}", str(numero)):
            raise OrcamentoRecusado("Número de orçamento inválido.")
        try:
            return json.loads((self.pasta / "rascunhos" / (str(numero) + ".json")).read_text())
        except (OSError, ValueError):
            raise OrcamentoRecusado(f"Não há orçamento {numero}.") from None

    def consultar(self, numero=""):
        o = self._ler_rascunho(numero)
        return {"numero": o["numero"], "gerado": bool(o.get("gerado")),
                "cliente": o["cliente"], "itens": o["itens"],
                "total_centavos": o["total_centavos"],
                "desconto_centavos": o.get("desconto_centavos", 0),
                "pagamento_extenso": o["pagamento_extenso"], "entrega": o["entrega"],
                "resumo": self.resumo(o).removesuffix("\n\nPosso gerar o PDF?")}

    def revisar(self, numero, alteracoes):
        """Revisão incremental preserva os dados que Nicolas não mudou."""
        o = self._ler_rascunho(numero)
        campos = {"cliente", "itens", "desconto_centavos", "pagamento_extenso",
                  "termos_pagamento", "entrega", "ref_cliente"}
        if not isinstance(alteracoes, dict) or not alteracoes or set(alteracoes) - campos:
            raise OrcamentoRecusado("Informe apenas os campos do orçamento que deseja alterar.")
        if "itens" in alteracoes and not isinstance(alteracoes["itens"], list):
            raise OrcamentoRecusado("Alterações de itens precisam vir como lista.")
        pedido = {k: o[k] for k in ("pagamento_extenso", "termos_pagamento", "entrega", "ref_cliente")}
        pedido["cliente"] = {k: v for k, v in o["cliente"].items() if v != "Não informado"}
        pedido["codigo_cliente"] = o["codigo_cliente"]
        pedido["desconto_centavos"] = o.get("desconto_centavos", 0)
        itens = []
        for item in o["itens"]:
            novo = {k: item[k] for k in ("sku", "rotulo", "descricao", "quantidade", "variante", "observacao") if k in item}
            if item.get("fonte") == "valor que você informou":
                novo["preco_informado_centavos"] = item["preco_centavos"]
            itens.append(novo)
        if "cliente" in alteracoes:
            if not isinstance(alteracoes["cliente"], dict):
                raise OrcamentoRecusado("Cliente precisa vir como objeto.")
            pedido["cliente"].update(alteracoes["cliente"])
        for mudanca in alteracoes.get("itens", []):
            permitidos = {"indice", "descricao", "rotulo", "variante", "observacao",
                          "quantidade", "preco_informado_centavos"}
            if not isinstance(mudanca, dict) or set(mudanca) - permitidos:
                raise OrcamentoRecusado("Alteração de item inválida.")
            indice = mudanca.get("indice")
            if type(indice) is not int or not 1 <= indice <= len(itens):
                raise OrcamentoRecusado("Índice de item inválido; conte a partir de 1.")
            itens[indice - 1].update({k: v for k, v in mudanca.items() if k != "indice"})
        pedido.update({k: v for k, v in alteracoes.items() if k not in ("cliente", "itens")})
        pedido["itens"] = itens
        r = self.preparar(pedido)
        caminho = self.pasta / "rascunhos" / (r["numero"] + ".json")
        dados = json.loads(caminho.read_text())
        dados["substitui"] = o["numero"]
        _gravar(caminho, dados)
        return dict(r, substitui=o["numero"])

    def gerar(self, numero: str, inicio_do_turno, mensagem: str) -> dict:
        caminho = self.pasta / "rascunhos" / f"{Path(str(numero)).name}.json"
        try:
            o = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise OrcamentoRecusado(f"Não há rascunho {numero}. Prepare o orçamento antes.") from None
        if o.get("gerado"):
            raise OrcamentoRecusado(f"{numero} já foi gerado. Mudança pede um orçamento novo.")
        if inicio_do_turno is None or datetime.fromisoformat(o["criado_em"]) >= inicio_do_turno:
            raise OrcamentoRecusado("Mostre o resumo e espere Nicolas confirmar numa mensagem "
                                    "nova antes de gerar.")
        if not CONFIRMACAO.search(mensagem or ""):
            raise OrcamentoRecusado("A mensagem de Nicolas não confirma o orçamento. "
                                    "Pergunte se pode gerar.")
        logo = self.pasta / "LOGO.jpg"
        pdf = desenhar(o, logo.read_bytes() if logo.is_file() else b"")
        nome = f"Orcamento_{o['numero']}_{nome_do_arquivo(o['ref_cliente'])}.pdf"
        _gravar(self.pasta / nome, pdf)
        o.update(gerado=True, arquivo=nome)
        _gravar(self.pasta / f"{o['numero']}.json", o)
        _gravar(caminho, o)
        return {"numero": o["numero"], "arquivo": str(self.pasta / nome)}
