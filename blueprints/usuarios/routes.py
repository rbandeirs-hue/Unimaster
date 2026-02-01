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

    # Lista paginada (inclui ativo se a coluna existir)
    if busca:
        cursor.execute("""
            SELECT 
                u.id, u.nome, u.email, u.criado_em,
                COALESCE(u.ativo, 1) AS ativo
            FROM usuarios u
            WHERE nome LIKE %s OR email LIKE %s
            ORDER BY nome
            LIMIT %s OFFSET %s
        """, (f"%{busca}%", f"%{busca}%", por_pagina, offset))
    else:
        cursor.execute("""
            SELECT id, nome, email, criado_em,
                   COALESCE(ativo, 1) AS ativo
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

    # Academias para vínculo (admin: todas ou as suas vinculadas)
    academias_disponiveis = []
    cursor.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
    vinculadas = [r["academia_id"] for r in cursor.fetchall()]
    if vinculadas:
        ph = ",".join(["%s"] * len(vinculadas))
        cursor.execute(f"SELECT id, nome FROM academias WHERE id IN ({ph}) ORDER BY nome", tuple(vinculadas))
        academias_disponiveis = cursor.fetchall()
    else:
        cursor.execute("SELECT id, nome FROM academias ORDER BY nome")
        academias_disponiveis = cursor.fetchall()

    if request.method == "POST":

        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip()
        senha = (request.form.get("senha") or "").strip()
        roles_escolhidas = request.form.getlist("roles")
        academias_escolhidas = []
        for x in request.form.getlist("academias"):
            try:
                aid = int(x)
                if academias_disponiveis and any(a["id"] == aid for a in academias_disponiveis):
                    academias_escolhidas.append(aid)
            except (ValueError, TypeError):
                pass

        if not nome or not email or not senha or not roles_escolhidas:
            flash("Preencha todos os campos e selecione ao menos uma Role.", "danger")
            return redirect(url_for("usuarios.cadastro_usuario"))

        # Verifica e-mail duplicado
        cursor.execute("SELECT id FROM usuarios WHERE email=%s", (email,))
        if cursor.fetchone():
            flash("Já existe um usuário com este e-mail.", "danger")
            return redirect(url_for("usuarios.cadastro_usuario"))

        senha_hash = generate_password_hash(senha)
        id_academia = academias_escolhidas[0] if academias_escolhidas else None

        # Inserir usuário
        cursor.execute(
            "INSERT INTO usuarios (nome, email, senha, id_academia) VALUES (%s, %s, %s, %s)",
            (nome, email, senha_hash, id_academia),
        )
        user_id = cursor.lastrowid

        # Inserir roles
        for role_id in roles_escolhidas:
            cursor.execute("""
                INSERT INTO roles_usuario (usuario_id, role_id)
                VALUES (%s, %s)
            """, (user_id, role_id))

        # Inserir academias vinculadas
        for aid in academias_escolhidas:
            cursor.execute(
                "INSERT INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)",
                (user_id, aid),
            )

        db.commit()
        flash("Usuário cadastrado com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    cursor.close()
    db.close()

    return render_template(
        "usuarios/criar_usuario.html",
        roles=roles,
        back_url=back_url,
        academias_disponiveis=academias_disponiveis,
    )


# ======================================================
# 🔹 EDITAR USUÁRIO
# ======================================================
def _pode_editar_usuario(usuario):
    """Verifica se o usuário logado pode editar o usuário informado."""
    try:
        if current_user.has_role("admin"):
            return True
        if current_user.has_role("gestor_associacao") and getattr(current_user, "id_associacao", None):
            db = get_db_connection()
            cur = db.cursor(dictionary=True)
            try:
                cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
                minhas_ids = [r["academia_id"] for r in cur.fetchall()]
            except Exception:
                minhas_ids = []
            try:
                if minhas_ids:
                    ph = ",".join(["%s"] * len(minhas_ids))
                    cur.execute(
                        f"SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id IN ({ph})",
                        (usuario["id"],) + tuple(minhas_ids),
                    )
                    ok = cur.fetchone() is not None
                    if not ok:
                        ok = usuario.get("id_academia") in minhas_ids
                else:
                    cur.execute("""
                        SELECT 1 FROM usuarios_academias ua
                        JOIN academias ac ON ac.id = ua.academia_id
                        WHERE ua.usuario_id = %s AND ac.id_associacao = %s
                    """, (usuario["id"], current_user.id_associacao))
                    ok = cur.fetchone() is not None
                    if not ok:
                        cur.execute("SELECT 1 FROM academias WHERE id = %s AND id_associacao = %s",
                                    (usuario.get("id_academia"), current_user.id_associacao))
                        ok = cur.fetchone() is not None
            except Exception:
                ok = False
            cur.close()
            db.close()
            return ok
        if current_user.has_role("gestor_academia") or current_user.has_role("professor"):
            db = get_db_connection()
            cur = db.cursor(dictionary=True)
            try:
                cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
                minhas_ids = [r["academia_id"] for r in cur.fetchall()]
            except Exception:
                minhas_ids = []
            if not minhas_ids and getattr(current_user, "id_academia", None):
                minhas_ids = [current_user.id_academia]
            if not minhas_ids:
                cur.close()
                db.close()
                return False
            try:
                ph = ",".join(["%s"] * len(minhas_ids))
                cur.execute(
                    f"SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id IN ({ph})",
                    (usuario["id"],) + tuple(minhas_ids),
                )
                ok = cur.fetchone() is not None
                if not ok:
                    ok = usuario.get("id_academia") in minhas_ids
            except Exception:
                ok = False
            cur.close()
            db.close()
            return ok
    except Exception:
        pass
    return False


@bp_usuarios.route("/editar/<int:user_id>", methods=["GET", "POST"])
@login_required
def editar_usuario(user_id):

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM usuarios WHERE id=%s", (user_id,))
    usuario = cursor.fetchone()

    if not usuario:
        cursor.close()
        db.close()
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("painel.home"))

    if not _pode_editar_usuario(usuario):
        cursor.close()
        db.close()
        flash("Você não tem permissão para editar este usuário.", "danger")
        return redirect(request.args.get("next") or request.referrer or url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("usuarios.lista_usuarios")

    # Carregar roles disponíveis (com chave para aluno/responsavel)
    cursor.execute("SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) as chave FROM roles ORDER BY nome")
    roles = cursor.fetchall()

    # Contexto academia: gestor/professor editando usuário da sua academia
    contexto_academia = (current_user.has_role("gestor_academia") or current_user.has_role("professor")) and _pode_editar_usuario(usuario)
    academia_id_editar = usuario.get("id_academia")
    alunos_para_aluno = []
    alunos_para_responsavel = []
    aluno_vinculado_id = None
    responsavel_aluno_ids = []
    if contexto_academia and academia_id_editar:
        cursor.execute(
            """SELECT id, nome, usuario_id FROM alunos WHERE id_academia = %s AND ativo = 1 AND status = 'ativo'
               ORDER BY nome""",
            (academia_id_editar,),
        )
        todos_alunos = cursor.fetchall()
        alunos_para_aluno = [a for a in todos_alunos if not a.get("usuario_id") or a.get("usuario_id") == user_id]
        alunos_para_responsavel = todos_alunos
        cursor.execute("SELECT id FROM alunos WHERE usuario_id = %s LIMIT 1", (user_id,))
        row = cursor.fetchone()
        if row:
            aluno_vinculado_id = row["id"]
        cursor.execute("SELECT aluno_id FROM responsavel_alunos WHERE usuario_id = %s", (user_id,))
        responsavel_aluno_ids = [r["aluno_id"] for r in cursor.fetchall()]

    # Carregar roles do usuário
    cursor.execute("""
        SELECT role_id 
        FROM roles_usuario 
        WHERE usuario_id=%s
    """, (user_id,))
    roles_do_usuario = [r["role_id"] for r in cursor.fetchall()]

    # Academias vinculadas — só admin e gestor_associacao
    mostrar_academias = current_user.has_role("admin") or current_user.has_role("gestor_associacao")
    academias_vinculadas = []
    academias_disponiveis = []

    if mostrar_academias:
        try:
            cursor.execute("""
                SELECT ua.academia_id, ac.nome
                FROM usuarios_academias ua
                JOIN academias ac ON ac.id = ua.academia_id
                WHERE ua.usuario_id = %s
                ORDER BY ac.nome
            """, (user_id,))
            academias_vinculadas = cursor.fetchall()
        except Exception:
            academias_vinculadas = []

        ids_permitidos = []
        try:
            cursor.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
            vinculadas = [r["academia_id"] for r in cursor.fetchall()]
        except Exception:
            vinculadas = []
        if vinculadas:
            ids_permitidos = vinculadas
        elif current_user.has_role("admin"):
            cursor.execute("SELECT id FROM academias")
            ids_permitidos = [r["id"] for r in cursor.fetchall()]
        elif current_user.has_role("gestor_associacao") and getattr(current_user, "id_associacao", None):
            cursor.execute("SELECT id FROM academias WHERE id_associacao = %s", (current_user.id_associacao,))
            ids_permitidos = [r["id"] for r in cursor.fetchall()]
        if ids_permitidos:
            ph = ",".join(["%s"] * len(ids_permitidos))
            cursor.execute(f"SELECT id, nome FROM academias WHERE id IN ({ph}) ORDER BY nome", tuple(ids_permitidos))
            academias_disponiveis = cursor.fetchall()

    if request.method == "POST":

        nova_senha = request.form.get("senha")
        roles_novas = request.form.getlist("roles")

        # Foto (câmera base64 ou arquivo)
        try:
            from blueprints.aluno.alunos import salvar_imagem_base64, salvar_arquivo_upload
            foto_dataurl = request.form.get("foto")
            foto_arquivo = request.files.get("foto_arquivo")
            foto_filename = None
            if foto_dataurl:
                foto_filename = salvar_imagem_base64(foto_dataurl, f"usuario_{user_id}")
            elif foto_arquivo and foto_arquivo.filename:
                foto_filename = salvar_arquivo_upload(foto_arquivo, f"usuario_{user_id}")
            if foto_filename:
                cursor.execute("UPDATE usuarios SET foto = %s WHERE id = %s", (foto_filename, user_id))
        except Exception:
            pass

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

        # Academias vinculadas
        if mostrar_academias and academias_disponiveis:
            ids_permitidos = {a["id"] for a in academias_disponiveis}
            academias_escolhidas = []
            for x in request.form.getlist("academias"):
                try:
                    aid = int(x)
                    if aid in ids_permitidos:
                        academias_escolhidas.append(aid)
                except (ValueError, TypeError):
                    pass

            cursor.execute("DELETE FROM usuarios_academias WHERE usuario_id = %s", (user_id,))
            for aid in academias_escolhidas:
                cursor.execute(
                    "INSERT INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)",
                    (user_id, aid),
                )
            id_academia = academias_escolhidas[0] if academias_escolhidas else None
            cursor.execute("UPDATE usuarios SET id_academia = %s WHERE id = %s", (id_academia, user_id))

        # Vínculo aluno/responsavel (contexto academia)
        if contexto_academia and academia_id_editar:
            cursor.execute("SELECT id FROM roles WHERE chave = 'aluno'")
            r_aluno = cursor.fetchone()
            cursor.execute("SELECT id FROM roles WHERE chave = 'responsavel'")
            r_resp = cursor.fetchone()
            roles_str = [str(x) for x in roles_novas]
            # Remover vínculos antigos
            cursor.execute("UPDATE alunos SET usuario_id = NULL WHERE usuario_id = %s", (user_id,))
            cursor.execute("DELETE FROM responsavel_alunos WHERE usuario_id = %s", (user_id,))
            if r_aluno and str(r_aluno["id"]) in roles_str:
                aluno_id = request.form.get("aluno_id", type=int)
                if aluno_id:
                    cursor.execute(
                        "UPDATE alunos SET usuario_id = %s WHERE id = %s AND id_academia = %s",
                        (user_id, aluno_id, academia_id_editar),
                    )
            if r_resp and str(r_resp.get("id", "")) in roles_str:
                for x in request.form.getlist("aluno_ids"):
                    try:
                        aid = int(x)
                        cursor.execute("SELECT 1 FROM alunos WHERE id = %s AND id_academia = %s", (aid, academia_id_editar))
                        if cursor.fetchone():
                            cursor.execute(
                                "INSERT IGNORE INTO responsavel_alunos (usuario_id, aluno_id) VALUES (%s, %s)",
                                (user_id, aid),
                            )
                    except (ValueError, TypeError):
                        pass

        db.commit()
        flash("Usuário atualizado com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    cursor.close()
    db.close()

    academias_vinculadas_ids = [a.get("academia_id") for a in academias_vinculadas if a.get("academia_id") is not None]

    return render_template(
        "usuarios/editar_usuario.html",
        usuario=usuario,
        roles=roles,
        roles_do_usuario=roles_do_usuario,
        back_url=back_url,
        mostrar_academias=mostrar_academias,
        academias_vinculadas=academias_vinculadas,
        academias_disponiveis=academias_disponiveis,
        academias_vinculadas_ids=academias_vinculadas_ids,
        contexto_academia=contexto_academia,
        alunos_para_aluno=alunos_para_aluno,
        alunos_para_responsavel=alunos_para_responsavel,
        aluno_vinculado_id=aluno_vinculado_id,
        responsavel_aluno_ids=responsavel_aluno_ids,
    )


# ======================================================
# 🔹 MEU PERFIL (usuário edita seu próprio cadastro e senha)
# ======================================================
@bp_usuarios.route("/meu-perfil", methods=["GET", "POST"])
@login_required
def meu_perfil():
    """Permite que o usuário logado edite seu próprio nome, e-mail e senha."""
    user_id = current_user.id
    back_url = request.args.get("next") or request.referrer or url_for("painel.home")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id, nome, email FROM usuarios WHERE id=%s", (user_id,))
    usuario = cursor.fetchone()

    if not usuario:
        flash("Usuário não encontrado.", "danger")
        db.close()
        return redirect(url_for("painel.home"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip()
        nova_senha = request.form.get("senha") or None

        erros = []
        if not nome:
            erros.append("Nome é obrigatório.")
        if not email:
            erros.append("E-mail é obrigatório.")

        if erros:
            for e in erros:
                flash(e, "danger")
        else:
            try:
                cursor.execute(
                    "SELECT id FROM usuarios WHERE email=%s AND id != %s",
                    (email, user_id),
                )
                if cursor.fetchone():
                    flash("Este e-mail já está em uso por outro usuário.", "danger")
                else:
                    if nova_senha:
                        cursor.execute(
                            "UPDATE usuarios SET nome=%s, email=%s, senha=%s WHERE id=%s",
                            (nome, email, generate_password_hash(nova_senha), user_id),
                        )
                        flash("Cadastro e senha atualizados com sucesso!", "success")
                    else:
                        cursor.execute(
                            "UPDATE usuarios SET nome=%s, email=%s WHERE id=%s",
                            (nome, email, user_id),
                        )
                        flash("Cadastro atualizado com sucesso!", "success")
                    db.commit()
                    redirect_url = request.form.get("next") or back_url
                    db.close()
                    return redirect(redirect_url)
            except Exception as e:
                db.rollback()
                flash(f"Erro ao atualizar: {e}", "danger")

    cursor.close()
    db.close()

    return render_template(
        "usuarios/meu_perfil.html",
        usuario=usuario,
        back_url=back_url,
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
