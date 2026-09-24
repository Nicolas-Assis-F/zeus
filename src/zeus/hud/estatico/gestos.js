"use strict";
/* Gestos pela webcam, sem modelo e sem nada saindo do navegador.

   Segmentação de pele em YCbCr cruzada com movimento contra um fundo
   aprendido, acompanhando a maior mancha. Isso reconhece presença, posição,
   tamanho e oscilação. NÃO reconhece dedos. "Mão fechada" aqui é a área da
   mancha encolher em relação ao pico — afastar a mão da câmera produz o mesmo
   sinal —, e por isso nenhum gesto aciona ação: o aceno só põe o foco no
   campo de conversa, e o microfone continua desligado.

   Tudo em 160x120, 12 quadros por segundo. Nenhum quadro é enviado a lugar
   nenhum, nada é gravado, e a câmera só liga por botão. */
(function (Z) {
const OLHO_L = 160, OLHO_A = 120, CELULA = 8;
const QUADROS_POR_SEGUNDO = 12;

function ehPele(r, g, b){
  /* YCbCr é melhor que RGB para isto: separa luminosidade de cor, então a
     mesma faixa vale com a luz do abajur e com a da janela. A faixa é a
     clássica da literatura de segmentação e cobre tons de pele variados —
     ela erra para madeira e para parede bege, e é por isso que o movimento
     precisa concordar antes de a mancha valer. */
  const cb = 128 - 0.168736*r - 0.331264*g + 0.5*b;
  const cr = 128 + 0.5*r - 0.418688*g - 0.081312*b;
  const y = 0.299*r + 0.587*g + 0.114*b;
  return y > 40 && cb >= 77 && cb <= 127 && cr >= 133 && cr <= 173;
}

function criarOlho(){
  const colunas = Math.ceil(OLHO_L/CELULA), linhas = Math.ceil(OLHO_A/CELULA);
  const fundo = new Float32Array(OLHO_L*OLHO_A);     // luminosidade aprendida
  let aprendido = 0;
  const grade = new Float32Array(colunas*linhas);
  const historico = [];
  let picoDeArea = 0;

  function olhar(dados){
    /* `dados` é o ImageData do quadro reduzido. Devolve o que se enxerga:
       presença, centro em 0..1, tamanho relativo e se é um aceno. */
    grade.fill(0);
    let soma = 0;
    for (let i = 0, p = 0; i < dados.length; i += 4, p++){
      const r = dados[i], g = dados[i+1], b = dados[i+2];
      const luz = 0.299*r + 0.587*g + 0.114*b;
      const diferenca = Math.abs(luz - fundo[p]);
      // O fundo é aprendido devagar: uma mão parada por muito tempo acaba
      // virando fundo, o que é o comportamento certo para não travar num
      // encosto de cadeira cor de pele.
      fundo[p] = aprendido < 20 ? luz : fundo[p]*0.97 + luz*0.03;
      if (aprendido < 20) continue;
      if (!ehPele(r, g, b) || diferenca < 12) continue;
      const x = p % OLHO_L, y = (p / OLHO_L) | 0;
      grade[((y/CELULA)|0)*colunas + ((x/CELULA)|0)] += 1;
      soma++;
    }
    if (aprendido < 20){ aprendido++; return {aprendendo: true, presente: false}; }

    // Maior mancha conectada na grade grossa. Grade grossa é o que deixa isto
    // caber em milissegundos: 20x15 células em vez de 19.200 pixels.
    const vistos = new Uint8Array(colunas*linhas);
    let melhor = null;
    for (let c = 0; c < colunas*linhas; c++){
      if (vistos[c] || grade[c] < CELULA*CELULA*0.25) continue;
      const fila = [c]; vistos[c] = 1;
      let peso = 0, sx = 0, sy = 0, n = 0;
      while (fila.length){
        const atual = fila.pop();
        const ax = atual % colunas, ay = (atual / colunas) | 0;
        peso += grade[atual]; sx += ax*grade[atual]; sy += ay*grade[atual]; n++;
        for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]){
          const nx = ax+dx, ny = ay+dy;
          if (nx < 0 || ny < 0 || nx >= colunas || ny >= linhas) continue;
          const vizinho = ny*colunas + nx;
          if (vistos[vizinho] || grade[vizinho] < CELULA*CELULA*0.25) continue;
          vistos[vizinho] = 1; fila.push(vizinho);
        }
      }
      if (!melhor || peso > melhor.peso)
        melhor = {peso, x: sx/peso/colunas, y: sy/peso/linhas, celulas: n};
    }
    if (!melhor || melhor.peso < 90){ historico.length = 0; return {presente: false}; }

    picoDeArea = Math.max(picoDeArea*0.995, melhor.peso);
    historico.push({x: melhor.x, y: melhor.y, quando: performance.now()});
    if (historico.length > 24) historico.shift();

    return {
      presente: true,
      x: 1 - melhor.x,                 // espelhado: a tela é um espelho
      y: melhor.y,
      area: melhor.peso,
      abertura: picoDeArea ? melhor.peso/picoDeArea : 1,
      acenando: contarIdasEVindas() >= 3,
    };
  }

  function contarIdasEVindas(){
    /* Aceno é a mão trocando de direção várias vezes em menos de um segundo.
       Movimento único, por maior que seja, não conta — senão passar na frente
       da câmera acordaria o Zeus. */
    const agora = performance.now();
    const recentes = historico.filter((h) => agora - h.quando < 1100);
    let trocas = 0, direcao = 0;
    for (let i = 1; i < recentes.length; i++){
      const d = recentes[i].x - recentes[i-1].x;
      if (Math.abs(d) < 0.02) continue;
      const nova = d > 0 ? 1 : -1;
      if (direcao && nova !== direcao) trocas++;
      direcao = nova;
    }
    return trocas;
  }

  return {olhar, reiniciar(){ aprendido = 0; historico.length = 0; picoDeArea = 0; }};
}


  const OLHO = criarOlho();
  let CAMERA = null, TRILHA_DE_VIDEO = null, RELOGIO_DO_OLHO = null;
  let VIDEO = null, ESPELHO = null, ULTIMO_GESTO = 0, MAO = null;

  function dizerGesto(texto) { Z.$("dicaGesto").textContent = texto; }

  async function alternarCamera() {
    if (CAMERA) { desligarCamera("Desligado. O vídeo nunca sai deste navegador."); return; }
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
      dizerGesto("Este navegador não dá acesso à câmera em origem insegura. Abra por https.");
      return;
    }
    try {
      TRILHA_DE_VIDEO = await navigator.mediaDevices.getUserMedia({
        video: {width: 320, height: 240, facingMode: "user"}, audio: false});
    } catch (e) {
      dizerGesto("A câmera não foi liberada. Sem ela, nada de gestos — e nada mudou.");
      return;
    }
    VIDEO = document.createElement("video");
    VIDEO.playsInline = true; VIDEO.muted = true; VIDEO.srcObject = TRILHA_DE_VIDEO;
    await VIDEO.play().catch(() => {});
    ESPELHO = document.createElement("canvas");
    ESPELHO.width = OLHO_L; ESPELHO.height = OLHO_A;
    CAMERA = true;
    OLHO.reiniciar();
    Z.$("ligarCamera").setAttribute("aria-pressed", "true");
    Z.$("ligarCamera").textContent = "Desligar gestos";
    Z.$("luzDaCamera").hidden = false;
    Z.$("olho").hidden = false;
    dizerGesto("Aprendendo o fundo. Fique parado um instante.");
    RELOGIO_DO_OLHO = setInterval(umQuadro, Math.round(1000 / QUADROS_POR_SEGUNDO));
  }

  function desligarCamera(motivo) {
    clearInterval(RELOGIO_DO_OLHO); RELOGIO_DO_OLHO = null;
    if (TRILHA_DE_VIDEO) TRILHA_DE_VIDEO.getTracks().forEach((t) => t.stop());
    TRILHA_DE_VIDEO = null; CAMERA = null; VIDEO = null; MAO = null;
    Z.$("ligarCamera").setAttribute("aria-pressed", "false");
    Z.$("ligarCamera").textContent = "Ligar gestos";
    Z.$("luzDaCamera").hidden = true;
    Z.$("olho").hidden = true;
    dizerGesto(motivo || "Desligado. O vídeo nunca sai deste navegador.");
  }

  function umQuadro() {
    if (!CAMERA || !VIDEO || VIDEO.readyState < 2) return;
    const ctx = ESPELHO.getContext("2d", {willReadFrequently: true});
    ctx.drawImage(VIDEO, 0, 0, OLHO_L, OLHO_A);
    const quadro = ctx.getImageData(0, 0, OLHO_L, OLHO_A);
    const visto = OLHO.olhar(quadro.data);
    desenharOlho(quadro, visto);
    aplicarGesto(visto);
  }

  function desenharOlho(quadro, visto) {
    const tela = Z.$("olho").getContext("2d");
    tela.putImageData(quadro, 0, 0);
    tela.fillStyle = "rgba(7,8,12,.45)";
    tela.fillRect(0, 0, OLHO_L, OLHO_A);
    if (visto && visto.presente) {
      tela.strokeStyle = visto.acenando ? "#9580ff" : "#5cb0ff";
      tela.lineWidth = 2;
      tela.beginPath(); tela.arc((1 - visto.x) * OLHO_L, visto.y * OLHO_A, 12 + 10 * Math.min(1, visto.abertura), 0, Math.PI * 2);
      tela.stroke();
    }
  }

  /* Os gestos só mexem no que é reversível e visível. Nenhum deles manda
     mensagem, liga microfone, executa ferramenta ou abre coisa. */
  function aplicarGesto(visto) {
    if (!visto || visto.aprendendo) return;
    if (!visto.presente) { if (MAO) { MAO = null; dizerGesto("Mão fora de vista."); } return; }
    const agora = performance.now();
    const primeiro = !MAO;
    MAO = visto;
    if (visto.acenando && agora - ULTIMO_GESTO > 1500) {
      ULTIMO_GESTO = agora;
      Z.irPara("conversa");
      Z.$("texto").focus();
      dizerGesto("Aceno: campo de conversa em foco. O microfone continua desligado.");
      return;
    }
    if (primeiro) { dizerGesto("Mão à vista. Acene para pôr o foco na conversa."); return; }
    dizerGesto("Mancha em " + Math.round(visto.x * 100) + "%, " + Math.round(visto.y * 100) + "% (presença, não dedos).");
  }

  Z.gestos = {ligar() { Z.$("ligarCamera").onclick = alternarCamera; }};
  // Aba escondida com a câmera ligada é o que ninguém quer ver.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && CAMERA) desligarCamera("Câmera desligada ao sair da aba.");
  });
  window.addEventListener("pagehide", () => { if (CAMERA) desligarCamera(); });
})(window.Z);
