# Trabalho conjunto de Codex e Claude

O plano mestre define o produto; as issues definem o próximo trabalho concreto.
Os rótulos de executor indicam divisão proposta, não agentes já executando nem
contas GitHub atribuídas automaticamente.

## Antes de editar

1. Ler a issue, seus critérios, dependências e áreas de código.
2. Registrar na issue quem está executando e o nome da branch. Uma issue em
   execução tem um responsável. O outro agente revisa ou escolhe trabalho independente.
3. Conferir `git status`, `git log` e o remoto. Criar branch e worktree próprios
   a partir de uma versão conhecida. Nunca fazer checkout, stash, reset ou pull
   no diretório em que o outro está trabalhando.
4. Mudanças locais preexistentes pertencem a quem as criou. Se forem necessárias
   como base, capturar snapshot separado, identificado, sem atribuir sua autoria ao novo trabalho.

## Áreas compartilhadas

`nucleo.py`, `store.py`, `__main__.py`, `config.py` e a interface têm risco maior
de conflito. A issue deve anunciar quais serão editados. Dois agentes podem
trabalhar simultaneamente em módulos diferentes; alterações de contrato devem
ser combinadas antes, com testes no PR. Migração de banco pertence a uma única
branch de cada vez.

## Entregar uma tarefa

Cada PR descreve comportamento antes/depois, testes, limitações e procedimento
de validação real. Diferenciar teste com dublê de teste no X99. Evitar refatoração
ampla junto de uma feature. Nunca publicar estado pessoal, gravações ou credenciais.

O revisor confere contrato, regressões, recuperação e aderência ao plano. Depois
da integração, registrar o commit e a evidência na issue. Fechar só o escopo
concluído; hardware ainda não testado permanece pendente. Não instalar, montar
SSD nem mudar provedor como efeito lateral de uma tarefa de código.

## Esta entrega

O checkout de desenvolvimento encontrado foi `Documents/zeus`, com 16 arquivos
alterados ou novos. Uma cópia isolada preservou essas mudanças num primeiro
commit de snapshot; as melhorias foram acrescentadas em commits separados.
O checkout compartilhado não recebeu checkout, reset, stash nem sobrescrita.

Após publicação, ele continuará com a edição original. Não fazer `pull` sobre
essa árvore suja. Comparar o snapshot e as mudanças posteriores em uma worktree
limpa; o responsável pelo checkout decide como consolidar seus arquivos.
