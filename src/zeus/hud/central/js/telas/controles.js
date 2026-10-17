/* Controles: o que se mexe no dia a dia, sem reiniciar o Zeus.
   Interruptor sem estado conhecido fica neutro (ideia do Mark-LV). Cada mudança
   é otimista: se o servidor recusar, volta e avisa. Parear o celular fica aqui. */
import {Z, el, pedir, brinde, quando} from "../base.js";
import {tocar} from "../voz.js";

function chave(rotulo, explicacao, valor, mudar) {
  const b = el("button", {class: "chave", type: "button", role: "switch",
    "aria-checked": valor === undefined || valor === null ? "mixed" : String(!!valor), "aria-label": rotulo});
  b.addEventListener("click", () => {
    const novo = b.getAttribute("aria-checked") !== "true";
    b.setAttribute("aria-checked", String(novo));
    mudar(novo).then((ok) => { if (!ok) b.setAttribute("aria-checked", String(!novo)); });
  });
  return el("div", {class: "ajuste"}, el("label", {}, rotulo, el("span", {class: "exp"}, explicacao)), b);
}

async function aplicar(mudanca) {
  const r = await pedir("controles", {corpo: mudanca});
  if (r.ok) { Z.estado.controles = r.corpo; return true; }
  brinde((r.corpo && r.corpo.erro) || "Não consegui mudar o ajuste.");
  return false;
}

async function parear(caixa) {
  caixa.replaceChildren(el("p", {class: "vazio"}, "Gerando o código…"));
  const r = await pedir("pareamento/iniciar", {corpo: {}});
  if (!r.ok) { caixa.replaceChildren(el("p", {class: "erro-txt"}, (r.corpo && r.corpo.erro) || "Pareamento indisponível.")); return; }
  const qr = el("div", {class: "qr", role: "img", "aria-label": "QR para parear o celular"});
  // O SVG vem do próprio servidor (gerado em Python puro) e só tem <path>.
  qr.append(new DOMParser().parseFromString(r.corpo.qr_svg, "image/svg+xml").documentElement);
  caixa.replaceChildren(el("div", {style: "display:flex;gap:16px;flex-wrap:wrap;align-items:center"}, qr,
    el("div", {}, el("p", {}, "Escaneie com a câmera do celular, na mesma rede de casa."),
      el("p", {}, "Ou abra ", el("code", {}, location.origin + "/central/parear"), " e digite ", el("b", {class: "mono"}, r.corpo.codigo_manual)),
      el("p", {class: "nota"}, `Vale até ${quando(r.corpo.expira_em)}. Depois, confirme aqui os 4 dígitos que aparecerem no celular.`))));
}

export function montar(raiz) {
  const c = Z.estado.controles || {};
  const npMin = el("select", {"aria-label": "Duração do não perturbe"},
    [["0", "desligado"], ["30", "30 minutos"], ["60", "1 hora"], ["120", "2 horas"], ["480", "8 horas"]].map(([v, r]) => el("option", {value: v}, r)));
  npMin.addEventListener("change", () => aplicar({nao_perturbe_minutos: Number(npMin.value)}).then((ok) => ok && brinde(Number(npMin.value) ? "Não perturbe ligado." : "Não perturbe desligado.")));
  const volume = el("input", {type: "range", min: "0", max: "1", step: "0.05", value: c.volume ?? 0.6, "aria-label": "Volume"});
  volume.addEventListener("change", () => aplicar({volume: Number(volume.value)}));
  const autonomia = el("fieldset", {}, el("legend", {}, "Nível de autonomia"),
    [["conservadora", "Pergunta antes de quase tudo que muda alguma coisa."],
     ["normal", "Faz o reversível e avisa; pergunta o irreversível e o que fala em seu nome."],
     ["ousada", "Faz mais coisa sozinho. O irreversível continua pedindo aprovação, sempre."]].map(([v, exp]) =>
      el("label", {}, el("input", {type: "radio", name: "autonomia", value: v, checked: (c.autonomia || "normal") === v,
        onchange: () => aplicar({autonomia: v})}), el("span", {}, el("b", {}, v), el("span", {class: "exp"}, exp)))));
  const caixaPar = el("div");
  const caixaApar = el("div");
  const tetoVoz = el("input", {type: "number", min: "0", step: "1000", value: c.teto_voz_caracteres ?? "", placeholder: "padrão", style: "width:130px"});
  tetoVoz.addEventListener("change", () => aplicar({teto_voz_caracteres: tetoVoz.value === "" ? null : Number(tetoVoz.value)}));
  const tetoMod = el("input", {type: "number", min: "0", step: "0.5", value: c.teto_modelo_usd ?? "", placeholder: "sem teto", style: "width:130px"});
  tetoMod.addEventListener("change", () => aplicar({teto_modelo_usd: tetoMod.value === "" ? null : Number(tetoMod.value)}));
  raiz.replaceChildren(el("div", {class: "tela"},
    el("h1", {}, "Controles"),
    el("p", {class: "sub"}, "Ajustes do dia a dia. Valem na hora, sem reiniciar o Zeus."),
    el("div", {class: "grade"},
      el("section", {class: "cartao"}, el("h2", {}, "Voz e som"),
        el("div", {class: "ajuste"}, el("label", {}, "Ouvir a voz atual", el("span", {class: "exp"}, "Uma frase curta, sintetizada agora.")),
          el("button", {class: "bt p", type: "button", disabled: !Z.estado.vozAmostra, onclick: async () => {
            const r = await pedir("voz/amostra", {corpo: {}});
            if (r.ok) tocar(r.corpo.audio); else brinde((r.corpo && r.corpo.erro) || "Sem voz agora.");
          }}, "▶ Ouvir")),
        el("div", {class: "ajuste"}, el("label", {}, "Volume do alto-falante", el("span", {class: "exp"}, "O da sala, no X99.")), volume),
        chave("Mudo", "O Zeus não fala na sala nem toca áudio aqui.", c.mudo, (v) => aplicar({mudo: v})),
        chave("Palavra de ativação", "\"Hey Jarvis\" pelo microfone da sala. Precisa do viva-voz para funcionar bem.", c.palavra_ativacao, (v) => aplicar({palavra_ativacao: v}))),
      el("section", {class: "cartao"}, el("h2", {}, "Interrupções"),
        el("div", {class: "ajuste"}, el("label", {}, "Não perturbe", el("span", {class: "exp"},
          c.nao_perturbe ? `ligado até ${quando(c.nao_perturbe_ate)}. Só o crítico passa.` : "Só o crítico passa enquanto estiver ligado.")), npMin),
        chave("Falar na sala", "Avisos podem ser falados no X99.", (c.canais || {}).sala, (v) => aplicar({canais: {sala: v}})),
        chave("Avisar no grupo", "Avisos podem ir para o grupo do WhatsApp.", (c.canais || {}).grupo, (v) => aplicar({canais: {grupo: v}}))),
      el("section", {class: "cartao"}, el("h2", {}, "Autonomia e tetos"), autonomia,
        el("div", {class: "ajuste"}, el("label", {}, "Teto de voz por dia", el("span", {class: "exp"}, "caracteres falados pela ElevenLabs")), tetoVoz),
        el("div", {class: "ajuste"}, el("label", {}, "Teto de modelo por dia", el("span", {class: "exp"}, "US$, somando o que os objetivos gastam")), tetoMod)),
      el("section", {class: "cartao"}, el("h2", {}, "Celular"),
        el("p", {class: "nota"}, "Pareie o celular para abrir a Central nele. Só pela rede de casa."),
        el("div", {style: "display:flex;gap:8px;flex-wrap:wrap"},
          el("button", {class: "bt pri p", type: "button", onclick: () => parear(caixaPar)}, "Parear celular"),
          el("button", {class: "bt p", type: "button", onclick: () => aparelhos(caixaApar)}, "Aparelhos pareados")),
        caixaPar, caixaApar))));
  npMin.value = "0";
}

async function aparelhos(caixa) {
  const r = await pedir("aparelhos");
  if (!r.ok) { caixa.replaceChildren(el("p", {class: "erro-txt"}, (r.corpo && r.corpo.erro) || "Indisponível.")); return; }
  const lista = r.corpo.aparelhos || [];
  caixa.replaceChildren(!lista.length ? el("p", {class: "vazio"}, "Nenhum aparelho pareado.") :
    el("ul", {class: "lista"}, lista.map((a) => el("li", {}, el("b", {}, a.nome || "aparelho"),
      el("span", {class: "meta"}, `pareado ${quando(a.criado_em)} · último uso ${quando(a.ultimo_uso)}${a.revogado ? " · revogado" : ""}`),
      a.revogado ? null : el("div", {class: "acoes"}, el("button", {class: "bt nao p", type: "button", onclick: async () => {
        await pedir(`aparelhos/${a.id}/revogar`, {corpo: {}}); aparelhos(caixa);
      }}, "Revogar"))))));
}
