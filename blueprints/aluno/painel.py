# ======================================================
# 🧩 Blueprint: Painel do Aluno
# ======================================================

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user
from config import get_db_connection
from datetime import datetime, date


bp_painel_aluno = Blueprint(
    "painel_aluno",
    __name__,
    url_prefix="/painel_aluno"
)


def _build_endereco_completo(aluno):
    """Monta o endereço completo para exibição no currículo."""
    partes = []
    rua = aluno.get("rua") or aluno.get("endereco") or ""
    numero = aluno.get("numero")
    if rua:
        partes.append(f"{rua}{', ' + str(numero) if numero else ''}")
    elif numero:
        partes.append(f"Nº {numero}")
    if aluno.get("complemento"):
        partes.append(str(aluno.get("complemento")))
    if aluno.get("bairro"):
        partes.append(str(aluno.get("bairro")))
    cidade = aluno.get("cidade") or ""
    estado = aluno.get("estado") or ""
    if cidade or estado:
        partes.append(f"{cidade}{' - ' + estado if estado else ''}".strip(" -"))
    cep = aluno.get("cep")
    if cep:
        cep_str = str(cep).replace("-", "").replace(".", "")[:8]
        partes.append(f"CEP {cep_str}")
    aluno["endereco_completo"] = ", ".join(p for p in partes if p) or None


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


def _enriquecer_aluno_painel(aluno):
    """Adiciona academia_nome, turma_nome, modalidades, faixa, proxima_faixa ao aluno."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ac.nome AS academia_nome, t.Nome AS turma_nome
               FROM alunos a
               LEFT JOIN academias ac ON ac.id = a.id_academia
               LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
               WHERE a.id = %s""",
            (aluno["id"],),
        )
        row = cur.fetchone()
        if row:
            aluno["academia_nome"] = row.get("academia_nome")
            aluno["turma_nome"] = row.get("turma_nome")
        cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (aluno.get("graduacao_id"),))
        g = cur.fetchone()
        if g:
            aluno["faixa_nome"] = g.get("faixa")
            aluno["graduacao_nome"] = g.get("graduacao")
        aluno.setdefault("faixa_nome", None)
        aluno.setdefault("graduacao_nome", None)
        cur.execute(
            """SELECT m.nome FROM modalidade m
               INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id
               WHERE am.aluno_id = %s ORDER BY m.nome""",
            (aluno["id"],),
        )
        aluno["modalidades"] = [r["nome"] for r in cur.fetchall()]
        aluno["proxima_faixa"] = "—"
        cur.execute("SELECT id, faixa, graduacao FROM graduacao ORDER BY id")
        faixas = cur.fetchall()
        gid = aluno.get("graduacao_id")
        for i, f in enumerate(faixas):
            if f["id"] == gid and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                aluno["proxima_faixa"] = f"{proxima.get('faixa', '')} {proxima.get('graduacao', '')}".strip() or "—"
                break
    except Exception:
        pass
    finally:
        cur.close()
        conn.close()


@bp_painel_aluno.route("/")
@login_required
@_aluno_required
def painel(aluno):
    session["modo_painel"] = "aluno"
    stats = _stats_painel_aluno(aluno)
    return render_template(
        "painel/painel_aluno.html",
        usuario=current_user,
        aluno=aluno,
        stats=stats,
    )


@bp_painel_aluno.route("/meu-perfil")
@login_required
@_aluno_required
def meu_perfil(aluno):
    session["modo_painel"] = "aluno"
    _enriquecer_aluno_painel(aluno)
    return render_template(
        "painel_aluno/meu_perfil.html",
        usuario=current_user,
        aluno=aluno,
    )


def _stats_painel_aluno(aluno):
    """Retorna estatísticas básicas para o dashboard do aluno."""
    stats = {"mensalidades_pendentes": 0, "presencas_mes": 0, "turmas_count": 0}
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        hoje = datetime.today()
        cur.execute(
            """SELECT COUNT(*) as c FROM mensalidade_aluno ma
               JOIN mensalidades m ON m.id = ma.mensalidade_id
               WHERE ma.aluno_id = %s AND (ma.status = 'pendente' OR ma.status IS NULL)
               AND ma.data_vencimento < %s""",
            (aluno["id"], hoje.strftime("%Y-%m-%d")),
        )
        stats["mensalidades_pendentes"] = cur.fetchone().get("c") or 0
        cur.execute(
            """SELECT COUNT(*) as c FROM presencas
               WHERE aluno_id = %s AND presente = 1
               AND MONTH(data_presenca) = %s AND YEAR(data_presenca) = %s""",
            (aluno["id"], hoje.month, hoje.year),
        )
        stats["presencas_mes"] = cur.fetchone().get("c") or 0
        cur.execute(
            """SELECT COUNT(DISTINCT TurmaID) as c FROM aluno_turmas WHERE aluno_id = %s""",
            (aluno["id"],),
        )
        r = cur.fetchone()
        if r and (r.get("c") or 0) > 0:
            stats["turmas_count"] = r.get("c") or 0
        else:
            cur.execute("SELECT 1 FROM alunos WHERE id = %s AND TurmaID IS NOT NULL", (aluno["id"],))
            stats["turmas_count"] = 1 if cur.fetchone() else 0
        cur.close()
        conn.close()
    except Exception:
        pass
    return stats


def _calcular_valor_com_juros_multas(ma, hoje=None):
    """Calcula valor ajustado com multa (2%/mês) e juros (0,033%/dia) quando atrasado."""
    hoje = hoje or date.today()
    if ma.get("status") == "pago" or not ma.get("aplicar_juros_multas"):
        return float(ma.get("valor") or 0), None
    try:
        venc = ma.get("data_vencimento")
        if isinstance(venc, str):
            venc = datetime.strptime(venc[:10], "%Y-%m-%d").date()
        if venc >= hoje:
            return float(ma.get("valor") or 0), None
    except Exception:
        return float(ma.get("valor") or 0), None
    valor = float(ma.get("valor") or 0)
    dias = (hoje - venc).days
    if dias <= 0:
        return valor, None
    pct_multa = float(ma.get("percentual_multa_mes") or 2) / 100
    pct_juros_dia = float(ma.get("percentual_juros_dia") or 0.0333) / 100
    meses = dias / 30.0
    multa = valor * pct_multa * meses
    juros = valor * pct_juros_dia * dias
    return round(valor + multa + juros, 2), round(valor, 2)


def _status_efetivo_painel(status, data_venc, status_pagamento=None):
    """Pendente_aprovacao -> aguardando_confirmacao. Pendente vencido -> atrasado."""
    if status_pagamento == "pendente_aprovacao":
        return "aguardando_confirmacao"
    if status and status not in ("pendente",):
        return status
    try:
        venc = data_venc if isinstance(data_venc, date) else (date.fromisoformat(str(data_venc)[:10]) if data_venc else None)
        if venc and venc < date.today():
            return "atrasado"
    except Exception:
        pass
    return status or "pendente"


@bp_painel_aluno.route("/mensalidades")
@login_required
@_aluno_required
def minhas_mensalidades(aluno):
    from blueprints.financeiro.routes import _valor_com_desconto

    mes_arg = request.args.get("mes", type=int)
    mes = mes_arg if (mes_arg and 1 <= mes_arg <= 12) else None
    ano_arg = request.args.get("ano", type=int)
    ano = ano_arg if (ano_arg and 2000 <= ano_arg <= 2100) else date.today().year

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE mensalidade_aluno SET status = 'atrasado' WHERE aluno_id = %s AND status = 'pendente' AND data_vencimento < CURDATE()",
            (aluno["id"],),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    cur.close()
    cur = conn.cursor(dictionary=True)
    hoje = date.today()
    id_academia = aluno.get("id_academia")

    if mes:
        where_clause = "ma.aluno_id = %s AND MONTH(ma.data_vencimento) = %s AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'"
        params = (aluno["id"], mes, ano)
    else:
        where_clause = "ma.aluno_id = %s AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'"
        params = (aluno["id"], ano)
    try:
        cur.execute(f"""
            SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                   ma.status_pagamento, ma.comprovante_url, ma.observacoes,
                   ma.valor_original, ma.desconto_aplicado, ma.id_desconto,
                   m.nome as plano_nome, m.id_academia,
                   COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
                   COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
                   COALESCE(m.percentual_juros_dia, 0.0333) AS percentual_juros_dia
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            WHERE {where_clause}
            ORDER BY ma.data_vencimento DESC
            LIMIT 200
        """, params)
        rows = cur.fetchall()
    except Exception:
        try:
            if mes:
                cur.execute("""
                    SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                           ma.observacoes, ma.status_pagamento, ma.comprovante_url,
                           m.nome as plano_nome, m.id_academia
                    FROM mensalidade_aluno ma
                    JOIN mensalidades m ON m.id = ma.mensalidade_id
                    WHERE ma.aluno_id = %s AND MONTH(ma.data_vencimento) = %s AND YEAR(ma.data_vencimento) = %s
                    ORDER BY ma.data_vencimento DESC
                    LIMIT 200
                """, (aluno["id"], mes, ano))
            else:
                cur.execute("""
                    SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                           ma.observacoes, ma.status_pagamento, ma.comprovante_url,
                           m.nome as plano_nome, m.id_academia
                    FROM mensalidade_aluno ma
                    JOIN mensalidades m ON m.id = ma.mensalidade_id
                    WHERE ma.aluno_id = %s AND YEAR(ma.data_vencimento) = %s
                    ORDER BY ma.data_vencimento DESC
                    LIMIT 200
                """, (aluno["id"], ano))
            rows = cur.fetchall()
            for r in rows:
                r.setdefault("aplicar_juros_multas", 0)
                r.setdefault("percentual_multa_mes", 2)
                r.setdefault("percentual_juros_dia", 0.0333)
                r.setdefault("status_pagamento", None)
                r.setdefault("comprovante_url", None)
                r.setdefault("valor_original", None)
                r.setdefault("desconto_aplicado", 0)
                r.setdefault("id_desconto", None)
        except Exception:
            rows = []

    all_for_contagens = []
    try:
        if mes:
            cur.execute("""
                SELECT ma.id, ma.status, ma.status_pagamento, ma.data_vencimento
                FROM mensalidade_aluno ma
                WHERE ma.aluno_id = %s AND MONTH(ma.data_vencimento) = %s AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'
            """, (aluno["id"], mes, ano))
        else:
            cur.execute("""
                SELECT ma.id, ma.status, ma.status_pagamento, ma.data_vencimento
                FROM mensalidade_aluno ma
                WHERE ma.aluno_id = %s AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'
            """, (aluno["id"], ano))
        all_for_contagens = cur.fetchall()
    except Exception:
        pass

    contagens = {"pago": 0, "pendente": 0, "atrasado": 0, "aguardando_confirmacao": 0}
    for r in all_for_contagens:
        se = _status_efetivo_painel(r.get("status"), r.get("data_vencimento"), r.get("status_pagamento"))
        contagens[se] = contagens.get(se, 0) + 1

    mensalidades = []
    for ma in rows:
        valor_display, valor_original = _calcular_valor_com_juros_multas(ma, hoje)
        ma["valor_display"] = valor_display
        ma["valor_original"] = valor_original
        ma["status_efetivo"] = _status_efetivo_painel(ma.get("status"), ma.get("data_vencimento"), ma.get("status_pagamento"))
        ma["comentario_informado"] = ma.get("comentario_informado") or ma.get("observacoes")
        id_acad = ma.get("id_academia") or id_academia
        if id_acad:
            vi, vd, vf, desconto_nome = _valor_com_desconto(ma, aluno["id"], id_acad, hoje)
            ma["valor_integral"] = vi
            ma["valor_desconto"] = vd
            ma["valor_final"] = vf
            ma["desconto_nome"] = desconto_nome
            ma["tem_desconto"] = vd > 0
        else:
            ma["valor_integral"] = valor_display
            ma["valor_desconto"] = 0
            ma["valor_final"] = valor_display
            ma["tem_desconto"] = False
        mensalidades.append(ma)

    avulsas = []
    try:
        if mes:
            cur.execute("""
                SELECT id, descricao, valor, data_vencimento, data_pagamento, status
                FROM cobranca_avulsa
                WHERE aluno_id = %s AND status != 'cancelado'
                AND MONTH(data_vencimento) = %s AND YEAR(data_vencimento) = %s
                ORDER BY data_vencimento DESC
            """, (aluno["id"], mes, ano))
        else:
            cur.execute("""
                SELECT id, descricao, valor, data_vencimento, data_pagamento, status
                FROM cobranca_avulsa
                WHERE aluno_id = %s AND status != 'cancelado'
                AND YEAR(data_vencimento) = %s
                ORDER BY data_vencimento DESC
            """, (aluno["id"], ano))
        avulsas = cur.fetchall()
    except Exception:
        pass

    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/minhas_mensalidades.html",
        usuario=current_user,
        aluno=aluno,
        mensalidades=mensalidades,
        avulsas=avulsas,
        contagens=contagens,
        mes=mes,
        ano=ano,
        ano_atual=date.today().year,
    )


def _aluno_ou_professor_required(f):
    """Permite aluno (com aluno vinculado) ou professor."""
    from functools import wraps
    @wraps(f)
    def _view(*a, **kw):
        if not (current_user.has_role("aluno") or current_user.has_role("professor") or current_user.has_role("admin")):
            flash("Acesso restrito.", "danger")
            return redirect(url_for("painel.home"))
        aluno = _get_aluno() if current_user.has_role("aluno") else None
        if current_user.has_role("aluno") and not aluno and not current_user.has_role("admin"):
            flash("Nenhum aluno vinculado a este usuário.", "warning")
            return redirect(url_for("painel.home"))
        return f(*a, aluno=aluno, **kw)
    return _view


def _buscar_alunos_turma(cur, turma_id, id_academia_turma):
    """Retorna lista de alunos da turma (mesma turma e mesma academia)."""
    try:
        if id_academia_turma is not None:
            cur.execute("""
                SELECT a.id, a.nome, a.foto, g.faixa AS faixa_nome, g.graduacao AS graduacao_nome
                FROM alunos a
                LEFT JOIN graduacao g ON g.id = a.graduacao_id
                WHERE a.TurmaID = %s AND a.id_academia = %s
                ORDER BY a.nome
            """, (turma_id, id_academia_turma))
        else:
            cur.execute("""
                SELECT a.id, a.nome, a.foto, g.faixa AS faixa_nome, g.graduacao AS graduacao_nome
                FROM alunos a
                LEFT JOIN graduacao g ON g.id = a.graduacao_id
                WHERE a.TurmaID = %s
                ORDER BY a.nome
            """, (turma_id,))
        return cur.fetchall()
    except Exception:
        return []


@bp_painel_aluno.route("/turma")
@login_required
@_aluno_ou_professor_required
def minha_turma(aluno=None):
    turma_selecionada_id = request.args.get("turma_id", type=int)
    turmas_com_alunos = []  # [(turma, alunos), ...]

    if aluno:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        turmas_list = _turmas_do_aluno(cur, aluno["id"], aluno.get("TurmaID"))
        turma_ids = [t["TurmaID"] for t in turmas_list]
        cur.close()
        conn.close()
    elif current_user.has_role("professor") or current_user.has_role("admin"):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        turma_ids = []
        try:
            cur.execute("SELECT id FROM professores WHERE email = %s LIMIT 1", (current_user.email,))
            prof = cur.fetchone()
            if prof:
                cur.execute("SELECT TurmaID FROM turma_professor WHERE professor_id = %s ORDER BY TurmaID", (prof["id"],))
                turma_ids = [r["TurmaID"] for r in cur.fetchall()]
        except Exception:
            pass
        cur.close()
        conn.close()
    else:
        turma_ids = []

    if turma_ids:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        for tid in turma_ids:
            cur.execute("SELECT * FROM turmas WHERE TurmaID = %s", (tid,))
            t = cur.fetchone()
            if t:
                id_acad = t.get("id_academia")
                alns = _buscar_alunos_turma(cur, tid, id_acad)
                turmas_com_alunos.append((t, alns))
        cur.close()
        conn.close()

    if turma_selecionada_id and len(turmas_com_alunos) > 1:
        turmas_com_alunos.sort(key=lambda x: (0 if x[0]["TurmaID"] == turma_selecionada_id else 1, x[0]["Nome"] or ""))
    else:
        turmas_com_alunos.sort(key=lambda x: (x[0]["Nome"] or "").lower())

    return render_template(
        "painel_aluno/minha_turma.html",
        usuario=current_user,
        aluno=aluno,
        turmas_com_alunos=turmas_com_alunos,
        turma_selecionada_id=turma_selecionada_id,
    )


def _turmas_do_aluno(cur, aluno_id, aluno_turma_id):
    """Retorna lista de turmas do aluno: de aluno_turmas ou fallback para TurmaID."""
    turmas_list = []
    try:
        cur.execute("""
            SELECT t.TurmaID, t.Nome
            FROM aluno_turmas at
            JOIN turmas t ON t.TurmaID = at.TurmaID
            WHERE at.aluno_id = %s
            ORDER BY t.Nome
        """, (aluno_id,))
        turmas_list = cur.fetchall()
    except Exception:
        pass
    if not turmas_list and aluno_turma_id:
        try:
            cur.execute("SELECT TurmaID, Nome FROM turmas WHERE TurmaID = %s", (aluno_turma_id,))
            row = cur.fetchone()
            if row:
                turmas_list = [row]
        except Exception:
            pass
    return turmas_list


def _calcular_meses_filtro(ano, mes_de, mes_ate, atalho):
    """Calcula lista de meses. Retorna [] para ano inteiro."""
    hoje = datetime.today()
    a = ano or hoje.year
    if atalho == "este_mes" and a == hoje.year:
        return [hoje.month]
    if atalho == "ultimos_3" and a == hoje.year:
        m = hoje.month
        return list(range(max(1, m - 2), m + 1))
    if atalho == "trimestre" and a == hoje.year:
        m = hoje.month
        inicio = ((m - 1) // 3) * 3 + 1
        return list(range(inicio, min(inicio + 3, 13)))
    if atalho == "ano" or (not mes_de and not mes_ate and not atalho):
        return []
    if mes_de and mes_ate:
        de, ate = int(mes_de), int(mes_ate)
        if 1 <= de <= 12 and 1 <= ate <= 12:
            return list(range(min(de, ate), max(de, ate) + 1))
    if mes_de:
        m = int(mes_de)
        return [m] if 1 <= m <= 12 else []
    return []


@bp_painel_aluno.route("/presencas")
@login_required
@_aluno_required
def minhas_presencas(aluno):
    ano = request.args.get("ano", datetime.today().year, type=int)
    mes_de = request.args.get("mes_de", type=int)
    mes_ate = request.args.get("mes_ate", type=int)
    atalho = request.args.get("atalho", "").strip()
    meses_legado = [int(x) for x in request.args.getlist("mes") if str(x).isdigit() and 1 <= int(x) <= 12]
    turma_filtro_id = request.args.get("turma_id", type=int)

    meses_sel = _calcular_meses_filtro(ano, mes_de, mes_ate, atalho) if atalho or mes_de or mes_ate else meses_legado

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    turmas_do_aluno = _turmas_do_aluno(cur, aluno["id"], aluno.get("TurmaID"))

    if turmas_do_aluno and not turma_filtro_id:
        turma_filtro_id = turmas_do_aluno[0]["TurmaID"]

    where_extra = ""
    params_extra = []
    if turma_filtro_id:
        where_extra = " AND p.turma_id = %s"
        params_extra = [turma_filtro_id]

    try:
        if meses_sel:
            placeholders = ",".join(["%s"] * len(meses_sel))
            cur.execute("""
                SELECT p.data_presenca, p.presente
                FROM presencas p
                WHERE p.aluno_id = %s AND YEAR(p.data_presenca) = %s
                  AND MONTH(p.data_presenca) IN (""" + placeholders + ")"
                + where_extra + """
                ORDER BY p.data_presenca
            """, [aluno["id"], ano] + meses_sel + params_extra)
        else:
            cur.execute("""
                SELECT p.data_presenca, p.presente
                FROM presencas p
                WHERE p.aluno_id = %s AND YEAR(p.data_presenca) = %s
                """ + where_extra + """
                ORDER BY p.data_presenca
            """, [aluno["id"], ano] + params_extra)
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
        ano_atual=datetime.today().year,
        meses_sel=meses_sel,
        mes_de=mes_de,
        mes_ate=mes_ate,
        atalho=atalho,
        total=total,
        presentes=presentes,
        turmas_do_aluno=turmas_do_aluno,
        turma_filtro_id=turma_filtro_id,
    )


# ======================================================
# ASSOCIAÇÃO — Academias vinculadas à associação do aluno
# ======================================================

@bp_painel_aluno.route("/associacao")
@login_required
@_aluno_required
def associacao(aluno):
    """Exibe as academias da associação à qual o aluno pertence."""
    from utils.contexto_logo import buscar_logo_url

    academias = []
    associacao_nome = None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_academia_aluno = aluno.get("id_academia")
        if not id_academia_aluno:
            cur.close()
            conn.close()
            return render_template(
                "painel_aluno/associacao.html",
                academias=[],
                associacao_nome=None,
                aluno=aluno,
            )

        cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_academia_aluno,))
        row = cur.fetchone()
        id_associacao = row.get("id_associacao") if row else None

        if not id_associacao:
            cur.close()
            conn.close()
            return render_template(
                "painel_aluno/associacao.html",
                academias=[],
                associacao_nome=None,
                aluno=aluno,
            )

        cur.execute("SELECT nome FROM associacoes WHERE id = %s", (id_associacao,))
        assoc = cur.fetchone()
        associacao_nome = assoc.get("nome") if assoc else None

        cur.execute("""
            SELECT id, nome, cidade, uf, email, telefone
            FROM academias
            WHERE id_associacao = %s
            ORDER BY nome
        """, (id_associacao,))
        academias = cur.fetchall()
        for acad in academias:
            acad["logo_url"] = buscar_logo_url("academia", acad["id"])
    except Exception:
        pass
    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/associacao.html",
        academias=academias,
        associacao_nome=associacao_nome,
        aluno=aluno,
    )


# ======================================================
# MEU CURRÍCULO — Currículo do atleta + link Zempo + sync
# ======================================================

@bp_painel_aluno.route("/curriculo", methods=["GET"])
@login_required
def curriculo():
    """Página Meu currículo: dados do cadastro + competições + eventos + link Zempo."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso restrito aos alunos.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT a.*, t.Nome AS turma_nome, ac.nome AS academia_nome
        FROM alunos a
        LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
        LEFT JOIN academias ac ON ac.id = a.id_academia
        WHERE a.usuario_id = %s
    """, (current_user.id,))
    aluno = cur.fetchone()
    if aluno:
        try:
            cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (aluno.get("graduacao_id"),))
            g = cur.fetchone()
            if g:
                aluno["faixa_nome"] = g.get("faixa")
                aluno["graduacao_nome"] = g.get("graduacao")
        except Exception:
            pass
        aluno.setdefault("faixa_nome", None)
        aluno.setdefault("graduacao_nome", None)
        aluno["email_curriculo"] = aluno.get("email") or getattr(current_user, "email", None)
        aluno["telefone_curriculo"] = aluno.get("telefone_celular") or aluno.get("telefone") or ""
        exame = aluno.get("ultimo_exame_faixa")
        if exame and hasattr(exame, "strftime"):
            aluno["ultimo_exame_faixa_formatada"] = exame.strftime("%d/%m/%Y")
        else:
            try:
                aluno["ultimo_exame_faixa_formatada"] = datetime.strptime(str(exame)[:10], "%Y-%m-%d").strftime("%d/%m/%Y") if exame else None
            except (ValueError, TypeError):
                aluno["ultimo_exame_faixa_formatada"] = str(exame) if exame else None
        _build_endereco_completo(aluno)
    if not aluno:
        cur.close()
        conn.close()
        flash("Nenhum aluno vinculado a este usuário.", "warning")
        return redirect(url_for("painel_aluno.painel"))

    competicoes = []
    eventos = []
    try:
        cur.execute("SELECT id, colocacao, competicao, ambito, local_texto, data_competicao, categoria, ordem FROM aluno_competicoes WHERE aluno_id = %s ORDER BY ordem, id", (aluno["id"],))
        competicoes = cur.fetchall()
    except Exception:
        try:
            cur.execute("SELECT id, colocacao, competicao, ambito, local_texto, ordem FROM aluno_competicoes WHERE aluno_id = %s ORDER BY ordem, id", (aluno["id"],))
            competicoes = [{**r, "data_competicao": None, "categoria": None} for r in cur.fetchall()]
        except Exception:
            pass
    try:
        cur.execute("SELECT id, evento, atividade, ambito, local_texto, data_evento, ordem FROM aluno_eventos WHERE aluno_id = %s ORDER BY ordem, id", (aluno["id"],))
        eventos = cur.fetchall()
    except Exception:
        pass

    tipo = (aluno.get("tipo_aluno") or "").strip().lower()
    aluno["classe_categoria"] = {"infantil": "Infantil", "juvenil": "Juvenil", "adulto": "Adulto"}.get(tipo, "")

    aluno["proxima_faixa"] = "—"
    try:
        cur.execute("SELECT id, faixa, graduacao FROM graduacao ORDER BY id")
        faixas = cur.fetchall()
        gid = aluno.get("graduacao_id")
        for i, f in enumerate(faixas):
            if f["id"] == gid and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                aluno["proxima_faixa"] = f"{proxima.get('faixa', '')} {proxima.get('graduacao', '')}".strip() or "—"
                break
    except Exception:
        pass

    aluno["modalidades"] = []
    try:
        cur.execute("SELECT m.id, m.nome FROM modalidade m INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id WHERE am.aluno_id = %s ORDER BY m.nome", (aluno["id"],))
        aluno["modalidades"] = cur.fetchall()
    except Exception:
        pass

    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/curriculo.html",
        aluno=aluno,
        competicoes=competicoes,
        eventos=eventos,
    )


@bp_painel_aluno.route("/curriculo/salvar-link", methods=["POST"])
@login_required
def curriculo_salvar_link():
    """Salva o link Zempo do aluno."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        return jsonify({"ok": False, "msg": "Acesso negado."}), 403
    link = (request.form.get("link_zempo") or (request.get_json(silent=True) or {}).get("link_zempo") or "").strip()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM alunos WHERE usuario_id = %s", (current_user.id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"ok": False, "msg": "Aluno não vinculado."}), 404
    try:
        cur.execute("UPDATE alunos SET link_zempo = %s WHERE id = %s", (link or None, row["id"]))
        conn.commit()
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao salvar: {e}"}), 500
    cur.close()
    conn.close()
    return jsonify({"ok": True, "msg": "Link salvo."})


@bp_painel_aluno.route("/curriculo/sincronizar", methods=["POST"])
@login_required
def curriculo_sincronizar():
    """Sincroniza currículo a partir do Zempo."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel_aluno.curriculo"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, link_zempo FROM alunos WHERE usuario_id = %s", (current_user.id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        flash("Aluno não vinculado.", "warning")
        return redirect(url_for("painel_aluno.curriculo"))
    link = (request.form.get("link_zempo") or row.get("link_zempo") or "").strip()
    if not link:
        flash("Informe o link do seu perfil Zempo.", "warning")
        return redirect(url_for("painel_aluno.curriculo"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE alunos SET link_zempo = %s WHERE id = %s", (link, row["id"]))
    conn.commit()
    cur.close()
    conn.close()

    from blueprints.aluno.zempo_sync import sync_zempo_curriculo
    zempo_user = request.form.get("zempo_user", "").strip()
    zempo_pass = request.form.get("zempo_pass", "").strip()
    ok, msg = sync_zempo_curriculo(row["id"], link, zempo_user=zempo_user or None, zempo_pass=zempo_pass or None)
    if ok:
        flash(msg, "success")
    else:
        flash(msg, "danger")
    return redirect(url_for("painel_aluno.curriculo"))


@bp_painel_aluno.route("/curriculo/impressao")
@login_required
def curriculo_impressao():
    """Página de impressão/PDF do currículo (sem sidebar, layout CV)."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso restrito.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT a.*, t.Nome AS turma_nome, ac.nome AS academia_nome
        FROM alunos a
        LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
        LEFT JOIN academias ac ON ac.id = a.id_academia
        WHERE a.usuario_id = %s
    """, (current_user.id,))
    aluno = cur.fetchone()
    if not aluno:
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.painel"))

    try:
        cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (aluno.get("graduacao_id"),))
        g = cur.fetchone()
        if g:
            aluno["faixa_nome"] = g.get("faixa")
            aluno["graduacao_nome"] = g.get("graduacao")
    except Exception:
        pass
    aluno.setdefault("faixa_nome", None)
    aluno.setdefault("graduacao_nome", None)
    aluno["email_curriculo"] = aluno.get("email") or getattr(current_user, "email", None)
    aluno["telefone_curriculo"] = aluno.get("telefone_celular") or aluno.get("telefone") or ""
    exame = aluno.get("ultimo_exame_faixa")
    if exame and hasattr(exame, "strftime"):
        aluno["ultimo_exame_faixa_formatada"] = exame.strftime("%d/%m/%Y")
    else:
        try:
            aluno["ultimo_exame_faixa_formatada"] = datetime.strptime(str(exame)[:10], "%Y-%m-%d").strftime("%d/%m/%Y") if exame else None
        except (ValueError, TypeError):
            aluno["ultimo_exame_faixa_formatada"] = str(exame) if exame else None
    _build_endereco_completo(aluno)

    tipo = (aluno.get("tipo_aluno") or "").strip().lower()
    aluno["classe_categoria"] = {"infantil": "Infantil", "juvenil": "Juvenil", "adulto": "Adulto"}.get(tipo, "")
    aluno["proxima_faixa"] = "—"
    try:
        cur.execute("SELECT id, faixa, graduacao FROM graduacao ORDER BY id")
        faixas = cur.fetchall()
        gid = aluno.get("graduacao_id")
        for i, f in enumerate(faixas):
            if f["id"] == gid and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                aluno["proxima_faixa"] = f"{proxima.get('faixa', '')} {proxima.get('graduacao', '')}".strip() or "—"
                break
    except Exception:
        pass

    aluno["modalidades"] = []
    try:
        cur.execute("SELECT m.id, m.nome FROM modalidade m INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id WHERE am.aluno_id = %s", (aluno["id"],))
        aluno["modalidades"] = cur.fetchall()
    except Exception:
        pass

    competicoes = []
    eventos = []
    try:
        cur.execute("SELECT id, colocacao, competicao, ambito, local_texto, data_competicao, categoria FROM aluno_competicoes WHERE aluno_id = %s ORDER BY ordem, id", (aluno["id"],))
        competicoes = cur.fetchall()
    except Exception:
        try:
            cur.execute("SELECT id, colocacao, competicao, ambito, local_texto FROM aluno_competicoes WHERE aluno_id = %s ORDER BY ordem, id", (aluno["id"],))
            competicoes = [{**r, "data_competicao": None, "categoria": None} for r in cur.fetchall()]
        except Exception:
            pass
    try:
        cur.execute("SELECT id, evento, atividade, ambito, local_texto, data_evento FROM aluno_eventos WHERE aluno_id = %s ORDER BY ordem, id", (aluno["id"],))
        eventos = cur.fetchall()
    except Exception:
        pass

    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/curriculo_impressao.html",
        aluno=aluno,
        competicoes=competicoes,
        eventos=eventos,
    )


@bp_painel_aluno.route("/curriculo/adicionar-competicao", methods=["POST"])
@login_required
def curriculo_adicionar_competicao():
    """Adiciona competição manualmente."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel_aluno.curriculo"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM alunos WHERE usuario_id = %s", (current_user.id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.curriculo"))

    colocacao = (request.form.get("colocacao") or "").strip() or None
    competicao = (request.form.get("competicao") or "").strip() or None
    ambito = (request.form.get("ambito") or "").strip() or None
    local_texto = (request.form.get("local_texto") or "").strip() or None
    data_s = (request.form.get("data_competicao") or "").strip()
    categoria = (request.form.get("categoria") or "").strip() or None

    if not competicao:
        flash("Informe o nome da competição.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.curriculo"))

    data_parsed = None
    if data_s:
        try:
            from datetime import datetime
            data_parsed = datetime.strptime(data_s, "%Y-%m-%d").date()
        except Exception:
            pass

    try:
        cur.execute("SELECT COALESCE(MAX(ordem), -1) + 1 AS prox FROM aluno_competicoes WHERE aluno_id = %s", (row["id"],))
        prox = cur.fetchone().get("prox", 0)
        cur.execute(
            """INSERT INTO aluno_competicoes (aluno_id, colocacao, competicao, ambito, local_texto, data_competicao, categoria, ordem)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (row["id"], colocacao, competicao, ambito, local_texto, data_parsed, categoria, prox),
        )
        conn.commit()
        flash("Competição adicionada.", "success")
    except Exception as e:
        conn.rollback()
        flash("Erro ao adicionar competição.", "danger")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("painel_aluno.curriculo"))


@bp_painel_aluno.route("/curriculo/adicionar-evento", methods=["POST"])
@login_required
def curriculo_adicionar_evento():
    """Adiciona evento manualmente."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel_aluno.curriculo"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM alunos WHERE usuario_id = %s", (current_user.id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.curriculo"))

    evento = (request.form.get("evento") or "").strip() or None
    atividade = (request.form.get("atividade") or "").strip() or None
    ambito = (request.form.get("ambito") or "").strip() or None
    local_texto = (request.form.get("local_texto") or "").strip() or None
    data_s = (request.form.get("data_evento") or "").strip()

    if not evento:
        flash("Informe o nome do evento.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.curriculo"))

    data_parsed = None
    if data_s:
        try:
            from datetime import datetime
            data_parsed = datetime.strptime(data_s, "%Y-%m-%d").date()
        except Exception:
            pass

    try:
        cur.execute("SELECT COALESCE(MAX(ordem), -1) + 1 AS prox FROM aluno_eventos WHERE aluno_id = %s", (row["id"],))
        prox = cur.fetchone().get("prox", 0)
        cur.execute(
            """INSERT INTO aluno_eventos (aluno_id, evento, atividade, ambito, local_texto, data_evento, ordem)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (row["id"], evento, atividade, ambito, local_texto, data_parsed, prox),
        )
        conn.commit()
        flash("Evento adicionado.", "success")
    except Exception:
        conn.rollback()
        flash("Erro ao adicionar evento.", "danger")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("painel_aluno.curriculo"))


@bp_painel_aluno.route("/curriculo/excluir-competicoes", methods=["POST"])
@login_required
def curriculo_excluir_competicoes():
    """Exclui competições selecionadas."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel_aluno.curriculo"))
    ids = request.form.getlist("ids")
    if not ids:
        flash("Nenhuma competição selecionada.", "warning")
        return redirect(url_for("painel_aluno.curriculo"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM alunos WHERE usuario_id = %s", (current_user.id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.curriculo"))

    placeholders = ",".join(["%s"] * len(ids))
    cur.execute("DELETE FROM aluno_competicoes WHERE aluno_id = %s AND id IN (" + placeholders + ")", (row["id"],) + tuple(int(x) for x in ids if x.isdigit()))
    conn.commit()
    cur.close()
    conn.close()
    flash("Competição(ões) excluída(s).", "success")
    return redirect(url_for("painel_aluno.curriculo"))


@bp_painel_aluno.route("/curriculo/excluir-eventos", methods=["POST"])
@login_required
def curriculo_excluir_eventos():
    """Exclui eventos selecionados."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel_aluno.curriculo"))
    ids = request.form.getlist("ids")
    if not ids:
        flash("Nenhum evento selecionado.", "warning")
        return redirect(url_for("painel_aluno.curriculo"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM alunos WHERE usuario_id = %s", (current_user.id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.curriculo"))

    placeholders = ",".join(["%s"] * len(ids))
    cur.execute("DELETE FROM aluno_eventos WHERE aluno_id = %s AND id IN (" + placeholders + ")", (row["id"],) + tuple(int(x) for x in ids if x.isdigit()))
    conn.commit()
    cur.close()
    conn.close()
    flash("Evento(s) excluído(s).", "success")
    return redirect(url_for("painel_aluno.curriculo"))
