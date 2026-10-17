/* Paleta de comandos (Ctrl+K), com o desenho do CommandPalette do OpenJarvis:
   <dialog> nativo, setas, Enter, Esc, seleção que acompanha o mouse. A busca é
   por subsequência; texto que não bate com nenhum comando vira pedido ao Zeus. */
import {$, el} from "./base.js";

const comandos = [];
const recentes = JSON.parse(sessionStorage.getItem("zeus_recentes") || "[]");
let selecionado = 0, visiveis = [];

export function registrarComandos(lista) { comandos.push(...lista); }

function pontuar(texto, busca) {
  const t = texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const b = busca.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  if (!b) return 1;
  if (t.includes(b)) return 100 - t.indexOf(b);
  let i = 0, pontos = 0;
  for (const c of t) { if (c === b[i]) { i++; pontos += 2; } if (i === b.length) return pontos; }
  return 0;
}

function desenhar() {
  const busca = $("buscaPaleta").value;
  visiveis = comandos.map((c) => ({c, p: pontuar(c.rotulo + " " + c.secao, busca) + (recentes.includes(c.id) ? 5 : 0)}))
    .filter((x) => x.p > 0).sort((a, b) => b.p - a.p).map((x) => x.c);
  if (busca.trim()) visiveis.push({id: "pedido", rotulo: `Pedir ao Zeus: “${busca.trim()}”`, secao: "Zeus",
    acao: async () => { const {pedirAoZeus} = await import("./telas/conversa.js"); pedirAoZeus(busca.trim()); }});
  selecionado = Math.min(selecionado, Math.max(0, visiveis.length - 1));
  $("listaPaleta").replaceChildren(...visiveis.map((c, i) => el("li", {role: "option", id: "op" + i,
    "aria-selected": String(i === selecionado), onclick: () => executar(i), onmousemove: () => marcar(i)},
    c.perigoso ? "⚠ " : "", c.rotulo, el("span", {class: "sec"}, c.secao))));
  $("buscaPaleta").setAttribute("aria-activedescendant", visiveis.length ? "op" + selecionado : "");
}
function marcar(i) {
  if (i === selecionado) return;
  selecionado = i;
  for (const [j, li] of [...$("listaPaleta").children].entries()) li.setAttribute("aria-selected", String(j === i));
  $("buscaPaleta").setAttribute("aria-activedescendant", "op" + i);
  $("listaPaleta").children[i]?.scrollIntoView({block: "nearest"});
}
function executar(i) {
  const c = visiveis[i];
  if (!c) return;
  $("paleta").close();
  if (c.id !== "pedido") {
    const r = recentes.filter((x) => x !== c.id); r.unshift(c.id);
    sessionStorage.setItem("zeus_recentes", JSON.stringify(r.slice(0, 6)));
  }
  c.acao();
}

export function abrirPaleta() {
  const d = $("paleta");
  if (d.open) { d.close(); return; }
  $("buscaPaleta").value = "";
  selecionado = 0;
  desenhar();
  d.showModal();
  $("buscaPaleta").focus();
}

$("buscaPaleta").addEventListener("input", () => { selecionado = 0; desenhar(); });
$("buscaPaleta").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); marcar(Math.min(selecionado + 1, visiveis.length - 1)); }
  else if (e.key === "ArrowUp") { e.preventDefault(); marcar(Math.max(selecionado - 1, 0)); }
  else if (e.key === "Enter") { e.preventDefault(); executar(selecionado); }
});
$("paleta").addEventListener("click", (e) => { if (e.target === $("paleta")) $("paleta").close(); });
addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); abrirPaleta(); }
});
