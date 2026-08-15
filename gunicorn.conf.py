# -*- coding: utf-8 -*-
# Gunicorn — https://docs.gunicorn.org/en/stable/settings.html
# Uso: .venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
# WorkingDirectory no systemd deve ser /var/www/Unimaster (caminhos relativos abaixo).

bind = "127.0.0.1:8000"
workers = 3
timeout = 120
graceful_timeout = 30
keepalive = 5

accesslog = "logs/access.log"
errorlog = "logs/error.log"
loglevel = "info"
capture_output = True

# Flask-SocketIO está com async_mode='threading'; workers múltiplos exigem sticky sessions
# no Nginx para o mesmo cliente ir sempre ao mesmo worker (ver deploy/nginx-unimaster.conf).
proc_name = "unimaster"
