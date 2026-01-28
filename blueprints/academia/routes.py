# blueprints/academia/routes.py
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from config import get_db_connection

academia_bp = Blueprint("academia", __name__, url_prefix="/academia")


# =====================================================
# 🔹 Painel da Academia
# =====================================================
@academia_bp.route("/")
@login_required
def painel_academia():

    # =====================================================
    # 🔥 RBAC — Perfis permitidos:
    #  - gestor_academia
    #  - professor
    #  - admin
    # =====================================================
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    # =====================================================
    # 🔍 Verificar se o usuário possui id_academia
    # =====================================================
    if not current_user.id_academia:
        flash("Você não está vinculado a nenhuma academia.", "warning")
        return redirect(url_for("painel.home"))

    # =====================================================
    # 🔍 Buscar alunos da academia
    # =====================================================
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT id, nome, email
        FROM academias
        WHERE id = %s
    """, (current_user.id_academia,))

    alunos = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "painel/painel_academia.html",
        usuario=current_user,
        alunos=alunos
    )
