# Zeus do zero

Documento vivo de construção do Zeus e Hermes

Início em 18 de setembro de 2026

## Estado real do projeto

Nicolas confirmou que vamos começar do absoluto zero. Nenhum componente do Zeus ou Hermes está confirmado como instalado, configurado ou funcionando. As descrições de equipamentos e serviços nos escopos anteriores são referências de planejamento até serem verificadas.

O plano mestre continua sendo a visão de destino. Este documento acompanha a construção real e distingue intenção, implementação e resultado verificado.

## O que estamos construindo

Zeus será um assistente pessoal persistente, com presença na casa, memória, capacidade de pesquisar, iniciativa e personalidade. A experiência desejada é a de um amigo e escudeiro digital: competente, leal, espirituoso, atento aos combinados e útil no cotidiano.

A inspiração no Jarvis orienta a elegância, a inteligência e o humor. Zeus terá identidade própria e deixará claras suas capacidades reais. A sensação de presença virá da continuidade entre perceber, compreender, perguntar, agir e acompanhar.

O destino inclui voz, percepção da casa, mensagens, ligações, projetos e integração financeira posterior. A escolha da primeira entrega organiza a construção; não reduz essa ambição.

## Primeira entrega

**Demonstrar uma conversa com personalidade, uma memória correta e uma iniciativa no horário combinado.**

Começaremos em um computador, com uma interface de conversa simples. O canal exato e o modelo serão escolhidos após verificar o equipamento e a preferência entre processamento local e serviço externo. Não há fornecedor escolhido ou assinatura necessária definida nesta etapa.

### Roteiro da demonstração

1. Nicolas diz: “Zeus, estou indo para a academia.”
2. Zeus responde com a persona inicial e pergunta se há algum combinado que deva acompanhar. Não presume treino, suplemento ou horário que ainda não conhece.
3. Nicolas pede: “Daqui a dois minutos, me pergunte se peguei a garrafa.” O intervalo curto serve apenas ao teste.
4. Zeus registra o combinado, confirma o horário e mantém uma pergunta pendente.
5. Sem nova mensagem de Nicolas, Zeus inicia o contato no canal disponível.
6. Nicolas responde. Zeus registra o resultado e encerra a pendência, evitando repetir o aviso.
7. Após reiniciar o sistema, Zeus consegue recuperar o combinado e seu estado correto.

Esse roteiro testa iniciativa agendada. A iniciativa provocada por um evento da casa terá uma demonstração própria quando conectarmos o primeiro sensor ou câmera.

### Critérios para considerar a entrega pronta

- A personalidade aparece na conversa sem comprometer a clareza.
- Uma informação desconhecida gera pergunta, não uma memória inventada.
- O combinado pode ser consultado, corrigido e apagado.
- O aviso acontece sem uma nova solicitação no momento do envio.
- Cancelar o combinado impede o aviso; responder encerra a pendência.
- Reiniciar não perde a memória nem provoca envio duplicado. Avisos vencidos seguem uma regra explícita e testada.
- O diário registra o que foi testado e o resultado observado.

Nenhum desses critérios foi testado ainda.

## Persona inicial para validar nas conversas

Zeus fala português brasileiro com naturalidade. É competente, atento e bem-humorado. Pode usar “senhor” com leveza, conforme a preferência de Nicolas, sem transformar toda frase em encenação.

O companheirismo aparece em lembrar de um assunto, acompanhar um objetivo, perguntar com interesse e oferecer ajuda concreta. Zeus respeita momentos de silêncio e não cobra atenção ou exclusividade.

Sua lealdade envolve honestidade: admite dúvidas, verifica informações e pode discordar de uma proposta explicando o motivo. O humor é discreto e diminui em situações urgentes.

### Exemplos de estilo

- Primeiro contato sobre academia: “Bom treino, senhor. Tem algum combinado que você quer que eu acompanhe?”
- Com um lembrete de creatina já cadastrado pelo usuário: “Bom treino, senhor. Já tomou a creatina? Seu treino está aqui se precisar.”
- Informação ausente: “Esse detalhe eu ainda não sei. Você quer me contar para eu lembrar nas próximas vezes?”
- Pesquisa concluída: “Encontrei duas opções. Esta atende melhor ao que você pediu por estes motivos.”
- Falha real: “Não consegui concluir. Sei onde parou e posso tentar novamente.”

Os exemplos de rotina seguem informações e planos fornecidos por Nicolas. Não são prescrições de suplemento ou exercício.

## Autonomia desde a primeira versão

Zeus precisa conseguir iniciar uma interação, manter uma pendência e acompanhar seu desfecho. O mecanismo deve funcionar com o aplicativo em execução; comportamento com o computador desligado ou suspenso será documentado e testado antes de qualquer promessa de disponibilidade contínua.

Ações reversíveis previamente configuradas podem ser executadas sem perguntar a cada vez. Cada nova integração define o que Zeus pode observar, fazer sozinho, perguntar e verificar depois. Compras, pagamentos, acesso físico e outras ações de impacto exigem regras específicas quando forem implementados.

O ciclo de operação é: receber um evento, consultar contexto, avaliar o que falta, agir ou perguntar, verificar o resultado e atualizar a memória. Cada execução guarda um registro curto do evento e do resultado, sem necessidade de armazenar raciocínio interno do modelo.

## Ordem de construção

| Etapa | Entrega concreta | Evidência necessária |
| --- | --- | --- |
| 0 Base | Inventário confirmado e ambiente de desenvolvimento preparado | Equipamento registrado e procedimento reproduzível |
| 1 Presença inicial | Conversa, persona, memória e iniciativa agendada | Demonstração completa descrita acima |
| 2 Contato à distância | Um canal de mensagens com a mesma memória | Aviso e resposta fora da interface local |
| 3 Voz | Falar, ouvir e interromper com naturalidade | Conversa real no equipamento escolhido |
| 4 Percepção | Um evento real da casa provoca interpretação e contato | Evento observado, aviso correto e resultado registrado |
| 5 Ligações | Chamada em uma situação configurada | Chamada real, identificação e encerramento verificados |
| 6 Expansão | Projetos, rotinas e integrações adicionais | Cada capacidade com teste e documentação próprios |
| Posterior Finanças | Consultas e alertas apoiados em registros reais | Fontes reconciliadas e regras de acesso verificadas |

Voz e percepção podem trocar de ordem conforme o equipamento disponível. Não há prazos estimados até confirmar recursos e disponibilidade para implementação.

Hermes será documentado conforme sua função se tornar concreta. A primeira versão deve evitar serviços separados que apenas aumentem o trabalho; a divisão entre Zeus e Hermes será registrada quando houver necessidade real de execução remota ou integrações.

## Inventário pendente

| Informação | Estado |
| --- | --- |
| Computador escolhido para começar | PC principal de Nicolas com plataforma X99, informado em 18/09/2026 |
| Sistema operacional do computador escolhido | Windows 11 Pro 25H2, compilação 26200.9168, confirmado na foto da tela Sobre; substitui a identificação anterior de Windows 10 |
| SSD do sistema | 128 GB nominais informados; espaço livre e letra da unidade a verificar |
| SSD secundário | Unidade D: de 256 GB nominais informados; espaço livre a verificar |
| Relação com a sessão atual | PC separado, reservado exclusivamente para Zeus; sem acesso remoto configurado nesta sessão |
| Memória e processador | 32 GB RAM, 31,8 GB utilizáveis, e Intel Xeon E5-2670 v3 a 2,30 GHz, confirmados na foto; DDR4 informado por Nicolas |
| Placa de vídeo e memória de vídeo | NVIDIA GeForce GTX 1050 Ti com 4 GB, confirmada na foto |
| Armazenamento agregado | A tela Sobre mostra 171 GB usados de 350 GB; distribuição por unidade a verificar |
| Microfone e saída de áudio | A confirmar antes da etapa de voz |
| Equipamento que poderá permanecer ligado | A confirmar |
| Câmeras e sensores disponíveis | A confirmar antes da percepção real |
| Preferência por execução local ou serviço externo | A decidir após o inventário |
| Orçamento para serviços ou equipamentos | Não informado |

Senhas, tokens, chaves e dados bancários não entram no diário. Quando necessários, a documentação descreve sua configuração sem registrar os valores.

## Como vamos documentar tudo

Este documento é a entrada do projeto. A cada etapa, registraremos a mudança, seu motivo, a configuração necessária, o teste realizado e o próximo passo. Instalações terão instruções para reproduzir e desfazer; decisões relevantes terão alternativas e justificativa.

Quando começarmos a implementação, a documentação acompanhará o código em um repositório versionado. Uma funcionalidade só passa a “verificada” com evidência de execução. Planos, simulações e testes reais serão identificados separadamente.

### Estados de acompanhamento

Proposto → escolhido → implementado → verificado. Bloqueios e falhas recebem descrição e próximo passo, sem serem registrados como conclusão.

### Registro de decisões

| Data | Decisão | Motivo | Estado |
| --- | --- | --- | --- |
| 18/09/2026 | Começar do absoluto zero | Orientação explícita de Nicolas | Confirmado |
| 18/09/2026 | Documentar construção e verificação desde o início | Tornar o projeto compreensível e reproduzível | Confirmado |
| 18/09/2026 | Incluir persona, memória e iniciativa na primeira entrega | Demonstrar a experiência central do Zeus | Proposto para implementação |
| 18/09/2026 | Manter finanças para uma etapa posterior | Orientação anterior de Nicolas | Confirmado |

### Diário da construção

**18/09/2026 — Fundação documental.** Registrados objetivo, persona inicial, primeira demonstração, critérios de conclusão, etapas e inventário pendente. Nenhum software foi instalado ou conectado nesta etapa. Próxima ação: identificar o computador e verificar suas capacidades para definir o ambiente inicial.

**18/09/2026 — Máquina escolhida.** Nicolas escolheu seu PC mais forte, com plataforma X99, processador Xeon, 32 GB DDR4 e GTX 1050 Ti. Essas informações foram fornecidas pelo usuário e ainda não foram verificadas no equipamento. Aguardando sistema operacional e confirmação de que esse PC é a máquina da sessão atual antes de qualquer inspeção local ou instalação.

**18/09/2026 — Local de execução confirmado.** O X99 é outro computador, dedicado ao Zeus, e está com Windows. Comandos executados na sessão atual não verificam nem configuram esse PC. A preparação inicial será guiada no equipamento de destino, até que exista uma forma de acesso explicitamente configurada.

**18/09/2026 — Sistema identificado.** Nicolas confirmou Windows 10. Versão e compilação ainda pendentes para verificar a compatibilidade do procedimento de instalação.

**18/09/2026 — Correção de sistema e preparação dos discos.** Nicolas corrigiu a identificação para Windows 11 Pro 25H2, compilação 26200.9168. Informou um SSD de 128 GB para Windows e outro SSD de 256 GB na unidade D:. Solicitou uma limpeza antes da instalação do Zeus. Nenhuma exclusão, formatação ou reinstalação foi realizada. Aguardando identificar o que precisa ser preservado. Procedimento em [Preparação e limpeza](PREPARACAO_E_LIMPEZA.md).

**18/09/2026 — Autorização e evidência visual.** Nicolas autorizou apagar tudo dos dois SSDs. A foto de Sistema, Sobre confirmou Xeon E5-2670 v3 a 2,30 GHz, 32 GB RAM, GTX 1050 Ti de 4 GB, Windows 11 Pro 25H2 e compilação 26200.9168. A tela exibe 171 GB usados de 350 GB agregados. Identificadores pessoais e de produto não foram transcritos. A limpeza ainda não foi executada; o roteiro foi atualizado para restauração com remoção dos dados das duas unidades.

## Próximo passo

Nicolas baixou Ubuntu 26.04.1 Desktop e definiu desenvolvimento neste computador com execução no X99 via Git e SSH. A ISO foi localizada e sua soma SHA256 confere com o manifesto oficial. O pendrive SanDisk foi identificado e sua exclusão autorizada. A ferramenta Discos foi chamada para preparar a gravação; conclusão pendente. A partir desta etapa, código e documentação operacional estão no [repositório local Zeus](../../README.md). A recomendação anterior de Ubuntu 24.04 e os roteiros Windows ficam como histórico. Nenhuma instalação no X99 foi confirmada.

Como caminho inicial, propõe-se manter o Windows e avaliar Ubuntu por WSL 2 para desenvolver o núcleo do Zeus. Isso evita uma formatação nesta fase. A decisão depende da versão do Windows, virtualização e recursos verificados; ainda não há instalação realizada. A operação contínua, o áudio e a aceleração pela GPU exigirão validações próprias.

A instalação simplificada descrita pela Microsoft exige Windows 10 versão 2004, compilação 19041 ou superior, ou Windows 11. Esse requisito de instalação não substitui a verificação do suporte de segurança da edição instalada.

Referência oficial consultada em 18/09/2026: [Instalar o WSL](https://learn.microsoft.com/en-us/windows/wsl/install).
