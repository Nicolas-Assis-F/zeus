# Ações no computador

Nicolas pediu "um trust de acesso ao computador". Confiança aqui não é o
modelo ganhar um terminal: é ele poder escolher entre ações que já existem,
escritas à mão, sobre pastas apontadas pelo nome. O modelo nunca compõe um
comando. Ele diz qual ação quer e com que argumento, e `src/zeus/acoes.py`
decide se aquilo é permitido.

## O catálogo

`listar_pasta`, `procurar_arquivo`, `ler_arquivo` e `abrir_no_computador`.
Quatro. Não existe escrever, apagar, mover, instalar nem executar, e um teste
cobre isso lendo o catálogo inteiro atrás dessas palavras — a lista não cresce
por descuido.

## Como ligar

```json
"acoes_pastas": ["/home/nicolas/Documentos", "/home/nicolas/projetos"],
"acoes_abrir": false
```

Vazio é o padrão, e vazio significa desligado. As pastas são escolha de
Nicolas, não descoberta do Zeus: ele nunca sai procurando o que mais existe na
máquina. `./zeus check` mostra quais pastas estão valendo.

## As três regras

**Só lê.** A única ação com efeito fora da conversa é `abrir`, que entrega o
caminho ao ambiente gráfico, e ela tem interruptor próprio, desligado.

**Nada fora das raízes.** Todo caminho passa por `resolve()` antes de ser
comparado. Isso fecha as duas fugas clássicas de uma vez: `..` e link
simbólico apontando para fora. Sem essa resolução a raiz seria enfeite, e há
teste para as duas.

**Segredo não é arquivo comum.** Chave, certificado, carteira, perfil de
navegador, `.env`, `.ssh`, `.gnupg`, a configuração do próprio Zeus — tudo
recusado mesmo dentro de uma raiz permitida, por nome de pasta, por sufixo e
por padrão no nome. E não aparece na listagem: mostrar `.ssh` já conta que
existe um alvo interessante ali.

## Conteúdo de arquivo é dado de fora

Um README baixado ontem tem tanto poder de tentar mandar quanto uma página da
internet. Por isso `ler_arquivo` marca o resultado como externo, e o núcleo
desliga as ferramentas pelo resto daquela resposta — a mesma barreira da
pesquisa.

Listagem é diferente. Nome de arquivo raramente carrega ordem, e derrubar as
ferramentas a cada `listar_pasta` tornaria inútil o encadeamento natural de
listar e então ler. Então a listagem só vira dado externo quando algum nome
tenta soar como instrução, e aí o aviso diz que aquilo é nome de arquivo.

Nomes também passam por uma limpeza: caractere de controle sai, e marca de
direção invertida também. Ela faz `relatorio_fdp.exe` aparecer como
`relatorio_exe.pdf`, que é engano barato demais para valer a pena permitir.

## Rastro

Toda ação abre, registra e fecha um episódio em `eventos`. Toda vez que o Zeus
olhou alguma coisa fica escrito, com o quê e quando. Confiança que não deixa
rastro não é confiança, é esquecimento.
