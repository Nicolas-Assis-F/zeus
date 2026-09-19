"""Canal em memória: usado em teste e no modo CLI, nunca em produção."""


from ..entregas import NaoEnviado


class CanalMemoria:
    nome = "memoria"

    def __init__(self, falhar=False):
        self.enviados = []
        self.recebidos = []
        self.falhar = falhar

    def enviar(self, texto: str):
        if self.falhar:
            raise NaoEnviado("canal indisponível")
        self.enviados.append(texto)

    def digitando(self):
        self.avisos_de_digitacao = getattr(self, "avisos_de_digitacao", 0) + 1

    def receber(self, espera: int = 0):
        pendentes, self.recebidos = self.recebidos, []
        return pendentes

    def confirmar(self, identificador):
        return None
