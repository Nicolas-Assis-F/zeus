/* Página do celular. O código vem no fragmento (#n=…), que nunca chega ao
   servidor nem a log; daqui ele vai por POST. Depois a página espera o PC
   aprovar e recebe o cookie do aparelho. */
const $ = (id) => document.getElementById(id);
const nonce = new URLSearchParams(location.hash.slice(1)).get("n");
history.replaceState(null, "", location.pathname);  // tira o código da barra de endereço

async function post(corpo) {
  const r = await fetch("/central/api/pareamento/reivindicar", {method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-Zeus": "1"}, body: JSON.stringify(corpo)});
  let dados = null; try { dados = await r.json(); } catch (e) {}
  return {status: r.status, dados};
}

async function reivindicar(segredo, nome) {
  const r = await post({nonce: segredo, nome});
  if (r.status !== 200) { $("erro").textContent = (r.dados && r.dados.erro) || "Código inválido ou vencido. Gere outro no PC."; return; }
  $("manual").hidden = true;
  $("msg").textContent = "Confira se o PC mostra este código e aprove lá:";
  $("codigo").hidden = false; $("codigo").textContent = r.dados.codigo_conferencia;
  const id = r.dados.reivindicacao_id;
  for (let i = 0; i < 90; i++) {
    await new Promise((ok) => setTimeout(ok, 2000));
    const b = await post({buscar: id});
    if (b.status === 200) { $("msg").textContent = "Pareado. Abrindo a Central…"; location.replace("/central/#hoje"); return; }
    if (b.status !== 202) { $("erro").textContent = "O pareamento foi recusado ou venceu."; return; }
  }
  $("erro").textContent = "O PC não aprovou a tempo. Gere outro código.";
}

if (!window.isSecureContext) $("erro").textContent = "Atenção: sem https o microfone não funciona neste aparelho.";
if (nonce) reivindicar(nonce, "Celular");
else {
  $("msg").textContent = "Digite o código que aparece na Central do PC.";
  $("manual").hidden = false;
  $("manual").addEventListener("submit", (e) => { e.preventDefault(); reivindicar($("cod").value, $("nome").value); });
}
