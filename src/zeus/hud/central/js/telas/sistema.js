/* Sistema: serviços e pontes, hardware, modelo em uso e gasto do dia.
   Nada vira zero por educação: medida ausente aparece como "—". */
import {Z, el, pedir, ha} from "../base.js";

const NOMES = {"zeus": "Zeus", "ponte-principal": "Ponte do número principal", "ponte-zeus": "Ponte do número do Zeus",
               "zeus-vigia.timer": "Vigia do serviço (10 min)"};
const gb = (b) => b === null || b === undefined ? "—" : (b / 1024 ** 3).toFixed(1) + " GB";
const pct = (v) => v === null || v === undefined ? "—" : Math.round(v) + "%";

function barra(valor, alto = 75, critico = 90) {
  const v = Math.max(0, Math.min(100, valor || 0));
  return el("div", {class: "barra-uso", "aria-hidden": "true"}, el("i", {class: v >= critico ? "critico" : v >= alto ? "alto" : "", style: `width:${v}%`}));
}
const medida = (rot, val) => el("div", {class: "medida"}, el("span", {}, rot), el("span", {class: "v"}, val));

export function montar(raiz) {
  let parar = false;
  const desenhar = async () => {
    const r = await pedir("sistema");
    if (!raiz.isConnected) { parar = true; return; }
    if (!r.ok) { raiz.replaceChildren(el("div", {class: "tela"}, el("h1", {}, "Sistema"), el("p", {class: "erro-txt"}, "Não consegui ler o sistema agora."))); return; }
    const s = r.corpo, saude = s.saude || {}, cpu = saude.cpu || {}, mem = saude.memoria || {}, gpu = (saude.gpu || [])[0] || {};
    const disco = ((saude.disco || {}).estado) || {};
    const ret = Z.estado.retrato || {};
    const gasto = s.gasto_voz || Z.estado.gastoVoz;
    const ruins = Object.entries(s.servicos || {}).filter(([, v]) => v !== "active").length;
    document.getElementById("navSis").textContent = ruins ? `${ruins}!` : "";
    document.getElementById("navSis").className = "n" + (ruins ? " ruim" : "");
    raiz.replaceChildren(el("div", {class: "tela"},
      el("h1", {}, "Sistema"),
      el("p", {class: "sub"}, `X99 ligado há ${saude.tempo_ligado_s ? ha(saude.tempo_ligado_s) : "—"}.`),
      el("div", {class: "grade"},
        el("section", {class: "cartao"}, el("h2", {}, "Serviços", el("span", {class: "n"}, ruins ? `${ruins} com problema` : "todos de pé")),
          Object.entries(s.servicos || {}).map(([nome, estado]) => el("div", {class: "medida"},
            el("span", {}, el("i", {class: "bolinha " + (estado === "active" ? "ok" : estado === "activating" ? "aviso" : "ruim")}), NOMES[nome] || nome),
            el("span", {class: "v"}, estado)))),
        el("section", {class: "cartao"}, el("h2", {}, "Modelo"),
          medida("Conversa", ret.modelo || "—"),
          medida("Degrau da escada", ret.degrau ? `${ret.degrau}º` : (ret.modelo ? "1º (principal)" : "—")),
          medida("Voz", ret.voz_origem || (ret.voz ? "pronta" : "sem voz")),
          medida("Escuta", ret.escuta_origem || (ret.ouvidos ? "pronta" : "sem escuta")),
          medida("Gasto de modelo hoje", ret.custo_hoje !== undefined && ret.custo_hoje !== null ? `US$ ${Number(ret.custo_hoje).toFixed(3)}` : "—")),
        el("section", {class: "cartao"}, el("h2", {}, "Voz remota hoje"),
          gasto ? [medida("Caracteres falados", String(gasto.caracteres)), medida("Segundos ouvidos", String(Math.round(gasto.segundos))),
                   medida("Estimado (preço cheio)", `US$ ${Number(gasto.usd_estimado || 0).toFixed(3)}`)]
                : el("p", {class: "vazio"}, "Voz remota desligada ou sem uso hoje.")),
        el("section", {class: "cartao"}, el("h2", {}, "Processador e vídeo"),
          medida("CPU", `${pct(cpu.uso)} · ${cpu.celsius ?? "—"} °C`), barra(cpu.uso),
          medida("GPU", `${pct(gpu.uso)} · ${gpu.celsius ?? "—"} °C`), barra(gpu.uso),
          medida("VRAM", `${gb(gpu.memoria_usada)} de ${gb(gpu.memoria_total)}`), barra(gpu.percentual_memoria, 90, 97)),
        el("section", {class: "cartao"}, el("h2", {}, "Memória e disco"),
          medida("RAM", `${gb(mem.usada)} de ${gb(mem.total)}`), barra(mem.percentual, 80, 92),
          medida("Swap", mem.troca_total ? `${gb(mem.troca_usada)} de ${gb(mem.troca_total)}` : "—"),
          medida("Disco do Zeus", `${gb(disco.livre)} livres`), barra(disco.percentual, 85, 92)))));
    if (!parar) setTimeout(desenhar, 5000);
  };
  raiz.replaceChildren(el("div", {class: "tela"}, el("h1", {}, "Sistema"), el("p", {class: "vazio"}, "Carregando…")));
  desenhar();
  return {desmontar() { parar = true; }};
}
