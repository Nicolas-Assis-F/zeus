#!/usr/bin/env bash
# Prepara as duas pontes do WhatsApp no X99. Pode rodar de novo sem estragar
# nada: não pareia número, não liga serviço, não toca em sessão existente.
#
# Uso:  deploy/whatsapp/instalar.sh [--historico CAMINHO/messages.db]
#
# --historico copia o banco de mensagens da ponte do PC para a ponte do
# número principal, para não perder o que já foi capturado. Só o messages.db:
# a sessão (whatsapp.db) nunca é copiada, porque a mesma sessão em duas
# máquinas dá conflito. O X99 é pareado como um aparelho novo.
set -euo pipefail

REPO="https://github.com/lharries/whatsapp-mcp"
VERSAO="7d6a06d"   # commit em que o patch foi feito e conferido
AQUI="$(cd "$(dirname "$0")" && pwd)"
DESTINO="$HOME/whatsapp-mcp"
PONTES="$HOME/pontes"
UNIDADES="$HOME/.config/systemd/user"
HISTORICO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --historico) HISTORICO="$2"; shift 2 ;;
    *) echo "Opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

falta=()
for programa in git go gcc python3 uv; do
  command -v "$programa" >/dev/null 2>&1 || falta+=("$programa")
done
if [ ${#falta[@]} -gt 0 ]; then
  echo "Faltam programas: ${falta[*]}" >&2
  echo "go: https://go.dev/dl  |  uv: https://docs.astral.sh/uv  |  gcc: apt install build-essential" >&2
  exit 1
fi

if [ ! -d "$DESTINO/.git" ]; then
  git clone "$REPO" "$DESTINO"
fi
cd "$DESTINO"
if git apply --reverse --check "$AQUI/whatsapp-mcp.patch" 2>/dev/null; then
  echo "Patch já aplicado em $DESTINO."
else
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "$DESTINO tem alterações que não são deste patch. Confira antes de seguir." >&2
    exit 1
  fi
  git checkout -q "$VERSAO"
  git apply "$AQUI/whatsapp-mcp.patch"
  echo "Patch aplicado sobre $VERSAO."
fi

cd "$DESTINO/whatsapp-bridge"
CGO_ENABLED=1 go build -o whatsapp-bridge .
echo "Ponte compilada: $DESTINO/whatsapp-bridge/whatsapp-bridge"

mkdir -p "$PONTES/principal/store" "$PONTES/zeus/store"
chmod 700 "$PONTES" "$PONTES/principal" "$PONTES/zeus" "$PONTES/principal/store" "$PONTES/zeus/store"

if [ -n "$HISTORICO" ]; then
  alvo="$PONTES/principal/store/messages.db"
  if [ -e "$PONTES/principal/store/whatsapp.db" ]; then
    echo "A ponte do número principal já foi pareada; o histórico não é sobrescrito." >&2
  elif [ -e "$alvo" ]; then
    echo "Já existe $alvo; não sobrescrevo." >&2
  else
    install -m 600 "$HISTORICO" "$alvo"
    echo "Histórico copiado para $alvo."
  fi
fi

mkdir -p "$UNIDADES"
for unidade in ponte-principal.service ponte-zeus.service; do
  install -m 644 "$AQUI/$unidade" "$UNIDADES/$unidade"
done
systemctl --user daemon-reload

cat <<EOF

Pronto para parear. Para cada número, com o celular na mão:

  cd $PONTES/principal && WHATSAPP_BRIDGE_PORT=8080 $DESTINO/whatsapp-bridge/whatsapp-bridge
  cd $PONTES/zeus      && WHATSAPP_BRIDGE_PORT=8081 $DESTINO/whatsapp-bridge/whatsapp-bridge

No celular: WhatsApp > Aparelhos conectados > Conectar um aparelho, e escaneie.
Quando aparecer "Connected to WhatsApp", espere a sincronização e pare com Ctrl+C.
Depois:

  systemctl --user enable --now ponte-principal.service ponte-zeus.service
  sudo loginctl enable-linger "\$USER"
EOF
