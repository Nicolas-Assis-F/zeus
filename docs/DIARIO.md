# Diário do projeto

## 18 de setembro de 2026

- Nicolas definiu que o desenvolvimento acontece no computador atual e o X99 será dedicado a executar Zeus.
- Foi localizada a ISO Ubuntu 26.04.1 Desktop amd64 em Downloads, com 6.482.409.472 bytes. A soma SHA256 corresponde ao manifesto oficial consultado por HTTPS.
- Identificado pendrive SanDisk Cruzer Blade de aproximadamente 14,3 GiB. Nicolas autorizou apagar o pendrive. O aplicativo Discos foi chamado com a ISO e o dispositivo selecionados; não houve confirmação de gravação concluída.
- Preparada a fundação Python: memória explícita SQLite, consulta, correção, remoção e processo de serviço com encerramento por sinal.
- Documentados instalação, acesso SSH, clone, testes, serviço de usuário e atualização controlada por Git.
- Nenhum modelo de IA, canal de mensagens, câmera ou controle doméstico foi conectado. Persona e iniciativa natural continuam como próxima entrega.
- Repositório remoto e acesso SSH ao X99 ainda não configurados. Não há publicação nem deploy remoto.

## Decisões

| Decisão | Estado | Motivo |
| --- | --- | --- |
| Desenvolver localmente e executar no X99 | Confirmado por Nicolas | Centralizar desenvolvimento e documentação |
| Usar a ISO Ubuntu 26.04.1 Desktop já baixada | Preparação autorizada; hardware a testar | Permite configuração inicial visual e futura operação sem monitor |
| Estado fora do Git | Implementado no código | Atualizar código sem transportar dados pessoais |
| Serviço de usuário systemd | Preparado; não instalado | Iniciar e manter o processo sem sessão gráfica |
| Modelo e canais de contato | Pendentes | Dependem do ambiente real e da primeira integração |

## Resultado dos testes

Três testes automatizados passaram nesta máquina: persistência e correção após reabertura, remoção da memória ativa, entrada literal sem alteração de SQL, ausência de fatos desconhecidos e início/encerramento do processo preservando memória. O arquivo de serviço passou em `systemd-analyze --user verify`. Nenhum serviço foi instalado nesta máquina. Validação local não substitui testes no X99.
