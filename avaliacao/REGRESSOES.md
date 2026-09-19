# Regressões conhecidas e origem da evidência

## Release 0.3.0

Publicada no PR #18. Voz, ouvidos, resposta em fluxo e memória foram validados
com testes e dublês no desenvolvimento. A aceitação no X99 continua em #2;
a publicação não comprova latência nem qualidade de áudio no hardware.

## Main após os PRs #19, #20 e #21

Pesquisa opcional com snippets, avaliador de jornadas e orçamento de contexto
já foram integrados. A jornada de pesquisa usa transporte controlado nos testes;
não significa pesquisa validada na instalação de Nicolas. A leitura integral
da fonte continua em #23.

## Proposta do PR #25 — entregas e percepção

120 testes locais passaram, incluindo migração com falha, concorrência,
reinício e queda depois do envio. HUD conferida em navegador com dados de teste.
A jornada `falha-de-canal` agora avança o relógio por um minuto antes de esperar
nova tentativa: a recusa conhecida tem backoff. Resultado ambíguo nunca autoriza
reenvio automático.

O monitor do catálogo Ollama é uma fonte operacional opcional. O contrato de
eventos não instala câmera ou sensor: a jornada `visitante` continua sem
hardware real. Publicação de presença doméstica permanece em #7 e #12.

**Ainda sem evidência real nesta rodada**

- Tempos e qualidade da conversa/voz no X99; medição comparativa de modelos.
- Telegram com queda de rede, reenvio deliberado e restauração de backup no X99.
- Julgamento de persona em conversa longa. Comparação cega proposta em #24.

**Limites conhecidos**

- Uma requisição lenta ao canal ainda pode atrasar outras saídas do worker;
  geração do modelo não bloqueia a agenda.
- Sem confirmação de leitura humana, ligação ou escalonamento de alerta.
- Sem leitura integral de páginas, visão ou controle do ambiente.
- Não há garantia automática de correção factual ou de profundidade da persona.
