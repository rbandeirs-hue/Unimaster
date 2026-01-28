# =======================================================
# 🔹 AUTH — Login / Logout com RBAC real
# =======================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user
from werkzeug.security import check_password_hash
from config import get_db_connection
from .user_model import Usuario

auth_bp = Blueprint("auth", __name__)


# =======================================================
# 🔹 LOGIN
# =======================================================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # Buscar usuário
        cur.execute("""
            SELECT 
                u.id, u.nome, u.email, u.senha,
                u.id_federacao, u.id_associacao, u.id_academia,
                u.tipo_id,
                t.nome AS tipo_nome
            FROM usuarios u
            JOIN tipo_usuario t ON t.id = u.tipo_id
            WHERE u.email = %s
        """, (email,))

        usuario = cur.fetchone()

        if not usuario:
            flash("E-mail ou senha incorretos!", "danger")
            return render_template("login.html")

        if not check_password_hash(usuario["senha"], senha):
            flash("E-mail ou senha incorretos!", "danger")
            return render_template("login.html")

        cur.close()
        conn.close()

        # Criar objeto de usuário com RBAC real
        user_obj = Usuario(
            id=usuario["id"],
            nome=usuario["nome"],
            email=usuario["email"],
            senha=usuario["senha"],
            id_federacao=usuario.get("id_federacao"),
            id_associacao=usuario.get("id_associacao"),
            id_academia=usuario.get("id_academia"),
            roles=Usuario.carregar_roles(usuario["id"]),
            permissoes=Usuario.carregar_permissoes(usuario["id"]),
            menus=Usuario.carregar_menus(usuario["id"])
        )

        login_user(user_obj)

        return redirect(url_for("painel.home"))

    return render_template("login.html")


# =======================================================
# 🔹 LOGOUT
# =======================================================
@auth_bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
