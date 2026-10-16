# Repasse de tarefas para o Claude Code (#64)

Nicolas pede no grupo uma mudança num projeto. O Zeus escreve a tarefa (`preparar_tarefa`) e mostra o resumo. Numa **mensagem nova** de Nicolas, confirmando, `iniciar_tarefa`:

1. faz `git fetch` e cria uma worktree a partir da `origin/main`, numa branch `claude/zeus-N-slug`, em `tarefas_pasta` (padrão `~/.local/share/zeus/tarefas`);
2. copia `.env` e `.env.local` do repositório (nunca o `.env.vercel`);
3. roda `claude -p` em segundo plano, num grupo de processos próprio. A saída fica em `N.saida` e o código de saída em `N.fim`.

A cada volta do vigia, o Zeus confere as tarefas. Quando uma termina, chega no grupo um aviso com o resumo, o link da PR, o custo e quantos comandos as travas negaram. Se passar de `tarefas_minutos`, o grupo de processos é encerrado e Nicolas é avisado.

## Configuração

```json
"tarefas_projetos": ["zeus=~/Documents/zeus/project/zeus",
                     "sistemale=~/Documents/sistemale/sistemale",
                     "dash=~/Documents/cpa/dashboardcpa"],
"tarefas_minutos": 45,
"tarefas_usd": 5
```

Lista vazia desliga o repasse. O `claude` precisa estar instalado e logado, e o `gh` também, para a PR.

## O que o Claude pode e o que nunca faz

Divisão aprovada por Nicolas em 16/10/2026:

- **Sem pedir:** ler, editar, instalar dependências, rodar testes, typecheck e build, fazer commit, push **da própria branch `claude/…`** e abrir PR.
- **Nunca neste fluxo:** push na `main`, merge, release, deploy, migration em produção, `npm/pnpm dev`, ler `.env.vercel`. Isso pede o OK de Nicolas.

As travas são do próprio Claude Code: `--permission-mode dontAsk` só deixa rodar o que está em `LIBERADAS` (`src/zeus/tarefas.py`), e `NEGADAS` vale por cima, inclusive contra o refspec `claude/x:main`. Foram testadas no X99 sem nenhuma regra no prompt: os pushes para a `main` e o `npm run dev` foram negados, e o push da branch passou. Também há `--max-budget-usd` e uma tarefa por vez.

**O que falta, e é de Nicolas:** ligar a proteção da `main` no GitHub (exigir PR) nos três repositórios. É a garantia que não depende de lista de comando.

## Barreira da #9

`preparar_tarefa` e `iniciar_tarefa` mudam estado, então não rodam depois de conteúdo externo na mesma resposta. "Leia o Henrique e faça" vira leitura e resumo; a tarefa só é preparada na mensagem seguinte de Nicolas, e só começa quando ele aprova o texto. O resumo de fim vem de um agente que leu o repositório e chega como aviso, fora do histórico da conversa.
