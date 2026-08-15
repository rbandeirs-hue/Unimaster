from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required
from app.models.usuario import Usuario

bp = Blueprint("auth", __name__)


@bp.get("/login")
def login():
    return render_template("login.html")


@bp.post("/login")
def login_post():
    email = request.form.get("email", "").strip().lower()
    senha = request.form.get("senha", "")
    lembrar = bool(request.form.get("lembrar"))

    usuario = Usuario.query.filter_by(email=email).first()

    if not usuario or not usuario.checar_senha(senha):
        flash("E-mail ou senha incorretos.", "error")
        return redirect(url_for("auth.login"))

    login_user(usuario, remember=lembrar)
    return redirect(request.args.get("next") or url_for("home.index"))


@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
