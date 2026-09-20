# Interface e voz

O X99 roda sem monitor, então a interface do Zeus vive no navegador de
qualquer máquina da rede. Ela é servida pelo próprio processo, sem framework e
sem dependência: uma página, um fluxo de eventos e duas rotas.

## Abrir

Defina `chave_hud` em `~/.config/zeus/config.json`. Se você deixar vazio, o
Zeus gera uma chave a cada início e a imprime no evento `started` — prático
para testar, ruim para o dia a dia, porque o endereço muda.

```bash
./zeus run
# {"event": "started", ..., "hud": "http://0.0.0.0:8770/?chave=..."}
```

Do seu computador, abra `http://192.168.100.221:8770/?chave=SUA_CHAVE`. A
página pede a chave se você entrar sem ela na URL.

A chave não é decoração. Sem ela, qualquer aparelho na mesma rede conversaria
com a memória do Zeus. A página em si é pública; nenhuma rota de dado responde
sem chave válida, e a comparação é de tempo constante.

## O que a interface mostra

O orbe reage ao estado: ocioso, ouvindo, pensando, falando, offline. Não é
enfeite — é a diferença entre "está gerando" e "travou", que a 9,8 tokens por
segundo importa mais do que parece.

Ao lado ficam as perguntas em aberto, a agenda e a memória confirmada. É a
mesma memória do Telegram: o que você conta por um canal aparece no outro,
porque a identidade e o episódio são do Zeus, não do canal.

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

### O que a página mostra

A coluna da esquerda é o plasma: o orbe, o estado (ocioso, ouvindo, pensando,
falando, offline) e os chips de capacidade. O anel externo do orbe é a
ocupação da CPU, e o ritmo da respiração acompanha a carga — dá para sentir a
máquina sob pressão sem ler número nenhum.

Abaixo vem o mapa do Zeus: cada nó é uma capacidade, e a aresta acende quando
ela está verificada. É o mapa honesto que dá para desenhar hoje. Um mapa
geográfico exige sensor com posição, e ainda não existe nenhum; desenhar um
agora seria enfeite.

A coluna da direita são os sinais vitais: CPU (total, por núcleo, frequência,
temperatura, carga), GPU (uso, VRAM, temperatura, potência, ventoinha),
memória e swap, disco do estado do Zeus, rede e o próprio processo. A faixa
embaixo guarda os últimos três minutos de CPU, memória e GPU — o suficiente
para ver se o pico foi a resposta que acabou de sair ou algo que já estava lá.

As pendências (perguntas, agenda, entregas, memória, operação) ficam em abas,
com contador, em vez de empilhadas numa lista só.

Abaixo de 980 px a página vira três vistas — Conversa, Saúde e Mapa — no celular.
