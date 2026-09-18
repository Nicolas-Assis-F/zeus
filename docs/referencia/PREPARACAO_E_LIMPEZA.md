# Preparação e limpeza do PC do Zeus

Registro iniciado em 18 de setembro de 2026. Estado atual: Nicolas confirmou pendrive disponível e propôs voltar ao Windows 10. Caminho preparado: mídia oficial de Windows 10 22H2 x64; instalação e limpeza ainda não executadas. O roteiro de restauração do Windows 11 abaixo fica como histórico das tentativas.

## Equipamento informado

PC dedicado, separado da sessão do Codex: plataforma X99 e RAM DDR4 informadas por Nicolas. A foto da tela Sobre confirmou Intel Xeon E5-2670 v3 a 2,30 GHz, 32 GB RAM (31,8 utilizáveis), GTX 1050 Ti de 4 GB e Windows 11 Pro 25H2, compilação 26200.9168. SSD do sistema de 128 GB e SSD secundário D: de 256 GB informados por Nicolas. A tela mostra armazenamento agregado de 350 GB, com 171 GB usados; não permite verificar as partições de cada disco. Identificadores pessoais e de produto foram omitidos.

## Objetivo

Preparar uma base organizada antes de instalar o Zeus. A escolha entre limpeza da instalação atual e reinstalação depende dos dados e programas que precisam ser preservados e do estado do Windows. Uma solicitação de limpeza não equivale a autorização para apagar os dois discos.

## Conferência inicial sem alterações

1. Abrir o Explorador de Arquivos com Windows + E e selecionar Este Computador.
2. Registrar a letra e o espaço livre da unidade do Windows e da unidade D:.
3. Conferir Área de Trabalho, Documentos, Downloads e pastas do D: para identificar arquivos a preservar.
4. Identificar programas e configurações que ainda serão necessários. Dados sincronizados precisam ser considerados antes de excluir arquivos: exclusões em pastas sincronizadas podem se propagar para a nuvem.

Não compartilhar senhas, chaves de recuperação, dados de licença ou documentos pessoais no diário.

## Caminhos possíveis

### Limpeza mantendo o Windows atual

Usar as ferramentas nativas de Configurações, Sistema, Armazenamento para revisar temporários e recomendações de limpeza. Selecionar categorias individualmente. Downloads, Lixeira e instalações anteriores não devem ser tratados como descartáveis sem conferência. Excluir uma instalação anterior remove a possibilidade correspondente de voltar à versão anterior.

Revisar aplicativos instalados e remover apenas programas identificados como desnecessários. Não remover drivers, componentes compartilhados ou pastas de sistema manualmente. Registrar os itens escolhidos e o espaço livre antes e depois.

### Reinstalação do Windows

É uma alternativa quando o objetivo for remover a instalação e as configurações anteriores, após definir o que será preservado. A função Restaurar o PC oferece opções com efeitos diferentes sobre arquivos, aplicativos e configurações. A opção Remover tudo é destrutiva.

Antes de preparar o procedimento executável, confirmar backup quando necessário, ativação, acesso à recuperação de criptografia se habilitada e o disco exato abrangido. A autorização para apagar o SSD do sistema não abrange automaticamente D:. O resumo final exibido pelo Windows deve corresponder aos discos e dados autorizados.

Nicolas autorizou apagar tudo dos dois SSDs. O procedimento recomendado abaixo usa a restauração do Windows e inclui as duas unidades. Não se trata de apagamento forense para descarte; o computador continuará com o próprio usuário.

## Procedimento preparado para executar no PC dedicado

1. Desconectar pendrives, cartões e discos externos para restringir o escopo aos dois SSDs internos. Manter energia e internet estáveis. Se houver BitLocker ativo, ter a chave de recuperação disponível, sem publicá-la na conversa.
2. Abrir Settings > System > Recovery > Reset PC.
3. Escolher Remove everything e Cloud download.
4. Em Change settings, habilitar a opção de excluir arquivos de todas as unidades. Verificar que não ficou selecionada apenas a unidade do Windows.
5. Manter Clean data desativado: a limpeza prolongada voltada a dificultar recuperação de dados não é necessária para reutilização pessoal.
6. Conferir no resumo que a remoção abrange as duas unidades internas e iniciar Reset. Se a opção de todas as unidades não aparecer, registrar a tela e ajustar o procedimento; não presumir que D: será apagado.
7. Aguardar os reinícios automáticos sem desligar à força. Ao concluir, configurar o Windows como computador novo, sem restaurar os aplicativos e ajustes antigos caso essa escolha seja oferecida.

Os nomes podem variar conforme o idioma e a versão do assistente. Nenhum comando destrutivo foi executado pela sessão atual.

## Verificação após a restauração

Confirmar inicialização, ativação do Windows, funcionamento da rede e reconhecimento da GPU. Executar Windows Update e registrar os resultados. Conferir separadamente o conteúdo e o espaço livre das duas unidades: a limpeza do D: só será marcada como concluída após essa verificação. Não remover partições de recuperação ou inicialização para tentar aumentar o espaço.

## Ocorrência durante a preparação

Em 18/09/2026, Nicolas informou que o assistente pede um pendrive e não oferece Cloud download. Ainda não recebemos o texto exato do aviso. Uma hipótese é que o ambiente de recuperação do Windows esteja desativado ou indisponível; a causa não está confirmada.

Próximo diagnóstico no computador de destino: abrir Terminal ou Prompt de Comando como administrador e executar `reagentc /info`. O comando consulta a configuração de recuperação e não apaga dados. Registrar o estado do Windows RE e eventual mensagem de erro antes de decidir entre corrigir a recuperação e preparar uma mídia de instalação. Não repetir a restauração nem apagar partições durante essa verificação.

Referência: [Opções do REAgentC](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/reagentc-command-line-options?view=windows-11).

**Diagnóstico confirmado por foto em 18/09/2026.** `reagentc /info` concluiu com sucesso e exibiu Windows RE status: Disabled, local do Windows RE vazio e versão 0.0.0.0. Isso confirma que a recuperação está desativada, mas não prova isoladamente que o arquivo de imagem esteja ausente.

Próxima tentativa no Prompt de Comando já aberto como administrador: `reagentc /enable`. Essa operação habilita a recuperação, sem restaurar o PC nem apagar arquivos. Se concluir com sucesso, executar `reagentc /info` novamente e verificar Enabled. Se falhar, registrar o erro exato para orientar o próximo passo; não alterar partições. Reativação ainda não confirmada.

**Resultado da tentativa simples, confirmado por nova foto.** `reagentc /enable` informou Operation Successful, mas a consulta subsequente ainda mostrou Disabled, local vazio e versão 0.0.0.0. A recuperação não foi habilitada; a mensagem de sucesso sozinha não comprova mudança de estado.

Próximo teste: `reagentc /enable /auditmode`, seguido de `reagentc /info`. A documentação da Microsoft informa que `/enable` sem `/auditmode` não realiza ações quando o Windows está em modo de auditoria. Esse modo é uma hipótese, não um diagnóstico confirmado. A opção permite a habilitação nessa condição e não executa restauração nem apaga arquivos. Se o estado continuar Disabled, coletar o diagnóstico do REAgentC antes de novas alterações. Não marcar a restauração como disponível até confirmar o estado e o funcionamento.

**Resultado da segunda tentativa, informado por Nicolas.** A opção `/auditmode` também retornou sucesso, mas o estado permaneceu Disabled. A causa permanece indeterminada e não há comprovação de que faltem arquivos. Evitar repetir as duas tentativas sem evidência nova.

Como o objetivo é começar com uma instalação limpa e os dois SSDs já foram autorizados para apagamento, está em avaliação seguir por mídia USB em vez de prolongar o reparo da instalação atual. Verificar disponibilidade de pendrive vazio de pelo menos 8 GB, cuja preparação apaga seu conteúdo. A autorização dos SSDs não abrange automaticamente um pendrive. Antes de apagar o Windows, verificar a compatibilidade do hardware e o funcionamento da mídia escolhida.

## Organização proposta após a limpeza

- SSD de 128 GB: Windows, drivers e ferramentas essenciais, preservando espaço para atualizações.
- SSD D: de 256 GB: arquivos do projeto, modelos e dados volumosos do Zeus, conforme a tecnologia escolhida. O local do ambiente Linux também será definido explicitamente antes da instalação.
- Cópias de segurança: destino externo ao PC a definir. Ter dois SSDs no mesmo computador não substitui uma cópia externa.

Essa organização é uma proposta, não uma migração já executada. Não mover pastas de sistema nem diretórios de aplicativos manualmente para D:.

## Caminho atual com Windows 10

Nicolas confirmou pendrive disponível e solicitou considerar Windows 10 por preocupação com o consumo de recursos do Windows 11. Não houve comparação de desempenho: não há evidência de que a troca isolada vá acelerar o Zeus.

O suporte regular do Windows 10 terminou em 14/10/2025. A página oficial consultada em 18/09/2026 informa que o programa ESU para consumidores oferece atualizações de segurança até 12/10/2027 para dispositivos elegíveis inscritos. Planejar Windows 10 como etapa temporária e verificar inscrição após instalar a versão 22H2 e suas atualizações. Não houve inscrição nem contratação de ESU. Ubuntu LTS diretamente no equipamento permanece alternativa para uma base de longo prazo, sem troca de sistema autorizada para Linux nesta etapa.

### Preparar a mídia

No PC Windows, acessar a página oficial de download, baixar a ferramenta na seção de criação de mídia e executá-la. Escolher criar mídia para outro computador, Windows 10, arquitetura x64 e o idioma desejado. Selecionar unidade flash USB e conferir o pendrive de pelo menos 8 GB pelo nome e capacidade. A gravação apaga o pendrive selecionado. Não selecionar nenhum dos SSDs como destino da ferramenta.

Após concluir, testar a inicialização pelo pendrive. A escolha da tecla de boot depende da placa-mãe, cujo modelo exato ainda não está registrado. Não fornecer números de discos para exclusão antes de observar a tela de partições e identificar os SSDs. A autorização para limpar ambos permanece válida; falta identificar os destinos no instalador.

Antes de excluir a instalação existente, verificar o caminho de ativação/licença do Windows 10 e a disponibilidade do driver de rede da placa-mãe. A presença de Windows 11 Pro não comprova sozinha uma licença válida de Windows 10 Pro. Próxima evidência solicitada: conclusão da criação da mídia ou eventual erro da ferramenta.

Fontes oficiais:

- [Windows 10 22H2 e ferramenta de criação de mídia](https://www.microsoft.com/en-us/software-download/windows10)
- [Requisitos e prazo do ESU para consumidores](https://www.microsoft.com/en-us/windows/extended-security-updates)
- [Ciclo de suporte do Ubuntu](https://ubuntu.com/about/release-cycle)

## Registro antes e depois

| Item | Antes | Depois |
| --- | --- | --- |
| Espaço livre no SSD do sistema | A informar | Não executado |
| Espaço livre no SSD D: | A informar | Não executado |
| Arquivos a preservar | Nicolas informou que pode apagar tudo dos dois SSDs | Não executado |
| Programas removidos | Nenhum confirmado | Não executado |
| Método escolhido | Recomendado: restaurar Windows, remover tudo, download da nuvem e todas as unidades | Não executado |
| Reinício e funcionamento do Windows | A verificar | Não executado |

## Referências

Documentação oficial da Microsoft consultada em 18 de setembro de 2026:

- [Liberar espaço no Windows](https://support.microsoft.com/en-us/windows/experience/storage-filemanagement/free-up-drive-space-in-windows)
- [Gerenciar espaço com o Sensor de Armazenamento](https://support.microsoft.com/en-us/windows/experience/storage-filemanagement/manage-drive-space-with-storage-sense)
- [Restaurar o PC](https://support.microsoft.com/en-us/windows/experience/backup-recovery/reset-your-pc)
- [Procedimento de restauração e escolha de unidades da MSI](https://www.msi.com/support/technical_details/Data_Sanitization_SOP)
