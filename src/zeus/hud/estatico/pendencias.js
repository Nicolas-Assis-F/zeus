"use strict";
/* Pendências, memória e a vista Hoje. Tudo aqui vem do retrato do servidor.

   Cada pendência diz o que falta e oferece só a ação que o backend suporta.
   Resultado incerto pede verificação: "chegou" ou "não chegou", decidido
   por Nicolas — nunca um reenvio automático às cegas. */
(function (Z) {
  const ATENCAO = ["incerta", "falhou", "expirada"];

  function vazio(texto) { return Z.el("li", {class: "vazio", texto}); }

  /* Ação em dois toques: o primeiro pede confirmação, o segundo age.
     Nada disso usa confirm(): o foco e o teclado continuam na página. */
  function acao(rotulo, confirmar, fazer, classe) {
    const botao = Z.el("button", {type: "button", class: "botao pequeno" + (classe ? " " + classe : ""), texto: rotulo});
    let armado = null;
    botao.addEventListener("click", async () => {
      if (confirmar && !armado) {
        botao.textContent = confirmar;
        botao.classList.add("confirmando");
        armado = setTimeout(() => { armado = null; botao.textContent = rotulo; botao.classList.remove("confirmando"); }, 5000);
        return;
      }
      clearTimeout(armado); armado = null;
      botao.disabled = true;
      await fazer();
    });
    return botao;
  }

  async function pedir(tipo, alvo, acaoNome) {
    Z.$("retornoPendencia").textContent = "Enviando…";
    const r = await Z.api.pendencia(tipo, alvo, acaoNome);
    Z.$("retornoPendencia").textContent = r.ok ? "Pedido recebido; aguardando o Zeus aplicar."
      : "Não consegui pedir: " + ((r.corpo && r.corpo.erro) || (r.rede ? "sem conexão" : "erro " + r.status));
  }

  function itemEntrega(e) {
    const o_que = {incerta: "Sem confirmação de que chegou", falhou: "O canal recusou três vezes",
                   expirada: "Passou do prazo de entrega"}[e.situacao] || e.situacao;
    const li = Z.el("li", {class: "item atencao"},
      Z.el("div", {class: "titulo", texto: e.texto}),
      Z.el("div", {class: "detalhe", texto: o_que + (e.motivo && !/sem confirmação/i.test(e.motivo) ? " — " + e.motivo : "")
                                           + " · " + e.canal}));
    const acoes = Z.el("div", {class: "acoes"});
    if (e.situacao === "incerta") {
      acoes.appendChild(acao("Chegou", "Confirmar: chegou", () => pedir("entrega", e.chave, "confirmar")));
      acoes.appendChild(acao("Não chegou — reenviar", "Reenviar mesmo?", () => pedir("entrega", e.chave, "reenviar")));
    } else {
      acoes.appendChild(acao("Reenviar", "Reenviar mesmo?", () => pedir("entrega", e.chave, "reenviar")));
    }
    acoes.appendChild(acao("Descartar", "Descartar mesmo?", () => pedir("entrega", e.chave, "descartar"), "perigo"));
    li.appendChild(acoes);
    return li;
  }

  function itemEntrada(e) {
    const efeitos = (e.efeitos || []).map((n) => (Z.FERRAMENTAS[n] || n).toLowerCase());
    const li = Z.el("li", {class: "item atencao"},
      Z.el("div", {class: "titulo", texto: "Mensagem do Telegram interrompida no meio da resposta"}),
      Z.el("div", {class: "detalhe", texto: efeitos.length
        ? "Já começou: " + efeitos.join("; ") + ". Reprocessar pode repetir isso."
        : "Nenhum efeito registrado neste turno."}));
    li.appendChild(Z.el("div", {class: "acoes"},
      acao("Reprocessar", efeitos.length ? "Pode repetir. Reprocessar?" : "Reprocessar?", () => pedir("entrada", e.id, "reprocessar")),
      acao("Descartar", "Descartar mesmo?", () => pedir("entrada", e.id, "descartar"), "perigo")));
    return li;
  }

  function itemPergunta(p) {
    const perguntada = p.situacao === "perguntada";
    const li = Z.el("li", {class: "item" + (perguntada ? " atencao" : "")},
      Z.el("div", {class: "titulo", texto: "#" + p.id + " " + p.texto}),
      Z.el("div", {class: "detalhe", texto: perguntada ? "Aguardando sua resposta"
                                                        : "Agendada para " + Z.fmt.momento(p.vence_em)}));
    const acoes = Z.el("div", {class: "acoes"});
    if (perguntada) {
      acoes.appendChild(Z.el("button", {type: "button", class: "botao pequeno primario", texto: "Responder",
                                        onclick: () => Z.conversa.responderA({id: p.id, texto: p.texto})}));
    }
    acoes.appendChild(acao("Cancelar pergunta", "Cancelar mesmo?", () => pedir("pergunta", p.id, "cancelar"), "perigo"));
    li.appendChild(acoes);
    return li;
  }

  function itemLembrete(l) {
    return Z.el("li", {class: "item"},
      Z.el("div", {class: "titulo", texto: l.texto}),
      Z.el("div", {class: "detalhe", texto: Z.fmt.momento(l.vence_em)}),
      Z.el("div", {class: "acoes"},
        acao("Cancelar lembrete", "Cancelar mesmo?", () => pedir("lembrete", l.id, "cancelar"), "perigo")));
  }

  function encher(id, itens, construir, textoVazio) {
    const lista = Z.$(id);
    lista.textContent = "";
    if (!itens || !itens.length) { lista.appendChild(vazio(textoVazio)); return; }
    for (const item of itens) lista.appendChild(construir(item));
  }

  Z.pendencias = {
    pintar(r) {
      r = r || Z.estado.retrato;
      const entregas = (r.entregas || []).filter((e) => ATENCAO.includes(e.situacao));
      const entradas = (r.entradas || []).filter((e) => e.situacao === "incerta");
      const perguntadas = (r.perguntas || []).filter((p) => p.situacao === "perguntada");
      const lista = Z.$("listaAtencao");
      lista.textContent = "";
      entregas.forEach((e) => lista.appendChild(itemEntrega(e)));
      entradas.forEach((e) => lista.appendChild(itemEntrada(e)));
      if (!entregas.length && !entradas.length) lista.appendChild(vazio("Nada esperando decisão sua."));
      encher("listaPerguntas", r.perguntas, itemPergunta, "Nenhuma pergunta em aberto.");
      encher("listaLembretes", r.lembretes, itemLembrete, "Nada agendado.");
      encher("listaMemoria", r.fatos, (f) => Z.el("li", {class: "item"},
        Z.el("div", {class: "titulo", texto: f.value}),
        Z.el("div", {class: "detalhe", texto: f.key + " · atualizado " + Z.fmt.momento(f.updated_at)})),
        "Nenhum fato confirmado ainda.");
      const precisa = entregas.length + entradas.length + perguntadas.length;
      Z.$("contaPendencias").textContent = precisa ? String(precisa) : "";
      Z.$("contaAba").textContent = precisa ? String(precisa) : "";
      Z.hoje.pintar(r, {entregas, entradas, perguntadas});
    },
  };

  /* ---------------------------------------------------------------- hoje */
  Z.hoje = {
    pintar(r, atencao) {
      const hora = new Date().getHours();
      Z.$("tituloHoje").textContent = hora < 5 ? "Boa madrugada." : hora < 12 ? "Bom dia." : hora < 18 ? "Boa tarde." : "Boa noite.";
      const modelo = (r.capacidades || {}).modelo || {};
      Z.$("hojeEstado").textContent = modelo.estado === "pronta"
        ? "O Zeus está de pé e o modelo respondeu à verificação."
        : "O modelo está indisponível. Agenda e lembretes continuam; a conversa responde que não pode falar agora.";
      const proximos = [
        ...(r.lembretes || []).map((l) => ({quando: l.vence_em, texto: l.texto})),
        ...(r.perguntas || []).filter((p) => p.situacao === "agendada").map((p) => ({quando: p.vence_em, texto: "Pergunta: " + p.texto})),
      ].sort((a, b) => String(a.quando).localeCompare(String(b.quando))).slice(0, 5);
      encher("hojeAgenda", proximos, (x) => Z.el("li", {}, Z.el("span", {class: "quando", texto: Z.fmt.momento(x.quando)}),
                                                        Z.el("span", {class: "o-que", texto: x.texto})), "Nada agendado.");
      Z.$("hojeAgendaConta").textContent = proximos.length ? String(proximos.length) : "";
      const itens = [
        ...atencao.perguntadas.map((p) => "Pergunta aguardando resposta: " + p.texto),
        ...atencao.entregas.map((e) => "Entrega " + e.situacao + ": " + e.texto),
        ...atencao.entradas.map(() => "Mensagem do Telegram interrompida"),
      ];
      encher("hojeAtencao", itens.slice(0, 5), (t) => Z.el("li", {}, Z.el("span", {class: "o-que", texto: t})), "Nada esperando você.");
      Z.$("hojeAtencaoConta").textContent = itens.length ? String(itens.length) : "";
      const turnos = (r.turnos || []).slice(-4);
      encher("hojeConversa", turnos, (t) => Z.el("li", {},
        Z.el("span", {class: "quando", texto: Z.fmt.hora(t.em)}),
        Z.el("span", {class: "o-que", texto: (t.papel === "zeus" ? "Zeus: " : "Você: ") + t.texto.slice(0, 140)
                                             + (t.texto.length > 140 ? "…" : "")})), "Nenhuma conversa ainda.");
      const caps = Z.$("hojeCapacidades");
      caps.textContent = "";
      for (const [nome, info] of Object.entries(r.capacidades || {})) caps.appendChild(Z.sinalDeCapacidade(nome, info));
      if (!caps.childElementCount) caps.appendChild(Z.el("span", {class: "vazio", texto: "Aguardando o estado das capacidades."}));
    },
  };

  const NOMES = {modelo: "Modelo", voz: "Voz", escuta: "Escuta", pesquisa: "Pesquisa", telegram: "Telegram", mapa: "Mapa"};
  const BOM = ["pronta", "configurada", "configurado", "ativo", "ok"];
  Z.sinalDeCapacidade = function (nome, info) {
    const classe = BOM.includes(info.estado) ? "bom" : info.estado === "indisponivel" ? "ruim" : "";
    return Z.el("span", {class: "sinal " + classe, title: info.motivo || info.estado},
                Z.el("i"), Z.el("span", {texto: (NOMES[nome] || nome) + ": " + (info.estado || "—")}));
  };

  Z.on("evento:pendencia_resultado", (p) => {
    Z.$("retornoPendencia").textContent = (p.ok ? "Feito: " : "Não aplicado: ") + (p.mensagem || "");
  });
})(window.Z);
