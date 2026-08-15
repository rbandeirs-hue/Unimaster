# ======================================================
# 🧩 Blueprint: Alunos
# ======================================================

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from config import get_db_connection


# ======================================================
# 🔹 DEFINIÇÃO DO BLUEPRINT (AJUSTADO)
#    - Nome: alunos
#    - Prefixo da rota: /alunos
# ======================================================
bp_alunos = Blueprint("alunos", __name__, url_prefix="/alunos")


# ======================================================
# 🔹 PAINEL DO ALUNO
# ======================================================
@bp_alunos.route("/")
@login_required
def painel():

    # ======================================================
    # 🔥 1. RBAC — Apenas "aluno" ou "admin"
    # ======================================================
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso restrito aos alunos.", "danger")
        return redirect(url_for("painel.home"))

    # ======================================================
    # 🔥 2. Validar se o usuário realmente representa um aluno
    #    (isto depende do campo que você usa)
    # ======================================================
    if not current_user.id:
        flash("Usuário não está vinculado a um aluno.", "warning")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # ======================================================
    # 🔥 3. Buscar o aluno correto pelo usuário vinculado
    #    AJUSTADO: usa aluno.usuario_id ao invés de aluno.id
    # ======================================================
    cur.execute("""
        SELECT *
        FROM alunos
        WHERE usuario_id = %s
    """, (current_user.id,))

    aluno = cur.fetchone()

    cur.close()
    conn.close()

    if not aluno:
        flash("Aluno não encontrado para este usuário.", "warning")
        return redirect(url_for("painel.home"))

    # ======================================================
    # 🔥 4. Exibir painel do aluno
    # ======================================================
    from blueprints.aluno.painel import _stats_painel_aluno

    stats = _stats_painel_aluno(aluno)
    return render_template(
        "painel/painel_aluno.html",
        usuario=current_user,
        aluno=aluno,
        stats=stats,
    )
