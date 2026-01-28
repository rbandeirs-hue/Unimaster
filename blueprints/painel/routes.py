# ======================================================
# blueprints/painel/routes.py (VERSÃO RBAC CORRIGIDA)
# ======================================================

from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

painel_bp = Blueprint("painel", __name__, url_prefix="/painel")


@painel_bp.route("/")
@login_required
def home():
    """
    Redireciona o usuário para o painel correto de acordo com sua Role.
    """

    # ======================================================
    # 🔵 ADMIN → Acesso total
    # ======================================================
    if current_user.has_role("admin"):
        return render_template("painel/admin.html", usuario=current_user)

    # ======================================================
    # 🟦 FEDERAÇÃO
    # ======================================================
    if current_user.has_role("gestor_federacao"):
        return redirect(url_for("federacao.painel_federacao"))

    # ======================================================
    # 🟩 ASSOCIAÇÃO
    # ======================================================
    if current_user.has_role("gestor_associacao"):
        return redirect(url_for("associacao.painel_associacao"))

    # ======================================================
    # 🟧 ACADEMIA / PROFESSOR
    # ======================================================
    if current_user.has_role("gestor_academia") or current_user.has_role("professor"):
        return redirect(url_for("academia.painel_academia"))

    # ======================================================
    # 🟡 ALUNO
    # ======================================================
    if current_user.has_role("aluno"):
        return redirect(url_for("aluno.painel_aluno"))

    # ======================================================
    # 🚨 Caso raro: sem roles
    # ======================================================
    return "Usuário sem roles definidas — contate o administrador."
