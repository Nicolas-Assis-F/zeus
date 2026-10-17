/* Central do Zeus: entrada, rotas, sino, paleta e eventos.

   As telas carregam sob demanda (import dinâmico): a primeira carga traz só o
   esqueleto, o orbe e a tela aberta. O estado vem de um retrato com marca
   d'água e depois do fluxo com sequência. */
import {Z, $, el, pedir, recarregar, abrirFluxo, fecharFluxo, anunciar, brinde, ha} from "./base.js";
import {mudarEstado, registrar, ROTULOS} from "./orbe.js";
import {abrirPaleta, registrarComandos} from "./paleta.js";

const TELAS = ["hoje", "conversa", "aprovacoes", "objetivos", "atividade", "memoria", "sistema", "controles"];
const TITULOS = {hoje: "Hoje", conversa: "Conversa", aprovacoes: "Aprovações", objetivos: "Objetivos",
                 atividade: "Atividade", memoria: "Memória", sistema: "Sistema", controles: "Controles"};
let atual = null, montada = null;

/* --------------------------------------------------------------- rotas */
async function irPara(nome) {
  if (!TELAS.includes(nome)) nome = "hoje";
  if (montada && montada.desmontar) montada.desmontar();
  atual = nome;
  for (const a of document.querySelectorAll("nav.lateral a"))
    a.toggleAttribute("aria-current", a.getAttribute("href") === "#" + nome) && a.setAttribute("aria-current", "page");
  document.title = `Zeus — ${TITULOS[nome]}`;
  const raiz = $("principal");
  try {
    const modulo = await import(`./telas/${nome}.js`);
    if (atual !== nome) return;
    montada = modulo.montar(raiz) || null;
  } catch (erro) {
    raiz.replaceChildren(el("div", {class: "tela"}, el("h1", {}, TITULOS[nome]),
      el("p", {class: "erro-txt"}, "Esta tela não carregou. Recarregue a página."), el("p", {class: "nota"}, String(erro))));
  }
  raiz.focus({preventScroll: true});
}
export const ir = (nome) => { if (location.hash === "#" + nome) irPara(nome); else location.hash = nome; };
addEventListener("hashchange", () => irPara(location.hash.slice(1)));

function redesenhar() { if (montada && montada.atualizar) montada.atualizar(); }

/* --------------------------------------------------------------- topo */
function pintarTopo() {
  $("estadoTopo").replaceChildren(el("b", {}, ROTULOS[Z.estado.orbe] || "Pronto"), Z.estado.detalhe ? " · " + Z.estado.detalhe : "");
  const n = (Z.estado.aprovacoes || []).length;
  const conta = $("contaSino");
  conta.hidden = !n; conta.textContent = n > 99 ? "99+" : String(n);
  $("navAprov").textContent = n ? String(n) : "";
  const ativos = (Z.estado.objetivos || []).filter((o) => o.estado === "ativo" || o.estado === "aguardando_nicolas").length;
  $("navObj").textContent = ativos ? String(ativos) : "";
}
Z.on("mudou:orbe", pintarTopo);
Z.on("mudou:detalhe", pintarTopo);
Z.on("mudou:conexao", (c) => {
  const caixa = $("conexao");
  caixa.dataset.c = c;
  caixa.querySelector("span").textContent = {conectado: "ao vivo", reconectando: "reconectando", sem_conexao: "sem conexão", conectando: "conectando"}[c] || c;
  if (c === "sem_conexao") mudarEstado("offline", "sem conexão com o Zeus");
  else if (c === "conectado" && Z.estado.orbe === "offline") mudarEstado("dormindo");
});

/* ---------------------------------------------------------------- sino */
async function abrirSino() {
  const painel = $("painelSino");
  if (!painel.hidden) { fecharSino(); return; }
  const {cartaoPedido} = await import("./telas/aprovacoes.js");
  const itens = Z.estado.aprovacoes || [];
  painel.replaceChildren(el("h2", {style: "font-size:14px;margin:0 0 10px"}, itens.length ? `${itens.length} esperando você` : "Nada esperando você"),
    ...(itens.length ? itens.slice(0, 5).map((a) => cartaoPedido(a, true)) : [el("p", {class: "vazio"}, "✓ Tudo decidido.")]),
    el("p", {style: "margin:10px 0 0"}, el("a", {class: "bt p", href: "#aprovacoes", onclick: fecharSino}, "Ver todas")));
  painel.hidden = false;
  $("sino").setAttribute("aria-expanded", "true");
  const negar = painel.querySelector(".bt.nao");
  (negar || painel.querySelector("a")).focus();
}
function fecharSino() { $("painelSino").hidden = true; $("sino").setAttribute("aria-expanded", "false"); }
$("sino").addEventListener("click", abrirSino);
document.addEventListener("click", (e) => { if (!$("painelSino").hidden && !e.target.closest("#painelSino,#sino")) fecharSino(); });
addEventListener("keydown", (e) => { if (e.key === "Escape") fecharSino(); });
$("marca").addEventListener("click", () => ir("hoje"));
$("abrirPaleta").addEventListener("click", abrirPaleta);

/* ---------------------------------------------------------- eventos vivos */
const SITUACAO = {ocioso: "dormindo", ouvindo: "ouvindo", pensando: "pensando", falando: "falando", agindo: "agindo", erro: "erro"};
Z.on("evento:situacao", (p) => {
  if (Z.estado.orbe === "ouvindo" && p.estado === "ocioso" && document.getElementById("falar")?.getAttribute("aria-pressed") === "true") return;
  mudarEstado(SITUACAO[p.estado] || "dormindo", p.detalhe && p.detalhe !== "—" ? p.detalhe : "");
});
Z.on("evento:estado", (p) => { Z.estado.retrato = p; pintarTopo(); redesenhar(); });
Z.on("evento:controles", (p) => { Z.estado.controles = p.controles || {}; });
let recarregarAutonomia = 0;
for (const tipo of ["aprovacao", "objetivo", "atividade"]) {
  Z.on("evento:" + tipo, (p) => {
    if (tipo === "aprovacao" && p.estado === "pendente" && !(Z.estado.aprovacoes || []).some((a) => a.id === p.id)) {
      anunciar(`O Zeus pede aprovação: ${p.acao}`);
    }
    clearTimeout(recarregarAutonomia);
    recarregarAutonomia = setTimeout(async () => {
      const r = await pedir("autonomia");
      if (r.ok && !r.corpo.erro) {
        Z.estado.aprovacoes = r.corpo.aprovacoes || []; Z.estado.objetivos = r.corpo.objetivos || [];
        Z.estado.atividade = r.corpo.atividade || [];
        pintarTopo(); redesenhar(); Z.emitir("aprovacoes");
      }
    }, 150);
  });
}
Z.on("retrato", () => { pintarTopo(); redesenhar(); });
Z.on("sessao_necessaria", () => { fecharFluxo(); mostrarPorta(); });

/* Pareamento: o celular pediu; o PC confirma. Foco começa em Recusar. */
Z.on("evento:pareamento", (p) => {
  const caixa = el("dialog", {class: "paleta", "aria-label": "Aprovar aparelho"});
  const responder = (aprovar) => {
    caixa.close(); caixa.remove();
    pedir(`pareamento/${p.reivindicacao}/aprovar`, {corpo: {aprovar}}).then((r) =>
      brinde(r.ok ? (aprovar ? "Aparelho aprovado." : "Aparelho recusado.") : (r.corpo && r.corpo.erro) || "Não consegui registrar."));
  };
  const recusar = el("button", {class: "bt nao", type: "button", onclick: () => responder(false)}, "Recusar");
  caixa.append(el("div", {style: "padding:18px;display:grid;gap:12px"},
    el("h2", {style: "margin:0;font-size:17px"}, `Parear “${p.nome}”?`),
    el("p", {style: "margin:0"}, "Só aprove se o celular mostrar este código:"),
    el("p", {class: "mono", style: "font-size:30px;letter-spacing:.3em;margin:0"}, p.codigo),
    el("div", {style: "display:flex;gap:8px"}, recusar, el("button", {class: "bt ok", type: "button", onclick: () => responder(true)}, "Aprovar"))));
  document.body.append(caixa);
  caixa.showModal();
  recusar.focus();
});

/* ---------------------------------------------------------------- porta */
function mostrarPorta() {
  const porta = $("porta");
  porta.hidden = false;
  registrar($("orbePorta"));
  if (!window.isSecureContext) $("notaPorta").textContent = "Sem https: a conversa funciona, mas o microfone não.";
  $("campoChave").focus();
}
$("formPorta").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await pedir("sessao", {corpo: {chave: $("campoChave").value}, semPorta: true});
  $("campoChave").value = "";
  if (!r.ok) { $("erroPorta").textContent = r.status === 429 ? "Tentativas demais. Espere 15 minutos." : "Chave inválida."; return; }
  $("porta").hidden = true;
  await iniciar();
});

/* --------------------------------------------------------------- início */
async function iniciar() {
  if (!(await recarregar())) { brinde("Não consegui ler o estado do Zeus."); }
  abrirFluxo();
  pintarTopo();
  await irPara(location.hash.slice(1) || "hoje");
}

registrarComandos([
  ...TELAS.map((t) => ({id: "ir:" + t, rotulo: "Ir para " + TITULOS[t], secao: "Navegar", acao: () => ir(t)})),
  {id: "mudo", rotulo: "Alternar mudo", secao: "Controles", acao: async () => {
    const r = await pedir("controles", {corpo: {mudo: !(Z.estado.controles || {}).mudo}});
    if (r.ok) { Z.estado.controles = r.corpo; brinde(r.corpo.mudo ? "Mudo." : "Som ligado."); }
  }},
  {id: "np60", rotulo: "Não perturbe por 1 hora", secao: "Controles", acao: () => pedir("controles", {corpo: {nao_perturbe_minutos: 60}}).then(() => brinde("Não perturbe por 1 hora."))},
  {id: "npoff", rotulo: "Desligar não perturbe", secao: "Controles", acao: () => pedir("controles", {corpo: {nao_perturbe_minutos: 0}}).then(() => brinde("Não perturbe desligado."))},
  {id: "aprovar1", rotulo: "Mostrar a primeira aprovação pendente", secao: "Aprovações", acao: () => abrirSino()},
  {id: "fezhoje", rotulo: "Perguntar: o que você fez hoje?", secao: "Zeus", acao: async () => {
    const {pedirAoZeus} = await import("./telas/conversa.js"); ir("conversa"); pedirAoZeus("O que você fez hoje?");
  }},
  {id: "sair", rotulo: "Sair deste aparelho", secao: "Sessão", perigoso: true, acao: async () => { await pedir("sair", {corpo: {}}); location.reload(); }},
]);

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/central/sw.js", {scope: "/central/"}).catch(() => {});
}

(async () => {
  const s = await pedir("sessao", {semPorta: true});
  if (s.ok && s.corpo && s.corpo.autenticado) await iniciar();
  else if (s.status === 0) { $("estadoTopo").textContent = "Sem conexão com o Zeus."; mudarEstado("offline"); mostrarPorta(); }
  else mostrarPorta();
})();
