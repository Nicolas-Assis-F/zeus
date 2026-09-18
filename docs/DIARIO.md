# Diário do projeto

## 18 de setembro de 2026

- Nicolas definiu que o desenvolvimento acontece no computador atual e o X99 será dedicado a executar Zeus.
- Foi localizada a ISO Ubuntu 26.04.1 Desktop amd64 em Downloads, com 6.482.409.472 bytes. A soma SHA256 corresponde ao manifesto oficial consultado por HTTPS.
- Identificado pendrive SanDisk Cruzer Blade de aproximadamente 14,3 GiB. Nicolas autorizou apagar o pendrive. O aplicativo Discos foi chamado com a ISO e o dispositivo selecionados; não houve confirmação de gravação concluída.
- Preparada a fundação Python: memória explícita SQLite, consulta, correção, remoção e processo de serviço com encerramento por sinal.
- Documentados instalação, acesso SSH, clone, testes, serviço de usuário e atualização controlada por Git.
- Nenhum modelo de IA, canal de mensagens, câmera ou controle doméstico foi conectado. Persona e iniciativa natural continuam como próxima entrega.
- Inicialmente não havia remoto. Nicolas criou `https://github.com/Nicolas-Assis-F/zeus.git` e forneceu o endereço; o clone local foi conectado como `origin`. O acesso SSH ao X99 e o deploy ainda estão pendentes.
- A tentativa gráfica de gravar o USB encontrou dispositivo ocupado. O diagnóstico identificou Nautilus usando a partição antiga UBUNTU-SERV. O aplicativo foi encerrado normalmente e a desmontagem pelo UDisks concluiu com sucesso. Foi preparada gravação da ISO Desktop com validação de identidade do SanDisk e conferência SHA256 após a escrita; aguarda resultado da execução.

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

## 18 de setembro de 2026 — Entrega 1

- O X99 foi formatado e recebeu Ubuntu 26.04 Desktop. O clone do repositório e o workspace de execução foram criados pelo próprio Nicolas; a máquina só recebe clone e `git pull`.
- Inventário conferido no hardware real, substituindo a suposição do escopo: Xeon E5-2670 v3, 24 threads, 30 GiB de RAM utilizáveis e 7 GiB de swap. O SSD de 111,8 GiB (`sdb`) tem o sistema e a EFI; o de 238,5 GiB (`sda`) está presente com uma partição e ainda não foi montado nem destinado.
- O driver NVIDIA proprietário subiu: versão 580.178.04, CUDA 13.0, GTX 1050 Ti com 4096 MiB. O ambiente gráfico já ocupa por volta de 537 MiB dessa memória, restando aproximadamente 3,5 GiB para inferência.
- Python do sistema é o 3.14.4. Endereço na rede local: 192.168.100.221.
- Implementada a Entrega 1: ciclo com conversa e revisão deliberada, memória com estado epistêmico, episódios, fila de perguntas, agenda, persona em arquivo, catálogo fixo de ferramentas, provedores Ollama e OpenRouter com verificação de modelo e canal Telegram por long polling. Sem dependência externa.
- Vinte e quatro testes automatizados passaram, incluindo a prova de presença de ponta a ponta com modelo e canal falsos. Nenhum teste fala com rede.
- Nenhuma validação com modelo real, latência medida ou conversa longa de persona foi feita até aqui. Isso continua pendente e depende do Ollama instalado no X99.

## Decisões — Entrega 1

| Decisão | Estado | Motivo |
| --- | --- | --- |
| Biblioteca padrão apenas | Implementado | Deploy sem venv e sem quebra de dependência no servidor |
| Persona em arquivo de configuração | Implementado | Ajustar tom sem tocar em código nem refazer deploy |
| Telegram junto da Etapa 1 | Implementado | Fecha o ciclo de iniciativa e adianta a Etapa 2 |
| Marca de envio antes do disparo | Implementado | Reinício não gera aviso duplicado; falha de canal não perde pendência |
| Bloqueio financeiro na escrita do modelo | Implementado | Repete a regra dura nascida do envenenamento de memória anterior |
| Modelo a usar no X99 | Pendente | Depende de medir tokens por segundo com a VRAM realmente livre |
| Destino do SSD de 238,5 GiB | Pendente | Falta decidir entre estado, mídia e futuras gravações |

## 18 de setembro de 2026 — primeira medição com modelo real

- Ollama instalado no X99 e GPU reconhecida na instalação. O `llama3.1:8b-instruct-q4_K_M` foi baixado, 4,9 GB.
- Medição com `--verbose`: leitura do prompt a 32,11 tokens por segundo e geração a 9,81 tokens por segundo, com o modelo já carregado. O 8B não cabe inteiro nos 4 GiB da placa, então parte das camadas roda na CPU.
- `python3 -m zeus check --modelo` respondeu com o modelo servido igual ao pedido: a verificação obrigatória passou contra o Ollama real, não só contra o dublê de teste.
- Geração a 9,8 tokens por segundo atende mensagem escrita. A leitura do prompt é o gargalo perceptível, porque o contexto do Zeus tem persona, fatos e turnos recentes.
- Três correções a partir disso: a persona passou a ser encontrada mesmo quando o comando roda de dentro de `src/`, que antes caía na persona mínima sem avisar; o dado volátil foi para o fim do contexto, para o servidor reaproveitar o cache do prefixo; e o modelo passa a ficar carregado por `keep_alive`, em vez de recarregar 4,9 GB a cada mensagem.
- Nenhuma decisão de modelo definitivo foi tomada. Falta comparar com um modelo de 3 a 4 bilhões que caiba inteiro na placa e avaliar a qualidade da persona nos dois.

## 18 de setembro de 2026 — atrito de configuração

- O token do Telegram foi preenchido em `config/config.example.json`, que está no Git e não é lido pelo programa. O `check` continuou mostrando "ausente" porque o Zeus lê `~/.config/zeus/config.json`. O exemplo passou a dizer isso dentro do próprio arquivo e o `check` passou a informar, em `origem`, qual arquivo foi lido de fato.
- O `chat_id` usado era o número do próprio bot, que aparece antes dos dois pontos no token. O identificador da conversa é outro e vem do `getUpdates`. A documentação passou a avisar.
- Os comandos só funcionavam de dentro de `src/`, porque é lá que o pacote vive. Foi adicionado o atalho `./zeus`, que descobre a raiz do repositório pelo próprio caminho e monta o `PYTHONPATH` sozinho.
- Trinta testes passando.
