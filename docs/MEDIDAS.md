# Medidas do turno

Antes de otimizar, saber onde o tempo vai. Cada turno do Zeus — HUD, Telegram,
voz ou bancada — gera uma medida com identidade própria (`turno`, `geracao`),
feita com relógio monotônico.

| Campo | O que mede |
| --- | --- |
| `espera_fila_ms` | da chegada na fila até o núcleo começar |
| `contexto_ms` | montar persona, memória, pendências e histórico |
| `rodadas[]` | cada chamada ao modelo: ferramentas ofertadas, duração, primeiro fragmento, chamadas pedidas |
| `rodadas[].servidor[]` | o que o provedor informou: `prompt_eval_count`, `prompt_eval_ms`, `eval_count`, `eval_ms`, `load_ms`, `total_ms` |
| `ferramentas[]` | nome, duração, resultado (`ok`, `erro`, `recusada`) e classe de efeito |
| `primeiro_fragmento_final_ms` | primeiro fragmento da rodada que virou resposta (não conta rascunho descartado) |
| `texto_final_ms`, `total_ms` | texto pronto e turno concluído |
| `escuta` | carga e transcrição do Whisper, duração do áudio |
| linhas `voz` | tempo de síntese do Piper por turno |

**Ausente é `null`**, e `ausentes` diz o motivo. O OpenRouter, por exemplo,
não informa durações; o Ollama sem fluxo não tem primeiro fragmento.

**Nenhum conteúdo.** Não entram texto de Nicolas, resposta, argumento de
ferramenta nem chave de fato — só contagens, tamanhos, nomes de etapa e de
ferramenta. Há teste que procura um valor privado no arquivo e falha se achar.

As estatísticas do servidor ajudam a comparar versões, mas não substituem a
medida do usuário nem provam, sozinhas, como o cache de prompt se comporta.

## Onde ficam

Sempre em memória (o Diagnóstico da HUD mostra os últimos turnos). Em disco só
com `"telemetria_arquivo": true`, em `~/.local/state/zeus/medidas/AAAA-MM-DD.jsonl`,
permissão 0600, mantidas por `telemetria_dias` (14 por padrão).

```bash
./zeus medidas                     # p50/p95 do que está gravado, com o tamanho da amostra
./zeus medidas --pasta /tmp/bancada-base/medidas
```

## Linha de base no X99, sem tocar a produção

A bancada repete um roteiro sintético (`avaliacao/bancada.json`, sem dado
pessoal) pela mesma rota da HUD, num estado isolado e sem canal. Ela recusa o
estado padrão e qualquer pasta que não esteja vazia.

```bash
cd ~/zeus
git log -1 --format=%h                       # anote o commit
ollama -v                                    # versão do servidor
ollama ps                                    # o modelo está carregado? quanto em CPU/GPU?
./zeus bancada --state-dir /tmp/bancada-$(git log -1 --format=%h) --repeticoes 3
./zeus medidas --pasta /tmp/bancada-$(git log -1 --format=%h)/medidas
```

Cuidados:

- O Zeus em serviço usa o mesmo Ollama. Rodar a bancada com ele ativo mede
  carga concorrente; para carga isolada, pare o serviço antes
  (`systemctl --user stop zeus`) e suba de novo no fim. Isso é decisão de
  quem opera o X99, não efeito colateral do comando.
- A primeira rodada inclui carga do modelo se ele não estava na memória.
  Compare `load_ms` e trate a primeira repetição como fria.
- `--sem-fluxo` mede a rota do Telegram; `--com-pesquisa` permite busca real
  e torna o número dependente da rede.
- p95 de poucas amostras é exploratório. Três repetições de doze turnos dão
  36 medidas; para afirmar uma melhoria pequena, aumente a amostra.

O resultado a registrar na issue é o JSON final de `./zeus medidas` mais a
linha `sessao` (commit, modelo, `contexto_tokens`), sem o estado da bancada.
