/* Voz na Central: segurar para falar, forma de onda real e um só tocador.

   - Segurar o botão (ou Ctrl+Espaço) grava; soltar envia. Arrastar 60 px para
     fora, ou soltar antes de 300 ms, cancela. Funciona com dedo e mouse
     (Pointer Events com captura).
   - A onda vem do AnalyserNode do próprio microfone; enquanto o Zeus fala, a do
     áudio dele. Nada é desenhado sem som de verdade.
   - Tocador único (ideia do useTts do OpenJarvis): uma fala nova para a anterior,
     e uma resposta que chega fora de ordem é descartada.
   O microfone exige https; sem ele, o botão diz o porquê em vez de sumir. */
import {Z, $, novoId, pedir, brinde, anunciar} from "./base.js";
import {mudarEstado, definirNivel} from "./orbe.js";

let gravador = null, trilha = null, pedacos = [], inicio = 0, cancelado = false;
let contexto = null, analisador = null, onda = null, quadroOnda = 0;
let audio = null, fichaAudio = 0;

export function podeGravar() {
  return !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
}
export function motivoSemMicrofone() {
  if (!window.isSecureContext) return "O microfone só funciona em https (endereço com cadeado).";
  if (!window.MediaRecorder) return "Este navegador não grava áudio.";
  return "";
}

function desenharOnda() {
  if (!onda || !analisador) return;
  const ctx = onda.getContext("2d");
  const dados = new Uint8Array(analisador.fftSize);
  analisador.getByteTimeDomainData(dados);
  const w = onda.width, h = onda.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue("--violeta") || "#9a86ff";
  ctx.lineWidth = 2 * devicePixelRatio;
  ctx.beginPath();
  let soma = 0;
  for (let i = 0; i < dados.length; i++) {
    const v = (dados[i] - 128) / 128;
    soma += v * v;
    const x = (i / (dados.length - 1)) * w, y = h / 2 + v * h * 0.45;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.stroke();
  definirNivel(Math.sqrt(soma / dados.length) * 3);
  quadroOnda = requestAnimationFrame(desenharOnda);
}

function prepararOnda(fonteDeAudio) {
  onda = $("onda");
  if (!onda) return;
  onda.width = onda.clientWidth * devicePixelRatio;
  onda.height = onda.clientHeight * devicePixelRatio;
  contexto = contexto || new AudioContext();
  analisador = contexto.createAnalyser();
  analisador.fftSize = 1024;
  fonteDeAudio.connect(analisador);
  cancelAnimationFrame(quadroOnda);
  desenharOnda();
}

function pararOnda() {
  cancelAnimationFrame(quadroOnda);
  analisador = null;
  definirNivel(0);
  if (onda) onda.getContext("2d").clearRect(0, 0, onda.width, onda.height);
}

export async function comecar() {
  if (gravador) return;
  if (!podeGravar()) { brinde(motivoSemMicrofone()); return; }
  parar();
  cancelado = false;
  try {
    trilha = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true,
                                                                 autoGainControl: true, channelCount: 1}});
  } catch (erro) {
    const negado = erro && (erro.name === "NotAllowedError" || erro.name === "SecurityError");
    brinde(negado ? "O navegador não liberou o microfone. Libere nas permissões do site." : "Nenhum microfone neste aparelho.");
    return;
  }
  gravador = new MediaRecorder(trilha, MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? {mimeType: "audio/webm;codecs=opus"} : {});
  pedacos = [];
  gravador.ondataavailable = (e) => { if (e.data && e.data.size) pedacos.push(e.data); };
  gravador.onstop = enviar;
  gravador.start();
  inicio = performance.now();
  const botao = $("falar");
  if (botao) botao.setAttribute("aria-pressed", "true");
  mudarEstado("ouvindo", "gravando — solte para enviar");
  contexto = contexto || new AudioContext();
  prepararOnda(contexto.createMediaStreamSource(trilha));
  setTimeout(() => { if (gravador && gravador.state === "recording") terminar(); }, 60000);
}

export function terminar(cancelar = false) {
  if (!gravador || gravador.state !== "recording") return;
  cancelado = cancelar || performance.now() - inicio < 300;
  gravador.stop();
}

async function enviar() {
  trilha.getTracks().forEach((t) => t.stop());
  const tipo = gravador.mimeType || "audio/webm";
  gravador = null;
  pararOnda();
  const botao = $("falar");
  if (botao) botao.setAttribute("aria-pressed", "false");
  if (cancelado) { mudarEstado("dormindo"); anunciar("Gravação cancelada"); return; }
  const blob = new Blob(pedacos, {type: tipo});
  if (blob.size < 1200) { mudarEstado("dormindo"); brinde("Áudio curto demais; nada foi enviado."); return; }
  mudarEstado("pensando", "transcrevendo");
  const r = await pedir("escuta", {bruto: blob, cabecalhos: {"Content-Type": tipo, "X-Zeus-Turno": novoId()}});
  if (!r.ok) { mudarEstado("erro", (r.corpo && r.corpo.erro) || "o áudio não chegou"); brinde((r.corpo && r.corpo.erro) || "O áudio não chegou ao Zeus."); }
}

/* Liga o botão de segurar e o Ctrl+Espaço. */
export function ligarBotao(botao) {
  let origem = null;
  botao.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    botao.setPointerCapture(e.pointerId);
    origem = {x: e.clientX, y: e.clientY};
    comecar();
  });
  botao.addEventListener("pointermove", (e) => {
    if (!origem || !gravador) return;
    const longe = Math.hypot(e.clientX - origem.x, e.clientY - origem.y) > 60;
    Z.definir("detalhe", longe ? "solte para cancelar" : "gravando — solte para enviar");
  });
  botao.addEventListener("pointerup", (e) => {
    const longe = origem && Math.hypot(e.clientX - origem.x, e.clientY - origem.y) > 60;
    origem = null;
    terminar(longe);
  });
  botao.addEventListener("pointercancel", () => { origem = null; terminar(true); });
}

let espacoSegurado = false;
addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.ctrlKey && !e.repeat && !espacoSegurado) {
    e.preventDefault();
    espacoSegurado = true;
    comecar();
  }
});
addEventListener("keyup", (e) => {
  if (espacoSegurado && (e.code === "Space" || e.key === "Control")) { espacoSegurado = false; terminar(); }
});

/* ------------------------------------------------------------ tocador único */
export function tocar(url) {
  parar();
  const minha = ++fichaAudio;
  audio = new Audio(url);
  audio.onplay = () => {
    if (minha !== fichaAudio) return;
    mudarEstado("falando");
    try {
      contexto = contexto || new AudioContext();
      prepararOnda(contexto.createMediaElementSource(audio));
      analisador.connect(contexto.destination);
    } catch (e) { /* sem onda; o som sai do mesmo jeito */ }
  };
  audio.onended = () => { if (minha === fichaAudio) { pararOnda(); mudarEstado("dormindo"); } };
  audio.onerror = () => { if (minha === fichaAudio) { pararOnda(); mudarEstado("dormindo"); } };
  audio.play().catch(() => { if (minha === fichaAudio) brinde("O navegador bloqueou o som; toque na página e tente de novo."); });
}
export function parar() {
  fichaAudio++;
  if (audio) { audio.onerror = null; audio.pause(); audio.removeAttribute("src"); audio = null; }
  pararOnda();
}
export const tocando = () => !!audio && !audio.paused;

/* Áudio do Zeus vem com caminho da HUD clássica; a Central serve pelo dela. */
export function urlDoAudio(caminho) {
  const nome = String(caminho || "").split("/").pop();
  return nome ? `/central/api/audio/${encodeURIComponent(nome)}` : "";
}
