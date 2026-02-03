# ======================================================
# Configurações (somente admin): Modalidades globais,
# vincular a uma ou mais academias.
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
from config import get_db_connection

bp_configuracoes = Blueprint("configuracoes", __name__, url_prefix="/configuracoes")


def admin_required(f):
    @wraps(f)
    def _view(*a, **kw):
        if not current_user.is_authenticated or not current_user.has_role("admin"):
            flash("Acesso restrito a administradores.", "danger")
            return redirect(url_for("painel.home"))
        return f(*a, **kw)
    return _view


@bp_configuracoes.route("")
@login_required
@admin_required
def hub():
    return render_template("configuracoes/hub.html")


@bp_configuracoes.route("/modalidades")
@login_required
@admin_required
def modalidades_lista():
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT m.id, m.nome, m.descricao, m.ativo,
                       COALESCE(m.visibilidade, 'publica') as visibilidade
                FROM modalidade m
                ORDER BY m.nome
                """
            )
            modalidades = cur.fetchall()
        except Exception:
            cur.execute("SELECT id, nome, descricao, ativo FROM modalidade ORDER BY nome")
            modalidades = cur.fetchall()
            for m in modalidades:
                m["visibilidade"] = "publica"
    except Exception:
        db.close()
        flash("Tabela modalidade não encontrada. Execute a migration add_modalidade_academia_modalidades.sql", "danger")
        return redirect(url_for("configuracoes.hub"))
    mod_academias = {}
    try:
        cur.execute(
            """
            SELECT am.modalidade_id, ac.id AS academia_id, ac.nome AS academia_nome
            FROM academia_modalidades am
            JOIN academias ac ON ac.id = am.academia_id
            ORDER BY ac.nome
            """
        )
        for r in cur.fetchall():
            mid = r["modalidade_id"]
            mod_academias.setdefault(mid, []).append({"id": r["academia_id"], "nome": r["academia_nome"]})
    except Exception:
        pass
    for m in modalidades:
        m["academias"] = mod_academias.get(m["id"], [])
    db.close()
    return render_template(
        "configuracoes/modalidades_lista.html",
        modalidades=modalidades,
    )


@bp_configuracoes.route("/modalidades/cadastro", methods=["GET", "POST"])
@login_required
@admin_required
def modalidades_cadastro():
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias ORDER BY nome")
    academias = cur.fetchall()
    cur.execute("SELECT id, nome FROM associacoes ORDER BY nome")
    associacoes = cur.fetchall()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        ativo = 1 if request.form.get("ativo") == "1" else 0
        visibilidade = request.form.get("visibilidade") or "publica"
        id_associacao = request.form.get("id_associacao", type=int) or None
        id_academia = request.form.get("id_academia", type=int) or None
        if visibilidade == "privada" and id_associacao and id_academia:
            id_academia = None  # Só um dono
        elif visibilidade == "publica":
            id_associacao = id_academia = None
        academia_ids = [int(x) for x in request.form.getlist("academia_ids") if str(x).strip()]
        if not nome:
            flash("Nome da modalidade é obrigatório.", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_cadastro"))
        try:
            cur.execute("SELECT id FROM modalidade WHERE nome = %s", (nome,))
            row = cur.fetchone()
            if row:
                modalidade_id = row["id"]
                for aid in academia_ids:
                    cur.execute(
                        "SELECT 1 FROM academia_modalidades WHERE academia_id = %s AND modalidade_id = %s",
                        (aid, modalidade_id),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT IGNORE INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                            (aid, modalidade_id),
                        )
                db.commit()
                flash("Modalidade existente vinculada às academias selecionadas.", "success")
            else:
                try:
                    cur.execute(
                        "INSERT INTO modalidade (nome, descricao, ativo, visibilidade, id_associacao, id_academia) VALUES (%s, %s, %s, %s, %s, %s)",
                        (nome, descricao, ativo, visibilidade, id_associacao, id_academia),
                    )
                except Exception:
                    cur.execute(
                        "INSERT INTO modalidade (nome, ativo, visibilidade, id_associacao, id_academia) VALUES (%s, %s, %s, %s, %s)",
                        (nome, ativo, visibilidade, id_associacao, id_academia),
                    )
                modalidade_id = cur.lastrowid
                for aid in academia_ids:
                    cur.execute(
                        "INSERT IGNORE INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                        (aid, modalidade_id),
                    )
                db.commit()
                flash("Modalidade cadastrada e vinculada às academias com sucesso.", "success")
            db.close()
            return redirect(url_for("configuracoes.modalidades_lista"))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao salvar: {e}", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_cadastro"))

    db.close()
    return render_template(
        "configuracoes/modalidades_cadastro.html",
        academias=academias,
        associacoes=associacoes,
    )


@bp_configuracoes.route("/modalidades/<int:modalidade_id>/editar", methods=["GET", "POST"])
@login_required
@admin_required
def modalidades_editar(modalidade_id):
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome, descricao, ativo, visibilidade, id_associacao, id_academia FROM modalidade WHERE id = %s", (modalidade_id,))
    except Exception:
        cur.execute("SELECT id, nome, descricao, ativo FROM modalidade WHERE id = %s", (modalidade_id,))
    modalidade = cur.fetchone()
    if not modalidade:
        db.close()
        flash("Modalidade não encontrada.", "danger")
        return redirect(url_for("configuracoes.modalidades_lista"))
    for k in ("visibilidade", "id_associacao", "id_academia"):
        if k not in modalidade:
            modalidade[k] = None
    if not modalidade.get("visibilidade"):
        modalidade["visibilidade"] = "publica"

    cur.execute("SELECT id, nome FROM academias ORDER BY nome")
    academias = cur.fetchall()
    cur.execute("SELECT id, nome FROM associacoes ORDER BY nome")
    associacoes = cur.fetchall()
    try:
        cur.execute("SELECT academia_id FROM academia_modalidades WHERE modalidade_id = %s", (modalidade_id,))
        vinculadas = {r["academia_id"] for r in cur.fetchall()}
    except Exception:
        vinculadas = set()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        ativo = 1 if request.form.get("ativo") == "1" else 0
        visibilidade = request.form.get("visibilidade") or "publica"
        id_associacao = request.form.get("id_associacao", type=int) or None
        id_academia = request.form.get("id_academia", type=int) or None
        if visibilidade == "privada" and id_associacao and id_academia:
            id_academia = None
        elif visibilidade == "publica":
            id_associacao = id_academia = None
        academia_ids = [int(x) for x in request.form.getlist("academia_ids") if str(x).strip()]
        if not nome:
            flash("Nome da modalidade é obrigatório.", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_editar", modalidade_id=modalidade_id))
        try:
            try:
                cur.execute("UPDATE modalidade SET nome = %s, descricao = %s, ativo = %s, visibilidade = %s, id_associacao = %s, id_academia = %s WHERE id = %s",
                            (nome, descricao, ativo, visibilidade, id_associacao, id_academia, modalidade_id))
            except Exception:
                cur.execute("UPDATE modalidade SET nome = %s, descricao = %s, ativo = %s WHERE id = %s", (nome, descricao, ativo, modalidade_id))
            cur.execute("DELETE FROM academia_modalidades WHERE modalidade_id = %s", (modalidade_id,))
            for aid in academia_ids:
                cur.execute(
                    "INSERT IGNORE INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                    (aid, modalidade_id),
                )
            db.commit()
            flash("Modalidade atualizada com sucesso.", "success")
            db.close()
            return redirect(url_for("configuracoes.modalidades_lista"))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao salvar: {e}", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_editar", modalidade_id=modalidade_id))

    db.close()
    return render_template(
        "configuracoes/modalidades_editar.html",
        modalidade=modalidade,
        academias=academias,
        associacoes=associacoes,
        vinculadas=vinculadas,
    )


@bp_configuracoes.route("/modalidades/<int:modalidade_id>/vincular", methods=["GET", "POST"])
@login_required
@admin_required
def modalidades_vincular(modalidade_id):
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome, descricao, ativo FROM modalidade WHERE id = %s", (modalidade_id,))
    modalidade = cur.fetchone()
    if not modalidade:
        db.close()
        flash("Modalidade não encontrada.", "danger")
        return redirect(url_for("configuracoes.modalidades_lista"))

    cur.execute("SELECT id, nome FROM academias ORDER BY nome")
    academias = cur.fetchall()
    try:
        cur.execute("SELECT academia_id FROM academia_modalidades WHERE modalidade_id = %s", (modalidade_id,))
        vinculadas = {r["academia_id"] for r in cur.fetchall()}
    except Exception:
        vinculadas = set()

    if request.method == "POST":
        novo_ids = [int(x) for x in request.form.getlist("academia_ids") if str(x).strip()]
        try:
            cur.execute("DELETE FROM academia_modalidades WHERE modalidade_id = %s", (modalidade_id,))
            for aid in novo_ids:
                cur.execute(
                    "INSERT INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                    (aid, modalidade_id),
                )
            db.commit()
            flash("Vínculos atualizados.", "success")
            db.close()
            return redirect(url_for("configuracoes.modalidades_lista"))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar vínculos: {e}", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_vincular", modalidade_id=modalidade_id))

    db.close()
    return render_template(
        "configuracoes/modalidades_vincular.html",
        modalidade=modalidade,
        academias=academias,
        vinculadas=vinculadas,
    )


@bp_configuracoes.route("/modalidades/<int:modalidade_id>/toggle", methods=["POST"])
@login_required
@admin_required
def modalidades_toggle(modalidade_id):
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome, ativo FROM modalidade WHERE id = %s", (modalidade_id,))
    m = cur.fetchone()
    if not m:
        db.close()
        flash("Modalidade não encontrada.", "danger")
        return redirect(url_for("configuracoes.modalidades_lista"))
    novo = 0 if m["ativo"] else 1
    cur.execute("UPDATE modalidade SET ativo = %s WHERE id = %s", (novo, modalidade_id))
    db.commit()
    db.close()
    flash(f"Modalidade «{m['nome']}» {'ativada' if novo else 'inativada'}.", "success")
    return redirect(url_for("configuracoes.modalidades_lista"))
