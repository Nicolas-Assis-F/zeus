/* Aprovações: o que o Zeus quer fazer e não pode sem você.

   Cada pedido mostra o alvo exato, a origem (você ou conteúdo externo, com a
   fonte), por quê, de qual objetivo veio e quanto tempo resta. O foco começa em
   Negar (ideia do ConfirmBanner do Mark-LV); ação irreversível pede para
   segurar Aprovar por 1 s. O mesmo código vale no grupo: "ok 4821". */
import {Z, el, pedir, ha, brinde, anunciar} from "../base.js";

function botaoSegurar(rotulo, fazer) {
  const barra = el("span", {class: "barra"});
  const b = el("button", {class: "bt ok segurar", type: "button", title: "Segure por 1 segundo"}, rotulo, barra);
  let t0 = 0, quadro = 0;
  const passo = () => {
    const p = Math.min(1, (performance.now() - t0) / 1000);
    barra.style.width = p * 100 + "%";
    if (p >= 1) { cancelar(); fazer(); return; }
    quadro = requestAnimationFrame(passo);
  };
  const cancelar = () => { cancelAnimationFrame(quadro); barra.style.width = "0"; };
  b.addEventListener("pointerdown", (e) => { e.preventDefault(); t0 = performance.now(); passo(); });
  b.addEventListener("pointerup", cancelar); b.addEventListener("pointerleave", cancelar);
  b.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.repeat) return; if (e.key === "Enter") fazer(); });
  return b;
}

export async function decidir(id, aprovar) {
  const r = await pedir(`aprovacoes/${id}`, {corpo: {aprovar}});
  if (r.ok) {
    anunciar(aprovar ? "Aprovado" : "Negado");
    Z.estado.aprovacoes = (Z.estado.aprovacoes || []).filter((a) => a.id !== id);
    Z.emitir("aprovacoes");
  } else brinde((r.corpo && r.corpo.erro) || "Não consegui registrar a decisão.");
  return r.ok;
}

export function cartaoPedido(a, compacto = false) {
  const agora = Date.now() / 1000;
  const resta = (a.expira_em || agora) - agora;
  const externo = String(a.origem || "").startsWith("externo");
  const negar = el("button", {class: "bt nao", type: "button", onclick: () => decidir(a.id, false)}, "Negar");
  const aprovar = a.irreversivel || externo
    ? botaoSegurar("Segure para aprovar", () => decidir(a.id, true))
    : el("button", {class: "bt ok", type: "button", onclick: () => decidir(a.id, true)}, "Aprovar");
  return el("article", {class: "pedido" + (resta < 600 ? " expirando" : ""), "aria-label": `Pedido ${a.codigo}`},
    el("div", {class: "acao"}, a.acao, "  ", el("span", {class: "codigo", title: "No grupo: ok " + a.codigo}, a.codigo)),
    el("dl", {},
      el("dt", {}, "Alvo"), el("dd", {}, a.alvo || "—"),
      compacto ? null : el("dt", {}, "Por quê"), compacto ? null : el("dd", {}, a.porque || "—"),
      el("dt", {}, "Origem"), el("dd", {class: externo ? "externo" : ""}, externo ? `veio de conteúdo externo: ${String(a.origem).slice(8)}` : "pedido seu"),
      a.objetivo_titulo || a.objetivo_id ? el("dt", {}, "Objetivo") : null,
      a.objetivo_titulo || a.objetivo_id ? el("dd", {}, a.objetivo_titulo || `#${a.objetivo_id}`) : null,
      el("dt", {}, "Validade"), el("dd", {}, resta > 0 ? `vence em ${ha(resta)}` : "vencido")),
    el("div", {class: "botoes"}, negar, aprovar));
}

export function montar(raiz) {
  const desenhar = () => {
    const itens = Z.estado.aprovacoes || [];
    let corpo;
    if (Z.estado.autonomia === "desligada") corpo = el("p", {class: "vazio"}, "A autonomia ainda não está ligada neste Zeus: não há caixa de aprovações.");
    else if (Z.estado.autonomia === "erro") corpo = el("p", {class: "erro-txt"}, "Não consegui ler a caixa de aprovações: " + (Z.estado.erroAutonomia || "erro"));
    else if (!itens.length) corpo = el("p", {class: "vazio"}, "✓ Nada esperando sua aprovação.");
    else corpo = el("div", {class: "grade"}, itens.map((a) => cartaoPedido(a)));
    raiz.replaceChildren(el("div", {class: "tela"},
      el("h1", {}, "Aprovações"),
      el("p", {class: "sub"}, "O que o Zeus quer fazer e espera você. Aprovar aqui, no grupo (\"ok 4821\") ou falando resolve em todos."),
      corpo));
    const primeiro = raiz.querySelector(".bt.nao");
    if (primeiro) primeiro.focus({preventScroll: true});
  };
  desenhar();
  Z.on("aprovacoes", () => raiz.isConnected && desenhar());
  return {atualizar: desenhar};
}
