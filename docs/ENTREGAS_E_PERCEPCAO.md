# Entregas recuperáveis e primeira percepção operacional

Entrega proposta nas issues #3, #7 e #16. A agenda roda em um worker separado:
uma geração lenta deixa de atrasar os lembretes. A persona e as ferramentas
continuam no núcleo, com a mesma memória. A fila não depende de o modelo estar
funcionando para entregar um combinado já registrado.

## O que uma confirmação significa

| Estado | Significado | Próximo passo |
| --- | --- | --- |
| pendente | Texto persistido, aguardando canal/prazo | automático |
| em_envio | Tentativa adquirida antes de chamar o canal | aguardar |
| enviada | Canal retornou sucesso e o banco confirmou | nenhum |
| incerta | Pode ter sido entregue, mas não há confirmação confiável | revisão explícita |
| falhou | Três recusas conhecidas do canal | revisão explícita |
| expirada | Passou do prazo permitido | revisar relevância |
| cancelada | Origem encerrada ou descarte explícito | nenhum |

No Telegram, sucesso técnico não significa leitura humana. Na HUD, significa
registro no histórico local, mesmo sem navegador conectado. A transmissão SSE
é uma atualização da tela; reabrir a interface recupera o histórico.

Não há promessa de “exatamente uma vez” através da rede. Se o Telegram aceitar
e o processo cair antes de confirmar no banco, a saída vira incerta no próximo
`run`. Ela não é reenviada automaticamente. Recusa conhecida permite três
tentativas, com pausas de 30 e 60 segundos. Timeout é ambíguo.

Entradas válidas do Telegram são gravadas junto do offset, antes da geração.
Uma atualização ignorada posterior não perde a mensagem válida anterior.
Entrada interrompida durante a geração só volta sozinha para a fila quando dá
para provar que nada com efeito começou. Antes de rodar uma ferramenta que muda
memória, agenda ou algo fora do Zeus, o núcleo grava a intenção num episódio
`efeitos_do_turno` ligado ao turno; depois grava o resultado. Na recuperação, e
também numa falha do modelo no meio da resposta:

- sem intenção de efeito registrada, a entrada volta para `pendente` e é
  respondida de novo (no máximo duas vezes; depois fica incerta);
- com intenção registrada, ou vinda de versão anterior que não deixava esse
  rastro, fica `incerta` e pede revisão — repetir poderia duplicar a ação.

Respostas prontas ficam na fila e não precisam ser geradas novamente após
falha de envio. O texto da resposta pode falhar; o registro do que foi feito,
não: se a redação sair vazia, a resposta descreve o efeito real em vez de dizer
que não soube responder.

## Inspeção e resolução

Os comandos abaixo atuam no estado configurado. Para ensaio, use
`./zeus --state-dir /caminho/de/teste COMANDO`.

```bash
./zeus entregas
./zeus resolver-entrega lembrete:12 confirmar
./zeus resolver-entrega lembrete:12 reenviar
./zeus resolver-entrega lembrete:12 descartar
./zeus resolver-entrada 123 reprocessar
./zeus resolver-entrada 123 descartar
```

Escolha **uma** ação após inspecionar o caso. Confirmar marca o combinado como
concluído; reenviar pode duplicar uma mensagem que já chegou; descartar cancela
a saída e seu combinado pendente. Reprocessar uma entrada pode repetir uma
ferramenta. A HUD sinaliza as pendências, mas a resolução nesta versão é por CLI.

`atraso_maximo_lembrete` é o prazo após o vencimento antes de expirar a saída
(padrão 86400 segundos). Reenvio explícito concede mais um dia. Cancelar um
combinado ainda pendente impede sua entrega; uma tentativa já iniciada pode
chegar ao destino.

## Backup, migração e volta à versão anterior

```bash
./zeus backup /caminho/privado/zeus-antes-da-atualizacao.sqlite3
```

O comando usa a API de backup SQLite, inclui os dados do WAL e verifica a
integridade. Cria arquivo com permissão 0600 e nunca sobrescreve um existente.
O estado contém dados pessoais: mantenha as cópias em armazenamento privado.

Ao abrir um banco de versão anterior, o Store cria automaticamente
`backups/antes-v3-IDENTIFICADOR.sqlite3` dentro do diretório de estado. A migração
3 acrescenta `entradas`, `saidas` e `percepcoes`, preservando fatos e episódios.
Tabelas e versão de cada migração são confirmadas na mesma transação.

Para voltar ao código anterior, pare o serviço, faça uma cópia do estado atual
e restaure o **diretório de estado em uma pasta nova** usando a cópia anterior
como `zeus.sqlite3`. Não copie um banco sobre um serviço ativo nem misture WAL/SHM
antigos com a cópia restaurada. Aponte `--state-dir` para a pasta restaurada e
valide antes de iniciar. Dados posteriores à cópia ficam apenas no estado que
você preservou; não há migração reversa automática.

## Primeira fonte real sem hardware novo

`monitorar_modelo: true` habilita a observação do catálogo do Ollama local.
`intervalo_monitor` (30 s por padrão; mínimo efetivo 5 s) controla as amostras.
Duas observações consecutivas e intervalo mínimo de 60 s entre transições
reduzem alertas por oscilação. Partida saudável é silenciosa. Queda e retorno
criam episódio, evento e aviso com origem, horário, validade e identificador.

Isso verifica que o endpoint apresenta o modelo esperado; não prova que uma
geração funciona nem que o modelo está carregado na GPU. O núcleo tenta se
recuperar de falhas de modelo a cada `intervalo_recuperacao_modelo` (30 s padrão).
Não há detecção de pessoas nesta entrega. Eventos simulados recebem marca
explícita; eventos vencidos não geram avisos.

## Validação e limites

Os testes cobrem reinício, timeout após aceite, queda antes do commit, envio
concorrente, cancelamento, expiração, offset com mensagens ignoradas, migração,
backup, trava de instância e agenda sem chamar o núcleo. O monitor é testado com
sonda controlada; o X99 e a entrega Telegram real continuam pendentes.

Ainda faltam retenção automática de backups, watchdog externo, métricas de
voz/LLM, confirmação humana e escalonamento por ligação. Uma chamada de envio
lenta ainda pode atrasar outras saídas do mesmo worker até seu timeout; geração
LLM não bloqueia esse worker. Não há meta de latência nova comprovada no hardware.

A issue #3 deve passar pelo ensaio de queda no X99 antes de encerrar. #7 recebe
o contrato e a fonte operacional; sensores/agenda conectada continuam próximos
passos. #16 continua aberta para o restante da operação e observabilidade.
