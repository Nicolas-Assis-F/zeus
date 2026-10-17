/* Base da Central: estado observável, utilitários e a conversa com o servidor.

   Um só lugar faz pedido HTTP (ideia do apiFetch do OpenJarvis): é aqui que o
   cabeçalho anti-CSRF entra e que o 401 vira "mostrar a porta". O fluxo de
   eventos tem sequência; perdeu o fio, recarrega o retrato inteiro em vez de
   adivinhar o que faltou (bloqueador A09 da #45). */

export const $ = (id) => document.getElementById(id);

export function el(tag, atributos = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(atributos || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "dados") Object.assign(n.dataset, v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) {
    if (f === null || f === undefined || f === false) continue;
    n.append(f instanceof Node ? f : document.createTextNode(String(f)));  // nunca innerHTML com dado
  }
  return n;
}

export function novoId() {
  return (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)).replace(/-/g, "");
}

export function quando(valor) {
  if (!valor) return "";
  const d = typeof valor === "number" ? new Date(valor * 1000) : new Date(valor);
  if (isNaN(d)) return String(valor);
  const hoje = new Date();
  const mesmoDia = d.toDateString() === hoje.toDateString();
  const hora = d.toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit"});
  return mesmoDia ? hora : d.toLocaleDateString("pt-BR", {day: "2-digit", month: "2-digit"}) + " " + hora;
}

export function ha(segundos) {
  const s = Math.max(0, Math.round(segundos));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
}

export const movimentoReduzido = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export function anunciar(texto) {
  const a = $("anunciador");
  a.textContent = "";
  setTimeout(() => { a.textContent = texto; }, 30);
}

export function brinde(texto, acao) {
  document.querySelectorAll(".brinde").forEach((b) => b.remove());
  const b = el("div", {class: "brinde", role: "status"}, el("span", {}, texto));
  if (acao) b.append(el("button", {class: "bt p", type: "button", onclick: () => { b.remove(); acao.fazer(); }}, acao.rotulo));
  b.append(el("button", {class: "bt leve p", type: "button", "aria-label": "Fechar", onclick: () => b.remove()}, "✕"));
  document.body.append(b);
  setTimeout(() => b.remove(), acao ? 9000 : 5000);
}

/* ----------------------------------------------------------------- estado */
const alvo = new EventTarget();
export const Z = {
  estado: {conexao: "conectando", orbe: "dormindo", detalhe: "", seq: 0, boot: "", retrato: null,
           aprovacoes: [], objetivos: [], atividade: [], controles: {}, sistema: null},
  on(tipo, fn) { alvo.addEventListener(tipo, (e) => fn(e.detail)); },
  emitir(tipo, detalhe) { alvo.dispatchEvent(new CustomEvent(tipo, {detail: detalhe})); },
  definir(chave, valor) {
    if (Z.estado[chave] === valor) return;
    Z.estado[chave] = valor;
    Z.emitir("mudou:" + chave, valor);
  },
};

/* -------------------------------------------------------------------- api */
export async function pedir(caminho, opcoes = {}) {
  const cabecalhos = {"X-Zeus": "1", ...(opcoes.cabecalhos || {})};
  if (opcoes.corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
  let resposta;
  try {
    resposta = await fetch("/central/api/" + caminho, {
      method: opcoes.metodo || (opcoes.corpo !== undefined || opcoes.bruto ? "POST" : "GET"),
      credentials: "same-origin", cache: "no-store", headers: cabecalhos, signal: opcoes.sinal,
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

/* Envio com id do navegador: a mesma mensagem, reenviada depois de uma falha
   de rede, entra uma vez só (A01–A03). Fila cheia (503) é repetível. */
export async function enviarComId(caminho, corpo, tentativas = 3) {
  const id = corpo.id || novoId();
  for (let i = 0; i < tentativas; i++) {
    const r = await pedir(caminho, {corpo: {...corpo, id}});
    if (r.ok || (r.status && r.status !== 503)) return r;
    await new Promise((ok) => setTimeout(ok, 800 * (i + 1)));
  }
  return {ok: false, status: 503, corpo: {erro: "Não consegui entregar; tente de novo."}};
}

/* ------------------------------------------------------------------ fluxo */
let fonte = null, semConexaoDesde = null, religar = null;

export async function recarregar() {
  const r = await pedir("retrato");
  if (!r.ok || !r.corpo) { Z.emitir("retrato_indisponivel", r); return false; }
  const ret = r.corpo;
  Z.estado.boot = ret.boot;
  Z.estado.seq = ret.seq || 0;           // marca d'água tirada sob a trava do servidor
  Z.estado.retrato = ret.estado || {};
  if (ret.autonomia && !ret.autonomia.erro) {
    Z.estado.aprovacoes = ret.autonomia.aprovacoes || [];
    Z.estado.objetivos = ret.autonomia.objetivos || [];
    Z.estado.atividade = ret.autonomia.atividade || [];
    Z.estado.autonomia = "ligada";
  } else {
    Z.estado.autonomia = ret.autonomia ? "erro" : "desligada";
    Z.estado.erroAutonomia = ret.autonomia && ret.autonomia.erro;
  }
  Z.estado.controles = ret.controles || {};
  Z.estado.gastoVoz = ret.gasto_voz || null;
  Z.estado.vozAmostra = !!ret.voz_amostra;
  Z.emitir("retrato", ret);
  return true;
}

export function abrirFluxo() {
  if (fonte) fonte.close();
  clearTimeout(religar);
  // EventSource reenvia Last-Event-ID sozinho ao reconectar; na primeira vez
  // o "desde" diz de onde o retrato parou.
  fonte = new EventSource(`/central/api/eventos?desde=${Z.estado.seq}&boot=${encodeURIComponent(Z.estado.boot)}`);
  fonte.onopen = () => { semConexaoDesde = null; Z.definir("conexao", "conectado"); };
  fonte.onerror = async () => {
    if (!semConexaoDesde) semConexaoDesde = Date.now();
    Z.definir("conexao", Date.now() - semConexaoDesde > 10000 ? "sem_conexao" : "reconectando");
    if (fonte.readyState === EventSource.CLOSED) {
      const s = await pedir("sessao", {semPorta: true});
      if (s.ok && s.corpo && !s.corpo.autenticado) { Z.emitir("sessao_necessaria"); return; }
      religar = setTimeout(async () => { await recarregar(); abrirFluxo(); }, 3000);
    }
  };
  fonte.addEventListener("sessao", () => { fonte.close(); Z.emitir("sessao_necessaria"); });
  fonte.onmessage = async (evento) => {
    let p;
    try { p = JSON.parse(evento.data); } catch (e) { return; }
    if (p.tipo === "ola") {
      if (p.boot !== Z.estado.boot || p.ressincronizar) { await recarregar(); }
      return;
    }
    if (p.tipo === "ressincronizar") { fonte.close(); await recarregar(); abrirFluxo(); return; }
    if (typeof p.seq === "number") {
      if (p.seq <= Z.estado.seq) return;   // já incluído no retrato ou repetido
      Z.estado.seq = p.seq;
    }
    Z.emitir("evento:" + p.tipo, p);
  };
}

export function fecharFluxo() { if (fonte) fonte.close(); fonte = null; }
