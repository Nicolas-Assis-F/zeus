"use strict";
/* Mapa de localização, escrito à mão (sem biblioteca, que viria de CDN).
   As telas vêm do próprio Zeus, pela sessão; nunca do servidor público. */
(function (Z) {
const LADO_DA_TELA = 256;

function criarMapa(elemento, aoMover){
  const estado = {lat: -16.6869, lon: -49.2648, zoom: 13, zoomMaximo: 19,
                  pinos: [], vivo: false, aviso: ""};
  const imagens = new Map();
  let arrastando = null;

  function paraTela(lat, lon, zoom){
    const n = Math.pow(2, zoom);
    const limitada = Math.max(-85.05112878, Math.min(85.05112878, lat));
    const rad = limitada * Math.PI / 180;
    return {x: (lon + 180) / 360 * n,
            y: (1 - Math.asinh(Math.tan(rad)) / Math.PI) / 2 * n};
  }
  function deTela(x, y, zoom){
    const n = Math.pow(2, zoom);
    return {lat: Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI,
            lon: x / n * 360 - 180};
  }

  function desenhar(){
    const L = elemento.clientWidth, A = elemento.clientHeight;
    if (!L || !A) return;
    if (estado.aviso){
      elemento.textContent = "";
      elemento.appendChild(Z.el("div", {class: "aviso", texto: estado.aviso}));
      return;
    }
    const centro = paraTela(estado.lat, estado.lon, estado.zoom);
    const meio = {x: L/2, y: A/2};
    const primeiroX = Math.floor(centro.x - meio.x / LADO_DA_TELA);
    const primeiroY = Math.floor(centro.y - meio.y / LADO_DA_TELA);
    const ultimoX = Math.floor(centro.x + meio.x / LADO_DA_TELA);
    const ultimoY = Math.floor(centro.y + meio.y / LADO_DA_TELA);
    const limite = Math.pow(2, estado.zoom);
    const usadas = new Set();
    for (let tx = primeiroX; tx <= ultimoX; tx++){
      for (let ty = primeiroY; ty <= ultimoY; ty++){
        if (ty < 0 || ty >= limite) continue;
        const enrolado = ((tx % limite) + limite) % limite;   // o mundo dá a volta
        const chave = estado.zoom + "/" + enrolado + "/" + ty;
        usadas.add(chave + "@" + tx);
        let img = imagens.get(chave + "@" + tx);
        if (!img){
          img = document.createElement("img");
          img.loading = "lazy"; img.alt = "";
          img.src = "/mapa/tela/" + chave + ".png";
          img.onerror = () => { img.style.visibility = "hidden"; };
          elemento.appendChild(img);
          imagens.set(chave + "@" + tx, img);
        }
        img.style.left = Math.round(meio.x + (tx - centro.x) * LADO_DA_TELA) + "px";
        img.style.top  = Math.round(meio.y + (ty - centro.y) * LADO_DA_TELA) + "px";
      }
    }
    for (const [chave, img] of imagens){
      if (!usadas.has(chave)){ img.remove(); imagens.delete(chave); }
    }
    for (const antigo of elemento.querySelectorAll(".pino,.rotuloPino,.credito")) antigo.remove();
    for (const pino of estado.pinos){
      const p = paraTela(pino.lat, pino.lon, estado.zoom);
      const x = meio.x + (p.x - centro.x) * LADO_DA_TELA;
      const y = meio.y + (p.y - centro.y) * LADO_DA_TELA;
      if (x < -40 || y < -40 || x > L + 40 || y > A + 40) continue;
      const marca = document.createElement("div");
      marca.className = "pino" + (pino.casa ? " casa" : "");
      marca.style.left = x + "px"; marca.style.top = y + "px";
      marca.title = pino.nome || "";
      elemento.appendChild(marca);
      if (pino.nome && L > 320){
        const rotulo = document.createElement("div");
        rotulo.className = "rotuloPino";
        rotulo.textContent = pino.nome.split(",").slice(0, 2).join(",");
        rotulo.style.left = x + "px"; rotulo.style.top = y + "px";
        elemento.appendChild(rotulo);
      }
    }
    const credito = document.createElement("div");
    credito.className = "credito";
    credito.textContent = "© OpenStreetMap";
    elemento.appendChild(credito);
    if (aoMover) aoMover(estado);
  }

  elemento.addEventListener("pointerdown", (e) => {
    arrastando = {x: e.clientX, y: e.clientY};
    elemento.classList.add("arrastando");
    elemento.setPointerCapture(e.pointerId);
  });
  elemento.addEventListener("pointermove", (e) => {
    if (!arrastando) return;
    const dx = e.clientX - arrastando.x, dy = e.clientY - arrastando.y;
    arrastando = {x: e.clientX, y: e.clientY};
    const centro = paraTela(estado.lat, estado.lon, estado.zoom);
    const novo = deTela(centro.x - dx / LADO_DA_TELA, centro.y - dy / LADO_DA_TELA, estado.zoom);
    estado.lat = novo.lat; estado.lon = novo.lon;
    desenhar();
  });
  const soltar = (e) => { arrastando = null; elemento.classList.remove("arrastando"); };
  elemento.addEventListener("pointerup", soltar);
  elemento.addEventListener("pointercancel", soltar);
  elemento.addEventListener("wheel", (e) => {
    e.preventDefault();
    const passo = e.deltaY < 0 ? 1 : -1;
    const alvo = Math.max(2, Math.min(estado.zoomMaximo, estado.zoom + passo));
    if (alvo === estado.zoom) return;
    estado.zoom = alvo;
    for (const img of imagens.values()) img.remove();
    imagens.clear();
    desenhar();
  }, {passive: false});

  return {
    estado,
    desenhar,
    ir(lat, lon, zoom){
      estado.lat = lat; estado.lon = lon;
      if (zoom) estado.zoom = zoom;
      for (const img of imagens.values()) img.remove();
      imagens.clear();
      desenhar();
    },
    marcar(pinos){ estado.pinos = pinos || []; desenhar(); },
    avisar(texto){
      estado.aviso = texto || "";
      if (texto){ elemento.textContent = ""; imagens.clear(); }
      desenhar();
    },
  };
}


  let mapaLocal = null, pinos = [], iniciado = false;

  Z.mapa = {
    async ligar() {
      if (iniciado) { if (mapaLocal) mapaLocal.desenhar(); return; }
      iniciado = true;
      mapaLocal = criarMapa(Z.$("telaLocal"));
      const r = await Z.api.mapa();
      if (r.status === 503) { mapaLocal.avisar("Mapa desligado. Ligue mapa_ativo na configuração."); return; }
      if (!r.ok || !r.corpo) { mapaLocal.avisar(r.rede ? "Sem conexão com o Zeus agora." : "Não consegui falar com o mapa do Zeus."); iniciado = false; return; }
      const inicio = r.corpo;
      if (!inicio.ativo) { mapaLocal.avisar(inicio.situacao || "mapa desligado"); return; }
      mapaLocal.estado.zoomMaximo = inicio.zoom_maximo || 19;
      pinos = [{lat: inicio.lat, lon: inicio.lon, nome: "aqui", casa: true}];
      mapaLocal.marcar(pinos);
      mapaLocal.ir(inicio.lat, inicio.lon, inicio.zoom);
    },
    marcar(lugares) {
      if (!lugares || !lugares.length) return;
      Z.painel.aba("mapa");
      Z.mapa.ligar().then(() => {
        if (!mapaLocal) return;
        const novos = lugares.map((l) => ({lat: l.lat, lon: l.lon, nome: l.nome}));
        pinos = pinos.filter((p) => p.casa).concat(novos);
        mapaLocal.marcar(pinos);
        mapaLocal.ir(novos[0].lat, novos[0].lon, Math.max(mapaLocal.estado.zoom, 15));
      });
    },
    redesenhar() { if (mapaLocal) mapaLocal.desenhar(); },
  };
  Z.on("evento:lugares", (p) => Z.mapa.marcar(p.lugares));
})(window.Z);
