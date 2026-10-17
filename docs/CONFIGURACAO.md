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
| `modelo_ferramentas` | No `openrouter`, outro modelo para escolher a ferramenta. Vazio é o próprio `modelo` |
| `base_conhecimento` | Pasta da base de conhecimento, fora de repositório. Padrão `~/.local/share/zeus/conhecimento` |
| `modelo_visao` | Modelo que descreve foto e vídeo recebidos. Vazio é o próprio `modelo` |
| `modelo` | Nome exato do modelo. É verificado antes de cada execução |
| `ollama_url` | Endereço do Ollama, normalmente `http://127.0.0.1:11434` |
| `openrouter_chave` | Chave do OpenRouter, quando o provedor for remoto |
| `telegram_token` | Token do bot criado no BotFather |
| `telegram_chat_id` | Conversa autorizada. Nenhuma outra é aceita |
| `canal` | `whatsapp` troca o Telegram pelo grupo do WhatsApp; vazio mantém o Telegram |
| `whatsapp_*`, `principal_*` | Pontes do WhatsApp e vigia do número principal. Veja [WhatsApp](WHATSAPP.md) |
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

## Tudo no OpenRouter, modelo por papel

Com `provedor: "openrouter"`, o mesmo modelo escolhe a ferramenta e escreve a
resposta, numa chamada só:

```json
"provedor": "openrouter",
"modelo": "anthropic/claude-sonnet-5.5",
"openrouter_chave": "..."
```

`modelo_ferramentas` diferente de `modelo` reparte o trabalho como no híbrido,
com os dois lados remotos. Isso custa uma chamada a mais nas respostas sem
ferramenta.

Cada chamada paga sai no log como `uso_modelo`, com tokens de entrada, saída e
custo em dólares. `./zeus uso` mostra o gasto da chave hoje, na semana e no mês,
segundo o próprio OpenRouter.

## Base de conhecimento (#58)

`base_conhecimento` (padrão `~/.local/share/zeus/conhecimento`) é uma pasta de
arquivos `.md` com o que Nicolas e o Claude sabem dos negócios: preços,
importação, clientes, contas a receber, orçamentos. Ela fica **fora de qualquer
repositório**, porque tem nomes e valores, e este repositório é público. Use
`chmod 700` na pasta e `chmod 600` nos arquivos.

- A ferramenta `consultar_base(busca, arquivo?, finalidade?)` devolve as seções
  mais relevantes, com arquivo e caminho de títulos para citar a fonte.
- O `LEIA-ME.md` da pasta entra no contexto do sistema, para o Zeus saber o que
  existe e quando consultar.
- **É a única leitura de arquivo que não sai como externa**, porque a pasta é
  escrita só por Nicolas e pelo Claude. Quem colocar ali conteúdo de terceiro
  (mensagem, página, PDF recebido) quebra a barreira da #9.
- Só lê `.md` diretamente dentro da pasta. Recusa link simbólico, subpasta e `..`.
- Com `finalidade: "orcamento"`, só consulta `catalogo-e-precos.md` e
  `orcamentos.md`, sem as seções INTERNO (título, nota de abertura e filhas) e
  sem as colunas INTERNO das tabelas. Custo interno nunca vai para cliente.
- O Zeus não edita a base. Decisões novas são aplicadas pelo Claude, com data e fonte.

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

## Escada de modelos (#72)

Quando o modelo principal falha, a mesma mensagem é respondida pelo degrau
seguinte, em vez de virar "sem modelo":

```json
"escada_reserva": ["openrouter:anthropic/claude-haiku-5.5",
                   "ollama:llama3.1:8b-instruct-q4_K_M"],
"escada_timeout_s": 60
```

- O degrau 1 é o provedor configurado acima, inclusive híbrido ou
  `modelo_ferramentas`.
- Um degrau que falha fica de lado por um tempo que depende do erro: rede ou
  timeout 60 s, 5xx 2 min, 429 5 min, 402 1 h, 401/403/404 6 h. Se todos
  estiverem de lado, tenta todos assim mesmo.
- A troca sai no log como `modelo_degrau`, com o número do degrau, o modelo e
  o motivo. A volta ao degrau 1 também é registrada.
- As mensagens de ferramenta são convertidas para o formato do degrau que vai
  responder. Na HUD, o rascunho do degrau que caiu é apagado.
- `escada_timeout_s` vale para os degraus remotos. Esperar os 120 s padrão
  antes de descer seria tempo demais.

Medido no X99 em 17/10/2026: com o OpenRouter inalcançável, o Ollama local
respondeu em 68 s (o 8B fez uma pesquisa antes). Com o modelo principal
inválido, o Haiku respondeu em 2,4 s.
