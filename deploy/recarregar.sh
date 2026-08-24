#!/usr/bin/env bash
# Recarrega o Unimaster depois de um deploy.
#
# Por que existe: os 3 workers do gunicorn carregam o Python uma vez, mas o
# Jinja relê os templates do disco. Um `git pull` sem reload deixa o processo
# com o código antigo servindo template novo — e a tela quebra com erros do
# tipo "'asset' is undefined". Foi o que aconteceu em 24/08/2026.
#
# Uso:  sudo deploy/recarregar.sh
set -euo pipefail

PID=$(pgrep -f 'Unimaster/.venv/bin/gunicorn' | head -1)
if [ -z "${PID}" ]; then
  echo "gunicorn do Unimaster não está rodando" >&2
  exit 1
fi

echo "master do Unimaster: PID ${PID}"
kill -HUP "${PID}"
sleep 5

echo "workers após o reload:"
pgrep -af 'Unimaster/.venv/bin/gunicorn' | sed 's/^/  /'

CODIGO=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/auth/login)
echo "GET /auth/login -> ${CODIGO}"
[ "${CODIGO}" = "200" ] || { echo "login não respondeu 200 — confira logs/error.log" >&2; exit 1; }
echo "ok"
