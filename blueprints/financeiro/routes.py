# ======================================================
# Blueprint: Financeiro (mensalidades, receitas, despesas, descontos)
# ======================================================
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_required, current_user
from datetime import date
from decimal import Decimal, InvalidOperation
from config import get_db_connection

bp_financeiro = Blueprint("financeiro", __name__, url_prefix="/financeiro")

COMPROVANTE_EXT = {"png", "jpg", "jpeg", "gif", "pdf"}


def _status_efetivo(status, data_venc, status_pagamento=None):
    """Retorna status efetivo: pendente_aprovacao -> aguardando_confirmacao, pendente vencido -> atrasado."""
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


def _valor_com_desconto(ma, aluno_id, id_academia, hoje=None):
    """Retorna (valor_integral, valor_desconto, valor_final, desconto_nome) para exibição.
    desconto_nome: nome do desconto (ex. 'Família'). Vazio se sem desconto."""
    hoje = hoje or date.today()
    valor_base = float(ma.get("valor") or 0)
    valor_original = float(ma.get("valor_original") or 0) or valor_base
    desconto_aplicado = float(ma.get("desconto_aplicado") or 0)
    id_acad = ma.get("id_academia") or id_academia
    desconto_nome = ""
    if desconto_aplicado > 0:
        id_desc = ma.get("id_desconto")
        if id_desc:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute("SELECT nome FROM descontos WHERE id = %s", (id_desc,))
                d = cur.fetchone()
                if d and d.get("nome"):
                    desconto_nome = str(d["nome"]).strip()
            except Exception:
                pass
            conn.close()
        return valor_original, desconto_aplicado, valor_base, desconto_nome
    try:
        venc = ma.get("data_vencimento")
        data_vigencia = venc if isinstance(venc, date) else (date.fromisoformat(str(venc)[:10]) if venc else hoje)
    except Exception:
        data_vigencia = hoje
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT d.nome, d.tipo, d.valor, COALESCE(d.aplicar_apenas_pagamento_em_dia, 1) AS aplicar_apenas_pagamento_em_dia
            FROM aluno_desconto ad
            JOIN descontos d ON d.id = ad.desconto_id AND d.ativo = 1
            WHERE ad.aluno_id = %s AND ad.ativo = 1
            AND (ad.data_inicio IS NULL OR ad.data_inicio <= %s)
            AND (ad.data_fim IS NULL OR ad.data_fim >= %s)
            AND d.id_academia = %s
            LIMIT 1
        """, (aluno_id, data_vigencia, data_vigencia, id_acad or id_academia))
        d = cur.fetchone()
    except Exception:
        d = None
    conn.close()
    if not d:
        return valor_base, 0, valor_base, ""
    desconto_nome = str(d.get("nome") or "").strip()
    atrasado = False
    try:
        venc = ma.get("data_vencimento")
        venc = venc if isinstance(venc, date) else (date.fromisoformat(str(venc)[:10]) if venc else None)
        atrasado = venc and venc < hoje
    except Exception:
        pass
    if d.get("aplicar_apenas_pagamento_em_dia") and atrasado:
        return valor_base, 0, valor_base
    tipo = d.get("tipo") or "percentual"
    val_desc = float(d.get("valor") or 0)
    if tipo == "percentual":
        desconto = valor_base * (val_desc / 100)
    else:
        desconto = min(val_desc, valor_base)
    return valor_base, round(desconto, 2), round(valor_base - desconto, 2), desconto_nome


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
    """Retorna IDs de academias acessíveis pelo usuário (prioridade: usuarios_academias)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ids = []
    try:
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas:
            conn.close()
            return vinculadas
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
    except Exception:
        pass
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

    mes_arg = request.args.get("mes")
    mes = int(mes_arg) if (mes_arg and str(mes_arg).isdigit() and 1 <= int(mes_arg) <= 12) else (date.today().month if "mes" not in request.args else None)
    ano = request.args.get("ano", type=int) or date.today().year
    if ano < 2000 or ano > 2100:
        ano = date.today().year

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
        ac = cur.fetchone()
        academia_nome = ac["nome"] if ac else None
    except Exception:
        academia_nome = None

    receitas_mes = despesas_mes = 0.0
    if mes:
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
    else:
        try:
            cur.execute(
                "SELECT COALESCE(SUM(valor), 0) as total FROM receitas WHERE id_academia = %s AND YEAR(data) = %s",
                (academia_id, ano),
            )
            receitas_mes = float(cur.fetchone().get("total") or 0)
        except Exception:
            pass
        try:
            cur.execute(
                "SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE id_academia = %s AND YEAR(data) = %s",
                (academia_id, ano),
            )
            despesas_mes = float(cur.fetchone().get("total") or 0)
        except Exception:
            pass

    # Mensalidades: via mensalidades.id_academia ou alunos.id_academia (fallback)
    msg_geradas = msg_pagas = msg_pendentes = msg_atrasadas = 0
    projecao = 0.0
    hoje = date.today()
    rows = []
    has_mes = mes and 1 <= mes <= 12
    mes_ano_clause = "AND MONTH(ma.data_vencimento) = %s AND YEAR(ma.data_vencimento) = %s" if has_mes else "AND YEAR(ma.data_vencimento) = %s"
    mes_ano_params = (mes, ano) if has_mes else (ano,)
    for q in [
        (f"""
            SELECT ma.status, ma.status_pagamento, ma.valor, ma.data_vencimento
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE (m.id_academia = %s OR (m.id_academia IS NULL AND a.id_academia = %s))
            {mes_ano_clause}
            AND ma.status != 'cancelado'
        """, (academia_id, academia_id) + mes_ano_params),
        (f"""
            SELECT ma.status, ma.valor, ma.data_vencimento
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            WHERE m.id_academia = %s
            {mes_ano_clause}
            AND ma.status != 'cancelado'
        """, (academia_id,) + mes_ano_params),
        (f"""
            SELECT ma.status, ma.valor, ma.data_vencimento
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE a.id_academia = %s
            {mes_ano_clause}
            AND ma.status != 'cancelado'
        """, (academia_id,) + mes_ano_params),
    ]:
        try:
            cur.execute(q[0], q[1])
            rows = cur.fetchall()
            for r in rows:
                r.setdefault("status_pagamento", None)
            break
        except Exception:
            continue
    for r in rows:
        msg_geradas += 1
        val = float(r.get("valor") or 0)
        st = (r.get("status") or "").lower()
        st_pag = (r.get("status_pagamento") or "").lower()
        if st == "pago" or st_pag == "pago":
            msg_pagas += 1
        elif st == "atrasado":
            msg_atrasadas += 1
            projecao += val
        elif st == "pendente":
            venc = r.get("data_vencimento")
            try:
                v = venc if isinstance(venc, date) else (date.fromisoformat(str(venc)[:10]) if venc else None)
                if v and v < hoje:
                    msg_atrasadas += 1
                    projecao += val
                else:
                    msg_pendentes += 1
                    projecao += val
            except Exception:
                msg_pendentes += 1
                projecao += val

    conn.close()

    return render_template(
        "financeiro/dashboard.html",
        academia_nome=academia_nome,
        receitas_mes=receitas_mes,
        despesas_mes=despesas_mes,
        academia_id=academia_id,
        mes=mes,
        ano=ano,
        ano_atual=date.today().year,
        msg_geradas=msg_geradas,
        msg_pagas=msg_pagas,
        msg_pendentes=msg_pendentes,
        msg_atrasadas=msg_atrasadas,
        projecao=round(projecao, 2),
    )


@bp_financeiro.route("/descontos")
@login_required
def lista_descontos():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome, tipo, valor, COALESCE(aplicar_apenas_pagamento_em_dia, 1) AS aplicar_apenas_pagamento_em_dia FROM descontos WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    except Exception:
        cur.execute(
            "SELECT id, nome, tipo, valor FROM descontos WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    descontos = cur.fetchall()
    conn.close()
    return render_template(
        "financeiro/descontos/lista_descontos.html",
        descontos=descontos,
        academia_id=academia_id,
    )


@bp_financeiro.route("/descontos/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar_desconto():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        tipo = request.form.get("tipo") or "percentual"
        valor_str = request.form.get("valor") or ""
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aplicar_apenas = 1 if "1" in request.form.getlist("aplicar_apenas_pagamento_em_dia") else 0

        if not nome:
            flash("Informe o nome do desconto.", "danger")
            return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)
        valor = _parse_valor(valor_str)
        if valor is None or valor < 0:
            flash("Informe um valor válido.", "danger")
            return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)
        if tipo == "percentual" and (valor > 100 or valor < 0):
            flash("Percentual deve estar entre 0 e 100.", "danger")
            return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """INSERT INTO descontos (nome, descricao, tipo, valor, id_academia, ativo, aplicar_apenas_pagamento_em_dia)
                       VALUES (%s, %s, %s, %s, %s, 1, %s)""",
                    (nome, descricao, tipo, valor, id_acad, aplicar_apenas),
                )
            except Exception as col_err:
                if "aplicar_apenas_pagamento_em_dia" in str(col_err) or "Unknown column" in str(col_err):
                    cur.execute(
                        "INSERT INTO descontos (nome, descricao, tipo, valor, id_academia, ativo) VALUES (%s, %s, %s, %s, %s, 1)",
                        (nome, descricao, tipo, valor, id_acad),
                    )
                else:
                    raise
            conn.commit()
            conn.close()
            flash("Desconto cadastrado com sucesso.", "success")
            return redirect(url_for("financeiro.lista_descontos", academia_id=academia_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Erro ao salvar desconto: {e}", "danger")
            return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)

    return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)


@bp_financeiro.route("/descontos/editar/<int:desconto_id>", methods=["GET", "POST"])
@login_required
def editar_desconto(desconto_id):
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(
            f"SELECT id, nome, descricao, tipo, valor, id_academia, ativo, COALESCE(aplicar_apenas_pagamento_em_dia, 1) AS aplicar_apenas_pagamento_em_dia FROM descontos WHERE id = %s AND id_academia IN ({ph})",
            (desconto_id,) + tuple(ids),
        )
    except Exception:
        cur.execute(
            f"SELECT id, nome, descricao, tipo, valor, id_academia, ativo FROM descontos WHERE id = %s AND id_academia IN ({ph})",
            (desconto_id,) + tuple(ids),
        )
    desconto = cur.fetchone()
    if desconto and "aplicar_apenas_pagamento_em_dia" not in desconto:
        desconto["aplicar_apenas_pagamento_em_dia"] = 1
    conn.close()

    if not desconto:
        flash("Desconto não encontrado.", "warning")
        return redirect(url_for("financeiro.lista_descontos"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        tipo = request.form.get("tipo") or "percentual"
        valor_str = request.form.get("valor") or ""
        id_acad = request.form.get("id_academia", type=int) or desconto.get("id_academia") or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aplicar_apenas = 1 if "1" in request.form.getlist("aplicar_apenas_pagamento_em_dia") else 0
        ativo = 1 if "1" in request.form.getlist("ativo") else 0

        if not nome:
            flash("Informe o nome do desconto.", "danger")
            desconto["nome"] = request.form.get("nome")
            desconto["descricao"] = request.form.get("descricao")
            desconto["tipo"] = tipo
            desconto["valor"] = valor_str
            return render_template("financeiro/descontos/editar_desconto.html", desconto=desconto, academias=academias, academia_id=academia_id)
        valor = _parse_valor(valor_str)
        if valor is None or valor < 0:
            flash("Informe um valor válido.", "danger")
            desconto["nome"] = nome
            desconto["descricao"] = descricao
            desconto["tipo"] = tipo
            desconto["valor"] = valor_str
            return render_template("financeiro/descontos/editar_desconto.html", desconto=desconto, academias=academias, academia_id=academia_id)
        if tipo == "percentual" and (valor > 100 or valor < 0):
            flash("Percentual deve estar entre 0 e 100.", "danger")
            return render_template("financeiro/descontos/editar_desconto.html", desconto=desconto, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """UPDATE descontos SET nome=%s, descricao=%s, tipo=%s, valor=%s, id_academia=%s, ativo=%s, aplicar_apenas_pagamento_em_dia=%s
                       WHERE id=%s""",
                    (nome, descricao, tipo, valor, id_acad, ativo, aplicar_apenas, desconto_id),
                )
            except Exception as col_err:
                if "aplicar_apenas_pagamento_em_dia" in str(col_err) or "Unknown column" in str(col_err):
                    cur.execute(
                        "UPDATE descontos SET nome=%s, descricao=%s, tipo=%s, valor=%s, id_academia=%s, ativo=%s WHERE id=%s",
                        (nome, descricao, tipo, valor, id_acad, ativo, desconto_id),
                    )
                else:
                    raise
            conn.commit()
            conn.close()
            flash("Desconto atualizado.", "success")
            return redirect(url_for("financeiro.lista_descontos", academia_id=academia_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Erro ao atualizar: {e}", "danger")

    return render_template("financeiro/descontos/editar_desconto.html", desconto=desconto, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/mensalidades")
@login_required
def painel_mensalidades():
    """Hub do módulo Mensalidades: Cadastro, Mensalidades alunos, Gerar cobrança."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    return render_template(
        "financeiro/mensalidades/painel_mensalidades.html",
        academias=academias,
        academia_id=academia_id,
    )


@bp_financeiro.route("/mensalidades/planos")
@login_required
def lista_planos_mensalidades():
    """Lista planos de mensalidade (cadastro)."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome, valor, COALESCE(aplicar_juros_multas, 0) AS aplicar_juros_multas FROM mensalidades WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    except Exception:
        cur.execute(
            "SELECT id, nome, valor FROM mensalidades WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    mensalidades = cur.fetchall()
    conn.close()
    return render_template(
        "financeiro/mensalidades/lista_planos_mensalidades.html",
        mensalidades=mensalidades,
        academia_id=academia_id,
    )


def _atualizar_status_atrasadas(academia_id):
    """Atualiza mensalidades pendentes vencidas para atrasado."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id SET ma.status = 'atrasado' WHERE m.id_academia = %s AND ma.status = 'pendente' AND ma.data_vencimento < CURDATE()",
            (academia_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


@bp_financeiro.route("/mensalidades/alunos")
@login_required
def mensalidades_alunos():
    """Mensalidades e cobranças avulsas por aluno com dashboard, filtros e confirmação."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    _atualizar_status_atrasadas(academia_id)

    mes_arg = request.args.get("mes", type=int)
    mes = mes_arg if (mes_arg and 1 <= mes_arg <= 12) else date.today().month
    ano_arg = request.args.get("ano", type=int)
    ano = ano_arg if (ano_arg and 2000 <= ano_arg <= 2100) else date.today().year
    busca = (request.args.get("busca") or "").strip()
    filtro_status = (request.args.get("status") or "").strip().lower()
    if filtro_status not in ("pago", "pendente", "atrasado", "aguardando_confirmacao"):
        filtro_status = None
    academias = _get_academias_for_select()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    hoje = date.today()
    where_ma = ["m.id_academia = %s", "ma.status != 'cancelado'"]
    where_ma.append("EXISTS (SELECT 1 FROM aluno_turmas at WHERE at.aluno_id = a.id)")
    params_ma = [academia_id]
    if mes and 1 <= mes <= 12:
        where_ma.append("MONTH(ma.data_vencimento) = %s")
        params_ma.append(mes)
    if ano:
        where_ma.append("YEAR(ma.data_vencimento) = %s")
        params_ma.append(ano)
    if busca:
        where_ma.append("a.nome LIKE %s")
        params_ma.append(f"%{busca}%")

    try:
        cur.execute(f"""
            SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                   ma.status_pagamento, ma.comprovante_url, ma.observacoes,
                   ma.valor_original, ma.desconto_aplicado, ma.id_desconto, ma.turma_id,
                   m.nome as plano_nome, m.id_academia, a.id as aluno_id, a.nome as aluno_nome, a.foto as aluno_foto,
                   t.Nome as turma_nome
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            LEFT JOIN turmas t ON t.TurmaID = ma.turma_id
            WHERE {' AND '.join(where_ma)}
            ORDER BY ma.data_vencimento DESC
            LIMIT 200
        """, params_ma)
        rows = cur.fetchall()
    except Exception:
        try:
            where_fb = ["m.id_academia = %s", "ma.status != 'cancelado'", "EXISTS (SELECT 1 FROM aluno_turmas at WHERE at.aluno_id = a.id)"]
            if mes and 1 <= mes <= 12:
                where_fb.append("MONTH(ma.data_vencimento) = %s")
            if ano:
                where_fb.append("YEAR(ma.data_vencimento) = %s")
            if busca:
                where_fb.append("a.nome LIKE %s")
            params_fb = [academia_id]
            if mes and 1 <= mes <= 12:
                params_fb.append(mes)
            if ano:
                params_fb.append(ano)
            if busca:
                params_fb.append(f"%{busca}%")
            cur.execute(f"""
                SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                       ma.status_pagamento, ma.comprovante_url, ma.observacoes,
                       m.nome as plano_nome, m.id_academia, a.id as aluno_id, a.nome as aluno_nome, a.foto as aluno_foto
                FROM mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                JOIN alunos a ON a.id = ma.aluno_id
                WHERE {' AND '.join(where_fb)}
                ORDER BY ma.data_vencimento DESC
                LIMIT 200
            """, params_fb)
            rows = cur.fetchall()
            for r in rows:
                r.setdefault("status_pagamento", None)
                r.setdefault("comprovante_url", None)
                r.setdefault("observacoes", None)
                r.setdefault("valor_original", None)
                r.setdefault("desconto_aplicado", 0)
                r.setdefault("id_desconto", None)
                r.setdefault("turma_id", None)
                r.setdefault("turma_nome", None)
        except Exception:
            rows = []

    mensalidades = []
    for ma in rows:
        ma["status_efetivo"] = _status_efetivo(ma.get("status"), ma.get("data_vencimento"), ma.get("status_pagamento"))
        ma["comentario_informado"] = ma.get("comentario_informado") or ma.get("observacoes")
        vi, vd, vf, desconto_nome = _valor_com_desconto(ma, ma.get("aluno_id"), academia_id, hoje)
        ma["valor_integral"] = vi
        ma["valor_desconto"] = vd
        ma["valor_final"] = vf
        ma["desconto_nome"] = desconto_nome
        ma["tem_desconto"] = vd > 0
        if not filtro_status or ma.get("status_efetivo") == filtro_status:
            mensalidades.append(ma)

    try:
        cur.execute(f"""
            SELECT ma.id, ma.status, ma.status_pagamento, ma.data_vencimento, m.id_academia, a.id as aluno_id
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE {' AND '.join(where_ma)}
        """, params_ma)
        all_ma = cur.fetchall()
    except Exception:
        try:
            cur.execute(f"""
                SELECT ma.id, ma.status, ma.status_pagamento, ma.data_vencimento, m.id_academia, a.id as aluno_id
                FROM mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                JOIN alunos a ON a.id = ma.aluno_id
                WHERE m.id_academia = %s AND ma.status != 'cancelado'
                  AND EXISTS (SELECT 1 FROM aluno_turmas at WHERE at.aluno_id = a.id)
            """, (academia_id,))
            all_ma = cur.fetchall()
        except Exception:
            all_ma = []
    contagens = {"pago": 0, "pendente": 0, "atrasado": 0, "aguardando_confirmacao": 0}
    for r in all_ma:
        if r.get("status_pagamento") == "pendente_aprovacao":
            contagens["aguardando_confirmacao"] = contagens.get("aguardando_confirmacao", 0) + 1
        elif r.get("status") == "pago":
            contagens["pago"] = contagens.get("pago", 0) + 1
        else:
            s = r.get("status")
            if s == "pendente":
                try:
                    venc = r.get("data_vencimento")
                    venc = venc if isinstance(venc, date) else date.fromisoformat(str(venc)[:10]) if venc else None
                    if venc and venc < hoje:
                        s = "atrasado"
                except Exception:
                    pass
            contagens[s] = contagens.get(s, 0) + 1

    avulsas = []
    try:
        where_av = ["id_academia = %s", "status != 'cancelado'", "EXISTS (SELECT 1 FROM aluno_turmas at WHERE at.aluno_id = cobranca_avulsa.aluno_id)"]
        params_av = [academia_id]
        if mes and 1 <= mes <= 12:
            where_av.append("MONTH(data_vencimento) = %s")
            params_av.append(mes)
        if ano:
            where_av.append("YEAR(data_vencimento) = %s")
            params_av.append(ano)
        if busca:
            try:
                cur.execute("SELECT id FROM alunos WHERE nome LIKE %s AND id_academia = %s", (f"%{busca}%", academia_id))
            except Exception:
                cur.execute("SELECT id FROM alunos WHERE nome LIKE %s", (f"%{busca}%",))
            ids_busca = [x["id"] for x in cur.fetchall()]
            if ids_busca:
                ph = ",".join(["%s"] * len(ids_busca))
                where_av.append(f"aluno_id IN ({ph})")
                params_av.extend(ids_busca)
            else:
                where_av.append("1=0")
        cur.execute(f"""
            SELECT id, descricao, valor, data_vencimento, data_pagamento, valor_pago, status, aluno_id
            FROM cobranca_avulsa WHERE {' AND '.join(where_av)}
            ORDER BY data_vencimento DESC
            LIMIT 200
        """, params_av)
        avulsas = cur.fetchall()
        for av in avulsas:
            cur.execute("SELECT nome, foto FROM alunos WHERE id = %s", (av["aluno_id"],))
            r = cur.fetchone()
            av["aluno_nome"] = r.get("nome", "-") if r else "-"
            av["aluno_foto"] = r.get("foto") if r else None
        if filtro_status and filtro_status != "aguardando_confirmacao":
            avulsas = [a for a in avulsas if (a.get("status") or "").lower() == filtro_status]
        elif filtro_status == "aguardando_confirmacao":
            avulsas = []
    except Exception:
        pass
    conn.close()

    return render_template(
        "financeiro/mensalidades/mensalidades_alunos.html",
        academia_id=academia_id,
        academias=academias,
        mensalidades=mensalidades,
        avulsas=avulsas,
        contagens=contagens,
        mes=mes,
        ano=ano,
        busca=busca,
        filtro_status=filtro_status,
        ano_atual=date.today().year,
    )


@bp_financeiro.route("/mensalidades/buscar-alunos")
@login_required
def buscar_alunos_mensalidades():
    """Busca alunos da academia para aplicar desconto."""
    acad_id = request.args.get("academia_id", type=int) or _get_academia_id()
    busca = (request.args.get("busca") or "").strip()[:100]
    ids = _get_academias_ids()
    if not acad_id or acad_id not in ids:
        return jsonify([])
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if busca:
            cur.execute(
                "SELECT id, nome, foto FROM alunos WHERE id_academia = %s AND ativo = 1 AND nome LIKE %s ORDER BY nome LIMIT 50",
                (acad_id, f"%{busca}%"),
            )
        else:
            cur.execute(
                "SELECT id, nome, foto FROM alunos WHERE id_academia = %s AND ativo = 1 ORDER BY nome LIMIT 30",
                (acad_id,),
            )
        rows = cur.fetchall()
        for r in rows:
            r["foto_url"] = url_for("static", filename="uploads/" + r["foto"]) if r.get("foto") else None
    except Exception:
        try:
            cur.execute(
                "SELECT a.id, a.nome, a.foto FROM alunos a WHERE a.id_academia = %s AND a.ativo = 1 ORDER BY a.nome LIMIT 30",
                (acad_id,),
            )
            rows = cur.fetchall()
            for r in rows:
                r["foto_url"] = url_for("static", filename="uploads/" + r["foto"]) if r.get("foto") else None
        except Exception:
            rows = []
    conn.close()
    return jsonify(rows)


@bp_financeiro.route("/mensalidades/alunos-por-academia/<int:acad_id>")
@login_required
def alunos_por_academia(acad_id):
    """Retorna alunos da academia (JSON). Se turma_id for passado, só alunos matriculados na turma."""
    ids = _get_academias_ids()
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        ids = []
    if not ids or acad_id not in ids:
        return jsonify([])
    turma_id = request.args.get("turma_id", type=int)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    rows = []
    try:
        if turma_id:
            try:
                cur.execute(
                    """SELECT DISTINCT a.id, a.nome FROM alunos a
                       LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                       WHERE (at.TurmaID IS NOT NULL OR a.TurmaID = %s)
                       AND a.id_academia = %s
                       AND NOT EXISTS (
                         SELECT 1 FROM mensalidade_aluno ma2
                         WHERE ma2.aluno_id = a.id AND ma2.turma_id = %s AND ma2.status != 'cancelado'
                       )
                       ORDER BY a.nome""",
                    (turma_id, turma_id, acad_id, turma_id),
                )
                rows = cur.fetchall()
            except Exception:
                try:
                    cur.execute(
                        """SELECT DISTINCT a.id, a.nome FROM alunos a
                           LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                           WHERE (at.TurmaID IS NOT NULL OR a.TurmaID = %s)
                           AND a.id_academia = %s
                           ORDER BY a.nome""",
                        (turma_id, turma_id, acad_id),
                    )
                    rows = cur.fetchall()
                except Exception:
                    pass
        else:
            try:
                cur.execute(
                    "SELECT id, nome FROM alunos WHERE id_academia = %s ORDER BY nome",
                    (acad_id,),
                )
                rows = cur.fetchall()
            except Exception:
                try:
                    cur.execute(
                        "SELECT a.id, a.nome FROM alunos a WHERE a.id_academia = %s ORDER BY a.nome",
                        (acad_id,),
                    )
                    rows = cur.fetchall()
                except Exception:
                    rows = []
    except Exception:
        rows = []
    conn.close()
    return jsonify(rows)


@bp_financeiro.route("/mensalidades/gerar-cobranca", methods=["GET", "POST"])
@login_required
def gerar_cobranca():
    """Gerar cobrança avulsa ou mensalidade para aluno(s)."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()

    if request.method == "POST":
        tipo = request.form.get("tipo") or "avulso"
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aluno_ids_raw = request.form.getlist("aluno_id")
        if not aluno_ids_raw:
            aluno_ids_raw = [request.form.get("aluno_id")] if request.form.get("aluno_id") else []
        aluno_ids = [int(x) for x in aluno_ids_raw if x and str(x).isdigit()]

        if not aluno_ids:
            flash("Selecione ao menos um aluno.", "danger")
            return _render_gerar_cobranca(academias, academia_id, id_acad)

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            if tipo == "avulso":
                if len(aluno_ids) > 1:
                    flash("Para cobrança avulsa, selecione apenas um aluno.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad)
                data_venc = request.form.get("data_vencimento", "").strip()
                if not data_venc:
                    flash("Informe a data de vencimento.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad)
                descricao = (request.form.get("descricao") or "").strip() or "Cobrança avulsa"
                valor_str = request.form.get("valor") or ""
                valor = _parse_valor(valor_str)
                if valor is None or valor < 0:
                    flash("Informe um valor válido.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad)
                try:
                    cur.execute(
                        """INSERT INTO cobranca_avulsa (aluno_id, id_academia, descricao, valor, data_vencimento, status, criado_por)
                           VALUES (%s, %s, %s, %s, %s, 'pendente', %s)""",
                        (aluno_ids[0], id_acad, descricao, valor, data_venc, current_user.id),
                    )
                except Exception:
                    cur.execute(
                        "INSERT INTO cobranca_avulsa (aluno_id, id_academia, descricao, valor, data_vencimento, status) VALUES (%s, %s, %s, %s, %s, 'pendente')",
                        (aluno_ids[0], id_acad, descricao, valor, data_venc),
                    )
                conn.commit()
                flash("Cobrança avulsa gerada.", "success")
                return redirect(url_for("financeiro.gerar_cobranca", academia_id=id_acad))
            else:
                plano_id = request.form.get("mensalidade_id", type=int)
                turma_id = request.form.get("turma_id", type=int)
                ano_ref = request.form.get("ano_ref", type=int) or date.today().year
                mes_inicial = request.form.get("mes_inicial", type=int) or 1
                dia_venc = min(28, max(1, request.form.get("dia_vencimento", type=int) or 10))
                if not plano_id:
                    flash("Selecione o plano de mensalidade.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad)
                if not turma_id:
                    flash("Selecione a turma.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad)
                cur.execute("SELECT id, nome, valor FROM mensalidades WHERE id = %s AND id_academia = %s", (plano_id, id_acad))
                plano = cur.fetchone()
                if not plano:
                    flash("Plano de mensalidade não encontrado.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad)
                cur.execute("SELECT TurmaID FROM turmas WHERE TurmaID = %s AND id_academia = %s", (turma_id, id_acad))
                if not cur.fetchone():
                    flash("Turma não encontrada.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad)
                valor_plano = float(plano[2] if isinstance(plano, (list, tuple)) else plano.get("valor", 0))
                dias_por_mes = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
                geradas = 0
                for mes in range(mes_inicial, 13):
                    dia = min(dia_venc, dias_por_mes.get(mes, 28))
                    data_venc = f"{ano_ref}-{mes:02d}-{dia:02d}"
                    for aid in aluno_ids:
                        try:
                            cur.execute(
                                """SELECT 1 FROM mensalidade_aluno
                                   WHERE aluno_id = %s AND turma_id = %s AND mensalidade_id = %s
                                   AND data_vencimento = %s AND status != 'cancelado'""",
                                (aid, turma_id, plano_id, data_venc),
                            )
                            if cur.fetchone():
                                continue
                            cur.execute(
                                """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, turma_id, data_vencimento, valor, status)
                                   VALUES (%s, %s, %s, %s, %s, 'pendente')""",
                                (plano_id, aid, turma_id, data_venc, valor_plano),
                            )
                            geradas += 1
                        except Exception:
                            try:
                                cur.execute(
                                    """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, data_vencimento, valor, status)
                                       VALUES (%s, %s, %s, %s, 'pendente')""",
                                    (plano_id, aid, data_venc, valor_plano),
                                )
                                geradas += 1
                            except Exception:
                                pass
                conn.commit()
                flash(f"{geradas} cobrança(s) gerada(s) do mês {mes_inicial} até dezembro.", "success")
                return redirect(url_for("financeiro.gerar_cobranca", academia_id=id_acad))
        except Exception as e:
            conn.rollback()
            flash(f"Erro ao gerar cobrança: {e}", "danger")
        conn.close()
        return redirect(url_for("financeiro.gerar_cobranca", academia_id=academia_id))

    academia_sel = request.args.get("academia_id", type=int) or academia_id
    if academia_sel not in ids:
        academia_sel = academia_id
    return _render_gerar_cobranca(academias, academia_id, academia_sel)


@bp_financeiro.route("/mensalidades/aplicar-desconto", methods=["GET", "POST"])
@login_required
def aplicar_desconto():
    """Aplicar desconto ao aluno com vigência; se 100% marca mensalidades como pagas."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    if academia_id not in ids:
        academia_id = ids[0] if ids else None

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome, tipo, valor FROM descontos WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    except Exception:
        cur.execute(
            "SELECT id, nome, tipo, valor FROM descontos WHERE id_academia = %s ORDER BY nome",
            (academia_id,),
        )
    descontos = cur.fetchall()

    if request.method == "POST":
        acao = request.form.get("acao")
        if acao == "cancelar":
            aluno_id = request.form.get("aluno_id", type=int)
            desconto_id = request.form.get("desconto_id", type=int)
            ad_id = request.form.get("aluno_desconto_id", type=int)
            if not aluno_id or not desconto_id:
                flash("Parâmetros inválidos.", "danger")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            try:
                cur.execute(
                    "UPDATE aluno_desconto SET ativo = 0 WHERE aluno_id = %s AND desconto_id = %s",
                    (aluno_id, desconto_id),
                )
                try:
                    cur.execute(
                        """SELECT ma.id, ma.valor_original, ma.desconto_aplicado, ma.status, ma.valor
                           FROM mensalidade_aluno ma
                           JOIN mensalidades m ON m.id = ma.mensalidade_id
                           WHERE ma.aluno_id = %s AND ma.id_desconto = %s AND ma.status != 'cancelado'""",
                        (aluno_id, desconto_id),
                    )
                except Exception:
                    rows = []
                else:
                    rows = cur.fetchall()
                for r in rows:
                    desconto_100 = (float(r.get("valor") or 0) == 0 and float(r.get("desconto_aplicado") or 0) > 0)
                    valor_orig = float(r.get("valor_original") or 0)
                    if valor_orig <= 0:
                        valor_orig = float(r.get("valor") or 0) + float(r.get("desconto_aplicado") or 0)
                    if valor_orig <= 0:
                        cur.execute("SELECT m.valor FROM mensalidades m JOIN mensalidade_aluno ma ON ma.mensalidade_id = m.id WHERE ma.id = %s", (r["id"],))
                        v = cur.fetchone()
                        valor_orig = float(v.get("valor", 0) or 0) if v else 0
                    try:
                        if desconto_100 and (r.get("status") or "").lower() == "pago":
                            cur.execute(
                                """UPDATE mensalidade_aluno SET valor = %s, valor_original = NULL, desconto_aplicado = 0, id_desconto = NULL, status = 'pendente', data_pagamento = NULL
                                   WHERE id = %s""",
                                (valor_orig, r["id"]),
                            )
                        else:
                            cur.execute(
                                """UPDATE mensalidade_aluno SET valor = %s, valor_original = NULL, desconto_aplicado = 0, id_desconto = NULL WHERE id = %s""",
                                (valor_orig, r["id"]),
                            )
                    except Exception:
                        try:
                            cur.execute("UPDATE mensalidade_aluno SET valor = %s, status = 'pendente', data_pagamento = NULL WHERE id = %s", (valor_orig, r["id"]))
                        except Exception:
                            cur.execute("UPDATE mensalidade_aluno SET valor = %s WHERE id = %s", (valor_orig, r["id"]))
                conn.commit()
                flash("Desconto cancelado. Mensalidades revertidas.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Erro ao cancelar: {e}", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        if acao == "editar":
            ad_id = request.form.get("aluno_desconto_id", type=int)
            aluno_id = request.form.get("aluno_id", type=int)
            desconto_atual = request.form.get("desconto_id", type=int)
            novo_desconto_id = request.form.get("novo_desconto_id", type=int)
            data_inicio = (request.form.get("data_inicio") or "").strip()
            data_fim = (request.form.get("data_fim") or "").strip()
            if not ad_id or not aluno_id or not novo_desconto_id:
                flash("Parâmetros inválidos.", "danger")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            cur.execute(
                "SELECT ad.id, ad.desconto_id FROM aluno_desconto ad JOIN descontos d ON d.id = ad.desconto_id WHERE ad.id = %s AND d.id_academia = %s AND ad.ativo = 1",
                (ad_id, academia_id),
            )
            ad_row = cur.fetchone()
            if not ad_row:
                flash("Vínculo não encontrado.", "warning")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            desconto_atual = ad_row.get("desconto_id") or desconto_atual
            cur.execute(
                "SELECT id FROM descontos WHERE id = %s AND id_academia = %s",
                (novo_desconto_id, academia_id),
            )
            if not cur.fetchone():
                flash("Desconto não encontrado.", "danger")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            try:
                dt_ini = date.fromisoformat(data_inicio) if data_inicio else date.today()
                dt_fim = date.fromisoformat(data_fim) if data_fim else date(2099, 12, 31)
            except Exception:
                dt_ini = date.today()
                dt_fim = date(2099, 12, 31)
            try:
                if novo_desconto_id == desconto_atual:
                    cur.execute(
                        "UPDATE aluno_desconto SET data_inicio = %s, data_fim = %s WHERE id = %s AND aluno_id = %s",
                        (dt_ini, dt_fim, ad_id, aluno_id),
                    )
                else:
                    cur.execute(
                        "SELECT id FROM aluno_desconto WHERE aluno_id = %s AND desconto_id = %s AND ativo = 1",
                        (aluno_id, novo_desconto_id),
                    )
                    existente = cur.fetchone()
                    if existente and existente.get("id") != ad_id:
                        cur.execute(
                            "UPDATE aluno_desconto SET data_inicio = %s, data_fim = %s WHERE id = %s",
                            (dt_ini, dt_fim, existente["id"]),
                        )
                        cur.execute("UPDATE aluno_desconto SET ativo = 0 WHERE id = %s", (ad_id,))
                    else:
                        cur.execute(
                            "UPDATE aluno_desconto SET desconto_id = %s, data_inicio = %s, data_fim = %s WHERE id = %s",
                            (novo_desconto_id, dt_ini, dt_fim, ad_id),
                        )
                conn.commit()
                flash("Desconto atualizado.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Erro ao atualizar: {e}", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        aluno_id = request.form.get("aluno_id", type=int)
        desconto_id = request.form.get("desconto_id", type=int)
        data_inicio = (request.form.get("data_inicio") or "").strip()
        data_fim = (request.form.get("data_fim") or "").strip()
        if not aluno_id or not desconto_id:
            flash("Selecione o aluno e o desconto.", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        cur.execute(
            "SELECT id, nome, tipo, valor FROM descontos WHERE id = %s AND id_academia = %s",
            (desconto_id, academia_id),
        )
        d = cur.fetchone()
        if not d:
            flash("Desconto não encontrado.", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        cur.execute("SELECT id FROM alunos WHERE id = %s AND id_academia = %s", (aluno_id, academia_id))
        if not cur.fetchone():
            flash("Aluno não encontrado.", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        try:
            dt_ini = date.fromisoformat(data_inicio) if data_inicio else date.today()
            dt_fim = date.fromisoformat(data_fim) if data_fim else date(2099, 12, 31)
        except Exception:
            dt_ini = date.today()
            dt_fim = date(2099, 12, 31)

        tipo = d.get("tipo") or "percentual"
        val_desc = float(d.get("valor") or 0)

        try:
            cur.execute(
                """INSERT INTO aluno_desconto (aluno_id, desconto_id, data_inicio, data_fim, ativo)
                   VALUES (%s, %s, %s, %s, 1)
                   ON DUPLICATE KEY UPDATE data_inicio = VALUES(data_inicio), data_fim = VALUES(data_fim), ativo = 1""",
                (aluno_id, desconto_id, dt_ini, dt_fim),
            )
        except Exception:
            cur.execute(
                "SELECT id FROM aluno_desconto WHERE aluno_id = %s AND desconto_id = %s",
                (aluno_id, desconto_id),
            )
            ex = cur.fetchone()
            if ex:
                cur.execute(
                    "UPDATE aluno_desconto SET data_inicio = %s, data_fim = %s, ativo = 1 WHERE id = %s",
                    (dt_ini, dt_fim, ex["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO aluno_desconto (aluno_id, desconto_id, data_inicio, data_fim, ativo) VALUES (%s, %s, %s, %s, 1)",
                    (aluno_id, desconto_id, dt_ini, dt_fim),
                )

        try:
            cur.execute(
                """SELECT ma.id, ma.valor, ma.data_vencimento, ma.status, ma.valor_original,
                          m.nome as plano_nome, a.nome as aluno_nome
                   FROM mensalidade_aluno ma
                   JOIN mensalidades m ON m.id = ma.mensalidade_id
                   JOIN alunos a ON a.id = ma.aluno_id
                   WHERE ma.aluno_id = %s AND m.id_academia = %s AND ma.status IN ('pendente', 'atrasado')
                   AND ma.data_vencimento >= %s AND ma.data_vencimento <= %s
                   AND (ma.id_desconto IS NULL OR ma.id_desconto = %s)""",
                (aluno_id, academia_id, dt_ini, dt_fim, desconto_id),
            )
            mensalidades = cur.fetchall()
        except Exception:
            try:
                cur.execute(
                    """SELECT ma.id, ma.valor, ma.data_vencimento, ma.status, ma.valor_original,
                              m.nome as plano_nome, a.nome as aluno_nome
                       FROM mensalidade_aluno ma
                       JOIN mensalidades m ON m.id = ma.mensalidade_id
                       JOIN alunos a ON a.id = ma.aluno_id
                       WHERE ma.aluno_id = %s AND (m.id_academia = %s OR a.id_academia = %s)
                       AND ma.status IN ('pendente', 'atrasado')
                       AND ma.data_vencimento >= %s AND ma.data_vencimento <= %s""",
                    (aluno_id, academia_id, academia_id, dt_ini, dt_fim),
                )
                mensalidades = cur.fetchall()
            except Exception:
                mensalidades = []

        hoje_str = date.today().strftime("%Y-%m-%d")
        aplicadas = 0
        teve_100 = False
        for ma in mensalidades:
            valor_base = float(ma.get("valor") or 0)
            valor_orig = float(ma.get("valor_original") or 0) or valor_base
            if tipo == "percentual":
                desconto_val = valor_base * (val_desc / 100)
            else:
                desconto_val = min(val_desc, valor_base)
            valor_final = round(valor_base - desconto_val, 2)
            if valor_final < 0:
                valor_final = 0
            desconto_100 = valor_final <= 0
            if desconto_100:
                teve_100 = True

            try:
                if desconto_100:
                    cur.execute(
                        """UPDATE mensalidade_aluno SET valor_original = %s, desconto_aplicado = %s, valor = 0, id_desconto = %s, status = 'pago', data_pagamento = %s WHERE id = %s""",
                        (valor_orig, round(desconto_val, 2), desconto_id, hoje_str, ma["id"]),
                    )
                    venc = ma.get("data_vencimento")
                    try:
                        data_receita = venc.strftime("%Y-%m-%d") if hasattr(venc, "strftime") else str(venc)[:10] if venc else hoje_str
                    except Exception:
                        data_receita = hoje_str
                    descricao = f"Mensalidade {ma.get('plano_nome') or 'Plano'} - {ma.get('aluno_nome') or 'Aluno'} (Desconto integral)"
                    try:
                        cur.execute(
                            "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, criado_por) VALUES (%s, 0, %s, 'Mensalidades', %s, %s, %s)",
                            (descricao, data_receita, academia_id, ma["id"], current_user.id),
                        )
                    except Exception:
                        try:
                            cur.execute(
                                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno) VALUES (%s, 0, %s, 'Mensalidades', %s, %s)",
                                (descricao, data_receita, academia_id, ma["id"]),
                            )
                        except Exception:
                            pass
                else:
                    cur.execute(
                        """UPDATE mensalidade_aluno SET valor_original = %s, desconto_aplicado = %s, valor = %s, id_desconto = %s WHERE id = %s""",
                        (valor_orig, round(desconto_val, 2), valor_final, desconto_id, ma["id"]),
                    )
            except Exception:
                try:
                    cur.execute(
                        "UPDATE mensalidade_aluno SET valor = %s WHERE id = %s",
                        (valor_final, ma["id"]),
                    )
                except Exception:
                    pass
            aplicadas += 1

        conn.commit()
        conn.close()
        flash(f"Desconto aplicado. {aplicadas} mensalidade(s) atualizada(s)." + (" Mensalidades com 100% marcadas como pagas." if teve_100 and aplicadas else ""), "success")
        return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

    vinculos = []
    try:
        cur.execute("""
            SELECT ad.id, ad.aluno_id, ad.desconto_id, ad.data_inicio, ad.data_fim, ad.ativo,
                   a.nome as aluno_nome, d.nome as desconto_nome, d.tipo as desconto_tipo, d.valor as desconto_valor
            FROM aluno_desconto ad
            JOIN alunos a ON a.id = ad.aluno_id
            JOIN descontos d ON d.id = ad.desconto_id
            WHERE a.id_academia = %s AND ad.ativo = 1
            ORDER BY ad.data_fim DESC
        """, (academia_id,))
        vinculos = cur.fetchall()
    except Exception:
        try:
            cur.execute("""
                SELECT ad.id, ad.aluno_id, ad.desconto_id, ad.data_inicio, ad.data_fim, ad.ativo,
                       a.nome as aluno_nome, d.nome as desconto_nome, d.tipo as desconto_tipo, d.valor as desconto_valor
                FROM aluno_desconto ad
                JOIN alunos a ON a.id = ad.aluno_id
                JOIN descontos d ON d.id = ad.desconto_id
                WHERE d.id_academia = %s AND ad.ativo = 1
                ORDER BY ad.data_fim DESC
            """, (academia_id,))
            vinculos = cur.fetchall()
            for v in vinculos:
                v.setdefault("desconto_tipo", "percentual")
                v.setdefault("desconto_valor", 0)
        except Exception:
            vinculos = []
    conn.close()

    return render_template(
        "financeiro/mensalidades/aplicar_desconto.html",
        academias=academias,
        academia_id=academia_id,
        descontos=descontos,
        vinculos=vinculos,
    )


def _registrar_pagamento_e_receita(conn, cur, tipo, registro_id, id_academia):
    """Atualiza status para pago e cria receita. tipo='mensalidade_aluno' ou 'cobranca_avulsa'."""
    hoje = date.today().strftime("%Y-%m-%d")
    if tipo == "mensalidade_aluno":
        cur.execute(
            "SELECT ma.id, ma.valor, m.nome, a.nome as aluno_nome, m.id_academia FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id JOIN alunos a ON a.id = ma.aluno_id WHERE ma.id = %s",
            (registro_id,),
        )
        row = cur.fetchone()
        if not row or row[3] is None:
            return False
        valor = float(row[1])
        descricao = f"Mensalidade {row[2]} - {row[3]}"
        id_acad = row[4] if len(row) > 4 and row[4] else id_academia
        try:
            cur.execute(
                "UPDATE mensalidade_aluno SET status='pago', status_pagamento='pago', data_pagamento=%s, valor_pago=%s WHERE id=%s",
                (hoje, valor, registro_id),
            )
        except Exception:
            cur.execute(
                "UPDATE mensalidade_aluno SET status='pago', data_pagamento=%s, valor_pago=%s WHERE id=%s",
                (hoje, valor, registro_id),
            )
        try:
            cur.execute(
                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, criado_por) VALUES (%s, %s, %s, 'Mensalidades', %s, %s, %s)",
                (descricao, valor, hoje, id_acad, registro_id, current_user.id),
            )
        except Exception:
            cur.execute(
                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno) VALUES (%s, %s, %s, 'Mensalidades', %s, %s)",
                (descricao, valor, hoje, id_acad, registro_id),
            )
    else:
        cur.execute(
            "SELECT ca.id, ca.valor, ca.descricao, a.nome, ca.id_academia FROM cobranca_avulsa ca JOIN alunos a ON a.id = ca.aluno_id WHERE ca.id = %s",
            (registro_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        valor = float(row[1])
        descricao = (row[2] or "Cobrança avulsa") + (" - %s" % row[3] if row[3] else "")
        id_acad = row[4] if len(row) > 4 and row[4] else id_academia
        cur.execute(
            "UPDATE cobranca_avulsa SET status='pago', data_pagamento=%s, valor_pago=%s WHERE id=%s",
            (hoje, valor, registro_id),
        )
        try:
            cur.execute(
                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_cobranca_avulsa, criado_por) VALUES (%s, %s, %s, 'Cobrança avulsa', %s, %s, %s)",
                (descricao, valor, hoje, id_acad, registro_id, current_user.id),
            )
        except Exception:
            cur.execute(
                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia) VALUES (%s, %s, %s, 'Cobrança avulsa', %s)",
                (descricao, valor, hoje, id_acad),
            )
    return True


@bp_financeiro.route("/mensalidades/informar-pagamento", methods=["POST"])
@login_required
def informar_pagamento_mensalidade():
    """Aluno informa pagamento com comprovante e comentário. Status -> aguardando_confirmacao."""
    registro_id = request.form.get("registro_id", type=int)
    comentario = (request.form.get("comentario") or "").strip() or None
    arquivo = request.files.get("comprovante")
    if not registro_id:
        flash("Parâmetros inválidos.", "danger")
        return redirect(request.referrer or url_for("painel_aluno.minhas_mensalidades"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT ma.id, ma.aluno_id, a.usuario_id
        FROM mensalidade_aluno ma
        JOIN alunos a ON a.id = ma.aluno_id
        WHERE ma.id = %s AND ma.status IN ('pendente','atrasado')
    """, (registro_id,))
    row = cur.fetchone()
    if not row or row.get("usuario_id") != current_user.id:
        conn.close()
        flash("Mensalidade não encontrada ou não pertence a você.", "warning")
        return redirect(request.referrer or url_for("painel_aluno.minhas_mensalidades"))

    comprovante_fn = None
    if arquivo and arquivo.filename:
        ext = (os.path.splitext(arquivo.filename)[1] or ".png").lower()
        if ext.lstrip(".") in COMPROVANTE_EXT:
            fn = f"comprovantes/comprovante_{registro_id}_{uuid.uuid4().hex[:12]}{ext}"
            folder = os.path.join(current_app.root_path, "static", "uploads", "comprovantes")
            os.makedirs(folder, exist_ok=True)
            arquivo.save(os.path.join(current_app.root_path, "static", "uploads", fn))
            comprovante_fn = fn

    try:
        if comprovante_fn:
            try:
                cur.execute(
                    "UPDATE mensalidade_aluno SET status_pagamento='pendente_aprovacao', comprovante_url=%s, observacoes=%s WHERE id=%s",
                    (comprovante_fn, comentario, registro_id),
                )
            except Exception:
                try:
                    cur.execute(
                        "UPDATE mensalidade_aluno SET status_pagamento='pendente_aprovacao', observacoes=%s WHERE id=%s",
                        (comentario, registro_id),
                    )
                except Exception:
                    cur.execute(
                        "UPDATE mensalidade_aluno SET observacoes=%s WHERE id=%s",
                        (comentario, registro_id),
                    )
        else:
            try:
                cur.execute(
                    "UPDATE mensalidade_aluno SET status_pagamento='pendente_aprovacao', observacoes=%s WHERE id=%s",
                    (comentario, registro_id),
                )
            except Exception:
                cur.execute(
                    "UPDATE mensalidade_aluno SET observacoes=%s WHERE id=%s",
                    (comentario, registro_id),
                )
        conn.commit()
        flash("Pagamento informado. Aguarde a confirmação do gestor.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao enviar: {e}", "danger")
    conn.close()
    return redirect(request.referrer or url_for("painel_aluno.minhas_mensalidades"))


@bp_financeiro.route("/mensalidades/confirmar-pagamento/<int:registro_id>", methods=["POST"])
@login_required
def confirmar_pagamento_mensalidade(registro_id):
    """Gestor confirma pagamento informado pelo aluno. Gera receita e marca como pago."""
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Sem acesso.", "danger")
        return redirect(request.referrer or url_for("financeiro.painel_mensalidades"))
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            f"SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id WHERE ma.id = %s AND m.id_academia IN ({ph}) AND ma.status_pagamento = 'pendente_aprovacao'",
            (registro_id,) + tuple(ids),
        )
        if not cur.fetchone():
            conn.close()
            flash("Mensalidade não encontrada ou não está aguardando confirmação.", "warning")
            return redirect(request.referrer or url_for("financeiro.mensalidades_alunos"))
        _registrar_pagamento_e_receita(conn, cur, "mensalidade_aluno", registro_id, academia_id)
        conn.commit()
        flash("Pagamento confirmado e receita gerada.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro: {e}", "danger")
    conn.close()
    return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))


@bp_financeiro.route("/mensalidades/api-por-status")
@login_required
def api_mensalidades_por_status():
    """Retorna JSON com mensalidades filtradas por status (para modal)."""
    academia_id = request.args.get("academia_id", type=int) or _get_academia_id()
    status = request.args.get("status")
    mes = request.args.get("mes", type=int)
    ano_arg = request.args.get("ano")
    ano = int(ano_arg) if (ano_arg and str(ano_arg).isdigit() and 2000 <= int(ano_arg) <= 2100) else None
    busca = (request.args.get("busca") or "").strip()
    if not academia_id or status not in ("pago", "pendente", "atrasado", "aguardando_confirmacao"):
        return jsonify([])
    ids = _get_academias_ids()
    if academia_id not in ids:
        return jsonify([])
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    hoje = date.today()
    where_cl = ["m.id_academia = %s", "ma.status != 'cancelado'"]
    params = [academia_id]
    if mes and 1 <= mes <= 12:
        where_cl.append("MONTH(ma.data_vencimento) = %s")
        params.append(mes)
    if ano and 2000 <= ano <= 2100:
        where_cl.append("YEAR(ma.data_vencimento) = %s")
        params.append(ano)
    if busca:
        where_cl.append("a.nome LIKE %s")
        params.append(f"%{busca}%")
    try:
        cur.execute(f"""
            SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.status,
                   ma.status_pagamento, ma.comprovante_url, ma.observacoes,
                   m.nome as plano_nome, a.id as aluno_id, a.nome as aluno_nome, a.foto as aluno_foto
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE {' AND '.join(where_cl)}
            ORDER BY a.nome, ma.data_vencimento DESC
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    conn.close()
    resultado = []
    for ma in rows:
        se = _status_efetivo(ma.get("status"), ma.get("data_vencimento"), ma.get("status_pagamento"))
        if se != status:
            continue
        vi, vd, vf, desconto_nome = _valor_com_desconto(ma, ma.get("aluno_id"), academia_id, hoje)
        ma["valor_integral"] = vi
        ma["valor_desconto"] = vd
        ma["valor_final"] = vf
        ma["desconto_nome"] = desconto_nome
        ma["tem_desconto"] = vd > 0
        ma["foto_url"] = url_for("static", filename="uploads/" + ma["aluno_foto"]) if ma.get("aluno_foto") else None
        ma["comprovante_url"] = url_for("static", filename="uploads/" + ma["comprovante_url"]) if ma.get("comprovante_url") else None
        resultado.append(ma)
    return jsonify(resultado)


@bp_financeiro.route("/mensalidades/cancelar-cobranca", methods=["POST"])
@login_required
def cancelar_cobranca():
    """Cancela mensalidade ou cobrança avulsa (status pendente/atrasado)."""
    tipo = request.form.get("tipo")
    registro_id = request.form.get("registro_id", type=int)
    academia_id = _get_academia_id()
    if not registro_id or tipo not in ("mensalidade_aluno", "cobranca_avulsa"):
        flash("Parâmetros inválidos.", "danger")
        return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))

    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        ph = ",".join(["%s"] * len(ids))
        if tipo == "mensalidade_aluno":
            cur.execute(
                f"SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id WHERE ma.id = %s AND m.id_academia IN ({ph}) AND ma.status IN ('pendente','atrasado')",
                (registro_id,) + tuple(ids),
            )
        else:
            cur.execute(
                f"SELECT id FROM cobranca_avulsa WHERE id = %s AND id_academia IN ({ph}) AND status IN ('pendente','atrasado')",
                (registro_id,) + tuple(ids),
            )
        if not cur.fetchone():
            flash("Cobrança não encontrada ou não pode ser cancelada.", "warning")
            conn.close()
            return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
        if tipo == "mensalidade_aluno":
            cur.execute("UPDATE mensalidade_aluno SET status = 'cancelado' WHERE id = %s", (registro_id,))
        else:
            cur.execute("UPDATE cobranca_avulsa SET status = 'cancelado' WHERE id = %s", (registro_id,))
        conn.commit()
        flash("Cobrança cancelada.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro: {e}", "danger")
    conn.close()
    return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))


@bp_financeiro.route("/mensalidades/registrar-pagamento", methods=["POST"])
@login_required
def registrar_pagamento():
    """Registra pagamento de mensalidade ou cobrança avulsa e gera receita."""
    tipo = request.form.get("tipo")
    registro_id = request.form.get("registro_id", type=int)
    academia_id = _get_academia_id()
    if not registro_id or tipo not in ("mensalidade_aluno", "cobranca_avulsa"):
        flash("Parâmetros inválidos.", "danger")
        return redirect(request.referrer or url_for("financeiro.painel_mensalidades"))

    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        ph = ",".join(["%s"] * len(ids))
        if tipo == "mensalidade_aluno":
            cur.execute(
                f"SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id WHERE ma.id = %s AND m.id_academia IN ({ph}) AND ma.status IN ('pendente','atrasado','aguardando_confirmacao')",
                (registro_id,) + tuple(ids),
            )
        else:
            cur.execute(
                f"SELECT id FROM cobranca_avulsa WHERE id = %s AND id_academia IN ({ph}) AND status IN ('pendente','atrasado')",
                (registro_id,) + tuple(ids),
            )
        if not cur.fetchone():
            flash("Cobrança não encontrada ou já paga.", "warning")
            conn.close()
            return redirect(request.referrer or url_for("financeiro.painel_mensalidades"))
        _registrar_pagamento_e_receita(conn, cur, tipo, registro_id, academia_id)
        conn.commit()
        flash("Pagamento registrado e receita gerada.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro: {e}", "danger")
    conn.close()
    ref = request.referrer or ""
    if "mensalidades/alunos" in ref or not ref:
        return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
    return redirect(ref)


def _render_gerar_cobranca(academias, academia_id, academia_sel):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome, valor FROM mensalidades WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_sel,),
        )
        planos = cur.fetchall()
    except Exception:
        planos = []
    try:
        cur.execute(
            "SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome",
            (academia_sel,),
        )
        turmas = cur.fetchall()
    except Exception:
        turmas = []
    conn.close()
    return render_template(
        "financeiro/mensalidades/gerar_cobranca.html",
        academias=academias,
        academia_id=academia_id,
        academia_sel=academia_sel,
        planos=planos,
        turmas=turmas,
        ano_atual=date.today().year,
    )


@bp_financeiro.route("/mensalidades/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar_mensalidade():
    """Cadastrar novo plano de mensalidade."""
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        valor_str = request.form.get("valor") or ""
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aplicar_juros = 1 if "1" in request.form.getlist("aplicar_juros_multas") else 0
        ativo = 1 if "1" in request.form.getlist("ativo") else 0

        if not nome:
            flash("Informe o nome do plano.", "danger")
            return render_template("financeiro/mensalidades/cadastrar_mensalidade.html", academias=academias, academia_id=academia_id)
        valor = _parse_valor(valor_str)
        if valor is None or valor < 0:
            flash("Informe um valor válido.", "danger")
            return render_template("financeiro/mensalidades/cadastrar_mensalidade.html", academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """INSERT INTO mensalidades (nome, descricao, valor, id_academia, ativo, aplicar_juros_multas, percentual_multa_mes, percentual_juros_dia)
                       VALUES (%s, %s, %s, %s, %s, %s, 2.00, 0.0333)""",
                    (nome, descricao, valor, id_acad, ativo, aplicar_juros),
                )
            except Exception as col_err:
                if "aplicar_juros_multas" in str(col_err) or "Unknown column" in str(col_err):
                    cur.execute(
                        "INSERT INTO mensalidades (nome, descricao, valor, id_academia, ativo) VALUES (%s, %s, %s, %s, %s)",
                        (nome, descricao, valor, id_acad, ativo),
                    )
                else:
                    raise
            conn.commit()
            conn.close()
            flash("Plano de mensalidade cadastrado com sucesso.", "success")
            return redirect(url_for("financeiro.lista_planos_mensalidades", academia_id=academia_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Erro ao salvar: {e}", "danger")
            return render_template("financeiro/mensalidades/cadastrar_mensalidade.html", academias=academias, academia_id=academia_id)

    return render_template("financeiro/mensalidades/cadastrar_mensalidade.html", academias=academias, academia_id=academia_id)


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
        try:
            cur.execute(
                "SELECT id, descricao, valor, data, categoria, id_mensalidade_aluno, id_cobranca_avulsa FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
                (academia_id, mes, ano),
            )
        except Exception:
            cur.execute(
                "SELECT id, descricao, valor, data, categoria FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
                (academia_id, mes, ano),
            )
        receitas = cur.fetchall()
        for r in receitas:
            r.setdefault("id_mensalidade_aluno", None)
            r.setdefault("id_cobranca_avulsa", None)
        total_mes = sum(float(r.get("valor") or 0) for r in receitas)
        conn.close()
    except Exception:
        pass
    return render_template("financeiro/receitas/lista_receitas.html", receitas=receitas, mes=mes, ano=ano, total_mes=total_mes, ano_atual=date.today().year, academia_id=academia_id)


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
    return render_template("financeiro/despesas/lista_despesas.html", despesas=despesas, mes=mes, ano=ano, total_mes=total_mes, ano_atual=date.today().year, academia_id=academia_id)


@bp_financeiro.route("/mensalidades/editar/<int:mensalidade_id>", methods=["GET", "POST"])
@login_required
def editar_mensalidade(mensalidade_id):
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(
            f"""SELECT id, nome, descricao, valor, id_academia, ativo,
               COALESCE(aplicar_juros_multas, 0) AS aplicar_juros_multas,
               COALESCE(percentual_multa_mes, 2) AS percentual_multa_mes,
               COALESCE(percentual_juros_dia, 0.0333) AS percentual_juros_dia
               FROM mensalidades WHERE id = %s AND id_academia IN ({ph})""",
            (mensalidade_id,) + tuple(ids),
        )
    except Exception:
        cur.execute(
            f"SELECT id, nome, descricao, valor, id_academia, ativo FROM mensalidades WHERE id = %s AND id_academia IN ({ph})",
            (mensalidade_id,) + tuple(ids),
        )
    mensalidade = cur.fetchone()
    conn.close()

    if not mensalidade:
        flash("Mensalidade não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_planos_mensalidades", academia_id=academia_id))

    if mensalidade and "aplicar_juros_multas" not in mensalidade:
        mensalidade["aplicar_juros_multas"] = 0

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        valor_str = request.form.get("valor") or ""
        id_acad = request.form.get("id_academia", type=int) or mensalidade.get("id_academia") or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aplicar_juros = 1 if "1" in request.form.getlist("aplicar_juros_multas") else 0
        ativo = 1 if "1" in request.form.getlist("ativo") else 0

        if not nome:
            flash("Informe o nome do plano.", "danger")
            mensalidade["nome"] = request.form.get("nome")
            mensalidade["descricao"] = request.form.get("descricao")
            mensalidade["valor"] = valor_str
            return render_template("financeiro/mensalidades/editar_mensalidade.html", mensalidade=mensalidade, academias=academias, academia_id=academia_id)
        valor = _parse_valor(valor_str)
        if valor is None or valor < 0:
            flash("Informe um valor válido.", "danger")
            mensalidade["nome"] = nome
            mensalidade["descricao"] = descricao
            mensalidade["valor"] = valor_str
            return render_template("financeiro/mensalidades/editar_mensalidade.html", mensalidade=mensalidade, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """UPDATE mensalidades SET nome=%s, descricao=%s, valor=%s, id_academia=%s, ativo=%s,
                       aplicar_juros_multas=%s, percentual_multa_mes=2, percentual_juros_dia=0.0333
                       WHERE id=%s""",
                    (nome, descricao, valor, id_acad, ativo, aplicar_juros, mensalidade_id),
                )
            except Exception as col_err:
                if "aplicar_juros_multas" in str(col_err) or "Unknown column" in str(col_err):
                    cur.execute(
                        "UPDATE mensalidades SET nome=%s, descricao=%s, valor=%s, id_academia=%s, ativo=%s WHERE id=%s",
                        (nome, descricao, valor, id_acad, ativo, mensalidade_id),
                    )
                else:
                    raise
            conn.commit()
            conn.close()
            flash("Mensalidade atualizada.", "success")
            return redirect(url_for("financeiro.lista_planos_mensalidades", academia_id=academia_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Erro ao atualizar: {e}", "danger")

    return render_template("financeiro/mensalidades/editar_mensalidade.html", mensalidade=mensalidade, academias=academias, academia_id=academia_id)


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
            return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id))
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
    try:
        cur.execute(
            "SELECT id, descricao, valor, data, categoria, id_academia, observacoes, id_mensalidade_aluno, id_cobranca_avulsa FROM receitas WHERE id = %s AND id_academia IN (" + placeholders + ")",
            (receita_id,) + tuple(ids),
        )
    except Exception:
        cur.execute(
            "SELECT id, descricao, valor, data, categoria, id_academia, observacoes FROM receitas WHERE id = %s AND id_academia IN (" + placeholders + ")",
            (receita_id,) + tuple(ids),
        )
    receita = cur.fetchone()
    conn.close()
    if not receita:
        flash("Receita não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_receitas", academia_id=_get_academia_id()))
    receita.setdefault("id_mensalidade_aluno", None)
    receita.setdefault("id_cobranca_avulsa", None)
    if receita.get("id_mensalidade_aluno") or receita.get("id_cobranca_avulsa"):
        flash("Não é possível editar receitas geradas a partir de pagamento de mensalidade ou cobrança confirmada.", "danger")
        return redirect(url_for("financeiro.lista_receitas", academia_id=_get_academia_id()))

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or receita.get("id_academia") or academia_id
        if id_acad not in ids:
            id_acad = receita.get("id_academia") or academia_id

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
            return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id))
        except Exception:
            flash("Erro ao atualizar receita.", "danger")

    return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/receitas/excluir/<int:receita_id>", methods=["POST"])
@login_required
def excluir_receita(receita_id):
    ids = _get_academias_ids()
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        ids = []
    if not ids:
        flash("Sem acesso a academias.", "warning")
        return redirect(url_for("painel.home"))
    academia_id = _get_academia_id()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    rec = None
    for query in [
        "SELECT id, id_academia, id_mensalidade_aluno, id_cobranca_avulsa FROM receitas WHERE id = %s",
        "SELECT id, id_academia FROM receitas WHERE id = %s",
    ]:
        try:
            cur.execute(query, (receita_id,))
            rec = cur.fetchone()
            if rec:
                rec.setdefault("id_mensalidade_aluno", None)
                rec.setdefault("id_cobranca_avulsa", None)
                break
        except Exception:
            continue
    if not rec:
        conn.close()
        flash("Receita não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id))
    rec_acad = rec.get("id_academia")
    try:
        rec_acad_int = int(rec_acad) if rec_acad is not None else None
    except (TypeError, ValueError):
        rec_acad_int = None
    if rec_acad_int is not None and rec_acad_int not in ids:
        conn.close()
        flash("Receita não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id))
    if rec.get("id_mensalidade_aluno") or rec.get("id_cobranca_avulsa"):
        conn.close()
        flash("Não é possível excluir receitas geradas a partir de pagamento de mensalidade ou cobrança confirmada.", "danger")
        return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id))
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM receitas WHERE id = %s", (receita_id,))
        conn.commit()
        flash("Receita excluída.", "success")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        flash("Erro ao excluir receita.", "danger")
    conn.close()
    return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id))


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
            return redirect(url_for("financeiro.lista_despesas", academia_id=academia_id))
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
        return redirect(url_for("financeiro.lista_despesas", academia_id=_get_academia_id()))

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or despesa.get("id_academia") or academia_id
        if id_acad not in ids:
            id_acad = despesa.get("id_academia") or academia_id

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
            return redirect(url_for("financeiro.lista_despesas", academia_id=academia_id))
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
    return redirect(url_for("financeiro.lista_despesas", academia_id=_get_academia_id()))
