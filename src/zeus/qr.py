"""Gerador de QR Code em Python puro, para o pareamento do celular.

O pareamento mostra na tela do PC um QR com o endereço da HUD e um nonce de
uso único. Gerar esse QR no navegador exigiria uma biblioteca de CDN (que a
HUD não carrega, por princípio) e gerar no servidor com pacote externo
quebraria a regra de só biblioteca padrão. O QR cabe em poucas centenas de
linhas: modo byte (UTF-8), versões 1 a 10, Reed-Solomon em GF(256) e as oito
máscaras do padrão ISO/IEC 18004, com saída em SVG.

Só o necessário para o caso de uso: uma URL com nonce tem ~70 bytes e cabe na
versão 5-M; a versão 10 (213 bytes no nível M) dá folga de sobra. Não há modo
numérico, alfanumérico, kanji nem ECI: o modo byte lê qualquer texto e todo
leitor de celular trata os bytes como UTF-8.
"""

# Nível de correção -> os 2 bits que vão na informação de formato. A ordem
# estranha (M=00) é a do padrão, não um engano.
BITS_ECC = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

# Por versão e nível: (codewords de correção por bloco, [(blocos, codewords de
# dados por bloco), ...]). Tabela 9 do ISO/IEC 18004, versões 1 a 10. O total
# de cada versão é conferido contra a geometria em `_codewords_totais`.
BLOCOS = {
    1: {"L": (7, [(1, 19)]), "M": (10, [(1, 16)]), "Q": (13, [(1, 13)]), "H": (17, [(1, 9)])},
    2: {"L": (10, [(1, 34)]), "M": (16, [(1, 28)]), "Q": (22, [(1, 22)]), "H": (28, [(1, 16)])},
    3: {"L": (15, [(1, 55)]), "M": (26, [(1, 44)]), "Q": (18, [(2, 17)]), "H": (22, [(2, 13)])},
    4: {"L": (20, [(1, 80)]), "M": (18, [(2, 32)]), "Q": (26, [(2, 24)]), "H": (16, [(4, 9)])},
    5: {"L": (26, [(1, 108)]), "M": (24, [(2, 43)]),
        "Q": (18, [(2, 15), (2, 16)]), "H": (22, [(2, 11), (2, 12)])},
    6: {"L": (18, [(2, 68)]), "M": (16, [(4, 27)]), "Q": (24, [(4, 19)]), "H": (28, [(4, 15)])},
    7: {"L": (20, [(2, 78)]), "M": (18, [(4, 31)]),
        "Q": (18, [(2, 14), (4, 15)]), "H": (26, [(4, 13), (1, 14)])},
    8: {"L": (24, [(2, 97)]), "M": (22, [(2, 38), (2, 39)]),
        "Q": (22, [(4, 18), (2, 19)]), "H": (26, [(4, 14), (2, 15)])},
    9: {"L": (30, [(2, 116)]), "M": (22, [(3, 36), (2, 37)]),
        "Q": (20, [(4, 16), (4, 17)]), "H": (24, [(4, 12), (4, 13)])},
    10: {"L": (18, [(2, 68), (2, 69)]), "M": (26, [(4, 43), (1, 44)]),
         "Q": (24, [(6, 19), (2, 20)]), "H": (28, [(6, 15), (2, 16)])},
}

# Centros dos padrões de alinhamento (Anexo E). A versão 1 não tem nenhum.
ALINHAMENTO = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

VERSAO_MAXIMA = 10
_MODO_BYTE = 0b0100


# --- Reed-Solomon em GF(256), polinômio primitivo x^8+x^4+x^3+x^2+1 (0x11D) ---

def _tabelas_gf():
    exp, log = [0] * 512, [0] * 256
    valor = 1
    for i in range(255):
        exp[i] = valor
        log[valor] = i
        valor <<= 1
        if valor & 0x100:
            valor ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]  # dobra a tabela para dispensar o módulo 255
    return exp, log


GF_EXP, GF_LOG = _tabelas_gf()


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]


def _gerador_rs(grau: int) -> list:
    """Produto de (x - α^i), i = 0..grau-1, do termo de maior grau ao menor."""
    gerador = [1]
    for i in range(grau):
        proximo = [0] * (len(gerador) + 1)
        for j, coef in enumerate(gerador):
            proximo[j] ^= coef
            proximo[j + 1] ^= gf_mul(coef, GF_EXP[i])
        gerador = proximo
    return gerador


def reed_solomon(dados: list, grau: int) -> list:
    """Resto da divisão de dados·x^grau pelo gerador: os codewords de correção."""
    gerador = _gerador_rs(grau)
    resto = list(dados) + [0] * grau
    for i in range(len(dados)):
        fator = resto[i]
        if fator:
            for j in range(1, len(gerador)):
                resto[i + j] ^= gf_mul(gerador[j], fator)
    return resto[len(dados):]


# --- códigos BCH da informação de formato e de versão ---

def _bch(valor: int, gerador: int, bits_resto: int) -> int:
    resto = valor << bits_resto
    grau = gerador.bit_length() - 1
    for deslocamento in range(resto.bit_length() - 1, grau - 1, -1):
        if resto >> deslocamento & 1:
            resto ^= gerador << (deslocamento - grau)
    return (valor << bits_resto) | resto


def bits_de_formato(ecc: str, mascara: int) -> int:
    """15 bits: 2 de ECC + 3 de máscara + 10 de BCH(15,5), com o XOR 0x5412
    que impede um formato todo claro (que se confundiria com área vazia)."""
    return _bch(BITS_ECC[ecc] << 3 | mascara, 0x537, 10) ^ 0x5412


def bits_de_versao(versao: int) -> int:
    """18 bits: 6 da versão + 12 de BCH(18,6), gerador 0x1F25 (versão >= 7)."""
    return _bch(versao, 0x1F25, 12)


# --- capacidade e codificação dos dados ---

def _bits_contagem(versao: int) -> int:
    return 8 if versao <= 9 else 16


def codewords_de_dados(versao: int, ecc: str) -> int:
    _, grupos = BLOCOS[versao][ecc]
    return sum(qtd * tamanho for qtd, tamanho in grupos)


def capacidade_bytes(versao: int, ecc: str) -> int:
    """Quantos bytes de texto cabem: o resto são 4 bits de modo e a contagem."""
    return (codewords_de_dados(versao, ecc) * 8 - 4 - _bits_contagem(versao)) // 8


def escolher_versao(tamanho: int, ecc: str) -> int:
    for versao in range(1, VERSAO_MAXIMA + 1):
        if tamanho <= capacidade_bytes(versao, ecc):
            return versao
    raise ValueError(
        f"texto de {tamanho} bytes não cabe num QR versão {VERSAO_MAXIMA} nível {ecc} "
        f"(máximo {capacidade_bytes(VERSAO_MAXIMA, ecc)} bytes); encurte o texto ou "
        "use um nível de correção menor")


def _codificar_dados(dados: bytes, versao: int, ecc: str) -> list:
    bits = []

    def poe(valor, quantos):
        bits.extend((valor >> i) & 1 for i in range(quantos - 1, -1, -1))

    poe(_MODO_BYTE, 4)
    poe(len(dados), _bits_contagem(versao))
    for byte in dados:
        poe(byte, 8)
    capacidade = codewords_de_dados(versao, ecc) * 8
    poe(0, min(4, capacidade - len(bits)))  # terminador, se couber
    poe(0, -len(bits) % 8)
    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    enchimento = (0xEC, 0x11)  # bytes de enchimento alternados do padrão
    for i in range(codewords_de_dados(versao, ecc) - len(codewords)):
        codewords.append(enchimento[i % 2])
    return codewords


def _intercalar(codewords: list, versao: int, ecc: str) -> list:
    """Divide em blocos, calcula a correção de cada um e intercala coluna a
    coluna: um arranhão no QR estraga um pouco de vários blocos em vez de
    destruir um só."""
    grau, grupos = BLOCOS[versao][ecc]
    blocos, pos = [], 0
    for qtd, tamanho in grupos:
        for _ in range(qtd):
            blocos.append(codewords[pos:pos + tamanho])
            pos += tamanho
    correcoes = [reed_solomon(bloco, grau) for bloco in blocos]
    saida = []
    for i in range(max(len(b) for b in blocos)):
        saida.extend(b[i] for b in blocos if i < len(b))
    for i in range(grau):
        saida.extend(c[i] for c in correcoes)
    return saida


# --- a matriz ---

class _Matriz:
    def __init__(self, versao: int):
        self.versao = versao
        self.tamanho = 17 + 4 * versao
        self.escuro = [[False] * self.tamanho for _ in range(self.tamanho)]
        self.funcao = [[False] * self.tamanho for _ in range(self.tamanho)]

    def poe(self, x, y, escuro):
        self.escuro[y][x] = bool(escuro)
        self.funcao[y][x] = True

    def padroes_de_funcao(self):
        n = self.tamanho
        for i in range(n):  # timing: alterna na linha e na coluna 6
            self.poe(6, i, i % 2 == 0)
            self.poe(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            self._localizador(cx, cy)
        centros = ALINHAMENTO[self.versao]
        for cy in centros:
            for cx in centros:
                # Os três cantos dos localizadores ficam sem alinhamento.
                if (cx, cy) in ((6, 6), (6, centros[-1]), (centros[-1], 6)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.poe(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        # Reserva as áreas de formato e versão; o valor vem depois da máscara.
        self.formato(0)
        if self.versao >= 7:
            self._versao()

    def _localizador(self, cx, cy):
        # 7x7 com anel claro, mais o separador claro em volta (9x9 cortado).
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < self.tamanho and 0 <= y < self.tamanho:
                    distancia = max(abs(dx), abs(dy))
                    self.poe(x, y, distancia not in (2, 4))

    def formato(self, bits):
        n = self.tamanho
        b = [(bits >> i) & 1 for i in range(15)]
        # Primeira cópia, em volta do localizador do canto superior esquerdo.
        for i in range(6):
            self.poe(8, i, b[i])
        self.poe(8, 7, b[6])
        self.poe(8, 8, b[7])
        self.poe(7, 8, b[8])
        for i in range(9, 15):
            self.poe(14 - i, 8, b[i])
        # Segunda cópia, dividida entre os outros dois localizadores.
        for i in range(8):
            self.poe(n - 1 - i, 8, b[i])
        for i in range(8, 15):
            self.poe(8, n - 15 + i, b[i])
        self.poe(8, n - 8, True)  # o módulo escuro fixo

    def _versao(self):
        bits = bits_de_versao(self.versao)
        n = self.tamanho
        for i in range(18):
            bit = (bits >> i) & 1
            a, b = n - 11 + i % 3, i // 3
            self.poe(a, b, bit)
            self.poe(b, a, bit)

    def zigue_zague(self):
        """Ordem de leitura dos módulos de dados: colunas de 2, da direita
        para a esquerda, subindo e descendo alternadamente, pulando a coluna
        do timing vertical."""
        n = self.tamanho
        direita = n - 1
        while direita >= 1:
            if direita == 6:
                direita = 5
            subindo = ((direita + 1) & 2) == 0
            for vertical in range(n):
                y = n - 1 - vertical if subindo else vertical
                for j in range(2):
                    x = direita - j
                    if not self.funcao[y][x]:
                        yield x, y
            direita -= 2

    def colocar(self, codewords):
        bits = [(c >> (7 - i)) & 1 for c in codewords for i in range(8)]
        for indice, (x, y) in enumerate(self.zigue_zague()):
            # Sobram 0 a 7 módulos de resto; ficam claros, como manda o padrão.
            self.escuro[y][x] = bool(indice < len(bits) and bits[indice])

    def aplicar_mascara(self, mascara):
        condicao = MASCARAS[mascara]
        for y in range(self.tamanho):
            for x in range(self.tamanho):
                if not self.funcao[y][x] and condicao(x, y):
                    self.escuro[y][x] = not self.escuro[y][x]


# Condição de inversão de cada máscara; x é a coluna, y a linha.
MASCARAS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (y // 2 + x // 3) % 2 == 0,
    lambda x, y: (x * y) % 2 + (x * y) % 3 == 0,
    lambda x, y: ((x * y) % 2 + (x * y) % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + (x * y) % 3) % 2 == 0,
]

_PADRAO_LOCALIZADOR = ((1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0), (0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1))


def penalidade(escuro: list) -> int:
    """As quatro regras do ISO/IEC 18004 (7.8.3): a máscara escolhida é a que
    deixa o símbolo mais fácil de ler para a câmera."""
    n = len(escuro)
    linhas = [list(map(int, linha)) for linha in escuro]
    colunas = [list(c) for c in zip(*linhas)]
    pontos = 0
    for faixa in linhas + colunas:
        # Regra 1: sequência de 5 ou mais módulos iguais vale 3 + (excesso).
        corrida = 1
        for i in range(1, n + 1):
            if i < n and faixa[i] == faixa[i - 1]:
                corrida += 1
            else:
                if corrida >= 5:
                    pontos += corrida - 2
                corrida = 1
        # Regra 3: algo parecido com localizador (1:1:3:1:1 com 4 claros de um
        # lado) confunde o detector; a zona de silêncio conta como clara.
        estendida = [0] * 4 + faixa + [0] * 4
        for i in range(len(estendida) - 10):
            if tuple(estendida[i:i + 11]) in _PADRAO_LOCALIZADOR:
                pontos += 40
    # Regra 2: cada bloco 2x2 da mesma cor vale 3.
    for y in range(n - 1):
        for x in range(n - 1):
            if linhas[y][x] == linhas[y][x + 1] == linhas[y + 1][x] == linhas[y + 1][x + 1]:
                pontos += 3
    # Regra 4: 10 pontos a cada 5% de desvio da proporção ideal de 50% escuro.
    total = n * n
    escuros = sum(map(sum, linhas))
    k = (abs(escuros * 20 - total * 10) + total - 1) // total - 1
    pontos += max(0, k) * 10
    return pontos


def _codewords_totais(versao: int) -> int:
    """Módulos livres para dados dividido por 8, contado na geometria real."""
    matriz = _Matriz(versao)
    matriz.padroes_de_funcao()
    return sum(1 for _ in matriz.zigue_zague()) // 8


def qr_matriz(texto: str, ecc: str = "M", versao: int = None, mascara: int = None) -> list:
    """Matriz do QR (True = escuro), sem a zona de silêncio.

    `versao` e `mascara` existem para os testes forçarem cada caso; no uso
    normal a menor versão que couber e a máscara de menor penalidade são
    escolhidas sozinhas."""
    ecc = (ecc or "M").upper()
    if ecc not in BITS_ECC:
        raise ValueError(f"nível de correção desconhecido: {ecc!r} (use L, M, Q ou H)")
    dados = texto.encode("utf-8")
    minima = escolher_versao(len(dados), ecc)
    if versao is None:
        versao = minima
    elif not minima <= versao <= VERSAO_MAXIMA:
        raise ValueError(f"texto de {len(dados)} bytes não cabe na versão {versao} nível {ecc}"
                         if versao < minima else f"versão {versao} fora de 1..{VERSAO_MAXIMA}")
    codewords = _intercalar(_codificar_dados(dados, versao, ecc), versao, ecc)
    base = _Matriz(versao)
    base.padroes_de_funcao()
    base.colocar(codewords)
    candidatas = range(8) if mascara is None else [mascara]
    melhor, melhor_pontos = None, None
    for candidata in candidatas:
        matriz = _Matriz(versao)
        matriz.escuro = [linha[:] for linha in base.escuro]
        matriz.funcao = base.funcao
        matriz.aplicar_mascara(candidata)
        matriz.formato(bits_de_formato(ecc, candidata))
        pontos = penalidade(matriz.escuro)
        if melhor_pontos is None or pontos < melhor_pontos:
            melhor, melhor_pontos = matriz, pontos
    return melhor.escuro


def qr_svg(texto: str, ecc: str = "M", modulo: int = 8, borda: int = 4) -> str:
    """SVG com um único <path> dos módulos escuros sobre fundo branco.

    O fundo é explícito porque a HUD é escura: um QR transparente sobre fundo
    preto inverte as cores e muitos leitores não aceitam. A borda de 4 módulos
    é a zona de silêncio do padrão. Cada módulo vira um quadrado em unidades
    de módulo e `modulo` só escala o tamanho final; crispEdges evita costuras
    de antisserrilhado entre quadrados vizinhos."""
    matriz = qr_matriz(texto, ecc)
    n = len(matriz)
    lado = n + 2 * borda
    pixels = lado * modulo
    trechos = []
    for y, linha in enumerate(matriz):
        x = 0
        while x < n:
            if linha[x]:
                inicio = x
                while x < n and linha[x]:
                    x += 1
                # Junta módulos escuros vizinhos da linha num só retângulo.
                trechos.append(f"M{inicio + borda} {y + borda}h{x - inicio}v1h-{x - inicio}z")
            else:
                x += 1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{pixels}" height="{pixels}" '
            f'viewBox="0 0 {lado} {lado}" shape-rendering="crispEdges">'
            f'<rect width="{lado}" height="{lado}" fill="#ffffff"/>'
            f'<path fill="#000000" d="{"".join(trechos)}"/></svg>')
