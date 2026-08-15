# -*- coding: utf-8 -*-
"""
WSGI — entrada para Gunicorn em produção.

    .venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
"""
from werkzeug.middleware.proxy_fix import ProxyFix

from app import app

# O Nginx é quem termina o TLS e repassa X-Forwarded-Proto/Host. Sem isto o Flask
# enxerga tudo como http e url_for(_external=True) gera link http:// — o que quebra
# o link público do formulário do Zempo, e-mails e qualquer URL absoluta.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
