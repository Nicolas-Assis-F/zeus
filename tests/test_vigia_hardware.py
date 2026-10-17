"""Vigia de hardware (#76): histerese, silêncio e volta ao normal."""

import unittest

from zeus.vigia_hardware import VigiaDeHardware


class Relogio:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


def retrato(cpu=50, gpu=40, vram=70, ram=50, livre=40, troca=0):
    return {"cpu": {"celsius": cpu}, "memoria": {"percentual": ram, "troca_total": 100,
                                                 "troca_usada": troca},
            "gpu": [{"celsius": gpu, "percentual_memoria": vram}],
            "disco": {"estado": {"total": 100, "livre": livre}}}


class TestVigiaDeHardware(unittest.TestCase):
    def setUp(self):
        self.relogio = Relogio()
        self.vigia = VigiaDeHardware(relogio=self.relogio)

    def ler(self, vezes=1, **medidas):
        avisos = []
        for _ in range(vezes):
            self.relogio.agora += 30
            avisos += self.vigia.avaliar(retrato(**medidas))
        return avisos

    def test_saudavel_fica_quieto(self):
        self.assertEqual(self.ler(10), [])

    def test_pico_isolado_nao_alerta(self):
        self.assertEqual(self.ler(2, cpu=95) + self.ler(1) + self.ler(2, cpu=95), [])

    def test_tres_leituras_seguidas_alertam_uma_vez(self):
        avisos = self.ler(3, cpu=91)
        self.assertEqual(avisos, ["Senhor, atenção: a CPU está a 91 °C."])
        self.assertEqual(self.ler(20, cpu=91), [])  # silêncio de 30 min

    def test_repete_depois_do_silencio(self):
        self.ler(3, cpu=91)
        self.relogio.agora += 1800
        self.assertEqual(len(self.ler(1, cpu=91)), 1)

    def test_volta_ao_normal_so_abaixo_da_margem(self):
        self.ler(3, gpu=88)
        self.assertEqual(self.ler(1, gpu=83), [])  # abaixo do limite, dentro da margem
        self.assertEqual(self.ler(1, gpu=78), ["Normalizou: a placa de vídeo está a 78 °C."])
        self.assertEqual(self.ler(5, gpu=60), [])

    def test_disco_e_ruim_abaixo(self):
        self.assertEqual(self.ler(3, livre=6), ["Senhor, atenção: o disco tem só 6% livre."])

    def test_medida_ausente_nao_vira_alerta(self):
        self.relogio.agora += 30
        self.assertEqual(self.vigia.avaliar({"cpu": {}, "gpu": [], "memoria": {}}), [])

    def test_limite_configurado(self):
        vigia = VigiaDeHardware({"cpu_celsius": 40}, confirmacoes=1, relogio=self.relogio)
        self.assertEqual(len(vigia.avaliar(retrato(cpu=45))), 1)


class TestAnuncioNaSala(unittest.TestCase):
    def test_so_fala_com_a_escuta_dormindo(self):
        import tempfile
        from zeus.escuta_continua import EscutaContinua, FimDeFala, GuardaDeEco
        guarda = GuardaDeEco()
        escuta = EscutaContinua(None, None, FimDeFala(), guarda, None, None, None,
                                lambda p: None, pasta=tempfile.mkdtemp())
        escuta._falar = lambda texto: None
        self.assertTrue(escuta.anunciar("Senhor, atenção."))
        escuta.estado = escuta.OUVINDO
        self.assertFalse(escuta.anunciar("Senhor, atenção."))
        escuta.estado = escuta.DORMINDO
        guarda.falando(10)
        self.assertFalse(escuta.anunciar("Senhor, atenção."))


if __name__ == "__main__":
    unittest.main()
