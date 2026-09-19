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
