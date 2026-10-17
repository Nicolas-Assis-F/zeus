/* Atividade: tudo que o Zeus fez sozinho, na ordem, com Desfazer onde houver.
   A trilha é encadeada por HMAC no servidor; aqui ela só é lida. */
import {Z, el, pedir, quando, brinde} from "../base.js";

const FILTROS = [["", "Tudo"], ["execucao", "Feito"], ["pedido,aprovacao,negacao,expiracao", "Aprovações"],
                 ["falha,laco", "Falhas"], ["desfazer", "Desfeito"], ["objetivo", "Objetivos"]];

export function montar(raiz) {
  let filtro = "";
  const desenhar = async () => {
    let itens = Z.estado.atividade || [];
    let erro = "";
    if (Z.estado.autonomia === "ligada") {
      const r = await pedir("atividade" + (filtro ? `?tipo=${encodeURIComponent(filtro)}` : ""));
      if (r.ok) itens = r.corpo.itens || []; else erro = "Não consegui ler a trilha agora.";
    }
    const barra = el("div", {class: "filtros", role: "group", "aria-label": "Filtrar"},
      FILTROS.map(([v, rot]) => el("button", {class: "bt p", type: "button", "aria-pressed": String(v === filtro),
        onclick: () => { filtro = v; desenhar(); }}, rot)));
    const desfazer = (i) => pedir(`atividade/${i.id}/desfazer`, {corpo: {}}).then((r) =>
      brinde(r.ok ? "Pedido de desfazer entregue ao Zeus." : (r.corpo && r.corpo.erro) || "Não consegui."));
    raiz.replaceChildren(el("div", {class: "tela"},
      el("h1", {}, "Atividade"),
      el("p", {class: "sub"}, "O que o Zeus fez sem você pedir na hora, com o alvo, o resultado e o custo."),
      barra,
      erro ? el("p", {class: "erro-txt"}, erro) :
      Z.estado.autonomia !== "ligada" ? el("p", {class: "vazio"}, "A autonomia ainda não está ligada neste Zeus.") :
      !itens.length ? el("p", {class: "vazio"}, "Nada registrado com este filtro.") :
      el("ul", {class: "linha-tempo"}, itens.map((i) => el("li", {},
        el("span", {class: "t"}, quando(i.ts)),
        el("div", {class: i.desfeito_em ? "desfeito" : ""},
          el("b", {}, i.acao || i.tipo), i.alvo ? ` → ${i.alvo}` : "",
          el("span", {class: "meta"}, [i.tipo, i.nivel, i.resultado, i.custo_usd ? `US$ ${Number(i.custo_usd).toFixed(4)}` : "",
                                       i.objetivo_id ? `objetivo #${i.objetivo_id}` : ""].filter(Boolean).join(" · "))),
        i.desfazer_json && !i.desfeito_em ? el("button", {class: "bt p", type: "button", onclick: () => desfazer(i)}, "Desfazer") : el("span"))))));
  };
  desenhar();
  return {atualizar: desenhar};
}
