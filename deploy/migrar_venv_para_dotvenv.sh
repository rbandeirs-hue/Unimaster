#!/usr/bin/env bash
# Renomeia a pasta antiga "venv" para ".venv" na raiz do projeto (Ubuntu/Debian).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -d venv && ! -d .venv ]]; then
  echo "A renomear venv -> .venv em $ROOT"
  mv venv .venv
  echo "Concluído. Atualize systemd/nginx se ainda apontarem para venv."
elif [[ -d venv && -d .venv ]]; then
  echo "Erro: existem venv e .venv. Remova ou una manualmente."
  exit 1
else
  echo "Nada a fazer (não existe pasta venv ou .venv já existe)."
fi
