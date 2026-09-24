"use strict";
/* Conversa com o servidor: pedidos, sessão e o fluxo de eventos.

   O fluxo tem sequência. Cada evento chega com `seq` e `sessao`; o navegador
   manda o último id visto ao reconectar e o servidor reenvia o que faltou.
   Quando o buraco é grande demais, ou o Zeus reiniciou, chega
   "ressincronizar" e a página recarrega o estado autoritativo — nunca tenta
   completar texto adivinhando fragmentos. */
(function (Z) {
  async function pedir(caminho, opcoes) {
    opcoes = opcoes || {};
    const cabecalhos = Object.assign({}, opcoes.corpo !== undefined ? {"Content-Type": "application/json"} : {},
                                     opcoes.cabecalhos || {});
    let resposta;
    try {
      resposta = await fetch(caminho, {
        method: opcoes.metodo || (opcoes.corpo !== undefined || opcoes.bruto ? "POST" : "GET"),
        credentials: "same-origin", cache: "no-store", headers: cabecalhos,
        body: opcoes.bruto || (opcoes.corpo !== undefined ? JSON.stringify(opcoes.corpo) : undefined),
      });
    } catch (erro) {
      return {ok: false, status: 0, corpo: null, rede: true};
    }
    let corpo = null;
    try { corpo = await resposta.json(); } catch (e) { corpo = null; }
    if (resposta.status === 401 && !opcoes.semPorta) Z.emitir("sessao_necessaria");
    return {ok: resposta.ok, status: resposta.status, corpo};
  }

  Z.api = {
    pedir,
    sessao: () => pedir("/sessao", {semPorta: true}),
    entrar: (segredo) => pedir("/sessao", {corpo: {chave: segredo}, semPorta: true}),
    sair: () => pedir("/sessao/sair", {corpo: {}}),
    estado: () => pedir("/estado"),
    saude: () => pedir("/saude"),
    diagnostico: () => pedir("/diagnostico"),
    mapa: () => pedir("/mapa"),
    enviar: (mensagem) => pedir("/mensagem", {corpo: mensagem}),
    audio: (id, blob) => pedir("/escuta", {bruto: blob, cabecalhos: {"Content-Type": blob.type || "audio/webm",
                                                                    "X-Zeus-Turno": id}}),
    pendencia: (tipo, alvo, acao) => pedir("/pendencia", {corpo: {id: Z.novoId(), tipo, alvo, acao}}),
  };

  /* ------------------------------------------------------------ fluxo */
  let fonte = null, tentativaEm = null, semConexaoDesde = null;

  function aceitar(pacote) {
    if (pacote.tipo === "ressincronizar") { Z.emitir("ressincronizar", pacote); return; }
    if (pacote.sessao && Z.estado.sessaoServidor && pacote.sessao !== Z.estado.sessaoServidor) {
      // O Zeus reiniciou: a sequência recomeçou e o que estava em andamento
      // não vai terminar. O estado novo decide o que mostrar.
      Z.estado.sessaoServidor = pacote.sessao;
      Z.estado.seq = 0;
      Z.emitir("ressincronizar", {motivo: "reinicio"});
    }
    if (typeof pacote.seq === "number") {
      if (pacote.seq <= Z.estado.seq) return;          // já visto (reenvio ou retrato mais novo)
      Z.estado.seq = pacote.seq;
    }
    Z.emitir("evento:" + pacote.tipo, pacote);
  }

  Z.fluxo = {
    abrir() {
      if (fonte) fonte.close();
      clearTimeout(tentativaEm);
      fonte = new EventSource("/fluxo");
      fonte.onopen = () => {
        const voltou = Z.estado.conexao !== "conectado" && Z.estado.conexao !== "conectando";
        semConexaoDesde = null;
        Z.definir("conexao", "conectado");
        if (voltou) Z.emitir("reconectou");
      };
      fonte.onerror = async () => {
        if (!semConexaoDesde) semConexaoDesde = Date.now();
        Z.definir("conexao", Date.now() - semConexaoDesde > 10000 ? "sem_conexao" : "reconectando");
        if (fonte.readyState === EventSource.CLOSED) {
          // Fechado de vez (ex.: sessão vencida). Conferir antes de insistir.
          const sessao = await Z.api.sessao();
          if (sessao.ok && sessao.corpo && !sessao.corpo.autenticado) { Z.emitir("sessao_necessaria"); return; }
          tentativaEm = setTimeout(() => Z.fluxo.abrir(), 3000);
        }
      };
      fonte.onmessage = (evento) => {
        let pacote;
        try { pacote = JSON.parse(evento.data); } catch (e) { return; }
        aceitar(pacote);
      };
    },
    fechar() { if (fonte) fonte.close(); fonte = null; },
  };

  /* Estado autoritativo: sempre que a sequência se perde, e na abertura. */
  Z.recarregar = async function () {
    const r = await Z.api.estado();
    if (!r.ok || !r.corpo) {
      Z.emitir("estado_indisponivel", r);
      return false;
    }
    const retrato = r.corpo;
    const mesmaSubida = retrato.sessao_servidor === Z.estado.sessaoServidor;
    Z.estado.sessaoServidor = retrato.sessao_servidor || Z.estado.sessaoServidor;
    // Outra subida do servidor recomeça a contagem; na mesma, nunca voltar.
    Z.estado.seq = mesmaSubida ? Math.max(Z.estado.seq, retrato.seq || 0) : (retrato.seq || 0);
    Z.estado.retrato = retrato;
    Z.estado.capacidades = retrato.capacidades || {};
    Z.emitir("retrato", retrato);
    return true;
  };
})(window.Z);
