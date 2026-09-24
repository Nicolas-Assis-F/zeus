"use strict";
/* Microfone e áudio.

   Dois caminhos de escuta, em ordem de honestidade: a escuta local (o
   navegador grava, o Zeus transcreve no próprio X99, o áudio não sai de
   casa) e o ditado do navegador, só quando a local não existe e com aviso,
   porque o áudio vai para o serviço dele. getUserMedia exige origem segura.

   "Parar áudio" para o áudio. Não finge cancelar a geração: o backend ainda
   não tem esse cancelamento. */
(function (Z) {
  let gravador = null, pedacos = [], gravando = false, limite = null, trilha = null, inicioGravacao = 0;
  let audio = null;

  const podeGravar = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  const Reconhecimento = window.SpeechRecognition || window.webkitSpeechRecognition;
  let ditado = null;

  function sinal(estado, texto) {
    Z.definir("microfone", estado);
    const s = Z.$("sinalMicrofone");
    s.className = "sinal " + ({pronto: "bom", capturando: "atencao", negado: "ruim", sem_dispositivo: "ruim",
                               origem_insegura: "ruim", indisponivel: ""}[estado] || "");
    s.querySelector(".val").textContent = texto;
    s.title = texto;
  }

  Z.voz = {
    ajustar(retrato) {
      const escuta = (retrato.capacidades || {}).escuta || {estado: retrato.ouvidos ? "pronta" : "ausente",
                                                            motivo: retrato.motivo_ouvidos};
      const local = escuta.estado === "pronta";
      if (!window.isSecureContext) sinal("origem_insegura", "microfone exige https");
      else if (!podeGravar() && !Reconhecimento) sinal("indisponivel", "navegador sem gravação");
      else if (Z.estado.microfone === "negado" || Z.estado.microfone === "sem_dispositivo") { /* mantém o motivo */ }
      else if (!gravando) sinal("pronto", local ? "microfone pronto" : (Reconhecimento ? "ditado do navegador" : "sem escuta"));
      Z.voz.local = local && podeGravar() && window.isSecureContext;
      const botao = Z.$("microfone");
      botao.disabled = !Z.voz.local && !Reconhecimento;
      botao.title = Z.voz.local ? "Gravar: transcrição local no Zeus"
        : (Reconhecimento ? "Ditado do navegador (o áudio sai deste computador)" : (escuta.motivo || "escuta indisponível"));
    },

    async alternar() {
      if (gravando) { gravador.stop(); return; }
      if (!Z.voz.local) { ditar(); return; }
      Z.audio.parar();
      try {
        trilha = await navigator.mediaDevices.getUserMedia({audio: {
          echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}});
      } catch (erro) {
        const negado = erro && (erro.name === "NotAllowedError" || erro.name === "SecurityError");
        sinal(negado ? "negado" : "sem_dispositivo", negado ? "microfone negado" : "sem microfone");
        Z.agora.avisar(negado ? "O navegador não liberou o microfone. Libere nas permissões do site."
                              : "Nenhum microfone encontrado neste aparelho.", "falhou");
        return;
      }
      gravador = new MediaRecorder(trilha, MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? {mimeType: "audio/webm;codecs=opus"} : {});
      pedacos = [];
      gravador.ondataavailable = (e) => { if (e.data && e.data.size) pedacos.push(e.data); };
      gravador.onstop = enviarGravacao;
      gravador.start();
      gravando = true; inicioGravacao = performance.now();
      Z.$("microfone").setAttribute("aria-pressed", "true");
      sinal("capturando", "gravando");
      Z.definir("interacao", "capturando");
      Z.agora.gravando(inicioGravacao);
      limite = setTimeout(() => gravando && gravador.stop(), 60000);
    },
  };

  async function enviarGravacao() {
    trilha.getTracks().forEach((t) => t.stop());
    gravando = false; clearTimeout(limite);
    Z.$("microfone").setAttribute("aria-pressed", "false");
    sinal("pronto", "microfone pronto");
    Z.definir("interacao", "pronto");
    const blob = new Blob(pedacos, {type: gravador.mimeType || "audio/webm"});
    if (blob.size < 1200) { Z.agora.avisar("Áudio curto demais; nada foi enviado.", "atencao"); return; }
    const id = Z.novoId();
    Z.conversa.local(id, "🎙 Áudio enviado — aguardando a transcrição");
    const r = await Z.api.audio(id, blob);
    if (!r.ok) {
      Z.conversa.marcar(id, "falhou", r.status === 503 ? "fila cheia" : (r.rede ? "não chegou ao Zeus" : "erro " + r.status));
      return;
    }
    Z.conversa.marcar(id, (r.corpo && r.corpo.estado) || "em_fila");
  }

  function ditar() {
    if (!Reconhecimento) { Z.agora.avisar("Sem escuta: a local não está instalada e este navegador não oferece ditado.", "atencao"); return; }
    if (!Z.ler("ditadoAceito", false)) {
      if (!window.confirm("A escuta local não está disponível. O ditado do navegador envia o áudio para o serviço dele. Usar mesmo assim?")) return;
      Z.guardar("ditadoAceito", true);
    }
    if (!ditado) {
      ditado = new Reconhecimento();
      ditado.lang = "pt-BR"; ditado.interimResults = false; ditado.continuous = false;
      ditado.onstart = () => { Z.$("microfone").setAttribute("aria-pressed", "true"); sinal("capturando", "ditado"); Z.definir("interacao", "capturando"); };
      ditado.onend = () => { Z.$("microfone").setAttribute("aria-pressed", "false"); sinal("pronto", "ditado do navegador"); Z.definir("interacao", "pronto"); };
      ditado.onerror = (e) => { if (e.error === "not-allowed") sinal("negado", "microfone negado"); };
      ditado.onresult = (e) => {
        const campo = Z.$("texto");
        campo.value = (campo.value + " " + e.results[0][0].transcript).trim();
        campo.dispatchEvent(new Event("input"));
      };
    }
    try { ditado.start(); } catch (e) { /* já estava ouvindo */ }
  }

  /* ---------------------------------------------------------------- áudio */
  Z.audio = {
    tocando: () => !!audio,
    parar() {
      if (!audio) return;
      audio.onended = null; audio.pause(); audio = null;
      Z.$("pararAudio").hidden = true;
      if (Z.estado.interacao === "falando") Z.definir("interacao", "pronto");
      Z.agora.pintar();
    },
    tocar(url) {
      Z.audio.parar();
      audio = new Audio(url);
      audio.onended = () => { audio = null; Z.$("pararAudio").hidden = true; Z.definir("interacao", "pronto"); Z.agora.pintar(); };
      return audio.play().then(() => {
        Z.$("pararAudio").hidden = false;
        Z.definir("interacao", "falando");
        Z.agora.pintar();
        return true;
      }).catch(() => { audio = null; return false; });
    },
    /* Áudio só toca sozinho para o turno mais recente desta página e
       quando ninguém está gravando. Evento antigo nunca toca num turno novo. */
    async chegou(pacote, bolhaDoTurno) {
      const doTurnoAtual = pacote.turno && pacote.turno === Z.estado.ultimoTurnoHud;
      const alvo = bolhaDoTurno && bolhaDoTurno.zeus;
      let tocou = false;
      if (doTurnoAtual && !gravando) tocou = await Z.audio.tocar(pacote.audio);
      if (!tocou && alvo && !alvo.querySelector(".ouvir")) {
        alvo._meta.appendChild(Z.el("button", {type: "button", class: "botao pequeno ouvir", texto: "▶ Ouvir",
                                               onclick: () => Z.audio.tocar(pacote.audio)}));
      }
    },
  };
})(window.Z);
