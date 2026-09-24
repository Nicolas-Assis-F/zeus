"use strict";
/* Liga tudo: sessão, navegação, faixa "Agora", sinais e reconexão.

   A faixa "Agora" mostra a etapa real que o núcleo publicou, o tempo que o
   servidor mediu e o resultado. Um "pensando" genérico não conta como
   resposta; aqui só aparece o que de fato está acontecendo. */
(function (Z) {
  const b = document.body;
  const FINAIS = ["concluida", "falhou", "interrompida"];
  let relogioAgora = null, avisoTemporario = null, gravandoDesde = null, finalAte = 0;

  /* ------------------------------------------------------------ agora */
  const INTERACAO_DA_ETAPA = {
    em_fila: "preparando", transcrevendo: "transcrevendo", montando_contexto: "preparando",
    consultando_modelo: "preparando", executando_ferramenta: "executando", escrevendo: "escrevendo",
    sintetizando_voz: "preparando", concluida: "pronto", falhou: "erro", interrompida: "erro",
  };

  function turnoAtivo() {
    const t = Z.estado.ativo && Z.estado.turnos.get(Z.estado.ativo);
    return t || null;
  }

  Z.agora = {
    pintar() {
      const faixa = Z.$("agora"), texto = Z.$("agoraTexto"), tempo = Z.$("agoraTempo");
      if (avisoTemporario) {
        faixa.dataset.estado = avisoTemporario.tipo;
        texto.textContent = avisoTemporario.texto; tempo.textContent = "";
        return;
      }
      if (gravandoDesde !== null) {
        faixa.dataset.estado = "ativo";
        texto.textContent = "Gravando o áudio — toque no microfone de novo para enviar";
        tempo.textContent = Z.fmt.segundos(performance.now() - gravandoDesde);
        return;
      }
      const t = turnoAtivo();
      if (t && (!FINAIS.includes(t.etapa) || performance.now() < finalAte)) {
        const rotulo = (Z.ETAPAS[t.etapa] || (() => t.etapa))(t.detalhe || {});
        const origem = t.canal === "telegram" ? " (mensagem do Telegram)" : t.origem === "voz" ? " (áudio)" : "";
        if (FINAIS.includes(t.etapa)) {
          faixa.dataset.estado = t.etapa === "concluida" ? "concluido" : "falhou";
          texto.textContent = rotulo + origem + (t.etapa === "concluida" && t.decorrido_ms !== null
            ? " em " + Z.fmt.segundos(t.decorrido_ms) : "");
          tempo.textContent = "";
        } else {
          faixa.dataset.estado = "ativo";
          texto.textContent = rotulo + origem;
          const base = t.decorrido_ms === null || t.decorrido_ms === undefined ? null : t.decorrido_ms;
          tempo.textContent = base === null ? "" : Z.fmt.segundos(base + performance.now() - t.recebido);
        }
        return;
      }
      if (Z.audio.tocando()) {
        faixa.dataset.estado = "ativo"; texto.textContent = "Falando"; tempo.textContent = ""; return;
      }
      const modelo = (Z.estado.retrato.capacidades || {}).modelo || {};
      faixa.dataset.estado = modelo.estado === "indisponivel" ? "atencao" : "ocioso";
      texto.textContent = Z.estado.conexao !== "conectado" ? "Sem conexão com o Zeus."
        : modelo.estado === "indisponivel" ? "Pronto, sem modelo: agenda e lembretes seguem; a conversa avisa que não pode responder."
        : "Pronto.";
      tempo.textContent = "";
    },
    avisar(texto, tipo) {
      avisoTemporario = {texto, tipo: tipo || "atencao"};
      Z.agora.pintar();
      setTimeout(() => { avisoTemporario = null; Z.agora.pintar(); }, 6000);
    },
    gravando(inicio) { gravandoDesde = inicio; ligarRelogio(); },
  };

  function ligarRelogio() {
    clearInterval(relogioAgora);
    relogioAgora = setInterval(() => {
      Z.agora.pintar();
      const t = turnoAtivo();
      const ativo = gravandoDesde !== null || (t && !FINAIS.includes(t.etapa)) || performance.now() < finalAte;
      if (!ativo) { clearInterval(relogioAgora); relogioAgora = null; Z.agora.pintar(); }
    }, 250);
  }

  Z.on("mudou:microfone", (m) => { if (m !== "capturando") { gravandoDesde = null; Z.agora.pintar(); } });

  Z.on("evento:turno", (p) => {
    const anterior = Z.estado.turnos.get(p.turno) || {};
    Z.estado.turnos.set(p.turno, Object.assign(anterior, {etapa: p.etapa, detalhe: p.detalhe || {},
      decorrido_ms: p.decorrido_ms, canal: p.canal || anterior.canal, origem: p.origem || anterior.origem,
      recebido: performance.now()}));
    Z.estado.ativo = p.turno;
    if (FINAIS.includes(p.etapa)) finalAte = performance.now() + 6000;
    if (!Z.audio.tocando() && gravandoDesde === null) Z.definir("interacao", INTERACAO_DA_ETAPA[p.etapa] || "preparando");
    if (FINAIS.includes(p.etapa)) setTimeout(() => {
      if (Z.estado.interacao === "erro" || Z.estado.interacao === "pronto") Z.definir("interacao", Z.audio.tocando() ? "falando" : "pronto");
    }, 2500);
    ligarRelogio();
    Z.agora.pintar();
  });

  /* ----------------------------------------------------------- sinais */
  function pintarSinais() {
    const modelo = (Z.estado.retrato.capacidades || {}).modelo;
    const s = Z.$("sinalModelo");
    if (modelo) {
      const pronto = modelo.estado === "pronta";
      s.className = "sinal " + (pronto ? "bom" : "ruim");
      s.querySelector(".val").textContent = pronto ? "modelo pronto" : "modelo indisponível";
      s.title = pronto ? modelo.nome : (modelo.motivo || "o modelo não respondeu à verificação");
    }
    Z.$("notaEntrada").textContent = modelo && modelo.estado !== "pronta"
      ? "O modelo está indisponível: a mensagem fica registrada e o Zeus responde que não pode falar agora."
      : "Enter envia · Shift+Enter quebra a linha · / volta para cá";
    const c = Z.$("sinalConexao"), conexao = Z.estado.conexao;
    c.className = "sinal " + ({conectado: "bom", reconectando: "atencao", sem_conexao: "ruim"}[conexao] || "");
    c.querySelector(".val").textContent = {conectado: "conectado", reconectando: "reconectando…",
                                           sem_conexao: "sem conexão", conectando: "conectando…"}[conexao];
    const faixa = Z.$("faixaAviso");
    if (conexao === "reconectando" || conexao === "sem_conexao") {
      faixa.hidden = false;
      faixa.className = "faixa-aviso" + (conexao === "sem_conexao" ? " ruim" : "");
      faixa.textContent = "Sem conexão com o Zeus. Tentando de novo a cada poucos segundos; "
                          + "seu rascunho fica guardado neste aparelho e nada é reenviado sozinho.";
    } else if (faixa.dataset.motivo !== "estado") {
      faixa.hidden = true;
    }
    if (conexao !== "conectado" && Z.estado.interacao !== "capturando") Z.definir("interacao", "sem_conexao");
    else if (conexao === "conectado" && Z.estado.interacao === "sem_conexao") Z.definir("interacao", "pronto");
    Z.agora.pintar();
  }
  Z.on("mudou:conexao", pintarSinais);

  /* -------------------------------------------------------- navegação */
  Z.irPara = function (vista) {
    const largo = window.innerWidth >= 1100, medio = window.innerWidth >= 760 && !largo;
    Z.estado.vista = vista;
    b.dataset.vista = vista;
    const secao = vista === "pendencias" ? "conversa" : vista;
    for (const s of document.querySelectorAll(".vista")) s.classList.toggle("ativa", s.id === "vista-" + secao);
    for (const botao of document.querySelectorAll("nav.vistas button")) {
      if (botao.dataset.vista === vista) botao.setAttribute("aria-current", "page");
      else botao.removeAttribute("aria-current");
    }
    if (vista === "pendencias") {
      b.classList.remove("painel-recolhido");
      if (medio) b.classList.add("painel-aberto");
      Z.painel.aba("pendencias");
    } else if (medio) {
      b.classList.remove("painel-aberto");
    }
    if (vista === "diagnostico") Z.diagnostico.abrir(); else Z.diagnostico.fechar();
    if (vista === "hoje") Z.orbe.redesenhar();
    Z.guardar("vista", vista === "pendencias" && largo ? "conversa" : vista);
  };

  Z.painel = {
    aba(nome) {
      for (const aba of ["pendencias", "memoria", "mapa"]) {
        Z.$("aba-" + aba).setAttribute("aria-selected", String(aba === nome));
        Z.$("painel-" + aba).hidden = aba !== nome;
      }
      if (nome === "mapa") Z.mapa.ligar();
    },
    fechar() {
      if (window.innerWidth >= 1100) b.classList.toggle("painel-recolhido");
      else { b.classList.remove("painel-aberto"); Z.irPara("conversa"); }
      Z.$("recolherPainel").setAttribute("aria-label", b.classList.contains("painel-recolhido") ? "Mostrar painel" : "Recolher painel");
    },
  };

  /* ------------------------------------------------------ dados */
  Z.on("retrato", (r) => {
    Z.pendencias.pintar(r);
    Z.voz.ajustar(r);
    pintarSinais();
    for (const t of r.turnos_hud || []) {
      Z.emitir("evento:turno", {turno: t.id, etapa: t.etapa, detalhe: t.detalhe, decorrido_ms: t.decorrido_ms,
                                canal: t.canal, origem: t.origem});
    }
    if (Z.estado.vista === "diagnostico") Z.diagnostico.pintarCapacidades();
  });
  Z.on("evento:estado", (p) => {
    const atual = Z.estado.retrato;
    Z.estado.retrato = Object.assign({}, atual, p, {turnos_hud: atual.turnos_hud});
    Z.pendencias.pintar(Z.estado.retrato);
    Z.voz.ajustar(Z.estado.retrato);
    pintarSinais();
  });
  Z.on("evento:operacao", (p) => {
    Z.estado.operacao = p.capacidades || {};
    Object.assign(Z.estado.retrato, {entregas: p.entregas, entradas: p.entradas,
                                     perguntas: p.perguntas, lembretes: p.lembretes});
    Z.pendencias.pintar(Z.estado.retrato);
    if (Z.estado.vista === "diagnostico") Z.diagnostico.pintarCapacidades();
  });
  function esquecerTurnosDaSubidaAnterior() {
    // Outra subida do servidor: nada do que estava em andamento vai terminar,
    // e a faixa Agora não pode continuar mostrando etapa de um processo morto.
    Z.estado.turnos.clear();
    Z.estado.ativo = null;
    finalAte = 0;
    if (!Z.audio.tocando() && gravandoDesde === null) Z.definir("interacao", "pronto");
    Z.conversa.marcarInterrompidas();
    Z.agora.pintar();
  }
  Z.on("ressincronizar", async (p) => {
    const sessaoAntes = Z.estado.sessaoServidor;
    const reinicio = p && p.motivo === "reinicio";
    if (await Z.recarregar()) {
      if (reinicio || Z.estado.sessaoServidor !== sessaoAntes) esquecerTurnosDaSubidaAnterior();
      Z.conversa.reconstruir(Z.estado.retrato);
    }
  });
  Z.on("reconectou", async () => {
    const sessaoAntes = Z.estado.sessaoServidor;
    if (await Z.recarregar() && Z.estado.sessaoServidor !== sessaoAntes) {
      esquecerTurnosDaSubidaAnterior();
      Z.conversa.reconstruir(Z.estado.retrato);
    }
  });
  Z.on("estado_indisponivel", (r) => {
    const faixa = Z.$("faixaAviso");
    faixa.hidden = false; faixa.dataset.motivo = "estado"; faixa.className = "faixa-aviso";
    faixa.textContent = "Não consegui carregar o estado do Zeus" + (r && r.rede ? " (sem conexão)" : "")
                        + ". O que já estava na tela continua; tento de novo ao reconectar.";
  });

  /* ------------------------------------------------------------- porta */
  function mostrarPorta(mensagem) {
    Z.fluxo.fechar();
    Z.$("porta").hidden = false;
    Z.$("erroPorta").textContent = mensagem || "";
    Z.orbe.redesenhar();
    setTimeout(() => Z.$("campoChave").focus(), 30);
  }
  Z.on("sessao_necessaria", () => { if (Z.$("porta").hidden) mostrarPorta("A sessão venceu. Entre de novo."); });

  async function entrar(segredo) {
    const r = await Z.api.entrar(segredo);
    if (r.ok) { Z.$("porta").hidden = true; Z.$("campoChave").value = ""; iniciar(); return true; }
    const motivo = r.status === 429 ? "Tentativas demais. Espere um minuto."
      : r.rede ? "Sem conexão com o Zeus." : "Chave ou código inválido.";
    if (Z.$("porta").hidden) mostrarPorta(motivo); else Z.$("erroPorta").textContent = motivo;
    return false;
  }

  async function abrirSessao() {
    const daUrl = new URLSearchParams(location.search).get("chave");
    if (daUrl) {
      // Endereço antigo com a chave: troca pela sessão e tira a chave da barra.
      history.replaceState(null, "", location.pathname);
      await entrar(daUrl);
      return;
    }
    const sessao = await Z.api.sessao();
    if (sessao.ok && sessao.corpo && sessao.corpo.autenticado) iniciar();
    else if (sessao.rede || sessao.status === 0) { Z.definir("conexao", "sem_conexao"); setTimeout(abrirSessao, 3000); }
    else mostrarPorta();
  }

  let iniciado = false;
  async function iniciar() {
    Z.fluxo.abrir();
    const ok = await Z.recarregar();
    if (ok && !iniciado) Z.conversa.reconstruir(Z.estado.retrato);
    iniciado = iniciado || ok;
    pintarSinais();
  }

  /* ------------------------------------------------------------- início */
  async function boot() {
    Z.orbe.registrar("orbeTopo", "orbeHoje", "orbePorta");
    if (Z.ler("economia", false)) { b.classList.add("economia"); Z.$("economia").checked = true; }
    Z.orbe.iniciar();
    Z.conversa.ligar();
    Z.gestos.ligar();
    for (const botao of document.querySelectorAll("nav.vistas button")) botao.onclick = () => Z.irPara(botao.dataset.vista);
    for (const botao of document.querySelectorAll("[data-ir]")) botao.onclick = () => Z.irPara(botao.dataset.ir);
    for (const aba of ["pendencias", "memoria", "mapa"]) Z.$("aba-" + aba).onclick = () => Z.painel.aba(aba);
    Z.$("recolherPainel").onclick = () => Z.painel.fechar();
    Z.$("pararAudio").onclick = () => Z.audio.parar();
    Z.$("microfone").onclick = () => Z.voz.alternar();
    Z.$("sair").onclick = async () => { await Z.api.sair(); iniciado = false; mostrarPorta("Sessão encerrada neste aparelho."); };
    Z.$("formPorta").addEventListener("submit", (e) => { e.preventDefault(); entrar(Z.$("campoChave").value.trim()); });
    Z.$("economia").onchange = (e) => {
      b.classList.toggle("economia", e.target.checked);
      Z.guardar("economia", e.target.checked);
      Z.orbe.iniciar();
      if (Z.estado.vista === "diagnostico") Z.diagnostico.abrir();
    };
    document.addEventListener("keydown", (e) => {
      const digitando = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      if (e.key === "/" && !digitando && Z.$("porta").hidden) {
        e.preventDefault(); Z.irPara("conversa"); Z.$("texto").focus();
      } else if (e.key === "Escape") {
        // Esc fecha o que está aberto; só depois disso para o áudio.
        if (b.classList.contains("painel-aberto")) { Z.painel.fechar(); Z.$("botaoPendencias").focus(); }
        else if (!Z.$("respostaA").hidden) Z.conversa.cancelarResposta();
        else if (Z.audio.tocando()) Z.audio.parar();
      }
    });
    window.addEventListener("resize", () => Z.mapa.redesenhar());
    Z.irPara(Z.ler("vista", "conversa"));
    abrirSessao();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})(window.Z);
