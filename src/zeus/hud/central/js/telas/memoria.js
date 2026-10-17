/* Memória: o que o Zeus sabe de você, com busca, esquecer e desfazer (#79).
   A lista vem do retrato (fatos confirmados, como estão no banco). */
import {Z, el, pedir, quando, brinde} from "../base.js";

function normal(t) { return String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

export function montar(raiz) {
  let busca = "";
  const campo = el("input", {type: "search", placeholder: "Buscar na memória…", "aria-label": "Buscar na memória", style: "width:100%;max-width:420px"});
  const lista = el("div");
  const esquecer = async (chave) => {
    const r = await pedir("memoria", {corpo: {acao: "esquecer", fato: chave}});
    if (!r.ok) { brinde((r.corpo && r.corpo.erro) || "Não consegui pedir."); return; }
    brinde(`Esqueci «${chave}».`, {rotulo: "Desfazer", fazer: () => pedir("memoria", {corpo: {acao: "desfazer", fato: chave}})});
  };
  const desenhar = () => {
    const fatos = (Z.estado.retrato || {}).fatos || [];
    const termo = normal(busca);
    const achados = termo ? fatos.filter((f) => normal(f.key + " " + f.value).includes(termo)) : fatos;
    lista.replaceChildren(!fatos.length ? el("p", {class: "vazio"}, "Nada guardado ainda.") :
      !achados.length ? el("p", {class: "vazio"}, `Nada com “${busca}”.`) :
      el("ul", {class: "lista"}, achados.map((f) => el("li", {},
        el("b", {}, f.key), ": ", f.value,
        el("span", {class: "meta"}, `${f.estado || "confirmado"} · origem ${f.source || "—"} · ${quando(f.updated_at)}`),
        el("div", {class: "acoes"}, el("button", {class: "bt p", type: "button", onclick: () => esquecer(f.key)}, "Esquecer"))))));
  };
  let espera = 0;
  campo.addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(() => { busca = campo.value; desenhar(); }, 200); });
  raiz.replaceChildren(el("div", {class: "tela"},
    el("h1", {}, "Memória"),
    el("p", {class: "sub"}, "Fatos confirmados, guardados só neste X99. Esquecer tira da memória ativa; desfazer vale por 5 minutos."),
    campo, el("div", {style: "height:12px"}), lista));
  desenhar();
  Z.on("evento:memoria", (p) => { if (raiz.isConnected) brinde(p.texto); });
  return {atualizar: desenhar};
}
