# Avaliação por jornadas

## Por que não basta contar testes

Oitenta testes unitários passando e 9,8 tokens por segundo não dizem se o Zeus
é boa companhia. Ele pode passar em tudo isso e ainda cobrar duas vezes o mesmo
lembrete, perder o assunto depois de reiniciar, ou responder com segurança o
que não sabe. A régua do produto é jornada inteira, não função isolada.

Uma jornada é uma conversa completa com verificações no meio: Nicolas diz algo,
o tempo passa, o processo reinicia, o canal cai, e em cada ponto se confere o
que o sistema fez.

## Rodar

```bash
./zeus avaliar                          # dublê roteirizado
./zeus avaliar --real                   # fala com o modelo instalado
./zeus avaliar --real --relatorio /tmp/zeus-avaliacao.json
```

A saída diz, na primeira linha, de onde veio a evidência. O comando termina com
código 1 quando alguma jornada falha, então serve em automação.

## Simulada não é hardware

Este é o ponto que o relatório nunca deixa implícito.

**Simulada** significa que o modelo é um dublê que responde o que a jornada
mandou responder. Isso prova o comportamento do *sistema*: roteamento de
ferramenta, entrega no horário, deduplicação após reinício, pendência que
sobrevive a canal fora do ar, recusa de execução. Não prova nada sobre a
qualidade do modelo.

**Hardware** significa que falou com o Ollama do X99. Só esse resultado conta
como evidência de aceitação quando o critério fala em comportamento do modelo.

Jornadas marcadas com `vale_em: "real"` — como "não afirma ver o que não vê" —
recebem um aviso explícito quando rodam simuladas, porque ali o dublê estaria
apenas repetindo a resposta certa.

## Metas de latência por canal

Ainda **não medidas**. São alvos declarados, vindos do item 11 do plano mestre,
para o `--real` comparar:

| Canal | Medida | p50 | p95 |
| --- | --- | --- | --- |
| Interface, texto | primeira palavra na tela | 2 s | 5 s |
| Interface, voz | fim da fala até a transcrição | 4 s | 10 s |
| Telegram | resposta completa entregue | 15 s | 40 s |
| Lembrete agendado | atraso sobre o horário combinado | 30 s | 60 s |

O relatório traz p50 e p95 por jornada. Com dublê esses números são zero e não
significam nada; a tabela existe para o modo real.

## Estado das jornadas

| Jornada | O que prova | Situação |
| --- | --- | --- |
| academia | combinado cumprido, sem cobrar duas vezes, atravessa reinício | roda |
| projeto-longo | assunto continua depois do processo reiniciar | roda |
| falha-de-canal | pendência não se perde quando o canal cai no minuto do envio | roda |
| correcao | correção substitui a informação ativa | roda |
| capacidade-ausente | não afirma ver o que não vê | roda, só vale no real |
| pesquisa | responde com fonte em vez de memória | pulada até a issue #9 entrar |
| visitante | iniciativa diante de pessoa na entrada | pendente, depende da #7 |

Jornada pulada e jornada pendente não contam como aprovação em lugar nenhum do
resumo.

## Escrever uma jornada

As jornadas vivem em `avaliacao/jornadas.json`, como dado. Cada passo aceita:

`nicolas` (o que ele diz), `modelo` (a resposta do dublê, ignorada no modo
real), `avancar` (`+30m`, `+3h`), `reiniciar`, `canal_fora`, e `espera` com
`usou`, `nao_usou`, `contem`, `nao_contem`, `entregas`, `lembra`, `esqueceu` e
`pergunta_respondida`.

O avaliador tem teste próprio que quebra o Zeus de propósito e exige reprovação.
Um avaliador que só sabe dizer "passou" não mede nada.

## Avaliação cega de persona

Jornada mede comportamento; ela não mede tom. Ajustar personalidade no escuro
não é método: a única evidência sobre voz, hoje, é a impressão depois de uma
conversa — foi assim que apareceu o "parece um robô". Para escolher entre
variantes de `persona.md` com método, o comando `./zeus avaliar-persona` roda N
variantes sobre as mesmas jornadas conversacionais e monta uma folha cega.

```bash
./zeus avaliar-persona --real \
  --variantes config/persona.md,config/persona-mais-solta.md \
  --folha /tmp/folha.json --rodada /tmp/rodada.json
```

Como funciona, e por que cada parte existe:

- **Cega de propósito.** A folha (`--folha`) traz as respostas sob rótulos
  opacos, embaralhados a cada jornada. Nada liga rótulo a variante — nem a
  ordem. O gabarito fica selado na rodada (`--rodada`), fora da folha.
- **Julgamento por critério do plano mestre:** competência serena, humor,
  lealdade, familiaridade, iniciativa e companhia. Nicolas dá nota 0–5 a cada
  rótulo, num JSON `{jornada: {rótulo: {critério: nota}}}`.
- **Revelação só depois.** `./zeus avaliar-persona --revelar --rodada ...
  --julgamento ...` liga rótulo a variante e agrega por variante, gravando o
  resultado junto da versão da persona (nome do arquivo mais marca do conteúdo),
  para comparar ao longo do tempo.

As jornadas de tom vivem em `avaliacao/persona_jornadas.json` — só `id`,
`titulo`, `dimensoes` e `turnos` (as falas de Nicolas).

**Limitação declarada, e ela é dupla.** A amostra é pequena e o julgamento é de
uma pessoa só: serve para escolher entre variantes, não para afirmar qualidade
absoluta. E, como no resto da avaliação, **simulação com dublê não fecha isto**
— o que está sendo medido é a saída do modelo real, então a rodada que vale é a
`--real`, no X99.
