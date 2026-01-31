# ======================================================
# 🧩 Blueprint: Painel do Aluno
# ======================================================

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from config import get_db_connection
from datetime import datetime


bp_painel_aluno = Blueprint(
    "painel_aluno",
    __name__,
    url_prefix="/painel_aluno"
)


def _get_aluno():
    """Retorna o aluno vinculado ao usuário ou None."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM alunos WHERE usuario_id = %s", (current_user.id,))
    aluno = cur.fetchone()
    cur.close()
    conn.close()
    return aluno


def _aluno_required(f):
    """Decorator: exige role aluno/admin e aluno vinculado."""
    from functools import wraps
    @wraps(f)
    def _view(*a, **kw):
        if not (current_user.has_role("aluno") or current_user.has_role("admin")):
            flash("Acesso restrito aos alunos.", "danger")
            return redirect(url_for("painel.home"))
        aluno = _get_aluno()
        if not aluno:
            flash("Nenhum aluno está vinculado a este usuário.", "warning")
            return redirect(url_for("painel.home"))
        return f(*a, aluno=aluno, **kw)
    return _view


@bp_painel_aluno.route("/")
@login_required
@_aluno_required
def painel(aluno):
    return render_template(
        "painel/painel_aluno.html",
        usuario=current_user,
        aluno=aluno
    )


@bp_painel_aluno.route("/mensalidades")
@login_required
@_aluno_required
def minhas_mensalidades(aluno):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                   m.nome as plano_nome
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            WHERE ma.aluno_id = %s
            ORDER BY ma.data_vencimento DESC
            LIMIT 24
        """, (aluno["id"],))
        mensalidades = cur.fetchall()
    except Exception:
        mensalidades = []
    cur.close()
    conn.close()
    return render_template(
        "painel_aluno/minhas_mensalidades.html",
        usuario=current_user,
        aluno=aluno,
        mensalidades=mensalidades
    )


@bp_painel_aluno.route("/turma")
@login_required
@_aluno_required
def minha_turma(aluno):
    turma_id = aluno.get("TurmaID")
    if not turma_id:
        return render_template(
            "painel_aluno/minha_turma.html",
            usuario=current_user,
            aluno=aluno,
            turma=None
        )
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM turmas WHERE TurmaID = %s", (turma_id,))
    turma = cur.fetchone()
    cur.close()
    conn.close()
    return render_template(
        "painel_aluno/minha_turma.html",
        usuario=current_user,
        aluno=aluno,
        turma=turma
    )


@bp_painel_aluno.route("/presencas")
@login_required
@_aluno_required
def minhas_presencas(aluno):
    ano = request.args.get("ano", datetime.today().year, type=int)
    mes = request.args.get("mes", 0, type=int)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if mes:
            cur.execute("""
                SELECT data_presenca, presente
                FROM presencas
                WHERE aluno_id = %s AND MONTH(data_presenca) = %s AND YEAR(data_presenca) = %s
                ORDER BY data_presenca
            """, (aluno["id"], mes, ano))
        else:
            cur.execute("""
                SELECT data_presenca, presente
                FROM presencas
                WHERE aluno_id = %s AND YEAR(data_presenca) = %s
                ORDER BY data_presenca
            """, (aluno["id"], ano))
        presencas = cur.fetchall()
    except Exception:
        presencas = []
    cur.close()
    conn.close()
    total = len(presencas)
    presentes = sum(1 for p in presencas if p.get("presente") == 1)
    return render_template(
        "painel_aluno/minhas_presencas.html",
        usuario=current_user,
        aluno=aluno,
        presencas=presencas,
        ano=ano,
        mes=mes,
        total=total,
        presentes=presentes
    )
