# ======================================================
# 🧩 Blueprint: Usuários (TOTALMENTE AJUSTADO PARA ROLES)
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from blueprints.auth.user_model import Usuario
from config import get_db_connection
from math import ceil

bp_usuarios = Blueprint("usuarios", __name__, url_prefix="/usuarios")


# ======================================================
# 🔹 Verificação geral de permissão
# ======================================================
def require_admin():
    if not current_user.has_role("admin"):
        flash("Acesso restrito aos administradores.", "danger")
        return False
    return True


# ======================================================
# 🔹 LISTA DE USUÁRIOS
# ======================================================
@bp_usuarios.route("/lista")
@login_required
def lista_usuarios():

    if not require_admin():
        return redirect(url_for("painel.home"))

    busca = request.args.get("busca", "").strip()
    page = int(request.args.get("page", 1))
    por_pagina = 10
    offset = (page - 1) * por_pagina

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Conta total
    if busca:
        cursor.execute("""
            SELECT COUNT(*) AS total 
            FROM usuarios 
            WHERE nome LIKE %s OR email LIKE %s
        """, (f"%{busca}%", f"%{busca}%"))
    else:
        cursor.execute("SELECT COUNT(*) AS total FROM usuarios")

    total = cursor.fetchone()["total"]

    # Lista paginada
    if busca:
        cursor.execute("""
            SELECT 
                u.id, u.nome, u.email, u.criado_em
            FROM usuarios u
            WHERE nome LIKE %s OR email LIKE %s
            ORDER BY nome
            LIMIT %s OFFSET %s
        """, (f"%{busca}%", f"%{busca}%", por_pagina, offset))
    else:
        cursor.execute("""
            SELECT id, nome, email, criado_em
            FROM usuarios
            ORDER BY nome
            LIMIT %s OFFSET %s
        """, (por_pagina, offset))

    usuarios = cursor.fetchall()

    # CARREGAR ROLES DE CADA USUÁRIO
    for u in usuarios:
        cursor.execute("""
            SELECT r.nome 
            FROM roles_usuario ru 
            JOIN roles r ON r.id = ru.role_id
            WHERE ru.usuario_id = %s
        """, (u["id"],))
        roles = [r["nome"] for r in cursor.fetchall()]
        u["roles"] = ", ".join(roles) if roles else "Sem Roles"
        niveis = Usuario.niveis_acesso_por_roles(roles)
        u["niveis_acesso"] = niveis if niveis else ["Sem nível"]

    cursor.close()
    db.close()

    total_paginas = ceil(total / por_pagina) if total > 0 else 1

    return render_template(
        "usuarios/lista_usuarios.html",
        usuarios=usuarios,
        busca=busca,
        pagina_atual=page,
        total_paginas=total_paginas
    )


# ======================================================
# 🔹 CADASTRAR USUÁRIO
# ======================================================
@bp_usuarios.route("/cadastro", methods=["GET", "POST"])
@login_required
def cadastro_usuario():

    if not require_admin():
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("usuarios.lista_usuarios")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Carregar roles disponíveis
    cursor.execute("SELECT id, nome FROM roles ORDER BY nome")
    roles = cursor.fetchall()

    if request.method == "POST":

        nome = request.form.get("nome").strip()
        email = request.form.get("email").strip()
        senha = request.form.get("senha").strip()
        roles_escolhidas = request.form.getlist("roles")

        if not nome or not email or not senha or not roles_escolhidas:
            flash("Preencha todos os campos e selecione ao menos uma Role.", "danger")
            return redirect(url_for("usuarios.cadastro_usuario"))

        # Verifica e-mail duplicado
        cursor.execute("SELECT id FROM usuarios WHERE email=%s", (email,))
        if cursor.fetchone():
            flash("Já existe um usuário com este e-mail.", "danger")
            return redirect(url_for("usuarios.cadastro_usuario"))

        senha_hash = generate_password_hash(senha)

        # Inserir usuário
        cursor.execute(
            """
            INSERT INTO usuarios (nome, email, senha)
            VALUES (%s, %s, %s)
            """,
            (nome, email, senha_hash),
        )
        user_id = cursor.lastrowid

        # Inserir roles
        for role_id in roles_escolhidas:
            cursor.execute("""
                INSERT INTO roles_usuario (usuario_id, role_id)
                VALUES (%s, %s)
            """, (user_id, role_id))

        db.commit()
        flash("Usuário cadastrado com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    cursor.close()
    db.close()

    return render_template("usuarios/criar_usuario.html", roles=roles, back_url=back_url)


# ======================================================
# 🔹 EDITAR USUÁRIO
# ======================================================
@bp_usuarios.route("/editar/<int:user_id>", methods=["GET", "POST"])
@login_required
def editar_usuario(user_id):

    if not require_admin():
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("usuarios.lista_usuarios")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Carregar usuário
    cursor.execute("SELECT * FROM usuarios WHERE id=%s", (user_id,))
    usuario = cursor.fetchone()

    if not usuario:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("usuarios.lista_usuarios"))

    # Carregar roles disponíveis
    cursor.execute("SELECT id, nome FROM roles ORDER BY nome")
    roles = cursor.fetchall()

    # Carregar roles do usuário
    cursor.execute("""
        SELECT role_id 
        FROM roles_usuario 
        WHERE usuario_id=%s
    """, (user_id,))
    roles_do_usuario = [r["role_id"] for r in cursor.fetchall()]

    if request.method == "POST":

        nova_senha = request.form.get("senha")
        roles_novas = request.form.getlist("roles")

        # Atualizar senha
        if nova_senha:
            cursor.execute("""
                UPDATE usuarios SET senha=%s WHERE id=%s
            """, (generate_password_hash(nova_senha), user_id))

        # Reset das roles
        cursor.execute("DELETE FROM roles_usuario WHERE usuario_id=%s", (user_id,))
        for role_id in roles_novas:
            cursor.execute("""
                INSERT INTO roles_usuario (usuario_id, role_id)
                VALUES (%s, %s)
            """, (user_id, role_id))

        db.commit()
        flash("Usuário atualizado com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    cursor.close()
    db.close()

    return render_template(
        "usuarios/editar_usuario.html",
        usuario=usuario,
        roles=roles,
        roles_do_usuario=roles_do_usuario,
        back_url=back_url
    )


# ======================================================
# 🔹 EXCLUIR USUÁRIO
# ======================================================
@bp_usuarios.route("/excluir/<int:user_id>", methods=["POST"])
@login_required
def excluir_usuario(user_id):

    if not require_admin():
        return redirect(url_for("usuarios.lista_usuarios"))

    if user_id == current_user.id:
        flash("Você não pode excluir a si mesmo.", "danger")
        return redirect(url_for("usuarios.lista_usuarios"))

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("DELETE FROM roles_usuario WHERE usuario_id=%s", (user_id,))
    cursor.execute("DELETE FROM usuarios WHERE id=%s", (user_id,))
    db.commit()

    cursor.close()
    db.close()

    flash("Usuário removido com sucesso!", "success")
    return redirect(url_for("usuarios.lista_usuarios"))
