# ======================================================
# Blueprint: Financeiro (mensalidades, receitas, despesas, descontos)
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from datetime import date
from decimal import Decimal, InvalidOperation
from config import get_db_connection

bp_financeiro = Blueprint("financeiro", __name__, url_prefix="/financeiro")


def _parse_valor(val: str):
    """Converte string para valor decimal (aceita , ou .)."""
    if not val:
        return None
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except (ValueError, InvalidOperation):
        return None


def _get_academias_for_select():
    """Retorna lista de academias para dropdown (quando usuário tem múltiplas)."""
    ids = _get_academias_ids()
    if not ids:
        return []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT id, nome FROM academias WHERE id IN ({placeholders}) ORDER BY nome", tuple(ids))
    rows = cur.fetchall()
    conn.close()
    return rows


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
    # Prioridade: request > academia_gerenciamento (modo academia) > finance_academia_id
    aid = (
        request.args.get("academia_id", type=int)
        or (session.get("academia_gerenciamento_id") if session.get("modo_painel") == "academia" else None)
        or session.get("finance_academia_id")
    )
    if aid and aid in ids:
        session["finance_academia_id"] = aid
        if session.get("modo_painel") == "academia":
            session["academia_gerenciamento_id"] = aid
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
    try:
        cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
        ac = cur.fetchone()
        academia_nome = ac["nome"] if ac else None
    except Exception:
        academia_nome = None

    mes, ano = date.today().month, date.today().year
    receitas_mes = despesas_mes = 0.0
    try:
        cur.execute(
            "SELECT COALESCE(SUM(valor), 0) as total FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
            (academia_id, mes, ano),
        )
        receitas_mes = float(cur.fetchone().get("total") or 0)
    except Exception:
        pass
    try:
        cur.execute(
            "SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
            (academia_id, mes, ano),
        )
        despesas_mes = float(cur.fetchone().get("total") or 0)
    except Exception:
        pass
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

    receitas = []
    total_mes = 0.0
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, descricao, valor, data, categoria FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
            (academia_id, mes, ano),
        )
        receitas = cur.fetchall()
        total_mes = sum(float(r.get("valor") or 0) for r in receitas)
        conn.close()
    except Exception:
        pass
    return render_template("financeiro/receitas/lista_receitas.html", receitas=receitas, mes=mes, ano=ano, total_mes=total_mes, ano_atual=date.today().year)


@bp_financeiro.route("/despesas")
@login_required
def lista_despesas():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    mes = request.args.get("mes", date.today().month, type=int)
    ano = request.args.get("ano", date.today().year, type=int)

    despesas = []
    total_mes = 0.0
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, descricao, valor, data, categoria FROM despesas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
            (academia_id, mes, ano),
        )
        despesas = cur.fetchall()
        total_mes = sum(float(d.get("valor") or 0) for d in despesas)
        conn.close()
    except Exception:
        pass
    return render_template("financeiro/despesas/lista_despesas.html", despesas=despesas, mes=mes, ano=ano, total_mes=total_mes, ano_atual=date.today().year)


@bp_financeiro.route("/mensalidades/editar/<int:mensalidade_id>", methods=["GET", "POST"])
@login_required
def editar_mensalidade(mensalidade_id):
    flash("Edição de mensalidade em desenvolvimento.", "info")
    return redirect(url_for("financeiro.lista_mensalidades"))


# ---------- RECEITAS: cadastrar, editar, excluir ----------
@bp_financeiro.route("/receitas/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar_receita():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in _get_academias_ids():
            id_acad = academia_id

        if not descricao:
            flash("Informe a descrição.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)
        if valor is None or valor <= 0:
            flash("Informe um valor válido.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)
        if not data_str:
            flash("Informe a data.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, observacoes, criado_por) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (descricao, valor, data_str, categoria, id_acad, observacoes, current_user.id),
            )
            conn.commit()
            conn.close()
            flash("Receita cadastrada com sucesso.", "success")
            return redirect(url_for("financeiro.lista_receitas"))
        except Exception:
            flash("Erro ao salvar receita.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)

    return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/receitas/editar/<int:receita_id>", methods=["GET", "POST"])
@login_required
def editar_receita(receita_id):
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(
        "SELECT id, descricao, valor, data, categoria, id_academia, observacoes FROM receitas WHERE id = %s AND id_academia IN (" + placeholders + ")",
        (receita_id,) + tuple(ids),
    )
    receita = cur.fetchone()
    conn.close()

    if not receita:
        flash("Receita não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_receitas"))

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or receita["id_academia"]
        if id_acad not in _get_academias_ids():
            id_acad = receita["id_academia"]

        if not descricao:
            flash("Informe a descrição.", "danger")
            receita["descricao"] = request.form.get("descricao")
            receita["valor"] = request.form.get("valor")
            receita["data"] = request.form.get("data")
            receita["categoria"] = request.form.get("categoria")
            receita["observacoes"] = request.form.get("observacoes")
            return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)
        if valor is None or valor <= 0:
            flash("Informe um valor válido.", "danger")
            receita["descricao"] = descricao
            receita["valor"] = request.form.get("valor")
            receita["data"] = data_str
            receita["categoria"] = categoria
            receita["observacoes"] = observacoes
            return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)
        if not data_str:
            flash("Informe a data.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE receitas SET descricao=%s, valor=%s, data=%s, categoria=%s, id_academia=%s, observacoes=%s WHERE id=%s",
                (descricao, valor, data_str, categoria, id_acad, observacoes, receita_id),
            )
            conn.commit()
            conn.close()
            flash("Receita atualizada.", "success")
            return redirect(url_for("financeiro.lista_receitas"))
        except Exception:
            flash("Erro ao atualizar receita.", "danger")

    return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/receitas/excluir/<int:receita_id>", methods=["POST"])
@login_required
def excluir_receita(receita_id):
    ids = _get_academias_ids()
    if not ids:
        return redirect(url_for("painel.home"))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ph = ",".join(["%s"] * len(ids))
        cur.execute("DELETE FROM receitas WHERE id = %s AND id_academia IN (" + ph + ")", (receita_id,) + tuple(ids))
        conn.commit()
        conn.close()
        flash("Receita excluída.", "success")
    except Exception:
        flash("Erro ao excluir receita.", "danger")
    return redirect(url_for("financeiro.lista_receitas"))


# ---------- DESPESAS: cadastrar, editar, excluir ----------
@bp_financeiro.route("/despesas/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar_despesa():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in _get_academias_ids():
            id_acad = academia_id

        if not descricao:
            flash("Informe a descrição.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)
        if valor is None or valor <= 0:
            flash("Informe um valor válido.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)
        if not data_str:
            flash("Informe a data.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO despesas (descricao, valor, data, categoria, id_academia, observacoes, criado_por) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (descricao, valor, data_str, categoria, id_acad, observacoes, current_user.id),
            )
            conn.commit()
            conn.close()
            flash("Despesa cadastrada com sucesso.", "success")
            return redirect(url_for("financeiro.lista_despesas"))
        except Exception:
            flash("Erro ao salvar despesa.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)

    return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/despesas/editar/<int:despesa_id>", methods=["GET", "POST"])
@login_required
def editar_despesa(despesa_id):
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(
        "SELECT id, descricao, valor, data, categoria, id_academia, observacoes FROM despesas WHERE id = %s AND id_academia IN (" + placeholders + ")",
        (despesa_id,) + tuple(ids),
    )
    despesa = cur.fetchone()
    conn.close()

    if not despesa:
        flash("Despesa não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_despesas"))

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or despesa["id_academia"]
        if id_acad not in _get_academias_ids():
            id_acad = despesa["id_academia"]

        if not descricao:
            flash("Informe a descrição.", "danger")
            despesa["descricao"] = request.form.get("descricao")
            despesa["valor"] = request.form.get("valor")
            despesa["data"] = request.form.get("data")
            despesa["categoria"] = request.form.get("categoria")
            despesa["observacoes"] = request.form.get("observacoes")
            return render_template("financeiro/despesas/form_despesa.html", despesa=despesa, academias=academias, academia_id=academia_id)
        if valor is None or valor <= 0:
            flash("Informe um valor válido.", "danger")
            despesa["descricao"] = descricao
            despesa["valor"] = request.form.get("valor")
            despesa["data"] = data_str
            despesa["categoria"] = categoria
            despesa["observacoes"] = observacoes
            return render_template("financeiro/despesas/form_despesa.html", despesa=despesa, academias=academias, academia_id=academia_id)
        if not data_str:
            flash("Informe a data.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=despesa, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE despesas SET descricao=%s, valor=%s, data=%s, categoria=%s, id_academia=%s, observacoes=%s WHERE id=%s",
                (descricao, valor, data_str, categoria, id_acad, observacoes, despesa_id),
            )
            conn.commit()
            conn.close()
            flash("Despesa atualizada.", "success")
            return redirect(url_for("financeiro.lista_despesas"))
        except Exception:
            flash("Erro ao atualizar despesa.", "danger")

    return render_template("financeiro/despesas/form_despesa.html", despesa=despesa, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/despesas/excluir/<int:despesa_id>", methods=["POST"])
@login_required
def excluir_despesa(despesa_id):
    ids = _get_academias_ids()
    if not ids:
        return redirect(url_for("painel.home"))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ph = ",".join(["%s"] * len(ids))
        cur.execute("DELETE FROM despesas WHERE id = %s AND id_academia IN (" + ph + ")", (despesa_id,) + tuple(ids))
        conn.commit()
        conn.close()
        flash("Despesa excluída.", "success")
    except Exception:
        flash("Erro ao excluir despesa.", "danger")
    return redirect(url_for("financeiro.lista_despesas"))
