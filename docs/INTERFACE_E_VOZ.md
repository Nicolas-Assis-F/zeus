# Interface e voz

O X99 roda sem monitor, então a interface do Zeus vive no navegador de
qualquer máquina da rede. Ela é servida pelo próprio processo, sem framework e
sem dependência: uma página, um fluxo de eventos e duas rotas.

## Abrir

Defina `chave_hud` em `~/.config/zeus/config.json` com 24 caracteres
aleatórios ou mais (`python3 -c "import secrets;print(secrets.token_urlsafe(24))"`).
`./zeus check` avisa quando ela é curta, sem mostrar o valor.

```bash
./zeus run
# {"event": "started", ..., "hud": "https://IP:8770/"}
```

Abra o endereço e digite a chave. Ela vai uma vez, por POST, e volta como
sessão num cookie `HttpOnly` e `SameSite=Strict`, válida por 30 dias e
guardada no servidor só como hash (`~/.local/state/zeus/hud/sessoes.json`).
“Sair” revoga a sessão daquele aparelho; apagar o arquivo revoga todas.

Sem `chave_hud`, o Zeus imprime no início um **código de pareamento de uso
único**, válido por quinze minutos (evento `hud_pareamento`). Depois de usado,
o log antigo não abre mais nada.

A chave nunca viaja na URL de dado: URL fica em histórico, favorito e log. Um
endereço antigo com `?chave=` ainda entra uma vez — a página troca pela sessão
e tira a chave da barra —, mas o pedido inicial pode ter ficado no histórico do
navegador; prefira digitar. Cinco tentativas erradas por minuto num endereço (ou
trinta no total) bloqueiam novas tentativas por um minuto. Mutação vinda de
outra origem é recusada.

A chave não é decoração. Sem ela, qualquer aparelho na mesma rede conversaria
com a memória do Zeus. A página em si é pública; nenhuma rota de dado responde
sem sessão válida, e a comparação é de tempo constante.

## O que a interface mostra (HUD v1)

A conversa fica no centro; o resto vem quando é preciso. Quatro áreas, com
navegação no topo (e embaixo, no celular):

- **Hoje** — o orbe, o que vem na agenda, o que precisa de você, a conversa
  recente e o estado verificado de cada capacidade. Nada de "próximo passo"
  inventado: só o que está no banco.
- **Conversa** — histórico, resposta em fluxo e um painel recolhível com
  pendências, memória confirmada (só leitura) e mapa.
- **Pendências** — no desktop abre o painel; no celular é uma vista própria.
- **Diagnóstico** — saúde da máquina (CPU, GPU, memória, disco, rede), mapa de
  capacidades, operação do supervisor e os últimos turnos medidos.

Embaixo do topo fica a faixa **Agora**: a etapa real que o núcleo publicou
(reunindo contexto, consultando o modelo, pesquisando, agendando lembrete,
escrevendo, transcrevendo), o tempo que o servidor mediu e o resultado
("Concluída em 3,2 s", "Falhou: modelo indisponível"). Um "pensando" genérico
não conta como resposta.

Três sinais separados no topo: **modelo** (respondeu à verificação ou não),
**microfone** (pronto, gravando, negado, sem dispositivo, exige https) e
**conexão** com o Zeus. O orbe representa só a interação — pronto, capturando,
transcrevendo, preparando, executando, escrevendo, falando, erro ou sem
conexão. Carga da CPU não muda o orbe; ela mora no Diagnóstico.

### Mensagens com identidade e estado

Cada mensagem ganha um id no aparelho. Os estados vêm do servidor: *enviando*
→ *na fila* (é só isso que o HTTP 202 quer dizer) → *processando* → *concluída*,
*falhou* ou *interrompida*. Reenviar usa o mesmo id e o servidor não duplica.
Se o envio não chega (rede caída), a bolha fica com "Tentar de novo", a
mensagem é guardada neste aparelho e sai do campo, para que um segundo Enter
não crie outra. O rascunho que está sendo digitado fica guardado e volta
depois de recarregar a página.

Cada resposta tem "Como chegou a isso?": ferramentas usadas, fontes
encontradas e lidas (com link), etapas do modelo e tempo medido. Nenhuma
explicação inventada do raciocínio.

Perguntas do Zeus têm "Responder": a resposta vai com o número da pergunta.
Mensagem solta não encerra pergunta nenhuma.

A tela não é puxada para baixo enquanto você lê o histórico; aparece "Novas
mensagens" para voltar ao fim. O leitor de tela recebe a resposta por frases,
não por fragmento.

### Pendências e o que dá para fazer com elas

Só as ações que o backend suporta, e em dois toques quando não têm volta:

| Pendência | O que diz | Ações |
| --- | --- | --- |
| Entrega incerta | sem confirmação de que chegou | Chegou · Não chegou — reenviar · Descartar |
| Entrega que falhou ou expirou | motivo | Reenviar · Descartar |
| Mensagem do Telegram interrompida | efeitos que já começaram, ou nenhum | Reprocessar (avisa se pode repetir) · Descartar |
| Pergunta aguardando | o texto | Responder · Cancelar |
| Lembrete | quando | Cancelar |

Resultado incerto pede verificação de quem sabe se chegou; nunca um reenvio
automático às cegas.

### Reconexão

O fluxo SSE leva `id` em cada evento. Na reconexão o navegador manda o último
visto e recebe o que faltou; se o buraco já saiu do histórico curto do
servidor, ou se o Zeus reiniciou, chega "ressincronizar" e a página recarrega o
estado. Mensagens que estavam em andamento num reinício aparecem como
*interrompidas*, com o trecho que chegou marcado como incompleto.

### Controles de áudio

"Parar áudio" para a reprodução e só isso. Não existe ainda botão de
interromper a resposta: o backend não cancela a geração, e um botão que
fingisse cancelar seria pior que nenhum.

### Arquivos

Sem build e sem framework. `index.html` é só marcação; estilos e scripts vivem
em `src/zeus/hud/estatico/` e são servidos por `/estatico/NOME` — só nomes
simples, só `.js` e `.css`, só dessa pasta. Nenhum texto que veio de fora
vira marcação: a página monta elementos com `textContent`.

Validação desta versão: Chrome headless com backend e estado isolados, Ollama
e Piper falsos, dados fictícios, em 1440×900, 1024×768, 390×844 e zoom de
200%, teclado (Tab, `/`, Esc) e contraste mínimo de 5,6:1 no texto. O
roteiro está descrito em `docs/execucao/LOTE_1.md`.

## Voz que sai: Piper, local

Falar não exige microfone, então é o lado da voz que dá para entregar inteiro
em casa hoje. O Piper roda na CPU, o que também evita disputar a VRAM com o
modelo de conversa.

```bash
pip install piper-tts --break-system-packages
mkdir -p ~/.local/share/piper
# baixe uma voz em português do repositório de vozes do Piper,
# por exemplo pt_BR-faber-medium (.onnx e .onnx.json no mesmo diretório)
```

No `~/.config/zeus/config.json`:

```json
"voz_binario": "piper",
"voz_modelo": "/home/zeus/.local/share/piper/pt_BR-faber-medium.onnx"
```

`./zeus check` mostra o diagnóstico da voz: pronta, binário ausente ou modelo
inexistente. Sem Piper, nada quebra — o Zeus continua escrevendo, e a interface
diz "sem voz" em vez de fingir.

A síntese acontece no servidor e o navegador toca o WAV. Cada frase vira um
arquivo com nome derivado do texto, então repetir uma frase não sintetiza de
novo.

## Ouvidos: faster-whisper, no próprio X99

O microfone é o do aparelho que abre a interface. O navegador grava, manda o
áudio para o Zeus e a transcrição acontece no X99, na CPU. O áudio não sai da
rede de casa — é isso que separa esta escuta do ditado do navegador.

```bash
pip install faster-whisper --break-system-packages
```

Nada mais é preciso: o modelo é baixado na primeira fala e fica em cache. O
`escuta_modelo` aceita `tiny`, `base`, `small`, `medium` e `large-v3`; `small`
com `int8` é o equilíbrio razoável para 24 threads. A GPU continua inteira com
o modelo de conversa.

```json
"escuta_modelo": "small",
"escuta_computo": "int8"
```

`./zeus check` diz se a escuta está pronta. Sem o pacote, o botão de falar cai
para o ditado do navegador, com aviso, e se nem isso existir ele aparece
desligado com o motivo.

## Origem segura: por que a HUD sobe em https

O navegador só libera o microfone em origem segura. Em `http://192.168.x.x` ele
recusa, e o Zeus ficaria sem ouvidos justamente no aparelho que tem microfone.

Por isso, com `hud_tls` ligado (o padrão), o Zeus gera um certificado próprio
na primeira execução e sobe em `https`. Como é autoassinado, o navegador avisa
uma vez: você aceita e pronto. A chave privada fica em
`~/.local/state/zeus/tls/`, com permissão restrita, e nunca sai da máquina.

Se o IP da máquina mudar, apague essa pasta e reinicie: o certificado é
refeito com o endereço novo. Sem `openssl` instalado, a HUD sobe em `http` e
avisa no log — aí o microfone só funciona por `localhost`.

## Voz que entra pelo navegador: o caminho de menor confiança

Quando a escuta local não está instalada, o botão cai para o reconhecimento do
próprio navegador, que envia o áudio para o serviço dele. Ele pede confirmação
na primeira vez e nunca é o caminho padrão. É conveniência, não a voz do
projeto.

O satélite de voz com microfone próprio, palavra de ativação e alto-falante
continua sendo outra etapa, e depende de hardware que ainda não existe na
bancada.

## Limites conhecidos

A interface fala HTTP simples na rede local. Não exponha essa porta no
roteador. Quando houver acesso de fora, o caminho previsto é Tailscale, não
abrir porta.

O fluxo de eventos é SSE, de mão única: o navegador envia por POST e recebe
pelo fluxo. Enquanto a conversa e o estado forem o conteúdo, isso basta e
dispensa implementar WebSocket à mão.

## A resposta em fluxo

O plano mestre pede resposta inicial útil em até dois segundos. A 9,8 tokens
por segundo isso é impossível se a resposta só aparecer pronta: uma frase de
oitenta tokens levaria oito segundos de tela parada.

Por isso a conversa na interface é transmitida token a token, com um cursor
piscando enquanto ele escreve. A primeira palavra aparece em um ou dois
segundos e o resto chega enquanto você lê.

Quando o modelo começa a escrever e então decide usar uma ferramenta, o
rascunho é descartado da tela: o que ele ia dizer antes de consultar a memória
não é resposta, e deixar isso visível seria mostrar pensamento como se fosse
conclusão.

O Telegram continua recebendo a resposta inteira de uma vez, com o aviso de
digitação durante a espera.

## Ajustes e medição da versão 0.3.0

No arquivo de configuração efetivamente indicado por `./zeus check`:

```json
{
  "escuta_modelo": "small",
  "escuta_computo": "int8",
  "escuta_idioma": "pt",
  "escuta_threads": 4,
  "escuta_beam": 1,
  "escuta_silencio_ms": 500,
  "escuta_vocabulario": ""
}
```

São valores iniciais para medir, não a configuração ótima comprovada do X99.
Beam maior pode melhorar reconhecimento com custo de processamento. O vocabulário
aceita nomes curtos específicos; não inserir a conversa inteira nem fatos pessoais.
A GPU continua destinada ao modelo de conversa.

```bash
./zeus preparar-escuta
./zeus medir-escuta /caminho/gravacao.webm --repeticoes 3
```

O primeiro comando pode baixar o modelo e confirma a carga naquele processo.
Não mantém um processo aquecido: `run` reutiliza seu próprio motor depois da
primeira fala. A medição não apaga o arquivo fornecido e não publica a transcrição.
Compare a primeira rodada com as seguintes, além de ouvir e conferir o acerto.
Dependências opcionais devem ficar em ambiente virtual, não no Python do sistema.

O texto final agora chega antes do WAV. Um novo turno ou início de gravação
interrompe a reprodução no navegador. Isso não é ainda cancelamento da geração
do LLM nem conversa contínua por palavra de ativação. O microfone continua com
início e parada explícitos e limite de 60 segundos na interface.

Referência: [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Autoteste de voz e escuta

"A voz não funciona" tem pelo menos seis causas, e de fora todas parecem
iguais: binário errado no PATH (o Ubuntu tem um `piper` que configura mouse),
modelo ausente, caminho com erro de digitação, microfone mudo, pacote de escuta
faltando, áudio sem saída.

```bash
./deploy/testar-voz.sh            # usa o microfone padrão
./deploy/testar-voz.sh --listar   # mostra os microfones, inclusive o da webcam
./deploy/testar-voz.sh --fonte alsa_input.usb-...
```

Cada etapa falha sozinha, com o motivo e o que fazer. A etapa do microfone não
se contenta em gravar: ela mede o nível do áudio, porque um arquivo de silêncio
tem exatamente o mesmo tamanho de um com voz — e foi assim que "gravou" passou
a parecer sucesso quando não era.

## Painel de saúde

A HUD deixou de ser só a janela de conversa. O X99 roda sem monitor num canto
da casa, e quando o Zeus fica lento a pergunta é sempre a mesma: é o modelo, é
a RAM, é a GPU térmica, é o disco cheio? Sem número na tela a resposta vira
palpite, então a página agora é também o painel de saúde da máquina.

A rota é `GET /saude`, com a mesma chave das outras rotas de dado — medir o X99
de fora sem chave seria um vazamento discreto de inventário. O corpo vem de
`src/zeus/saude.py`, que lê `/proc`, `/sys/class/hwmon` e `nvidia-smi`. Nenhuma
biblioteca externa: a promessa de clonar e rodar continua valendo.

Três decisões que o painel tomou de propósito:

**Nada aqui vira zero por educação.** Uma GeForce não informa potência, e
`nvidia-smi` devolve `[N/A]`. O painel mostra `—`, não `0 W`. O mesmo vale para
a primeira amostra de CPU: `/proc/stat` guarda contadores desde o boot, então
ocupação só existe entre duas leituras, e antes da segunda o campo é `None`.

**`iowait` conta como ocioso.** Disco travado não é CPU ocupada. Somar iowait
inflaria o painel exatamente no cenário em que ele precisa apontar para o
disco.

**`MemAvailable`, não `MemFree`.** Num servidor saudável a memória livre vive
perto de zero de propósito, porque o kernel usa o resto como cache. O número
honesto é o que dá para recuperar.

O navegador pede `/saude` a cada dois segundos e para quando a aba sai de foco.
`nvidia-smi` custa uns 40 ms e é consultado no máximo a cada três segundos; se
não existe placa, a busca acontece uma vez e nunca mais.

### Onde a saúde aparece

Na vista Diagnóstico: medidores de CPU e GPU, núcleos, os últimos minutos de
CPU, memória e GPU, memória, swap, VRAM, disco do estado, rede e o processo
do Zeus. O navegador só pede `/saude` com essa vista aberta e a aba visível —
a cada dois segundos, ou a cada dez no modo Economia.
