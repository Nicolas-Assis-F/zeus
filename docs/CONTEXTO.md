# Orçamento de contexto

## O problema

Todos os fatos confirmados entravam no prompt a cada turno. A leitura do prompt
no X99 foi medida em 32 tokens por segundo, então cada coisa nova que o Zeus
aprendia tornava **toda resposta futura** mais lenta. Ele ficaria mais devagar
quanto mais conhecesse Nicolas, que é o contrário do que um assistente pessoal
deveria fazer.

Com memória sintética, contexto medido em tokens estimados:

| fatos na memória | antes | depois | leitura antes, a 32 tok/s | depois |
| --- | --- | --- | --- | --- |
| 10 | 1082 | 1082 | 33,8 s | 33,8 s |
| 100 | 1959 | 1362 | 61,2 s | 42,6 s |
| 500 | 5959 | 1370 | 186,2 s | 42,8 s |
| 2000 | 21459 | 1365 | 670,6 s | 42,7 s |

Os segundos são o pior caso, com cache frio: o servidor reaproveita o prefixo
entre turnos, então na conversa contínua o custo real é menor. O que a tabela
mostra de verdade é que **o contexto para de crescer**.

## Como a escolha acontece

Três faixas, com teto configurável em `teto_de_contexto` (600 tokens por padrão,
zero desliga tudo e volta ao comportamento antigo):

**Núcleo estável, 60%** — fatos confirmados mais recentes, em ordem
determinística. Só muda quando a memória muda, então continua fazendo parte do
prefixo que o servidor reaproveita.

**Hipóteses, 20%** — reserva própria, e não é generosidade. Hipótese é o que faz
o Zeus perguntar; uma hipótese sobre a rotina que caia do contexto vira uma
pergunta que ele nunca faz, e a rotina nunca se confirma. Na primeira versão
elas competiam por casamento de palavra com a mensagem, e um teste que já
existia reprovou a mudança justamente por isso.

**Trazidos pela mensagem, o que sobrar** — fatos que casam com o que Nicolas
acabou de dizer, mesmo que sejam antigos demais para o núcleo. Um treino
registrado em janeiro volta ao contexto quando ele diz "vou treinar hoje".
Esses ficam no **fim** do contexto, junto do relógio, porque mudam a cada turno
e ali não há cache a perder.

## Nada sai em silêncio

O contexto informa quantos fatos ficaram de fora, e `./zeus persona` lista quais:

```bash
./zeus persona
./zeus persona --mensagem "vou treinar hoje"   # mostra o que a mensagem traria
```

A saída termina com um evento `contexto` trazendo teto, tokens usados, quantos
entraram em cada faixa e as chaves que ficaram de fora.

## Limites conhecidos

A contagem de tokens é uma **estimativa** de quatro caracteres por token, boa o
bastante para orçar e não substitui medir no servidor. Se a diferença entre o
estimado e o real importar, o caminho é pedir a contagem ao próprio Ollama.

A relevância é casamento de termos, sem semântica: "malhar" não encontra
"academia". Busca semântica sobre fontes rastreáveis é o passo seguinte, e a
issue #10 prevê isso.

Com o orçamento ligado, a maior parte do contexto passou a ser a própria
persona, com cerca de mil tokens — metade disso são os exemplos de voz. Reduzir
persona é troca direta contra qualidade de tom e precisa de medição própria,
não de chute.
