# Qualidade da conversa — diagnóstico da primeira conversa real

Registro da primeira conversa do Zeus com Nicolas pelo Telegram, em 18/09/2026,
e do que ela revelou. A conversa funcionou de ponta a ponta: memória, lembrete
agendado por pedido e entrega no horário. As falhas abaixo são de qualidade,
não de funcionamento.

## O que era defeito do projeto, já corrigido

**Ferramenta chamada para qualquer coisa.** "Opa" e "Bom?" viraram consulta à
memória, e a resposta foi "não há fato algum sobre Opa". O catálogo ia junto de
toda mensagem sem nenhuma instrução sobre quando não usá-lo. A persona agora
diz, com exemplo, que saudação se responde conversando.

**Persona descrita em vez de demonstrada.** O contexto explicava o tom em prosa
e terminava com uma lista de proibições. Um modelo de 8 bilhões de parâmetros
responde a isso virando um atendente cauteloso. A persona passou a carregar
pares de fala reais, injetados na conversa como turnos, que é como um modelo
pequeno aprende voz. Editar esses pares em `config/persona.md` é o controle
mais direto sobre a personalidade.

**Chamada de ferramenta vazando como texto.** O modelo imaginou uma ferramenta
inexistente e escreveu o JSON dela na resposta. A saída passa por uma limpeza
que remove objetos com cara de chamada; se sobrar nada, vai uma frase honesta.

**Silêncio parecendo travamento.** A 9,8 tokens por segundo, uma resposta demora
mais que a paciência de quem espera. Agora o aviso de digitação é mantido
enquanto o modelo gera, mensagens que chegam juntas viram um turno só em vez de
duas gerações fora de ordem, e a resposta tem teto de tamanho.

## O que é limite real, não defeito

**Invenção de dado do mundo.** Crocodilo-de-garganta-azul, mordida de mosquito,
força de mordida do tigre: nada disso veio de fonte, porque não existe pesquisa
nesta entrega. Um modelo local pequeno preenche lacuna com invenção plausível.
A persona agora manda marcar esse tipo de resposta como memória do modelo e não
como fato conferido, mas a correção de verdade é a Etapa 5, com busca e
procedência.

**Profundidade da persona.** O teto continua sendo o tamanho do modelo que cabe
em 4 GiB de VRAM. Os exemplos de voz melhoram muito o tom sem trocar hardware;
eles não transformam um 8B em um 70B.

## Ordem de esforço para melhorar

1. Editar `config/persona.md`. Custo zero, efeito imediato, sem deploy.
2. Comparar modelos que cabem: o `llama3.1:8b` atual contra alternativas de 7 a
   8 bilhões com uso de ferramenta mais estável em português.
3. Híbrido seletivo: modelo local decide e usa ferramenta, modelo remoto
   conduz a conversa. O código já alterna provedor por configuração.
4. GPU com mais memória, que é a única forma de subir o teto sem sair de casa.

## Autonomia

Hoje a iniciativa existe, mas só nasce de pedido: Nicolas combina um lembrete e
o Zeus cumpre no horário. A iniciativa que o plano descreve nasce de percepção,
e para isso falta fonte de evento: presença, entrada, agenda, câmera. Sem uma
delas, não há o que perceber, e qualquer "autonomia" seria só o modelo
inventando assunto. O próximo degrau real é conectar a primeira fonte de evento,
não aumentar a liberdade do modelo.

## Agir, e depois contar

Depois da primeira conversa longa pelo Telegram, Nicolas resumiu o problema em
duas frases: "ainda muito robótico, sem persona" e "sempre fica falando pra eu
confirmar". A segunda tinha causa concreta dentro do próprio arquivo de
persona.

Os exemplos de voz não são enfeite: eles entram na conversa como turnos reais,
de usuário e de assistente. Um deles dizia, para um pedido de lembrete:

> Vou conferir o horário e registrar esse lembrete. A confirmação vem assim que
> estiver salvo.

Isso ensina exatamente o hábito que incomodava — anunciar a intenção e devolver
o turno. O exemplo virou:

> Registrado para as 14h32. Falo com você lá.

E a regra que faltava foi escrita: guardar um fato, consultar a memória,
agendar, pesquisar, listar uma pasta permitida e ler um arquivo de texto são
ações reversíveis e já autorizadas. O Zeus faz e relata no passado. "Procurei e
achei", não "quer que eu procure".

Perguntar antes ficou reservado a três casos: a ação sai do que Nicolas
permitiu; ela é irreversível ou tem efeito fora da conversa, como abrir algo na
tela dele; ou falta um dado que muda o resultado, e aí é uma pergunta só,
adiantando o que já dá para adiantar.

### Como saber se melhorou

`tests/test_persona.py` guarda o arquivo contra a volta do hábito: nenhum
exemplo de voz pode abrir com "posso", "devo", "quer que eu" ou "vou registrar".
É um teste sobre o texto, não sobre o tom — ele impede a regressão óbvia e não
prova nada sobre a conversa.

A prova de tom é comparativa e cega. A persona anterior está guardada em
`avaliacao/personas/anterior.md`, de propósito sem correção nenhuma:

```
./zeus persona-cega --real --variantes config/persona.md,avaliacao/personas/anterior.md
```

As respostas aparecem sob rótulos opacos, embaralhados por jornada. Nicolas dá
nota nos seis critérios e só depois vem a revelação.

A jornada `sem-pedir-licenca`, em `avaliacao/jornadas.json`, cobre o lado
automático: ela roda só com `--real`, porque com dublê o texto é fixo e não diz
nada sobre tom. Os passos verificam que guardar um fato e pesquisar acontecem
sem pedir licença, e que abrir algo na tela — a única ação com efeito fora da
conversa — continua sendo confirmada antes.

## O robô que era corte silencioso de prompt

Depois de ajustar a persona, Nicolas disse de novo: "ele ainda tá muito
robótico". A persona não era o problema — ela nem chegava ao modelo.

O Ollama usa uma janela de contexto padrão quando ninguém pede outra, e ela é
pequena: 2048 tokens em boa parte das instalações. Quando o prompt não cabe,
ele **corta pela frente, em silêncio**. Não há erro, não há aviso no log, a
resposta chega normalmente. O que vive na frente do prompt é exatamente a
persona.

A conta:

```
instrução da persona    ~1190 tokens
exemplos de voz          ~360 tokens
catálogo de ferramentas ~1280 tokens   (13 ferramentas)
contexto e memória       ~200 tokens
                        ------------
                        ~3030 tokens
```

Com 2048 de janela, quase mil tokens eram descartados do começo a cada
mensagem. Sobrava um assistente genérico com uma lista de ferramentas — que é
precisamente a descrição de "parece um bot qualquer".

`contexto_tokens` agora vai explícito no pedido, com 8192 de padrão, e
`./zeus check` mostra a conta antes de a conversa acontecer:

```
"contexto": "cabe (3161 tokens estimados para janela de 8192)"
```

Se algum dia o catálogo crescer a ponto de não caber, o `check` diz isso com
todas as letras em vez de deixar a persona sumir de novo.

### Duas causas menores, no mesmo lugar

**O prompt tinha metatexto.** O `persona.md` começava com "Arquivo editável,
fora do código. Mudar o texto muda a conversa sem novo deploy", e trazia a
seção "Exemplos de voz" explicando que os pares viram turnos reais. O modelo lê
o prompt inteiro como instrução: texto que fala *sobre* a persona, em registro
de documentação, ensina a responder como documentação. Agora tudo antes da
primeira seção `##` e a seção de exemplos ficam fora do que o modelo recebe —
sem perder os exemplos, que continuam entrando como turnos de verdade.

**A amostragem era só temperatura.** `top_p`, `top_k` e `repeat_penalty` iam
com o padrão do servidor. Sem penalidade de repetição, um modelo de 8B cai nas
mesmas construções resposta após resposta, e repetição lida em sequência é
metade da sensação de robô.

**E a última linha do prompt era inventário.** O bloco terminava listando
capacidades — "Sem câmera, sem dispositivo, sem ligação" — logo antes da
mensagem de Nicolas. Num modelo pequeno, a última linha é a que mais pesa no
registro. Agora, depois do relógio, vem uma linha fixa que devolve a voz: ela
não muda de turno para turno, então não custa cache nenhum.
