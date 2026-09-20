"""O painel de saúde só vale se o número for verdade.

Cada teste aqui existe por um jeito específico de mentir: somar `iowait` como
trabalho, chamar `[N/A]` de zero, confundir kB com byte, ou pedir ocupação de
CPU a partir de uma leitura só — que é contador desde o boot, não percentual.
"""

import unittest

from zeus.saude import (HISTORICO, Saude, _ocupacao, _resumo_termico, disco,
                        frequencia_mhz, interpretar_gpu, ler_cpu, ler_memoria,
                        ler_rede, modelo_da_cpu, temperaturas)

STAT = """cpu  100 0 100 800 100 0 0 0 0 0
cpu0 50 0 50 400 50 0 0 0 0 0
cpu1 50 0 50 400 50 0 0 0 0 0
intr 1 2 3
ctxt 99
"""
STAT_DEPOIS = """cpu  200 0 200 1400 100 0 0 0 0 0
cpu0 100 0 100 700 50 0 0 0 0 0
cpu1 100 0 100 700 50 0 0 0 0 0
"""

MEMINFO = """MemTotal:       32000000 kB
MemFree:         1000000 kB
MemAvailable:   16000000 kB
Cached:          8000000 kB
SwapTotal:       2000000 kB
SwapFree:        1500000 kB
"""


class Leituras(unittest.TestCase):
    def test_ocupacao_precisa_de_duas_amostras(self):
        antes, depois = ler_cpu(STAT), ler_cpu(STAT_DEPOIS)
        self.assertIsNone(_ocupacao(None, depois.get("cpu")))
        self.assertIsNone(_ocupacao(antes.get("cpu"), antes.get("cpu")))
        # 800 de delta total, 600 ociosos (idle 600 + iowait 0): 25% ocupado.
        self.assertAlmostEqual(_ocupacao(antes["cpu"], depois["cpu"]), 25.0, places=3)
        self.assertEqual(sorted(antes), ["cpu", "cpu0", "cpu1"])

    def test_iowait_conta_como_ocioso(self):
        """Disco travado não é CPU ocupada; somar iowait inflaria o painel."""
        parado = ler_cpu("cpu 0 0 0 0 0 0 0 0 0 0")["cpu"]
        so_iowait = ler_cpu("cpu 0 0 0 0 1000 0 0 0 0 0")["cpu"]
        self.assertEqual(_ocupacao(parado, so_iowait), 0.0)

    def test_linha_quebrada_nao_derruba_a_leitura(self):
        """Uma linha ilegível é descartada; as outras continuam valendo."""
        lido = ler_cpu("cpu abc def\ncpu0 1 2 3 4 5\ncpu1 1 2\n")
        self.assertEqual(sorted(lido), ["cpu0"])   # 'cpu' ilegível, 'cpu1' curta
        self.assertEqual(lido["cpu0"], (15, 9))    # total, ocioso (idle+iowait)

    def test_memoria_usa_available_e_converte_kb(self):
        m = ler_memoria(MEMINFO)
        self.assertEqual(m["total"], 32000000 * 1024)
        self.assertEqual(m["usada"], 16000000 * 1024)     # total - MemAvailable
        self.assertEqual(m["percentual"], 50.0)
        self.assertEqual(m["troca_usada"], 500000 * 1024)
        self.assertEqual(ler_memoria("lixo"), {})

    def test_memoria_sem_available_cai_para_free(self):
        m = ler_memoria("MemTotal: 1000 kB\nMemFree: 250 kB\n")
        self.assertEqual(m["disponivel"], 250 * 1024)

    def test_modelo_e_frequencia(self):
        info = "model name\t: Intel(R) Xeon(R) E5-2680\ncpu MHz\t\t: 2500.0\ncpu MHz\t\t: 3500.0\n"
        self.assertEqual(modelo_da_cpu(info), "Intel(R) Xeon(R) E5-2680")
        self.assertEqual(frequencia_mhz(info), 3000)
        self.assertIsNone(frequencia_mhz("sem nada"))
        self.assertEqual(modelo_da_cpu(""), "")

    def test_rede_ignora_loopback(self):
        texto = ("Inter-|   Receive\n face |bytes packets\n"
                 "    lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0\n"
                 "  eth0: 100 1 0 0 0 0 0 0 200 1 0 0 0 0 0 0\n")
        self.assertEqual(ler_rede(texto), (100, 200))


class GPU(unittest.TestCase):
    def test_na_vira_none_e_nao_zero(self):
        """Uma GeForce não informa potência. Zero watt seria medida falsa."""
        linha = "NVIDIA GeForce RTX 3060, 42, 2048, 12288, 61, [N/A], [N/A], 38"
        placa = interpretar_gpu(linha)[0]
        self.assertEqual(placa["nome"], "NVIDIA GeForce RTX 3060")
        self.assertEqual(placa["uso"], 42)
        self.assertEqual(placa["memoria_usada"], 2048 * 1024 * 1024)
        self.assertEqual(placa["percentual_memoria"], 16.7)
        self.assertIsNone(placa["watts"])
        self.assertIsNone(placa["watts_teto"])
        self.assertEqual(placa["ventoinha"], 38)

    def test_duas_placas_e_linha_curta_descartada(self):
        saida = ("A, 1, 1, 2, 3, 4, 5, 6\n"
                 "B, 2, 1, 2, 3, 4, 5, 6\n"
                 "truncada, 1, 2\n")
        self.assertEqual([p["nome"] for p in interpretar_gpu(saida)], ["A", "B"])
        self.assertEqual(interpretar_gpu(""), [])


class Termico(unittest.TestCase):
    def test_pacote_da_cpu_ganha_do_resto(self):
        sensores = [{"sensor": "nvme", "rotulo": "Composite", "celsius": 70.0},
                    {"sensor": "coretemp", "rotulo": "Package id 0", "celsius": 48.0}]
        self.assertEqual(_resumo_termico(sensores), 48.0)

    def test_sem_pacote_usa_o_mais_quente_plausivel(self):
        sensores = [{"sensor": "nvme", "rotulo": "Composite", "celsius": 70.0},
                    {"sensor": "acpi", "rotulo": "temp1", "celsius": 200.0}]
        self.assertEqual(_resumo_termico(sensores), 70.0)
        self.assertIsNone(_resumo_termico([]))

    def test_diretorio_ausente_nao_levanta(self):
        from pathlib import Path
        self.assertEqual(temperaturas(Path("/nao/existe/hwmon")), [])


class Amostragem(unittest.TestCase):
    def setUp(self):
        self.relogio = [0.0]
        self.chamadas = []

        class Saida:
            stdout = "Placa, 10, 1, 2, 3, 4, 5, 6"

        def executar(argumentos, **resto):
            self.chamadas.append(argumentos)
            return Saida()

        self.saude = Saude(relogio=lambda: self.relogio[0], executar_gpu=executar)

    def test_primeira_amostra_nao_inventa_ocupacao(self):
        """Sem amostra anterior não há delta: o painel mostra '—', não 0%."""
        primeira = Saude(relogio=lambda: 0.0)._medir()
        self.assertIsNone(primeira["cpu"]["uso"])
        self.assertIsNone(primeira["rede"]["entrada"])

    def test_historico_cresce_e_para_no_teto(self):
        for i in range(HISTORICO + 25):
            self.relogio[0] += 2.0
            retrato = self.saude.medir()
        self.assertEqual(len(retrato["historico"]["cpu"]), HISTORICO)
        self.assertEqual(len(retrato["historico"]["memoria"]), HISTORICO)

    def test_gpu_fica_em_cache_entre_amostras(self):
        import shutil
        if not shutil.which("nvidia-smi"):
            self.skipTest("medir_gpu procura o binário antes de executar")
        self.saude.medir()
        self.saude.medir()
        self.assertEqual(len(self.chamadas), 1)

    def test_retrato_tem_as_secoes_que_a_pagina_desenha(self):
        r = self.saude.medir()
        for chave in ("cpu", "memoria", "gpu", "disco", "rede", "sensores",
                      "tempo_ligado_s", "processo", "historico"):
            self.assertIn(chave, r)
        self.assertEqual(r["tipo"], "saude")
        self.assertIn("percentual", disco("/"))

    def test_disco_em_caminho_inexistente_volta_vazio(self):
        self.assertEqual(disco("/nao/existe/mesmo"), {})


if __name__ == "__main__":
    unittest.main()
