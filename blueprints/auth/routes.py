# blueprints/auth/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user
from werkzeug.security import check_password_hash
from config import get_db_connection
from .user_model import Usuario

auth_bp = Blueprint("auth", __name__)


# =======================================================
# 🔹 LOGIN (versão RBAC pura)
# =======================================================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # --------------------------------------------
        # 1️⃣ Buscar usuário (SEM tipo_usuario)
        # --------------------------------------------
        cur.execute("""
            SELECT 
                id, nome, email, senha,
                id_federacao, id_associacao, id_academia
            FROM usuarios
            WHERE email = %s
        """, (email,))

        usuario = cur.fetchone()

        if not usuario:
            flash("E-mail ou senha incorretos!", "danger")
            return render_template("login.html")

        # --------------------------------------------
        # 2️⃣ Validar senha
        # --------------------------------------------
        if not check_password_hash(usuario["senha"], senha):
            flash("E-mail ou senha incorretos!", "danger")
            return render_template("login.html")

        cur.close()
        conn.close()

        # --------------------------------------------
        # 3️⃣ Criar objeto usuário com RBAC real
        # --------------------------------------------
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

        # --------------------------------------------
        # 4️⃣ Logar usuário
        # --------------------------------------------
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
