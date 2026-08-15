#!/usr/bin/env bash
# Prepara o projeto em /var/www/Unimaster (sem sudo, exceto se correr com sudo para chown).
# Depois: copiar unimaster.service + nginx e systemctl (ver deploy/PRODUCAO.md).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Raiz: $ROOT"

if [[ -d "$ROOT/venv" && -d "$ROOT/.venv" ]]; then
  echo "==> A remover pasta antiga venv (mantém-se apenas .venv)."
  rm -rf "$ROOT/venv"
elif [[ -d "$ROOT/venv" && ! -d "$ROOT/.venv" ]]; then
  echo "==> A renomear venv -> .venv"
  mv "$ROOT/venv" "$ROOT/.venv"
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "==> A criar .venv"
  python3 -m venv "$ROOT/.venv"
fi

echo "==> pip install -r requirements.txt"
"$ROOT/.venv/bin/pip" install -U pip wheel
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"

mkdir -p "$ROOT/logs"
# Se correr como root (ex.: sudo ./deploy/subir.sh), já deixa logs/uploads para o Gunicorn (www-data).
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  chown -R www-data:www-data "$ROOT/logs" "$ROOT/static/uploads" 2>/dev/null || true
fi

echo "==> Smoke test wsgi + gunicorn (3s)…"
timeout 3 "$ROOT/.venv/bin/gunicorn" -c "$ROOT/gunicorn.conf.py" wsgi:app >/dev/null 2>&1 || true

echo ""
echo "OK. Próximo passo (com sudo no servidor — obrigatório antes do systemctl se não usou sudo neste script):"
echo "  sudo chown -R www-data:www-data $ROOT/logs $ROOT/static/uploads 2>/dev/null || true"
echo "  sudo cp $ROOT/deploy/unimaster.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload && sudo systemctl enable --now unimaster"
echo "  sudo cp $ROOT/deploy/nginx-unimaster-letsencrypt.conf /etc/nginx/sites-available/unimaster"
echo "  sudo ln -sf /etc/nginx/sites-available/unimaster /etc/nginx/sites-enabled/"
echo "  sudo nginx -t && sudo systemctl reload nginx"
