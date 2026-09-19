# Desenvolver aqui e executar no Zeus

## Separação de responsabilidades

O computador de desenvolvimento contém código, documentação e testes. O X99 dedicado executa a versão aprovada e mantém o estado local do Zeus. Git transporta código; não transporta memória, bancos, gravações ou credenciais. SSH permite administrar o X99 a partir do computador de desenvolvimento.

Nicolas criou o remoto `https://github.com/Nicolas-Assis-F/zeus.git`. Usar autenticação própria do Git ou chave SSH, sem colocar tokens no endereço. A visibilidade do repositório não foi alterada por esta sessão. Manter dados pessoais e credenciais fora do código publicado.

## Primeira execução no servidor

Clonar o repositório para `~/zeus` usando o usuário criado na instalação. A configuração do serviço depende desse diretório; adaptar a unidade explicitamente se escolher outro local.

```bash
git clone https://github.com/Nicolas-Assis-F/zeus.git ~/zeus
```

No diretório clonado:

```bash
cd ~/zeus
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m zeus check
```

Esses comandos verificam a fundação; não configuram IA ou integrações. O projeto ainda não tem dependências externas. Quando houver dependências, usar um ambiente virtual com versões registradas e atualizar o procedimento.

## Rodar automaticamente

Após os testes, ainda com o usuário humano que será dono do serviço:

```bash
mkdir -p ~/.config/systemd/user
cp ~/zeus/deploy/zeus.service ~/.config/systemd/user/zeus.service
systemctl --user daemon-reload
systemctl --user enable --now zeus.service
systemctl --user status zeus.service
```

Para manter o serviço de usuário ativo sem uma sessão SSH aberta e iniciá-lo no boot:

```bash
sudo loginctl enable-linger "$USER"
```

O processo executa como usuário comum. Não precisa de login gráfico, navegador aberto ou terminal conectado. Verificar após reiniciar o X99; o arquivo de serviço ter sido copiado não comprova inicialização automática no hardware.

Logs:

```bash
journalctl --user -u zeus.service -n 50 --no-pager
```

## Atualizar sem editar no servidor

Desenvolver, testar e fazer commit na máquina de desenvolvimento. Publicar no remoto configurado. No servidor, deixar a árvore de código sem alterações locais, anotar o commit anterior e baixar a atualização:

```bash
cd ~/zeus
git status --short
git rev-parse HEAD
git pull --ff-only
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m zeus check
```

Se os testes passarem, reiniciar e verificar:

```bash
systemctl --user restart zeus.service
systemctl --user status zeus.service
journalctl --user -u zeus.service -n 20 --no-pager
```

Não automatizar um pull contínuo: cada atualização precisa de uma versão conhecida e verificada. Futuras alterações de banco exigem migração e backup antes da atualização; este procedimento simples cobre a fundação atual.

## Recuperação e dados

O estado fica fora do clone, em `~/.local/state/zeus`. Para um backup consistente simples, parar o serviço antes de copiar o diretório de estado e iniciá-lo em seguida. Guardar uma cópia fora do PC. Restaurar código antigo não desfaz migrações nem recupera dados por si só.

Para desfazer apenas a ativação do serviço:

```bash
systemctl --user disable --now zeus.service
rm ~/.config/systemd/user/zeus.service
systemctl --user daemon-reload
```

Isso preserva código e estado. Não desativar linger automaticamente: outros serviços de usuário podem depender dele.

## Interface futura

Uma interface web poderá ser hospedada no Zeus e aberta no computador de desenvolvimento. O servidor não precisa de ambiente gráfico para servir essa interface. Quando essa funcionalidade for implementada, definir autenticação e acesso antes de disponibilizá-la fora da própria máquina.

## Atualização para a versão 0.3.0

No clone de execução do X99, com árvore limpa, anotar a revisão atual antes:

```bash
git status --short
git rev-parse HEAD
git pull --ff-only origin main
bash deploy/validar.sh
```

A validação roda a suíte e confere o modelo real. Não instala pacotes, modifica
configuração nem altera dados. Para reiniciar um serviço já configurado:

```bash
bash deploy/validar.sh --reiniciar
```

O script recusa reiniciar se `WorkingDirectory` da unidade não for esse clone.
Se usar venv, alinhar o interpretador de `ExecStart` com o utilizado nos testes;
o script usa `.venv/bin/python` quando existe, ou `ZEUS_PYTHON` quando definido.
Se o Zeus roda em terminal, encerrar essa execução e iniciar `./zeus run` no
mesmo ambiente virtual. Não iniciar dois consumidores Telegram em paralelo.

Depois, conferir texto, voz, escuta, um lembrete e um reinício. Registrar os
resultados na issue de validação no X99. A publicação no GitHub não prova deploy
nem validação de hardware. Para retorno à versão anterior, usar a revisão anotada
em uma checkout limpa e reiniciar conscientemente; nunca usar reset na cópia
compartilhada com outro agente. Esta entrega não altera o esquema do banco.
