# Regressões conhecidas por versão

Cada release registra aqui o que está quebrado, o que foi contornado e o que
ainda não foi medido em hardware. Uma versão sem esta seção preenchida não está
pronta para ser chamada de release.

## 0.3.0 — em preparação

**Não medido em hardware**

- Todas as jornadas abaixo foram rodadas apenas com dublê. Nenhum número de
  latência real existe ainda; a tabela de metas em `docs/AVALIACAO.md` está sem
  contraparte medida.

**Pulado por dependência**

- `pesquisa`: a ferramenta de busca chega na issue #9. Até lá, a jornada é
  pulada e o Zeus continua respondendo do próprio modelo quando perguntado
  sobre o mundo — com a invenção que isso implica.
- `visitante`: depende do contrato de eventos da issue #7.

**Comportamento conhecido, não corrigido**

- Persona rasa em conversa longa: teto do modelo que cabe em 4 GiB de VRAM.
- Sem leitura do corpo de páginas; sem visão; sem telefonia.
