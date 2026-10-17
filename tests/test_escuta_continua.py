"""Escuta no ambiente (#68): estados, fim de fala, eco e reconhecimento.

Sem microfone, sem alto-falante e sem openwakeword: tudo dublê."""

import array
import tempfile
import threading
import time
import unittest
from pathlib import Path

from zeus.config import Config
from zeus.escuta_continua import (QUADRO, EscutaContinua, FimDeFala, GuardaDeEco,
                                  limpar_transcricao, montar_escuta_ambiente,
                                  nivel, para_fala)


def quadro(amplitude: int) -> bytes:
    return array.array("h", [amplitude, -amplitude] * (QUADRO // 2)).tobytes()


SILENCIO = quadro(20)
FALA = quadro(3000)
JARVIS = quadro(1)  # a palavra de mentira reconhece este quadro


class Relogio:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


class Palavra:
    def __init__(self):
        self.reinicios = 0

    def ouviu(self, q):
        return q == JARVIS

    def reiniciar(self):
        self.reinicios += 1


class Alto:
    def __init__(self, guarda):
        self.guarda = guarda
        self.tocados = []

    def tocar(self, arquivo):
        self.tocados.append(arquivo)
        self.guarda.falando(1.0)
        return True

    def parar(self):
        pass


class Voz:
    def __init__(self):
        self.falas = []

    def disponivel(self):
        return True

    def diagnostico(self):
        return "pronta"

    def falar(self, texto, caprichada=False):
        self.falas.append(texto)
        return Path(f"/tmp/{len(self.falas)}.wav")


class Ouvidos:
    def __init__(self, texto="que horas são"):
        self.texto = texto
        self.arquivos = []

    def disponivel(self):
        return True

    def diagnostico(self):
        return "pronta"

    def transcrever(self, arquivo, remover=True):
        self.arquivos.append(Path(arquivo).stat().st_size)
        Path(arquivo).unlink()
        return self.texto


class Microfone:
    def fechar(self):
        pass


class TestPecas(unittest.TestCase):
    def test_nivel(self):
        self.assertAlmostEqual(nivel(FALA), 3000, delta=1)
        self.assertEqual(nivel(b""), 0.0)

    def test_fim_de_fala_espera_silencio_que_dura(self):
        fim = FimDeFala(silencio_ms=240, espera_inicio_s=5)
        self.assertEqual(fim.alimentar(FALA), "falando")
        self.assertEqual(fim.alimentar(SILENCIO), "falando")
        self.assertEqual(fim.alimentar(FALA), "falando")  # pausa curta não encerra
        self.assertEqual([fim.alimentar(SILENCIO) for _ in range(3)][-1], "fim")

    def test_fim_de_fala_desiste_sem_fala(self):
        fim = FimDeFala(espera_inicio_s=0.24)
        self.assertEqual([fim.alimentar(SILENCIO) for _ in range(3)][-1], "desistiu")

    def test_piso_da_sala_sobe_o_limiar_aos_poucos(self):
        fim = FimDeFala(minimo=300)
        for nivel_da_sala in range(200, 1500, 5):
            fim.calibrar(nivel_da_sala)
        self.assertGreater(fim.limiar, 3000)
        self.assertEqual(fim.alimentar(FALA), "aguardando")  # 3000 é ruído aqui

    def test_conversa_na_sala_nao_vira_piso(self):
        fim = FimDeFala(minimo=300)
        for _ in range(500):
            fim.calibrar(3000)
        self.assertEqual(fim.limiar, 300)

    def test_guarda_de_eco(self):
        relogio = Relogio()
        guarda = GuardaDeEco(cauda_s=0.25, relogio=relogio)
        self.assertTrue(guarda.aberto())
        guarda.falando(2.0, latencia_s=0.15)
        relogio.agora = 2.3
        self.assertFalse(guarda.aberto())
        relogio.agora = 2.41
        self.assertTrue(guarda.aberto())

    def test_alucinacoes_do_whisper_somem(self):
        self.assertEqual(limpar_transcricao("Legendas pela comunidade Amara.org"), "")
        self.assertEqual(limpar_transcricao("Obrigado por assistir!"), "")
        self.assertEqual(limpar_transcricao("[Música]"), "")
        self.assertEqual(limpar_transcricao("obrigado por assistir o jogo comigo"),
                         "obrigado por assistir o jogo comigo")

    def test_nome_corrigido_so_no_chamado(self):
        self.assertEqual(limpar_transcricao("Deus, que horas são?"), "Zeus, que horas são?")
        self.assertEqual(limpar_transcricao("Ei seus, liga a luz"), "Ei Zeus, liga a luz")
        self.assertEqual(limpar_transcricao("graças a Deus deu certo"), "graças a Deus deu certo")

    def test_para_fala_tira_marcacao_e_link(self):
        self.assertEqual(para_fala("**Pronto**, veja https://x.y/z\n- item"),
                         "Pronto, veja o link na tela item")


class TestEstados(unittest.TestCase):
    def montar(self, responder=None, ouvidos=None, **extra):
        self.relogio = Relogio()
        self.guarda = GuardaDeEco(relogio=self.relogio)
        self.alto = Alto(self.guarda)
        self.voz = Voz()
        self.palavra = Palavra()
        self.pedidos = []
        self.situacoes = []

        def enfileirar(pedido):
            self.pedidos.append(pedido)
            (responder or (lambda p: p["responder"]("São dez horas, senhor.")))(pedido)

        opcoes = dict(reconhecimento_apos_s=0.05, continuacao_s=0.24)
        opcoes.update(extra)
        return EscutaContinua(
            Microfone(), self.palavra, FimDeFala(silencio_ms=160, espera_inicio_s=1),
            self.guarda, self.alto, ouvidos or Ouvidos(), self.voz, enfileirar,
            publicar=lambda tipo, **c: self.situacoes.append(c.get("estado")),
            pasta=tempfile.mkdtemp(), **opcoes)

    def falar(self, escuta, *quadros):
        for q in quadros:
            escuta.processar(q)

    def test_dormindo_ignora_fala_sem_palavra(self):
        escuta = self.montar()
        self.falar(escuta, FALA, FALA, SILENCIO, SILENCIO, SILENCIO)
        self.assertEqual(escuta.estado, "dormindo")
        self.assertEqual(self.pedidos, [])

    def test_ciclo_completo(self):
        ouvidos = Ouvidos()
        escuta = self.montar(ouvidos=ouvidos)
        self.falar(escuta, JARVIS)
        self.assertEqual(escuta.estado, "ouvindo")
        self.falar(escuta, FALA, FALA, SILENCIO, SILENCIO)
        self.assertEqual(self.pedidos[0]["texto"], "que horas são")
        self.assertEqual(self.pedidos[0]["tipo"], "ambiente")
        self.assertEqual(ouvidos.arquivos[0], 44 + 4 * QUADRO * 2)  # WAV com o que foi dito
        self.assertEqual(self.voz.falas, ["São dez horas, senhor."])
        self.assertEqual(len(self.alto.tocados), 1)
        # Continua ouvindo para emendar, sem exigir a palavra.
        self.assertEqual(escuta.estado, "ouvindo")
        self.assertIn("falando", self.situacoes)

    def test_nao_ouve_a_propria_voz(self):
        escuta = self.montar()
        self.falar(escuta, JARVIS, FALA, SILENCIO, SILENCIO)
        self.assertFalse(self.guarda.aberto())  # o alto-falante acabou de tocar
        self.falar(escuta, FALA, FALA, SILENCIO, SILENCIO, SILENCIO)
        self.assertEqual(len(self.pedidos), 1)  # a voz do Zeus não virou pedido
        self.relogio.agora = 5
        self.falar(escuta, FALA, SILENCIO, SILENCIO)
        self.assertEqual(len(self.pedidos), 2)  # passou a janela: é Nicolas emendando

    def test_continuacao_expira_e_volta_a_dormir(self):
        escuta = self.montar()
        self.falar(escuta, JARVIS, FALA, SILENCIO, SILENCIO)
        self.relogio.agora = 5
        self.falar(escuta, SILENCIO, SILENCIO, SILENCIO)
        self.assertEqual(escuta.estado, "dormindo")
        self.assertGreaterEqual(self.palavra.reinicios, 1)

    def test_reconhecimento_quando_a_resposta_demora(self):
        def devagar(pedido):
            threading.Timer(0.2, pedido["responder"], args=("Pronto, senhor.",)).start()
        escuta = self.montar(responder=devagar)
        self.falar(escuta, JARVIS, FALA, SILENCIO, SILENCIO)
        self.assertEqual(self.voz.falas, ["Deixa comigo, senhor.", "Pronto, senhor."])

    def test_resposta_rapida_nao_tem_reconhecimento(self):
        escuta = self.montar()
        self.falar(escuta, JARVIS, FALA, SILENCIO, SILENCIO)
        self.assertNotIn("Deixa comigo, senhor.", self.voz.falas)

    def test_transcricao_vazia_volta_a_dormir(self):
        escuta = self.montar(ouvidos=Ouvidos(texto="Legendas pela comunidade Amara.org"))
        self.falar(escuta, JARVIS, FALA, SILENCIO, SILENCIO)
        self.assertEqual(self.pedidos, [])
        self.assertEqual(escuta.estado, "dormindo")

    def test_falha_do_nucleo_nao_trava(self):
        escuta = self.montar(responder=lambda p: p["responder"](None))
        inicio = time.monotonic()
        self.falar(escuta, JARVIS, FALA, SILENCIO, SILENCIO)
        self.assertLess(time.monotonic() - inicio, 1)
        self.assertEqual(self.voz.falas, [])


class TestMontagem(unittest.TestCase):
    def test_desligada_por_padrao(self):
        escuta, motivo = montar_escuta_ambiente(Config(), tempfile.mkdtemp(), Ouvidos(),
                                                Voz(), lambda p: None)
        self.assertIsNone(escuta)
        self.assertIn("desligada", motivo)


if __name__ == "__main__":
    unittest.main()
