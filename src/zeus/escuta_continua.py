"""Escuta no ambiente: o Zeus ouve pelo microfone da própria máquina (#68).

O laço tem três estados:

- **dormindo**: só a palavra de ativação ouve o microfone, e nenhum áudio sai
  da máquina;
- **ouvindo**: grava até a fala acabar, medindo a energia contra o piso de ruído
  da sala;
- **respondendo**: transcreve, entrega ao núcleo pelo mesmo caminho da HUD e
  fala a resposta no alto-falante. Se a resposta demorar mais de
  `reconhecimento_apos_s`, toca na hora uma frase curta ("Deixa comigo,
  senhor.") para o silêncio não parecer travamento.

Depois de responder, o Zeus continua ouvindo por alguns segundos sem exigir a
palavra de ativação, para Nicolas emendar a próxima frase.

A guarda de eco é uma janela, não um filtro. Enquanto o alto-falante toca, mais
a latência e uma cauda, o microfone é descartado. Assim o Zeus não responde à
própria voz. O custo é não poder ser interrompido falando por cima, o que fica
para a #36.

A captura usa o `pw-record` do PipeWire, lido como PCM cru pela biblioteca
padrão. Só a palavra de ativação precisa de extra (openwakeword + numpy).
Sem ele, `diagnostico` diz o que falta e nada sobe. Fica desligada por padrão:
microfone ouvindo a casa é decisão de Nicolas (`escuta_ambiente`).

Ideias de referência: janela de eco com cauda e fila de quadros com descarte
(Mark-LV, só a ideia); filtro de frases que o Whisper inventa no silêncio
(javis-os, MIT).
"""

import array
import math
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

TAXA = 16000
QUADRO = 1280  # 80 ms: o tamanho que o openwakeword espera
BYTES_DO_QUADRO = QUADRO * 2
MS_DO_QUADRO = QUADRO * 1000 // TAXA


def nivel(quadro: bytes) -> float:
    """RMS de um quadro PCM 16 bits."""
    amostras = array.array("h")
    amostras.frombytes(quadro[: len(quadro) // 2 * 2])
    if not amostras:
        return 0.0
    return math.sqrt(sum(a * a for a in amostras) / len(amostras))


# Frases que o reconhecimento inventa em silêncio ou ruído, aprendidas de
# legendas de vídeo. Só caem quando são a transcrição inteira.
ALUCINACOES = re.compile(
    r"^\W*(legendas? (pela|por) .*|obrigad[oa] por assistir\W*|inscreva-se.*|"
    r"\[(m[úu]sica|music|aplausos|risos)\]|tchau\W*|\.+)\W*$", re.IGNORECASE)
# "Deus" e "seus" no lugar de "Zeus", só quando é chamado.
CHAMADO = re.compile(r"^(\s*(?:ei|hey|oi|ô)?\s*,?\s*)(deus|seus|zeuz|zéus)\b", re.IGNORECASE)


def limpar_transcricao(texto: str) -> str:
    texto = (texto or "").strip()
    if ALUCINACOES.match(texto):
        return ""
    return CHAMADO.sub(lambda m: m.group(1) + "Zeus", texto, count=1)


def para_fala(texto: str) -> str:
    """O que se lê na tela e o que se diz em voz alta são diferentes: endereço
    e marcação não se falam."""
    texto = re.sub(r"https?://\S+", "o link na tela", texto or "")
    texto = re.sub(r"```.*?```", "o código na tela", texto, flags=re.DOTALL)
    texto = re.sub(r"[*_#`>|]+", "", texto)
    texto = re.sub(r"^\s*[-•]\s+", "", texto, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", texto).strip()


class Microfone:
    """Quadros de 80 ms do PipeWire. `fonte` é o nome do nó (`wpctl status`);
    vazio é a entrada padrão."""

    def __init__(self, fonte: str = "", binario: str = "pw-record"):
        self.fonte = fonte
        self.binario = shutil.which(binario)
        self.processo = None

    def disponivel(self):
        return bool(self.binario)

    def diagnostico(self):
        return "pw-record pronto" if self.binario else "pw-record não encontrado (PipeWire)"

    def quadros(self, parado):
        comando = [self.binario, "--raw", "--rate", str(TAXA), "--channels", "1",
                   "--format", "s16"]
        if self.fonte:
            comando += ["--target", self.fonte]
        self.processo = subprocess.Popen(comando + ["-"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)
        try:
            while not parado.is_set():
                dados = self.processo.stdout.read(BYTES_DO_QUADRO)
                if len(dados) < BYTES_DO_QUADRO:
                    return
                yield dados
        finally:
            self.fechar()

    def fechar(self):
        if self.processo is not None and self.processo.poll() is None:
            self.processo.terminate()
            try:
                self.processo.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.processo.kill()


class PalavraDeAtivacao:
    """openwakeword com o modelo `hey_jarvis` de partida. Um modelo treinado
    para "Zeus" entra pelo caminho do .onnx em `escuta_palavra`."""

    def __init__(self, modelo: str = "hey_jarvis", limiar: float = 0.5):
        self.modelo = modelo
        self.limiar = limiar
        self._motor = None
        self._erro = ""

    def disponivel(self):
        try:
            import numpy  # noqa: F401
            import openwakeword  # noqa: F401
            return True
        except Exception:
            return False

    def diagnostico(self):
        if not self.disponivel():
            return "openwakeword não instalado (extra opcional)"
        if self._erro:
            return f"falhou ao carregar: {self._erro}"
        return f"palavra {self.modelo}, limiar {self.limiar}"

    def _carregar(self):
        if self._motor is None:
            from openwakeword.model import Model
            try:
                self._motor = Model(wakeword_models=[self.modelo], inference_framework="onnx")
            except Exception as erro:
                self._erro = str(erro)[:200]
                raise
        return self._motor

    def pontuar(self, quadro: bytes) -> float:
        import numpy as np
        pontos = self._carregar().predict(np.frombuffer(quadro, dtype=np.int16))
        return max(pontos.values()) if pontos else 0.0

    def ouviu(self, quadro: bytes) -> bool:
        return self.pontuar(quadro) >= self.limiar

    def reiniciar(self):
        if self._motor is not None:
            self._motor.reset()


class FimDeFala:
    """Fala é energia acima do piso de ruído da sala; fim é silêncio que dura."""

    def __init__(self, silencio_ms=800, espera_inicio_s=5.0, maximo_s=30.0,
                 fator=3.0, minimo=300.0):
        self.silencio_ms = silencio_ms
        self.espera_inicio_s = espera_inicio_s
        self.maximo_s = maximo_s
        self.fator = fator
        self.minimo = minimo
        self.piso = minimo / fator
        self.novo()

    def calibrar(self, nivel_do_quadro: float):
        """Chamado enquanto dorme: o piso acompanha a sala devagar. Só quadro
        abaixo do limiar conta; conversa na sala não pode virar "ruído"."""
        if nivel_do_quadro < self.limiar:
            self.piso = 0.95 * self.piso + 0.05 * nivel_do_quadro

    @property
    def limiar(self):
        return max(self.minimo, self.piso * self.fator)

    def novo(self, espera_inicio_s=None):
        self._espera = self.espera_inicio_s if espera_inicio_s is None else espera_inicio_s
        self._ms = 0
        self._silencio = 0
        self.falou = False

    def alimentar(self, quadro: bytes) -> str:
        """'aguardando', 'falando', 'fim', 'desistiu' ou 'limite'."""
        self._ms += MS_DO_QUADRO
        if nivel(quadro) > self.limiar:
            self.falou = True
            self._silencio = 0
        elif self.falou:
            self._silencio += MS_DO_QUADRO
            if self._silencio >= self.silencio_ms:
                return "fim"
        if not self.falou and self._ms >= self._espera * 1000:
            return "desistiu"
        if self._ms >= self.maximo_s * 1000:
            return "limite"
        return "falando" if self.falou else "aguardando"


class GuardaDeEco:
    """Microfone fechado enquanto o Zeus fala, mais latência e cauda."""

    def __init__(self, cauda_s: float = 0.25, relogio=None):
        self.cauda_s = cauda_s
        self.relogio = relogio or time.monotonic
        self._ate = 0.0

    def falando(self, duracao_s: float, latencia_s: float = 0.0):
        self._ate = max(self._ate, self.relogio() + duracao_s + latencia_s + self.cauda_s)

    def terminou(self):
        self._ate = self.relogio() + self.cauda_s

    def aberto(self) -> bool:
        return self.relogio() >= self._ate


def duracao_do_wav(arquivo) -> float:
    try:
        with wave.open(str(arquivo)) as entrada:
            return entrada.getnframes() / float(entrada.getframerate() or 1)
    except (OSError, wave.Error, EOFError):
        return 0.0


class AltoFalante:
    def __init__(self, guarda: GuardaDeEco, destino: str = "", binario: str = "pw-play",
                 latencia_s: float = 0.15):
        self.guarda = guarda
        self.destino = destino
        self.binario = shutil.which(binario)
        self.latencia_s = latencia_s
        self._processo = None

    def disponivel(self):
        return bool(self.binario)

    def tocar(self, arquivo) -> bool:
        if not self.binario or arquivo is None:
            return False
        self.guarda.falando(duracao_do_wav(arquivo), self.latencia_s)
        comando = [self.binario] + (["--target", self.destino] if self.destino else [])
        try:
            self._processo = subprocess.Popen(comando + [str(arquivo)],
                                              stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
            self._processo.wait(timeout=180)
            return self._processo.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
        finally:
            self.guarda.terminou()

    def parar(self):
        if self._processo is not None and self._processo.poll() is None:
            self._processo.terminate()


class EscutaContinua:
    DORMINDO, OUVINDO = "dormindo", "ouvindo"

    def __init__(self, microfone, palavra, fim, guarda, alto_falante, ouvidos, voz,
                 enfileirar, publicar=None, emitir=None, pasta=None,
                 reconhecimento="Deixa comigo, senhor.", reconhecimento_apos_s=1.5,
                 ao_acordar="", continuacao_s=6.0, espera_resposta_s=120.0):
        self.microfone = microfone
        self.palavra = palavra
        self.fim = fim
        self.guarda = guarda
        self.alto_falante = alto_falante
        self.ouvidos = ouvidos
        self.voz = voz
        self.enfileirar = enfileirar
        self.publicar = publicar or (lambda *a, **k: None)
        self.emitir = emitir or (lambda *a, **k: None)
        self.pasta = Path(pasta) if pasta else Path(tempfile.gettempdir()) / "zeus-ambiente"
        self.pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.reconhecimento = reconhecimento
        self.reconhecimento_apos_s = reconhecimento_apos_s
        self.ao_acordar = ao_acordar
        self.continuacao_s = continuacao_s
        self.espera_resposta_s = espera_resposta_s
        self.estado = self.DORMINDO
        self._gravado = []
        self._continuando = False
        self._quadros = queue.Queue(maxsize=64)
        self._parado = threading.Event()
        self._threads = []

    # ----------------------------------------------------------- ciclo
    def iniciar(self):
        for alvo, nome in ((self._ler, "zeus-microfone"), (self._rodar, "zeus-ambiente")):
            thread = threading.Thread(target=alvo, daemon=True, name=nome)
            thread.start()
            self._threads.append(thread)

    def parar(self):
        self._parado.set()
        self.microfone.fechar()
        self.alto_falante.parar()

    def _ler(self):
        """Lê o microfone sem parar; quadro que não cabe na fila é descartado,
        para nunca processar áudio velho depois de uma resposta longa."""
        while not self._parado.is_set():
            try:
                for quadro in self.microfone.quadros(self._parado):
                    try:
                        self._quadros.put_nowait(quadro)
                    except queue.Full:
                        pass
            except OSError as erro:
                self.emitir("ambiente_microfone_falhou", detalhe=str(erro)[:200])
            if not self._parado.is_set():
                self.emitir("ambiente_microfone_reiniciado")
                self._parado.wait(2)

    def _rodar(self):
        while not self._parado.is_set():
            try:
                quadro = self._quadros.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.processar(quadro)
            except Exception as erro:  # o laço da escuta não morre por um quadro
                self.emitir("ambiente_falhou", detalhe=str(erro)[:200])
                self._dormir()

    # ------------------------------------------------- máquina de estados
    def processar(self, quadro: bytes):
        if not self.guarda.aberto():
            return  # é a voz do próprio Zeus saindo do alto-falante
        if self.estado == self.DORMINDO:
            self.fim.calibrar(nivel(quadro))
            if self.palavra.ouviu(quadro):
                self._acordar()
            return
        self._gravado.append(quadro)
        situacao = self.fim.alimentar(quadro)
        if situacao == "desistiu":
            self._dormir()
        elif situacao in ("fim", "limite"):
            self._responder(b"".join(self._gravado))

    def _acordar(self):
        self.emitir("ambiente_acordou")
        self.estado = self.OUVINDO
        self._gravado = []
        self.fim.novo()
        self.publicar("situacao", estado="ouvindo", detalhe="pode falar")
        if self.ao_acordar:
            self._falar(self.ao_acordar)

    def _dormir(self):
        self.estado = self.DORMINDO
        self._gravado = []
        self._continuando = False
        self.palavra.reiniciar()
        self._esvaziar()
        self.publicar("situacao", estado="ocioso", detalhe="—")

    def _esvaziar(self):
        while True:
            try:
                self._quadros.get_nowait()
            except queue.Empty:
                return

    def _responder(self, pcm: bytes):
        self.publicar("situacao", estado="pensando", detalhe="transcrevendo")
        arquivo = self.pasta / f"fala-{time.time_ns()}.wav"
        with wave.open(str(arquivo), "wb") as saida:
            saida.setnchannels(1)
            saida.setsampwidth(2)
            saida.setframerate(TAXA)
            saida.writeframes(pcm)
        inicio = time.perf_counter()
        texto = limpar_transcricao(self.ouvidos.transcrever(str(arquivo), remover=True))
        transcrito = time.perf_counter()
        if not texto:
            self.emitir("ambiente_sem_texto", detalhe=self.ouvidos.diagnostico()[:200])
            self._dormir()
            return
        resposta = queue.Queue(maxsize=1)
        try:
            self.enfileirar({"tipo": "ambiente", "texto": texto, "responder": resposta.put})
        except queue.Full:
            self._falar("Estou ocupado agora, senhor. Repita daqui a pouco.")
            self._dormir()
            return
        final = self._aguardar(resposta)
        respondido = time.perf_counter()
        if final:
            self._falar(final)
        self.emitir("ambiente_turno", transcricao_s=round(transcrito - inicio, 3),
                    resposta_s=round(respondido - transcrito, 3),
                    reconheceu=bool(self.reconhecimento) and
                    respondido - transcrito > self.reconhecimento_apos_s)
        self._esvaziar()
        # Emendar a próxima frase sem a palavra de ativação.
        self.estado = self.OUVINDO
        self._gravado = []
        self._continuando = True
        self.fim.novo(espera_inicio_s=self.continuacao_s)
        self.publicar("situacao", estado="ouvindo", detalhe="pode continuar")

    def _aguardar(self, resposta):
        try:
            return resposta.get(timeout=self.reconhecimento_apos_s)
        except queue.Empty:
            pass
        if self.reconhecimento:
            self._falar(self.reconhecimento)
        try:
            return resposta.get(timeout=self.espera_resposta_s)
        except queue.Empty:
            return "Isto está demorando mais do que devia, senhor. Mando por escrito quando terminar."

    def _falar(self, texto):
        dito = para_fala(texto)
        if not dito or not self.voz.disponivel():
            return
        self.publicar("situacao", estado="falando", detalhe="")
        self.alto_falante.tocar(self.voz.falar(dito))


def montar_escuta_ambiente(config, estado, ouvidos, voz, enfileirar, publicar=None, emitir=None):
    """A escuta montada, ou (None, motivo) quando falta peça ou está desligada."""
    if not config.escuta_ambiente:
        return None, "desligada (escuta_ambiente)"
    microfone = Microfone(config.escuta_ambiente_fonte)
    palavra = PalavraDeAtivacao(config.escuta_palavra, config.escuta_palavra_limiar)
    guarda = GuardaDeEco()
    alto_falante = AltoFalante(guarda, config.escuta_ambiente_saida)
    faltas = [motivo for pronto, motivo in (
        (microfone.disponivel(), microfone.diagnostico()),
        (palavra.disponivel(), palavra.diagnostico()),
        (alto_falante.disponivel(), "pw-play não encontrado"),
        (ouvidos.disponivel(), ouvidos.diagnostico()),
        (voz.disponivel(), voz.diagnostico())) if not pronto]
    if faltas:
        return None, "; ".join(faltas)
    escuta = EscutaContinua(
        microfone, palavra, FimDeFala(silencio_ms=config.escuta_fim_silencio_ms),
        guarda, alto_falante, ouvidos, voz, enfileirar, publicar=publicar, emitir=emitir,
        pasta=Path(estado) / "ambiente", reconhecimento=config.escuta_reconhecimento,
        reconhecimento_apos_s=config.escuta_reconhecimento_apos_s,
        ao_acordar=config.escuta_ao_acordar, continuacao_s=config.escuta_continuacao_s)
    return escuta, f"pronta: {palavra.diagnostico()}"
