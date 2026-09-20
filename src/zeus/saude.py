"""Sinais vitais da máquina onde o Zeus mora.

A HUD não é só a janela de conversa: é o painel de saúde do X99, que roda
sem monitor num canto da casa. Quando o Zeus fica lento, a pergunta é sempre
a mesma — é o modelo, é a RAM, é a GPU térmica, é o disco cheio? Sem número
na tela a resposta vira palpite.

Tudo aqui sai de `/proc`, de `/sys` e de `nvidia-smi`. Nenhuma biblioteca
externa: a promessa do projeto é clonar e rodar. Nada aqui levanta exceção
para quem chama — uma métrica que não existe volta `None`, e o painel mostra
"—" em vez de mentir um zero.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

PROC = Path("/proc")
INTERVALO_DA_GPU = 3.0          # nvidia-smi custa ~40ms; não vale a cada amostra
TEMPO_LIMITE_DA_GPU = 4.0
HISTORICO = 90                  # ~3 minutos a uma amostra a cada 2s


def _ler(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _numero(texto: str):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------- CPU
def ler_cpu(texto: str):
    """Soma os tempos de /proc/stat por núcleo.

    O arquivo dá totais desde o boot, não percentual. A ocupação só existe
    entre duas leituras, então aqui devolvemos os acumulados e quem compara
    é `Saude`."""
    linhas = {}
    for linha in texto.splitlines():
        if not linha.startswith("cpu"):
            continue
        partes = linha.split()
        nome = partes[0]
        try:
            campos = [int(v) for v in partes[1:11]]
        except ValueError:
            continue
        if len(campos) < 5:
            continue
        ocioso = campos[3] + campos[4]          # idle + iowait
        linhas[nome] = (sum(campos), ocioso)
    return linhas


def _ocupacao(antes, agora):
    if not antes or not agora:
        return None
    total = agora[0] - antes[0]
    ocioso = agora[1] - antes[1]
    if total <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * (total - ocioso) / total))


def modelo_da_cpu(texto: str) -> str:
    for linha in texto.splitlines():
        if linha.lower().startswith("model name"):
            return linha.split(":", 1)[-1].strip()
    return ""


def frequencia_mhz(texto: str):
    """Média das frequências correntes, em MHz.

    Num X99 os núcleos raramente andam juntos; a média é o que cabe num
    painel, e a variação por núcleo já aparece nas barras de ocupação."""
    valores = [_numero(l.split(":", 1)[-1].strip())
               for l in texto.splitlines() if l.lower().startswith("cpu mhz")]
    valores = [v for v in valores if v]
    if not valores:
        return None
    return round(sum(valores) / len(valores))


# --------------------------------------------------------------------- RAM
def ler_memoria(texto: str) -> dict:
    campos = {}
    for linha in texto.splitlines():
        nome, _, resto = linha.partition(":")
        valor = _numero(resto.strip().split(" ")[0])
        if valor is not None:
            campos[nome] = valor * 1024          # kB no arquivo, bytes aqui
    total = campos.get("MemTotal")
    if not total:
        return {}
    # MemAvailable já desconta cache recuperável: é o número honesto, e não
    # "free", que num servidor saudável vive perto de zero de propósito.
    disponivel = campos.get("MemAvailable", campos.get("MemFree", 0))
    trocas = campos.get("SwapTotal", 0)
    return {
        "total": total,
        "disponivel": disponivel,
        "usada": total - disponivel,
        "percentual": round(100.0 * (total - disponivel) / total, 1),
        "cache": campos.get("Cached", 0),
        "troca_total": trocas,
        "troca_usada": trocas - campos.get("SwapFree", 0) if trocas else 0,
    }


# ------------------------------------------------------------- temperatura
def temperaturas(raiz: Path = Path("/sys/class/hwmon")) -> list:
    """Sensores que o kernel já expõe, sem lm-sensors instalado."""
    achados = []
    try:
        monitores = sorted(raiz.iterdir())
    except OSError:
        return achados
    for monitor in monitores:
        rotulo_base = _ler(monitor / "name").strip()
        try:
            entradas = sorted(monitor.glob("temp*_input"))
        except OSError:
            continue
        for entrada in entradas:
            valor = _numero(_ler(entrada).strip())
            if valor is None:
                continue
            rotulo = _ler(entrada.with_name(entrada.name.replace("_input", "_label"))).strip()
            achados.append({
                "sensor": rotulo_base or monitor.name,
                "rotulo": rotulo or entrada.stem.replace("_input", ""),
                "celsius": round(valor / 1000.0, 1),
            })
    return achados


def _resumo_termico(sensores: list):
    """Uma temperatura para o painel: a do pacote da CPU, se houver."""
    for sensor in sensores:
        if sensor["sensor"] in ("coretemp", "k10temp", "zenpower") and \
           sensor["rotulo"].lower().startswith(("package", "tctl", "tdie")):
            return sensor["celsius"]
    quentes = [s["celsius"] for s in sensores if s["celsius"] < 125]
    return max(quentes) if quentes else None


# --------------------------------------------------------------------- GPU
CAMPOS_DA_GPU = ("name,utilization.gpu,memory.used,memory.total,"
                 "temperature.gpu,power.draw,power.limit,fan.speed")


def interpretar_gpu(saida: str) -> list:
    """Lê o CSV do nvidia-smi. Campos ausentes viram None, não zero.

    `[N/A]` aparece o tempo todo em placas de consumo — potência e ventoinha,
    principalmente. Zero ali seria uma leitura errada disfarçada de medida."""
    placas = []
    for linha in saida.strip().splitlines():
        partes = [p.strip() for p in linha.split(",")]
        if len(partes) < 8:
            continue
        nome = partes[0]
        numeros = [None if p.lower().startswith(("[n/a", "n/a", "[not")) else _numero(p)
                   for p in partes[1:8]]
        uso, mem_usada, mem_total, temp, potencia, teto, ventoinha = numeros
        placas.append({
            "nome": nome,
            "uso": uso,
            "memoria_usada": int(mem_usada * 1024 * 1024) if mem_usada is not None else None,
            "memoria_total": int(mem_total * 1024 * 1024) if mem_total is not None else None,
            "percentual_memoria": round(100.0 * mem_usada / mem_total, 1)
            if mem_usada is not None and mem_total else None,
            "celsius": temp,
            "watts": potencia,
            "watts_teto": teto,
            "ventoinha": ventoinha,
        })
    return placas


def medir_gpu(executar=None) -> list:
    binario = shutil.which("nvidia-smi")
    if not binario:
        return []
    executar = executar or subprocess.run
    try:
        saida = executar([binario, f"--query-gpu={CAMPOS_DA_GPU}",
                          "--format=csv,noheader,nounits"],
                         capture_output=True, text=True,
                         timeout=TEMPO_LIMITE_DA_GPU, check=True)
    except (subprocess.SubprocessError, OSError):
        return []
    return interpretar_gpu(saida.stdout or "")


# -------------------------------------------------------------------- rede
def ler_rede(texto: str):
    recebido = enviado = 0
    for linha in texto.splitlines()[2:]:
        nome, _, resto = linha.partition(":")
        nome = nome.strip()
        if nome == "lo" or not resto:
            continue
        campos = resto.split()
        if len(campos) < 9:
            continue
        try:
            recebido += int(campos[0])
            enviado += int(campos[8])
        except ValueError:
            continue
    return recebido, enviado


# ------------------------------------------------------------------ disco
def disco(caminho) -> dict:
    try:
        uso = shutil.disk_usage(str(caminho))
    except OSError:
        return {}
    return {"total": uso.total, "usado": uso.used, "livre": uso.free,
            "percentual": round(100.0 * uso.used / uso.total, 1) if uso.total else None}


# --------------------------------------------------------------- processo
def _memoria_do_processo():
    for linha in _ler(PROC / "self/status").splitlines():
        if linha.startswith("VmRSS:"):
            valor = _numero(linha.split()[1])
            return int(valor * 1024) if valor else None
    return None


class Saude:
    """Amostra os sinais vitais e guarda o histórico curto que o painel desenha.

    Só a diferença entre duas amostras diz alguma coisa sobre CPU e rede, então
    esta classe tem memória de propósito. É usada por threads do servidor HTTP,
    e por isso toda leitura acontece sob trava."""

    def __init__(self, caminho_do_estado=None, relogio=time.monotonic,
                 executar_gpu=None):
        self.trava = threading.Lock()
        self.relogio = relogio
        self.executar_gpu = executar_gpu
        self.caminho_do_estado = Path(caminho_do_estado) if caminho_do_estado else Path.home()
        self._cpu_antes = {}
        self._rede_antes = None
        self._momento_antes = None
        self._gpu = []
        self._gpu_em = 0.0
        self._gpu_procurada = False
        self.historico = {"cpu": [], "memoria": [], "gpu": []}
        informacao = _ler(PROC / "cpuinfo")
        self.modelo = modelo_da_cpu(informacao)
        self.nucleos = os.cpu_count() or 1

    # ------------------------------------------------------------ amostra
    def medir(self) -> dict:
        with self.trava:
            return self._medir()

    def _medir(self) -> dict:
        agora = self.relogio()
        cpu_agora = ler_cpu(_ler(PROC / "stat"))
        total = _ocupacao(self._cpu_antes.get("cpu"), cpu_agora.get("cpu"))
        nucleos = []
        for nome in sorted(k for k in cpu_agora if k != "cpu"):
            nucleos.append(_ocupacao(self._cpu_antes.get(nome), cpu_agora.get(nome)))
        self._cpu_antes = cpu_agora

        rede_agora = ler_rede(_ler(PROC / "net/dev"))
        entrada = saida = None
        if self._rede_antes and self._momento_antes is not None:
            intervalo = agora - self._momento_antes
            if intervalo > 0:
                entrada = max(0.0, (rede_agora[0] - self._rede_antes[0]) / intervalo)
                saida = max(0.0, (rede_agora[1] - self._rede_antes[1]) / intervalo)
        self._rede_antes = rede_agora
        self._momento_antes = agora

        memoria = ler_memoria(_ler(PROC / "meminfo"))
        sensores = temperaturas()
        placas = self._gpu_em_cache(agora)
        tempo_ligado = _numero((_ler(PROC / "uptime").split() or [""])[0])
        carga = None
        try:
            carga = [round(v, 2) for v in os.getloadavg()]
        except (OSError, AttributeError):
            pass

        retrato = {
            "tipo": "saude",
            "cpu": {
                "modelo": self.modelo,
                "nucleos": self.nucleos,
                "uso": round(total, 1) if total is not None else None,
                "por_nucleo": [round(v, 1) if v is not None else None for v in nucleos],
                "mhz": frequencia_mhz(_ler(PROC / "cpuinfo")),
                "carga": carga,
                "celsius": _resumo_termico(sensores),
            },
            "memoria": memoria,
            "gpu": placas,
            "disco": {
                "estado": disco(self.caminho_do_estado),
                "raiz": disco("/"),
            },
            "rede": {"entrada": entrada, "saida": saida},
            "sensores": sensores,
            "tempo_ligado_s": tempo_ligado,
            "processo": {"memoria": _memoria_do_processo(),
                         "threads": threading.active_count()},
        }
        self._guardar(retrato)
        retrato["historico"] = {k: list(v) for k, v in self.historico.items()}
        return retrato

    def _guardar(self, retrato):
        def empurrar(chave, valor):
            serie = self.historico[chave]
            serie.append(valor)
            del serie[:-HISTORICO]

        empurrar("cpu", retrato["cpu"]["uso"])
        empurrar("memoria", (retrato["memoria"] or {}).get("percentual"))
        placas = retrato["gpu"]
        empurrar("gpu", placas[0]["uso"] if placas else None)

    def _gpu_em_cache(self, agora):
        """nvidia-smi é caro demais para o ritmo do painel.

        Quando não há placa, a primeira tentativa já responde vazio e nenhuma
        outra acontece: procurar o binário a cada dois segundos para sempre
        não achar nada é desperdício puro."""
        if not self._gpu and self._gpu_procurada and not shutil.which("nvidia-smi"):
            return []
        if self._gpu and (agora - self._gpu_em) < INTERVALO_DA_GPU:
            return self._gpu
        self._gpu_procurada = True
        self._gpu = medir_gpu(self.executar_gpu)
        self._gpu_em = agora
        return self._gpu
