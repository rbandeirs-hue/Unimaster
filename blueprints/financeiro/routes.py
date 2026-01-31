# ======================================================
# Blueprint: Financeiro (mensalidades, receitas, despesas, descontos)
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from datetime import date
from config import get_db_connection

bp_financeiro = Blueprint("financeiro", __name__, url_prefix="/financeiro")


def _get_academias_ids():
    """Retorna IDs de academias acessíveis pelo usuário."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ids = []
    if current_user.has_role("admin"):
        cur.execute("SELECT id FROM academias")
        ids = [r["id"] for r in cur.fetchall()]
    elif current_user.has_role("gestor_federacao"):
        cur.execute(
            "SELECT ac.id FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s",
            (getattr(current_user, "id_federacao", None),),
        )
        ids = [r["id"] for r in cur.fetchall()]
    elif current_user.has_role("gestor_associacao"):
        cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (getattr(current_user, "id_associacao", None),))
        ids = [r["id"] for r in cur.fetchall()]
    elif getattr(current_user, "id_academia", None):
        ids = [current_user.id_academia]
    conn.close()
    return ids


def _get_academia_id():
    """Academia ativa para o financeiro (session ou primeira disponível)."""
    ids = _get_academias_ids()
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]
    aid = request.args.get("academia_id", type=int) or session.get("finance_academia_id")
    if aid and aid in ids:
        session["finance_academia_id"] = aid
        return aid
    session["finance_academia_id"] = ids[0]
    return ids[0]


@bp_financeiro.route("/")
@bp_financeiro.route("/dashboard")
@login_required
def dashboard():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    ac = cur.fetchone()
    academia_nome = ac["nome"] if ac else None

    mes, ano = date.today().month, date.today().year
    cur.execute(
        "SELECT COALESCE(SUM(valor), 0) as total FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
        (academia_id, mes, ano),
    )
    receitas_mes = float(cur.fetchone().get("total") or 0)
    cur.execute(
        "SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
        (academia_id, mes, ano),
    )
    despesas_mes = float(cur.fetchone().get("total") or 0)
    conn.close()

    return render_template(
        "financeiro/dashboard.html",
        academia_nome=academia_nome,
        receitas_mes=receitas_mes,
        despesas_mes=despesas_mes,
    )


@bp_financeiro.route("/descontos")
@login_required
def lista_descontos():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, tipo, valor FROM descontos WHERE (id_academia = %s OR id_academia IS NULL) AND ativo = 1 ORDER BY nome",
        (academia_id,),
    )
    descontos = cur.fetchall()
    conn.close()
    return render_template("financeiro/descontos/lista_descontos.html", descontos=descontos)


@bp_financeiro.route("/descontos/editar/<int:desconto_id>", methods=["GET", "POST"])
@login_required
def editar_desconto(desconto_id):
    flash("Edição de desconto em desenvolvimento.", "info")
    return redirect(url_for("financeiro.lista_descontos"))


@bp_financeiro.route("/mensalidades")
@login_required
def lista_mensalidades():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, valor FROM mensalidades WHERE (id_academia = %s OR id_academia IS NULL) AND ativo = 1 ORDER BY nome",
        (academia_id,),
    )
    mensalidades = cur.fetchall()
    conn.close()
    return render_template("financeiro/mensalidades/lista_mensalidades.html", mensalidades=mensalidades)


@bp_financeiro.route("/receitas")
@login_required
def lista_receitas():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    mes = request.args.get("mes", date.today().month, type=int)
    ano = request.args.get("ano", date.today().year, type=int)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, descricao, valor, data FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
        (academia_id, mes, ano),
    )
    receitas = cur.fetchall()
    total_mes = sum(float(r.get("valor") or 0) for r in receitas)
    conn.close()
    return render_template("financeiro/receitas/lista_receitas.html", receitas=receitas, mes=mes, ano=ano, total_mes=total_mes)


@bp_financeiro.route("/despesas")
@login_required
def lista_despesas():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    mes = request.args.get("mes", date.today().month, type=int)
    ano = request.args.get("ano", date.today().year, type=int)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, descricao, valor, data FROM despesas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
        (academia_id, mes, ano),
    )
    despesas = cur.fetchall()
    total_mes = sum(float(d.get("valor") or 0) for d in despesas)
    conn.close()
    return render_template("financeiro/despesas/lista_despesas.html", despesas=despesas, mes=mes, ano=ano, total_mes=total_mes)


@bp_financeiro.route("/mensalidades/editar/<int:mensalidade_id>", methods=["GET", "POST"])
@login_required
def editar_mensalidade(mensalidade_id):
    flash("Edição de mensalidade em desenvolvimento.", "info")
    return redirect(url_for("financeiro.lista_mensalidades"))


@bp_financeiro.route("/receitas/editar/<int:receita_id>", methods=["GET", "POST"])
@login_required
def editar_receita(receita_id):
    flash("Edição de receita em desenvolvimento.", "info")
    return redirect(url_for("financeiro.lista_receitas"))


@bp_financeiro.route("/despesas/editar/<int:despesa_id>", methods=["GET", "POST"])
@login_required
def editar_despesa(despesa_id):
    flash("Edição de despesa em desenvolvimento.", "info")
    return redirect(url_for("financeiro.lista_despesas"))
