"""Autonomia do Zeus (fase 2): a camada de dados e regras, sem modelo nenhum.

Aqui ficam os objetivos que atravessam turnos, a guarda contra laço, o nível
de permissão de cada ação, a caixa de aprovações por código, a trilha
encadeada e o feedback dos avisos. Nada aqui chama LLM, rede ou ferramenta:
quem executa é o núcleo, que consulta esta camada antes e registra nela
depois. Assim as regras de segurança são testáveis sem modelo e não dependem
do que o modelo resolver dizer.

Uso típico:

    autonomia = Autonomia(segredo=segredo_do_arquivo())
    objetivo_id = autonomia.objetivos.criar("Cobrar o frete com o Henrique", ...)

Ver docs/AUTONOMIA.md.
"""

from .aprovacoes import VALIDADE_PADRAO_S, Aprovacoes, interpretar_resposta
from .banco import CAMINHO_PADRAO, Banco, args_hash, dia_local, fuso_padrao
from .feedback import Feedback
from .niveis import (AUTONOMIAS, CATALOGO_DE_NIVEIS, Classificacao, Nivel, RegraDeNivel,
                     classificar, nivel_efetivo)
from .objetivos import LOCK_ZUMBI_S, Objetivos, TransicaoInvalida, Veredito
from .trilha import Trilha, segredo_do_arquivo

__all__ = [
    "AUTONOMIAS", "Aprovacoes", "Autonomia", "Banco", "CAMINHO_PADRAO", "CATALOGO_DE_NIVEIS",
    "Classificacao", "Feedback", "Nivel", "Objetivos", "RegraDeNivel", "Trilha",
    "TransicaoInvalida", "Veredito", "args_hash", "classificar", "dia_local", "fuso_padrao",
    "interpretar_resposta", "nivel_efetivo", "segredo_do_arquivo",
]


class Autonomia:
    """Abre o banco e monta as partes ligadas entre si.

    `segredo` assina a trilha (o chamador lê de ~/.config/zeus com
    `segredo_do_arquivo`; em teste, um valor fixo). `relogio` devolve epoch
    float; `fuso` define o "dia" dos contadores (padrão America/Sao_Paulo).
    """

    def __init__(self, caminho=None, segredo=None, relogio=None, fuso=None,
                 lock_zumbi_s=LOCK_ZUMBI_S, validade_aprovacao_s=VALIDADE_PADRAO_S):
        self.banco = Banco(caminho, relogio=relogio, fuso=fuso)
        try:
            self.trilha = Trilha(self.banco, segredo)
        except ValueError:
            self.banco.fechar()
            raise
        self.objetivos = Objetivos(self.banco, self.trilha, lock_zumbi_s=lock_zumbi_s)
        self.aprovacoes = Aprovacoes(self.banco, self.trilha, self.objetivos,
                                     validade_s=validade_aprovacao_s)
        self.feedback = Feedback(self.banco)

    def fechar(self):
        self.banco.fechar()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechar()
