# ======================================================
# Blueprint: Professores (CRUD por academia)
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from config import get_db_connection
from utils.modalidades import filtro_visibilidade_sql

bp_professores = Blueprint("professores", __name__, url_prefix="/professores")


def _academia_permitida(academia_id):
    """Verifica se o usuário pode acessar essa academia."""
    if current_user.has_role("admin"):
        return True
    if current_user.has_role("gestor_federacao"):
        db = get_db_connection()
        cur = db.cursor()
        cur.execute(
            """
            SELECT 1 FROM academias ac
            JOIN associacoes ass ON ass.id = ac.id_associacao
            WHERE ac.id = %s AND ass.id_federacao = %s
            """,
            (academia_id, getattr(current_user, "id_federacao", None)),
        )
        ok = cur.fetchone() is not None
        cur.close()
        db.close()
        return ok
    if current_user.has_role("gestor_associacao"):
        db = get_db_connection()
        cur = db.cursor()
        cur.execute(
            "SELECT 1 FROM academias WHERE id = %s AND id_associacao = %s",
            (academia_id, getattr(current_user, "id_associacao", None)),
        )
        ok = cur.fetchone() is not None
        cur.close()
        db.close()
        return ok
    if current_user.has_role("gestor_academia") or current_user.has_role("professor"):
        db = get_db_connection()
        cur = db.cursor()
        cur.execute("SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id = %s", (current_user.id, academia_id))
        ok = cur.fetchone() is not None
        cur.close()
        db.close()
        return ok
    return False


@bp_professores.route("/academia/<int:academia_id>")
@login_required
def lista(academia_id):
    if not _academia_permitida(academia_id):
        flash("Acesso negado a esta academia.", "danger")
        return redirect(url_for("painel.home"))

    origin = request.args.get("origin", "")

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
    academia = cur.fetchone()
    if not academia:
        flash("Academia não encontrada.", "danger")
        db.close()
        return redirect(url_for("painel.home"))

    cur.execute(
        """
        SELECT p.id, p.nome, p.email, p.telefone, p.ativo, p.id_academia, p.usuario_id,
               (SELECT a.foto FROM alunos a WHERE a.usuario_id = p.usuario_id LIMIT 1) AS foto_aluno
        FROM professores p
        WHERE p.id_academia = %s
        ORDER BY p.nome
        """,
        (academia_id,),
    )
    professores = cur.fetchall()
    for p in professores:
        p["foto_url"] = (
            url_for("static", filename="uploads/" + p["foto_aluno"])
            if p.get("foto_aluno") else None
        )
    # Modalidades por professor
    if professores:
        pids = [p["id"] for p in professores]
        cur.execute(
            """
            SELECT pm.professor_id, m.nome
            FROM professor_modalidade pm
            JOIN modalidade m ON m.id = pm.modalidade_id
            WHERE pm.professor_id IN (%s) AND pm.ativo = 1
            ORDER BY m.nome
            """
            % ",".join(["%s"] * len(pids)),
            tuple(pids),
        )
        mods_por_prof = {}
        for r in cur.fetchall():
            mods_por_prof.setdefault(r["professor_id"], []).append(r["nome"])
        for p in professores:
            p["modalidades_nomes"] = ", ".join(mods_por_prof.get(p["id"], [])) or "—"
    db.close()

    return render_template(
        "professores/lista_professores.html",
        professores=professores,
        academia=academia,
        academia_id=academia_id,
        origin=origin,
    )


@bp_professores.route("/academia/<int:academia_id>/cadastro", methods=["GET", "POST"])
@login_required
def cadastrar(academia_id):
    if not _academia_permitida(academia_id):
        flash("Acesso negado a esta academia.", "danger")
        return redirect(url_for("painel.home"))

    origin = request.args.get("origin", "")

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
    academia = cur.fetchone()
    if not academia:
        flash("Academia não encontrada.", "danger")
        db.close()
        return redirect(url_for("painel.home"))

    cur.execute("SELECT ac.id_associacao FROM academias ac WHERE ac.id = %s", (academia_id,))
    row = cur.fetchone()
    id_associacao = row.get("id_associacao") if row else None

    # Buscar usuários com role professor que ainda não têm registro na tabela professores
    # Filtrar apenas usuários vinculados à academia do usuário logado
    # Incluir telefone do aluno vinculado (se existir)
    cur.execute(
        """
        SELECT DISTINCT u.id, u.nome, u.email,
               COALESCE(
                   a.telefone, 
                   a.tel_celular, 
                   a.tel_residencial, 
                   a.tel_comercial
               ) as telefone
        FROM usuarios u
        INNER JOIN roles_usuario ru ON ru.usuario_id = u.id
        INNER JOIN roles r ON r.id = ru.role_id
        INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id AND ua.academia_id = %s
        LEFT JOIN alunos a ON a.usuario_id = u.id AND a.ativo = 1 AND a.id_academia = %s
        WHERE u.ativo = 1 
          AND (r.chave = 'professor' OR LOWER(r.nome) LIKE '%professor%')
          AND u.id NOT IN (SELECT usuario_id FROM professores WHERE usuario_id IS NOT NULL)
        ORDER BY u.nome
        """,
        (academia_id, academia_id),
    )
    usuarios = cur.fetchall()

    if request.method == "POST":
        usuario_id = request.form.get("usuario_id")
        usuario_id = int(usuario_id) if usuario_id and str(usuario_id).isdigit() else None
        # Telefone pode vir do formulário ou será buscado do aluno
        telefone = (request.form.get("telefone") or "").strip() or None
        if not usuario_id:
            flash("Selecione um usuário para vincular como professor.", "danger")
            db.close()
            return redirect(url_for("professores.cadastrar", academia_id=academia_id))
        # Buscar dados do usuário e do aluno vinculado (se houver)
        cur.execute("""
            SELECT u.nome, u.email,
                   COALESCE(a.telefone, a.tel_celular, a.tel_residencial, a.tel_comercial) as telefone_aluno
            FROM usuarios u
            LEFT JOIN alunos a ON a.usuario_id = u.id AND a.ativo = 1
            WHERE u.id = %s
        """, (usuario_id,))
        u = cur.fetchone()
        
        # Usar dados do formulário se preenchidos, senão buscar do usuário
        nome_form = (request.form.get("nome") or "").strip()
        email_form = (request.form.get("email") or "").strip() or None
        
        nome = nome_form if nome_form else ((u.get("nome") or "").strip() if u else "")
        email = email_form if email_form else ((u.get("email") or "").strip() or None if u else None)
        telefone_aluno = u.get("telefone_aluno") if u else None
        
        if not nome:
            flash("Usuário não encontrado.", "danger")
            db.close()
            return redirect(url_for("professores.cadastrar", academia_id=academia_id))
        
        # Usar telefone do formulário, ou do aluno, ou None (prioridade: formulário > aluno)
        if not telefone and telefone_aluno:
            telefone = telefone_aluno
        try:
            cur.execute(
                """
                INSERT INTO professores (nome, email, telefone, usuario_id, id_academia, id_associacao, ativo)
                VALUES (%s, %s, %s, %s, %s, %s, 1)
                """,
                (nome, email, telefone, usuario_id, academia_id, id_associacao),
            )
            professor_id = cur.lastrowid
            modalidade_ids = [int(x) for x in request.form.getlist("modalidade_ids") if str(x).strip().isdigit()]
            if modalidade_ids:
                cur.execute(
                    "SELECT modalidade_id FROM academia_modalidades WHERE academia_id = %s",
                    (academia_id,),
                )
                ids_validos = {r["modalidade_id"] for r in cur.fetchall()}
                for mid in modalidade_ids:
                    if mid in ids_validos:
                        cur.execute(
                            "INSERT INTO professor_modalidade (professor_id, modalidade_id) VALUES (%s, %s)",
                            (professor_id, mid),
                        )
            db.commit()
            flash("Professor cadastrado com sucesso.", "success")
            db.close()
            redir = url_for("professores.lista", academia_id=academia_id)
            if origin:
                redir += f"?origin={origin}"
            return redirect(redir)
        except Exception as e:
            db.rollback()
            flash(f"Erro ao cadastrar: {e}", "danger")

    extra_mod, extra_params_mod = filtro_visibilidade_sql(id_academia=academia_id, id_associacao=id_associacao)
    cur.execute(
        """
        SELECT m.id, m.nome FROM modalidade m
        INNER JOIN academia_modalidades am ON am.modalidade_id = m.id
        WHERE am.academia_id = %s AND m.ativo = 1
        """ + extra_mod + """
        ORDER BY m.nome
        """,
        (academia_id,) + extra_params_mod,
    )
    modalidades = cur.fetchall()

    db.close()
    back_url = url_for("academia.painel_academia", academia_id=academia_id)
    return render_template(
        "professores/cadastro_professor.html",
        academia=academia,
        academia_id=academia_id,
        back_url=back_url,
        usuarios=usuarios,
        modalidades=modalidades,
    )


@bp_professores.route("/editar/<int:professor_id>", methods=["GET", "POST"])
@login_required
def editar(professor_id):
    origin = request.args.get("origin", "")

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, email, telefone, ativo, id_academia, id_associacao, usuario_id FROM professores WHERE id = %s",
        (professor_id,),
    )
    professor = cur.fetchone()
    if not professor:
        flash("Professor não encontrado.", "danger")
        db.close()
        return redirect(url_for("painel.home"))

    academia_id = professor.get("id_academia")
    if not academia_id or not _academia_permitida(academia_id):
        flash("Acesso negado.", "danger")
        db.close()
        return redirect(url_for("painel.home"))

    cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
    academia = cur.fetchone()

    # Buscar usuários com role professor que ainda não têm registro na tabela professores (ou o próprio professor sendo editado)
    # Filtrar apenas usuários vinculados à academia
    cur.execute(
        """
        SELECT DISTINCT u.id, u.nome, u.email 
        FROM usuarios u
        INNER JOIN roles_usuario ru ON ru.usuario_id = u.id
        INNER JOIN roles r ON r.id = ru.role_id
        INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id AND ua.academia_id = %s
        WHERE u.ativo = 1 
          AND (r.chave = 'professor' OR LOWER(r.nome) LIKE '%professor%' OR u.id = %s)
          AND (u.id NOT IN (SELECT usuario_id FROM professores WHERE usuario_id IS NOT NULL AND professores.id != %s) OR u.id = %s)
        ORDER BY u.nome
        """,
        (academia_id, professor.get("usuario_id") or 0, professor_id, professor.get("usuario_id") or 0),
    )
    usuarios = cur.fetchall()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip() or None
        telefone = (request.form.get("telefone") or "").strip() or None
        ativo = 1 if request.form.get("ativo") == "1" else 0
        usuario_id = request.form.get("usuario_id")
        usuario_id = int(usuario_id) if usuario_id and str(usuario_id).isdigit() else None
        if not nome:
            flash("Nome do professor é obrigatório.", "danger")
            db.close()
            return redirect(url_for("professores.editar", professor_id=professor_id))
        try:
            cur.execute(
                """
                UPDATE professores SET nome=%s, email=%s, telefone=%s, ativo=%s, usuario_id=%s
                WHERE id=%s
                """,
                (nome, email, telefone, ativo, usuario_id, professor_id),
            )
            cur.execute("DELETE FROM professor_modalidade WHERE professor_id = %s", (professor_id,))
            modalidade_ids = [int(x) for x in request.form.getlist("modalidade_ids") if str(x).strip().isdigit()]
            if modalidade_ids:
                cur.execute(
                    "SELECT modalidade_id FROM academia_modalidades WHERE academia_id = %s",
                    (academia_id,),
                )
                ids_validos = {r["modalidade_id"] for r in cur.fetchall()}
                for mid in modalidade_ids:
                    if mid in ids_validos:
                        cur.execute(
                            "INSERT INTO professor_modalidade (professor_id, modalidade_id) VALUES (%s, %s)",
                            (professor_id, mid),
                        )
            db.commit()
            flash("Professor atualizado com sucesso.", "success")
            db.close()
            redir = url_for("professores.lista", academia_id=academia_id)
            if origin:
                redir += f"?origin={origin}"
            return redirect(redir)
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar: {e}", "danger")

    cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (academia_id,))
    r_acad = cur.fetchone()
    id_assoc_edit = r_acad.get("id_associacao") if r_acad else None
    extra_edit, extra_params_edit = filtro_visibilidade_sql(id_academia=academia_id, id_associacao=id_assoc_edit)
    cur.execute(
        """
        SELECT m.id, m.nome FROM modalidade m
        INNER JOIN academia_modalidades am ON am.modalidade_id = m.id
        WHERE am.academia_id = %s AND m.ativo = 1
        """ + extra_edit + """
        ORDER BY m.nome
        """,
        (academia_id,) + extra_params_edit,
    )
    modalidades = cur.fetchall()
    cur.execute("SELECT modalidade_id FROM professor_modalidade WHERE professor_id = %s", (professor_id,))
    professor_modalidades_ids = {r["modalidade_id"] for r in cur.fetchall()}

    db.close()
    back_url = url_for("academia.painel_academia", academia_id=academia_id)
    return render_template(
        "professores/editar_professor.html",
        professor=professor,
        academia=academia,
        academia_id=academia_id,
        back_url=back_url,
        usuarios=usuarios,
        modalidades=modalidades,
        professor_modalidades_ids=professor_modalidades_ids,
    )


@bp_professores.route("/excluir/<int:professor_id>", methods=["POST"])
@login_required
def excluir(professor_id):
    origin = request.form.get("origin", "")

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome, id_academia FROM professores WHERE id = %s", (professor_id,))
    professor = cur.fetchone()
    if not professor:
        flash("Professor não encontrado.", "danger")
        db.close()
        return redirect(url_for("painel.home"))

    academia_id = professor.get("id_academia")
    if not academia_id or not _academia_permitida(academia_id):
        flash("Acesso negado.", "danger")
        db.close()
        return redirect(url_for("painel.home"))

    try:
        cur.execute("DELETE FROM turma_professor WHERE professor_id = %s", (professor_id,))
        cur.execute("DELETE FROM professores WHERE id = %s", (professor_id,))
        db.commit()
        flash("Professor excluído com sucesso.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao excluir: {e}", "danger")
    db.close()
    redir = url_for("professores.lista", academia_id=academia_id)
    if origin:
        redir += f"?origin={origin}"
    return redirect(redir)
