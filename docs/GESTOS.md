# Gestos pela webcam

A interface lê a mão na câmera e responde a ela. Vale dizer logo o que isso é
e o que não é.

## O que é

Segmentação de pele em YCbCr cruzada com movimento contra um fundo aprendido,
acompanhando a maior mancha. Roda em 160 por 120 pixels, a doze quadros por
segundo, em JavaScript comum.

Isso reconhece **presença**, **posição**, **tamanho** e **oscilação**. Não
reconhece dedo. Não sabe quantos dedos estão levantados, não lê língua de
sinais e não distingue a sua mão da mão de outra pessoa.

O caminho que faria isso — landmarks, MediaPipe e parentes — precisa de um
modelo de vários megabytes baixado de algum lugar. Isso briga com duas
promessas do Zeus ao mesmo tempo: clonar e rodar, e funcionar sem rede. Se um
dia valer a pena, o lugar certo é um `./zeus preparar-visao` que baixa uma vez
e verifica, como a voz e a escuta já fazem.

## O que dá para fazer

**Acenar** chama a atenção: o campo de conversa recebe foco. O orbe **não** vai
para "ouvindo" — nenhum microfone foi ligado, e dizer que está ouvindo seria
mentira. Aceno é a mão trocando de direção três vezes em menos de um
segundo — passar na frente da câmera não conta, de propósito.

O arrasto do mapa com a "mão fechada" saiu na HUD v1. "Fechada" aqui era a
mancha encolher em relação ao pico, e afastar a mão da câmera produz o mesmo
sinal: o mapa se mexia sem ninguém pedir. Voltará quando houver
reconhecimento de dedos de verdade, com calibração.

O botão dos gestos fica no Diagnóstico, marcado como experimental.

Nenhum gesto manda mensagem, executa ferramenta ou abre coisa. Uma sombra na
parede não pode disparar ação no computador de ninguém, e um gesto é sempre
mais ambíguo que um clique.

## Privacidade

**O vídeo não sai do navegador.** Nenhum quadro vai para o Zeus, nada é
gravado, nada é enviado a serviço nenhum. O que existe é um `<canvas>` de 160
por 120 dentro da página. Há teste lendo a página atrás de qualquer envio de
imagem, justamente para que ninguém acrescente um por engano mais tarde.

**Desligado por padrão**, com botão próprio.

**Enquanto está ligada**, um indicador vermelho pulsa ao lado do botão e a
prévia mostra exatamente o que o Zeus enxerga — que é pouco, e ver isso vale
mais que qualquer texto tranquilizador.

**Sair da aba desliga a câmera.** Aba escondida com a luz da webcam acesa é o
que ninguém quer ver.

A câmera exige origem segura. O certificado próprio que o Zeus gera já
resolve; em `http` puro o navegador nem oferece a opção, e a interface diz
isso em vez de deixar um botão morto.

## Limites conhecidos

Luz forte atrás da pessoa derruba a segmentação: a mão vira silhueta e perde a
cor. Parede bege e madeira clara entram na faixa de pele — é por isso que o
movimento precisa concordar antes de a mancha valer. Uma mão parada por muito
tempo acaba virando fundo, e isso é de propósito: sem isso, um encosto de
cadeira cor de pele travaria o rastreio para sempre.
