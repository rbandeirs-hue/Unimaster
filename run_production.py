#!/usr/bin/env python3
"""
Unimaster - Servidor de produção com Waitress
Executado pelo systemd (unimaster.service)
"""
import os

from waitress import serve
from app import app

if __name__ == "__main__":
    host = os.environ.get("UNIMASTER_HOST", "127.0.0.1")
    port = int(os.environ.get("UNIMASTER_PORT", "5000"))
    serve(app, host=host, port=port)
