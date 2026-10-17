"""Vigia de hardware do X99 (#76): avisa quando a máquina está em apuro.

Lê o mesmo retrato do painel de saúde (`saude.py`) e compara com limites. Um
alerta exige `confirmacoes` leituras seguidas acima do limite, porque um pico
de um segundo na CPU não é problema. Depois de avisar, a mesma medida fica
quieta por `silencio_s`. A volta ao normal é avisada uma vez e só conta
abaixo do limite menos `margem`, para o aviso não piscar no limiar. A ideia
da histerese vem do Mark-LV; o código é próprio.
"""

import time

GB = 1024 ** 3


def _gpu(retrato, campo):
    valores = [g.get(campo) for g in retrato.get("gpu") or [] if g.get(campo) is not None]
    return max(valores) if valores else None


def _disco_livre_pct(retrato):
    disco = (retrato.get("disco") or {}).get("estado") or {}
    if not disco.get("total"):
        return None
    return 100.0 * disco["livre"] / disco["total"]


def _troca_pct(retrato):
    memoria = retrato.get("memoria") or {}
    if not memoria.get("troca_total"):
        return None
    return 100.0 * memoria.get("troca_usada", 0) / memoria["troca_total"]


# nome, como ler, limite padrão, sentido (+1: ruim acima; -1: ruim abaixo),
# margem de volta, unidade e frase.
MEDIDAS = {
    "cpu_celsius": (lambda r: (r.get("cpu") or {}).get("celsius"), 85, +1, 5, "°C",
                    "a CPU está a {v:.0f} °C"),
    "gpu_celsius": (lambda r: _gpu(r, "celsius"), 85, +1, 5, "°C",
                    "a placa de vídeo está a {v:.0f} °C"),
    "vram_pct": (lambda r: _gpu(r, "percentual_memoria"), 98, +1, 5, "%",
                 "a memória da placa de vídeo está em {v:.0f}%"),
    "ram_pct": (lambda r: (r.get("memoria") or {}).get("percentual"), 92, +1, 5, "%",
                "a memória RAM está em {v:.0f}%"),
    "troca_pct": (_troca_pct, 50, +1, 10, "%", "a swap está em {v:.0f}%"),
    "disco_livre_pct": (_disco_livre_pct, 10, -1, 3, "%",
                        "o disco tem só {v:.0f}% livre"),
}


class VigiaDeHardware:
    def __init__(self, limites=None, confirmacoes=3, silencio_s=1800, relogio=None):
        self.limites = {nome: m[1] for nome, m in MEDIDAS.items()}
        self.limites.update({k: float(v) for k, v in (limites or {}).items() if k in MEDIDAS})
        self.confirmacoes = max(1, confirmacoes)
        self.silencio_s = silencio_s
        self.relogio = relogio or time.monotonic
        self._seguidas = {}
        self._alertado = {}
        self._ultimo_aviso = {}

    def _ruim(self, nome, valor):
        _, _, sentido, _, _, _ = MEDIDAS[nome]
        limite = self.limites[nome]
        return valor >= limite if sentido > 0 else valor <= limite

    def _normal(self, nome, valor):
        _, _, sentido, margem, _, _ = MEDIDAS[nome]
        limite = self.limites[nome]
        return valor < limite - margem if sentido > 0 else valor > limite + margem

    def avaliar(self, retrato: dict) -> list:
        """Os avisos desta leitura (texto pronto para o grupo e para a fala)."""
        avisos, agora = [], self.relogio()
        for nome, (ler, _, _, _, _, frase) in MEDIDAS.items():
            try:
                valor = ler(retrato)
            except (TypeError, ValueError, ZeroDivisionError):
                valor = None
            if valor is None:
                continue  # medida que não existe aqui não vira zero nem alerta
            if self._ruim(nome, valor):
                self._seguidas[nome] = self._seguidas.get(nome, 0) + 1
                calado = agora - self._ultimo_aviso.get(nome, -1e12) < self.silencio_s
                if self._seguidas[nome] >= self.confirmacoes and not calado:
                    self._alertado[nome] = True
                    self._ultimo_aviso[nome] = agora
                    avisos.append(f"Senhor, atenção: {frase.format(v=valor)}.")
                continue
            self._seguidas[nome] = 0
            if self._alertado.get(nome) and self._normal(nome, valor):
                self._alertado[nome] = False
                avisos.append(f"Normalizou: {frase.format(v=valor)}.")
        return avisos
