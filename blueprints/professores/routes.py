# ======================================================
# Blueprint: Professores (CRUD por academia)
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from config import get_db_connection

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
        return getattr(current_user, "id_academia", None) == academia_id
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
        SELECT p.id, p.nome, p.email, p.telefone, p.ativo, p.id_academia, p.id_associacao
        FROM professores p
        WHERE p.id_academia = %s
        ORDER BY p.nome
        """,
        (academia_id,),
    )
    professores = cur.fetchall()
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

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip() or None
        telefone = (request.form.get("telefone") or "").strip() or None
        if not nome:
            flash("Nome do professor é obrigatório.", "danger")
            db.close()
            return redirect(url_for("professores.cadastrar", academia_id=academia_id))
        try:
            cur.execute(
                """
                INSERT INTO professores (nome, email, telefone, id_academia, id_associacao, ativo)
                VALUES (%s, %s, %s, %s, %s, 1)
                """,
                (nome, email, telefone, academia_id, id_associacao),
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

    db.close()
    back_url = url_for("professores.lista", academia_id=academia_id)
    if origin:
        back_url += f"?origin={origin}"
    return render_template(
        "professores/cadastro_professor.html",
        academia=academia,
        academia_id=academia_id,
        back_url=back_url,
    )


@bp_professores.route("/editar/<int:professor_id>", methods=["GET", "POST"])
@login_required
def editar(professor_id):
    origin = request.args.get("origin", "")

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, email, telefone, ativo, id_academia, id_associacao FROM professores WHERE id = %s",
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

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip() or None
        telefone = (request.form.get("telefone") or "").strip() or None
        ativo = 1 if request.form.get("ativo") == "1" else 0
        if not nome:
            flash("Nome do professor é obrigatório.", "danger")
            db.close()
            return redirect(url_for("professores.editar", professor_id=professor_id))
        try:
            cur.execute(
                """
                UPDATE professores SET nome=%s, email=%s, telefone=%s, ativo=%s
                WHERE id=%s
                """,
                (nome, email, telefone, ativo, professor_id),
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

    db.close()
    back_url = url_for("professores.lista", academia_id=academia_id)
    if origin:
        back_url += f"?origin={origin}"
    return render_template(
        "professores/editar_professor.html",
        professor=professor,
        academia=academia,
        academia_id=academia_id,
        back_url=back_url,
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
