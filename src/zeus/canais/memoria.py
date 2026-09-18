"""Canal em memória: usado em teste e no modo CLI, nunca em produção."""


class CanalMemoria:
    nome = "memoria"

    def __init__(self, falhar=False):
        self.enviados = []
        self.recebidos = []
        self.falhar = falhar

    def enviar(self, texto: str):
        if self.falhar:
            raise RuntimeError("canal indisponível")
        self.enviados.append(texto)

    def receber(self, espera: int = 0):
        pendentes, self.recebidos = self.recebidos, []
        return pendentes

    def confirmar(self, identificador):
        return None
