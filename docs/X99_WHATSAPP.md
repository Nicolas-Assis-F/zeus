# Preparar o X99 para o Zeus no WhatsApp

Issue: #48. Meta: #46. Este roteiro é para a sessão do Claude Code aberta **no próprio X99**. Os passos marcados **Nicolas** envolvem celular, login ou credencial, e nenhum agente faz esses passos.

O contexto do trabalho (quem é o Nicolas, os projetos e as regras) não está neste repositório, que é público. Ele chega ao X99 em `~/x99-transferencia/CONTEXTO_X99.md`, levado do PC por script. Leia esse arquivo antes deste roteiro.

Ao fim do roteiro, o X99 roda sozinho, sem o PC ligado:

| Serviço | O que é | Porta |
| --- | --- | --- |
| `ponte-principal` | ponte do número principal; o Zeus só lê | 8080 |
| `ponte-zeus` | ponte do número do Zeus, usada no grupo com Nicolas | 8081 |
| `zeus` | o Zeus, com `"canal": "whatsapp"` | HUD 8770 |

Também fica no X99 um Claude Code autenticado, que vai receber as tarefas de código na fase 3.

## 0. Inspeção da máquina (Claude)

Antes de instalar, registrar o estado atual na #48:

```bash
uname -a; lsb_release -a 2>/dev/null; nproc; free -h; df -h ~
python3 --version; go version; uv --version; gcc --version | head -1; git --version
systemctl --user list-units --type=service --no-pager | head -30
loginctl show-user "$USER" -p Linger
ss -ltnp
ls ~/zeus 2>/dev/null && git -C ~/zeus log --oneline -1
```

Se faltar Go, `uv` ou `gcc`, instalar antes do passo 2. O Go pode ficar em `~/.local/opt/go` sem sudo, como já foi feito no PC.

## 1. Histórico do número principal (Nicolas, no PC)

Opcional, mas evita perder o que a ponte do PC já capturou. Fazer uma cópia consistente sem parar a ponte do PC:

```bash
python3 -c "import sqlite3; sqlite3.connect('$HOME/whatsapp-mcp/whatsapp-bridge/store/messages.db').backup(sqlite3.connect('/tmp/historico-whatsapp.db'))"
scp /tmp/historico-whatsapp.db x99:/tmp/historico-whatsapp.db
rm /tmp/historico-whatsapp.db
```

Só o `messages.db` vai para o X99. O `whatsapp.db` é a sessão do aparelho e nunca é copiado. O PC continua conectado como está, e o X99 entra como mais um aparelho, já que o WhatsApp aceita até quatro.

## 2. Pontes (Claude)

```bash
git -C ~/zeus pull --ff-only
~/zeus/deploy/whatsapp/instalar.sh --historico /tmp/historico-whatsapp.db
```

O script:
- clona o `whatsapp-mcp` no commit conferido e aplica `deploy/whatsapp/whatsapp-mcp.patch`;
- compila a ponte, cria `~/pontes/principal` e `~/pontes/zeus` e instala as duas unidades systemd;
- não pareia nenhum número e não liga nenhum serviço.

O patch reúne as correções feitas no PC:
- a API da ponte responde só a `127.0.0.1`;
- o MCP fica sem as ferramentas de envio;
- o código está ajustado à versão atual da biblioteca do WhatsApp;
- as mídias expiradas são baixadas de novo;
- a porta vem de `WHATSAPP_BRIDGE_PORT`, para duas pontes rodarem na mesma máquina.

## 3. Parear os dois números (Nicolas)

O script imprime os dois comandos. Para cada número:

1. Rode o comando no terminal do X99. Vai aparecer um QR code.
2. No celular do número certo, abra WhatsApp → **Aparelhos conectados** → **Conectar um aparelho** e escaneie.
3. Espere aparecer "Connected to WhatsApp" e a sincronização terminar, depois pare com Ctrl+C.

Então:

```bash
systemctl --user enable --now ponte-principal.service ponte-zeus.service
sudo loginctl enable-linger "$USER"
```

## 4. Grupo com o Zeus (Nicolas, depois Claude)

1. **Nicolas:** crie um grupo com você e o número do Zeus, e mande um "oi" nele.
2. **Claude:** liste as conversas e anote os valores:

```bash
cd ~/zeus
ZEUS_WHATSAPP_BANCO=~/pontes/zeus/store/messages.db ./zeus whatsapp
ZEUS_PRINCIPAL_BANCO=~/pontes/principal/store/messages.db ./zeus whatsapp --principal --limite 50
```

Do primeiro comando saem o `jid` do grupo (termina em `@g.us`) e o seu LID, que é o remetente do "oi". Do segundo saem as conversas que o Zeus vai acompanhar. Confirme a lista com Nicolas antes de configurar: Henrique e os clientes da LE.

## 5. Configuração do Zeus (Nicolas para as chaves, Claude para o resto)

Em `~/.config/zeus/config.json`, com `chmod 600`:

```json
{
  "provedor": "openrouter",
  "modelo": "<modelo escolhido>",
  "openrouter_chave": "<Nicolas preenche>",
  "canal": "whatsapp",
  "whatsapp_ponte_url": "http://127.0.0.1:8081",
  "whatsapp_banco": "/home/<usuario>/pontes/zeus/store/messages.db",
  "whatsapp_grupo": "<jid do grupo>",
  "whatsapp_remetentes": ["<LID de Nicolas>"],
  "principal_banco": "/home/<usuario>/pontes/principal/store/messages.db",
  "principal_acompanhados": ["<jid>=Henrique"]
}
```

A chave do OpenRouter é digitada pelo Nicolas, e nunca vai para o `config.py` nem para o Git. Os detalhes de cada campo estão em [WHATSAPP.md](WHATSAPP.md), que chega com o PR da #47.

```bash
./zeus check --modelo --canal
systemctl --user restart zeus.service
```

## 6. Claude Code no X99 (Nicolas para os logins, Claude para o resto)

1. **Nicolas:** instale o Claude Code pelo instalador oficial e faça login com a sua conta.
2. **Nicolas:** rode `gh auth login`.
3. **Claude:** configure a identidade do git e clone os projetos nos mesmos caminhos do PC: `~/Documents/zeus`, `~/Documents/catalogo-le/letorneadora` e `~/Documents/CPA/dashboard`. Esses clones ficam separados do `~/zeus`, que é o clone do serviço.
4. **Nicolas:** coloque no X99 só as credenciais de deploy que as tarefas de código vão usar, como Vercel e o release da dash.
5. **Claude:** registre o MCP de leitura do WhatsApp, apontando para a ponte do número principal:

```bash
claude mcp add --scope user whatsapp -- uv --directory ~/whatsapp-mcp/whatsapp-mcp-server run main.py
```

6. **Claude:** confira que o modo sem terminal funciona:

```bash
cd ~/Documents/zeus && claude -p "responda só: ok"
```

## 7. Evidência para fechar a #48

Colar na issue, sem chave, token, telefone nem LID:

- `systemctl --user status ponte-principal ponte-zeus zeus --no-pager` **depois de reiniciar o X99**
- `ss -ltnp | grep -E ':808[01]'`, mostrando as duas portas presas a `127.0.0.1`
- `./zeus check --canal`, com `canal` dizendo "banco legível" e `vigia_principal` dizendo "configurado"
- um "oi" de Nicolas no grupo respondido pelo Zeus
- uma mensagem real numa conversa acompanhada virando aviso com rascunho no grupo
- a saída de `claude -p "responda só: ok"`
- o PC continuando a ler o WhatsApp nas sessões de lá

## Se algo der errado

- **Ponte cai e pede QR de novo:** o celular ficou muito tempo sem abrir o WhatsApp. Pareie de novo (passo 3). A sessão anterior não precisa ser apagada antes, porque a ponte cria outra.
- **`vigia_indisponivel` no log do Zeus:** a ponte do número principal está parada ou o caminho em `principal_banco` está errado.
- **O Zeus não responde no grupo:** o LID em `whatsapp_remetentes` não confere. Rode `./zeus whatsapp` de novo e veja quem aparece como remetente do grupo.
