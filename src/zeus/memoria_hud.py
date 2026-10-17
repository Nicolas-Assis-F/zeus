"""Esquecer um fato pela HUD, com desfazer (#79).

A HUD só pede; quem apaga é o laço principal, dono da conexão com o banco. O
desfazer restaura exatamente o que foi apagado, guardado aqui por
`janela_s`: a HUD nunca escreve um fato arbitrário na memória. Cada
esquecimento fica registrado como episódio, como as ações no computador.
"""

import time

JANELA_S = 300


class MemoriaDaHUD:
    def __init__(self, store, janela_s: float = JANELA_S, relogio=None):
        self.store = store
        self.janela_s = janela_s
        self.relogio = relogio or time.monotonic
        self._lixeira = {}

    def _registrar(self, tipo, chave, resumo):
        episodio = self.store.abrir_episodio(tipo, f"{resumo}: {chave}"[:300])
        self.store.registrar_evento(episodio, "hud", tipo, {"chave": chave[:200]})
        self.store.fechar_episodio(episodio, resumo)

    def esquecer(self, chave: str) -> dict:
        fato = self.store.recall(chave)
        if fato is None or not self.store.forget(chave):
            return {"acao": "esquecer", "fato": chave, "ok": False,
                    "texto": f"Não achei «{chave}» na memória."}
        self._lixeira[chave] = (fato, self.relogio())
        self._registrar("memoria_esquecida", chave, "esquecido pela HUD")
        return {"acao": "esquecida", "fato": chave, "ok": True,
                "texto": f"Esqueci «{chave}».", "desfazer_s": self.janela_s}

    def desfazer(self, chave: str) -> dict:
        guardado = self._lixeira.pop(chave, None)
        if guardado is None or self.relogio() - guardado[1] > self.janela_s:
            return {"acao": "desfazer", "fato": chave, "ok": False,
                    "texto": f"Não dá mais para desfazer «{chave}»."}
        fato = guardado[0]
        self.store.remember(chave, fato["value"], fato["source"], fato["estado"],
                            fato.get("validade"))
        self._registrar("memoria_restaurada", chave, "restaurado pela HUD")
        return {"acao": "restaurada", "fato": chave, "ok": True,
                "texto": f"Pronto, «{chave}» voltou para a memória."}

    def executar(self, acao: str, chave: str) -> dict:
        if acao == "esquecer":
            return self.esquecer(chave)
        if acao == "desfazer":
            return self.desfazer(chave)
        return {"acao": acao, "fato": chave, "ok": False, "texto": "Ação desconhecida."}
