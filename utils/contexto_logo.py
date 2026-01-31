# ======================================================
# Utilitário: Logo e nome do contexto (academia/associação/federação)
# Usado no sidebar e em páginas para personalização visual
# ======================================================
import os
from flask import url_for, current_app

LOGO_EXTENSOES = (".png", ".jpg", ".jpeg", ".gif")


def buscar_logo_url(prefixo, entidade_id):
    """Retorna URL da logo ou None. Prefixo: academia, associacao, federacao."""
    if not entidade_id:
        return None
    pasta = os.path.join(current_app.root_path, "static", "uploads", "logos")
    for ext in LOGO_EXTENSOES:
        filename = f"{prefixo}_{entidade_id}{ext}"
        if os.path.isfile(os.path.join(pasta, filename)):
            return url_for("static", filename=f"uploads/logos/{filename}")
    return None


def get_contexto_logo_e_nome(current_user, session):
    """
    Retorna (logo_url, nome, tipo) do contexto atual do usuário.
    tipo: 'academia' | 'associacao' | 'federacao' | None
    """
    from config import get_db_connection

    if not current_user or not hasattr(current_user, 'is_authenticated') or not current_user.is_authenticated:
        return None, "Judo Academy", None

    modo = session.get("modo_painel") if session else None
    if not modo or modo not in ("admin", "federacao", "associacao", "academia", "aluno"):
        modo = _modo_efetivo(current_user)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    try:
        if modo == "federacao" and getattr(current_user, "id_federacao", None):
            cur.execute("SELECT id, nome FROM federacoes WHERE id = %s", (current_user.id_federacao,))
            row = cur.fetchone()
            if row:
                logo = buscar_logo_url("federacao", row["id"])
                return logo, row["nome"] or "Federação", "federacao"

        if modo == "associacao" and getattr(current_user, "id_associacao", None):
            cur.execute("SELECT id, nome FROM associacoes WHERE id = %s", (current_user.id_associacao,))
            row = cur.fetchone()
            if row:
                logo = buscar_logo_url("associacao", row["id"])
                return logo, row["nome"] or "Associação", "associacao"

        if modo == "academia" and getattr(current_user, "id_academia", None):
            cur.execute("SELECT id, nome FROM academias WHERE id = %s", (current_user.id_academia,))
            row = cur.fetchone()
            if row:
                logo = buscar_logo_url("academia", row["id"])
                return logo, row["nome"] or "Academia", "academia"

        if modo == "aluno":
            cur.execute(
                "SELECT a.id_academia FROM alunos a WHERE a.usuario_id = %s",
                (current_user.id,),
            )
            row = cur.fetchone()
            if row and row.get("id_academia"):
                cur.execute("SELECT id, nome FROM academias WHERE id = %s", (row["id_academia"],))
                ac = cur.fetchone()
                if ac:
                    logo = buscar_logo_url("academia", ac["id"])
                    return logo, ac["nome"] or "Academia", "academia"

        # Admin sem contexto específico: tentar primeira federação
        if modo == "admin":
            cur.execute("SELECT id, nome FROM federacoes ORDER BY nome LIMIT 1")
            row = cur.fetchone()
            if row:
                logo = buscar_logo_url("federacao", row["id"])
                return logo, row["nome"] or "Sistema", "federacao"
    finally:
        cur.close()
        conn.close()

    return None, "Judo Academy", None


def _modo_efetivo(current_user):
    """Define o modo baseado nas roles (ordem de prioridade)."""
    if current_user.has_role("admin"):
        return "admin"
    if current_user.has_role("gestor_federacao"):
        return "federacao"
    if current_user.has_role("gestor_associacao"):
        return "associacao"
    if current_user.has_role("gestor_academia") or current_user.has_role("professor"):
        return "academia"
    if current_user.has_role("aluno"):
        return "aluno"
    return None
