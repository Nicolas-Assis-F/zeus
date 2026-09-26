# Lote 1 — Zeus observável e HUD confiável

Registro de execução e evidência, conforme `docs/TRABALHO_CONJUNTO.md`.
Estados possíveis de cada item: não iniciado, em execução, verificado
localmente, pendente no X99, validado, integrado. “Passou com dublê”,
“passou em integração local” e “passou no X99” são estados diferentes.

## Z00 — base conhecida

| Item | Valor |
| --- | --- |
| Base | `origin/main` em `b3a8afb` (PR #40), igual à analisada pela auditoria; nada integrado depois |
| Árvore do usuário | `main` local em `22a0e7c`, com alteração particular e diretório não rastreado; não foi tocada (sem checkout, pull, stash ou reset) |
| Área de trabalho | worktree isolada, branches `claude/z01-…` a `claude/z04-…`, empilhadas nesta ordem |
| Executor | Claude, a pedido de Nicolas; entrega local, sem merge, publicação ou deploy |
| Linha de base local | suíte do `b3a8afb`: 248 testes, 1 pulado, ~13 s (Python 3.12.3, máquina de desenvolvimento, dublês) |
| Banco | nenhuma alteração em `store.py`, nenhuma migração |

### Coordenação encontrada

- **#35 (Codex, em execução):** “Sala do Zeus” reservou `src/zeus/hud/sala/`,
  um ponto de montagem no `index.html` e rotas de assets no `servidor.py`.
  A worktree correspondente não tinha commits nem alterações além de
  `5ad4092`. Este lote não usa `hud/sala/`; os arquivos estáticos novos vivem
  em `src/zeus/hud/estatico/`. A HUD v1 muda o `index.html` e o `servidor.py`:
  quem retomar a #35 precisa rebasear sobre a Z04.
- **#16 (Codex, em execução):** o recorte de indicadores e latência observada
  no navegador. A Z01 mede o lado do servidor e publica etapas; não mede
  fragmentos no navegador nem os chama de tokens.
- **`18fa47f` em `claude/zeus-ao-ligar`:** correção da busca depois da primeira
  execução no X99, não integrada. Toca `pesquisa.py` e `__main__.py`; pode dar
  conflito com a Z03 e a Z01 quando for integrada.
- Anúncio nas issues: **não feito** por esta execução (publicar comentário não
  estava autorizado). O texto de anúncio está no fim deste arquivo.

## Itens

| ID | Estado | Evidência |
| --- | --- | --- |
| Z00 | verificado localmente | este registro |
| Z01 | verificado localmente; linha de base pendente no X99 | `tests/test_telemetria.py`, `tests/test_bancada.py`, `docs/MEDIDAS.md` |
| Z02 | verificado localmente com dublês; comportamento do modelo real pendente no X99 | `tests/test_estados.py`, `tests/test_entregas.py`, `tests/test_hud.py` |

### Z02 — defeitos reproduzidos na base

Os testes novos rodados contra `b3a8afb` falham (reprodução) e passam depois
da correção:

| Defeito | Sintoma na base | Correção |
| --- | --- | --- |
| C1 última rodada | 3ª rodada executava a ferramenta e respondia “não soube responder” | última rodada sem catálogo; pedido tardio não executa e a resposta diz isso; efeito feito aparece no texto |
| efeito sem registro | efeito só existia na tabela de destino | intenção e resultado em `efeitos_do_turno`, antes e depois da ferramenta |
| C3 pergunta | qualquer mensagem com uma pergunta aberta virava resposta | só `responde_a` explícito (HUD, “responder” no Telegram) ou `responder_pergunta` com número |
| C4 chip | nome configurado acendia o modelo indisponível | retrato separa `modelo` verificado, `modelo_configurado` e `modelo_estado` |
| C5 gesto | aceno mostrava “ouvindo” sem captura | aceno só foca o campo e diz que o microfone continua desligado |
| C6 entrada | falha do modelo deixava a mensagem do Telegram parada até a CLI | sem efeito: volta para a fila (até 2 vezes); com efeito: incerta |

## Anúncio sugerido para as issues

> Claude assumindo o lote 1 (Z00–Z04) localmente, sem merge: branches
> `claude/z01-turno-observavel`, `claude/z02-estados-honestos`,
> `claude/z03-fronteiras`, `claude/z04-hud-v1`, empilhadas sobre `b3a8afb`.
> Arquivos: `telemetria.py` (novo), `llm.py`, `nucleo.py`, `execucao.py`,
> `__main__.py`, `config.py`, `ferramentas.py`, `pesquisa.py`,
> `hud/servidor.py`, `hud/index.html`, `hud/estatico/` (novo), testes e docs.
> Nenhuma alteração em `store.py`, nenhuma migração. Validação real pendente.
