"""Persona carregada de arquivo, nunca embutida no código.

O plano mestre trata personalidade como critério de qualidade desde a primeira
entrega. Manter o texto fora do programa permite ajustar tom sem tocar em
lógica, e permite versionar o estilo separadamente do comportamento.
"""

from pathlib import Path

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

    def sistema(self, fatos=None, perguntas=None, agenda=None, agora=None) -> str:
        partes = [self.texto, "", "## Contexto desta conversa", ""]
        confirmados = [f for f in (fatos or []) if f.get("estado") == "confirmado"]
        hipoteses = [f for f in (fatos or []) if f.get("estado") == "hipotese"]
        if confirmados:
            partes.append("Fatos confirmados na memória:")
            for fato in confirmados:
                partes.append(f"- {fato['key']}: {fato['value']}")
        else:
            partes.append("A memória ainda não tem fato confirmado sobre Nicolas.")
        if hipoteses:
            partes.append("Hipóteses ainda não confirmadas (trate como suposição):")
            for fato in hipoteses:
                partes.append(f"- {fato['key']}: {fato['value']}")
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
            "Só existe o que está acima e o que Nicolas disser agora. "
            "Se algo não estiver aqui, você não sabe.",
            "Para lembrar, consultar, esquecer, agendar pergunta ou agendar lembrete, "
            "use as ferramentas disponíveis. Você não tem nenhuma outra capacidade "
            "nesta versão: não vê câmera, não controla dispositivo, não faz ligação.",
        ]
        # O que muda a cada turno fica por último de propósito: o começo do
        # prompt continua idêntico e o servidor reaproveita o cache em vez de
        # reprocessar a persona inteira a cada mensagem.
        if agora is not None:
            partes.append(f"Momento atual: {agora.astimezone().strftime('%d/%m/%Y %H:%M')}.")
        return "\n".join(partes)
