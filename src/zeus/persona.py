"""Persona carregada de arquivo, nunca embutida no código.

O plano mestre trata personalidade como critério de qualidade desde a primeira
entrega. Manter o texto fora do programa permite ajustar tom sem tocar em
lógica, e permite versionar o estilo separadamente do comportamento.
"""

import re
from pathlib import Path

from .contexto import linha_do_fato, selecionar

FALA = re.compile(r"^-\s*(nicolas|zeus)\s*:\s*(.+)$", re.IGNORECASE)
CABECALHO = re.compile(r"^##\s+(.+?)\s*$")
COMENTARIO_HTML = re.compile(r"<!--.*?-->", re.DOTALL)

# Seções do arquivo que falam *sobre* a persona, e não *como* a persona. O
# modelo lê o prompt inteiro como instrução: uma linha explicando que o arquivo
# é editável e que os pares viram turnos reais ensina o registro de documento
# técnico, e a resposta sai com cara de documentação. Os exemplos em si não se
# perdem -- eles entram como turnos de verdade, por `exemplos()`.
SECOES_DE_NOTA = {"exemplos de voz"}

PERSONA_MINIMA = (
    "Você é Zeus, presença pessoal e persistente na casa de Nicolas. "
    "Fala português do Brasil com competência serena e humor seco. "
    "Não afirma ter feito nada sem confirmação do sistema. "
    "Distingue fato confirmado, hipótese e desconhecido."
)


class Persona:
    def __init__(self, texto: str, origem: str):
        self.texto = texto.strip()
        self.origem = origem

    @classmethod
    def carregar(cls, caminho) -> "Persona":
        alvo = cls.resolver(caminho)
        if alvo.exists():
            conteudo = alvo.read_text(encoding="utf-8").strip()
            if conteudo:
                return cls(conteudo, str(alvo))
        return cls(PERSONA_MINIMA, "persona mínima embutida")

    @staticmethod
    def resolver(caminho) -> Path:
        """Um caminho relativo vale a partir do diretório atual ou da raiz do
        repositório. Sem isso, rodar de dentro de src/ cairia na persona mínima
        sem avisar, e a conversa perderia a identidade em silêncio."""
        alvo = Path(caminho)
        if alvo.is_absolute() or alvo.exists():
            return alvo
        raiz = Path(__file__).resolve().parents[2]
        candidato = raiz / alvo
        return candidato if candidato.exists() else alvo

    def exemplos(self):
        """Pares de fala do próprio persona.md, entregues como turnos reais.

        Um modelo pequeno aprende tom por exemplo muito melhor do que por
        adjetivo. Descrever a voz em prosa produz um robô educado; mostrar a
        voz acontecendo produz a voz."""
        mensagens = []
        for linha in self.texto.splitlines():
            casou = FALA.match(linha.strip())
            if not casou:
                continue
            quem, fala = casou.group(1).lower(), casou.group(2).strip()
            papel = "assistant" if quem == "zeus" else "user"
            if mensagens and mensagens[-1]["role"] == papel:
                continue
            if not mensagens and papel == "assistant":
                continue
            mensagens.append({"role": papel, "content": fala})
        if mensagens and mensagens[-1]["role"] == "user":
            mensagens.pop()
        return mensagens

    def instrucao(self) -> str:
        """O que o modelo lê como instrução, sem o que é nota para humano.

        Tudo antes do primeiro `##` é apresentação do arquivo — título e aviso
        de que ele é editável — e não é instrução para ninguém. As seções de
        nota saem inteiras. Os pares de fala saem daqui porque entram como
        turnos reais em `exemplos()`."""
        linhas, guardando, achou_secao = [], False, False
        for linha in COMENTARIO_HTML.sub("", self.texto).splitlines():
            cabecalho = CABECALHO.match(linha.strip())
            if cabecalho:
                achou_secao = True
                guardando = cabecalho.group(1).strip().lower() not in SECOES_DE_NOTA
            if not guardando:
                continue
            if FALA.match(linha.strip()):
                continue
            linhas.append(linha)
        if not achou_secao:
            # Persona sem seção nenhuma (a mínima embutida, por exemplo) vale
            # inteira: não há o que separar.
            return "\n".join(l for l in self.texto.splitlines()
                              if not FALA.match(l.strip())).strip()
        return "\n".join(linhas).strip()

    def sistema(self, fatos=None, perguntas=None, agenda=None, agora=None,
                capacidades=None, incluir_persona=True, mensagem: str = "",
                teto: int = 0) -> str:
        return self.montar(fatos, perguntas, agenda, agora, capacidades,
                           incluir_persona, mensagem, teto)["texto"]

    def montar(self, fatos=None, perguntas=None, agenda=None, agora=None,
               capacidades=None, incluir_persona=True, mensagem: str = "",
               teto: int = 0) -> dict:
        """Monta o contexto e devolve também o que ficou de fora.

        O orçamento é opcional: com `teto` zero o comportamento é o antigo, com
        a memória inteira no prompt."""
        escolha = selecionar(fatos, mensagem, teto)
        partes = ([self.instrucao(), ""] if incluir_persona else [])
        partes += ["## Contexto desta conversa", ""]
        if escolha["nucleo"]:
            partes.append("Fatos confirmados na memória:")
            partes.extend(linha_do_fato(fato) for fato in escolha["nucleo"])
        else:
            partes.append("A memória ainda não tem fato confirmado sobre Nicolas.")
        if escolha["hipoteses"]:
            partes.append("Hipóteses ainda não confirmadas (trate como suposição):")
            partes.extend(linha_do_fato(fato) for fato in escolha["hipoteses"])
        if perguntas:
            partes.append("Perguntas suas ainda em aberto:")
            for pergunta in perguntas:
                partes.append(f"- #{pergunta['id']} {pergunta['texto']} ({pergunta['situacao']})")
        if agenda:
            partes.append("Compromissos que você agendou:")
            for item in agenda:
                partes.append(f"- #{item['id']} {item['texto']} em {item['vence_em']}")
        partes += [
            "",
            "Sobre Nicolas, só existe o que está acima e o que ele disser agora.",
            "Use ferramenta quando ele informar algo para guardar, pedir para "
            "consultar ou esquecer, combinar um horário, ou perguntar o que está "
            "pendente. Para saudação, comentário solto e conversa, responda "
            "conversando: não consulte a memória por causa de um 'opa'.",
            "Capacidades desta versão: conversa, memória e agenda. "
            + ("Voz local disponível. " if (capacidades or {}).get("voz") else "Sem voz disponível. ")
            + ("Escuta local disponível. " if (capacidades or {}).get("ouvidos") else "Sem escuta local disponível. ")
            + "Sem câmera, sem dispositivo, sem ligação. "
            + ("Pesquisa na internet configurada: use pesquisar quando precisar de "
               "informação externa, cite as fontes retornadas e admita falhas ou "
               "evidência insuficiente. Não invente resultados ou datas de publicação."
               if (capacidades or {}).get("pesquisa") else "Sem busca na internet disponível."),
        ]
        # O que muda a cada turno fica por último de propósito: o começo do
        # prompt continua idêntico e o servidor reaproveita o cache em vez de
        # reprocessar a persona inteira a cada mensagem. Os fatos trazidos pela
        # mensagem entram aqui pelo mesmo motivo: eles mudam a cada turno.
        if escolha["trazidos"]:
            partes.append("")
            partes.append("Da memória, por causa do que ele acabou de dizer:")
            partes.extend(linha_do_fato(fato) for fato in escolha["trazidos"])
        if escolha["fora"]:
            partes.append(f"Outros {len(escolha['fora'])} fatos ficaram fora deste "
                          "contexto por orçamento. Se precisar de um, consulte pela chave.")
        if agora is not None:
            partes.append(f"Momento atual: {agora.astimezone().strftime('%d/%m/%Y %H:%M')}.")
        if incluir_persona:
            # A última linha antes da mensagem é a que mais pesa no registro de
            # um modelo pequeno. Tudo acima dela é inventário -- memória,
            # pendências, capacidades -- e inventário lido por último produz
            # resposta com cara de inventário. Esta linha devolve a voz.
            partes.append("")
            partes.append("Agora responda como Zeus fala: curto, vivo, direto, "
                          "sem repetir o que ele disse e sem listar o que você é.")
        return {"texto": "\n".join(partes), "escolha": escolha}
