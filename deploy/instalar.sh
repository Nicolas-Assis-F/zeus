#!/usr/bin/env bash
# Deixa o Zeus subir sozinho quando a máquina liga.
#
# Três coisas precisam ser verdade, e cada uma já deu problema:
#   1. a unidade tem que apontar para a pasta onde o repositório realmente
#      está (WorkingDirectory errado foi o que girou 419 reinícios);
#   2. serviço de usuário só sobe no boot se a sessão tiver "linger" ligado,
#      senão ele espera alguém fazer login;
#   3. uma unidade em estado `failed` de uma tentativa anterior não sobe
#      sozinha nem depois de consertada.
set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unidade="$HOME/.config/systemd/user/zeus.service"
python_zeus="${ZEUS_PYTHON:-/usr/bin/python3}"
[[ -x "$raiz/.venv/bin/python" && -z "${ZEUS_PYTHON:-}" ]] && python_zeus="$raiz/.venv/bin/python"

echo "repositório: $raiz"
echo "python:      $python_zeus"

if [[ ! -f "$raiz/src/zeus/__main__.py" ]]; then
  echo "Isto não parece a raiz do Zeus. Rode deploy/instalar.sh de dentro do clone." >&2
  exit 2
fi

# O arquivo de exemplo está no git e o Zeus nunca lê dele, mas é o primeiro
# que aparece para quem procura onde configurar — e já foi preenchido com
# valores de verdade duas vezes. Avisar aqui é mais barato que revogar depois.
if grep -Eq 'sk-[A-Za-z0-9_-]{16,}|[0-9]{8,}:[A-Za-z0-9_-]{30,}' \
     "$raiz/config/config.example.json" 2>/dev/null; then
  echo >&2
  echo "ATENÇÃO: config/config.example.json tem valor que parece segredo." >&2
  echo "Esse arquivo vai para o GitHub. Revogue a chave e escreva em" >&2
  echo "~/.config/zeus/config.json, que é de onde o Zeus lê." >&2
  echo "Para limpar:  git checkout -- config/config.example.json" >&2
  echo >&2
fi

mkdir -p "$(dirname "$unidade")"
cat > "$unidade" <<UNIDADE
[Unit]
Description=Zeus base runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$raiz
Environment=PYTHONPATH=$raiz/src
ExecStart=$python_zeus -m zeus run
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=5
TimeoutStopSec=15
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
UNIDADE
echo "unidade escrita em $unidade"

# Sem linger, o serviço de usuário só sobe quando alguém faz login. O X99 fica
# num canto sem monitor: ninguém vai logar nele.
if loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
  echo "linger: já ligado"
else
  if loginctl enable-linger "$USER" 2>/dev/null; then
    echo "linger: ligado agora (o Zeus passa a subir no boot, sem login)"
  else
    echo "linger: não consegui ligar sozinho. Rode:  sudo loginctl enable-linger $USER" >&2
  fi
fi

systemctl --user daemon-reload
systemctl --user reset-failed zeus.service 2>/dev/null || true
systemctl --user enable --now zeus.service
sleep 2

echo
systemctl --user --no-pager --lines=0 status zeus.service || true
echo
echo "reinícios desde que subiu: $(systemctl --user show -p NRestarts --value zeus.service)"
echo
echo "--- conferência ---"
cd "$raiz" && ./zeus check || true
echo
echo "Para ver o endereço da interface:"
echo "  journalctl --user -u zeus.service -n 30 --no-pager | grep started"
