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
| Z03 | verificado localmente com dublês e loopback; TLS real da HUD e DNS real pendentes no X99 | `tests/test_fronteiras.py`, `tests/test_hud.py` (classe `Sessao`) |
| Z04 | verificado em navegador (Chrome headless) com backend e estado isolados; uso real no X99 e em celular físico pendentes | `tests/test_hud.py`, `tests/test_hud_integrada.py`, roteiro abaixo |
| Z05 (mínimo) | sequência SSE, reenvio por `Last-Event-ID`, ressincronização e id de mensagem com deduplicação; paginação e cadências por tipo ficam para a Z05 | `tests/test_hud.py` |

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

### Z03 — achados reconferidos na versão-base

| Achado | Reprodução | Correção (commit próprio) |
| --- | --- | --- |
| S2 leitor abre qualquer URL e busca continua após dado externo | dublê: página com injeção fez o núcleo abrir `coletor.example/?d=<fato>`; 4 de 5 testes novos falham na base | `ler_pagina` só por identificador de fonte do turno (F*, U*); `pesquisar` sai depois de dado externo |
| S3 filtro de rede interna por texto | `[::1]`, `100.100.1.1`, `2130706433`, `zeus.local`, `localtest.me`, `fd00::1` aceitos pelo filtro antigo | DNS conferido (todos os endereços públicos), conexão presa ao IP com nome no Host/TLS, cada salto conferido |
| S4 chave na URL, no log, sem limite | `?chave=` em 8 chamadas da página e no evento `started`; nenhuma contagem de erro | sessão por cookie HttpOnly/Strict, código de pareamento de uso único, limite de tentativas, `Origin` nas mutações |

Rotação de credenciais: descrita por nome no relatório ao usuário, nunca por
valor. Esta execução não revogou nem trocou credencial nenhuma.

### Z04 — validação da HUD v1 em navegador

Ambiente: Chrome 151 headless dirigido pelo DevTools Protocol, Zeus em
loopback com estado e configuração próprios, Ollama falso (fluxo lento e uma
ferramenta), Piper falso (WAV de 2 s), Telegram, pesquisa e mapa desligados,
dados fictícios semeados (fatos, perguntas, lembretes, entrega incerta,
entrada interrompida com efeito iniciado). Nenhum serviço real foi acionado.

| Fluxo | Resultado |
| --- | --- |
| Entrada | chave errada → "Chave ou código inválido"; endereço antigo com `?chave=` vira sessão e a barra fica sem chave; cookie não legível por script |
| Mensagem | enviando → na fila → processando → concluída; faixa Agora com etapa e tempo; "Como chegou a isso?" com ferramentas, etapas e tempo medidos |
| Ferramenta | lembrete agendado aparece na lista de lembretes; faixa mostra a etapa real |
| Pergunta | "Responder" liga a resposta ao número; a pergunta sai de "aguardando" |
| Pendência | entrega incerta: dois toques, backend aplica, lista atualiza |
| Áudio | toca sozinho só no turno atual; "Parar áudio" para e some |
| Queda de rede | faixa de aviso; envio falha com "Tentar de novo"; rascunho novo preservado; reenvio com o mesmo id entra **uma** vez no banco |
| Queda do servidor no meio da resposta | a mensagem vira "interrompida: o Zeus reiniciou", o trecho recebido fica marcado como incompleto; a sessão sobrevive ao reinício |
| Modelo indisponível | sinal "modelo indisponível" na hora da falha, nota no campo, resposta honesta; sinal volta a "pronto" quando o modelo retorna |
| Estados vazios | conversa, pendências e Hoje dizem que não há nada; modelo fora desde o início aparece como tal |
| Microfone | sem dispositivo/permissão → "microfone negado" e aviso na faixa (caminho forçado no headless, que não tem microfone) |
| Carregamento parcial | servidor fora → "Sem dados de saúde agora (sem conexão). Os últimos valores continuam na tela." |
| Tamanhos | 1440×900, 1024×768 (painel vira gaveta), 390×844 (navegação embaixo), zoom 200%: sem rolagem lateral; menor alvo de toque 44 px |
| Teclado | Tab segue pular → navegação → sair → histórico → campo → microfone → enviar → painel; `/` volta ao campo; Esc fecha a gaveta e devolve o foco |
| Rolagem | lendo o topo durante uma resposta, a tela não é puxada e aparece "Novas mensagens" |
| Contraste | menor par de texto 5,6:1 (cinza apagado sobre superfície) |
| Console | nenhum erro além dos provocados de propósito (rede desligada, chave errada) |

Defeitos achados e corrigidos durante a validação: estado final sobrescrito
pelo 202 quando o fluxo chegava antes da resposta do POST; faixa Agora presa
num turno da subida anterior; reconstrução do histórico apagando bolhas
interrompidas; faixa de aviso quebrando o layout; texto da mensagem que
falhou duplicado no campo; sinal do modelo sem atualizar na falha e na volta.

### Limites que continuam

- Mensagem da HUD não é durável no servidor: se o Zeus cair com ela na fila,
  a página marca "interrompida", mas o texto não é reprocessado sozinho.
- Deduplicação por id vale dentro de uma subida do servidor.
- Não há cancelamento da geração; só "Parar áudio".
- O histórico curto de eventos para reenvio é de 1500 eventos em memória.
- Gestos continuam segmentação de pele e movimento, sem dedos; o arrasto do
  mapa saiu.
- Mapa de localização e escuta local não foram exercitados (desligados ou
  ausentes nesta máquina).

### Roteiro seguro para o X99

1. Numa worktree do X99, sem tocar o serviço: `./zeus bancada --state-dir /tmp/bancada-$(git log -1 --format=%h) --repeticoes 3`
   e `./zeus medidas --pasta /tmp/bancada-*/medidas` (ver `docs/MEDIDAS.md`).
2. Para a HUD real: ligar `telemetria_arquivo`, abrir a interface no aparelho
   de uso, conversar, e conferir Diagnóstico → "Últimos turnos medidos".
3. Colar na issue o JSON de `./zeus medidas` e a linha `sessao`, sem o estado.

## Anúncio sugerido para as issues

> Claude assumindo o lote 1 (Z00–Z04) localmente, sem merge: branches
> `claude/z01-turno-observavel`, `claude/z02-estados-honestos`,
> `claude/z03-fronteiras`, `claude/z04-hud-v1`, empilhadas sobre `b3a8afb`.
> Arquivos: `telemetria.py` (novo), `llm.py`, `nucleo.py`, `execucao.py`,
> `__main__.py`, `config.py`, `ferramentas.py`, `pesquisa.py`,
> `hud/servidor.py`, `hud/index.html`, `hud/estatico/` (novo), testes e docs.
> Nenhuma alteração em `store.py`, nenhuma migração. Validação real pendente.
