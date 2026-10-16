"""Base de conhecimento: o que Nicolas e o Claude sabem dos negócios dele.

Preço, importação, clientes, contas a receber. Mora fora de qualquer
repositório (o do Zeus é público), numa pasta só dele, em Markdown.

Esta é a única leitura de arquivo que **não** sai marcada como externa, e a
razão é quem escreve: a pasta é mantida por Nicolas e pelo Claude, nunca por
terceiro. Por isso o Zeus pode consultar o preço aqui e, na mesma resposta,
seguir usando ferramentas. Quem colocar nesta pasta conteúdo de terceiro
(mensagem, página, PDF recebido) quebra a barreira da #9. Conteúdo de fora vai
pelas ferramentas de leitura, que marcam o resultado como externo.

A leitura fica presa à pasta: só arquivos `.md` diretamente dentro dela, sem
link simbólico, sem subpasta, sem `..`.

Seções marcadas INTERNO (custo, margem, lucro) servem a Nicolas e nunca a
cliente. Com `finalidade="orcamento"` a busca fica no catálogo e no manual de
orçamento, e ainda saem as seções cujo título ou nota de abertura dizem
INTERNO, as filhas delas, e as colunas INTERNO das tabelas.
"""

import os
import re
from pathlib import Path

from .conversas import normalizar

MAXIMO_POR_SECAO = 3500
MAXIMO_TOTAL = 9000
MAXIMO_DE_SECOES = 4
MAXIMO_DO_INDICE = 4000
INDICE = "LEIA-ME.md"
# Orçamento só lê o que foi escrito para isso. A importação e os clientes têm
# custo em lista solta, sem marca, e filtrar texto ali vazaria (a seção 4.3 da
# importação traz "custo por peça" fora de qualquer seção INTERNO).
ARQUIVOS_DE_ORCAMENTO = ("catalogo-e-precos.md", "orcamentos.md")
TITULO = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
MARCA = re.compile(r"\bINTERN[OA]S?\b")
CUSTO_INTERNO = re.compile(r"\bcustos? intern[oa]s?\b")
VAZIAS = set("de da do das dos e o a os as um uma uns umas para pra por com que qual quais "
             "quanto quanta quantos quem me eu em no na nos nas ao aos se ja tem ter tudo "
             "ainda ficou fica esta este isso essa esse meu minha sobre como".split())


class BaseRecusada(ValueError):
    pass


def termos(busca: str) -> list:
    return [t for t in normalizar(busca).split()
            if (len(t) >= 3 or any(c.isdigit() for c in t)) and t not in VAZIAS]


def interno(texto: str) -> bool:
    """A marca da base é INTERNO em maiúsculas, ou "custo(s) interno(s)".
    "O livro interno" (a conversa com o pai) não é custo."""
    return bool(MARCA.search(texto) or CUSTO_INTERNO.search(normalizar(texto)))


def sem_colunas_internas(texto: str) -> str:
    """Tira das tabelas Markdown as colunas cujo cabeçalho diz INTERNO."""
    linhas, saida, i = texto.split("\n"), [], 0
    while i < len(linhas):
        if not linhas[i].lstrip().startswith("|"):
            saida.append(linhas[i])
            i += 1
            continue
        bloco = []
        while i < len(linhas) and linhas[i].lstrip().startswith("|"):
            bloco.append(linhas[i])
            i += 1
        celulas = [l.strip().strip("|").split("|") for l in bloco]
        fora = {n for n, c in enumerate(celulas[0]) if interno(c)}
        for linha in celulas:
            mantidas = [c for n, c in enumerate(linha) if n not in fora]
            saida.append("|" + "|".join(mantidas) + "|")
    return "\n".join(saida)


class Base:
    def __init__(self, pasta: str):
        self.pasta = Path(os.path.expanduser(pasta)) if pasta else None

    # ------------------------------------------------------------- arquivos
    def disponivel(self) -> bool:
        return bool(self.pasta and self.pasta.is_dir() and not self.pasta.is_symlink())

    def diagnostico(self) -> str:
        if not self.pasta:
            return "desligada"
        if self.pasta.is_symlink():
            return "recusada: a pasta é link simbólico"
        if not self.pasta.is_dir():
            return "pasta não encontrada"
        return f"{len(self.arquivos())} arquivos"

    def _arquivo(self, nome: str) -> Path:
        nome = str(nome or "").strip()
        if (not nome or "/" in nome or "\\" in nome or nome.startswith(".")
                or not nome.endswith(".md")):
            raise BaseRecusada(f"'{nome}' não é um arquivo da base. Use só o nome, como "
                               "catalogo-e-precos.md.")
        alvo = self.pasta / nome
        if alvo.is_symlink():
            raise BaseRecusada(f"'{nome}' é link simbólico; não leio.")
        if not alvo.is_file():
            raise BaseRecusada(f"'{nome}' não existe na base.")
        if alvo.resolve().parent != self.pasta.resolve():
            raise BaseRecusada(f"'{nome}' fica fora da base; não leio.")
        return alvo

    def arquivos(self) -> list:
        if not self.disponivel():
            return []
        nomes = []
        for alvo in sorted(self.pasta.iterdir()):
            try:
                self._arquivo(alvo.name)
            except BaseRecusada:
                continue
            nomes.append(alvo.name)
        return nomes

    def indice(self) -> str:
        """O LEIA-ME, para o sistema: o que existe e quando consultar."""
        if not self.disponivel() or INDICE not in self.arquivos():
            return ""
        return self._arquivo(INDICE).read_text(encoding="utf-8")[:MAXIMO_DO_INDICE]

    # ------------------------------------------------------------- seções
    def secoes(self, nome: str) -> list:
        """Cada título com o próprio corpo, o caminho de títulos e se é INTERNO.

        Duas passadas: a nota de abertura só é conhecida depois de ler o
        corpo, e as filhas herdam dela tanto quanto do título."""
        brutas = [{"nivel": 0, "nome": nome, "linhas": []}]
        for linha in self._arquivo(nome).read_text(encoding="utf-8").split("\n"):
            titulo = TITULO.match(linha)
            if titulo:
                brutas.append({"nivel": len(titulo.group(1)), "nome": titulo.group(2),
                               "linhas": []})
            else:
                brutas[-1]["linhas"].append(linha)
        resultado, caminho = [], []
        for secao in brutas:
            corpo = "\n".join(secao["linhas"]).strip()
            abertura = next((l for l in corpo.split("\n") if l.strip()), "")
            proprio = interno(secao["nome"]) if secao["nivel"] else False
            proprio = proprio or (abertura.lstrip().startswith(">") and interno(abertura))
            caminho = [c for c in caminho if c["nivel"] < secao["nivel"]]
            herdado = any(c["interno"] for c in caminho)
            caminho.append({"nivel": secao["nivel"], "nome": secao["nome"],
                            "interno": proprio or herdado})
            if corpo:
                resultado.append({"arquivo": nome,
                                  "titulo": " › ".join(c["nome"] for c in caminho[1:]) or nome,
                                  "texto": corpo, "interno": proprio or herdado})
        return resultado

    def consultar(self, busca: str, arquivo: str = "", finalidade: str = "consulta") -> dict:
        if not self.disponivel():
            raise BaseRecusada("A base de conhecimento não está configurada neste computador.")
        para_orcamento = finalidade == "orcamento"
        nomes = [self._arquivo(arquivo).name] if arquivo else self.arquivos()
        if para_orcamento:
            nomes = [n for n in nomes if n in ARQUIVOS_DE_ORCAMENTO]
            if not nomes:
                raise BaseRecusada("Para orçamento só consulto catalogo-e-precos.md e "
                                   "orcamentos.md: custo interno não vai para cliente.")
        procurados = termos(busca)
        if not procurados:
            raise BaseRecusada("Diga o que procurar, por exemplo: martelo CIR110 revenda.")
        achadas = []
        for nome in nomes:
            for secao in self.secoes(nome):
                if para_orcamento and secao["interno"]:
                    continue
                titulo, corpo = normalizar(secao["titulo"]), normalizar(secao["texto"])
                presentes = [t for t in procurados if t in titulo or t in corpo]
                if not presentes:
                    continue
                pontos = sum(5 * (t in titulo) + min(corpo.count(t), 5) for t in presentes)
                pontos += 10 * (len(presentes) == len(procurados))
                achadas.append((pontos, secao))
        achadas.sort(key=lambda par: -par[0])
        resultado, total = [], 0
        for _, secao in achadas[:MAXIMO_DE_SECOES]:
            texto = secao["texto"]
            if para_orcamento:
                texto = sem_colunas_internas(texto)
            texto = texto[:MAXIMO_POR_SECAO]
            if total + len(texto) > MAXIMO_TOTAL:
                break
            total += len(texto)
            item = {"arquivo": secao["arquivo"], "secao": secao["titulo"], "texto": texto}
            if secao["interno"]:
                item["interno"] = True
            resultado.append(item)
        return {"busca": busca, "finalidade": "orcamento" if para_orcamento else "consulta",
                "encontrado": bool(resultado), "secoes": resultado}
