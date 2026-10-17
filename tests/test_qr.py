"""Gerador de QR (zeus.qr), conferido sem depender de leitor externo.

Três camadas: valores conhecidos do padrão (Reed-Solomon do exemplo clássico
"HELLO WORLD" 1-M, bits de formato e de versão tabelados), propriedades
estruturais da matriz e ida e volta pelo decodificador independente em
tests/qr_decodificar.py. Se o sistema tiver libzbar ou libZXing, o QR também
passa por eles via ctypes; sem elas, esses testes se pulam.
"""

import ctypes
import ctypes.util
import re
import unittest

from qr_decodificar import ErroDeLeitura, decodificar, resto_gf2
from zeus import qr

URL = "https://192.168.100.221:8770/parear#n=Jr2wQ9-xK_fA0bLmZ3cVtw"

TEXTOS = [
    "",
    "a",
    "Zeus",
    URL,
    "pareamento ção",
    "ação, coração, pão, maçã — ñ ü € 😀",
    "x" * 100,
    "0123456789" * 20,
    "".join(chr(32 + i % 95) for i in range(150)),
]

# Capacidade em bytes do modo byte, tabela 7 do ISO/IEC 18004.
CAPACIDADE_ISO = {
    1: (17, 14, 11, 7), 2: (32, 26, 20, 14), 3: (53, 42, 32, 24), 4: (78, 62, 46, 34),
    5: (106, 84, 60, 44), 6: (134, 106, 74, 58), 7: (154, 122, 86, 64),
    8: (192, 152, 108, 84), 9: (230, 180, 130, 98), 10: (271, 213, 151, 119),
}


def ler_formato_cru(matriz):
    """As duas cópias de 15 bits, do bit 14 ao 0, lidas direto da matriz."""
    n = len(matriz)
    a = [matriz[8][c] for c in (0, 1, 2, 3, 4, 5, 7, 8)] + [matriz[7][8]] + \
        [matriz[l][8] for l in (5, 4, 3, 2, 1, 0)]
    b = [matriz[l][8] for l in range(n - 1, n - 8, -1)] + [matriz[8][c] for c in range(n - 8, n)]
    return [int("".join("1" if m else "0" for m in copia), 2) for copia in (a, b)]


class TestValoresConhecidos(unittest.TestCase):
    def test_reed_solomon_do_exemplo_hello_world_1m(self):
        dados = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(qr.reed_solomon(dados, 10),
                         [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_bits_de_formato_tabelados(self):
        self.assertEqual(qr.bits_de_formato("L", 0), 0b111011111000100)
        self.assertEqual(qr.bits_de_formato("M", 0), 0b101010000010010)
        self.assertEqual(qr.bits_de_formato("Q", 0), 0b011010101011111)
        self.assertEqual(qr.bits_de_formato("H", 0), 0b001011010001001)
        self.assertEqual(qr.bits_de_formato("Q", 7), 0b010101111101101)
        self.assertEqual(qr.bits_de_formato("L", 7), 0b110100101110110)

    def test_bits_de_versao_tabelados(self):
        self.assertEqual(qr.bits_de_versao(7), 0b000111110010010100)
        self.assertEqual(qr.bits_de_versao(10), 0b001010010011010011)

    def test_capacidade_bate_com_o_padrao(self):
        for versao, capacidades in CAPACIDADE_ISO.items():
            for ecc, esperado in zip("LMQH", capacidades):
                self.assertEqual(qr.capacidade_bytes(versao, ecc), esperado, (versao, ecc))

    def test_tabela_de_blocos_fecha_com_a_geometria(self):
        for versao in range(1, 11):
            totais = qr._codewords_totais(versao)
            for ecc in "LMQH":
                grau, grupos = qr.BLOCOS[versao][ecc]
                self.assertEqual(sum(q * (k + grau) for q, k in grupos), totais, (versao, ecc))


class TestEstrutura(unittest.TestCase):
    def conferir(self, matriz, versao, ecc):
        n = len(matriz)
        self.assertEqual(n, 17 + 4 * versao)
        self.assertTrue(all(len(linha) == n for linha in matriz))
        # Localizadores 7x7 nos três cantos, com o separador claro.
        for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):
            for dy in range(7):
                for dx in range(7):
                    anel = max(abs(dx - 3), abs(dy - 3))
                    self.assertEqual(matriz[y0 + dy][x0 + dx], anel != 2, (x0, y0, dx, dy))
        for i in range(8):
            self.assertFalse(matriz[7][i])
            self.assertFalse(matriz[i][7])
            self.assertFalse(matriz[7][n - 1 - i])
            self.assertFalse(matriz[i][n - 8])
            self.assertFalse(matriz[n - 8][i])
            self.assertFalse(matriz[n - 1 - i][7])
        # Timing alternado entre os localizadores.
        for i in range(8, n - 8):
            self.assertEqual(matriz[6][i], i % 2 == 0)
            self.assertEqual(matriz[i][6], i % 2 == 0)
        # Módulo escuro fixo.
        self.assertTrue(matriz[n - 8][8])
        # Formato: as duas cópias iguais, BCH conferindo, ECC certo.
        primeira, segunda = ler_formato_cru(matriz)
        self.assertEqual(primeira, segunda)
        sem_xor = primeira ^ 0x5412
        self.assertEqual(resto_gf2(sem_xor, 0x537), 0)
        self.assertEqual(sem_xor >> 13, qr.BITS_ECC[ecc])
        return (sem_xor >> 10) & 0b111

    def test_estrutura_em_todas_as_versoes_niveis_e_mascaras(self):
        for versao in range(1, 11):
            for ecc in "LMQH":
                for mascara in range(8):
                    matriz = qr.qr_matriz("Zeus", ecc, versao=versao, mascara=mascara)
                    self.assertEqual(self.conferir(matriz, versao, ecc), mascara)

    def test_mascara_escolhida_e_a_de_menor_penalidade(self):
        for texto in (URL, "pareamento ção", "x" * 100):
            for ecc in "LMQH":
                escolhida = qr.qr_matriz(texto, ecc)
                versao = (len(escolhida) - 17) // 4
                mascara = self.conferir(escolhida, versao, ecc)
                pontos = [qr.penalidade(qr.qr_matriz(texto, ecc, mascara=m)) for m in range(8)]
                self.assertEqual(pontos[mascara], min(pontos))
                self.assertEqual(pontos.index(min(pontos)), mascara)

    def test_versao_minima_automatica(self):
        self.assertEqual(len(qr.qr_matriz("", "M")), 21)
        self.assertEqual(len(qr.qr_matriz("x" * 14, "M")), 21)
        self.assertEqual(len(qr.qr_matriz("x" * 15, "M")), 25)
        self.assertEqual(len(qr.qr_matriz("x" * 213, "M")), 57)
        self.assertEqual(len(qr.qr_matriz("x" * 119, "H")), 57)

    def test_texto_grande_demais_da_valueerror_claro(self):
        with self.assertRaisesRegex(ValueError, "não cabe"):
            qr.qr_matriz("x" * 214, "M")
        with self.assertRaisesRegex(ValueError, "não cabe"):
            qr.qr_matriz("ç" * 136, "L")  # 272 bytes em UTF-8
        with self.assertRaises(ValueError):
            qr.qr_matriz("abc", "Z")
        with self.assertRaises(ValueError):
            qr.qr_matriz("x" * 30, "M", versao=1)


class TestIdaEVolta(unittest.TestCase):
    def test_textos_em_todos_os_niveis(self):
        for texto in TEXTOS:
            for ecc in "LMQH":
                if len(texto.encode()) > qr.capacidade_bytes(10, ecc):
                    continue
                with self.subTest(texto=texto[:20], ecc=ecc):
                    self.assertEqual(decodificar(qr.qr_matriz(texto, ecc)), texto)

    def test_duzentos_bytes(self):
        texto = "ab" * 100
        for ecc in "LM":
            lido, detalhes = decodificar(qr.qr_matriz(texto, ecc), devolver_detalhes=True)
            self.assertEqual(lido, texto)
            self.assertEqual(detalhes["ecc"], ecc)

    def test_forcando_cada_versao_e_mascara_no_limite_da_capacidade(self):
        base = "https://192.168.100.221:8770/parear#n=" * 8
        for versao in range(1, 11):
            for ecc in "LMQH":
                for mascara in range(8):
                    texto = base[:qr.capacidade_bytes(versao, ecc)]
                    lido, detalhes = decodificar(
                        qr.qr_matriz(texto, ecc, versao=versao, mascara=mascara), True)
                    self.assertEqual(lido, texto)
                    self.assertEqual(detalhes, {"versao": versao, "ecc": ecc, "mascara": mascara})

    def test_texto_curto_em_versao_grande(self):
        for versao in range(2, 11):  # 16 bytes em Q pedem pelo menos a versão 2
            self.assertEqual(decodificar(qr.qr_matriz("pareamento ção", "Q", versao=versao)),
                             "pareamento ção")

    def test_decodificador_acusa_modulo_trocado(self):
        # Garante que a conferência de síndromes não é decorativa.
        matriz = qr.qr_matriz(URL, "M")
        n = len(matriz)
        matriz[n - 1][n - 1] = not matriz[n - 1][n - 1]  # primeiro módulo de dados
        with self.assertRaisesRegex(ErroDeLeitura, "síndromes"):
            decodificar(matriz)


class TestSVG(unittest.TestCase):
    def test_svg_tem_um_path_fundo_branco_e_viewbox(self):
        svg = qr.qr_svg(URL, modulo=8, borda=4)
        lado = len(qr.qr_matriz(URL)) + 8
        self.assertTrue(svg.startswith("<svg"))
        self.assertEqual(svg.count("<path"), 1)
        self.assertIn(f'viewBox="0 0 {lado} {lado}"', svg)
        self.assertIn(f'width="{lado * 8}"', svg)
        self.assertIn('shape-rendering="crispEdges"', svg)
        self.assertIn('fill="#ffffff"', svg)
        self.assertNotIn("<script", svg)

    def test_path_reproduz_a_matriz(self):
        matriz = qr.qr_matriz(URL)
        n = len(matriz)
        svg = qr.qr_svg(URL, borda=4)
        desenhado = [[False] * n for _ in range(n)]
        for x, y, largura in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\d+z", svg):
            for dx in range(int(largura)):
                desenhado[int(y) - 4][int(x) - 4 + dx] = True
        self.assertEqual(desenhado, matriz)


# --- leitores externos opcionais, chamados por ctypes (nada é instalado) ---

def _rasterizar(matriz, escala=4, borda=4):
    n = len(matriz)
    lado = (n + 2 * borda) * escala
    pixels = bytearray(b"\xff" * lado * lado)
    for y, linha in enumerate(matriz):
        for x, escuro in enumerate(linha):
            if escuro:
                for dy in range(escala):
                    inicio = ((y + borda) * escala + dy) * lado + (x + borda) * escala
                    pixels[inicio:inicio + escala] = b"\x00" * escala
    return bytes(pixels), lado


_ZBAR = ctypes.util.find_library("zbar")
_ZXING = ctypes.util.find_library("ZXing")


def _ler_com_zbar(matriz):
    z = ctypes.CDLL(_ZBAR)
    p = ctypes.c_void_p
    z.zbar_image_scanner_create.restype = p
    z.zbar_image_scanner_set_config.argtypes = [p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    z.zbar_image_create.restype = p
    z.zbar_image_set_format.argtypes = [p, ctypes.c_ulong]
    z.zbar_image_set_size.argtypes = [p, ctypes.c_uint, ctypes.c_uint]
    z.zbar_image_set_data.argtypes = [p, ctypes.c_char_p, ctypes.c_ulong, p]
    z.zbar_scan_image.argtypes = [p, p]
    z.zbar_image_first_symbol.restype = p
    z.zbar_image_first_symbol.argtypes = [p]
    z.zbar_symbol_get_data.restype = p
    z.zbar_symbol_get_data.argtypes = [p]
    z.zbar_symbol_get_data_length.argtypes = [p]
    z.zbar_image_destroy.argtypes = [p]
    z.zbar_image_scanner_destroy.argtypes = [p]
    pixels, lado = _rasterizar(matriz)
    leitor = z.zbar_image_scanner_create()
    z.zbar_image_scanner_set_config(leitor, 0, 0, 1)    # ZBAR_CFG_ENABLE em tudo
    z.zbar_image_scanner_set_config(leitor, 64, 4, 1)   # QR: ZBAR_CFG_BINARY, bytes crus
    imagem = z.zbar_image_create()
    z.zbar_image_set_format(imagem, int.from_bytes(b"Y800", "little"))
    z.zbar_image_set_size(imagem, lado, lado)
    z.zbar_image_set_data(imagem, pixels, len(pixels), None)
    try:
        if z.zbar_scan_image(leitor, imagem) <= 0:
            return None
        simbolo = z.zbar_image_first_symbol(imagem)
        return ctypes.string_at(z.zbar_symbol_get_data(simbolo),
                                z.zbar_symbol_get_data_length(simbolo))
    finally:
        z.zbar_image_destroy(imagem)
        z.zbar_image_scanner_destroy(leitor)


def _ler_com_zxing(matriz):
    x = ctypes.CDLL(_ZXING)
    p = ctypes.c_void_p
    x.ZXing_ImageView_new.restype = p
    x.ZXing_ImageView_new.argtypes = [ctypes.c_char_p] + [ctypes.c_int] * 5
    x.ZXing_ReadBarcodes.restype = p
    x.ZXing_ReadBarcodes.argtypes = [p, p]
    x.ZXing_Barcodes_size.argtypes = [p]
    x.ZXing_Barcodes_at.restype = p
    x.ZXing_Barcodes_at.argtypes = [p, ctypes.c_int]
    x.ZXing_Barcode_bytes.restype = p
    x.ZXing_Barcode_bytes.argtypes = [p, ctypes.POINTER(ctypes.c_int)]
    x.ZXing_free.argtypes = [p]
    x.ZXing_Barcodes_delete.argtypes = [p]
    x.ZXing_ImageView_delete.argtypes = [p]
    pixels, lado = _rasterizar(matriz)
    visao = x.ZXing_ImageView_new(pixels, lado, lado, 0x01000000, 0, 0)  # ZXing_ImageFormat_Lum
    codigos = x.ZXing_ReadBarcodes(visao, None)
    try:
        if not codigos or x.ZXing_Barcodes_size(codigos) < 1:
            return None
        tamanho = ctypes.c_int()
        dados = x.ZXing_Barcode_bytes(x.ZXing_Barcodes_at(codigos, 0), ctypes.byref(tamanho))
        try:
            return ctypes.string_at(dados, tamanho.value)
        finally:
            x.ZXing_free(dados)
    finally:
        if codigos:
            x.ZXing_Barcodes_delete(codigos)
        x.ZXing_ImageView_delete(visao)


class TestLeitoresExternos(unittest.TestCase):
    # O texto vazio fica de fora: o ZXing não reporta símbolo sem conteúdo.
    CASOS = [t for t in TEXTOS if t]

    def _todos(self, ler):
        for texto in self.CASOS:
            for ecc in "LMQH":
                if len(texto.encode()) > qr.capacidade_bytes(10, ecc):
                    continue
                with self.subTest(texto=texto[:20], ecc=ecc):
                    self.assertEqual(ler(qr.qr_matriz(texto, ecc)), texto.encode("utf-8"))
        for versao in range(1, 11):
            with self.subTest(versao=versao):
                self.assertEqual(ler(qr.qr_matriz("Zeus", "H", versao=versao)), b"Zeus")

    @unittest.skipUnless(_ZBAR, "libzbar ausente")
    def test_zbar(self):
        self._todos(_ler_com_zbar)

    @unittest.skipUnless(_ZXING, "libZXing ausente")
    def test_zxing(self):
        try:
            ctypes.CDLL(_ZXING).ZXing_ReadBarcodes
        except AttributeError:
            self.skipTest("libZXing sem a API em C")
        self._todos(_ler_com_zxing)


if __name__ == "__main__":
    unittest.main()
