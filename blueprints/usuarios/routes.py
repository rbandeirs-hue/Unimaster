# ======================================================
# 🧩 Blueprint: Usuários (TOTALMENTE AJUSTADO PARA ROLES)
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from blueprints.auth.user_model import Usuario
from blueprints.auth.routes import _so_digitos, _valida_cpf
from config import get_db_connection
from utils.foto_sync import propagar_foto_usuario_para_aluno
from math import ceil

bp_usuarios = Blueprint("usuarios", __name__, url_prefix="/usuarios")


def _ctx_shell():
    """Contexto que o `base_academia.html` consome: item ativo da lateral,
    seletor de academia do topo e nome no rodapé. Sem academia no contexto,
    a lateral esconde sozinha os itens que dependem dela."""
    academia_id = (session.get("academia_gerenciamento_id")
                   or getattr(current_user, "id_academia", None))
    if not academia_id:
        return {"academia": None, "academias": [], "academia_id": None}
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s",
                    (current_user.id,))
        ids = [r["academia_id"] for r in cur.fetchall()] or []
        if academia_id not in ids:
            ids.append(academia_id)
        cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome"
                    % ",".join(["%s"] * len(ids)), tuple(ids))
        academias = cur.fetchall()
    except Exception:
        academias = []
    finally:
        cur.close()
        db.close()
    academia = next((a for a in academias if a["id"] == academia_id), None)
    return {"academia": academia, "academias": academias, "academia_id": academia_id}


# ======================================================
# 🔹 Verificação geral de permissão
# ======================================================
def require_admin():
    if not current_user.has_role("admin"):
        flash("Acesso restrito aos administradores.", "danger")
        return False
    return True


def require_admin_or_gestor():
    """Verifica se o usuário é admin, gestor_academia ou gestor_associacao."""
    if not (
        current_user.has_role("admin") or
        current_user.has_role("gestor_academia") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso restrito aos administradores, gestores de academia e gestores de associação.", "danger")
        return False
    return True


# ======================================================
# 🔹 LISTA DE USUÁRIOS
# ======================================================
@bp_usuarios.route("/lista")
@login_required
def lista_usuarios():

    if not require_admin_or_gestor():
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

    # CARREGAR ROLES E ALUNO VINCULADO DE CADA USUÁRIO
    for u in usuarios:
        # Roles / níveis
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

        # Aluno vinculado (para modal com foto)
        try:
            cursor.execute(
                "SELECT id, nome, foto FROM alunos WHERE usuario_id = %s LIMIT 1",
                (u["id"],),
            )
            aluno = cursor.fetchone()
        except Exception:
            aluno = None
        if aluno:
            u["aluno_id"] = aluno.get("id")
            u["aluno_nome"] = aluno.get("nome")
            u["aluno_foto"] = aluno.get("foto")
        else:
            u["aluno_id"] = None
            u["aluno_nome"] = None
            u["aluno_foto"] = None

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

    if not require_admin_or_gestor():
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("usuarios.lista_usuarios")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Carregar roles disponíveis
    cursor.execute("SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) as chave FROM roles ORDER BY nome")
    roles = cursor.fetchall()

    # Academias para vínculo
    academias_disponiveis = []
    if current_user.has_role("admin"):
        # Admin: todas as academias ou as suas vinculadas
        cursor.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cursor.fetchall()]
        if vinculadas:
            ph = ",".join(["%s"] * len(vinculadas))
            cursor.execute(f"SELECT id, nome FROM academias WHERE id IN ({ph}) ORDER BY nome", tuple(vinculadas))
            academias_disponiveis = cursor.fetchall()
        else:
            cursor.execute("SELECT id, nome FROM academias ORDER BY nome")
            academias_disponiveis = cursor.fetchall()
    elif current_user.has_role("gestor_associacao") and getattr(current_user, "id_associacao", None):
        # Gestor de associação: academias da sua associação
        cursor.execute("SELECT id, nome FROM academias WHERE id_associacao = %s ORDER BY nome", (current_user.id_associacao,))
        academias_disponiveis = cursor.fetchall()
    elif current_user.has_role("gestor_academia"):
        # Gestor de academia: apenas academias vinculadas ao usuário
        cursor.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cursor.fetchall()]
        if vinculadas:
            ph = ",".join(["%s"] * len(vinculadas))
            cursor.execute(f"SELECT id, nome FROM academias WHERE id IN ({ph}) ORDER BY nome", tuple(vinculadas))
            academias_disponiveis = cursor.fetchall()

    if request.method == "POST":

        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip()
        cpf = _so_digitos(request.form.get("cpf") or "")
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

        if not nome or not email or not cpf or not senha or not roles_escolhidas:
            flash("Preencha todos os campos (incluindo CPF) e selecione ao menos uma Role.", "danger")
            return redirect(url_for("usuarios.cadastro_usuario"))

        if not _valida_cpf(cpf):
            flash("CPF inválido. Verifique e tente novamente.", "danger")
            return redirect(url_for("usuarios.cadastro_usuario"))

        # Verifica e-mail duplicado
        cursor.execute("SELECT id FROM usuarios WHERE email=%s", (email,))
        if cursor.fetchone():
            flash("Já existe um usuário com este e-mail.", "danger")
            return redirect(url_for("usuarios.cadastro_usuario"))

        # Verifica CPF duplicado (será o login)
        cursor.execute("SELECT id FROM usuarios WHERE cpf=%s", (cpf,))
        if cursor.fetchone():
            flash("Já existe um usuário com este CPF.", "danger")
            return redirect(url_for("usuarios.cadastro_usuario"))

        senha_hash = generate_password_hash(senha)
        id_academia = academias_escolhidas[0] if academias_escolhidas else None

        # Buscar id_associacao e id_federacao da academia selecionada (se houver)
        id_associacao_usuario = None
        id_federacao_usuario = None
        if id_academia:
            cursor.execute("""
                SELECT ac.id_associacao, ass.id_federacao
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ac.id = %s
            """, (id_academia,))
            acad_info = cursor.fetchone()
            if acad_info:
                id_associacao_usuario = acad_info.get("id_associacao")
                id_federacao_usuario = acad_info.get("id_federacao")

        # Inserir usuário com id_federacao, id_associacao e CPF
        cursor.execute(
            """INSERT INTO usuarios (nome, email, cpf, senha, id_academia, id_associacao, id_federacao)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (nome, email, cpf, senha_hash, id_academia, id_associacao_usuario, id_federacao_usuario),
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

        # Vínculo automático com aluno se a role "Aluno" foi marcada e existe um aluno
        # com o mesmo CPF nas academias selecionadas (ou em qualquer academia se nenhuma foi).
        cursor.execute("SELECT id FROM roles WHERE chave = 'aluno' OR LOWER(nome) = 'aluno' LIMIT 1")
        role_aluno = cursor.fetchone()
        aluno_vinculado = None
        if role_aluno and str(role_aluno["id"]) in [str(r) for r in roles_escolhidas]:
            params = [cpf]
            sql_busca = (
                "SELECT id, id_academia, cpf FROM alunos "
                "WHERE REGEXP_REPLACE(COALESCE(cpf,''), '[^0-9]', '') = %s "
                "AND (usuario_id IS NULL OR usuario_id = 0)"
            )
            if academias_escolhidas:
                ph = ",".join(["%s"] * len(academias_escolhidas))
                sql_busca += f" AND id_academia IN ({ph})"
                params.extend(academias_escolhidas)
            sql_busca += " LIMIT 1"
            cursor.execute(sql_busca, tuple(params))
            aluno_vinculado = cursor.fetchone()
            if aluno_vinculado:
                cursor.execute(
                    "UPDATE alunos SET usuario_id = %s WHERE id = %s",
                    (user_id, aluno_vinculado["id"]),
                )

        db.commit()
        if role_aluno and str(role_aluno["id"]) in [str(r) for r in roles_escolhidas]:
            if aluno_vinculado:
                flash(f"Usuário cadastrado e vinculado automaticamente ao aluno (id {aluno_vinculado['id']}) pelo CPF.", "success")
            else:
                flash("Usuário cadastrado. Nenhum aluno com este CPF foi encontrado para vínculo automático — use a edição do usuário para vincular ou cadastrar o aluno.", "warning")
        else:
            flash("Usuário cadastrado com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    cursor.close()
    db.close()

    from flask import session
    modo_painel = session.get("modo_painel")
    # No modo academia, esconder roles de acesso global (admin, gestor_associacao, gestor_federacao)
    roles_filtradas = []
    for r in roles:
        chave = (r.get("chave") or r.get("nome") or "").lower()
        if modo_painel == "academia" and chave in ("admin", "gestor_associacao", "gestor_federacao"):
            continue
        roles_filtradas.append(r)

    return render_template(
        "usuarios/criar_usuario.html",
        roles=roles_filtradas,
        back_url=back_url,
        academias_disponiveis=academias_disponiveis,
        **_ctx_shell(),
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
                # Gestor de associação pode editar usuários de qualquer academia da associação
                cur.execute("""
                    SELECT 1 FROM usuarios_academias ua
                    JOIN academias ac ON ac.id = ua.academia_id
                    WHERE ua.usuario_id = %s AND ac.id_associacao = %s
                    LIMIT 1
                """, (usuario["id"], current_user.id_associacao))
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
            if not minhas_ids:
                cur.close()
                db.close()
                return False
            try:
                ph = ",".join(["%s"] * len(minhas_ids))
                cur.execute(
                    f"SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id IN ({ph}) LIMIT 1",
                    (usuario["id"],) + tuple(minhas_ids),
                )
                ok = cur.fetchone() is not None
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
    # Todas as academias do usuário editado — e não só a primeira por id.
    # Dependente não tem academia: `responsavel_alunos` é global. Com uma
    # academia só, um pai que treina numa e tem filho em outra nunca conseguia
    # marcar esse filho, e pior: salvar apagava o vínculo que já existia.
    cursor.execute(
        "SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id",
        (user_id,),
    )
    academias_editar = [r["academia_id"] for r in cursor.fetchall()]
    # O gestor só enxerga (e só mexe) no que ele próprio administra.
    if not (current_user.has_role("admin") or current_user.has_role("gestor_associacao")):
        cursor.execute(
            "SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s",
            (current_user.id,),
        )
        minhas = {r["academia_id"] for r in cursor.fetchall()}
        _atual = session.get("academia_gerenciamento_id") or getattr(current_user, "id_academia", None)
        if _atual:
            minhas.add(_atual)
        academias_editar = [a for a in academias_editar if a in minhas]
    academia_id_editar = academias_editar[0] if academias_editar else None
    alunos_para_aluno = []
    alunos_para_responsavel = []
    aluno_vinculado_id = None
    responsavel_aluno_ids = []
    
    # Buscar dados do visitante se existir
    visitante_dados = None
    cursor.execute("SELECT * FROM visitantes WHERE usuario_id = %s LIMIT 1", (user_id,))
    visitante_row = cursor.fetchone()
    if visitante_row:
        visitante_dados = visitante_row
    
    if contexto_academia and academias_editar:
        _ph = ", ".join(["%s"] * len(academias_editar))
        cursor.execute(
            f"""SELECT al.id, al.nome, al.usuario_id, al.id_academia, ac.nome AS academia_nome
                FROM alunos al LEFT JOIN academias ac ON ac.id = al.id_academia
                WHERE al.id_academia IN ({_ph}) AND al.ativo = 1 AND al.status = 'ativo'
                ORDER BY al.nome""",
            tuple(academias_editar),
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

    # Academias vinculadas: admin e gestor_associacao editam; gestor_academia vê bloqueado (somente leitura)
    mostrar_academias = (
        current_user.has_role("admin") or
        current_user.has_role("gestor_associacao") or
        current_user.has_role("gestor_academia")
    )
    # Bloquear academias apenas quando no modo academia; no modo associação pode alterar
    academias_bloqueadas = (
        session.get("modo_painel") == "academia" and current_user.has_role("gestor_academia")
    )
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
        # gestor_associacao: sempre todas as academias da associação
        if current_user.has_role("gestor_associacao") and getattr(current_user, "id_associacao", None):
            cursor.execute("SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome", (current_user.id_associacao,))
            ids_permitidos = [r["id"] for r in cursor.fetchall()]
        elif current_user.has_role("gestor_academia"):
            # gestor_academia: apenas academias de usuarios_academias (para exibir bloqueada)
            cursor.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
            ids_permitidos = [r["academia_id"] for r in cursor.fetchall()]
        else:
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
        if ids_permitidos:
            ph = ",".join(["%s"] * len(ids_permitidos))
            cursor.execute(f"SELECT id, nome FROM academias WHERE id IN ({ph}) ORDER BY nome", tuple(ids_permitidos))
            academias_disponiveis = cursor.fetchall()

    if request.method == "POST":

        nova_senha = request.form.get("senha")
        roles_novas = request.form.getlist("roles")

        # CPF: validar, garantir unicidade e atualizar (sincronizando com o aluno vinculado se houver)
        cpf_form = _so_digitos(request.form.get("cpf") or "")
        if cpf_form:
            if not _valida_cpf(cpf_form):
                flash("CPF inválido. Verifique e tente novamente.", "danger")
                cursor.close()
                db.close()
                return redirect(url_for("usuarios.editar_usuario", user_id=user_id))
            cursor.execute("SELECT id FROM usuarios WHERE cpf = %s AND id <> %s", (cpf_form, user_id))
            if cursor.fetchone():
                flash("Este CPF já está em uso por outro usuário.", "danger")
                cursor.close()
                db.close()
                return redirect(url_for("usuarios.editar_usuario", user_id=user_id))
            cursor.execute("UPDATE usuarios SET cpf = %s WHERE id = %s", (cpf_form, user_id))
            # Propagar para o cadastro de aluno vinculado, se ainda não tiver CPF
            cursor.execute(
                "UPDATE alunos SET cpf = %s WHERE usuario_id = %s "
                "AND (cpf IS NULL OR cpf = '' OR REGEXP_REPLACE(cpf, '[^0-9]', '') = '')",
                (cpf_form, user_id),
            )

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
                propagar_foto_usuario_para_aluno(cursor, user_id, foto_filename)
        except Exception:
            pass

        # Atualizar senha
        if nova_senha:
            cursor.execute("""
                UPDATE usuarios SET senha=%s WHERE id=%s
            """, (generate_password_hash(nova_senha), user_id))

        # Verificar se role visitante está sendo adicionada ou removida ANTES de deletar roles
        cursor.execute("SELECT id FROM roles WHERE chave = 'visitante' OR nome = 'Visitante' LIMIT 1")
        role_visitante = cursor.fetchone()
        role_visitante_id = role_visitante.get("id") if role_visitante else None
        
        tinha_role_visitante = False
        tem_role_visitante_agora = False
        
        if role_visitante_id:
            cursor.execute("SELECT 1 FROM roles_usuario WHERE usuario_id = %s AND role_id = %s", (user_id, role_visitante_id))
            tinha_role_visitante = cursor.fetchone() is not None
            tem_role_visitante_agora = str(role_visitante_id) in roles_novas

        # Reset das roles — APENAS as que estavam visíveis no formulário.
        # Roles fora do escopo (ex.: admin/gestor_associacao/gestor_federacao no modo
        # academia) ficam ESCONDIDAS no form, mas NÃO devem ser apagadas. Antes era
        # feito DELETE de todas, o que zerava roles invisíveis e corrompia o cadastro.
        _modo_painel_atual = session.get("modo_painel")
        _roles_ocultas = ("admin", "gestor_associacao", "gestor_federacao")
        roles_visiveis_ids = []
        for r in roles:
            chave = (r.get("chave") or r.get("nome") or "").lower()
            if _modo_painel_atual == "academia" and chave in _roles_ocultas:
                continue
            if r.get("id") is not None:
                roles_visiveis_ids.append(r["id"])

        if roles_visiveis_ids:
            ph = ",".join(["%s"] * len(roles_visiveis_ids))
            cursor.execute(
                f"DELETE FROM roles_usuario WHERE usuario_id=%s AND role_id IN ({ph})",
                (user_id, *roles_visiveis_ids),
            )

        # Insere apenas as que foram efetivamente marcadas E estavam no escopo do form
        ids_visiveis_set = set(str(rid) for rid in roles_visiveis_ids)
        for role_id in roles_novas:
            if not ids_visiveis_set or str(role_id) in ids_visiveis_set:
                cursor.execute("""
                    INSERT IGNORE INTO roles_usuario (usuario_id, role_id)
                    VALUES (%s, %s)
                """, (user_id, role_id))

        # Academias vinculadas (não atualiza se bloqueado para gestor_academia)
        if mostrar_academias and academias_disponiveis and not academias_bloqueadas:
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
            
            # Buscar id_associacao e id_federacao da academia selecionada (se houver)
            id_associacao_usuario = None
            id_federacao_usuario = None
            if id_academia:
                cursor.execute("""
                    SELECT ac.id_associacao, ass.id_federacao
                    FROM academias ac
                    LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                    WHERE ac.id = %s
                """, (id_academia,))
                acad_info = cursor.fetchone()
                if acad_info:
                    id_associacao_usuario = acad_info.get("id_associacao")
                    id_federacao_usuario = acad_info.get("id_federacao")
            
            cursor.execute("UPDATE usuarios SET id_academia = %s, id_associacao = %s, id_federacao = %s WHERE id = %s", 
                         (id_academia, id_associacao_usuario, id_federacao_usuario, user_id))
        
        # Gerenciar registro de visitante (após atualizar academias)
        if tem_role_visitante_agora and not tinha_role_visitante:
            # Criar registro de visitante
            # Buscar primeira academia vinculada ao usuário
            cursor.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id LIMIT 1", (user_id,))
            acad_row = cursor.fetchone()
            academia_id_visitante = None
            if acad_row:
                academia_id_visitante = acad_row["academia_id"]
            elif usuario.get("id_academia"):
                academia_id_visitante = usuario.get("id_academia")
            
            if academia_id_visitante:
                # Buscar limite de aulas da academia
                cursor.execute("SELECT aulas_experimentais_permitidas FROM academias WHERE id = %s", (academia_id_visitante,))
                acad_config = cursor.fetchone()
                limite_aulas = acad_config.get("aulas_experimentais_permitidas") if acad_config else None
                
                # Verificar se já existe visitante
                cursor.execute("SELECT id FROM visitantes WHERE usuario_id = %s", (user_id,))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO visitantes (nome, email, telefone, usuario_id, id_academia, aulas_experimentais_permitidas, ativo)
                        VALUES (%s, %s, %s, %s, %s, %s, 1)
                    """, (
                        usuario.get("nome"),
                        usuario.get("email"),
                        None,  # telefone pode ser adicionado depois
                        user_id,
                        academia_id_visitante,
                        limite_aulas,
                    ))
        elif tinha_role_visitante and not tem_role_visitante_agora:
            # Remover role visitante - manter registro mas desativar
            cursor.execute("UPDATE visitantes SET ativo = 0 WHERE usuario_id = %s", (user_id,))
        elif tem_role_visitante_agora and tinha_role_visitante:
            # Reativar visitante se estava desativado e atualizar academia se necessário
            cursor.execute("UPDATE visitantes SET ativo = 1 WHERE usuario_id = %s", (user_id,))
            # Atualizar academia do visitante se academias foram alteradas
            if mostrar_academias and academias_disponiveis and not academias_bloqueadas:
                cursor.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id LIMIT 1", (user_id,))
                acad_row = cursor.fetchone()
                if acad_row:
                    cursor.execute("UPDATE visitantes SET id_academia = %s WHERE usuario_id = %s", (acad_row["academia_id"], user_id))

        # Vínculo aluno/responsavel (contexto academia)
        if contexto_academia and academias_editar:
            _ph = ", ".join(["%s"] * len(academias_editar))
            cursor.execute("SELECT id FROM roles WHERE chave = 'aluno'")
            r_aluno = cursor.fetchone()
            cursor.execute("SELECT id FROM roles WHERE chave = 'responsavel'")
            r_resp = cursor.fetchone()
            roles_str = [str(x) for x in roles_novas]
            # Remover vínculos antigos — só dentro do que esta tela mostra.
            # Apagar tudo fazia o gestor de uma academia derrubar, sem saber, o
            # vínculo de um aluno de outra que ele nem via na lista.
            cursor.execute(
                f"UPDATE alunos SET usuario_id = NULL "
                f"WHERE usuario_id = %s AND id_academia IN ({_ph})",
                (user_id, *academias_editar),
            )
            cursor.execute(
                f"""DELETE ra FROM responsavel_alunos ra
                    JOIN alunos al ON al.id = ra.aluno_id
                    WHERE ra.usuario_id = %s AND al.id_academia IN ({_ph})""",
                (user_id, *academias_editar),
            )
            if r_aluno and str(r_aluno["id"]) in roles_str:
                aluno_id = request.form.get("aluno_id", type=int)
                if aluno_id:
                    cursor.execute(
                        f"UPDATE alunos SET usuario_id = %s "
                        f"WHERE id = %s AND id_academia IN ({_ph})",
                        (user_id, aluno_id, *academias_editar),
                    )
            if r_resp and str(r_resp.get("id", "")) in roles_str:
                for x in request.form.getlist("aluno_ids"):
                    try:
                        aid = int(x)
                        cursor.execute(
                            f"SELECT 1 FROM alunos WHERE id = %s AND id_academia IN ({_ph})",
                            (aid, *academias_editar),
                        )
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

    # Filtrar roles visíveis no modo academia (evitar oferecer admin/gestor_associacao/gestor_federacao)
    modo_painel = session.get("modo_painel")
    roles_filtradas = []
    for r in roles:
        chave = (r.get("chave") or r.get("nome") or "").lower()
        if modo_painel == "academia" and chave in ("admin", "gestor_associacao", "gestor_federacao"):
            continue
        roles_filtradas.append(r)

    return render_template(
        "usuarios/editar_usuario.html",
        usuario=usuario,
        roles=roles_filtradas,
        roles_do_usuario=roles_do_usuario,
        back_url=back_url,
        mostrar_academias=mostrar_academias,
        academias_vinculadas=academias_vinculadas,
        academias_disponiveis=academias_disponiveis,
        academias_vinculadas_ids=academias_vinculadas_ids,
        academias_bloqueadas=academias_bloqueadas,
        contexto_academia=contexto_academia,
        alunos_para_aluno=alunos_para_aluno,
        alunos_para_responsavel=alunos_para_responsavel,
        aluno_vinculado_id=aluno_vinculado_id,
        responsavel_aluno_ids=responsavel_aluno_ids,
        visitante_dados=visitante_dados,
        **_ctx_shell(),
    )


# ======================================================
# 🔹 MEU PERFIL (usuário edita seu próprio cadastro e senha)
# ======================================================
@bp_usuarios.route("/meu-perfil", methods=["GET", "POST"])
@login_required
def meu_perfil():
    """Permite que o usuário logado edite seu próprio nome, e-mail e senha."""
    from urllib.parse import urlparse
    
    user_id = current_user.id
    next_url = request.args.get("next") or request.form.get("next")
    
    # Validar URL segura
    if next_url:
        parsed = urlparse(next_url)
        # Permitir apenas URLs relativas ou do mesmo host
        if parsed.netloc and parsed.netloc not in ['', 'www.rmservicosnet.com.br', 'rmservicosnet.com.br']:
            next_url = None
    
    back_url = next_url or request.referrer or url_for("painel.home")

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT id, nome, email, cpf, foto FROM usuarios WHERE id=%s", (user_id,))
        usuario = cursor.fetchone()

        if not usuario:
            flash("Usuário não encontrado.", "danger")
            return redirect(url_for("painel.home"))

        # Buscar aluno vinculado ao usuário (se houver)
        cursor.execute("SELECT id, nome, foto FROM alunos WHERE usuario_id=%s LIMIT 1", (user_id,))
        aluno_vinculado = cursor.fetchone()

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            email = (request.form.get("email") or "").strip()
            cpf_form = _so_digitos(request.form.get("cpf") or "")
            nova_senha = request.form.get("senha") or None

            erros = []
            if not nome:
                erros.append("Nome é obrigatório.")
            if not email:
                erros.append("E-mail é obrigatório.")
            # CPF: se já cadastrado, é exigido (mantém o atual). Se não tem, é obrigatório informar.
            if not usuario.get("cpf") and not cpf_form:
                erros.append("CPF é obrigatório.")
            if cpf_form and not _valida_cpf(cpf_form):
                erros.append("CPF inválido.")

            if erros:
                for e in erros:
                    flash(e, "danger")
            else:
                try:
                    cursor.execute(
                        "SELECT id FROM usuarios WHERE email=%s AND id != %s",
                        (email, user_id),
                    )
                    email_em_uso = cursor.fetchone() is not None
                    cpf_em_uso = False
                    if cpf_form:
                        cursor.execute(
                            "SELECT id FROM usuarios WHERE cpf=%s AND id != %s",
                            (cpf_form, user_id),
                        )
                        cpf_em_uso = cursor.fetchone() is not None

                    if email_em_uso:
                        flash("Este e-mail já está em uso por outro usuário.", "danger")
                    elif cpf_em_uso:
                        flash("Este CPF já está em uso por outro usuário.", "danger")
                    else:
                        # Atualizar CPF (se informado e ainda não cadastrado, ou se mudou)
                        if cpf_form and cpf_form != (usuario.get("cpf") or ""):
                            cursor.execute("UPDATE usuarios SET cpf=%s WHERE id=%s", (cpf_form, user_id))
                            cursor.execute(
                                "UPDATE alunos SET cpf=%s WHERE usuario_id=%s "
                                "AND (cpf IS NULL OR cpf = '' OR REGEXP_REPLACE(cpf, '[^0-9]', '') = '')",
                                (cpf_form, user_id),
                            )
                        # Foto (câmera base64 ou arquivo)
                        try:
                            from blueprints.aluno.alunos import salvar_imagem_base64, salvar_arquivo_upload
                            foto_dataurl = request.form.get("foto")
                            foto_arquivo = request.files.get("foto_arquivo")
                            foto_filename = None
                            if foto_dataurl and foto_dataurl.startswith("data:"):
                                foto_filename = salvar_imagem_base64(foto_dataurl, f"usuario_{user_id}")
                            elif foto_arquivo and foto_arquivo.filename:
                                foto_filename = salvar_arquivo_upload(foto_arquivo, f"usuario_{user_id}")
                        except Exception as e:
                            current_app.logger.error(f"Erro ao processar foto: {e}")
                            foto_filename = None

                        if nova_senha:
                            if foto_filename:
                                cursor.execute(
                                    "UPDATE usuarios SET nome=%s, email=%s, senha=%s, foto=%s WHERE id=%s",
                                    (nome, email, generate_password_hash(nova_senha), foto_filename, user_id),
                                )
                            else:
                                cursor.execute(
                                    "UPDATE usuarios SET nome=%s, email=%s, senha=%s WHERE id=%s",
                                    (nome, email, generate_password_hash(nova_senha), user_id),
                                )
                            flash("Cadastro e senha atualizados com sucesso!", "success")
                        else:
                            if foto_filename:
                                cursor.execute(
                                    "UPDATE usuarios SET nome=%s, email=%s, foto=%s WHERE id=%s",
                                    (nome, email, foto_filename, user_id),
                                )
                            else:
                                cursor.execute(
                                    "UPDATE usuarios SET nome=%s, email=%s WHERE id=%s",
                                    (nome, email, user_id),
                                )
                            flash("Cadastro atualizado com sucesso!", "success")
                        if foto_filename:
                            propagar_foto_usuario_para_aluno(cursor, user_id, foto_filename)
                        db.commit()
                        # Validar URL de redirecionamento
                        redirect_url = request.form.get("next") or back_url
                        parsed_redirect = urlparse(redirect_url)
                        if parsed_redirect.netloc and parsed_redirect.netloc not in ['', 'www.rmservicosnet.com.br', 'rmservicosnet.com.br']:
                            redirect_url = url_for("painel.home")
                        return redirect(redirect_url)
                except Exception as e:
                    db.rollback()
                    current_app.logger.error(f"Erro ao atualizar usuário: {e}")
                    flash(f"Erro ao atualizar: {e}", "danger")

        return render_template(
            "usuarios/meu_perfil.html",
            usuario=usuario,
            aluno_vinculado=aluno_vinculado,
            back_url=back_url,
        )
    except Exception as e:
        current_app.logger.error(f"Erro em meu_perfil: {e}")
        flash(f"Erro ao carregar página: {e}", "danger")
        return redirect(url_for("painel.home"))
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


# ======================================================
# 🔹 SINCRONIZAR FOTO DO ALUNO PARA O USUÁRIO
# ======================================================
@bp_usuarios.route("/sincronizar-foto-aluno", methods=["POST"])
@login_required
def sincronizar_foto_aluno():
    """Copia a foto do aluno vinculado para o usuário."""
    user_id = current_user.id
    back_url = request.form.get("next") or request.referrer or url_for("usuarios.meu_perfil")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        # Buscar aluno vinculado ao usuário
        cursor.execute("SELECT id, nome, foto FROM alunos WHERE usuario_id=%s LIMIT 1", (user_id,))
        aluno = cursor.fetchone()

        if not aluno:
            flash("Você não possui um aluno vinculado.", "warning")
            cursor.close()
            db.close()
            return redirect(back_url)

        if not aluno.get("foto"):
            flash("O aluno vinculado não possui foto cadastrada.", "warning")
            cursor.close()
            db.close()
            return redirect(back_url)

        # Copiar o arquivo de foto do aluno para o usuário
        import os
        import shutil
        from datetime import datetime

        foto_aluno = aluno["foto"]
        upload_folder = os.path.join(current_app.root_path, "static", "uploads")
        arquivo_origem = os.path.join(upload_folder, foto_aluno)

        if not os.path.exists(arquivo_origem):
            flash("Arquivo de foto do aluno não encontrado.", "danger")
            cursor.close()
            db.close()
            return redirect(back_url)

        # Criar novo nome de arquivo para o usuário
        _, ext = os.path.splitext(foto_aluno)
        if not ext:
            ext = ".png"
        nova_foto = f"usuario_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext.lower()}"
        arquivo_destino = os.path.join(upload_folder, nova_foto)

        # Copiar arquivo
        shutil.copy2(arquivo_origem, arquivo_destino)

        # Atualizar foto do usuário no banco
        cursor.execute("UPDATE usuarios SET foto=%s WHERE id=%s", (nova_foto, user_id))
        db.commit()

        flash("Foto sincronizada com sucesso!", "success")
        cursor.close()
        db.close()
        return redirect(back_url)

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Erro ao sincronizar foto: {e}")
        flash(f"Erro ao sincronizar foto: {e}", "danger")
        cursor.close()
        db.close()
        return redirect(back_url)


# ======================================================
# 🔹 EXCLUIR USUÁRIO
# ======================================================
@bp_usuarios.route("/<int:user_id>/toggle-ativo", methods=["POST"])
@login_required
def toggle_ativo(user_id):
    """Alterna o status ativo/inativo de um usuário. Retorna JSON.
    Permissão: admin/gestor_associacao/gestor_academia (com escopo)."""
    from flask import jsonify

    if user_id == current_user.id:
        return jsonify({"ok": False, "error": "Você não pode alterar o próprio status."}), 400

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nome, COALESCE(ativo, 1) AS ativo FROM usuarios WHERE id = %s", (user_id,))
        usuario = cursor.fetchone()
        if not usuario:
            return jsonify({"ok": False, "error": "Usuário não encontrado."}), 404

        if not _pode_editar_usuario(usuario):
            return jsonify({"ok": False, "error": "Sem permissão para alterar este usuário."}), 403

        novo = 0 if usuario["ativo"] else 1
        cursor.execute("UPDATE usuarios SET ativo = %s WHERE id = %s", (novo, user_id))
        db.commit()
        return jsonify({
            "ok": True,
            "ativo": bool(novo),
            "nome": usuario["nome"],
            "mensagem": ("Usuário reativado." if novo else "Usuário inativado."),
        })
    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Erro ao alterar status: {e}", exc_info=True)
        return jsonify({"ok": False, "error": "Erro interno."}), 500
    finally:
        cursor.close()
        db.close()


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


# ======================================================
# 🔹 UNIFICAÇÃO DE CADASTROS DUPLICADOS (admin)
# ======================================================
@bp_usuarios.route("/duplicados", methods=["GET"])
@login_required
def duplicados():
    """Lista grupos de usuários potencialmente duplicados (admin)."""
    if not require_admin():
        return redirect(url_for("painel.home"))
    from utils.unificar_usuarios import encontrar_duplicados

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        grupos = encontrar_duplicados(cur)
        # Anexar lista de roles e flags por usuário (para o admin decidir)
        for g in grupos:
            for u in g["usuarios"]:
                cur.execute(
                    """SELECT r.nome FROM roles_usuario ru
                       JOIN roles r ON r.id = ru.role_id
                       WHERE ru.usuario_id = %s ORDER BY r.nome""",
                    (u["id"],),
                )
                u["roles"] = [r["nome"] for r in cur.fetchall()]
                cur.execute("SELECT id FROM alunos WHERE usuario_id = %s", (u["id"],))
                u["tem_aluno"] = cur.fetchone() is not None
                cur.execute("SELECT id FROM professores WHERE usuario_id = %s", (u["id"],))
                u["tem_professor"] = cur.fetchone() is not None
                cur.execute("SELECT COUNT(*) AS c FROM usuarios_academias WHERE usuario_id = %s", (u["id"],))
                u["academias"] = (cur.fetchone() or {}).get("c", 0)
    finally:
        cur.close()
        db.close()

    return render_template("usuarios/duplicados.html", grupos=grupos)


@bp_usuarios.route("/duplicados/buscar", methods=["GET"])
@login_required
def duplicados_buscar():
    """Busca usuários por nome/e-mail/CPF para unificação manual (admin)."""
    from flask import jsonify
    if not current_user.has_role("admin"):
        return jsonify({"ok": False, "error": "Acesso negado"}), 403
    termo = (request.args.get("q") or "").strip()
    if len(termo) < 2:
        return jsonify({"itens": []})

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cpf_digits = "".join(filter(str.isdigit, termo))
        like = f"%{termo}%"
        params = [like, like]
        sql = """
            SELECT u.id, u.nome, u.email, u.cpf, u.foto, COALESCE(u.ativo,1) AS ativo, u.criado_em,
                   (SELECT COUNT(*) FROM alunos a WHERE a.usuario_id = u.id) AS tem_aluno,
                   (SELECT COUNT(*) FROM professores p WHERE p.usuario_id = u.id) AS tem_professor,
                   (SELECT COUNT(*) FROM usuarios_academias ua WHERE ua.usuario_id = u.id) AS academias
            FROM usuarios u
            WHERE u.nome LIKE %s OR u.email LIKE %s
        """
        if cpf_digits and len(cpf_digits) >= 4:
            sql += " OR REGEXP_REPLACE(COALESCE(u.cpf,''), '[^0-9]', '') LIKE %s"
            params.append(f"%{cpf_digits}%")
        sql += " ORDER BY u.nome LIMIT 30"
        cur.execute(sql, tuple(params))
        itens = cur.fetchall()
        # Anexar roles
        for u in itens:
            cur.execute(
                """SELECT r.nome FROM roles_usuario ru
                   JOIN roles r ON r.id = ru.role_id
                   WHERE ru.usuario_id = %s ORDER BY r.nome""",
                (u["id"],),
            )
            u["roles"] = [r["nome"] for r in cur.fetchall()]
            if u.get("criado_em"):
                u["criado_em"] = u["criado_em"].strftime("%d/%m/%Y") if hasattr(u["criado_em"], "strftime") else str(u["criado_em"])
        return jsonify({"itens": itens})
    finally:
        cur.close()
        db.close()


@bp_usuarios.route("/duplicados/unificar", methods=["POST"])
@login_required
def duplicados_unificar():
    """Unifica os perdedores no usuário principal escolhido."""
    if not require_admin():
        return redirect(url_for("usuarios.duplicados"))
    from utils.unificar_usuarios import unificar

    try:
        principal_id = int(request.form.get("principal_id") or 0)
    except (TypeError, ValueError):
        principal_id = 0
    perdedores_ids = []
    for x in request.form.getlist("perdedor_id"):
        try:
            v = int(x)
            if v != principal_id:
                perdedores_ids.append(v)
        except (TypeError, ValueError):
            pass

    if not principal_id or not perdedores_ids:
        flash("Selecione o usuário principal e pelo menos um perdedor.", "danger")
        return redirect(url_for("usuarios.duplicados"))

    if current_user.id in perdedores_ids:
        flash("Você não pode unificar a si mesmo como perdedor.", "danger")
        return redirect(url_for("usuarios.duplicados"))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        relatorio = unificar(cur, principal_id, perdedores_ids)
        db.commit()
        n = len(relatorio.get("perdedores_apagados", []))
        flash(f"Unificação concluída: {n} cadastro(s) mesclado(s) ao principal.", "success")
        for aviso in relatorio.get("avisos", []):
            flash(aviso, "warning")
    except Exception as e:
        db.rollback()
        current_app.logger.error("Erro ao unificar usuários: %s", e, exc_info=True)
        flash(f"Erro na unificação: {e}", "danger")
    finally:
        cur.close()
        db.close()

    return redirect(url_for("usuarios.duplicados"))
