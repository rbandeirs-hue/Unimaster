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
    if not modo or modo not in ("admin", "federacao", "associacao", "academia", "professor", "aluno", "responsavel", "visitante"):
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

        if modo == "professor":
            cur.execute(
                "SELECT id_academia FROM professores WHERE usuario_id = %s AND ativo = 1 LIMIT 1",
                (current_user.id,),
            )
            row = cur.fetchone()
            if row and row.get("id_academia"):
                cur.execute("SELECT id, nome FROM academias WHERE id = %s", (row["id_academia"],))
                ac = cur.fetchone()
                if ac:
                    logo = buscar_logo_url("academia", ac["id"])
                    return logo, ac["nome"] or "Minha Turma", "academia"
            return None, "Professor", None

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

        if modo == "responsavel":
            cur.execute(
                """SELECT a.id_academia FROM alunos a
                   JOIN responsavel_alunos ra ON ra.aluno_id = a.id
                   WHERE ra.usuario_id = %s LIMIT 1""",
                (current_user.id,),
            )
            row = cur.fetchone()
            if row and row.get("id_academia"):
                cur.execute("SELECT id, nome FROM academias WHERE id = %s", (row["id_academia"],))
                ac = cur.fetchone()
                if ac:
                    logo = buscar_logo_url("academia", ac["id"])
                    return logo, ac["nome"] or "Academia", "academia"

        if modo == "visitante":
            cur.execute(
                "SELECT id_academia FROM visitantes WHERE usuario_id = %s AND ativo = 1 LIMIT 1",
                (current_user.id,),
            )
            row = cur.fetchone()
            if row and row.get("id_academia"):
                cur.execute("SELECT id, nome FROM academias WHERE id = %s", (row["id_academia"],))
                ac = cur.fetchone()
                if ac:
                    logo = buscar_logo_url("academia", ac["id"])
                    return logo, ac["nome"] or "Academia", "academia"
            return None, "Visitante", None

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


def _usuario_e_professor_ou_auxiliar(current_user):
    """True se o usuário tem registro em professores e aparece em alguma turma (responsável ou auxiliar)."""
    try:
        from config import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT 1 FROM professores p
               INNER JOIN turma_professor tp ON tp.professor_id = p.id
               WHERE p.usuario_id = %s AND p.ativo = 1 LIMIT 1""",
            (current_user.id,),
        )
        ok = cur.fetchone() is not None
        cur.close()
        conn.close()
        return ok
    except Exception:
        return False


def _modo_efetivo(current_user):
    """Define o modo baseado nas roles (ordem de prioridade). Inclui professor auxiliar."""
    if current_user.has_role("admin"):
        return "admin"
    if current_user.has_role("gestor_federacao"):
        return "federacao"
    if current_user.has_role("gestor_associacao"):
        return "associacao"
    if current_user.has_role("gestor_academia"):
        return "academia"
    if current_user.has_role("professor") or _usuario_e_professor_ou_auxiliar(current_user):
        return "professor"
    if current_user.has_role("aluno"):
        return "aluno"
    if current_user.has_role("responsavel"):
        return "responsavel"
    if current_user.has_role("visitante"):
        return "visitante"
    return None
