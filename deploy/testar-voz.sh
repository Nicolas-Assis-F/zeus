#!/usr/bin/env bash
# Autoteste de voz e escuta, de ponta a ponta, na máquina onde o Zeus roda.
#
# Existe porque "a voz não funciona" tem seis causas possíveis — binário errado
# no PATH, modelo ausente, caminho com typo, microfone mudo, pacote de escuta
# faltando, áudio sem saída — e do lado de fora todas parecem iguais. Cada
# etapa aqui falha sozinha, com o motivo e o que fazer.
#
#   ./deploy/testar-voz.sh                 usa o microfone padrão do sistema
#   ./deploy/testar-voz.sh --listar        só mostra os microfones e sai
#   ./deploy/testar-voz.sh --fonte NOME    grava de uma fonte específica
set -uo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="${XDG_CONFIG_HOME:-$HOME/.config}/zeus/config.json"
trabalho="$(mktemp -d)"
trap 'rm -rf "$trabalho"' EXIT

verde() { printf "  \033[32mok\033[0m    %s\n" "$1"; }
vermelho() { printf "  \033[31mfalhou\033[0m %s\n" "$1"; }
aviso() { printf "        %s\n" "$1"; }
etapa() { printf "\n%s\n" "$1"; }

ler_config() {  # $1 = chave
  python3 - "$config" "$1" <<'PY' 2>/dev/null
import json, sys
try:
    print(json.load(open(sys.argv[1])).get(sys.argv[2], "") or "")
except Exception:
    print("")
PY
}

fonte=""
case "${1:-}" in
  --listar)
    echo "Microfones que o sistema enxerga:"
    pactl list short sources 2>/dev/null | grep -v "\.monitor" || arecord -l 2>/dev/null
    echo
    echo "A webcam costuma aparecer com 'usb' ou o nome do fabricante no identificador."
    echo "Use: ./deploy/testar-voz.sh --fonte <nome-da-fonte>"
    exit 0 ;;
  --fonte) fonte="${2:-}" ;;
esac

falhas=0

etapa "1. Configuração"
if [ -f "$config" ]; then
  verde "config em $config"
else
  vermelho "não achei $config"
  aviso "copie config/config.example.json para lá e preencha"
  exit 1
fi

binario="$(ler_config voz_binario)"; binario="${binario:-piper}"
modelo="$(ler_config voz_modelo)"

etapa "2. Piper (voz que sai)"
if [ -x "$binario" ] || command -v "$binario" >/dev/null 2>&1; then
  caminho_real="$(command -v "$binario" || echo "$binario")"
  verde "binário em $caminho_real"
  # O Ubuntu distribui um 'piper' de configuração de mouse com o mesmo nome.
  if "$caminho_real" --help 2>&1 | grep -qi "onnx\|model"; then
    verde "responde como Piper de voz"
  else
    vermelho "esse 'piper' não é o de voz (provavelmente o configurador de mouse)"
    aviso "instale com: pip install piper-tts --break-system-packages"
    aviso "e aponte voz_binario para \$HOME/.local/bin/piper"
    falhas=$((falhas+1))
  fi
else
  vermelho "binário '$binario' não encontrado"; falhas=$((falhas+1))
fi

if [ -n "$modelo" ] && [ -f "$modelo" ]; then
  verde "modelo de voz em $modelo"
  [ -f "$modelo.json" ] || { vermelho "falta $modelo.json ao lado do .onnx"; falhas=$((falhas+1)); }
else
  vermelho "voz_modelo vazio ou arquivo inexistente: '${modelo:-vazio}'"
  aviso "confira nome e extensão: pt_BR-<voz>-medium.onnx"
  falhas=$((falhas+1))
fi

etapa "3. Falar"
frase="Boa noite, senhor. Estou ouvindo."
if [ $falhas -eq 0 ]; then
  if echo "$frase" | "$caminho_real" -m "$modelo" -f "$trabalho/fala.wav" 2>"$trabalho/erro-voz"; then
    verde "sintetizou $(du -h "$trabalho/fala.wav" | cut -f1)"
    paplay "$trabalho/fala.wav" 2>/dev/null || aplay -q "$trabalho/fala.wav" 2>/dev/null \
      || aviso "não consegui tocar; ouça depois em $trabalho/fala.wav"
  else
    vermelho "piper falhou: $(head -2 "$trabalho/erro-voz" | tr '\n' ' ')"; falhas=$((falhas+1))
  fi
else
  aviso "pulado: corrija as etapas acima"
fi

etapa "4. Microfone"
if command -v parecord >/dev/null 2>&1; then
  gravar=(parecord --channels=1 --rate=16000 --file-format=wav)
  [ -n "$fonte" ] && gravar+=(--device="$fonte")
elif command -v arecord >/dev/null 2>&1; then
  gravar=(arecord -q -f S16_LE -c 1 -r 16000)
  [ -n "$fonte" ] && gravar+=(-D "$fonte")
else
  vermelho "nem parecord nem arecord instalados"; gravar=()
fi

if [ ${#gravar[@]} -gt 0 ]; then
  echo "        fale alguma coisa agora — gravando 5 segundos..."
  timeout 5 "${gravar[@]}" "$trabalho/voce.wav" 2>/dev/null
  tamanho=$(stat -c%s "$trabalho/voce.wav" 2>/dev/null || echo 0)
  if [ "$tamanho" -gt 20000 ]; then
    verde "gravou $tamanho bytes"
    # Um arquivo cheio de silêncio tem o mesmo tamanho de um com voz.
    nivel=$(python3 - "$trabalho/voce.wav" <<'PY' 2>/dev/null
import audioop, sys, wave
try:
    with wave.open(sys.argv[1]) as w:
        print(audioop.rms(w.readframes(w.getnframes()), w.getsampwidth()))
except Exception:
    print(0)
PY
)
    if [ "${nivel:-0}" -gt 300 ]; then
      verde "tem som de verdade (nível $nivel)"
    else
      vermelho "gravou só silêncio (nível ${nivel:-0})"
      aviso "microfone mudo ou fonte errada. Veja: ./deploy/testar-voz.sh --listar"
      falhas=$((falhas+1))
    fi
  else
    vermelho "gravação vazia"; falhas=$((falhas+1))
  fi
fi

etapa "5. Entender (escuta local)"
if [ -s "$trabalho/voce.wav" ]; then
  if (cd "$raiz" && ./zeus medir-escuta "$trabalho/voce.wav" --repeticoes 1); then
    verde "transcreveu"
  else
    vermelho "a escuta falhou"
    aviso "instale com: pip install faster-whisper --break-system-packages"
    aviso "e prepare o modelo: ./zeus preparar-escuta"
    falhas=$((falhas+1))
  fi
fi

etapa "Resultado"
if [ $falhas -eq 0 ]; then
  printf "  Voz e escuta prontas. Suba o serviço e abra a interface.\n\n"
else
  printf "  %d etapa(s) com problema. Corrija de cima para baixo.\n\n" "$falhas"
fi
exit $falhas
