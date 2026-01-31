# ======================================================
# blueprints/painel/routes.py (VERSÃO RBAC + MODO)
# ======================================================

from flask import Blueprint, render_template, redirect, url_for, session
from flask_login import login_required, current_user

painel_bp = Blueprint("painel", __name__, url_prefix="/painel")

# Mapeamento: modo -> (nome, url_endpoint, template_ou_none)
MODOS = {
    "admin": ("Administrador", "painel._redirect_admin", None),
    "federacao": ("Federação", "federacao.painel_federacao", None),
    "associacao": ("Associação", "associacao.painel_associacao", None),
    "academia": ("Academia", "academia.painel_academia", None),
    "aluno": ("Aluno", "painel_aluno.painel", None),
}


def _modos_disponiveis():
    """Retorna lista de (modo_id, nome) disponíveis para o usuário."""
    modos = []
    if current_user.has_role("admin"):
        modos.append(("admin", "Administrador"))
    if current_user.has_role("gestor_federacao"):
        modos.append(("federacao", "Federação"))
    if current_user.has_role("gestor_associacao"):
        modos.append(("associacao", "Associação"))
    if current_user.has_role("gestor_academia") or current_user.has_role("professor"):
        modos.append(("academia", "Academia"))
    if current_user.has_role("aluno"):
        modos.append(("aluno", "Aluno"))
    return modos


def _redirecionar_modo(modo):
    """Redireciona para o painel do modo."""
    if modo == "admin":
        return render_template("painel/admin.html", usuario=current_user)
    if modo == "federacao":
        return redirect(url_for("federacao.painel_federacao"))
    if modo == "associacao":
        return redirect(url_for("associacao.painel_associacao"))
    if modo == "academia":
        return redirect(url_for("academia.painel_academia"))
    if modo == "aluno":
        return redirect(url_for("painel_aluno.painel"))
    return redirect(url_for("painel.home"))


@painel_bp.route("/")
@login_required
def home():
    """
    Se usuário tem um único modo: redireciona direto.
    Se tem múltiplos: mostra página de escolha (ou usa modo salvo na session).
    ?trocar=1 força exibir a escolha de modo.
    """
    from flask import request
    modos = _modos_disponiveis()
    if not modos:
        return "Usuário sem roles definidas — contate o administrador."

    forcar_escolha = request.args.get("trocar") == "1"

    # Modo preferido na session (se ainda válido e não forçar escolha)
    modo_preferido = session.get("modo_painel")
    if not forcar_escolha and modo_preferido and any(m[0] == modo_preferido for m in modos):
        return _redirecionar_modo(modo_preferido)

    # Um único modo e não forçar: vai direto
    if len(modos) == 1 and not forcar_escolha:
        session["modo_painel"] = modos[0][0]
        return _redirecionar_modo(modos[0][0])

    # Múltiplos modos (ou forçar): mostra escolha
    return render_template("painel/escolher_modo.html", modos=modos)


@painel_bp.route("/escolher/<modo>")
@login_required
def escolher_modo(modo):
    """Ativa um modo e redireciona para o painel correspondente."""
    modos = _modos_disponiveis()
    if not any(m[0] == modo for m in modos):
        return redirect(url_for("painel.home"))
    session["modo_painel"] = modo
    return _redirecionar_modo(modo)


# usado internamente no mapeamento
@painel_bp.route("/_admin")
@login_required
def _redirect_admin():
    return render_template("painel/admin.html", usuario=current_user)
