# Configuração do Zeus

O Zeus lê **`~/.config/zeus/config.json`**, e só. O arquivo
`config/config.example.json`, dentro do repositório, é um modelo: está no Git,
não é lido por ninguém e nunca deve receber token. Preencher o exemplo e
estranhar que o token continua "ausente" é o erro mais fácil de cometer aqui.

Em caso de dúvida, `./zeus check` mostra em `origem` qual arquivo foi lido.

```bash
mkdir -p ~/.config/zeus
cp ~/zeus/config/config.example.json ~/.config/zeus/config.json
chmod 600 ~/.config/zeus/config.json
```

Qualquer chave também pode vir do ambiente, com prefixo `ZEUS_` e nome em
maiúsculas (`ZEUS_MODELO`, `ZEUS_TELEGRAM_TOKEN`). O ambiente tem prioridade
sobre o arquivo, o que permite testar um modelo sem editar configuração.

## Chaves

| Chave | Para que serve |
| --- | --- |
| `provedor` | `ollama` (local), `openrouter` (remoto) ou `hibrido` |
| `modelo_conversa` | No híbrido, o modelo remoto que conduz a conversa |
| `modelo` | Nome exato do modelo. É verificado antes de cada execução |
| `ollama_url` | Endereço do Ollama, normalmente `http://127.0.0.1:11434` |
| `openrouter_chave` | Chave do OpenRouter, quando o provedor for remoto |
| `telegram_token` | Token do bot criado no BotFather |
| `telegram_chat_id` | Conversa autorizada. Nenhuma outra é aceita |
| `keep_alive` | Quanto tempo o Ollama mantém o modelo carregado |
| `pesquisa_provedor` | `nenhum`, `duckduckgo` ou `searxng` — ver docs/PESQUISA.md |
| `pesquisa_url` | Endereço do SearXNG próprio, quando for o provedor |
| `escuta_modelo` | Tamanho do Whisper para a escuta local |
| `hud_tls` | Sobe a interface em https, necessário para o microfone |
| `persona` | Caminho do `persona.md`, relativo à raiz do repositório ou absoluto |
| `temperatura_conversa` | 0.75 por padrão, para a conversa ter vida |
| `temperatura_decisao` | 0.0, para decisão e roteamento serem estáveis |
| `turnos_de_conversa` | Quantos turnos recentes entram no contexto |
| `teto_de_contexto` | Teto de tokens da memória no prompt; 0 desliga — ver docs/CONTEXTO.md |

## Modelo

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
./zeus check --modelo
```

A verificação falha quando o modelo pedido não está servido. Isso é
intencional: já aconteceu de um servidor entregar variante diferente e quebrar
o uso de ferramentas em silêncio.

Medição no X99 em 18/09/2026, com o 8B em quantização q4_K_M dividido entre GPU
e CPU: 32 tokens por segundo na leitura do prompt e 9,8 na geração. A geração
serve para mensagem escrita. A leitura lenta do prompt é o que dói, e por isso
duas coisas importam: `keep_alive` mantém o modelo carregado entre mensagens, e
o contexto foi montado com a parte estável primeiro, para o servidor reaproveitar
o cache em vez de reprocessar a persona a cada turno.

## Telegram

Crie o bot no BotFather, mande uma mensagem para ele e pegue o `chat_id`. O
`chat_id` **não** é o número que aparece antes dos dois pontos no token: aquele
é o identificador do próprio bot. O seu é outro, e vem do `getUpdates` abaixo,
em `message.chat.id`, depois que você manda uma mensagem para o bot:

```bash
curl -s "https://api.telegram.org/bot<SEU_TOKEN>/getUpdates" | python3 -m json.tool
```

Depois:

```bash
./zeus check --canal
```

Só a conversa configurada é aceita. Mensagem de terceiro é descartada e o
offset avança, então a fila não trava. O offset fica no banco: depois de
reiniciar, o Zeus não responde duas vezes a mensagem antiga.

Sem token configurado, o Zeus roda normalmente: a agenda continua e o contato
fica indisponível até o canal existir.

## Se o token aparecer onde não devia

Token exposto em arquivo versionado, em captura de tela ou em conversa deixa de
ser secreto. No BotFather, `/revoke` invalida o antigo e entrega um novo na
hora. Trocar o valor em `~/.config/zeus/config.json` basta; nada mais no
projeto guarda essa informação.

## Híbrido seletivo

`provedor: "hibrido"` divide o trabalho como o plano mestre propõe: o modelo
local decide e usa ferramenta a temperatura zero, o remoto conduz a conversa.

```json
"provedor": "hibrido",
"modelo": "llama3.1:8b-instruct-q4_K_M",
"modelo_conversa": "nousresearch/hermes-3-llama-3.1-70b",
"openrouter_chave": "..."
```

Memória, agenda e decisão continuam em casa. O que sai é o texto da conversa, e
só porque essa escolha foi feita de propósito. Nenhum áudio e nenhuma imagem
são enviados por consequência disso.

## Escolher modelo com número, não com impressão

```bash
./zeus medir --modelos llama3.1:8b-instruct-q4_K_M,qwen2.5:7b-instruct --repeticoes 3
```

Para cada modelo ele mede três coisas: quanto tempo até a primeira palavra,
quantos tokens por segundo depois dela, e quantas vezes ele acerta a chamada de
ferramenta quando a frase pede uma. Um modelo veloz que erra a chamada não
serve; um certeiro que demora meio minuto também não.

## Contexto transmitido no híbrido

Ao escolher o híbrido, o provedor remoto recebe as mensagens fornecidas ao modelo:
persona, exemplos, histórico recente, fatos e pendências inseridos no contexto,
e resultados de ferramentas usados na resposta. O banco fica local, mas trechos
dele podem sair no prompt. Não interpretar “texto da conversa” como somente a
última frase digitada. O híbrido não foi ativado por esta revisão.

O modo local continua padrão. A tarefa de roteamento do plano mestre deve
acrescentar seleção e redução explícita desse contexto, com uma avaliação
comparando qualidade, custo e latência reais.
