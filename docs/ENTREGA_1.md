# Entrega 1 — Presença

Escopo desta entrega, conforme a Etapa 1 do plano mestre v2: Zeus conversa com
persona, guarda memória explícita, decide sozinho que falta um dado, agenda uma
pergunta, entrega no momento certo e incorpora a resposta. O canal de contato
entra junto, o que adianta boa parte da Etapa 2.

## O que existe agora

O ciclo vive em `nucleo.py` e tem dois ritmos. Resposta imediata é a conversa
que chega pelo Telegram ou pelo terminal. Revisão deliberada é o `tick`, que
acorda, olha o que venceu e decide se contata. Não há modelo pensando sem
parar: o agendador é quem retoma cada assunto na hora.

A memória em `store.py` separa fato confirmado de hipótese, guarda episódios
com seus eventos, mantém uma fila de perguntas com motivo e prazo, e uma agenda
de lembretes. O esquema evolui por migração numerada e a fundação anterior
continua legível.

A persona vive em `config/persona.md`, fora do código. Mudar o tom não exige
deploy novo.

O catálogo de ferramentas em `ferramentas.py` é fixo. O modelo propõe; o
programa decide se a chamada existe, valida os argumentos e executa. Nome fora
do catálogo devolve erro e o ciclo segue. Nenhuma ação física, nenhuma tranca,
nenhum dispositivo nesta entrega.

## As regras duras, em código

Verificação de modelo acontece antes da primeira conversa e de novo em cada
resposta: se o servidor devolver outra variante, levanta erro em vez de virar
comportamento estranho.

Valor financeiro não entra na memória narrativa. O bloqueio está em
`guarda.py`, aplicado na escrita feita pelo modelo, que é onde o
envenenamento aconteceu da outra vez.

Aviso duplicado tem freio próprio: cada pendência só é entregue uma vez, com a
marca gravada no banco antes do envio. Reiniciar o processo não repete nada. Se
o canal falhar, a marca é desfeita e a pendência volta a valer na revisão
seguinte, em vez de virar assunto perdido.

## O que não existe, dito em voz alta

Sem visão, sem telefonia, sem controle de ambiente, sem pesquisa externa, sem
memória semântica. O contexto informa isso à persona, para que ela não afirme
ter visto ou feito algo que o sistema não fez.

## Critério de conclusão

O teste `tests/test_presenca.py` reproduz o cenário de aceitação de ponta a
ponta com modelo e canal falsos: Nicolas comenta que vai à academia, Zeus
agenda uma pergunta sobre um lembrete que não está combinado, entrega no
horário, registra a resposta no mesmo episódio, cria o combinado e não repete
nada depois do reinício.

A validação no hardware real é outra coisa e ainda falta: modelo servido de
verdade, latência medida e uma conversa longa com a persona.

## Comandos

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m zeus check --modelo --canal
PYTHONPATH=src python3 -m zeus conversar "amanhã cedo eu saio mais tarde"
PYTHONPATH=src python3 -m zeus agenda
PYTHONPATH=src python3 -m zeus persona
PYTHONPATH=src python3 -m zeus evento entrada "pessoa na entrada" --simulado
PYTHONPATH=src python3 -m zeus run
```
