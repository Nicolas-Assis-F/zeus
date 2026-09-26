"use strict";
/* Estado central da interface e utilidades.

   Os componentes não deduzem nada por conta própria: modelo, microfone,
   conexão e saúde da máquina são estados separados, e cada um vem de uma
   fonte real — o retrato do servidor, os eventos do fluxo ou o navegador. */
window.Z = window.Z || {};
(function (Z) {
  Z.$ = (id) => document.getElementById(id);

  /* Cria elemento sem montar marcação a partir de texto: o que veio do servidor (ou de uma
     página da internet, via Zeus) nunca vira marcação. */
  Z.el = function (tag, atributos, ...filhos) {
    const no = document.createElement(tag);
    for (const [nome, valor] of Object.entries(atributos || {})) {
      if (valor === undefined || valor === null || valor === false) continue;
      if (nome === "class") no.className = valor;
      else if (nome === "texto") no.textContent = valor;
      else if (nome.startsWith("on")) no.addEventListener(nome.slice(2), valor);
      else no.setAttribute(nome, valor === true ? "" : valor);
    }
    for (const filho of filhos) {
      if (filho === null || filho === undefined || filho === false) continue;
      no.appendChild(typeof filho === "string" ? document.createTextNode(filho) : filho);
    }
    return no;
  };

  const ouvintes = {};
  Z.on = (tipo, fn) => { (ouvintes[tipo] = ouvintes[tipo] || []).push(fn); };
  Z.emitir = (tipo, dados) => {
    for (const fn of ouvintes[tipo] || []) {
      try { fn(dados); } catch (erro) { console.error("[zeus]", tipo, erro); }
    }
  };

  Z.estado = {
    sessaoServidor: null,
    seq: 0,
    conexao: "conectando",   // conectando | conectado | reconectando | sem_conexao
    retrato: {},
    capacidades: {},
    operacao: {},
    turnos: new Map(),        // id -> {estado, etapa, detalhe, decorrido_ms, recebido}
    ativo: null,              // turno mostrado na faixa Agora
    interacao: "pronto",      // o orbe: pronto | capturando | transcrevendo | preparando |
                              // executando | escrevendo | falando | erro | sem_conexao
    vista: "conversa",
    microfone: "desconhecido",
  };

  Z.definir = function (campo, valor) {
    if (Z.estado[campo] === valor) return;
    Z.estado[campo] = valor;
    Z.emitir("mudou:" + campo, valor);
  };

  /* Armazenamento local só para conveniência deste aparelho: rascunho,
     envios que falharam, vista escolhida. Pode falhar (aba privada) e a
     página continua funcionando. */
  Z.guardar = (chave, valor) => {
    try { localStorage.setItem("zeus." + chave, JSON.stringify(valor)); } catch (e) { /* sem armazenamento */ }
  };
  Z.ler = (chave, padrao) => {
    try {
      const bruto = localStorage.getItem("zeus." + chave);
      return bruto === null ? padrao : JSON.parse(bruto);
    } catch (e) { return padrao; }
  };

  /* Identidade da mensagem, gerada no aparelho. getRandomValues existe
     também em origem não segura, ao contrário de randomUUID. */
  Z.novoId = function () {
    const bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    return "h" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  };

  Z.movimentoReduzido = () =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    document.body.classList.contains("economia");

  const NADA = "—";
  Z.fmt = {
    NADA,
    segundos(ms) {
      if (ms === null || ms === undefined || isNaN(ms)) return NADA;
      if (ms < 1000) return Math.round(ms) + " ms";
      return (ms / 1000).toFixed(ms < 10000 ? 1 : 0).replace(".", ",") + " s";
    },
    hora(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      if (isNaN(d)) return "";
      return d.toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit"});
    },
    momento(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      if (isNaN(d)) return String(iso);
      const hoje = new Date();
      const amanha = new Date(Date.now() + 86400000);
      const hora = d.toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit"});
      if (d.toDateString() === hoje.toDateString()) return "hoje " + hora;
      if (d.toDateString() === amanha.toDateString()) return "amanhã " + hora;
      return d.toLocaleString("pt-BR", {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
    },
    bytes(v) {
      if (v === null || v === undefined || isNaN(v)) return NADA;
      const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; v = Number(v);
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
      return (v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)) + " " + u[i];
    },
    porcento(v) { return (v === null || v === undefined || isNaN(v)) ? NADA : Math.round(v) + "%"; },
    duracao(s) {
      if (!s && s !== 0) return NADA;
      const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
      if (d) return d + "d " + h + "h";
      if (h) return h + "h " + m + "min";
      return m + "min";
    },
  };

  /* Nomes de ferramenta viram o que Nicolas reconhece. */
  Z.FERRAMENTAS = {
    pesquisar: "Pesquisando na internet", ler_pagina: "Lendo uma fonte",
    lembrar_fato: "Guardando na memória", consultar_fato: "Consultando a memória",
    esquecer_fato: "Tirando da memória", agendar_lembrete: "Agendando lembrete",
    agendar_pergunta: "Agendando pergunta", listar_pendencias: "Conferindo pendências",
    encerrar_pendencia: "Encerrando pendência", responder_pergunta: "Registrando sua resposta",
    listar_pasta: "Olhando uma pasta", procurar_arquivo: "Procurando arquivo",
    ler_arquivo: "Lendo um arquivo", localizar: "Procurando no mapa",
    abrir_no_computador: "Abrindo no computador",
  };

  Z.ETAPAS = {
    em_fila: () => "Na fila",
    transcrevendo: () => "Transcrevendo o áudio aqui mesmo",
    montando_contexto: () => "Reunindo contexto",
    consultando_modelo: (d) => "Consultando o modelo" + (d && d.rodada > 1 ? " (etapa " + d.rodada + ")" : ""),
    escrevendo: () => "Escrevendo a resposta",
    executando_ferramenta: (d) => (d && Z.FERRAMENTAS[d.ferramenta]) || "Usando uma ferramenta",
    sintetizando_voz: () => "Preparando a voz",
    concluida: () => "Concluída",
    falhou: (d) => "Falhou" + (d && (d.erro || d.motivo) ? ": " + Z.motivoLegivel(d.erro || d.motivo) : ""),
    interrompida: () => "Interrompida",
  };

  Z.motivoLegivel = function (codigo) {
    return ({
      modelo_indisponivel: "modelo indisponível",
      sem_transcricao: "não entendi o áudio",
      mensagem_vazia: "mensagem vazia",
      ErroDeModelo: "o modelo não respondeu",
      "fila cheia": "fila cheia",
    })[codigo] || String(codigo);
  };
})(window.Z);
