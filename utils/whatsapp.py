# -*- coding: utf-8 -*-
"""Cliente do microserviço WhatsApp (Baileys multi-instância).

Cada academia = uma instância identificada pelo academia_id. Todas as funções são
tolerantes a falha: se o serviço estiver fora, retornam um dict de erro em vez de
quebrar o fluxo do app.
"""
import os
import requests
from flask import current_app

_BASE = os.environ.get("WPP_BASE_URL", "http://127.0.0.1:3333")
_KEY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "whatsapp-service", "api_key.txt",
)
_TIMEOUT = 8


def _api_key():
    k = os.environ.get("WPP_API_KEY")
    if k:
        return k.strip()
    try:
        with open(_KEY_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return ""


def _headers():
    return {"x-api-key": _api_key(), "Content-Type": "application/json"}


def disponivel():
    """True se o microserviço está no ar."""
    try:
        r = requests.get(f"{_BASE}/health", timeout=4)
        return r.ok
    except Exception:
        return False


def conectar(academia_id):
    """Inicia/garante a sessão da academia. Retorna {status, qr, number} ou {erro}."""
    try:
        r = requests.post(f"{_BASE}/instances/{academia_id}/connect", headers=_headers(), timeout=_TIMEOUT)
        return r.json()
    except Exception as e:
        current_app.logger.warning(f"WhatsApp conectar falhou (acad {academia_id}): {e}")
        return {"erro": "serviço de WhatsApp indisponível", "status": "offline"}


def status(academia_id):
    """Retorna {status, number, fila} ou {erro/offline}."""
    try:
        r = requests.get(f"{_BASE}/instances/{academia_id}/status", headers=_headers(), timeout=_TIMEOUT)
        return r.json()
    except Exception:
        return {"status": "offline"}


def qrcode(academia_id):
    """Retorna {status, qr(dataURL), number}."""
    try:
        r = requests.get(f"{_BASE}/instances/{academia_id}/qr", headers=_headers(), timeout=_TIMEOUT)
        return r.json()
    except Exception:
        return {"status": "offline", "qr": None}


def logout(academia_id):
    try:
        r = requests.post(f"{_BASE}/instances/{academia_id}/logout", headers=_headers(), timeout=_TIMEOUT)
        return r.json()
    except Exception:
        return {"erro": "serviço indisponível"}


def enviar(academia_id, telefone, mensagem):
    """Enfileira o envio de uma mensagem. Retorna (ok: bool, info: dict).
    Não levanta exceção — uso seguro dentro de qualquer fluxo."""
    if not academia_id or not telefone or not mensagem:
        return False, {"erro": "parâmetros incompletos"}
    try:
        r = requests.post(
            f"{_BASE}/instances/{academia_id}/send",
            json={"telefone": str(telefone), "mensagem": str(mensagem)},
            headers=_headers(), timeout=_TIMEOUT,
        )
        if r.ok:
            return True, r.json()
        return False, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"erro": r.text}
    except Exception as e:
        current_app.logger.warning(f"WhatsApp envio falhou (acad {academia_id}): {e}")
        return False, {"erro": "serviço de WhatsApp indisponível"}


def conectado(academia_id):
    """Atalho: True se a instância está pareada e pronta para enviar."""
    return status(academia_id).get("status") == "open"
