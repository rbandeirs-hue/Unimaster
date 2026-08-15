# -*- coding: utf-8 -*-
"""
Utilitário de Web Push Notifications.

Uso rápido:
    from utils.push_notifications import enviar_push_usuario, enviar_push_usuarios

    enviar_push_usuario(usuario_id=5, title="Olá", body="Você tem uma nova mensagem")
    enviar_push_usuarios([1, 2, 3], title="Aviso", body="Texto", url="/pagina")
"""
import json
import os
import logging
from typing import Optional

from config import get_db_connection

logger = logging.getLogger(__name__)
_PYWEBPUSH_IMPORT_WARNED = False

# ── Chaves VAPID (lidas do .env; fallback para as geradas no setup) ───────────
VAPID_PUBLIC_KEY  = os.environ.get(
    "VAPID_PUBLIC_KEY",
    "BHcd_g9Mz_UMFvlTygkhJPPGvHJQtehes-ZDo7bS7ZSmr72ZvrG1XNVYNeaSHrC3NBleu96z5Mj1fr6nBJWHRSg"
)
VAPID_PRIVATE_KEY = os.environ.get(
    "VAPID_PRIVATE_KEY",
    "tyPRoCXLsh8UA5mbyiA1RP9dAZOxgaTh5Yg7V9yuG7Y"
)
# Claim JWT "sub" (contacto do emissor VAPID). Evitar "mailto:mailto:..." se .env já trouxer mailto:
_raw_vapid_contact = os.environ.get("VAPID_CLAIMS_EMAIL", "admin@unimaster.app").strip()
if _raw_vapid_contact.lower().startswith("mailto:"):
    VAPID_CLAIMS_SUB = _raw_vapid_contact
else:
    VAPID_CLAIMS_SUB = f"mailto:{_raw_vapid_contact}"


def _get_webpusher():
    """Importa pywebpush só quando necessário."""
    global _PYWEBPUSH_IMPORT_WARNED
    try:
        from pywebpush import webpush, WebPushException
        return webpush, WebPushException
    except ImportError:
        if not _PYWEBPUSH_IMPORT_WARNED:
            logger.error(
                "pywebpush não instalado — pushes não serão enviados. "
                "Execute: pip install pywebpush (ou pip install -r requirements.txt)."
            )
            _PYWEBPUSH_IMPORT_WARNED = True
        return None, None


# ── Salvar / remover assinatura ───────────────────────────────────────────────

def salvar_subscription(usuario_id: int, subscription_info: dict, user_agent: str = "") -> tuple:
    """
    Persiste ou atualiza uma push subscription no banco.
    Retorna (True, "") em sucesso ou (False, mensagem) em falha.
    """
    endpoint = subscription_info.get("endpoint", "")
    keys     = subscription_info.get("keys", {})
    p256dh   = keys.get("p256dh", "")
    auth     = keys.get("auth", "")
    if not endpoint or not p256dh or not auth:
        return False, "Payload da assinatura incompleto (endpoint/keys)."
    db = get_db_connection()
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO push_subscriptions (usuario_id, endpoint, p256dh, auth, user_agent)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                usuario_id  = VALUES(usuario_id),
                p256dh      = VALUES(p256dh),
                auth        = VALUES(auth),
                user_agent  = VALUES(user_agent),
                atualizado_em = NOW()
        """, (usuario_id, endpoint, p256dh, auth, user_agent[:255]))
        db.commit()
        return True, ""
    except Exception as exc:
        logger.error("Erro ao salvar subscription: %s", exc)
        err = str(exc)
        errno = getattr(exc, "errno", None)
        missing = errno == 1146 or (
            "push_subscriptions" in err.lower()
            and ("doesn't exist" in err.lower() or "does not exist" in err.lower() or "unknown table" in err.lower())
        )
        if missing:
            return False, (
                "Tabela push_subscriptions ausente. Execute no MySQL: "
                "migrations/add_push_subscriptions.sql"
            )
        return False, err
    finally:
        cur.close(); db.close()


def remover_subscription(endpoint: str) -> None:
    db = get_db_connection()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
        db.commit()
    except Exception as exc:
        logger.error("Erro ao remover subscription: %s", exc)
    finally:
        cur.close(); db.close()


def _subscriptions_do_usuario(usuario_id: int) -> list:
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE usuario_id = %s",
            (usuario_id,)
        )
        return cur.fetchall()
    finally:
        cur.close(); db.close()


def obter_qtd_push_subscriptions(usuario_id: int) -> int:
    """Quantidade de endpoints push salvos para o usuário (diagnóstico / teste)."""
    return len(_subscriptions_do_usuario(usuario_id))


def _subscriptions_dos_usuarios(usuario_ids: list) -> list:
    if not usuario_ids:
        return []
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        ph = ",".join(["%s"] * len(usuario_ids))
        cur.execute(
            f"SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE usuario_id IN ({ph})",
            tuple(usuario_ids)
        )
        return cur.fetchall()
    finally:
        cur.close(); db.close()


# ── Envio ─────────────────────────────────────────────────────────────────────

def _formatar_erro_webpush(exc: BaseException) -> str:
    """Resumo curto para logs e resposta do /push/test (sem dados sensíveis)."""
    nome = type(exc).__name__
    try:
        from pywebpush import WebPushException

        if isinstance(exc, WebPushException):
            resp = getattr(exc, "response", None)
            sc = getattr(resp, "status_code", None) if resp is not None else None
            corpo = ""
            if resp is not None:
                try:
                    corpo = (getattr(resp, "text", None) or "")[:200]
                except Exception:
                    corpo = ""
            if sc is not None:
                return f"{nome} HTTP {sc}" + (f": {corpo}" if corpo else "")
    except ImportError:
        pass
    s = str(exc).strip()
    if len(s) > 280:
        s = s[:277] + "…"
    return f"{nome}: {s}" if s else nome


def _enviar_para_subscription(sub: dict, payload: dict, erros_envio: Optional[list] = None) -> bool:
    webpush, _ = _get_webpusher()
    if not webpush:
        if erros_envio is not None and len(erros_envio) < 12:
            erros_envio.append("pywebpush não disponível neste interpretador Python.")
        return False
    subscription_info = {
        "endpoint": sub["endpoint"],
        "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_CLAIMS_SUB},
        )
        return True
    except Exception as exc:
        brief = _formatar_erro_webpush(exc)
        if erros_envio is not None and len(erros_envio) < 12:
            host = ""
            try:
                from urllib.parse import urlparse

                host = urlparse(sub.get("endpoint") or "").netloc[:80]
            except Exception:
                pass
            erros_envio.append(f"[{host}] {brief}" if host else brief)
        status = None
        try:
            from pywebpush import WebPushException

            if isinstance(exc, WebPushException):
                r = getattr(exc, "response", None)
                status = getattr(r, "status_code", None) if r is not None else None
        except ImportError:
            pass
        msg = str(exc)
        if status in (404, 410) or " 404" in msg or " 410" in msg:
            remover_subscription(sub["endpoint"])
        else:
            logger.warning("Push falhou (%s): %s", (sub.get("endpoint") or "")[:60], brief)
        return False


def _montar_payload(title: str, body: str, url: str = "/", icon: str = "",
                    tag: str = "default", actions: list = None,
                    require_interaction: bool = False) -> dict:
    return {
        "title": title,
        "body": body,
        "url": url,
        "icon": icon or "/static/img/icon-192.png",
        "badge": "/static/img/badge-72.png",
        "tag": tag,
        "actions": actions or [],
        "requireInteraction": require_interaction,
    }


def enviar_push_usuario(usuario_id: int, title: str, body: str, url: str = "/",
                        icon: str = "", tag: str = "default",
                        actions: list = None, require_interaction: bool = False,
                        erros_envio: Optional[list] = None) -> int:
    """Envia push para todos os dispositivos de um usuário. Retorna qtd enviada."""
    subs = _subscriptions_do_usuario(usuario_id)
    if not subs:
        return 0
    payload = _montar_payload(title, body, url, icon, tag, actions, require_interaction)
    return sum(1 for s in subs if _enviar_para_subscription(s, payload, erros_envio))


def enviar_push_usuarios(usuario_ids: list, title: str, body: str, url: str = "/",
                         icon: str = "", tag: str = "default",
                         actions: list = None, erros_envio: Optional[list] = None,
                         require_interaction: bool = False) -> int:
    """Envia push para múltiplos usuários. Retorna qtd de envios bem-sucedidos."""
    subs = _subscriptions_dos_usuarios(usuario_ids)
    if not subs:
        return 0
    payload = _montar_payload(
        title, body, url, icon, tag, actions, require_interaction
    )
    return sum(1 for s in subs if _enviar_para_subscription(s, payload, erros_envio))
