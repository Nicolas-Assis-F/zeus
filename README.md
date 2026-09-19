# Zeus

Assistente pessoal persistente com persona, memória e iniciativa.

## Estado atual

Entrega 1 — Presença, de 18/09/2026. Zeus conversa com persona carregada de
arquivo, guarda memória explícita separando fato confirmado de hipótese,
registra episódios, agenda perguntas e lembretes por decisão própria e entrega
no Telegram quando o canal está configurado. A resposta volta para o mesmo
episódio e nenhum aviso é enviado duas vezes, inclusive depois de reinício.

Ainda não existe visão, telefonia, controle de ambiente, pesquisa externa nem
memória semântica. O contexto entregue ao modelo diz isso explicitamente, para
que a persona não afirme ter feito o que o sistema não fez.

O desenvolvimento acontece no computador de Nicolas. O X99 é o destino de
execução e recebe atualização por `git pull`.

## Executar localmente

Requer Python 3.10 ou superior. Apenas biblioteca padrão: nenhuma dependência
externa, nem para o Telegram, nem para o modelo.

O atalho `./zeus` funciona de qualquer diretório: ele encontra a raiz do
repositório pelo próprio caminho e monta o `PYTHONPATH` sozinho. Sem ele,
`python3 -m zeus` só funciona de dentro de `src/`.

```bash
./zeus check
./zeus remember tratamento senhor
./zeus recall tratamento
./zeus run

PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Com modelo e canal configurados (veja `docs/CONFIGURACAO.md`):

```bash
./zeus check --modelo --canal
./zeus conversar "vou treinar mais tarde"
./zeus agenda
./zeus medir --modelos llama3.1:8b-instruct-q4_K_M,qwen2.5:7b-instruct
```

Com `chave_hud` definida, `./zeus run` também sobe a interface no navegador e
imprime o endereço no evento `started`. Telegram e interface compartilham a
mesma memória e os mesmos episódios.

`check` diz em `origem` qual arquivo de configuração foi lido de verdade. Se
aparecer "não existe", o Zeus está rodando com os padrões e qualquer edição
feita em outro arquivo não tem efeito.

Ctrl+C encerra o processo. Os dados ficam em `~/.local/state/zeus`, ou sob
`XDG_STATE_HOME` quando configurado. Use `--state-dir CAMINHO` antes do
subcomando para isolar uma execução de teste. Nenhum dado pessoal e nenhum
segredo vão para o Git.

`forget` remove o registro da memória ativa; não é ferramenta de apagamento
forense e não remove cópias de segurança anteriores.

## Estrutura

| Módulo | Responsabilidade |
| --- | --- |
| `nucleo.py` | Ciclo: conversa, revisão deliberada, percepção de evento |
| `store.py` | Memória: fatos, turnos, episódios, perguntas, agenda, envios |
| `persona.py` | Persona de arquivo e montagem do contexto |
| `llm.py` | Provedores Ollama e OpenRouter, com verificação de modelo |
| `ferramentas.py` | Catálogo fixo do que o modelo pode pedir |
| `guarda.py` | Barreiras que não dependem do modelo se comportar |
| `tempo.py` | Interpretação de momentos declarados em português |
| `canais/` | Telegram e canal em memória para teste |
| `hud/` | Interface no navegador, servida pelo próprio processo |
| `voz.py` | Síntese local com Piper, opcional |
| `ouvidos.py` | Escuta local com faster-whisper, opcional |

## Documentação

- [Instalação da máquina e acesso remoto](docs/INSTALACAO.md)
- [Configuração de modelo e canal](docs/CONFIGURACAO.md)
- [Interface e voz](docs/INTERFACE_E_VOZ.md)
- [Entrega 1 — Presença](docs/ENTREGA_1.md)
- [Desenvolvimento aqui e execução no Zeus](docs/DESENVOLVIMENTO_E_DEPLOY.md)
- [Persona e próxima entrega](docs/PERSONA_E_PROXIMA_ENTREGA.md)
- [Diário e decisões](docs/DIARIO.md)
- `docs/referencia/`: plano mestre e histórico anterior, preservados como referência.

Remoto: https://github.com/Nicolas-Assis-F/zeus.git
