/* Conversa: texto e voz no mesmo lugar.
   Resposta em fluxo com cursor; rascunho descartado some (o servidor manda
   "reiniciar" quando o modelo desiste do texto para usar ferramenta). As
   etapas aparecem enquanto ele trabalha, e "Deixa comigo, senhor" também. */
import {Z, el, enviarComId, quando, brinde} from "../base.js";
import {registrar, ROTULOS} from "../orbe.js";
import {ligarBotao, podeGravar, motivoSemMicrofone, tocar, urlDoAudio} from "../voz.js";

let historico = null, bolha = null, etapas = null;

function fala(de, texto, hora) {
  const classe = de === "zeus" ? "zeus" : de === "sistema" ? "sistema" : "nicolas";
  const n = el("div", {class: "fala " + classe}, texto);
  if (classe !== "sistema") n.append(el("span", {class: "hora"}, hora || new Date().toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit"})));
  historico.append(n);
  historico.scrollTop = historico.scrollHeight;
  return n;
}

function fluir(pedaco) {
  if (!bolha) { bolha = el("div", {class: "fala zeus fluindo"}); bolha.dataset.t = ""; historico.append(bolha); }
  bolha.dataset.t += pedaco;
  bolha.textContent = bolha.dataset.t;
  historico.scrollTop = historico.scrollHeight;
}
function descartar() { if (bolha) bolha.remove(); bolha = null; }

function etapa(texto) {
  if (!etapas) { etapas = el("div", {class: "etapas", "aria-live": "polite"}); historico.append(etapas); }
  etapas.append(el("details", {}, el("summary", {}, "⚙ " + texto)));
  historico.scrollTop = historico.scrollHeight;
}

export function montar(raiz) {
  const orbe = el("canvas", {width: 128, height: 128, "aria-hidden": "true"});
  const estado = el("div", {class: "o-estado"}), detalhe = el("div", {class: "o-detalhe"});
  historico = el("div", {class: "historico", role: "log", "aria-label": "Histórico da conversa", tabindex: "0"});
  const texto = el("textarea", {id: "texto", rows: 1, placeholder: "Fale com o Zeus…", enterkeyhint: "send", "aria-label": "Mensagem"});
  const botaoFalar = el("button", {class: "bt falar", id: "falar", type: "button", "aria-pressed": "false",
    title: podeGravar() ? "Segure para falar (Ctrl+Espaço)" : motivoSemMicrofone()}, "🎙");
  const nota = el("p", {class: "nota"}, podeGravar() ? "Segure 🎙 ou Ctrl+Espaço para falar. Arraste para fora para cancelar."
                                                     : motivoSemMicrofone());
  const enviar = async (e) => {
    if (e) e.preventDefault();
    const t = texto.value.trim();
    if (!t) return;
    texto.value = "";
    fala("nicolas", t);
    const r = await enviarComId("mensagem", {texto: t});
    if (!r.ok) { fala("sistema", (r.corpo && r.corpo.erro) || "A mensagem não chegou ao Zeus."); texto.value = t; }
  };
  texto.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) enviar(e); });
  texto.addEventListener("input", () => { texto.style.height = "auto"; texto.style.height = Math.min(texto.scrollHeight, 180) + "px"; });
  raiz.replaceChildren(el("div", {class: "conversa"},
    el("div", {class: "faixa"}, orbe, el("div", {}, estado, detalhe)),
    historico,
    el("form", {class: "entrada", onsubmit: enviar},
      el("canvas", {class: "onda", id: "onda", "aria-hidden": "true"}),
      el("div", {class: "linha-entrada"}, texto, botaoFalar, el("button", {class: "bt pri", type: "submit"}, "Enviar")),
      nota)));
  registrar(orbe);
  if (podeGravar()) ligarBotao(botaoFalar); else botaoFalar.disabled = true;
  const turnos = (Z.estado.retrato || {}).turnos || [];
  if (!turnos.length) fala("sistema", "Ainda não conversamos. Escreva ou segure 🎙 para falar.");
  for (const t of turnos) fala(t.papel === "zeus" ? "zeus" : "nicolas", t.texto, quando(t.em));
  const pintarEstado = () => { estado.textContent = ROTULOS[Z.estado.orbe] || "Pronto"; detalhe.textContent = Z.estado.detalhe || ""; };
  pintarEstado();
  const fns = [
    ["mudou:orbe", pintarEstado], ["mudou:detalhe", pintarEstado],
    ["evento:mensagem", (p) => {
      if (p.de === "nicolas" && historico.lastElementChild && historico.lastElementChild.textContent.startsWith(p.texto)) return;
      if (p.de === "zeus") { descartar(); if (etapas) { etapas = null; } }
      fala(p.de, p.texto, p.hora);
    }],
    ["evento:fluxo", (p) => { if (p.reiniciar) descartar(); else fluir(p.pedaco || ""); }],
    ["evento:situacao", (p) => { if (p.estado === "pensando" && p.detalhe && p.detalhe !== "gerando resposta") etapa(p.detalhe); }],
    ["evento:audio", (p) => { if (Z.estado.controles && Z.estado.controles.mudo) return; tocar(urlDoAudio(p.audio)); }],
  ];
  for (const [t, f] of fns) Z.on(t, (d) => { if (historico && historico.isConnected) f(d); });
  texto.focus({preventScroll: true});
  return {desmontar() { historico = null; bolha = null; etapas = null; }};
}

export function pedirAoZeus(texto) {
  return enviarComId("mensagem", {texto}).then((r) => {
    if (r.ok) brinde("Pedido entregue ao Zeus."); else brinde((r.corpo && r.corpo.erro) || "Não entreguei o pedido.");
    return r;
  });
}
