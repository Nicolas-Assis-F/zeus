# Mapa de localização

O mapa de capacidades responde uma pergunta — o que está ligado. Não responde
onde as coisas são. Este responde.

## Como funciona

A interface tem um mapa deslizante escrito à mão, umas cem linhas de
JavaScript. A matemática é a projeção do Mercator (a mesma que o OpenStreetMap
usa) e o resto é posicionar imagem. Não é orgulho: biblioteca de mapa vem de
CDN ou de passo de build, e o Zeus precisa funcionar com a internet caída.

**O navegador nunca fala com o servidor de telas.** A página pede a tela ao
próprio Zeus, em `GET /mapa/tela/{z}/{x}/{y}.png`, com a mesma chave das outras
rotas. O Zeus busca uma vez, guarda em disco e serve dali para sempre.

Isso resolve três coisas de uma vez. Depois de olhar a sua cidade uma vez, o
mapa funciona sem rede. Cada aparelho da casa não aparece sozinho no servidor
público — aparece um agente só, identificado. E existe um lugar só para
respeitar o limite de uso educado do OpenStreetMap, em vez de espalhar esse
cuidado por cada navegador.

O cache fica em `~/.local/state/zeus/mapa/`, com teto configurável
(`mapa_cache_mb`, 200 MB de padrão). Cheio, as telas mais antigas saem
primeiro. Uma tela nunca muda de conteúdo para o mesmo `z/x/y`, então pedir de
novo seria desperdício puro.

## Achar um lugar

A ferramenta `localizar` transforma endereço, bairro ou ponto conhecido em
coordenada, pelo Nominatim, e o resultado vai com a fonte junto — como a
pesquisa faz. O Zeus espera um segundo entre buscas, que é o limite pedido pelo
serviço público, e guarda o que já procurou.

Nome de lugar é texto de fora: qualquer pessoa pode cadastrar qualquer coisa no
mapa aberto. Por isso o resultado sai marcado como externo, e um nome que tenta
soar como ordem leva aviso dizendo que aquilo é nome de lugar.

Na interface, quando o Zeus localiza algo, o mapa vai junto: o pino aparece e a
tela se move. A caixa de busca do painel não fala com o mapa direto — ela
manda uma pergunta para o Zeus, porque quem decide buscar é ele.

## Configurar

```json
"mapa_ativo": true,
"mapa_centro_lat": -16.6869,
"mapa_centro_lon": -49.2648,
"mapa_zoom": 13,
"mapa_cache_mb": 200
```

O centro padrão é Goiânia. Troque para a sua casa e o mapa abre olhando para o
lugar certo, com um pino verde marcando "aqui".

`mapa_telas_url` e `mapa_busca_url` existem para quem quiser apontar para um
servidor próprio — um `tileserver-gl` na rede de casa, por exemplo. Aí o mapa
passa a funcionar sem internet nenhuma, desde a primeira olhada.

`./zeus check` mostra quantas telas já estão guardadas.

## O que ainda não é

Não há rota, não há trânsito e não há posição de ninguém em tempo real. O
mapa mostra onde as coisas são e marca o que o Zeus encontrou. Posição de
pessoa exigiria um sensor que ainda não existe, e desenhar uma seria invenção.
