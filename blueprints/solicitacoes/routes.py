# ======================================================
# Blueprint: Solicitações de Aprovação (visita em academia)
# ======================================================
from datetime import date, datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from config import get_db_connection

try:
    import mysql.connector.errors as _mce
    _TABLE_ERROR = (_mce.ProgrammingError, _mce.OperationalError)
except Exception:
    _TABLE_ERROR = (Exception,)

bp_solicitacoes = Blueprint("solicitacoes", __name__, url_prefix="/solicitacoes")


def _get_academias_ids():
    """IDs de academias acessíveis pelo usuário."""
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
                "SELECT ac.id FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s",
                (getattr(current_user, "id_federacao", None),),
            )
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (getattr(current_user, "id_associacao", None),))
            ids = [r["id"] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return ids
    except Exception:
        return []


def _academia_permitida(academia_id):
    return academia_id in _get_academias_ids()


@bp_solicitacoes.route("")
@login_required
def lista():
    """Hub de solicitações agrupadas por tipo."""
    ids = _get_academias_ids()
    if not ids:
        flash("Nenhuma academia disponível.", "danger")
        return redirect(url_for("academia.painel_academia"))
    academia_id = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id") or ids[0]
    if academia_id not in ids:
        academia_id = ids[0]
    session["academia_gerenciamento_id"] = academia_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids)), tuple(ids))
    academias = cur.fetchall()

    # Contagens por tipo (visita: pendentes como origem e como destino)
    visita_origem = visita_destino = 0
    try:
        cur.execute(
            """SELECT COUNT(*) as c FROM solicitacoes_aprovacao
               WHERE academia_origem_id = %s AND status = 'pendente_origem' AND tipo = 'visita'""",
            (academia_id,),
        )
        visita_origem = cur.fetchone().get("c", 0) or 0
        cur.execute(
            """SELECT COUNT(*) as c FROM solicitacoes_aprovacao
               WHERE academia_destino_id = %s AND status = 'pendente_destino' AND tipo = 'visita'""",
            (academia_id,),
        )
        visita_destino = cur.fetchone().get("c", 0) or 0
    except _TABLE_ERROR:
        flash("A tabela de solicitações não existe. Execute a migration: migrations/add_solicitacoes_aprovacao.sql", "warning")
    cur.close()
    conn.close()

    return render_template(
        "solicitacoes/hub.html",
        academias=academias,
        academia_id=academia_id,
        visita_origem=visita_origem,
        visita_destino=visita_destino,
    )


@bp_solicitacoes.route("/visita")
@login_required
def visita_lista():
    """Lista solicitações de visita (como origem ou destino)."""
    ids = _get_academias_ids()
    if not ids:
        flash("Nenhuma academia disponível.", "danger")
        return redirect(url_for("academia.painel_academia"))
    academia_id = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id") or ids[0]
    if academia_id not in ids:
        academia_id = ids[0]
    tipo_filtro = request.args.get("tipo", "origem")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids)), tuple(ids))
    academias = cur.fetchall()
    cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
    academia = cur.fetchone()

    solicitacoes = []
    pendentes_origem = pendentes_destino = 0
    try:
        if tipo_filtro == "origem":
            cur.execute(
                """SELECT s.*, a.nome AS aluno_nome, ac_dest.nome AS academia_destino_nome
                   FROM solicitacoes_aprovacao s
                   JOIN alunos a ON a.id = s.aluno_id
                   JOIN academias ac_dest ON ac_dest.id = s.academia_destino_id
                   WHERE s.academia_origem_id = %s AND s.tipo = 'visita'
                     AND s.status IN ('pendente_origem', 'aprovado_origem', 'rejeitado_origem')
                   ORDER BY s.criado_em DESC""",
                (academia_id,),
            )
        else:
            cur.execute(
                """SELECT s.*, a.nome AS aluno_nome, ac_orig.nome AS academia_origem_nome,
                          t.Nome AS turma_nome, t.hora_inicio, t.hora_fim, t.dias_semana
                   FROM solicitacoes_aprovacao s
                   JOIN alunos a ON a.id = s.aluno_id
                   JOIN academias ac_orig ON ac_orig.id = s.academia_origem_id
                   LEFT JOIN turmas t ON t.TurmaID = s.turma_id
                   WHERE s.academia_destino_id = %s AND s.tipo = 'visita'
                     AND s.status IN ('pendente_destino', 'aprovado_destino', 'rejeitado_destino')
                   ORDER BY s.criado_em DESC""",
                (academia_id,),
            )
        solicitacoes = cur.fetchall()
        cur.execute("SELECT COUNT(*) as c FROM solicitacoes_aprovacao WHERE academia_origem_id = %s AND status = 'pendente_origem' AND tipo = 'visita'", (academia_id,))
        pendentes_origem = cur.fetchone().get("c", 0) or 0
        cur.execute("SELECT COUNT(*) as c FROM solicitacoes_aprovacao WHERE academia_destino_id = %s AND status = 'pendente_destino' AND tipo = 'visita'", (academia_id,))
        pendentes_destino = cur.fetchone().get("c", 0) or 0
    except _TABLE_ERROR:
        flash("A tabela de solicitações não existe. Execute: mysql DB < migrations/add_solicitacoes_aprovacao.sql", "warning")
    cur.close()
    conn.close()

    return render_template(
        "solicitacoes/visita_lista.html",
        academias=academias,
        academia_id=academia_id,
        academia=academia,
        solicitacoes=solicitacoes,
        tipo_filtro=tipo_filtro,
        pendentes_origem=pendentes_origem,
        pendentes_destino=pendentes_destino,
    )


@bp_solicitacoes.route("/visita/<int:sol_id>/aprovar-origem", methods=["POST"])
@login_required
def visita_aprovar_origem(sol_id):
    """Gestor academia origem aprova a solicitação."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM solicitacoes_aprovacao WHERE id = %s AND tipo = 'visita' AND status = 'pendente_origem'", (sol_id,))
    sol = cur.fetchone()
    if not sol or not _academia_permitida(sol["academia_origem_id"]):
        cur.close()
        conn.close()
        flash("Solicitação não encontrada ou sem permissão.", "danger")
        return redirect(url_for("solicitacoes.visita_lista", academia_id=sol["academia_origem_id"] if sol else None))
    observacao_origem = request.form.get("observacao_origem", "").strip()
    cur.execute(
        """UPDATE solicitacoes_aprovacao 
           SET status = 'pendente_destino', aprovado_origem_em = NOW(), aprovado_origem_por = %s,
               observacao_origem = %s
           WHERE id = %s""",
        (current_user.id, observacao_origem if observacao_origem else None, sol_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    flash("Solicitação aprovada. Aguardando aprovação da academia de destino.", "success")
    return redirect(url_for("solicitacoes.visita_lista", academia_id=sol["academia_origem_id"], tipo="origem"))


@bp_solicitacoes.route("/visita/<int:sol_id>/rejeitar-origem", methods=["POST"])
@login_required
def visita_rejeitar_origem(sol_id):
    """Gestor academia origem rejeita a solicitação."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM solicitacoes_aprovacao WHERE id = %s AND tipo = 'visita' AND status = 'pendente_origem'", (sol_id,))
    sol = cur.fetchone()
    if not sol or not _academia_permitida(sol["academia_origem_id"]):
        cur.close()
        conn.close()
        flash("Solicitação não encontrada ou sem permissão.", "danger")
        return redirect(url_for("solicitacoes.visita_lista", academia_id=sol["academia_origem_id"] if sol else None))
    cur.execute(
        "UPDATE solicitacoes_aprovacao SET status = 'rejeitado_origem', rejeitado_origem_em = NOW(), rejeitado_origem_por = %s WHERE id = %s",
        (current_user.id, sol_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    flash("Solicitação rejeitada.", "info")
    return redirect(url_for("solicitacoes.visita_lista", academia_id=sol["academia_origem_id"], tipo="origem"))


@bp_solicitacoes.route("/visita/<int:sol_id>/aprovar-destino", methods=["GET", "POST"])
@login_required
def visita_aprovar_destino(sol_id):
    """Gestor academia destino aprova, escolhe turma e data."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM solicitacoes_aprovacao WHERE id = %s AND tipo = 'visita' AND status = 'pendente_destino'", (sol_id,))
    sol = cur.fetchone()
    if not sol or not _academia_permitida(sol["academia_destino_id"]):
        cur.close()
        conn.close()
        flash("Solicitação não encontrada ou sem permissão.", "danger")
        return redirect(url_for("solicitacoes.visita_lista", academia_id=sol["academia_destino_id"] if sol else None))

    cur.execute("SELECT id, nome FROM alunos WHERE id = %s", (sol["aluno_id"],))
    aluno = cur.fetchone()
    cur.execute("SELECT TurmaID, Nome, hora_inicio, hora_fim, dias_semana FROM turmas WHERE id_academia = %s ORDER BY Nome", (sol["academia_destino_id"],))
    turmas = cur.fetchall()
    # Formatar horas das turmas
    for t in turmas:
        if t.get("hora_inicio"):
            hi = t["hora_inicio"]
            t["hora_inicio_str"] = hi.strftime("%H:%M") if hasattr(hi, "strftime") else str(hi)[:5]
        if t.get("hora_fim"):
            hf = t["hora_fim"]
            t["hora_fim_str"] = hf.strftime("%H:%M") if hasattr(hf, "strftime") else str(hf)[:5]

    if request.method == "POST":
        turma_id = request.form.get("turma_id", type=int)
        data_visita = request.form.get("data_visita")
        if not turma_id or not data_visita:
            flash("Selecione a turma e a data da visita.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("solicitacoes.visita_aprovar_destino", sol_id=sol_id))
        try:
            data_visita_dt = datetime.strptime(data_visita, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            flash("Data inválida.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("solicitacoes.visita_aprovar_destino", sol_id=sol_id))
        observacao_destino = request.form.get("observacao_destino", "").strip()
        cur.execute(
            """UPDATE solicitacoes_aprovacao
               SET status = 'aprovado_destino', aprovado_destino_em = NOW(), aprovado_destino_por = %s,
                   turma_id = %s, data_visita = %s, observacao_destino = %s
               WHERE id = %s""",
            (current_user.id, turma_id, data_visita_dt, observacao_destino if observacao_destino else None, sol_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Visita aprovada. O aluno aparecerá na lista de chamada da turma na data indicada.", "success")
        return redirect(url_for("solicitacoes.visita_lista", academia_id=sol["academia_destino_id"], tipo="destino"))

    cur.close()
    conn.close()
    return render_template(
        "solicitacoes/visita_aprovar_destino.html",
        sol=sol,
        aluno=aluno,
        turmas=turmas,
    )


@bp_solicitacoes.route("/visita/<int:sol_id>/rejeitar-destino", methods=["POST"])
@login_required
def visita_rejeitar_destino(sol_id):
    """Gestor academia destino rejeita a solicitação."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM solicitacoes_aprovacao WHERE id = %s AND tipo = 'visita' AND status = 'pendente_destino'", (sol_id,))
    sol = cur.fetchone()
    if not sol or not _academia_permitida(sol["academia_destino_id"]):
        cur.close()
        conn.close()
        flash("Solicitação não encontrada ou sem permissão.", "danger")
        return redirect(url_for("solicitacoes.visita_lista", academia_id=sol["academia_destino_id"] if sol else None))
    observacao_destino = request.form.get("observacao_destino", "").strip()
    cur.execute(
        """UPDATE solicitacoes_aprovacao 
           SET status = 'rejeitado_destino', aprovado_destino_em = NOW(), aprovado_destino_por = %s,
               observacao_destino = %s
           WHERE id = %s""",
        (current_user.id, observacao_destino if observacao_destino else None, sol_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    flash("Solicitação rejeitada.", "info")
    return redirect(url_for("solicitacoes.visita_lista", academia_id=sol["academia_destino_id"], tipo="destino"))
