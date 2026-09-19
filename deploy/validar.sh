#!/usr/bin/env bash
# Rodar depois do pull, no X99. Sem instalação e sem alteração de configuração.
set -euo pipefail
raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$raiz"
reiniciar=false
if [[ "${1:-}" == "--reiniciar" ]]; then
  reiniciar=true
elif [[ $# -gt 0 ]]; then
  echo "Uso: bash deploy/validar.sh [--reiniciar]" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Há alterações locais. Preserve-as antes de validar uma versão para deploy." >&2
  exit 2
fi
python_zeus="${ZEUS_PYTHON:-python3}"
if [[ -z "${ZEUS_PYTHON:-}" && -x "$raiz/.venv/bin/python" ]]; then
  python_zeus="$raiz/.venv/bin/python"
fi
export PYTHONPATH="$raiz/src${PYTHONPATH:+:$PYTHONPATH}"
"$python_zeus" -m unittest discover -s tests -q
"$python_zeus" -m zeus check --modelo
if $reiniciar; then
  if [[ "$(systemctl --user show zeus.service -p WorkingDirectory --value)" != "$raiz" ]]; then
    echo "O serviço usa outro diretório. Confira a unidade antes de reiniciar." >&2
    exit 2
  fi
  systemctl --user restart zeus.service
  systemctl --user is-active --quiet zeus.service
fi
echo "Código validado: $(git rev-parse --short HEAD)"
echo "Confirme no hardware: conversa, áudio, lembrete e retorno após reinício."
