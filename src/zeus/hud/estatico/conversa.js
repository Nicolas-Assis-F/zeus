"use strict";
/* A conversa: histórico, mensagens com identidade e estado, fluxo da
   resposta e o campo de entrada.

   Uma mensagem enviada passa por estados que vêm do servidor, não de
   suposição: enviando → na fila (HTTP 202 é só isso) → processando →
   concluída, falhou ou interrompida. Reenviar usa o mesmo id, e o servidor
   não duplica. */
(function (Z) {
  const historico = () => Z.$("historico");
  const bolhas = new Map();      // turno -> {nicolas, zeus, meta, texto, fluxo, anunciado}
  let respondendoA = null;       // {id, texto}
  let rascunhoTimer = null;

  const ROTULO_ESTADO = {
    enviando: "enviando…", aceita: "aceita", em_fila: "na fila", processando: "processando",
    concluida: "concluída", falhou: "falhou", interrompida: "interrompida",
  };

  /* ------------------------------------------------------------ rolagem */
  function pertoDoFim() {
    const h = historico();
    return h.scrollHeight - h.scrollTop - h.clientHeight < 90;
  }
  function descer(forcar) {
    const h = historico();
    if (forcar || pertoDoFim()) { h.scrollTop = h.scrollHeight; Z.$("novas").hidden = true; }
    else Z.$("novas").hidden = false;
  }
  function anexar(no, forcar) {
    const estavaNoFim = pertoDoFim();
    const vazio = Z.$("vazioConversa");
    if (vazio) vazio.remove();
    historico().appendChild(no);
    descer(forcar || estavaNoFim);
  }

  /* ------------------------------------------------------------- bolhas */
  function bolha(quem, texto, opcoes) {
    opcoes = opcoes || {};
    const corpo = Z.el("div", {class: "corpo", texto: texto});
    const meta = Z.el("div", {class: "meta"});
    if (opcoes.hora) meta.appendChild(Z.el("span", {texto: opcoes.hora}));
    if (opcoes.via) meta.appendChild(Z.el("span", {texto: opcoes.via}));
    const no = Z.el("div", {class: "fala " + quem + (opcoes.classe ? " " + opcoes.classe : "")}, corpo, meta);
    no._corpo = corpo; no._meta = meta;
    return no;
  }

  function vazio() {
    const tela = Z.el("canvas", {id: "orbeVazio", width: 240, height: 240, "aria-hidden": "true"});
    return Z.el("div", {class: "vazio-conversa", id: "vazioConversa"}, tela,
      Z.el("p", {texto: "Nenhuma conversa ainda. Escreva abaixo, ou use o microfone."}));
  }

  const VIA = {telegram: "via Telegram", saida: "aviso do Zeus", avaliacao: "avaliação", cli: "terminal"};

  Z.conversa = {
    reconstruir(retrato) {
      const h = historico();
      // Bolhas desta página que o banco não sabe descrever: em andamento,
      // interrompidas por um reinício, ou que nem chegaram ao Zeus.
      const emAndamento = [...bolhas.entries()].filter(([, b]) => b.nicolas &&
        (["enviando", "aceita", "em_fila", "processando", "interrompida"].includes(b.estado) || b.falhouEnvio));
      const textosVivos = emAndamento.map(([, b]) => b.texto);
      h.textContent = "";
      const turnos = (retrato && retrato.turnos) || [];
      // O turno em andamento já está no banco; não mostrar duas vezes.
      const pular = new Set();
      for (let i = turnos.length - 1, restantes = [...textosVivos]; i >= 0 && restantes.length; i--) {
        const j = turnos[i].papel === "nicolas" ? restantes.indexOf(turnos[i].texto) : -1;
        if (j >= 0) { pular.add(i); restantes.splice(j, 1); }
      }
      turnos.forEach((t, i) => {
        if (pular.has(i)) return;
        const quem = t.papel === "zeus" ? "zeus" : "nicolas";
        h.appendChild(bolha(quem, t.texto, {hora: Z.fmt.momento(t.em),
                                             via: VIA[t.canal], classe: t.canal === "saida" ? "aviso-zeus" : ""}));
      });
      for (const [, b] of emAndamento) {
        h.appendChild(b.nicolas);
        if (b.zeus) h.appendChild(b.zeus);
      }
      for (const pendente of Z.ler("pendentes", [])) {
        if (!bolhas.has(pendente.id)) Z.conversa.falhaDeEnvio(pendente);
      }
      if (!h.childElementCount) h.appendChild(vazio());
      Z.orbe.registrar("orbeVazio");
      descer(true);
    },

    /* --------------------------------------------------------- envio */
    async enviar(texto, id, responde_a) {
      texto = (texto || "").trim();
      if (!texto) return;
      id = id || Z.novoId();
      let b = bolhas.get(id);
      if (!b) {
        const no = bolha("nicolas", texto, {hora: Z.fmt.hora(new Date().toISOString())});
        b = {nicolas: no, texto, estado: "enviando", responde_a};
        bolhas.set(id, b);
        anexar(no, true);
      }
      b.falhouEnvio = false;
      estadoDaBolha(id, "enviando");
      Z.audio.parar();
      const r = await Z.api.enviar({id, texto, responde_a: responde_a || undefined});
      if (r.ok) {
        removerPendente(id);
        // O rascunho só sai quando o Zeus aceitou — e só se ainda for este
        // texto: o que foi digitado enquanto enviava continua lá.
        if (Z.$("texto").value.trim() === texto) {
          Z.$("texto").value = "";
          Z.guardar("rascunho", "");
          ajustarAltura();
        }
        // O fluxo pode ter chegado antes da resposta do POST: se o servidor já
        // disse "processando" ou "falhou", o 202 ("na fila") não volta atrás.
        if (b.estado === "enviando") estadoDaBolha(id, (r.corpo && r.corpo.estado) || "em_fila");
        Z.estado.ultimoTurnoHud = id;
        return;
      }
      if (r.status === 503) {
        estadoDaBolha(id, "falhou", "fila cheia", true);
      } else if (r.status === 401) {
        estadoDaBolha(id, "falhou", "sessão vencida — entre de novo", true);
      } else if (r.rede || r.status === 0) {
        estadoDaBolha(id, "falhou", "não chegou ao Zeus", true);
      } else {
        estadoDaBolha(id, "falhou", (r.corpo && r.corpo.erro) || ("erro " + r.status), false);
        return;
      }
      guardarPendente({id, texto, responde_a});
      // A mensagem agora vive na bolha, com "Tentar de novo" e o mesmo id. Se
      // continuasse também no campo, um segundo Enter criaria outra mensagem.
      if (Z.$("texto").value.trim() === texto) {
        Z.$("texto").value = "";
        Z.guardar("rascunho", "");
        ajustarAltura();
      }
    },

    falhaDeEnvio(pendente) {
      const no = bolha("nicolas", pendente.texto, {});
      bolhas.set(pendente.id, {nicolas: no, texto: pendente.texto, estado: "falhou",
                               responde_a: pendente.responde_a, falhouEnvio: true});
      anexar(no, false);
      estadoDaBolha(pendente.id, "falhou", "não chegou ao Zeus", true);
    },

    /* ------------------------------------------------------- respostas */
    responderA(pergunta) {
      respondendoA = pergunta;
      Z.$("respostaA").hidden = false;
      Z.$("respostaATexto").textContent = "Respondendo à pergunta #" + pergunta.id + ": " + pergunta.texto;
      Z.irPara("conversa");
      Z.$("texto").focus();
    },
    cancelarResposta() {
      respondendoA = null;
      Z.$("respostaA").hidden = true;
    },

    /* Mensagem de áudio: a bolha nasce com o id do turno e recebe o texto
       quando a transcrição chega. */
    local(id, texto) {
      const no = bolha("nicolas", texto, {hora: Z.fmt.hora(new Date().toISOString())});
      bolhas.set(id, {nicolas: no, texto, estado: "enviando"});
      anexar(no, true);
      estadoDaBolha(id, "enviando");
      Z.estado.ultimoTurnoHud = id;
    },
    marcar(id, estado, motivo) {
      const b = bolhas.get(id);
      // Mesma regra do texto: a resposta do POST não desfaz o que o fluxo já disse.
      if (b && estado === "em_fila" && b.estado !== "enviando") return;
      estadoDaBolha(id, estado, motivo, false);
    },

    marcarInterrompidas() {
      // O servidor reiniciou: o que estava em andamento não vai terminar.
      for (const [id, b] of bolhas) {
        if (["aceita", "em_fila", "processando"].includes(b.estado)) {
          estadoDaBolha(id, "interrompida", "o Zeus reiniciou antes de concluir", false);
          if (b.zeus && b.zeus.classList.contains("fluindo")) {
            // O trecho que chegou fica visível, mas dito como incompleto.
            b.zeus.classList.remove("fluindo");
            b.zeus._meta.textContent = "";
            b.zeus._meta.appendChild(Z.el("span", {class: "estado-msg interrompida",
                                                   texto: "resposta incompleta: o Zeus reiniciou no meio"}));
          }
        }
      }
    },
  };

  function estadoDaBolha(id, estado, motivo, podeRepetir) {
    const b = bolhas.get(id);
    if (!b) return;
    b.estado = estado;
    b.falhouEnvio = !!podeRepetir && estado === "falhou";
    const meta = b.nicolas._meta;
    meta.querySelectorAll(".estado-msg, .repetir").forEach((n) => n.remove());
    meta.appendChild(Z.el("span", {class: "estado-msg " + estado,
                                   texto: ROTULO_ESTADO[estado] + (motivo ? ": " + motivo : "")}));
    if (b.falhouEnvio) {
      meta.appendChild(Z.el("button", {type: "button", class: "botao pequeno repetir",
        onclick: () => Z.conversa.enviar(b.texto, id, b.responde_a), texto: "Tentar de novo"}));
    }
  }

  function guardarPendente(p) {
    const lista = Z.ler("pendentes", []).filter((x) => x.id !== p.id);
    lista.push(p);
    Z.guardar("pendentes", lista.slice(-10));
  }
  function removerPendente(id) {
    Z.guardar("pendentes", Z.ler("pendentes", []).filter((x) => x.id !== id));
  }

  /* --------------------------------------------------- leitor de tela */
  function anunciar(b, final) {
    // Frases completas, não tokens: o leitor de tela não é inundado.
    const texto = b.textoZeus || "";
    let ate = final ? texto.length : Math.max(texto.lastIndexOf(". "), texto.lastIndexOf("! "),
                                             texto.lastIndexOf("? "), texto.lastIndexOf("\n")) + 1;
    if (ate > (b.anunciado || 0)) {
      Z.$("anunciador").textContent = texto.slice(b.anunciado || 0, ate).trim();
      b.anunciado = ate;
    }
  }

  function bolhaDoZeus(turno) {
    let b = bolhas.get(turno);
    if (!b) { b = {estado: "processando", externa: true}; bolhas.set(turno, b); }
    if (!b.zeus) {
      b.zeus = bolha("zeus", "", {});
      b.textoZeus = ""; b.anunciado = 0;
      anexar(b.zeus, false);
    }
    return b;
  }

  /* ------------------------------------------------------------ eventos */
  Z.on("evento:turno", (p) => {
    const b = bolhas.get(p.turno);
    const estado = {em_fila: "em_fila", concluida: "concluida", falhou: "falhou",
                    interrompida: "interrompida"}[p.etapa] || "processando";
    if (b && b.nicolas && !b.falhouEnvio) {
      const motivo = estado === "falhou" && p.detalhe ? Z.motivoLegivel(p.detalhe.erro || p.detalhe.motivo || "") : "";
      if (b.estado !== estado || motivo) estadoDaBolha(p.turno, estado, motivo, false);
    }
  });

  Z.on("evento:fluxo", (p) => {
    if (!p.turno) return;
    if (p.reiniciar) {
      // O que estava na tela era rascunho: o modelo decidiu usar uma ferramenta.
      const b = bolhas.get(p.turno);
      if (b && b.zeus) { b.zeus.remove(); b.zeus = null; b.textoZeus = ""; b.anunciado = 0; }
      return;
    }
    const b = bolhaDoZeus(p.turno);
    b.zeus.classList.add("fluindo");
    b.textoZeus += p.pedaco || "";
    const estavaNoFim = pertoDoFim();
    b.zeus._corpo.textContent = b.textoZeus;
    descer(estavaNoFim);
    anunciar(b, false);
  });

  Z.on("evento:mensagem", (p) => {
    if (p.de === "zeus") {
      const b = p.turno ? bolhaDoZeus(p.turno) : {zeus: null};
      if (!b.zeus) { b.zeus = bolha("zeus", "", {}); anexar(b.zeus, false); }
      b.zeus.classList.remove("fluindo");
      b.textoZeus = p.texto || "";
      b.zeus._corpo.textContent = b.textoZeus;
      const meta = b.zeus._meta;
      meta.textContent = "";
      meta.appendChild(Z.el("span", {texto: p.hora || Z.fmt.hora(new Date().toISOString())}));
      if (p.canal && p.canal !== "hud") meta.appendChild(Z.el("span", {texto: VIA[p.canal] || p.canal}));
      if (p.detalhes) b.zeus.appendChild(comoChegou(p.detalhes));
      anunciar(b, true);
      descer(false);
      return;
    }
    if (p.de === "nicolas") {
      const b = p.turno && bolhas.get(p.turno);
      if (b && b.nicolas) {                         // transcrição de um áudio enviado daqui
        b.texto = p.texto;
        b.nicolas._corpo.textContent = p.texto;
        return;
      }
      const no = bolha("nicolas", p.texto, {hora: p.hora, via: VIA[p.canal]});
      if (p.turno) bolhas.set(p.turno, {nicolas: no, texto: p.texto, estado: "processando", externa: true});
      anexar(no, false);
      return;
    }
    anexar(bolha("sistema", p.texto, {}), false);
  });

  Z.on("evento:aviso", (p) => {
    if (p.tipo_saida === "resposta") return;
    const no = bolha("zeus", p.texto, {hora: Z.fmt.hora(new Date().toISOString()),
                                       via: p.tipo_saida === "pergunta" ? "pergunta do Zeus" : "aviso do Zeus",
                                       classe: "aviso-zeus"});
    const id = p.tipo_saida === "pergunta" && /^pergunta:(\d+)$/.exec(p.chave || "");
    if (id) {
      no._meta.appendChild(Z.el("button", {type: "button", class: "botao pequeno",
        onclick: () => Z.conversa.responderA({id: Number(id[1]), texto: p.texto}), texto: "Responder"}));
    }
    anexar(no, false);
  });

  Z.on("evento:audio", (p) => Z.audio.chegou(p, p.turno && bolhas.get(p.turno)));

  function comoChegou(d) {
    const itens = [];
    const usadas = (d.ferramentas || []).filter((f) => f.resultado !== "nao_executada");
    const naoFeitas = (d.ferramentas || []).filter((f) => f.resultado === "nao_executada");
    itens.push(Z.el("li", {texto: usadas.length
      ? "Ferramentas: " + usadas.map((f) => (Z.FERRAMENTAS[f.nome] || f.nome).toLowerCase()
                                           + (f.resultado === "ok" ? "" : " (" + f.resultado + ")")).join("; ")
      : "Respondeu sem usar ferramenta."}));
    if (naoFeitas.length) itens.push(Z.el("li", {texto: "Pedida e não executada: " + naoFeitas.map((f) => f.nome).join(", ")}));
    const lidas = (d.fontes || []).filter((f) => f.lida), vistas = (d.fontes || []).filter((f) => !f.lida);
    for (const [rotulo, lista] of [["Fontes lidas", lidas], ["Fontes encontradas", vistas]]) {
      if (!lista.length) continue;
      const sub = Z.el("ul");
      for (const f of lista.slice(0, 6)) {
        let dominio = f.url;
        try { dominio = new URL(f.url).hostname; } catch (e) { /* mantém */ }
        sub.appendChild(Z.el("li", {}, Z.el("a", {href: f.url, target: "_blank", rel: "noopener noreferrer",
                                                   texto: f.id + " · " + dominio})));
      }
      itens.push(Z.el("li", {}, rotulo + ":", sub));
    }
    itens.push(Z.el("li", {texto: "Etapas do modelo: " + (d.rodadas || 0) + " · tempo medido: " + Z.fmt.segundos(d.total_ms)
                                   + (d.modelo ? " · " + d.modelo : "")}));
    return Z.el("details", {class: "como"}, Z.el("summary", {texto: "Como chegou a isso?"}), Z.el("ul", {}, ...itens));
  }

  /* ------------------------------------------------------------ entrada */
  function ajustarAltura() {
    const campo = Z.$("texto");
    campo.style.height = "auto";
    campo.style.height = Math.min(160, campo.scrollHeight) + "px";
    campo.style.overflowY = campo.scrollHeight > 160 ? "auto" : "hidden";
    document.documentElement.style.setProperty("--altura-entrada",
                                               Z.$("formEntrada").offsetHeight + "px");
  }

  Z.conversa.ligar = function () {
    const campo = Z.$("texto");
    campo.value = Z.ler("rascunho", "") || "";
    ajustarAltura();
    campo.addEventListener("input", () => {
      ajustarAltura();
      clearTimeout(rascunhoTimer);
      rascunhoTimer = setTimeout(() => Z.guardar("rascunho", campo.value), 250);
    });
    campo.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); Z.$("formEntrada").requestSubmit(); }
    });
    Z.$("formEntrada").addEventListener("submit", (e) => {
      e.preventDefault();
      const resposta = respondendoA ? respondendoA.id : undefined;
      Z.conversa.cancelarResposta();
      Z.conversa.enviar(campo.value, null, resposta);
    });
    Z.$("cancelarResposta").onclick = () => Z.conversa.cancelarResposta();
    Z.$("novas").onclick = () => descer(true);
    historico().addEventListener("scroll", () => { if (pertoDoFim()) Z.$("novas").hidden = true; });
  };
})(window.Z);
