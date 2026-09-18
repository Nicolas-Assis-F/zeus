# Instalação do PC dedicado ao Zeus

## Equipamento e mídia

X99 com Xeon E5-2670 v3, 32 GB RAM e GTX 1050 Ti de 4 GB. SSD do sistema informado como 128 GB e SSD secundário de 256 GB. Identificar modelo e capacidade no instalador antes de escolher o destino; a letra D: não será mantida como identificador no Linux.

Mídia escolhida por Nicolas: Ubuntu 26.04.1 Desktop amd64. Seu SHA256 foi comparado com o manifesto obtido por HTTPS do servidor oficial e coincidiu em 18/09/2026:

```text
601e30fbf5d97759367c632e2c33630665039b7e2158fd068403da3ccf1bda1f
```

Não foi realizada verificação separada da assinatura GPG do manifesto. O pendrive observado é um SanDisk Cruzer Blade, capacidade nominal 16 GB, exibida como 14,3 GiB. Gravação não confirmada.

## Gravar o pendrive neste computador Ubuntu

Usar Discos, selecionar o SanDisk, abrir o menu e escolher Restaurar imagem de disco. Indicar a ISO 26.04.1 em Downloads e iniciar a restauração. A ferramenta grava a imagem e suas partições: não é necessário formatar previamente nem apenas copiar a ISO. A autenticação administrativa acontece na janela do sistema, sem compartilhar a senha na conversa. Ao terminar, ejetar o pendrive.

O NVMe SKHynix de aproximadamente 477 GiB pertence ao computador de desenvolvimento e não é alvo de nenhuma operação de formatação.

## Iniciar e instalar no X99

1. Conectar o pendrive ao X99 e, de preferência, conectar internet por cabo.
2. Abrir o menu de boot da placa-mãe e escolher a entrada UEFI do pendrive. A tecla depende do fabricante; consultar a tela inicial ou manual, sem presumir F12 para todo X99.
3. Escolher a sessão de experimentar o Ubuntu e conferir vídeo, teclado, USB e rede. Se o vídeo falhar, tentar a opção de gráficos seguros, se disponível. Não interpretar vídeo básico funcionando como teste de aceleração de IA.
4. Abrir o instalador e usar instalação interativa com seleção padrão de aplicativos, sem pacote estendido desnecessário.
5. Escolher o SSD do sistema pelo modelo e capacidade. A opção de apagar disco se aplica ao disco selecionado, não necessariamente aos dois SSDs. Se não for possível identificar os dois destinos, registrar a tela para conferência antes de excluir partições.
6. Criar um usuário administrativo de uso humano, sugerido `nicolas`, e nome de máquina `zeus`. Escolher senha própria, sem registrá-la no Git.
7. Concluir e retirar o pendrive quando solicitado. Conferir que o Ubuntu inicia pelo SSD.

A limpeza e montagem do segundo SSD serão feitas depois de identificá-lo no Ubuntu instalado. A autorização de Nicolas para apagar os dois SSDs já existe; o que falta é a identificação técnica do destino. Nenhum comando de formatação genérico faz parte deste guia.

## Desktop ou Server

Desktop 26.04.1 serve para desenvolver e executar o núcleo sem monitor. A interface do sistema não é a interface do Zeus. A versão Server dispensa os pacotes gráficos desde o início, mas não é necessária para o primeiro deploy. Depois de testar SSH e inicialização automática, podemos configurar o Desktop para iniciar em modo texto, sem reinstalar o sistema.

A GTX 1050 Ti exige driver compatível com Pascal. A linha Linux NVIDIA 580 é a última compatível com essa geração. Consultar os pacotes realmente disponíveis no Ubuntu instalado e verificar `nvidia-smi` antes de escolher o mecanismo de IA. Não instalar automaticamente a linha mais nova nem assumir que os módulos NVIDIA abertos atendem a Pascal. O teste em sessão live não valida o driver proprietário.

## Preparar acesso remoto após instalar

No X99, abrir um terminal e executar, um comando por vez:

```bash
sudo apt update
sudo apt install openssh-server git python3
sudo systemctl enable --now ssh
hostname -I
```

Anotar o endereço da rede local. No computador de desenvolvimento, conectar com o usuário criado: `ssh nicolas@IP_DO_ZEUS`, substituindo o endereço real. Na primeira conexão, comparar a impressão da chave com a obtida no X99 por `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.

Configurar autenticação por chave depois da primeira conexão e testá-la antes de desativar autenticação por senha. Se houver firewall ativo, liberar SSH para a rede de administração identificada; não presumir uma faixa de rede. Não expor o SSH no roteador para esta etapa local.

Nas configurações de energia, desativar suspensão automática para que o servidor não pare quando ficar ocioso. Reinícios, retorno após falta de energia e rede ainda precisam ser testados no hardware real.

## Fontes

- [Criar mídia USB no Ubuntu](https://ubuntu.com/desktop/docs/en/latest/how-to/create-a-bootable-usb-stick/)
- [Instalar Ubuntu Desktop](https://ubuntu.com/tutorials/install-ubuntu-desktop)
- [Notas do Ubuntu 26.04](https://documentation.ubuntu.com/release-notes/26.04/)
- [Manifesto SHA256 usado](https://releases.ubuntu.com/26.04.1/SHA256SUMS)
- [OpenSSH no Ubuntu](https://ubuntu.com/server/docs/how-to/security/openssh-server/)
- [Drivers NVIDIA para gerações antigas](https://nvidia.custhelp.com/app/answers/detail/a_id/3142/kw/legacy%20drivers)
