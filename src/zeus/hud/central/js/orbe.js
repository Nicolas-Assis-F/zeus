/* O orbe é a presença do Zeus, e mostra uma coisa só: o que ele está fazendo
   com você agora. Desenho herdado da HUD v1 (#44), com os estados da fase 2.
   Movimento só quando a aba está visível e o usuário não pediu menos movimento;
   o nível de voz entra por `nivel` (0..1) enquanto ele fala ou ouve. */
import {Z, $, movimentoReduzido} from "./base.js";

const CORES = {
  dormindo: ["#1d6f86", "#4a3f99", 0.35],
  ouvindo:  ["#9a86ff", "#ff8ad8", 1.4],
  pensando: ["#33d3f0", "#eafcff", 1.7],
  agindo:   ["#ffbe66", "#33d3f0", 1.5],
  falando:  ["#eafcff", "#33d3f0", 1.3],
  erro:     ["#ff8f8f", "#9a86ff", 0.6],
  offline:  ["#344052", "#252c38", 0.2],
};
export const ROTULOS = {dormindo: "Pronto", ouvindo: "Ouvindo", pensando: "Pensando", agindo: "Agindo",
                        falando: "Falando", erro: "Erro", offline: "Sem conexão"};
const telas = new Set();
let nivel = 0, rodando = false;

function desenhar(tela, estado, parado) {
  const ctx = tela.getContext("2d");
  const lado = tela.width, r = lado / 2;
  const t = parado ? 0 : performance.now() / 1000;
  const [a, b, ritmo] = CORES[estado] || CORES.dormindo;
  ctx.clearRect(0, 0, lado, lado);
  const pulso = 1 + (parado ? 0 : 0.05 * Math.sin(t * ritmo * 2.2)) + nivel * 0.14;
  const halo = ctx.createRadialGradient(r, r, r * 0.12, r, r, r * 0.95 * Math.min(pulso, 1.05));
  halo.addColorStop(0, a); halo.addColorStop(0.45, b); halo.addColorStop(1, "rgba(6,10,16,0)");
  ctx.globalAlpha = 0.5; ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(r, r, r * 0.95 * Math.min(pulso, 1.05), 0, Math.PI * 2); ctx.fill();
  ctx.globalAlpha = 0.85;
  for (let i = 0; i < 3; i++) {
    const fase = t * ritmo * (0.5 + i * 0.35) + i * 2.1;
    const raio = r * (0.32 + i * 0.14);
    ctx.beginPath();
    ctx.strokeStyle = i % 2 ? b : a;
    ctx.lineWidth = Math.max(1, lado / 110);
    ctx.ellipse(r, r, raio, raio * (0.35 + 0.28 * Math.abs(Math.sin(fase))), fase, 0, Math.PI * 2);
    ctx.stroke();
  }
  const nucleo = ctx.createRadialGradient(r, r, 0, r, r, r * 0.3 * pulso);
  nucleo.addColorStop(0, "#ffffff"); nucleo.addColorStop(0.5, a); nucleo.addColorStop(1, "rgba(6,10,16,0)");
  ctx.globalAlpha = 1; ctx.fillStyle = nucleo;
  ctx.beginPath(); ctx.arc(r, r, r * 0.3 * pulso, 0, Math.PI * 2); ctx.fill();
}

function quadro() {
  const parado = movimentoReduzido() || document.hidden;
  for (const tela of telas) {
    if (!tela.isConnected) { telas.delete(tela); continue; }
    if (tela.offsetParent !== null) desenhar(tela, Z.estado.orbe, parado);
  }
  rodando = !parado;
  if (rodando) requestAnimationFrame(quadro);
}

export function registrar(tela) {
  if (!tela) return;
  telas.add(tela);
  if (!rodando) quadro();
}
export function definirNivel(valor) { nivel = Math.max(0, Math.min(1, valor)); }
export function mudarEstado(estado, detalhe = "") {
  Z.definir("detalhe", detalhe);
  Z.definir("orbe", estado);
  document.body.dataset.orbe = estado;
  if (!rodando) quadro();
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && !rodando) quadro(); });
registrar($("orbeTopo"));
