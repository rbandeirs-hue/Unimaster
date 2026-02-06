# ======================================================
# Pré-cadastro — listagem, formulário público e promover
# ======================================================
import os
import re
import base64
import unicodedata
import uuid
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from flask_login import login_required, current_user
from config import get_db_connection
from math import ceil
from werkzeug.security import generate_password_hash

bp_precadastro = Blueprint("precadastro", __name__, url_prefix="/precadastro")


def _slugify(nome):
    """Converte nome em slug URL-amigável: 'Academia Judô Centro' -> 'academia-judo-centro'."""
    if not nome:
        return ""
    s = unicodedata.normalize("NFD", str(nome))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-") or "academia"

UPLOAD_PRECAD = "precadastro"


def _salvar_foto_precad_file(file_storage, prefix):
    """Salva foto de upload em static/uploads/precadastro/."""
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return None
    filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
    folder = os.path.join(current_app.root_path, "static", "uploads", UPLOAD_PRECAD)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    file_storage.save(filepath)
    return filename


def _salvar_foto_precad_base64(data_url, prefix):
    """Salva foto base64 (câmera) em static/uploads/precadastro/."""
    if not data_url:
        return None
    try:
        if "," in data_url:
            _, encoded = data_url.split(",", 1)
        else:
            encoded = data_url
        img_data = base64.b64decode(encoded)
    except Exception:
        return None
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
    folder = os.path.join(current_app.root_path, "static", "uploads", UPLOAD_PRECAD)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, "wb") as f:
        f.write(img_data)
    return filename


def _get_academias_ids():
    """IDs de academias acessíveis (prioridade: usuarios_academias)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas:
            cur.close()
            conn.close()
            return vinculadas
        # Modo academia: gestor_academia/professor só veem academias de usuarios_academias (não id_academia)
        if session.get("modo_painel") == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
            cur.close()
            conn.close()
            return []
        ids = []
        if current_user.has_role("admin"):
            cur.execute("SELECT id FROM academias ORDER BY nome")
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT ac.id FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s ORDER BY ac.nome",
                (getattr(current_user, "id_federacao", None),),
            )
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome", (getattr(current_user, "id_associacao", None),))
            ids = [r["id"] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return ids
    except Exception:
        return []


def _get_academia_filtro():
    """Retorna (academia_id, academias)."""
    ids = _get_academias_ids()
    if not ids:
        return None, []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids)), tuple(ids))
    academias = cur.fetchall()
    cur.close()
    conn.close()
    if len(ids) == 1:
        return ids[0], academias
    raw = request.args.get("academia_id", type=str)
    if raw is not None:
        aid = int(raw) if raw and raw != "0" else None
        if aid is not None:
            session["academia_gerenciamento_id"] = aid
            session["finance_academia_id"] = aid
    else:
        aid = session.get("academia_gerenciamento_id")
    if aid and aid in ids:
        return aid, academias
    return ids[0], academias


@bp_precadastro.route("/")
@login_required
def lista():
    """Lista pré-cadastros da academia selecionada."""
    academia_id, academias = _get_academia_filtro()
    if not academia_id:
        flash("Selecione uma academia.", "warning")
        return redirect(url_for("academia.painel_academia"))

    busca = request.args.get("busca", "").strip()
    page = int(request.args.get("page", 1))
    por_pagina = 15
    offset = (page - 1) * por_pagina

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    where = "academia_id = %s"
    params = [academia_id]
    if busca:
        where += " AND (nome LIKE %s OR email LIKE %s OR telefone LIKE %s OR cpf LIKE %s)"
        params.extend([f"%{busca}%", f"%{busca}%", f"%{busca}%", f"%{busca}%"])

    cur.execute(f"SELECT COUNT(*) AS total FROM pre_cadastro WHERE {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(f"""
        SELECT id, nome, email, telefone, data_nascimento, sexo, foto, created_at
        FROM pre_cadastro
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, params + [por_pagina, offset])
    precadastros = cur.fetchall()

    cur.execute("SELECT id, nome, slug FROM academias WHERE id = %s", (academia_id,))
    row = cur.fetchone()
    academia_nome = row.get("nome", "") if row else ""
    academia_slug = row.get("slug") if row else ""
    if not academia_slug and academia_nome:
        academia_slug = _slugify(academia_nome)
        base_slug = academia_slug
        n = 1
        while True:
            cur.execute("SELECT id FROM academias WHERE slug = %s AND id != %s", (academia_slug, academia_id))
            if cur.fetchone() is None:
                break
            academia_slug = f"{base_slug}-{n}"
            n += 1
        cur.execute("UPDATE academias SET slug = %s WHERE id = %s", (academia_slug, academia_id))
        conn.commit()
    cur.close()
    conn.close()

    total_paginas = ceil(total / por_pagina) if total > 0 else 1

    link_publico = url_for("precadastro.form_publico", academia_slug=academia_slug or academia_id, _external=True)

    return render_template(
        "precadastro/lista.html",
        precadastros=precadastros,
        busca=busca,
        pagina_atual=page,
        total_paginas=total_paginas,
        academias=academias,
        academia_id=academia_id,
        academia_nome=academia_nome,
        link_publico=link_publico,
    )


@bp_precadastro.route("/form/<academia_slug>", methods=["GET", "POST"])
def form_publico(academia_slug):
    """Formulário público de pré-cadastro — sem login. URL usa nome da academia."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome, slug FROM academias WHERE slug = %s", (academia_slug,))
    ac = cur.fetchone()
    if not ac and academia_slug.isdigit():
        cur.execute("SELECT id, nome, slug FROM academias WHERE id = %s", (int(academia_slug),))
        ac = cur.fetchone()
    cur.close()
    conn.close()
    if not ac:
        return "<h1>Academia não encontrada</h1>", 404

    academia_id = ac["id"]
    academia_nome = ac.get("nome", "")
    academia_slug = ac.get("slug") or ""
    if not academia_slug:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        base_slug = _slugify(academia_nome) or "academia"
        academia_slug = base_slug
        n = 1
        while True:
            cur.execute("SELECT id FROM academias WHERE slug = %s AND id != %s", (academia_slug, academia_id))
            if cur.fetchone() is None:
                break
            academia_slug = f"{base_slug}-{n}"
            n += 1
        cur.execute("UPDATE academias SET slug = %s WHERE id = %s", (academia_slug, academia_id))
        conn.commit()
        cur.close()
        conn.close()

    if request.method == "POST":
        form = request.form
        nome = (form.get("nome") or "").strip()
        if not nome:
            flash("Nome é obrigatório.", "danger")
            return render_template(
                "precadastro/form_publico.html",
                academia_id=academia_id,
                academia_nome=academia_nome,
                academia_slug=academia_slug,
                form=form,
                sucesso=False,
            )
        email = (form.get("email") or "").strip() or None
        telefone = (form.get("telefone") or "").strip() or None
        data_nascimento = form.get("data_nascimento") or None
        sexo = (form.get("sexo") or "").strip() or None
        cpf = (form.get("cpf") or "").strip() or None
        observacoes = (form.get("observacoes") or "").strip() or None
        acesso_sistema = (form.get("acesso_sistema") or "aluno").strip()
        responsavel_eh_proprio = 1 if form.get("responsavel_eh_proprio") == "1" else 0
        email_acesso = (form.get("email_acesso") or "").strip() or None

        # Verificar se o email já existe (em pre_cadastro ou usuarios)
        if email:
            conn_check = get_db_connection()
            cur_check = conn_check.cursor(dictionary=True)
            cur_check.execute("SELECT id FROM pre_cadastro WHERE LOWER(email) = %s", (email.lower(),))
            if cur_check.fetchone():
                cur_check.close()
                conn_check.close()
                flash("Este e-mail já está cadastrado. Por favor, utilize outro e-mail.", "danger")
                return render_template(
                    "precadastro/form_publico.html",
                    academia_id=academia_id,
                    academia_nome=academia_nome,
                    academia_slug=academia_slug,
                    form=form,
                    sucesso=False,
                )
            cur_check.execute("SELECT id FROM usuarios WHERE LOWER(email) = %s", (email.lower(),))
            if cur_check.fetchone():
                cur_check.close()
                conn_check.close()
                flash("Este e-mail já está cadastrado. Por favor, utilize outro e-mail.", "danger")
                return render_template(
                    "precadastro/form_publico.html",
                    academia_id=academia_id,
                    academia_nome=academia_nome,
                    academia_slug=academia_slug,
                    form=form,
                    sucesso=False,
                )
            cur_check.close()
            conn_check.close()

        # Verificar se o email_acesso já existe (quando é responsável)
        if email_acesso:
            conn_check = get_db_connection()
            cur_check = conn_check.cursor(dictionary=True)
            cur_check.execute("SELECT id FROM pre_cadastro WHERE LOWER(email_acesso) = %s", (email_acesso.lower(),))
            if cur_check.fetchone():
                cur_check.close()
                conn_check.close()
                flash("Este e-mail de acesso já está cadastrado. Por favor, utilize outro e-mail.", "danger")
                return render_template(
                    "precadastro/form_publico.html",
                    academia_id=academia_id,
                    academia_nome=academia_nome,
                    academia_slug=academia_slug,
                    form=form,
                    sucesso=False,
                )
            cur_check.execute("SELECT id FROM usuarios WHERE LOWER(email) = %s", (email_acesso.lower(),))
            if cur_check.fetchone():
                cur_check.close()
                conn_check.close()
                flash("Este e-mail de acesso já está cadastrado. Por favor, utilize outro e-mail.", "danger")
                return render_template(
                    "precadastro/form_publico.html",
                    academia_id=academia_id,
                    academia_nome=academia_nome,
                    academia_slug=academia_slug,
                    form=form,
                    sucesso=False,
                )
            cur_check.close()
            conn_check.close()

        resp_nome = (form.get("responsavel_financeiro_nome") or "").strip() or None
        resp_cpf = (form.get("responsavel_financeiro_cpf") or "").strip() or None
        if responsavel_eh_proprio:
            resp_nome = nome
            resp_cpf = cpf

        foto_filename = None
        foto_dataurl = form.get("foto")
        foto_file = request.files.get("foto_arquivo")
        if foto_dataurl and foto_dataurl.startswith("data:"):
            foto_filename = _salvar_foto_precad_base64(foto_dataurl, "precad")
        elif foto_file and foto_file.filename:
            foto_filename = _salvar_foto_precad_file(foto_file, "precad")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SHOW COLUMNS FROM pre_cadastro LIKE 'acesso_sistema'")
            tem_acesso = cur.fetchone() is not None
            cur.close()
        except Exception:
            tem_acesso = False

        cur = conn.cursor()
        try:
            if tem_acesso:
                cur.execute(
                    """
                    INSERT INTO pre_cadastro (
                        academia_id, nome, email, telefone, data_nascimento, sexo, cpf,
                        observacoes, foto, responsavel_financeiro_nome, responsavel_financeiro_cpf,
                        acesso_sistema, responsavel_eh_proprio, email_acesso
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        academia_id, nome, email, telefone, data_nascimento, sexo, cpf,
                        observacoes, foto_filename, resp_nome, resp_cpf,
                        acesso_sistema, responsavel_eh_proprio, email_acesso,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO pre_cadastro (
                        academia_id, nome, email, telefone, data_nascimento, sexo, cpf,
                        observacoes, foto, responsavel_financeiro_nome, responsavel_financeiro_cpf
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        academia_id, nome, email, telefone, data_nascimento, sexo, cpf,
                        observacoes, foto_filename, resp_nome, resp_cpf,
                    ),
                )
            conn.commit()
            cur.close()
            conn.close()
            return render_template(
                "precadastro/form_publico.html",
                academia_id=academia_id,
                academia_nome=academia_nome,
                academia_slug=academia_slug,
                form={},
                sucesso=True,
            )
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            flash(f"Erro ao salvar: {e}", "danger")

    return render_template(
        "precadastro/form_publico.html",
        academia_id=academia_id,
        academia_nome=academia_nome,
        academia_slug=academia_slug,
        form=request.form,
        sucesso=False,
    )


@bp_precadastro.route("/verificar-email", methods=["POST"])
def verificar_email():
    """Verifica se um email já existe (AJAX)."""
    from flask import jsonify
    data = request.get_json()
    email = (data.get("email") or "").strip().lower() if data else ""
    
    if not email:
        return jsonify({"existe": False})
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    # Verificar em pre_cadastro
    cur.execute("SELECT id FROM pre_cadastro WHERE LOWER(email) = %s", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"existe": True})
    
    # Verificar em usuarios
    cur.execute("SELECT id FROM usuarios WHERE LOWER(email) = %s", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"existe": True})
    
    cur.close()
    conn.close()
    return jsonify({"existe": False})


@bp_precadastro.route("/editar/<int:precadastro_id>", methods=["GET", "POST"])
@login_required
def editar(precadastro_id):
    """Edita um pré-cadastro existente."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM pre_cadastro WHERE id = %s", (precadastro_id,))
    pc = cur.fetchone()
    if not pc:
        cur.close()
        conn.close()
        flash("Pré-cadastro não encontrado.", "danger")
        return redirect(url_for("precadastro.lista"))

    academia_id = pc["academia_id"]
    ids = _get_academias_ids()
    if academia_id not in ids:
        cur.close()
        conn.close()
        flash("Sem permissão para editar este pré-cadastro.", "danger")
        return redirect(url_for("precadastro.lista"))

    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    ac = cur.fetchone()
    academia_nome = ac.get("nome", "") if ac else ""

    if request.method == "POST":
        form = request.form
        nome = (form.get("nome") or "").strip()
        if not nome:
            flash("Nome é obrigatório.", "danger")
            form_data = dict(form)
            form_data.update(pc)
            cur.close()
            conn.close()
            return render_template(
                "precadastro/editar.html",
                p=pc,
                academia_id=academia_id,
                academia_nome=academia_nome,
                form=form_data,
            )
        email = (form.get("email") or "").strip() or None
        telefone = (form.get("telefone") or "").strip() or None
        data_nascimento = form.get("data_nascimento") or None
        sexo = (form.get("sexo") or "").strip() or None
        cpf = (form.get("cpf") or "").strip() or None
        observacoes = (form.get("observacoes") or "").strip() or None
        acesso_sistema = (form.get("acesso_sistema") or "aluno").strip()
        responsavel_eh_proprio = 1 if form.get("responsavel_eh_proprio") == "1" else 0
        email_acesso = (form.get("email_acesso") or "").strip() or None
        resp_nome = (form.get("responsavel_financeiro_nome") or "").strip() or None
        resp_cpf = (form.get("responsavel_financeiro_cpf") or "").strip() or None
        if responsavel_eh_proprio:
            resp_nome = nome
            resp_cpf = cpf

        foto_filename = pc.get("foto")
        foto_dataurl = form.get("foto")
        foto_file = request.files.get("foto_arquivo")
        if foto_dataurl and foto_dataurl.startswith("data:"):
            foto_filename = _salvar_foto_precad_base64(foto_dataurl, "precad")
        elif foto_file and foto_file.filename:
            foto_filename = _salvar_foto_precad_file(foto_file, "precad")

        try:
            cur.execute("SHOW COLUMNS FROM pre_cadastro LIKE 'acesso_sistema'")
            tem_acesso = cur.fetchone() is not None
        except Exception:
            tem_acesso = False

        try:
            if tem_acesso:
                cur.execute(
                    """
                    UPDATE pre_cadastro SET
                        nome=%s, email=%s, telefone=%s, data_nascimento=%s, sexo=%s, cpf=%s,
                        observacoes=%s, foto=%s, responsavel_financeiro_nome=%s, responsavel_financeiro_cpf=%s,
                        acesso_sistema=%s, responsavel_eh_proprio=%s, email_acesso=%s
                    WHERE id=%s
                    """,
                    (
                        nome, email, telefone, data_nascimento, sexo, cpf,
                        observacoes, foto_filename, resp_nome, resp_cpf,
                        acesso_sistema, responsavel_eh_proprio, email_acesso,
                        precadastro_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE pre_cadastro SET
                        nome=%s, email=%s, telefone=%s, data_nascimento=%s, sexo=%s, cpf=%s,
                        observacoes=%s, foto=%s, responsavel_financeiro_nome=%s, responsavel_financeiro_cpf=%s
                    WHERE id=%s
                    """,
                    (
                        nome, email, telefone, data_nascimento, sexo, cpf,
                        observacoes, foto_filename, resp_nome, resp_cpf,
                        precadastro_id,
                    ),
                )
            conn.commit()
            cur.close()
            conn.close()
            flash("Pré-cadastro atualizado com sucesso.", "success")
            return redirect(url_for("precadastro.lista", academia_id=academia_id))
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            flash(f"Erro ao atualizar: {e}", "danger")

    cur.close()
    conn.close()
    form = {}
    for k, v in pc.items():
        if v is None:
            form[k] = ""
        elif hasattr(v, "strftime"):
            form[k] = v.strftime("%Y-%m-%d") if v else ""
        else:
            form[k] = str(v)
    form["responsavel_eh_proprio"] = "1" if pc.get("responsavel_eh_proprio") else ""
    form["acesso_sistema"] = pc.get("acesso_sistema") or "aluno"
    form["email_acesso"] = pc.get("email_acesso") or pc.get("email") or ""
    return render_template(
        "precadastro/editar.html",
        p=pc,
        academia_id=academia_id,
        academia_nome=academia_nome,
        form=form,
    )


@bp_precadastro.route("/<int:precadastro_id>/excluir", methods=["POST"])
@login_required
def excluir(precadastro_id):
    """Exclui um pré-cadastro."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, academia_id, nome FROM pre_cadastro WHERE id = %s", (precadastro_id,))
    pc = cur.fetchone()
    if not pc:
        cur.close()
        conn.close()
        flash("Pré-cadastro não encontrado.", "danger")
        return redirect(url_for("precadastro.lista"))

    academia_id = pc["academia_id"]
    ids = _get_academias_ids()
    if academia_id not in ids:
        cur.close()
        conn.close()
        flash("Sem permissão para excluir este pré-cadastro.", "danger")
        return redirect(url_for("precadastro.lista"))

    try:
        cur.execute("DELETE FROM pre_cadastro WHERE id = %s", (precadastro_id,))
        conn.commit()
        cur.close()
        conn.close()
        flash(f'Pré-cadastro de "{pc.get("nome", "")}" excluído com sucesso.', "success")
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        flash(f"Erro ao excluir: {e}", "danger")
    return redirect(url_for("precadastro.lista", academia_id=academia_id))


@bp_precadastro.route("/<int:precadastro_id>/promover", methods=["GET", "POST"])
@login_required
def promover(precadastro_id):
    """Promove pré-cadastro para usuário com múltiplos perfis. GET mostra formulário, POST processa."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM pre_cadastro WHERE id = %s", (precadastro_id,))
    pc = cur.fetchone()
    if not pc:
        cur.close()
        conn.close()
        flash("Pré-cadastro não encontrado.", "danger")
        return redirect(url_for("precadastro.lista"))

    academia_id = pc["academia_id"]
    ids = _get_academias_ids()
    if academia_id not in ids:
        cur.close()
        conn.close()
        flash("Sem permissão para promover pré-cadastros desta academia.", "danger")
        return redirect(url_for("precadastro.lista"))

    cur.execute(
        """
        SELECT ac.id_associacao, ass.id_federacao
        FROM academias ac
        LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
        WHERE ac.id = %s
        """,
        (academia_id,),
    )
    row = cur.fetchone()
    id_associacao = row.get("id_associacao") if row else None
    id_federacao = row.get("id_federacao") if row else None

    # Buscar roles disponíveis
    cur.execute("""
        SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) as chave 
        FROM roles 
        WHERE chave IN ('aluno', 'professor', 'gestor_academia', 'gestor_associacao', 'responsavel', 'visitante')
           OR nome IN ('Aluno', 'Professor', 'Gestor Academia', 'Gestor Associação', 'Responsável', 'Visitante')
        ORDER BY 
            CASE chave
                WHEN 'aluno' THEN 1
                WHEN 'professor' THEN 2
                WHEN 'gestor_academia' THEN 3
                WHEN 'gestor_associacao' THEN 4
                WHEN 'responsavel' THEN 5
                WHEN 'visitante' THEN 6
                ELSE 7
            END
    """)
    roles_disponiveis = cur.fetchall()

    # Buscar alunos para vínculo (aluno e responsavel)
    cur.execute(
        """SELECT id, nome, usuario_id FROM alunos WHERE id_academia = %s AND ativo = 1 AND status = 'ativo'
           ORDER BY nome""",
        (academia_id,),
    )
    todos_alunos = cur.fetchall()
    alunos_para_aluno = [a for a in todos_alunos if not a.get("usuario_id")]
    alunos_para_responsavel = todos_alunos

    if request.method == "GET":
        cur.close()
        conn.close()
        return render_template(
            "precadastro/promover.html",
            precadastro=pc,
            academia_id=academia_id,
            roles_disponiveis=roles_disponiveis,
            alunos_para_aluno=alunos_para_aluno,
            alunos_para_responsavel=alunos_para_responsavel,
        )

    # POST: Processar promoção
    roles_escolhidas = request.form.getlist("roles")
    email_usuario = (request.form.get("email_usuario") or "").strip()
    senha_usuario = (request.form.get("senha_usuario") or "").strip()
    tem_role_aluno = any(
        r.get("chave") == "aluno" and str(r.get("id")) in roles_escolhidas 
        for r in roles_disponiveis
    )
    aluno_ids_responsavel = [int(x) for x in request.form.getlist("aluno_ids") if str(x).strip().isdigit()]

    if not roles_escolhidas:
        cur.close()
        conn.close()
        flash("Selecione ao menos um perfil para promover.", "danger")
        return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))

    # Se precisa criar usuário, validar email e senha
    precisa_usuario = any(
        r.get("chave") in ["professor", "gestor_academia", "gestor_associacao", "responsavel", "visitante"]
        and str(r.get("id")) in roles_escolhidas
        for r in roles_disponiveis
    )
    
    # Verificar se usuário quer criar usuário mesmo quando seleciona apenas aluno
    criar_usuario_check = request.form.get("criar_usuario") == "1"
    tem_role_aluno_apenas = (
        any(r.get("chave") == "aluno" and str(r.get("id")) in roles_escolhidas for r in roles_disponiveis)
        and not precisa_usuario
    )
    
    # Se apenas aluno e checkbox marcado, também precisa criar usuário
    if tem_role_aluno_apenas and criar_usuario_check:
        precisa_usuario = True
    
    if precisa_usuario:
        if not email_usuario:
            email_usuario = pc.get("email") or pc.get("email_acesso")
        if not email_usuario:
            cur.close()
            conn.close()
            flash("E-mail é obrigatório para criar usuário. Informe um e-mail válido.", "danger")
            return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))
        if not senha_usuario:
            cur.close()
            conn.close()
            flash("Senha é obrigatória para criar usuário.", "danger")
            return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))

    try:
        usuario_id = None
        aluno_id = None

        # Criar usuário se necessário
        if precisa_usuario:
            # Verificar se email já existe
            cur.execute("SELECT id FROM usuarios WHERE email = %s", (email_usuario,))
            if cur.fetchone():
                cur.close()
                conn.close()
                flash("Já existe usuário com este e-mail.", "danger")
                return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))

            cur.execute(
                """INSERT INTO usuarios (nome, email, senha, id_academia, id_associacao, id_federacao) VALUES (%s, %s, %s, %s, %s, %s)""",
                (pc.get("nome"), email_usuario, generate_password_hash(senha_usuario), academia_id, id_associacao, id_federacao),
            )
            usuario_id = cur.lastrowid

            # Vincular roles
            for rid in roles_escolhidas:
                cur.execute("INSERT INTO roles_usuario (usuario_id, role_id) VALUES (%s, %s)", (usuario_id, rid))

            # Vincular academia
            cur.execute("INSERT INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)", (usuario_id, academia_id))

        # Criar/vincular aluno se role aluno está selecionada
        if tem_role_aluno:
            aluno_id = None
            
            # Verificar se aluno já está cadastrado (por CPF ou nome+data_nasc)
            cpf_precad = (pc.get("cpf") or "").strip()
            cpf_digits = "".join(filter(str.isdigit, cpf_precad)) if cpf_precad else ""
            nome_precad = (pc.get("nome") or "").strip()
            data_nasc_precad = pc.get("data_nascimento")

            aluno_existente = None
            if cpf_digits and len(cpf_digits) >= 11:
                cur.execute(
                    """
                    SELECT id, nome FROM alunos
                    WHERE REPLACE(REPLACE(REPLACE(COALESCE(cpf,''), '.', ''), '-', ''), ' ', '') = %s
                    """,
                    (cpf_digits,),
                )
                aluno_existente = cur.fetchone()
            elif nome_precad:
                cur.execute(
                    """
                    SELECT id, nome FROM alunos
                    WHERE TRIM(nome) = %s AND (data_nascimento = %s OR (%s IS NULL AND data_nascimento IS NULL))
                    """,
                    (nome_precad, data_nasc_precad, data_nasc_precad),
                )
                aluno_existente = cur.fetchone()

            if aluno_existente:
                # Aluno já existe - vincular usuário ao aluno existente
                aluno_id = aluno_existente["id"]
                if usuario_id:
                    cur.execute(
                        "UPDATE alunos SET usuario_id = %s WHERE id = %s AND (usuario_id IS NULL OR usuario_id = %s)",
                        (usuario_id, aluno_id, usuario_id),
                    )
            else:
                # Criar novo aluno automaticamente a partir do pré-cadastro
                # Função auxiliar para limpar valores e converter para None
                def _clean_value(val):
                    """Converte valores vazios, 'None', None para NULL."""
                    if val is None:
                        return None
                    if isinstance(val, str):
                        val = val.strip()
                        if val == "" or val.lower() in ("none", "null", "undefined", "nan"):
                            return None
                        # Verificar se é string "None" ou similar
                        if val.lower() == "none":
                            return None
                    elif isinstance(val, (int, float)):
                        # Manter números válidos (exceto NaN)
                        import math
                        if isinstance(val, float) and math.isnan(val):
                            return None
                        return val
                    return val if val else None
                
                graduacao_id = pc.get("graduacao_id")
                if graduacao_id and str(graduacao_id).isdigit():
                    graduacao_id = int(graduacao_id)
                else:
                    graduacao_id = None

                turma_id = pc.get("TurmaID")
                if turma_id and str(turma_id).isdigit():
                    turma_id = int(turma_id)
                else:
                    turma_id = None

                telefone_principal = _clean_value(pc.get("telefone") or pc.get("tel_celular"))
                
                # Limpar peso - converter para float ou None
                peso_val = _clean_value(pc.get("peso"))
                peso = None
                if peso_val:
                    try:
                        peso = float(str(peso_val).replace(",", "."))
                    except (ValueError, TypeError):
                        peso = None

                cur.execute(
                    """
                    INSERT INTO alunos (
                        nome, data_nascimento, sexo, status, ativo, data_matricula,
                        graduacao_id, peso, zempo, telefone, email, observacoes, ultimo_exame_faixa,
                        TurmaID, cpf, id_academia, id_associacao, id_federacao,
                        nome_pai, nome_mae, responsavel_nome, responsavel_parentesco,
                        nacionalidade, rg, orgao_emissor, rg_data_emissao,
                        cep, rua, numero, complemento, bairro, cidade, estado,
                        tel_residencial, tel_comercial, tel_celular, tel_outro,
                        responsavel_financeiro_nome, responsavel_financeiro_cpf, foto, usuario_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        _clean_value(pc.get("nome")),
                        _clean_value(pc.get("data_nascimento")),
                        _clean_value(pc.get("sexo")),
                        "ativo",
                        1,  # Campo ativo: usar 1 como padrão (coluna não permite NULL)
                        date.today(),
                        graduacao_id,
                        peso,
                        _clean_value(pc.get("zempo")),
                        telefone_principal,
                        _clean_value(pc.get("email")),
                        _clean_value(pc.get("observacoes")),
                        _clean_value(pc.get("ultimo_exame_faixa")),
                        turma_id,
                        _clean_value(pc.get("cpf")),
                        academia_id,
                        id_associacao,
                        id_federacao,
                        _clean_value(pc.get("nome_pai")),
                        _clean_value(pc.get("nome_mae")),
                        _clean_value(pc.get("responsavel_nome")),
                        _clean_value(pc.get("responsavel_parentesco")),
                        _clean_value(pc.get("nacionalidade")),
                        _clean_value(pc.get("rg")),
                        _clean_value(pc.get("orgao_emissor")),
                        _clean_value(pc.get("rg_data_emissao")),
                        _clean_value(pc.get("cep")),
                        _clean_value(pc.get("endereco")),
                        _clean_value(pc.get("numero")),
                        _clean_value(pc.get("complemento")),
                        _clean_value(pc.get("bairro")),
                        _clean_value(pc.get("cidade")),
                        _clean_value(pc.get("estado")),
                        _clean_value(pc.get("tel_residencial")),
                        _clean_value(pc.get("tel_comercial")),
                        _clean_value(pc.get("tel_celular")),
                        _clean_value(pc.get("tel_outro")),
                        _clean_value(pc.get("responsavel_financeiro_nome")),
                        _clean_value(pc.get("responsavel_financeiro_cpf")),
                        f"{UPLOAD_PRECAD}/{pc['foto']}" if pc.get("foto") else None,
                        usuario_id,
                    ),
                )
                aluno_id = cur.lastrowid

                # Vincular usuário ao aluno criado
                if usuario_id:
                    cur.execute(
                        "UPDATE alunos SET usuario_id = %s WHERE id = %s",
                        (usuario_id, aluno_id),
                    )

        # Vincular responsável aos alunos selecionados
        tem_role_responsavel = any(
            r.get("chave") == "responsavel" and str(r.get("id")) in roles_escolhidas 
            for r in roles_disponiveis
        )
        if tem_role_responsavel and usuario_id and aluno_ids_responsavel:
            for aid in aluno_ids_responsavel:
                cur.execute(
                    "SELECT 1 FROM alunos WHERE id = %s AND id_academia = %s",
                    (aid, academia_id),
                )
                if cur.fetchone():
                    cur.execute(
                        "INSERT IGNORE INTO responsavel_alunos (usuario_id, aluno_id) VALUES (%s, %s)",
                        (usuario_id, aid),
                    )

        # Criar registro de professor se role professor está selecionada
        tem_role_professor = any(
            r.get("chave") == "professor" and str(r.get("id")) in roles_escolhidas 
            for r in roles_disponiveis
        )
        if tem_role_professor and usuario_id:
            # Verificar se já existe professor com este usuario_id
            cur.execute("SELECT id FROM professores WHERE usuario_id = %s", (usuario_id,))
            if not cur.fetchone():
                telefone_professor = pc.get("telefone") or pc.get("tel_celular") or None
                email_professor = email_usuario or pc.get("email") or None
                cur.execute(
                    """
                    INSERT INTO professores (nome, email, telefone, usuario_id, id_academia, id_associacao, ativo)
                    VALUES (%s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        pc.get("nome"),
                        email_professor,
                        telefone_professor,
                        usuario_id,
                        academia_id,
                        id_associacao,
                    ),
                )

        # Criar registro de visitante se role visitante está selecionada
        tem_role_visitante = any(
            r.get("chave") == "visitante" and str(r.get("id")) in roles_escolhidas 
            for r in roles_disponiveis
        )
        if tem_role_visitante and usuario_id:
            # Verificar se já existe visitante com este usuario_id
            cur.execute("SELECT id FROM visitantes WHERE usuario_id = %s", (usuario_id,))
            if not cur.fetchone():
                # Buscar limite de aulas da academia
                cur.execute("SELECT aulas_experimentais_permitidas FROM academias WHERE id = %s", (academia_id,))
                acad_row = cur.fetchone()
                limite_aulas = acad_row.get("aulas_experimentais_permitidas") if acad_row else None
                
                telefone_visitante = pc.get("telefone") or pc.get("tel_celular") or None
                email_visitante = email_usuario or pc.get("email") or None
                foto_visitante = f"{UPLOAD_PRECAD}/{pc['foto']}" if pc.get("foto") else None
                
                cur.execute(
                    """
                    INSERT INTO visitantes (nome, email, telefone, data_nascimento, foto, usuario_id, id_academia, aulas_experimentais_permitidas, ativo)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        pc.get("nome"),
                        email_visitante,
                        telefone_visitante,
                        pc.get("data_nascimento"),
                        foto_visitante,
                        usuario_id,
                        academia_id,
                        limite_aulas,
                    ),
                )

        # Remover pré-cadastro
        cur.execute("DELETE FROM pre_cadastro WHERE id = %s", (precadastro_id,))
        conn.commit()
        cur.close()
        conn.close()

        perfis_criados = []
        for r in roles_disponiveis:
            if str(r.get("id")) in roles_escolhidas:
                perfis_criados.append(r.get("nome", ""))

        flash(
            f'Pré-cadastro de "{pc.get("nome")}" promovido com sucesso! Perfis criados: {", ".join(perfis_criados)}',
            "success",
        )
        if aluno_id:
            return redirect(url_for("alunos.editar_aluno", aluno_id=aluno_id, next=url_for("precadastro.lista", academia_id=academia_id)))
        return redirect(url_for("precadastro.lista", academia_id=academia_id))

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        current_app.logger.error(f"Erro ao promover pré-cadastro: {e}")
        flash(f"Erro ao promover: {e}", "danger")
        return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))
