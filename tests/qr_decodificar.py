"""Decodificador mínimo de QR, escrito à parte só para conferir o gerador.

Não importa nada de `zeus.qr`: as tabelas, o corpo finito, as posições de
alinhamento (aqui pela fórmula, lá por tabela) e a leitura em zigue-zague são
refeitos de outro jeito, para que um erro no gerador não se esconda atrás do
mesmo erro no conferidor. Lê o formato (as duas cópias, conferindo o BCH),
a versão (versão >= 7), desfaz a máscara, junta os codewords, desintercala os
blocos, exige síndromes Reed-Solomon todas zero e só então lê o modo byte.

Não corrige erros: qualquer módulo trocado é falha, que é o que um teste quer.
"""


class ErroDeLeitura(ValueError):
    pass


# Por versão e nível: lista de (quantidade de blocos, codewords no bloco,
# codewords de dados no bloco), na notação (c, k) do ISO/IEC 18004.
TABELA = {
    1: {"L": [(1, 26, 19)], "M": [(1, 26, 16)], "Q": [(1, 26, 13)], "H": [(1, 26, 9)]},
    2: {"L": [(1, 44, 34)], "M": [(1, 44, 28)], "Q": [(1, 44, 22)], "H": [(1, 44, 16)]},
    3: {"L": [(1, 70, 55)], "M": [(1, 70, 44)], "Q": [(2, 35, 17)], "H": [(2, 35, 13)]},
    4: {"L": [(1, 100, 80)], "M": [(2, 50, 32)], "Q": [(2, 50, 24)], "H": [(4, 25, 9)]},
    5: {"L": [(1, 134, 108)], "M": [(2, 67, 43)],
        "Q": [(2, 33, 15), (2, 34, 16)], "H": [(2, 33, 11), (2, 34, 12)]},
    6: {"L": [(2, 86, 68)], "M": [(4, 43, 27)], "Q": [(4, 43, 19)], "H": [(4, 43, 15)]},
    7: {"L": [(2, 98, 78)], "M": [(4, 49, 31)],
        "Q": [(2, 32, 14), (4, 33, 15)], "H": [(4, 39, 13), (1, 40, 14)]},
    8: {"L": [(2, 121, 97)], "M": [(2, 60, 38), (2, 61, 39)],
        "Q": [(4, 40, 18), (2, 41, 19)], "H": [(4, 40, 14), (2, 41, 15)]},
    9: {"L": [(2, 146, 116)], "M": [(3, 58, 36), (2, 59, 37)],
        "Q": [(4, 36, 16), (4, 37, 17)], "H": [(4, 36, 12), (4, 37, 13)]},
    10: {"L": [(2, 86, 68), (2, 87, 69)], "M": [(4, 69, 43), (1, 70, 44)],
         "Q": [(6, 43, 19), (2, 44, 20)], "H": [(6, 43, 15), (2, 44, 16)]},
}

NIVEL_POR_BITS = {0b01: "L", 0b00: "M", 0b11: "Q", 0b10: "H"}


# --- GF(256) por multiplicação "camponesa", sem tabelas de log ---

def gf_vezes(a, b):
    produto = 0
    while b:
        if b & 1:
            produto ^= a
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
        b >>= 1
    return produto


def gf_potencia_de_alfa(expoente):
    valor = 1
    for _ in range(expoente):
        valor = gf_vezes(valor, 2)
    return valor


def sindromes(bloco, grau):
    """S_i = C(α^i), i = 0..grau-1, com C de coeficientes do mais alto ao mais baixo."""
    saida = []
    for i in range(grau):
        ponto = gf_potencia_de_alfa(i)
        acumulado = 0
        for coef in bloco:  # Horner
            acumulado = gf_vezes(acumulado, ponto) ^ coef
        saida.append(acumulado)
    return saida


def resto_gf2(valor, gerador):
    """Resto da divisão de polinômios sobre GF(2)."""
    grau = gerador.bit_length() - 1
    while valor.bit_length() - 1 >= grau:
        valor ^= gerador << (valor.bit_length() - 1 - grau)
    return valor


# --- geometria ---

def posicoes_alinhamento(versao):
    if versao == 1:
        return []
    quantos = versao // 7 + 2
    lado = 17 + 4 * versao
    passo = (versao * 8 + quantos * 3 + 5) // (quantos * 4 - 4) * 2
    return [6] + sorted(lado - 7 - i * passo for i in range(quantos - 1))


def mapa_de_funcao(versao):
    lado = 17 + 4 * versao
    reservado = [[False] * lado for _ in range(lado)]

    def marca(linha0, coluna0, altura, largura):
        for linha in range(max(0, linha0), min(lado, linha0 + altura)):
            for coluna in range(max(0, coluna0), min(lado, coluna0 + largura)):
                reservado[linha][coluna] = True

    marca(0, 0, 9, 9)              # localizador + separador + formato
    marca(0, lado - 8, 9, 8)       # canto superior direito + formato
    marca(lado - 8, 0, 8, 9)       # canto inferior esquerdo + formato + escuro
    # Antes do timing: só os localizadores podem barrar um alinhamento.
    centros = posicoes_alinhamento(versao)
    for linha in centros:
        for coluna in centros:
            if reservado[linha][coluna]:
                continue  # encostaria num localizador
            marca(linha - 2, coluna - 2, 5, 5)
    marca(6, 0, 1, lado)           # timing horizontal
    marca(0, 6, lado, 1)           # timing vertical
    if versao >= 7:
        marca(0, lado - 11, 6, 3)
        marca(lado - 11, 0, 3, 6)
    return reservado


# Coordenadas (linha, coluna) dos bits de formato, do bit 14 ao bit 0.
def coordenadas_formato(lado):
    primeira = ([(8, c) for c in (0, 1, 2, 3, 4, 5, 7, 8)] + [(7, 8)]
                + [(l, 8) for l in (5, 4, 3, 2, 1, 0)])
    segunda = ([(l, 8) for l in range(lado - 1, lado - 8, -1)]
               + [(8, c) for c in range(lado - 8, lado)])
    return primeira, segunda


def ler_formato(matriz):
    """Devolve (nível, máscara, bits crus) lendo e conferindo as duas cópias."""
    lado = len(matriz)
    copias = []
    for coordenadas in coordenadas_formato(lado):
        valor = 0
        for linha, coluna in coordenadas:
            valor = valor << 1 | int(matriz[linha][coluna])
        copias.append(valor)
    if copias[0] != copias[1]:
        raise ErroDeLeitura(f"cópias do formato diferem: {copias[0]:015b} x {copias[1]:015b}")
    sem_xor = copias[0] ^ 0x5412
    if resto_gf2(sem_xor, 0x537) != 0:
        raise ErroDeLeitura(f"BCH do formato não confere: {copias[0]:015b}")
    dados = sem_xor >> 10
    return NIVEL_POR_BITS[dados >> 3], dados & 0b111, copias[0]


def ler_versao(matriz):
    lado = len(matriz)
    if (lado - 17) % 4 or not 21 <= lado <= 57:
        raise ErroDeLeitura(f"lado {lado} não é de QR versão 1..10")
    versao = (lado - 17) // 4
    if versao < 7:
        return versao
    leituras = []
    for transposta in (False, True):
        valor = 0
        for i in range(17, -1, -1):
            a, b = i // 3, lado - 11 + i % 3
            linha, coluna = (b, a) if transposta else (a, b)
            valor = valor << 1 | int(matriz[linha][coluna])
        leituras.append(valor)
    for valor in leituras:
        if resto_gf2(valor, 0x1F25) != 0 or valor >> 12 != versao:
            raise ErroDeLeitura(f"informação de versão inválida: {valor:018b}")
    return versao


def mascara_inverte(mascara, i, j):
    """i é a linha, j a coluna, como no texto do padrão."""
    return [
        (i + j) % 2 == 0,
        i % 2 == 0,
        j % 3 == 0,
        (i + j) % 3 == 0,
        (i // 2 + j // 3) % 2 == 0,
        (i * j) % 2 + (i * j) % 3 == 0,
        ((i * j) % 2 + (i * j) % 3) % 2 == 0,
        ((i + j) % 2 + (i * j) % 3) % 2 == 0,
    ][mascara]


def ler_bits(matriz, versao, mascara):
    lado = len(matriz)
    reservado = mapa_de_funcao(versao)
    bits = []
    coluna = lado - 1
    para_cima = True
    while coluna > 0:
        if coluna == 6:
            coluna -= 1
        linhas = range(lado - 1, -1, -1) if para_cima else range(lado)
        for linha in linhas:
            for c in (coluna, coluna - 1):
                if not reservado[linha][c]:
                    bits.append(int(matriz[linha][c]) ^ int(mascara_inverte(mascara, linha, c)))
        para_cima = not para_cima
        coluna -= 2
    return bits


def decodificar(matriz, devolver_detalhes=False):
    """Lê a matriz (True = escuro, sem zona de silêncio) e devolve o texto."""
    versao = ler_versao(matriz)
    nivel, mascara, _ = ler_formato(matriz)
    bits = ler_bits(matriz, versao, mascara)
    blocos_def = [(c, k) for qtd, c, k in TABELA[versao][nivel] for _ in range(qtd)]
    total = sum(c for c, _ in blocos_def)
    if len(bits) // 8 != total:
        raise ErroDeLeitura(f"geometria dá {len(bits) // 8} codewords, tabela {total}")
    codewords = [int("".join(map(str, bits[i * 8:i * 8 + 8])), 2) for i in range(total)]
    # Desintercala: primeiro os dados coluna a coluna, depois a correção.
    dados = [[] for _ in blocos_def]
    correcao = [[] for _ in blocos_def]
    pos = 0
    for i in range(max(k for _, k in blocos_def)):
        for b, (_, k) in enumerate(blocos_def):
            if i < k:
                dados[b].append(codewords[pos])
                pos += 1
    grau = blocos_def[0][0] - blocos_def[0][1]
    for _ in range(grau):
        for b in range(len(blocos_def)):
            correcao[b].append(codewords[pos])
            pos += 1
    for b in range(len(blocos_def)):
        s = sindromes(dados[b] + correcao[b], grau)
        if any(s):
            raise ErroDeLeitura(f"síndromes RS do bloco {b} não são zero: {s}")
    fluxo = "".join(format(c, "08b") for bloco in dados for c in bloco)
    if fluxo[:4] != "0100":
        raise ErroDeLeitura(f"modo {fluxo[:4]} não é byte")
    tamanho_contagem = 8 if versao <= 9 else 16
    quantos = int(fluxo[4:4 + tamanho_contagem], 2)
    inicio = 4 + tamanho_contagem
    fim = inicio + 8 * quantos
    if fim > len(fluxo):
        raise ErroDeLeitura("contagem maior que os dados")
    carga = bytes(int(fluxo[i:i + 8], 2) for i in range(inicio, fim, 8))
    # Depois dos dados: até 4 zeros de terminador, zeros até fechar o byte, e
    # enchimento 0xEC/0x11 alternado.
    resto = fluxo[fim:]
    terminador = min(4, len(resto))
    if resto[:terminador].strip("0"):
        raise ErroDeLeitura("terminador não é zero")
    alinhado = fim + terminador + (-(fim + terminador) % 8)
    if fluxo[fim + terminador:alinhado].strip("0"):
        raise ErroDeLeitura("bits de alinhamento não são zero")
    enchimento = [int(fluxo[i:i + 8], 2) for i in range(alinhado, len(fluxo), 8)]
    if enchimento != [(0xEC, 0x11)[i % 2] for i in range(len(enchimento))]:
        raise ErroDeLeitura(f"enchimento inesperado: {enchimento[:4]}")
    texto = carga.decode("utf-8")
    if devolver_detalhes:
        return texto, {"versao": versao, "ecc": nivel, "mascara": mascara}
    return texto
