/* Hoje: o que o Zeus está fazendo, o que ele precisa de você, se está tudo bem.
   Cada cartão diz de onde vem o dado; o que não tem evidência fica apagado. */
import {Z, el, quando, ha} from "../base.js";
import {registrar, ROTULOS} from "../orbe.js";

function saudacao() {
  const h = new Date().getHours();
  return h < 5 ? "Boa madrugada, senhor." : h < 12 ? "Bom dia, senhor." : h < 18 ? "Boa tarde, senhor." : "Boa noite, senhor.";
}

function cartao(titulo, conteudo, n, semEvidencia) {
  return el("section", {class: "cartao" + (semEvidencia ? " sem-evidencia" : "")},
    el("h2", {}, titulo, n !== undefined && n !== null ? el("span", {class: "n"}, String(n)) : null), conteudo);
}

function lista(itens, vazio, formatar) {
  if (!itens || !itens.length) return el("p", {class: "vazio"}, vazio);
  return el("ul", {class: "lista"}, itens.slice(0, 8).map((i) => el("li", {}, ...formatar(i))));
}

export function montar(raiz) {
  const desenhar = () => {
    const r = Z.estado.retrato || {};
    const agora = Date.now() / 1000;
    const hojeFim = new Date(); hojeFim.setHours(23, 59, 59, 999);
    const agenda = (r.lembretes || []).filter((l) => new Date(l.vence_em) <= hojeFim);
    const ativos = (Z.estado.objetivos || []).filter((o) => ["ativo", "aguardando_nicolas", "bloqueado"].includes(o.estado));
    const aprov = Z.estado.aprovacoes || [];
    const alertas = (r.entregas || []).filter((e) => ["incerta", "falhou", "expirada"].includes(e.situacao));
    const orbe = el("canvas", {width: 256, height: 256, "aria-hidden": "true"});
    raiz.replaceChildren(el("div", {class: "tela"},
      el("div", {class: "heroi"}, orbe,
        el("div", {},
          el("h1", {}, saudacao()),
          el("p", {class: "sub"}, `${ROTULOS[Z.estado.orbe] || "Pronto"}. `,
            aprov.length ? `${aprov.length} pedido(s) esperando sua aprovação. ` : "Nada esperando sua aprovação. ",
            ativos.length ? `${ativos.length} objetivo(s) em andamento.` : ""))),
      el("div", {class: "grade"},
        cartao("Precisa de você", lista(aprov, "Nenhum pedido pendente.", (a) => [
          el("b", {}, a.acao), " — ", a.alvo || "",
          el("span", {class: "meta"}, (a.origem || "").startsWith("externo") ? `veio de conteúdo externo · ` : "",
             `código ${a.codigo} · vence em ${ha((a.expira_em || agora) - agora)}`),
          el("div", {class: "acoes"}, el("a", {class: "bt p", href: "#aprovacoes"}, "Decidir"))]),
          aprov.length, Z.estado.autonomia !== "ligada"),
        cartao("Agenda de hoje", lista(agenda, "Nada marcado para hoje.", (l) => [
          l.texto, el("span", {class: "meta"}, new Date(l.vence_em) < new Date() ? "atrasado · " + quando(l.vence_em) : quando(l.vence_em))]),
          agenda.length),
        cartao("Objetivos em andamento", lista(ativos, Z.estado.autonomia === "ligada" ? "Nenhum objetivo ativo. Peça um na conversa." :
          "A autonomia ainda não está ligada neste Zeus.", (o) => [
          el("b", {}, o.titulo), el("span", {class: "meta"}, `${o.estado.replace("_", " ")} · próxima: ${o.proxima_acao || "—"}`)]),
          ativos.length, Z.estado.autonomia !== "ligada"),
        cartao("Perguntas do Zeus", lista(r.perguntas, "Nenhuma pergunta aberta.", (p) => [p.texto, el("span", {class: "meta"}, p.situacao + " · " + quando(p.vence_em))]),
          (r.perguntas || []).length),
        cartao("Alertas", lista(alertas, "Nenhuma entrega com problema.", (e) => [e.texto, el("span", {class: "meta"}, `${e.situacao} · ${e.motivo || ""}`)]),
          alertas.length),
        cartao("Conversa recente", lista((r.turnos || []).slice(-4).reverse(), "Ainda não conversamos.", (t) => [
          el("b", {}, t.papel === "zeus" ? "Zeus: " : "Você: "), String(t.texto).slice(0, 160),
          el("span", {class: "meta"}, `${t.canal} · ${quando(t.em)}`)])))));
    registrar(orbe);
  };
  desenhar();
  return {atualizar: desenhar};
}
