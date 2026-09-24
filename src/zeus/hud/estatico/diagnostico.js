"use strict";
/* Diagnóstico: a saúde da máquina, as capacidades e as medidas dos turnos.
   Fica fora do caminho da conversa. Só consulta o servidor com a vista
   aberta e a aba visível; em economia, a cada dez segundos. */
(function (Z) {
  let relogio = null;
  const faixaDeCor = (v, aviso, limite) => v === null || v === undefined ? "#5b6478"
    : v >= limite ? "#ff8a8a" : v >= aviso ? "#ffbe66" : "#5cb0ff";

  function ajustarTela(tela) {
    const r = tela.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const L = Math.round(r.width * dpr), A = Math.round(r.height * dpr);
    if (tela.width !== L || tela.height !== A) { tela.width = L; tela.height = A; }
    return {L, A, escala: dpr};
  }

  function anel(tela, valor, rotulo, cor) {
    const ctx = tela.getContext("2d"), L = tela.width, A = tela.height;
    const cx = L / 2, cy = A * 0.86, r = Math.min(L / 2, A) * 0.78;
    ctx.clearRect(0, 0, L, A);
    ctx.lineWidth = r * 0.22; ctx.lineCap = "round"; ctx.strokeStyle = "#161c2a";
    ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 0); ctx.stroke();
    if (valor !== null && valor !== undefined && !isNaN(valor)) {
      ctx.strokeStyle = cor;
      ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI + Math.PI * Math.min(1, valor / 100)); ctx.stroke();
    }
    ctx.fillStyle = "#e8edf7"; ctx.textAlign = "center";
    ctx.font = "600 " + Math.round(r * 0.52) + "px ui-sans-serif,system-ui,sans-serif";
    ctx.fillText(rotulo, cx, cy - r * 0.08);
  }

  function faixa(tela, series) {
    const caixa = ajustarTela(tela); if (!caixa) return;
    const ctx = tela.getContext("2d"), {L, A, escala} = caixa;
    ctx.clearRect(0, 0, L, A);
    ctx.strokeStyle = "#161c2a"; ctx.lineWidth = escala;
    for (const y of [A * 0.25, A * 0.5, A * 0.75]) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(L, y); ctx.stroke(); }
    for (const {dados, cor} of series) {
      if (!dados || dados.filter((v) => v !== null && v !== undefined).length < 2) continue;
      const passo = L / Math.max(1, dados.length - 1);
      ctx.beginPath(); let iniciou = false;
      dados.forEach((v, i) => {
        if (v === null || v === undefined) return;
        const x = i * passo, y = A - (Math.min(100, Math.max(0, v)) / 100) * (A - 3) - 1.5;
        if (iniciou) ctx.lineTo(x, y); else { ctx.moveTo(x, y); iniciou = true; }
      });
      ctx.strokeStyle = cor; ctx.lineWidth = 1.4 * escala; ctx.stroke();
    }
  }

  function barra(id, valor, aviso, limite) {
    const b = Z.$(id);
    b.style.width = (valor || 0) + "%";
    b.style.background = faixaDeCor(valor, aviso, limite);
  }

  function pintarSaude(s) {
    const f = Z.fmt, cpu = s.cpu || {}, mem = s.memoria || {}, placa = (s.gpu || [])[0];
    anel(Z.$("anelCpu"), cpu.uso, f.porcento(cpu.uso), faixaDeCor(cpu.uso, 75, 92));
    Z.$("subCpu").textContent = [cpu.mhz ? Math.round(cpu.mhz) + " MHz" : null,
                                  cpu.celsius ? cpu.celsius + " °C" : null].filter(Boolean).join(" · ")
                                 || (cpu.nucleos ? cpu.nucleos + " núcleos" : f.NADA);
    anel(Z.$("anelGpu"), placa ? placa.uso : null, placa ? f.porcento(placa.uso) : f.NADA,
         faixaDeCor(placa ? placa.uso : null, 80, 95));
    Z.$("subGpu").textContent = placa ? (placa.nome || "GPU") : "sem placa NVIDIA";
    const caixa = Z.$("nucleos"), nucleos = cpu.por_nucleo || [];
    if (caixa.childElementCount !== nucleos.length) {
      caixa.textContent = "";
      nucleos.forEach(() => caixa.appendChild(document.createElement("i")));
    }
    nucleos.forEach((v, i) => {
      caixa.children[i].style.height = Math.max(6, v || 0) + "%";
      caixa.children[i].style.background = faixaDeCor(v, 75, 92);
    });
    const h = s.historico || {};
    faixa(Z.$("faixaCpu"), [{dados: h.cpu, cor: "#5cb0ff"}, {dados: h.memoria, cor: "#9580ff"},
                            {dados: h.gpu, cor: "#4fdca2"}]);
    const carga = (cpu.carga || [])[0];
    Z.$("obsCpu").textContent = [cpu.modelo || null, carga !== undefined ? "carga " + carga.toFixed(2) : null,
                                 "linhas: CPU azul, memória violeta, GPU verde"].filter(Boolean).join(" · ");
    Z.$("tempoLigado").textContent = "ligado há " + f.duracao(s.tempo_ligado_s);
    Z.$("valMem").textContent = mem.total ? f.bytes(mem.usada) + " de " + f.bytes(mem.total) + " (" + f.porcento(mem.percentual) + ")" : f.NADA;
    barra("barraMem", mem.percentual, 80, 92);
    Z.$("memSwap").textContent = mem.troca_total ? f.bytes(mem.troca_usada) + " de " + f.bytes(mem.troca_total) : "sem swap";
    Z.$("vram").textContent = placa && placa.memoria_total ? f.bytes(placa.memoria_usada) + " de " + f.bytes(placa.memoria_total) : f.NADA;
    barra("barraVram", placa ? placa.percentual_memoria : null, 85, 95);
    Z.$("gpuTermico").textContent = placa ? [placa.celsius ? placa.celsius + " °C" : null,
      placa.watts ? Math.round(placa.watts) + " W" : null].filter(Boolean).join(" · ") || f.NADA : f.NADA;
    const disco = (s.disco || {}).estado || {};
    Z.$("valDisco").textContent = disco.livre ? f.bytes(disco.livre) + " livres (" + f.porcento(disco.percentual) + " usado)" : f.NADA;
    barra("barraDisco", disco.percentual, 85, 94);
    const rede = s.rede || {};
    Z.$("rede").textContent = rede.entrada === null || rede.entrada === undefined ? f.NADA
      : "↓ " + f.bytes(rede.entrada) + "/s  ↑ " + f.bytes(rede.saida) + "/s";
    const proc = s.processo || {};
    Z.$("processo").textContent = proc.memoria ? f.bytes(proc.memoria) + " · " + proc.threads + " threads" : f.NADA;
    Z.$("obsSaude").textContent = "Atualizado " + new Date().toLocaleTimeString("pt-BR");
  }

  async function lerSaude() {
    const r = await Z.api.saude();
    if (r.ok && r.corpo) pintarSaude(r.corpo);
    else Z.$("obsSaude").textContent = "Sem dados de saúde agora" + (r.rede ? " (sem conexão)" : r.status ? " (erro " + r.status + ")" : "")
                                       + ". Os últimos valores continuam na tela.";
  }

  /* -------------------------------------------------- mapa de capacidades */
  const NOS = [["modelo", "modelo"], ["memoria", "memória"], ["voz", "voz"], ["escuta", "escuta"],
               ["telegram", "telegram"], ["hud", "hud"], ["pesquisa", "pesquisa"], ["agenda", "agenda"], ["mapa", "mapa"]];
  function vidaDe(nome) {
    const r = Z.estado.retrato, cap = (r.capacidades || {})[nome];
    if (nome === "hud") return Z.estado.conexao === "conectado" ? "on" : "meia";
    if (nome === "memoria") return (r.fatos || []).length ? "on" : "meia";
    if (nome === "agenda") {
      const op = (Z.estado.operacao || {}).agenda;
      return op && op.estado === "pronta" ? "on" : op ? "meia" : "off";
    }
    if (!cap) return "off";
    return ["pronta", "configurada", "configurado", "ativo"].includes(cap.estado) ? "on"
      : cap.estado === "indisponivel" ? "meia" : "off";
  }
  function desenharCapacidades() {
    const tela = Z.$("mapaCapacidades");
    const caixa = ajustarTela(tela); if (!caixa) return;
    const {L, A, escala} = caixa, ctx = tela.getContext("2d");
    const cx = L / 2, cy = A / 2, rx = L * 0.3, ry = A * 0.34;
    ctx.clearRect(0, 0, L, A);
    let vivos = 0;
    NOS.forEach(([id, rot], i) => {
      const ang = -Math.PI / 2 + i * (Math.PI * 2 / NOS.length);
      const x = cx + Math.cos(ang) * rx, y = cy + Math.sin(ang) * ry, vida = vidaDe(id);
      if (vida === "on") vivos++;
      ctx.strokeStyle = vida === "on" ? "rgba(92,176,255,.5)" : vida === "meia" ? "rgba(255,190,102,.45)" : "rgba(60,70,92,.6)";
      ctx.lineWidth = escala; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke();
      ctx.fillStyle = vida === "on" ? "#5cb0ff" : vida === "meia" ? "#ffbe66" : "#3f4760";
      ctx.beginPath(); ctx.arc(x, y, (vida === "on" ? 5 : 4) * escala, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = vida === "off" ? "#8290a8" : "#dfe6f3";
      ctx.font = Math.round(12 * escala) + "px ui-sans-serif,system-ui,sans-serif";
      ctx.textAlign = x < cx - 6 ? "right" : x > cx + 6 ? "left" : "center";
      ctx.textBaseline = y < cy ? "bottom" : "top";
      ctx.fillText(rot, x + (x < cx - 6 ? -10 : x > cx + 6 ? 10 : 0) * escala, y + (y < cy ? -8 : 8) * escala);
    });
    ctx.fillStyle = "#eaf4ff"; ctx.beginPath(); ctx.arc(cx, cy, 8 * escala, 0, Math.PI * 2); ctx.fill();
    Z.$("contaMapa").textContent = vivos + " de " + NOS.length + " ativos";
  }

  function pintarCapacidades() {
    desenharCapacidades();
    const lista = Z.$("listaCapacidades");
    lista.textContent = "";
    for (const [nome, info] of Object.entries(Z.estado.retrato.capacidades || {})) {
      const motivo = info.motivo && info.motivo !== info.estado ? info.motivo : "";
      lista.appendChild(Z.el("li", {}, Z.sinalDeCapacidade(nome, info),
                             Z.el("span", {class: "o-que", texto: motivo})));
    }
    const op = Z.$("listaOperacao");
    op.textContent = "";
    const operacao = Z.estado.operacao || {};
    for (const [nome, info] of Object.entries(operacao)) {
      op.appendChild(Z.el("li", {}, Z.el("span", {class: "quando", texto: nome.replaceAll("_", " ")}),
        Z.el("span", {class: "o-que", texto: (info.estado || "—") + (info.ciclos ? " · " + info.ciclos + " ciclos" : "")
                                             + (info.atualizado_em ? " · " + Z.fmt.hora(info.atualizado_em) : "")})));
    }
    if (!op.childElementCount) op.appendChild(Z.el("li", {class: "vazio", texto: "Aguardando o supervisor."}));
  }

  /* -------------------------------------------------------------- medidas */
  function celula(valor, motivo, formatar) {
    const texto = valor === null || valor === undefined ? Z.fmt.NADA : (formatar ? formatar(valor) : String(valor));
    return Z.el("td", {class: "num", texto, title: valor === null || valor === undefined ? (motivo || "não medido") : null});
  }
  async function lerMedidas() {
    const r = await Z.api.diagnostico();
    const corpo = Z.$("tabelaMedidas");
    corpo.textContent = "";
    if (!r.ok || !r.corpo) {
      corpo.appendChild(Z.el("tr", {}, Z.el("td", {colspan: "9", texto: "Medidas indisponíveis agora."})));
      return;
    }
    Z.$("obsMedidas").textContent = r.corpo.gravando ? "também gravadas em disco" : "só em memória (telemetria_arquivo desligada)";
    const turnos = (r.corpo.turnos || []).slice().reverse();
    if (!turnos.length) {
      corpo.appendChild(Z.el("tr", {}, Z.el("td", {colspan: "9", texto: "Nenhum turno medido desde que o Zeus subiu."})));
      return;
    }
    for (const t of turnos) {
      const ausentes = t.ausentes || {};
      const prompt = (t.rodadas || []).map((rd) => (rd.servidor || []).map((s) => s.prompt_eval_count)
        .filter((v) => v !== null && v !== undefined).reduce((a, b) => a + b, 0)).reduce((a, b) => a + b, 0);
      const temPrompt = (t.rodadas || []).some((rd) => (rd.servidor || []).some((s) => s.prompt_eval_count !== null && s.prompt_eval_count !== undefined));
      corpo.appendChild(Z.el("tr", {},
        Z.el("td", {texto: Z.fmt.hora(t.registrado_em)}), Z.el("td", {texto: t.canal + (t.origem === "voz" ? " (voz)" : "")}),
        Z.el("td", {texto: t.resultado + (t.erro ? " · " + Z.motivoLegivel(t.erro) : "")}),
        celula(t.espera_fila_ms, ausentes.espera_fila_ms, Z.fmt.segundos),
        celula(t.contexto_ms, null, Z.fmt.segundos),
        celula((t.rodadas || []).length),
        celula(temPrompt ? prompt : null, "o provedor não informou", (v) => v + " tokens"),
        celula(t.primeiro_fragmento_final_ms, ausentes.primeiro_fragmento_final_ms, Z.fmt.segundos),
        celula(t.total_ms, null, Z.fmt.segundos)));
    }
  }

  Z.diagnostico = {
    abrir() {
      pintarCapacidades();
      lerSaude(); lerMedidas();
      clearInterval(relogio);
      relogio = setInterval(() => {
        if (!document.hidden && Z.estado.vista === "diagnostico") lerSaude();
      }, document.body.classList.contains("economia") ? 10000 : 2000);
    },
    fechar() { clearInterval(relogio); relogio = null; },
    pintarCapacidades,
    lerMedidas,
  };

  Z.on("retrato", () => { if (Z.estado.vista === "diagnostico") pintarCapacidades(); });
  Z.on("evento:turno", (p) => {
    if (Z.estado.vista === "diagnostico" && ["concluida", "falhou", "interrompida"].includes(p.etapa)) lerMedidas();
  });
})(window.Z);
