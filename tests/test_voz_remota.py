"""Voz e escuta pela ElevenLabs no OpenRouter, com reserva local (#68).

Tudo com dublê: nenhum teste toca a rede, o Piper nem o faster-whisper."""

import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from zeus.config import Config
from zeus.gasto_voz import GastoDeVoz
from zeus.ouvidos import OuvidosComReserva, OuvidosScribe, com_escuta_remota
from zeus.voz import ErroDeVoz, VozComReserva, VozElevenLabs

PCM = b"\x01\x00" * 24000  # um segundo de áudio a 24 kHz


class Transporte:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def __call__(self, url, corpo, cabecalhos, timeout):
        self.pedidos.append({"url": url, "corpo": json.loads(corpo), "cabecalhos": cabecalhos})
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


class Relogio:
    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora


class PiperDeMentira:
    nome = "piper"

    def __init__(self, destino, pronto=True):
        self.destino = Path(destino)
        self.pronto = pronto
        self.falas = []

    def disponivel(self):
        return self.pronto

    def diagnostico(self):
        return "pronta" if self.pronto else "piper não encontrado no PATH"

    def falar(self, texto):
        self.falas.append(texto)
        if not self.pronto:
            return None
        arquivo = self.destino / f"piper-{len(self.falas)}.wav"
        arquivo.write_bytes(b"RIFF" + b"\0" * 60)
        return arquivo


class OuvidosDeMentira:
    nome = "faster-whisper"
    limite_segundos = 65

    def __init__(self, destino, texto="ouvido localmente"):
        self.destino = Path(destino)
        self.texto = texto
        self.chamadas = 0
        self.ultima_medicao = {"local": True}

    def instalado(self):
        return True

    def disponivel(self):
        return True

    def diagnostico(self):
        return "modelo small ainda não carregado"

    def preparar(self):
        return True

    def transcrever(self, arquivo, remover=True):
        self.chamadas += 1
        return self.texto


class Base(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.relogio = Relogio()
        self.dia = "2026-10-17"
        self.gasto = GastoDeVoz(self.pasta / "gasto.json", teto_caracteres=1000,
                                teto_segundos=100, hoje=lambda: self.dia)

    def voz(self, *respostas, **extra):
        self.transporte = Transporte(*respostas)
        return VozElevenLabs("chave-teste", destino=self.pasta, gasto=self.gasto,
                             transporte=self.transporte, relogio=self.relogio, **extra)


class TestVozElevenLabs(Base):
    def test_sintetiza_wav_com_turbo_e_registra_gasto(self):
        voz = self.voz((200, PCM))
        arquivo = voz.falar("Bom dia, senhor.")
        with wave.open(str(arquivo)) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 24000))
            self.assertEqual(w.getnframes(), 24000)
        pedido = self.transporte.pedidos[0]
        self.assertTrue(pedido["url"].endswith("/audio/speech"))
        self.assertEqual(pedido["corpo"]["model"], "elevenlabs/eleven-v4-turbo")
        self.assertEqual(pedido["corpo"]["response_format"], "pcm")
        self.assertEqual(pedido["cabecalhos"]["Authorization"], "Bearer chave-teste")
        self.assertEqual(self.gasto.hoje_gasto()["caracteres"], len("Bom dia, senhor."))

    def test_texto_longo_e_briefing_usam_v4(self):
        voz = self.voz((200, PCM), (200, PCM))
        voz.falar("x" * 401)
        voz.falar("Resumo da manhã.", caprichada=True)
        modelos = [p["corpo"]["model"] for p in self.transporte.pedidos]
        self.assertEqual(modelos, ["elevenlabs/eleven-v4", "elevenlabs/eleven-v4"])

    def test_cache_por_hash_nao_sintetiza_de_novo(self):
        voz = self.voz((200, PCM))
        primeiro = voz.falar("Às ordens.")
        self.assertEqual(voz.falar("Às ordens."), primeiro)
        self.assertEqual(len(self.transporte.pedidos), 1)

    def test_teto_diario_impede_chamada(self):
        voz = self.voz()
        with self.assertRaises(ErroDeVoz):
            voz.falar("x" * 1001)
        self.assertEqual(self.transporte.pedidos, [])

    def test_saldo_esgotado_descansa_e_volta_depois(self):
        voz = self.voz((402, b'{"error":"saldo"}'), (200, PCM))
        with self.assertRaises(ErroDeVoz):
            voz.falar("Oi.")
        self.assertFalse(voz.disponivel())
        self.assertIn("descanso", voz.diagnostico())
        self.relogio.agora += 3601
        self.assertTrue(voz.disponivel())
        self.assertIsNotNone(voz.falar("Oi."))

    def test_texto_recusado_nao_tira_a_voz_do_ar(self):
        voz = self.voz((400, b"{}"))
        with self.assertRaises(ErroDeVoz):
            voz.falar("Oi.")
        self.assertTrue(voz.disponivel())

    def test_sem_chave_fica_indisponivel(self):
        voz = VozElevenLabs("", destino=self.pasta)
        self.assertFalse(voz.disponivel())
        self.assertIsNone(voz.falar("Oi."))
        self.assertEqual(voz.diagnostico(), "sem chave do OpenRouter")


class TestVozComReserva(Base):
    def test_rede_cortada_cai_para_o_piper_e_avisa_a_troca(self):
        trocas = []
        piper = PiperDeMentira(self.pasta)
        remota = self.voz(ErroDeVoz("sem rede: timed out", 60))
        voz = VozComReserva(remota, piper, ao_trocar=lambda o, m: trocas.append((o, m)))
        arquivo = voz.falar("Deixa comigo, senhor.")
        self.assertTrue(arquivo.name.startswith("piper-"))
        self.assertEqual(trocas, [("piper", "sem rede: timed out")])
        # Em descanso, nem tenta a rede de novo: vai direto ao Piper.
        voz.falar("Outra.")
        self.assertEqual(len(piper.falas), 2)
        self.assertEqual(len(trocas), 1)

    def test_volta_para_a_elevenlabs_e_registra(self):
        trocas = []
        remota = self.voz(ErroDeVoz("sem rede", 60), (200, PCM))
        voz = VozComReserva(remota, PiperDeMentira(self.pasta),
                            ao_trocar=lambda o, m: trocas.append(o))
        voz.falar("Um.")
        self.relogio.agora += 61
        voz.falar("Dois.")
        self.assertEqual(trocas, ["piper", "elevenlabs"])

    def test_sem_nenhuma_voz_devolve_none(self):
        remota = VozElevenLabs("", destino=self.pasta)
        voz = VozComReserva(remota, PiperDeMentira(self.pasta, pronto=False))
        self.assertFalse(voz.disponivel())
        self.assertIsNone(voz.falar("Oi."))
        self.assertIn("reserva piper", voz.diagnostico())


class TestGasto(Base):
    def test_aviso_aos_80_por_cento_uma_vez_por_dia(self):
        avisos = []
        self.gasto.avisar = avisos.append
        self.assertIsNone(self.gasto.registrar(caracteres=700))
        self.assertIn("80%", self.gasto.registrar(caracteres=100))
        self.assertIsNone(self.gasto.registrar(caracteres=50))
        self.assertEqual(len(avisos), 1)
        self.dia = "2026-10-18"
        self.assertEqual(self.gasto.hoje_gasto()["caracteres"], 0)

    def test_arquivo_fica_privado(self):
        self.gasto.registrar(caracteres=1)
        self.assertEqual((self.pasta / "gasto.json").stat().st_mode & 0o777, 0o600)

    def test_teto_zero_desliga(self):
        gasto = GastoDeVoz(self.pasta / "zero.json", teto_caracteres=0, teto_segundos=0)
        self.assertFalse(gasto.pode(caracteres=1))
        self.assertFalse(gasto.pode(segundos=1))


def resposta_scribe(texto, segundos=3.0, custo=0.00009):
    return (200, json.dumps({"text": texto, "usage": {"seconds": segundos, "cost": custo},
                             "words": [{"word": "Zeus", "start": 0.1, "end": 0.4}]}).encode())


class TestScribe(Base):
    def ouvidos(self, *respostas):
        self.transporte = Transporte(*respostas)
        return OuvidosScribe("chave-teste", gasto=self.gasto, transporte=self.transporte,
                             relogio=self.relogio)

    def audio(self, nome="fala.ogg"):
        arquivo = self.pasta / nome
        arquivo.write_bytes(b"OggS" + b"\0" * 100)
        return arquivo

    def test_transcreve_com_palavras_e_gasto(self):
        ouvidos = self.ouvidos(resposta_scribe("Zeus, que horas são?"))
        arquivo = self.audio()
        self.assertEqual(ouvidos.transcrever(arquivo), "Zeus, que horas são?")
        self.assertFalse(arquivo.exists())  # removido, como no faster-whisper
        corpo = self.transporte.pedidos[0]["corpo"]
        self.assertEqual(corpo["input_audio"]["format"], "ogg")
        self.assertEqual(corpo["language"], "pt")
        self.assertEqual(ouvidos.palavras[0]["word"], "Zeus")
        self.assertEqual(self.gasto.hoje_gasto()["segundos"], 3.0)

    def test_audio_longo_e_recusado(self):
        ouvidos = self.ouvidos(resposta_scribe("…", segundos=80))
        self.assertEqual(ouvidos.transcrever(self.audio()), "")
        self.assertIn("excede", ouvidos.diagnostico())

    def test_reserva_quando_falta_rede(self):
        trocas = []
        local = OuvidosDeMentira(self.pasta)
        cadeia = OuvidosComReserva(self.ouvidos(ErroDeVoz("sem rede", 60)), local,
                                   ao_trocar=lambda o, m: trocas.append(o))
        arquivo = self.audio()
        self.assertEqual(cadeia.transcrever(arquivo), "ouvido localmente")
        self.assertFalse(arquivo.exists())
        self.assertEqual(trocas, ["faster-whisper"])

    def test_silencio_no_scribe_nao_chama_a_reserva(self):
        local = OuvidosDeMentira(self.pasta)
        cadeia = OuvidosComReserva(self.ouvidos(resposta_scribe("")), local)
        self.assertEqual(cadeia.transcrever(self.audio()), "")
        self.assertEqual(local.chamadas, 0)

    def test_teto_estourado_vai_direto_ao_local(self):
        self.gasto.registrar(segundos=100)
        local = OuvidosDeMentira(self.pasta)
        cadeia = OuvidosComReserva(self.ouvidos(), local)
        self.assertEqual(cadeia.transcrever(self.audio()), "ouvido localmente")
        self.assertEqual(self.transporte.pedidos, [])
        self.assertIn("teto", cadeia.diagnostico())

    def test_montagem_respeita_a_configuracao(self):
        local = OuvidosDeMentira(self.pasta)
        self.assertIs(com_escuta_remota(Config(), self.pasta, local), local)
        sem_chave = Config(escuta_provedor="scribe")
        self.assertIs(com_escuta_remota(sem_chave, self.pasta, local), local)
        ligada = Config(escuta_provedor="scribe", openrouter_chave="x")
        cadeia = com_escuta_remota(ligada, self.pasta, local)
        self.assertIsInstance(cadeia, OuvidosComReserva)
        self.assertEqual(cadeia.destino, local.destino)


class CanalComArquivo:
    nome = "whatsapp"

    def __init__(self):
        self.arquivos = []

    def enviar_arquivo(self, caminho, legenda=""):
        self.arquivos.append(caminho)


class TestRespostaEmAudio(Base):
    def setUp(self):
        super().setUp()
        import zeus.voz as voz
        self.original = voz.nota_de_voz
        voz.nota_de_voz = lambda wav, destino=None: Path(destino) / "resposta.ogg"

    def tearDown(self):
        import zeus.voz as voz
        voz.nota_de_voz = self.original

    def test_audio_de_nicolas_volta_em_audio(self):
        from zeus.__main__ import responder_em_audio
        from zeus.canais.whatsapp import MARCA_AUDIO_DE_NICOLAS
        canal = CanalComArquivo()
        voz = VozComReserva(self.voz((200, PCM)), PiperDeMentira(self.pasta))
        ogg = responder_em_audio(canal, voz, MARCA_AUDIO_DE_NICOLAS + " que horas são?",
                                 "São dez da manhã, senhor.", self.pasta / "wa")
        self.assertEqual(canal.arquivos, [str(ogg)])

    def test_texto_escrito_nao_vira_audio(self):
        from zeus.__main__ import responder_em_audio
        canal = CanalComArquivo()
        voz = VozComReserva(self.voz(), PiperDeMentira(self.pasta))
        self.assertIsNone(responder_em_audio(canal, voz, "que horas são?", "Dez.", self.pasta))
        self.assertEqual(canal.arquivos, [])

    def test_canal_sem_arquivo_nao_tenta(self):
        from zeus.__main__ import responder_em_audio
        from zeus.canais.whatsapp import MARCA_AUDIO_DE_NICOLAS
        voz = VozComReserva(self.voz(), PiperDeMentira(self.pasta))
        canal = SimpleNamespace(nome="telegram")
        self.assertIsNone(responder_em_audio(canal, voz, MARCA_AUDIO_DE_NICOLAS + " oi",
                                             "Oi.", self.pasta))


class TestMontagemDaVoz(unittest.TestCase):
    def test_padrao_continua_piper(self):
        from zeus.__main__ import montar_voz
        from zeus.voz import Voz
        self.assertIsInstance(montar_voz(Config()), Voz)

    def test_elevenlabs_com_reserva(self):
        from zeus.__main__ import montar_voz
        pasta = tempfile.mkdtemp()
        voz = montar_voz(Config(voz_provedor="elevenlabs", openrouter_chave="x",
                                voz_eleven_voz="george"), pasta)
        self.assertIsInstance(voz, VozComReserva)
        self.assertEqual(voz.principal.voz, "george")
        self.assertEqual(voz.destino, voz.reserva.destino)


if __name__ == "__main__":
    unittest.main()
