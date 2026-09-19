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

## Voz que entra: ainda não é local

O botão de microfone usa o reconhecimento do próprio navegador, que envia o
áudio para o serviço dele. Por isso ele pede confirmação na primeira vez e
nunca é o caminho padrão. É conveniência para ditar rápido, não a voz do
projeto.

A escuta local de verdade — faster-whisper com microfone no satélite — é outra
etapa, e depende de hardware que ainda não existe na bancada. Prometer que o
ditado do navegador é "voz local" seria mentira, e o projeto inteiro depende de
não mentir sobre o que está instalado.

## Limites conhecidos

A interface fala HTTP simples na rede local. Não exponha essa porta no
roteador. Quando houver acesso de fora, o caminho previsto é Tailscale, não
abrir porta.

O fluxo de eventos é SSE, de mão única: o navegador envia por POST e recebe
pelo fluxo. Enquanto a conversa e o estado forem o conteúdo, isso basta e
dispensa implementar WebSocket à mão.
