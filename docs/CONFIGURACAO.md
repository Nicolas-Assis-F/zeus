# Configuração do Zeus

Nenhum segredo entra no Git. A configuração fica em `~/.config/zeus/config.json`
no computador que executa o Zeus, com permissão restrita ao usuário.

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
| `provedor` | `ollama` (local) ou `openrouter` (remoto, só texto) |
| `modelo` | Nome exato do modelo. É verificado antes de cada execução |
| `ollama_url` | Endereço do Ollama, normalmente `http://127.0.0.1:11434` |
| `openrouter_chave` | Chave do OpenRouter, quando o provedor for remoto |
| `telegram_token` | Token do bot criado no BotFather |
| `telegram_chat_id` | Conversa autorizada. Nenhuma outra é aceita |
| `persona` | Caminho do `persona.md` |
| `temperatura_conversa` | 0.75 por padrão, para a conversa ter vida |
| `temperatura_decisao` | 0.0, para decisão e roteamento serem estáveis |
| `turnos_de_conversa` | Quantos turnos recentes entram no contexto |

## Modelo

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
PYTHONPATH=src python3 -m zeus check --modelo
```

A verificação falha quando o modelo pedido não está servido. Isso é
intencional: já aconteceu de um servidor entregar variante diferente e quebrar
o uso de ferramentas em silêncio.

## Telegram

Crie o bot no BotFather, mande uma mensagem para ele e pegue o `chat_id`:

```bash
curl -s "https://api.telegram.org/bot<SEU_TOKEN>/getUpdates" | python3 -m json.tool
```

Depois:

```bash
PYTHONPATH=src python3 -m zeus check --canal
```

Só a conversa configurada é aceita. Mensagem de terceiro é descartada e o
offset avança, então a fila não trava. O offset fica no banco: depois de
reiniciar, o Zeus não responde duas vezes a mensagem antiga.

Sem token configurado, o Zeus roda normalmente: a agenda continua e o contato
fica indisponível até o canal existir.
