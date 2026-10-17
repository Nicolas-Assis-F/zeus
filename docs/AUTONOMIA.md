# Autonomia: objetivos, permissões e aprovação por código

Fase 2. Este documento descreve a camada de dados e regras em
`src/zeus/autonomia/`. Ela não chama modelo, rede nem ferramenta. O núcleo
consulta essa camada antes de agir e registra nela depois. Assim as regras de
segurança têm teste sem modelo e não dependem do que o modelo disser.

O estudo que motivou cada regra está em `07-pesquisa-autonomia.md` (OpenJarvis,
commit 091068cb). As partes adaptadas trazem atribuição no cabeçalho do
arquivo.

## Banco próprio

`~/.local/state/zeus/autonomia.db`, um SQLite separado do `zeus.sqlite3`. O
banco da conversa não muda, e o `store.py` também não. Se esta camada der
problema, basta parar o serviço e mover o arquivo: o Zeus volta a ser o que
era, sem migração reversa.

- WAL e `BEGIN IMMEDIATE` em toda escrita: o serviço e um comando de terminal
  podem usar o mesmo arquivo sem se atropelar.
- Uma conexão compartilhada, sob trava reentrante: pode ser chamada de
  qualquer thread.
- Relógio injetável, em epoch float. Nada de comparar data ISO como texto, que
  era o erro do agendador do OpenJarvis com o fuso -03:00.
- O "dia" dos contadores é o dia local de Nicolas (America/Sao_Paulo; sem a
  base de fusos, UTC-3 fixo).

## Objetivos

Um objetivo é um pedido que atravessa turnos: "vê com o Henrique se o frete
chegou e me avisa". Ele guarda a memória de trabalho (`estado_json`), a
próxima ação, o prazo, quando acordar e os contadores do dia.

| Estado | Significado | Sai para |
| --- | --- | --- |
| ativo | O Zeus trabalha nele quando acordar | aguardando_nicolas, bloqueado, abandonado, concluido |
| aguardando_nicolas | Depende de resposta ou aprovação | ativo, bloqueado, abandonado, concluido |
| bloqueado | A guarda ou o próprio Zeus parou; precisa de olhar humano | ativo, aguardando_nicolas, abandonado, concluido |
| concluido | Feito, **com evidência** | final |
| abandonado | Desistência explícita | final |

- `concluir(id, evidencia)` recusa evidência vazia. "Feito" sem prova é o
  jeito mais comum de um agente mentir sem querer.
- Um objetivo é **devido** quando está ativo, sem trava viva, e chegou a hora
  (`acordar_em <= agora`) ou chegou o evento que ele esperava (`acordar_por`,
  por exemplo `aprovacao:12`). Objetivo novo nasce devido.
- A **trava de execução** é um UPDATE condicional (`dono_lock`, `lock_ate`):
  entre threads ou processos, só um dono pega. Uma trava sem dono vivo expira
  em 600 s, a trava zumbi. `liberar` solta a trava, agenda o próximo despertar
  e consome o evento recebido.
- O **taint** é o conjunto de origens externas que tocaram o objetivo, por
  exemplo `externo:whatsapp:Henrique`. Ele é persistido e só cresce: entrar é
  registrado na trilha, e não há caminho para limpar.
- Depois de um reinício, um passo que estava `executando` tem resultado
  incerto. `recuperar_passos_interrompidos` o deixa em `aguardando` com essa
  marca, e ele não é repetido sozinho. O motivo é o mesmo da fila de entregas:
  o efeito pode já ter acontecido.

Ordem de uso de um passo pelo núcleo:

1. `avaliar_passo` (guarda)
2. `nivel_efetivo` (permissão)
3. aprovação, se o nível pedir
4. `adicionar_passo`
5. `iniciar_passo`
6. executar
7. `terminar_passo`
8. `registrar_progresso`

## Guarda contra laço

`avaliar_passo(objetivo, acao, args)` devolve `permitir` ou `bloquear`, sempre
com o motivo. Bloqueia quando:

1. o objetivo não está ativo;
2. o dia já tem `passos_hoje >= teto_passos_dia` (padrão 30);
3. o dia já tem `custo_usd_hoje >= teto_usd_dia` (padrão US$ 1,00);
4. a mesma chamada, com a mesma ação e os mesmos argumentos (`args_hash`), já
   terminou `feito` ou `falhou` duas vezes neste objetivo;
5. as últimas 6 chamadas, contando a candidata, repetem um padrão de período 2
   (A, B, A, B, A, B) ou 3 (A, B, C, A, B, C).

A identidade de uma chamada é o hash da ação mais os argumentos em JSON
canônico. Quatro buscas com termos diferentes não são laço. No OpenJarvis o
ping-pong olhava só o nome da ferramenta, e o bloqueio por chamada idêntica
nunca disparava.

`registrar_progresso(objetivo, False)` três vezes seguidas bloqueia o objetivo.
Mudar para bloqueado depois de um veredito é decisão do chamador. Para isso
existe `bloquear(id, motivo)`, que grava `laco` na trilha. Voltar a ativo zera
o contador de rodadas vazias. Os contadores diários zeram na virada do dia
local.

## Níveis de permissão

O nível é atributo da ação, definido em `CATALOGO_DE_NIVEIS`, no código. O
modelo escolhe a ação e os argumentos, nunca o nível. Ação fora do catálogo é
`PEDE_ANTES` e conta como irreversível.

| Nível | Quando | O que acontece |
| --- | --- | --- |
| LIVRE (0) | Só lê ou rascunha | Roda e fica na trilha |
| FAZ_E_AVISA (1) | Reversível, ou só fala com Nicolas | Roda, fica na trilha com o jeito de desfazer, e Nicolas é avisado |
| PEDE_ANTES (2) | Irreversível, envia a terceiro, gasta, desconhecida | Só com aprovação por código |

| Ações | Piso |
| --- | --- |
| consultar_fato, listar_pendencias, pesquisar, ler_pagina, localizar, listar_pasta, procurar_arquivo, ler_arquivo, consultar_base, ler_midia, preparar_orcamento, preparar_tarefa, propor_atualizacao_base, situacao_tarefas, preparar_envio_whatsapp, consultar_custos, consultar_orcamento, situacao_secretaria | LIVRE |
| lembrar_fato, esquecer_fato (o desfazer guarda o fato), agendar_pergunta, agendar_lembrete, encerrar_pendencia, revisar_orcamento, abrir_no_computador, ler_conversa | FAZ_E_AVISA |
| gerar_orcamento, gerar_documento (para o grupo de Nicolas), iniciar_tarefa (worktree descartável, #64), responder_tarefa | FAZ_E_AVISA |
| mudar_volume, mudo, criar_evento_agenda (sem convidados), escrever_nota | FAZ_E_AVISA |
| reiniciar_servico (só zeus, ponte-principal, ponte-zeus) | PEDE_ANTES, reversível |
| enviar_whatsapp; gerar_orcamento ou gerar_documento com destinatário de fora; convite de agenda | PEDE_ANTES, irreversível, envio a terceiro |
| apagar_arquivo, fazer_merge, fazer_push, fazer_deploy, gastar_dinheiro | PEDE_ANTES, irreversível |

`ler_conversa` é FAZ_E_AVISA de propósito. A leitura não muda nada, mas
Nicolas precisa saber que o Zeus abriu a conversa. Com taint externo, ela
passa a pedir antes, pelo mesmo motivo que o núcleo a tira das ferramentas de
leitura: uma página não pode mandar abrir a conversa de fulano.

`nivel_efetivo(acao, args, taint, autonomia)` aplica, nesta ordem:

1. o piso da ação no catálogo;
2. a **autonomia**:
   - `conservadora` sobe FAZ_E_AVISA para PEDE_ANTES;
   - `ousada` desce PEDE_ANTES para FAZ_E_AVISA, mas só para ação conhecida,
     reversível e que não envia a terceiro. Irreversível nunca desce;
   - um valor inválido conta como `conservadora`;
3. o **taint**: com origem `externo:` presente, todo nível a partir de
   FAZ_E_AVISA vira PEDE_ANTES, com o motivo
   `veio de conteúdo externo: <fonte>`. Esta regra vem por último para nenhum
   ajuste desfazê-la.

O catálogo vale para o modo autônomo. Na conversa, um pedido explícito de
Nicolas ("manda para o Henrique") continua sendo a autorização, como hoje.

## Aprovação com código

Um pedido mostra a ação, o alvo exato (destinatário, arquivo ou serviço) e o
porquê, e recebe um código de 4 dígitos, por exemplo `4821`:

> Posso mandar ao Henrique "Chegou o frete?"? Responda **ok 4821** ou **não 4821**.

| Estado | Significado |
| --- | --- |
| pendente | Esperando Nicolas, por até 24 h (configurável) |
| aprovada | Nicolas disse sim; ainda não executou |
| consumida | Executou; não executa de novo |
| negada | Nicolas disse não |
| expirada | Passou o prazo sem resposta |

- O código é gerado com `secrets` e é único entre os pendentes. Ele também
  não repete um código usado nos últimos 7 dias, para um "ok" antigo repetido
  não aprovar um pedido novo que herdou o mesmo número.
- Só `por='nicolas'` decide. Uma tentativa de outra pessoa é recusada e fica
  como `aviso` na trilha. Garantir que a mensagem veio de Nicolas é trabalho
  do canal.
- Decidir é idempotente: o mesmo "ok" repetido devolve o resultado anterior,
  sem efeito. Decidir o contrário do que já foi decidido é recusado.
- `consumir(id, args_hash)` é um UPDATE condicional
  `WHERE estado='aprovada' AND args_hash=?`. Ele devolve True uma única vez, e
  só para os argumentos exatos que Nicolas aprovou. Se o destinatário mudar
  depois do "ok", o consumo falha. No OpenJarvis, uma ação já executada
  voltava a aprovada e rodava de novo.
- `interpretar_resposta` aceita "ok 4821", "sim 4821", "aprovo 4821",
  "4821 ok", "não 4821", "nega 4821" e "negar 4821". "não aprovo 4821" conta
  como negação. A função não aceita "ok" sem código nem aprovação em lote
  ("sim para todos", "all", "tudo"). O mesmo código com sim e não na mesma
  mensagem não decide nada. Na dúvida, devolve lista vazia, e o Zeus pergunta
  de novo.
- `ao_mudar(callback)` avisa depois de cada mudança gravada. É por ele que a
  sala, o grupo e a HUD retiram o pedido quando Nicolas responde em outro
  canal.
- Uma decisão ou expiração de pedido ligado a objetivo dispara o evento
  `aprovacao:<id>`. O objetivo que esperava esse evento acorda.

## Trilha de ações

Todo pedido, decisão, expiração, execução, falha, desfazer, taint, laço,
mudança de objetivo e aviso entra na tabela `trilha`. É dela que sai o "o que
eu fiz hoje" (`resumo_do_dia`).

A trilha é uma cadeia. Cada linha guarda o hash da anterior e o próprio,
calculado como `HMAC-SHA256(segredo, prev_hash | campos canônicos)`. O segredo
fica fora do banco, em `~/.config/zeus/autonomia.segredo`, criado com
permissão 600 por `segredo_do_arquivo()`. `verificar()` devolve
`(True, None)` ou `(False, id da primeira linha quebrada)`.

Diferenças em relação ao OpenJarvis:

- uma linha com hash vazio é falha, e não linha pulada;
- o hash exige o segredo, então quem edita o SQLite não consegue refazer a
  cadeia.

O `desfeito_em` é a única coluna que muda depois de gravada. Por isso fica
fora do hash, e `marcar_desfeito` acrescenta uma linha `desfazer` encadeada.

A cadeia tem um limite: apagar as últimas linhas não quebra o que sobra.
Quem precisar dessa garantia guarda o último hash em outro lugar.

## Feedback dos avisos

Cada aviso proativo tem uma chave canônica (`hardware:cpu_celsius`,
`objetivo_concluido`, `acompanhamento`). Nicolas responde se o aviso foi
útil, se não precisava ou se era para mais tarde. A resposta vira contador, e
`peso(chave) = 1 + 0,1·útil − 0,15·não precisava`, limitado a [0,2; 1,5].
A política de interrupção (#8) multiplica a nota do aviso por esse peso.

- "Mais tarde" não muda o peso: fala da hora, não do assunto.
- Um aviso nunca some de vez, porque o peso mínimo é 0,2.
- Todo feedback é um evento, e `desfazer_feedback(id)` desconta esse evento
  uma vez.

## O que esta camada ainda não faz

- Não executa nada nem chama o modelo. Isso fica para o laço de objetivos no
  núcleo.
- Não decide quando falar nem por qual canal. Isso fica para a política de
  interrupção e o escalonamento.
- Não lembra regras de permissão ("pode sempre lembrar fatos"). Os contadores
  do `permission_memory` ficam para quando houver uso real.
- Não varre conteúdo externo atrás de injeção. O taint é marcado por quem traz
  o conteúdo.
