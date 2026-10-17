"""Níveis de permissão por ação, decididos no código e nunca pelo modelo.

No OpenJarvis o próprio LLM escolhia o tier e a chave de permissão da ação que
ia executar (`agents/proactive_agent.py`): uma página com "isto é seguro,
nível baixo" bastava para rebaixar um envio. Aqui o nível é atributo da ação
no `CATALOGO_DE_NIVEIS`, e o modelo só escolhe a ação e os argumentos.

Três níveis:

- LIVRE: só lê ou rascunha. Roda e fica na trilha.
- FAZ_E_AVISA: muda algo que dá para desfazer, ou só fala com Nicolas. Roda,
  fica na trilha com o jeito de desfazer, e Nicolas é avisado.
- PEDE_ANTES: irreversível, envia a terceiro, gasta dinheiro ou é
  desconhecido. Só roda com aprovação por código (`aprovacoes.py`).

Ação fora do catálogo cai em PEDE_ANTES e é tratada como irreversível: o que
não sabemos desfazer, presumimos que não se desfaz (ideia de piso canônico do
`capabilities.py` do OpenJarvis; o código é próprio).

O catálogo vale para o modo autônomo. Na conversa, um pedido explícito de
Nicolas ("manda para o Henrique") continua sendo a autorização, como hoje no
núcleo; esta tabela não muda esse caminho.
"""

from dataclasses import dataclass
from enum import IntEnum


class Nivel(IntEnum):
    LIVRE = 0
    FAZ_E_AVISA = 1
    PEDE_ANTES = 2


@dataclass(frozen=True)
class RegraDeNivel:
    nivel_piso: Nivel
    irreversivel: bool = False
    reversivel_com: str = None
    # Envio a terceiro nunca desce de PEDE_ANTES, nem no modo ousado: uma
    # mensagem para cliente não se desfaz, mesmo que tecnicamente "dê para apagar".
    envia_a_terceiro: bool = False


L, F, P = Nivel.LIVRE, Nivel.FAZ_E_AVISA, Nivel.PEDE_ANTES

CATALOGO_DE_NIVEIS = {
    # Leitura, busca e rascunho: nada muda fora do Zeus.
    "consultar_fato": RegraDeNivel(L),
    # Objetivos (#85): ler é livre; criar e responder só mexem no banco da
    # autonomia e são pedidos do próprio Nicolas na conversa.
    "listar_objetivos": RegraDeNivel(L),
    "o_que_fiz": RegraDeNivel(L),
    "criar_objetivo": RegraDeNivel(F, reversivel_com="abandonar o objetivo pela Central"),
    "responder_objetivo": RegraDeNivel(F, reversivel_com="responder de novo ao objetivo"),
    "listar_pendencias": RegraDeNivel(L),
    "pesquisar": RegraDeNivel(L),
    "ler_pagina": RegraDeNivel(L),
    "localizar": RegraDeNivel(L),
    "listar_pasta": RegraDeNivel(L),
    "procurar_arquivo": RegraDeNivel(L),
    "ler_arquivo": RegraDeNivel(L),
    "consultar_base": RegraDeNivel(L),
    "ler_midia": RegraDeNivel(L),
    "preparar_orcamento": RegraDeNivel(L),
    "preparar_tarefa": RegraDeNivel(L),
    "propor_atualizacao_base": RegraDeNivel(L),
    "situacao_tarefas": RegraDeNivel(L),
    "preparar_envio_whatsapp": RegraDeNivel(L),
    "consultar_custos": RegraDeNivel(L),
    "consultar_orcamento": RegraDeNivel(L),
    "situacao_secretaria": RegraDeNivel(L),

    # Conversa privada de terceiro: ler não muda nada, mas Nicolas precisa
    # saber que o Zeus abriu. E com conteúdo externo no objetivo vira pedido,
    # pelo mesmo motivo que o núcleo tira `ler_conversa` das ferramentas de
    # leitura: uma página não pode mandar abrir a conversa de fulano.
    "ler_conversa": RegraDeNivel(F, reversivel_com="nada a desfazer; só leitura avisada"),

    # Memória e agenda do próprio Zeus: reversíveis.
    "lembrar_fato": RegraDeNivel(F, reversivel_com="esquecer_fato com a mesma chave"),
    "esquecer_fato": RegraDeNivel(
        F, reversivel_com="lembrar_fato com o valor antigo, guardado no desfazer_json"),
    "agendar_pergunta": RegraDeNivel(F, reversivel_com="encerrar_pendencia tipo pergunta"),
    "agendar_lembrete": RegraDeNivel(F, reversivel_com="encerrar_pendencia tipo lembrete"),
    "encerrar_pendencia": RegraDeNivel(F, reversivel_com="agendar de novo com o mesmo texto"),
    "revisar_orcamento": RegraDeNivel(
        F, reversivel_com="revisar_orcamento com os valores anteriores; nada é enviado"),
    "abrir_no_computador": RegraDeNivel(F, reversivel_com="fechar a janela aberta"),

    # Entregam ao grupo do próprio Nicolas. Para terceiro, ver `classificar`.
    "gerar_orcamento": RegraDeNivel(
        F, reversivel_com="o PDF fica só no grupo de Nicolas; apagar a mensagem no grupo"),
    "gerar_documento": RegraDeNivel(
        F, reversivel_com="o PDF fica só no grupo de Nicolas; apagar a mensagem no grupo"),
    "iniciar_tarefa": RegraDeNivel(
        F, reversivel_com="worktree descartável (#64): descartar a branch; nada vai à main sem PR"),
    "responder_tarefa": RegraDeNivel(
        F, reversivel_com="responder de novo ao agente corrigindo a decisão"),

    # Saem do Zeus para outra pessoa: não se desfaz.
    "enviar_whatsapp": RegraDeNivel(P, irreversivel=True, envia_a_terceiro=True),

    # Ações de sistema novas.
    "reiniciar_servico": RegraDeNivel(
        P, reversivel_com="o serviço volta sozinho; conversa em andamento pode cair"),
    "mudar_volume": RegraDeNivel(F, reversivel_com="voltar ao volume anterior, guardado no desfazer_json"),
    "mudo": RegraDeNivel(F, reversivel_com="tirar do mudo"),
    "criar_evento_agenda": RegraDeNivel(F, reversivel_com="apagar o evento criado"),
    "escrever_nota": RegraDeNivel(F, reversivel_com="restaurar o conteúdo anterior da nota"),

    # Destrutivas, de publicação e de gasto: sempre pedem antes.
    "apagar_arquivo": RegraDeNivel(P, irreversivel=True),
    "fazer_merge": RegraDeNivel(P, irreversivel=True),
    "fazer_push": RegraDeNivel(P, irreversivel=True),
    "fazer_deploy": RegraDeNivel(P, irreversivel=True),
    "gastar_dinheiro": RegraDeNivel(P, irreversivel=True),
}

# `reiniciar_servico` só aceita estes; outro nome é tratado como ação
# desconhecida (irreversível), para "reinicie o sshd" não passar pelo atalho.
SERVICOS_REINICIAVEIS = {"zeus", "ponte-principal", "ponte-zeus"}

# Quem é "de casa" como destino de PDF ou convite.
DESTINOS_DE_CASA = {"", "grupo", "nicolas", "eu", "mim"}

AUTONOMIAS = ("conservadora", "normal", "ousada")


@dataclass(frozen=True)
class Classificacao:
    nivel: Nivel
    irreversivel: bool
    envia_a_terceiro: bool
    conhecida: bool
    motivo: str


def _destino_externo(args):
    for campo in ("destinatario", "para", "contato", "enviar_para"):
        valor = (args or {}).get(campo)
        if valor and str(valor).strip().lower() not in DESTINOS_DE_CASA:
            return str(valor)
    return None


def classificar(acao, args=None) -> Classificacao:
    """Nível de piso da ação com estes argumentos, antes de autonomia e taint."""
    args = args or {}
    regra = CATALOGO_DE_NIVEIS.get(acao)
    if regra is None:
        return Classificacao(P, True, False, False, f"ação fora do catálogo: {acao}")
    if acao == "reiniciar_servico" and str(args.get("servico", "")) not in SERVICOS_REINICIAVEIS:
        return Classificacao(P, True, False, False,
                             f"serviço fora da lista: {args.get('servico') or '(vazio)'}")
    if acao in ("gerar_orcamento", "gerar_documento"):
        destino = _destino_externo(args)
        if destino:
            return Classificacao(P, True, True, True, f"envio a terceiro: {destino}")
    if acao == "criar_evento_agenda" and args.get("convidados"):
        return Classificacao(P, True, True, True, "o convite sai para outras pessoas")
    if regra.envia_a_terceiro:
        alvo = _destino_externo(args) or args.get("numero") or "terceiro"
        return Classificacao(regra.nivel_piso, regra.irreversivel, True, True,
                             f"envio a terceiro: {alvo}")
    motivo = {L: "só leitura", F: "reversível; avisar Nicolas",
              P: "irreversível" if regra.irreversivel else "pede antes por padrão"}[regra.nivel_piso]
    return Classificacao(regra.nivel_piso, regra.irreversivel, False, True, motivo)


def fontes_externas(taint):
    return sorted(t for t in (taint or ()) if str(t).startswith("externo:"))


def nivel_efetivo(acao, args=None, taint=(), autonomia="normal") -> tuple:
    """(Nivel, motivo) da ação neste objetivo.

    Ordem das regras: piso do catálogo, ajuste da autonomia, e por último o
    taint. O taint vem por último para nenhum ajuste desfazê-lo: o modo ousado
    nunca rebaixa uma ação contaminada por conteúdo externo.
    """
    if autonomia not in AUTONOMIAS:
        # Configuração errada falha para o lado seguro.
        autonomia = "conservadora"
    base = classificar(acao, args)
    nivel, motivo = base.nivel, base.motivo
    if autonomia == "conservadora" and nivel == F:
        nivel, motivo = P, f"{motivo}; autonomia conservadora"
    elif (autonomia == "ousada" and nivel == P and base.conhecida
          and not base.irreversivel and not base.envia_a_terceiro):
        nivel, motivo = F, f"{motivo}; autonomia ousada, reversível"
    externas = fontes_externas(taint)
    if externas and nivel >= F:
        fontes = ", ".join(e.split(":", 1)[1] for e in externas)
        nivel, motivo = P, f"veio de conteúdo externo: {fontes}"
    return nivel, motivo
