#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para rodar o Unimaster em produção com Waitress (WSGI).
Usado pelo systemd ao ativar o serviço.

Variáveis de ambiente:
  UNIMASTER_HOST  - IP para escutar (default: 127.0.0.1 para uso com Nginx)
  UNIMASTER_PORT  - Porta (default: 5000)
"""
import os
from waitress import serve
from app import app

host = os.environ.get("UNIMASTER_HOST", "127.0.0.1")
port = int(os.environ.get("UNIMASTER_PORT", "5000"))

if __name__ == "__main__":
    serve(app, host=host, port=port)
