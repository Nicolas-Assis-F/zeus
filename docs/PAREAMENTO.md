# Pareamento do celular

Como colocar o celular na HUD do Zeus sem digitar a chave, e por que é seguro.
Código: `src/zeus/pareamento.py` (fluxo e tokens) e `src/zeus/qr.py` (o QR,
em Python puro). Testes: `tests/test_pareamento.py`, `tests/test_qr.py`.

> Estado: o núcleo está pronto e testado, mas a tela e as rotas da HUD ainda
> não foram ligadas (`hud/servidor.py` e `hud/index.html` ficaram de fora
> desta entrega). O passo a passo abaixo descreve o fluxo como ele vai
> funcionar depois dessa integração.

## Passo a passo

Antes da primeira vez, o celular precisa confiar no certificado da HUD (veja
[HTTPS e o certificado](#https-e-o-certificado)). Isso se faz uma vez só.

**No PC**

1. Abra a HUD e vá em **Central → Controles → Parear celular**.
2. Aparece um QR e, embaixo, um código de 8 dígitos. Os dois valem por
   **2 minutos** e **uma vez só**. Se passar o tempo, clique de novo: o QR
   anterior deixa de valer na hora.

**No celular** (na mesma rede Wi-Fi do PC)

3. Abra a câmera e aponte para o QR. Toque no link que aparece
   (`https://192.168.100.221:8770/parear...`). Se a câmera não ler, abra
   `https://192.168.100.221:8770/parear` no navegador e digite os 8 dígitos.
4. O celular mostra um número de **4 dígitos**.

**De volta no PC**

5. A HUD mostra o nome do aparelho, o IP e **os mesmos 4 dígitos**. Confira:
   - batem → **Aprovar**;
   - não batem, ou você não pediu nada → **Negar** (o botão em foco é o
     Negar, de propósito). Número diferente quer dizer que outro aparelho
     usou o QR antes do seu.
6. Pronto. O celular entra na HUD e continua entrando por 30 dias a partir
   do último uso, até no máximo 90 dias desde o pareamento. Depois disso,
   pareie de novo.

**Tirar um aparelho**: Central → Controles → Aparelhos → Revogar (ou
"Revogar todos"). O aparelho cai na hora, inclusive a conexão ao vivo (SSE).
Celular perdido: revogue antes de qualquer outra coisa.

## Modelo de segurança

O que protege cada etapa, e contra o quê.

| Etapa | Proteção | Contra |
|---|---|---|
| QR | nonce de 128 bits (`secrets.token_urlsafe(16)`), 120 s, uso único | adivinhação, reuso de foto antiga |
| QR | o nonce vai no fragmento (`#n=`), que o navegador não manda ao servidor | nonce em log de acesso, em proxy, no histórico do servidor |
| Código de 8 dígitos | bloqueado após 5 erros (o QR continua valendo) | força bruta do código digitável |
| Reivindicação | 5 tentativas por minuto por IP | força bruta em geral |
| Reivindicação | comparação de hashes em tempo constante (`hmac.compare_digest`) | descobrir o segredo pelo tempo de resposta |
| Conferência | 4 dígitos derivados por HMAC do segredo apresentado e do id do pedido | alguém que fotografou o QR e chegou antes |
| Aprovação | só pelo PC já autenticado, com foco em Negar, 2 minutos para decidir | aprovação por engano, pedido esquecido aberto |
| Token | `secrets.token_urlsafe(32)` (256 bits), entregue **uma vez** | — |
| Token | cookie `zeus_aparelho`, `HttpOnly; Secure; SameSite=Strict; Path=/` | XSS lendo o token, envio fora de HTTPS, CSRF |
| Token | no disco só o `sha256` | quem ler o arquivo não entra |
| Token | 30 dias renováveis pelo uso, teto de 90 dias desde a criação | celular perdido e esquecido entrando para sempre |
| Revogação | apaga o hash e chama `ao_revogar` (o servidor derruba o SSE) | aparelho revogado continuar ouvindo |
| Servidor | `Host` na lista (`host_permitido`) | DNS rebinding |
| Servidor | `Origin` da própria HUD (`origem_permitida`) e cabeçalho `X-Zeus: 1` nas chamadas que mudam estado | CSRF |

O estado fica em arquivo próprio (`pareamento.json` no diretório de estado do
Zeus), com permissão `0600`, pasta `0700` e gravação atômica (arquivo
temporário + `os.replace`). Nele estão só hashes: nonce, código e token nunca
aparecem em claro (há teste lendo o arquivo para garantir).

O último uso do aparelho é gravado com precisão de um minuto, para não haver
uma escrita em disco por requisição.

**O que isso não cobre**, para ser honesto:

- Um celular desbloqueado nas mãos de outra pessoa é o Nicolas, para a HUD.
  A defesa é o bloqueio de tela do próprio celular e a revogação.
- Na rede local, quem vê a tela do PC pode fotografar o QR. A conferência de
  4 dígitos existe exatamente para isso, mas só funciona se for conferida.
- O token tem escopo `celular`, mas hoje ainda não há permissões diferentes
  por escopo: o servidor precisa decidir o que um celular pode fazer.

## HTTPS e o certificado

Sem HTTPS o celular não libera microfone, não instala a HUD como app (PWA) e
o cookie `Secure` nem é guardado. A HUD já sobe em HTTPS com um certificado
próprio, gerado na primeira execução em `~/.local/state/zeus/tls/`
(`zeus-cert.pem`; a chave `zeus-chave.pem` nunca sai do PC). Ele é
autoassinado, vale para `192.168.100.221`, `127.0.0.1`, `zeus` e `localhost`.

Como não é de uma autoridade pública, o celular desconfia dele até você
instalá-lo como confiável. Mande **só o `zeus-cert.pem`** para o celular
(cabo USB, e-mail para você mesmo, Drive). Nunca a chave.

Antes de instalar, confira a impressão digital no PC:

```sh
openssl x509 -in ~/.local/state/zeus/tls/zeus-cert.pem -noout -fingerprint -sha256
```

e compare com a que o celular mostra nos detalhes do certificado. Se forem
diferentes, não instale.

### Android

1. Configurações → Segurança e privacidade → Mais configurações de segurança
   → Criptografia e credenciais → **Instalar um certificado → Certificado CA**
   (o caminho muda um pouco por fabricante; procure "certificado CA" na busca
   das configurações).
2. O Android avisa que a rede pode ser monitorada: é o aviso padrão para
   qualquer CA instalada pelo usuário. Confirme e escolha o `zeus-cert.pem`.
   É preciso ter bloqueio de tela.
3. Abra `https://192.168.100.221:8770` no Chrome: deve abrir sem aviso.

O Chrome do Android confia em CAs instaladas pelo usuário. Muitos outros apps
não (desde o Android 7 isso é opção de cada app), mas para a HUD só o
navegador importa.

Dá para pular a instalação e tocar em "Avançado → continuar" no aviso, mas aí
a HUD fica pela metade: o Chrome não registra service worker com erro de
certificado, então nada de PWA, e o aviso volta.

### iPhone (iOS)

1. Mande o `zeus-cert.pem` por AirDrop ou e-mail e abra **no Safari/Mail**.
   O iOS diz "Perfil transferido".
2. Ajustes → Geral → VPN e Gerenciamento de Dispositivo → perfil "zeus" →
   **Instalar**.
3. Ajustes → Geral → Sobre → **Ajustes de Confiança de Certificados** → ligue
   a chave do "zeus". Sem este passo o perfil fica instalado, mas não vale
   para sites.

**Limitação conhecida no iPhone.** Desde o iOS 13 a Apple exige, para
qualquer certificado de servidor, inclusive os instalados à mão: validade de
no máximo 825 dias e a extensão *Extended Key Usage* com `serverAuth`. O
certificado que a HUD gera hoje vale 10 anos e não tem essa extensão, então
é provável que o Safari continue recusando mesmo depois dos passos acima.
Corrigir isso é mudar `garantir_certificado` em `hud/servidor.py` (validade
de 825 dias e `-addext extendedKeyUsage=serverAuth`) e apagar o certificado
antigo para ele ser refeito; ficou fora desta entrega, que não podia mexer no
servidor. No Android isso não acontece.

## Para quem for ligar no servidor

API de `zeus.pareamento.Pareamento(arquivo_json, relogio=None, ao_revogar=None)`:

- `iniciar(endereco_base)` → `{id, url, qr_svg, codigo_manual, expira_em}`.
  Só o PC autenticado chama. `qr_svg` vai direto no HTML (fundo branco
  próprio, funciona na HUD escura).
- `situacao()` → estado da tentativa para a tela do PC (inclui os 4 dígitos
  quando há pedido); `cancelar()` fecha a tentativa.
- `reivindicar(nonce_ou_codigo, nome_aparelho, ip)` →
  `{reivindicacao_id, codigo_conferencia}`. Recusas levantam
  `ErroDePareamento` com `.motivo` (`invalido`, `expirado`, `usado`,
  `bloqueado`, `limite`, `sem_tentativa`); `limite` vira HTTP 429. A página
  `/parear` lê o nonce de `location.hash` e manda por POST; o celular pode
  recalcular os 4 dígitos com HMAC-SHA256 se quiser, mas basta mostrar o que
  o servidor devolveu.
- `aprovar(reivindicacao_id, aprovar)` → com `True`, `{aprovado, aparelho_id,
  nome, token, expira_em, max_age, set_cookie}`. O `set_cookie` vai na
  resposta à **página do celular** (por exemplo, o celular consulta o
  resultado do pedido e recebe o cookie nessa resposta); o token não deve
  passar pela tela do PC nem ser guardado em lugar nenhum.
- `validar(token, ip=None)` → aparelho sem hash, ou `None`. Use com
  `token_do_cookie(cabecalho_cookie_da_requisicao)`.
- `aparelhos()`, `revogar(aparelho_id)`, `revogar_todos()`; `ao_revogar`
  recebe cada id revogado.
- Funções soltas: `cabecalho_cookie(token, max_age)`, `token_do_cookie`,
  `host_permitido(host, permitidos)`, `origem_permitida(origin, permitidos)`,
  `hosts_padrao(ip, porta)`.
