# ======================================================
# Pré-cadastro — listagem, formulário público e promover
# ======================================================
import os
import re
import base64
import unicodedata
import uuid
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_required, current_user
from config import get_db_connection
from math import ceil

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
        elif getattr(current_user, "id_academia", None):
            ids = [current_user.id_academia]
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
        session["academia_gerenciamento_id"] = aid
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


@bp_precadastro.route("/<int:precadastro_id>/promover", methods=["POST"])
@login_required
def promover(precadastro_id):
    """Converte pré-cadastro em aluno. Requer permissão (gestor_academia, etc.)."""
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

    graduacao_id = pc.get("graduacao_id")
    if graduacao_id and str(graduacao_id).isdigit():
        graduacao_id = int(graduacao_id)
    elif graduacao_id and not str(graduacao_id).isdigit():
        graduacao_id = None

    turma_id = pc.get("TurmaID")
    if turma_id and str(turma_id).isdigit():
        turma_id = int(turma_id)
    else:
        turma_id = None

    telefone_principal = pc.get("telefone") or pc.get("tel_celular")

    # Verificar se aluno já está cadastrado
    cpf_precad = (pc.get("cpf") or "").strip()
    cpf_digits = "".join(filter(str.isdigit, cpf_precad)) if cpf_precad else ""
    nome_precad = (pc.get("nome") or "").strip()
    data_nasc_precad = pc.get("data_nascimento")

    if cpf_digits and len(cpf_digits) >= 11:
        cur.execute(
            """
            SELECT id, nome FROM alunos
            WHERE REPLACE(REPLACE(REPLACE(COALESCE(cpf,''), '.', ''), '-', ''), ' ', '') = %s
            """,
            (cpf_digits,),
        )
        existente = cur.fetchone()
        if existente:
            cur.close()
            conn.close()
            flash(
                f"Aluno já cadastrado: o CPF informado pertence a \"{existente.get('nome', '')}\" (ID {existente.get('id', '')}).",
                "danger",
            )
            return redirect(url_for("precadastro.lista", academia_id=academia_id))
    elif nome_precad:
        cur.execute(
            """
            SELECT id, nome FROM alunos
            WHERE TRIM(nome) = %s AND (data_nascimento = %s OR (%s IS NULL AND data_nascimento IS NULL))
            """,
            (nome_precad, data_nasc_precad, data_nasc_precad),
        )
        existente = cur.fetchone()
        if existente:
            cur.close()
            conn.close()
            flash(
                f"Aluno já cadastrado: existe cadastro com o mesmo nome e data de nascimento (\"{existente.get('nome', '')}\", ID {existente.get('id', '')}).",
                "danger",
            )
            return redirect(url_for("precadastro.lista", academia_id=academia_id))

    try:
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
                responsavel_financeiro_nome, responsavel_financeiro_cpf, foto
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                pc.get("nome"),
                pc.get("data_nascimento"),
                pc.get("sexo"),
                "ativo",
                1,
                date.today(),
                graduacao_id,
                pc.get("peso"),
                pc.get("zempo"),
                telefone_principal,
                pc.get("email"),
                pc.get("observacoes"),
                pc.get("ultimo_exame_faixa"),
                turma_id,
                pc.get("cpf"),
                academia_id,
                id_associacao,
                id_federacao,
                pc.get("nome_pai"),
                pc.get("nome_mae"),
                pc.get("responsavel_nome"),
                pc.get("responsavel_parentesco"),
                pc.get("nacionalidade"),
                pc.get("rg"),
                pc.get("orgao_emissor"),
                pc.get("rg_data_emissao"),
                pc.get("cep"),
                pc.get("endereco"),
                pc.get("numero"),
                pc.get("complemento"),
                pc.get("bairro"),
                pc.get("cidade"),
                pc.get("estado"),
                pc.get("tel_residencial"),
                pc.get("tel_comercial"),
                pc.get("tel_celular"),
                pc.get("tel_outro"),
                pc.get("responsavel_financeiro_nome"),
                pc.get("responsavel_financeiro_cpf"),
                f"{UPLOAD_PRECAD}/{pc['foto']}" if pc.get("foto") else None,
            ),
        )
        aluno_id = cur.lastrowid

        cur.execute("DELETE FROM pre_cadastro WHERE id = %s", (precadastro_id,))
        conn.commit()
        cur.close()
        conn.close()
        flash(f'Pré-cadastro de "{pc.get("nome")}" promovido a aluno com sucesso!', "success")
        return redirect(url_for("alunos.editar_aluno", aluno_id=aluno_id, next=url_for("precadastro.lista", academia_id=academia_id)))
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        flash(f"Erro ao promover: {e}", "danger")
        return redirect(url_for("precadastro.lista", academia_id=academia_id))
