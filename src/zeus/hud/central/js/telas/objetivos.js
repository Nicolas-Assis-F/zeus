/* Objetivos: o quadro do que o Zeus está levando adiante sozinho.
   Quatro colunas; clicar mostra o histórico de passos e a evidência. Pausar ou
   abandonar é seu, e acorda o motor no laço principal. */
import {Z, el, pedir, quando, brinde} from "../base.js";
import {pedirAoZeus} from "./conversa.js";

const COLUNAS = [["ativo", "Ativos"], ["aguardando_nicolas", "Aguardando você"], ["bloqueado", "Bloqueados"], ["concluido", "Concluídos"]];

async function detalhar(caixa, o) {
  caixa.replaceChildren(el("p", {class: "vazio"}, "Carregando…"));
  const r = await pedir(`objetivos/${o.id}`);
  if (!r.ok) { caixa.replaceChildren(el("p", {class: "erro-txt"}, "Não consegui ler o objetivo.")); return; }
  const d = r.corpo;
  const mudar = (estado) => pedir(`objetivos/${o.id}/estado`, {corpo: {estado}}).then((x) =>
    brinde(x.ok ? "Pedido entregue ao Zeus." : (x.corpo && x.corpo.erro) || "Não consegui."));
  caixa.replaceChildren(el("section", {class: "cartao detalhe"},
    el("h2", {}, `#${d.id} ${d.titulo}`, el("span", {class: "n"}, d.estado)),
    el("p", {}, el("b", {}, "Pedido: "), d.pedido_original || "—"),
    el("p", {}, el("b", {}, "Próxima ação: "), d.proxima_acao || "—", d.prazo ? `  ·  prazo ${quando(d.prazo)}` : ""),
    d.evidencia ? el("p", {}, el("b", {}, "Evidência: "), String(d.evidencia)) : null,
    el("h2", {}, "Passos", el("span", {class: "n"}, String((d.passos || []).length))),
    (d.passos || []).length ? el("ul", {class: "passos"}, d.passos.map((p) => el("li", {dados: {e: p.estado}},
      el("b", {}, p.descricao || p.acao), el("span", {class: "meta"}, `${p.estado} · ${p.acao} · ${quando(p.terminado_em || p.criado_em)}`),
      p.resultado ? el("div", {class: "meta"}, String(p.resultado).slice(0, 300)) : null))) : el("p", {class: "vazio"}, "Nenhum passo ainda."),
    el("div", {class: "acoes", style: "display:flex;gap:8px;margin-top:12px;flex-wrap:wrap"},
      d.estado !== "ativo" && d.estado !== "concluido" ? el("button", {class: "bt p", type: "button", onclick: () => mudar("ativo")}, "Retomar") : null,
      d.estado === "ativo" ? el("button", {class: "bt p", type: "button", onclick: () => mudar("bloqueado")}, "Pausar") : null,
      d.estado !== "concluido" && d.estado !== "abandonado" ? el("button", {class: "bt nao p", type: "button", onclick: () => mudar("abandonado")}, "Abandonar") : null)));
}

export function montar(raiz) {
  const desenhar = () => {
    const objetivos = Z.estado.objetivos || [];
    const caixa = el("div");
    const novo = el("form", {style: "display:flex;gap:8px;margin:0 0 16px;flex-wrap:wrap", onsubmit: (e) => {
      e.preventDefault(); const t = campo.value.trim(); if (!t) return; campo.value = "";
      pedirAoZeus("Novo objetivo: " + t);
    }});
    const campo = el("input", {type: "text", placeholder: "Novo objetivo, ex.: renegociar o frete da importação até sexta",
      style: "flex:1;min-width:240px", "aria-label": "Novo objetivo"});
    novo.append(campo, el("button", {class: "bt pri", type: "submit"}, "Pedir ao Zeus"));
    raiz.replaceChildren(el("div", {class: "tela", style: "max-width:none"},
      el("h1", {}, "Objetivos"),
      el("p", {class: "sub"}, "O que o Zeus leva adiante sozinho, por dias se for preciso. Ele só para no que é irreversível."),
      Z.estado.autonomia !== "ligada" ? el("p", {class: "vazio"}, "A autonomia ainda não está ligada neste Zeus.") : novo,
      el("div", {class: "quadro"}, COLUNAS.map(([estado, titulo]) => {
        const deles = objetivos.filter((o) => o.estado === estado || (estado === "concluido" && o.estado === "abandonado"));
        return el("section", {class: "coluna", "aria-label": titulo}, el("h2", {}, `${titulo} · ${deles.length}`),
          deles.length ? deles.map((o) => el("article", {class: "objetivo", tabindex: "0", role: "button",
              onclick: () => detalhar(caixa, o), onkeydown: (e) => { if (e.key === "Enter") detalhar(caixa, o); }},
            el("b", {}, o.titulo), el("div", {class: "prox"}, o.estado === "abandonado" ? "abandonado"
              : o.estado === "concluido" ? "✓ " + String(o.evidencia || "concluído").slice(0, 90) : (o.proxima_acao || "—"))))
            : el("p", {class: "vazio"}, "—"));
      })),
      caixa));
  };
  desenhar();
  return {atualizar: desenhar};
}
