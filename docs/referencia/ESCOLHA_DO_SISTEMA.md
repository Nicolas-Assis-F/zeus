# Escolha do sistema operacional do Zeus

Análise de 18 de setembro de 2026. Estado: recomendação apresentada; instalação de Linux ainda não escolhida pelo usuário nem executada. Preparação de Windows 10 em reavaliação a pedido de Nicolas.

## Recomendação

Para o PC dedicado ao Zeus, começar com Ubuntu Desktop 24.04 LTS x64 instalado diretamente no SSD do sistema. Usar instalação mínima, com interface gráfica para facilitar configuração, manutenção e testes de áudio. Essa escolha é um julgamento de engenharia para este projeto, não um resultado de comparação de desempenho medida.

O Ubuntu 26.04 LTS também existe e possui suporte mais longo. A proposta inicial de 24.04 privilegia uma base estabelecida para o hardware antigo; a combinação de kernel, driver NVIDIA e mecanismo de IA precisa ser verificada antes de fixar versões. O Ubuntu 24.04 LTS tem manutenção de segurança padrão até maio de 2029 segundo as notas de lançamento.

## Por que Linux neste projeto

O PC terá como função principal executar o núcleo do Zeus, memória, voz, pesquisa e serviços de integração, com funcionamento contínuo. Linux permite executar esses componentes e Docker Engine diretamente, sem adicionar WSL para os componentes Linux. Isso reduz camadas a administrar; não garante uma porcentagem de ganho de velocidade.

ESPHome funciona também no Windows. Seu firmware roda nas placas ESP32, independentemente do sistema do computador que o compila. No Linux, o painel e a compilação podem usar a imagem oficial do ESPHome, com acesso explícito a USB e à rede local. Sensores e atuadores podem continuar suas automações locais quando configurados para isso; decisões dependentes do Zeus ainda precisam do servidor.

## Comparação para esta máquina

| Opção | Vantagem para o projeto | Custo ou limite | Avaliação |
| --- | --- | --- | --- |
| Ubuntu Desktop LTS | Serviços Linux diretos e interface para configuração | Exige aprendizado inicial e validação de drivers | Recomendação inicial |
| Ubuntu Server LTS | Base enxuta para operação sem monitor | Mais trabalho inicial via terminal e configuração de áudio | Alternativa quando a operação estiver consolidada |
| Windows 10 22H2 com ESU | Familiaridade com o ambiente Windows | Base com suporte regular encerrado e manutenção estendida temporária | Possível, mas não preferido como base definitiva |
| Home Assistant OS diretamente no PC | Administração simplificada da automação doméstica | Ambiente especializado em Home Assistant; menos adequado como estação geral do núcleo Zeus | Usar como componente do ecossistema |

## Arquitetura proposta

Ubuntu hospeda o núcleo do Zeus e os serviços de IA e voz. Na etapa de integração doméstica, considerar Home Assistant OS em uma máquina virtual KVM, com sua gestão de apps e backups, para reduzir o trabalho manual no lado da casa. A GPU permanece no Ubuntu para o Zeus, sem necessidade inicial de passá-la para essa máquina virtual. Validar virtualização no firmware antes de criar a VM.

ESPHome pode ser administrado como app do Home Assistant OS. Alternativamente, Home Assistant Container e ESPHome separado em Docker são opções documentadas; nesse caso, a gestão dos serviços e atualizações fica sob nossa responsabilidade e Home Assistant Container não oferece o gerenciador de apps do HAOS. Não instalar ambas as arquiteturas ao mesmo tempo.

A etapa inicial continua sendo persona, memória e iniciativa. Não é necessário instalar toda a automação doméstica antes dessa primeira demonstração.

## Limite real do hardware

A GTX 1050 Ti tem 4 GB de memória de vídeo. A troca do sistema não aumenta essa capacidade. Modelos locais, tamanho do contexto, voz e visão simultâneos precisam caber no orçamento de memória ou usar divisão de carga. A documentação do Ollama lista a GTX 1050 Ti entre as placas suportadas, mas a aceleração e a latência devem ser medidas no equipamento.

A NVIDIA informa que a série Linux 580 é a última linha com suporte às arquiteturas Maxwell, Pascal e Volta. A GTX 1050 Ti pertence à geração Pascal. Selecionar o driver compatível oferecido pela distribuição e testar o mecanismo de IA; não instalar uma linha mais nova indiscriminadamente.

## Discos e próximo passo

Proposta: Ubuntu e ferramentas essenciais no SSD de 128 GB; dados volumosos, modelos e armazenamento dos serviços no SSD de 256 GB. Depois da instalação Linux, as unidades serão identificadas por dispositivo, UUID e ponto de montagem, não pela letra D: do Windows.

Se Nicolas escolher Ubuntu, preparar um pendrive e iniciar primeiro a sessão de experimentação, sem instalar, para testar vídeo básico, rede e USB. Confirmar os discos no instalador antes de executar a limpeza já autorizada. O driver proprietário e a aceleração de IA serão verificados após a instalação. A autorização para apagar os SSDs permanece registrada, mas não transforma esta recomendação em uma instalação já feita.

## Fontes oficiais consultadas

- [Ubuntu 24.04 LTS e suporte](https://documentation.ubuntu.com/release-notes/24.04/)
- [Ciclo de versões do Ubuntu](https://ubuntu.com/about/release-cycle)
- [Instalar ESPHome em diferentes sistemas](https://esphome.io/install/)
- [ESPHome em Docker e acesso à rede e USB](https://esphome.io/install/docker/)
- [Home Assistant em Linux e diferenças entre HAOS e Container](https://www.home-assistant.io/installation/linux)
- [Suporte NVIDIA para GPUs antigas](https://nvidia.custhelp.com/app/answers/detail/a_id/3142/kw/legacy%20drivers)
- [Hardware suportado pelo Ollama](https://github.com/ollama/ollama/blob/main/docs/gpu.mdx)
- [Windows 10 e ESU](https://www.microsoft.com/en-us/windows/extended-security-updates)
