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

## Voz natural: ElevenLabs pelo OpenRouter (#68)

O Piper resolve, mas soa como máquina. A ElevenLabs soa como gente, e o
OpenRouter a serve no mesmo endpoint e com a mesma chave do modelo, então não
há conta nova nem dependência: só `urllib`.

```json
"voz_provedor": "elevenlabs",
"voz_eleven_voz": "brian",
"escuta_provedor": "scribe"
```

- **Conversa** usa o `eleven-v4-turbo`. **Briefing** e textos acima de
  `voz_caprichada_acima` (400 caracteres) usam o `eleven-v4`, que aceita
  tags de emoção inline como `[warmly]` e `[calmly]`.
- **A voz** é um nome da lista do OpenRouter (brian, george, daniel, liam,
  adam, chris…) ou um `voice_id` da Voice Library da ElevenLabs.
- **A reserva é automática.** Sem rede, sem chave, sem saldo ou com o teto
  estourado, a fala cai para o Piper e a escuta para o faster-whisper. A troca
  sai no log como `voz_origem` e `escuta_origem`, com o motivo. Depois de uma
  falha, o provedor remoto fica de lado por um tempo que depende do erro: rede
  60 s, servidor 2 min, 429 5 min, saldo 1 h, chave recusada 6 h. Assim o Zeus
  não paga a espera de rede a cada frase.
- **Teto diário.** O teto vale para `voz_teto_caracteres_dia` e
  `escuta_teto_segundos_dia`. O contador fica em `~/.local/state/zeus/voz-gasto.json`
  e zera à meia-noite. Aos 80% o Zeus avisa no canal, uma vez por dia. Teto
  zero desliga a voz remota.
- **Áudio no WhatsApp.** Quando Nicolas manda áudio no grupo, a resposta vai
  em texto e também como nota de voz (ogg/opus pelo ffmpeg). Para desligar,
  use `voz_resposta_em_audio: false`.
- **Mídia de terceiros.** `escuta_scribe_midia` vem desligado. A mídia do
  WhatsApp inclui áudio de clientes e do Henrique, e ligar isso manda essas
  vozes para a ElevenLabs. O texto delas já vai ao modelo remoto, mas a voz é
  um dado a mais, então a decisão fica com Nicolas.

Medido no X99 em 17/10/2026:

| | Remoto | Local |
|---|---|---|
| Fala de 5 s (Turbo × Piper) | 1,6–2,1 s até o primeiro byte | 2,4 s |
| Transcrição de 7 s (Scribe × large-v3 na CPU) | 0,75–0,82 s | 19,6 s, com a carga do modelo |

O endpoint devolve o PCM quase de uma vez, entre 0,05 e 0,4 s depois do
primeiro byte. Tocar em fluxo economizaria pouco, então o ganho de verdade
está em começar a falar antes de a resposta inteira do modelo ficar pronta
(#36).

Preço com o desconto de lançamento, que vai até 19/10/2026: Turbo
US$ 20/M caracteres, v4 US$ 40/M, Scribe US$ 0,11/h. Depois disso, o dobro.
O `usd_estimado` do contador usa o preço cheio.

## Escuta no ambiente: "Hey Jarvis" pelo microfone da casa (#68)

Com `escuta_ambiente: true`, o Zeus ouve pelo microfone do próprio X99 (a
webcam) e responde no alto-falante, sem navegador aberto.

1. **Dormindo**, só a palavra de ativação (openwakeword, local) escuta. Nenhum
   áudio sai da máquina.
2. **Ouvindo**, grava até a fala acabar: `escuta_fim_silencio_ms` de silêncio
   contra o piso de ruído da sala.
3. **Respondendo**, transcreve (Scribe, ou faster-whisper de reserva), entrega
   ao núcleo pelo mesmo caminho da HUD e fala a resposta. Se a resposta passar
   de `escuta_reconhecimento_apos_s`, toca na hora `escuta_reconhecimento`
   ("Deixa comigo, senhor.", já sintetizada e em cache).
4. Depois de responder, ouve por mais `escuta_continuacao_s` sem exigir a
   palavra, para emendar.

**Guarda de eco.** Enquanto o alto-falante toca, mais a latência e 250 ms de
cauda, o microfone é descartado, e o Zeus não responde à própria voz. Falar
por cima do Zeus não o interrompe; isso fica para a #36.

**Extras opcionais.** O `pw-record`/`pw-play` vem do PipeWire. Já o
`openwakeword`, o `numpy` e o `onnxruntime` são pacotes Python. Sem eles, o
`escuta_ambiente` no log do `run` diz o que falta, e o resto do Zeus sobe normal.

```bash
pip install --user --break-system-packages --no-deps openwakeword
pip install --user --break-system-packages scipy scikit-learn tqdm requests
python3 -c "from openwakeword.utils import download_models; download_models(['hey_jarvis'])"
```

A palavra de partida é `hey_jarvis`. Um modelo treinado para "Zeus" entra pelo
caminho do `.onnx` em `escuta_palavra`. A transcrição corrige "Deus" e "seus"
para "Zeus" quando estão em posição de chamado, e descarta as frases que o
Whisper inventa no silêncio ("Legendas pela comunidade Amara.org").

Medido no X99, com a cadeia real e o microfone trocado pelo arquivo:

| Etapa | Tempo |
|---|---|
| Palavra detectada | ainda durante a frase |
| Fim de fala + transcrição (Scribe) | 1,3 s depois do fim da frase |
| "Deixa comigo, senhor." no alto-falante | 2,8 s |
| Palavra de ativação na CPU | ~4% de um núcleo |

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
