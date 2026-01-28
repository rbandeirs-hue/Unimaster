# ======================================================
# 🧩 Blueprint: Painel do Aluno
# ======================================================

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from config import get_db_connection


# ======================================================
# 🚀 Definição do Blueprint
# ======================================================
# ⚠️ Nome diferente de "alunos" para evitar conflito
# ⚠️ Prefixo exclusivo: /painel_aluno
bp_painel_aluno = Blueprint(
    "painel_aluno",
    __name__,
    url_prefix="/painel_aluno"
)


# ======================================================
# 🔹 PAINEL DO ALUNO — HOME
# ======================================================
@bp_painel_aluno.route("/")
@login_required
def painel():

    # ------------------------------------------------------
    # 🔐 RBAC — Apenas para usuários com role 'aluno' ou admin
    # ------------------------------------------------------
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso restrito aos alunos.", "danger")
        return redirect(url_for("painel.home"))

    # ------------------------------------------------------
    # 🔍 Busca do aluno vinculado ao usuário atual
    # ------------------------------------------------------
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT *
        FROM alunos
        WHERE usuario_id = %s
    """, (current_user.id,))

    aluno = cur.fetchone()

    cur.close()
    conn.close()

    # ------------------------------------------------------
    # ❗ Caso não exista aluno vinculado
    # ------------------------------------------------------
    if not aluno:
        flash("Nenhum aluno está vinculado a este usuário.", "warning")
        return redirect(url_for("painel.home"))

    # ------------------------------------------------------
    # 🎯 Renderização do painel
    # ------------------------------------------------------
    return render_template(
        "painel/painel_aluno.html",
        usuario=current_user,
        aluno=aluno
    )
