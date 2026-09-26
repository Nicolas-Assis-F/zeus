"use strict";
/* O orbe representa a interação, e só ela: pronto, capturando áudio,
   transcrevendo, preparando resposta, executando, escrevendo, falando,
   erro ou sem conexão. CPU e temperatura não mudam o que "ouvindo"
   significa — a saúde da máquina mora no Diagnóstico. */
(function (Z) {
  const CORES = {
    pronto:       ["#5cb0ff", "#9580ff", 0.55],
    capturando:   ["#9580ff", "#ff8ad8", 1.4],
    transcrevendo:["#9580ff", "#5cb0ff", 1.1],
    preparando:   ["#5cb0ff", "#eaf4ff", 1.6],
    executando:   ["#ffbe66", "#5cb0ff", 1.5],
    escrevendo:   ["#5cb0ff", "#eaf4ff", 1.9],
    falando:      ["#eaf4ff", "#5cb0ff", 1.35],
    erro:         ["#ff8a8a", "#9580ff", 0.6],
    sem_conexao:  ["#3a4257", "#2a3040", 0.25],
  };
  const telas = [];

  function desenhar(tela, estado, parado) {
    const ctx = tela.getContext("2d");
    const lado = tela.width, r = lado / 2;
    const t = parado ? 0 : performance.now() / 1000;
    const [a, b, ritmo] = CORES[estado] || CORES.pronto;
    ctx.clearRect(0, 0, lado, lado);
    const pulso = 1 + (parado ? 0 : 0.06 * Math.sin(t * ritmo * 2.2));
    const halo = ctx.createRadialGradient(r, r, r * 0.12, r, r, r * 0.95 * pulso);
    halo.addColorStop(0, a); halo.addColorStop(0.45, b); halo.addColorStop(1, "rgba(7,8,12,0)");
    ctx.globalAlpha = 0.5; ctx.fillStyle = halo;
    ctx.beginPath(); ctx.arc(r, r, r * 0.95 * pulso, 0, Math.PI * 2); ctx.fill();
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
    nucleo.addColorStop(0, "#ffffff"); nucleo.addColorStop(0.5, a); nucleo.addColorStop(1, "rgba(7,8,12,0)");
    ctx.globalAlpha = 1; ctx.fillStyle = nucleo;
    ctx.beginPath(); ctx.arc(r, r, r * 0.3 * pulso, 0, Math.PI * 2); ctx.fill();
  }

  function visivel(tela) {
    return tela.offsetParent !== null || tela.id === "orbePorta" && !Z.$("porta").hidden;
  }

  function quadro() {
    const parado = Z.movimentoReduzido() || document.hidden;
    for (const tela of telas) if (visivel(tela)) desenhar(tela, Z.estado.interacao, parado);
    // Sem movimento contínuo, só redesenha quando o estado muda.
    if (!parado) requestAnimationFrame(quadro);
  }

  Z.orbe = {
    registrar(...ids) { for (const id of ids) { const t = Z.$(id); if (t) telas.push(t); } },
    iniciar() { quadro(); },
    redesenhar() { if (Z.movimentoReduzido() || document.hidden) quadro(); },
  };
  Z.on("mudou:interacao", () => Z.orbe.redesenhar());
  document.addEventListener("visibilitychange", () => { if (!document.hidden) quadro(); });
})(window.Z);
