# ======================================================
# Blueprint: Painel do Responsável
# Exibe dados do(s) aluno(s) vinculado(s) ao responsável
# ======================================================

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from config import get_db_connection
from datetime import datetime, date
from functools import wraps

# Importar helpers do painel do aluno para reutilizar lógica
from blueprints.aluno.painel import (
    _turmas_do_aluno, _buscar_alunos_turma, _calcular_meses_filtro,
    _status_efetivo_painel, _calcular_valor_com_juros_multas,
    _calcular_graduacao_prevista,
)

bp_painel_responsavel = Blueprint(
    "painel_responsavel",
    __name__,
    url_prefix="/painel_responsavel"
)


def _get_alunos_responsavel():
    """Retorna lista de alunos vinculados ao responsável via responsavel_alunos."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT a.id, a.nome, a.foto, a.TurmaID
            FROM responsavel_alunos ra
            JOIN alunos a ON a.id = ra.aluno_id
            WHERE ra.usuario_id = %s AND a.ativo = 1
            ORDER BY a.nome
        """, (current_user.id,))
        alunos = cur.fetchall()
    except Exception:
        alunos = []
    finally:
        cur.close()
        conn.close()
    return alunos


def _get_aluno_responsavel(aluno_id):
    """Retorna o aluno se o usuário for responsável por ele."""
    if not aluno_id:
        return None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT a.*
            FROM alunos a
            JOIN responsavel_alunos ra ON ra.aluno_id = a.id
            WHERE ra.usuario_id = %s AND a.id = %s AND a.ativo = 1
        """, (current_user.id, aluno_id))
        aluno = cur.fetchone()
    except Exception:
        aluno = None
    finally:
        cur.close()
        conn.close()
    return aluno


def _responsavel_required(f):
    """Decorator: exige role responsavel e pelo menos um aluno vinculado."""
    @wraps(f)
    def _view(*a, **kw):
        if not (current_user.has_role("responsavel") or current_user.has_role("admin")):
            flash("Acesso restrito aos responsáveis.", "danger")
            return redirect(url_for("painel.home"))
        alunos = _get_alunos_responsavel()
        if not alunos:
            flash("Nenhum aluno vinculado a este responsável.", "warning")
            return redirect(url_for("painel.home"))
        return f(*a, alunos=alunos, **kw)
    return _view


def _enriquecer_aluno_painel(aluno):
    """Adiciona academia_nome, turma_nome, modalidades, faixa, proxima_faixa ao aluno."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Inicializar valores padrão
        aluno.setdefault("academia_nome", None)
        aluno.setdefault("turma_nome", None)
        aluno.setdefault("faixa_nome", None)
        aluno.setdefault("graduacao_nome", None)
        
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
        
        # Se não encontrou turma no JOIN, tentar buscar diretamente pelo TurmaID
        if not aluno.get("turma_nome") and aluno.get("TurmaID"):
            cur.execute("SELECT Nome FROM turmas WHERE TurmaID = %s", (aluno.get("TurmaID"),))
            turma_row = cur.fetchone()
            if turma_row:
                aluno["turma_nome"] = turma_row.get("Nome")
        
        # Se ainda não encontrou, tentar buscar via aluno_turmas
        if not aluno.get("turma_nome"):
            cur.execute(
                """SELECT t.Nome FROM aluno_turmas at
                   INNER JOIN turmas t ON t.TurmaID = at.TurmaID
                   WHERE at.aluno_id = %s
                   ORDER BY at.TurmaID LIMIT 1""",
                (aluno["id"],),
            )
            turma_row = cur.fetchone()
            if turma_row:
                aluno["turma_nome"] = turma_row.get("Nome")
        
        cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (aluno.get("graduacao_id"),))
        g = cur.fetchone()
        if g:
            aluno["faixa_nome"] = g.get("faixa")
            aluno["graduacao_nome"] = g.get("graduacao")
        cur.execute(
            """SELECT m.nome FROM modalidade m
               INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id
               WHERE am.aluno_id = %s ORDER BY m.nome""",
            (aluno["id"],),
        )
        modalidades_list = [r["nome"] for r in cur.fetchall()]
        aluno["modalidades"] = modalidades_list
        aluno["modalidades_nomes"] = ", ".join(modalidades_list) if modalidades_list else "-"
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


@bp_painel_responsavel.route("/")
@login_required
@_responsavel_required
def painel(alunos):
    """Redireciona para meu_perfil."""
    session["modo_painel"] = "responsavel"
    if len(alunos) == 1:
        return redirect(url_for("painel_responsavel.meu_perfil", aluno_id=alunos[0]["id"]))
    return redirect(url_for("painel_responsavel.meu_perfil"))


@bp_painel_responsavel.route("/meu-perfil")
@login_required
@_responsavel_required
def meu_perfil(alunos):
    """Exibe perfil do aluno selecionado. Se múltiplos, mostra seletor."""
    session["modo_painel"] = "responsavel"
    aluno_id = request.args.get("aluno_id", type=int)
    if not aluno_id and len(alunos) == 1:
        aluno_id = alunos[0]["id"]
        return redirect(url_for("painel_responsavel.meu_perfil", aluno_id=aluno_id))

    if not aluno_id:
        return render_template(
            "painel_responsavel/selecionar_aluno.html",
            alunos=alunos,
        )

    aluno = _get_aluno_responsavel(aluno_id)
    if not aluno:
        flash("Aluno não encontrado ou sem permissão.", "danger")
        return redirect(url_for("painel_responsavel.meu_perfil"))

    _enriquecer_aluno_painel(aluno)
    from blueprints.aluno.alunos import enriquecer_aluno_para_modal
    enriquecer_aluno_para_modal(aluno)
    return render_template(
        "painel_responsavel/meu_perfil.html",
        usuario=current_user,
        aluno=aluno,
        alunos=alunos,
    )


def _aluno_id_responsavel_required(f):
    """Decorator: obtém aluno_id da URL, valida que o usuário é responsável e passa aluno."""
    @wraps(f)
    def _view(*a, **kw):
        if not (current_user.has_role("responsavel") or current_user.has_role("admin")):
            flash("Acesso restrito aos responsáveis.", "danger")
            return redirect(url_for("painel.home"))
        aluno_id = request.args.get("aluno_id", type=int)
        aluno = _get_aluno_responsavel(aluno_id) if aluno_id else None
        if not aluno:
            flash("Selecione um aluno ou sem permissão.", "danger")
            return redirect(url_for("painel_responsavel.meu_perfil"))
        session["modo_painel"] = "responsavel"
        return f(*a, aluno=aluno, **kw)
    return _view


@bp_painel_responsavel.route("/mensalidades")
@login_required
@_aluno_id_responsavel_required
def minhas_mensalidades(aluno):
    """Mensalidades do aluno (mesmo conteúdo do painel_aluno)."""
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
                   COALESCE(ma.remover_juros, 0) AS remover_juros,
                   m.nome as plano_nome, m.id_academia,
                   COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
                   COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
                   COALESCE(m.percentual_juros_dia, 0.033) AS percentual_juros_dia
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
                r.setdefault("remover_juros", 0)
                r.setdefault("aplicar_juros_multas", 0)
                r.setdefault("percentual_multa_mes", 2)
                r.setdefault("percentual_juros_dia", 0.033)
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
        valor_display, valor_original, multa_val, juros_val = _calcular_valor_com_juros_multas(ma, hoje)
        ma["valor_display"] = valor_display
        ma["valor_original"] = valor_original
        ma["multa_val"] = multa_val
        ma["juros_val"] = juros_val
        ma["tem_juros"] = (multa_val or 0) + (juros_val or 0) > 0
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
        voltar_url=url_for("painel_responsavel.meu_perfil", aluno_id=aluno["id"]),
    )


@bp_painel_responsavel.route("/turma")
@login_required
@_aluno_id_responsavel_required
def minha_turma(aluno):
    """Turma do aluno."""
    turma_selecionada_id = request.args.get("turma_id", type=int)
    turmas_com_alunos = []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    turmas_list = _turmas_do_aluno(cur, aluno["id"], aluno.get("TurmaID"))
    turma_ids = [t["TurmaID"] for t in turmas_list]
    if turma_ids:
        for tid in turma_ids:
            cur.execute("SELECT * FROM turmas WHERE TurmaID = %s", (tid,))
            t = cur.fetchone()
            if t:
                try:
                    cur.execute(
                        """SELECT p.nome FROM turma_professor tp
                           JOIN professores p ON p.id = tp.professor_id
                           WHERE tp.TurmaID = %s AND tp.tipo = 'responsavel' LIMIT 1""",
                        (tid,),
                    )
                    row = cur.fetchone()
                    t["Professor"] = row["nome"] if row and row.get("nome") else t.get("Professor") or "—"
                except Exception:
                    t["Professor"] = t.get("Professor") or "—"
                id_acad = t.get("id_academia")
                alns = _buscar_alunos_turma(cur, tid, id_acad)
                turmas_com_alunos.append((t, alns))
        if turma_selecionada_id and len(turmas_com_alunos) > 1:
            turmas_com_alunos.sort(key=lambda x: (0 if x[0]["TurmaID"] == turma_selecionada_id else 1, x[0]["Nome"] or ""))
        else:
            turmas_com_alunos.sort(key=lambda x: (x[0]["Nome"] or "").lower())
    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/minha_turma.html",
        usuario=current_user,
        aluno=aluno,
        turmas_com_alunos=turmas_com_alunos,
        turma_selecionada_id=turma_selecionada_id,
        voltar_url=url_for("painel_responsavel.meu_perfil", aluno_id=aluno["id"]),
    )


@bp_painel_responsavel.route("/presencas")
@login_required
@_aluno_id_responsavel_required
def minhas_presencas(aluno):
    """Presenças do aluno."""
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
            ph = ",".join(["%s"] * len(meses_sel))
            cur.execute("""
                SELECT p.data_presenca, p.presente
                FROM presencas p
                WHERE p.aluno_id = %s AND YEAR(p.data_presenca) = %s
                  AND MONTH(p.data_presenca) IN (""" + ph + ")" + where_extra + """
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
        voltar_url=url_for("painel_responsavel.meu_perfil", aluno_id=aluno["id"]),
    )


@bp_painel_responsavel.route("/curriculo")
@login_required
@_aluno_id_responsavel_required
def curriculo(aluno):
    """Currículo do aluno (somente leitura para responsável)."""
    from utils.contexto_logo import buscar_logo_url
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
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
    from blueprints.aluno.painel import _build_endereco_completo
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
        cur.execute("SELECT m.id, m.nome FROM modalidade m INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id WHERE am.aluno_id = %s ORDER BY m.nome", (aluno["id"],))
        aluno["modalidades"] = cur.fetchall()
    except Exception:
        pass
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
    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/curriculo.html",
        aluno=aluno,
        competicoes=competicoes,
        eventos=eventos,
        voltar_url=url_for("painel_responsavel.meu_perfil", aluno_id=aluno["id"]),
        somente_leitura=True,
    )


@bp_painel_responsavel.route("/simular-graduacao-prevista", methods=["GET", "POST"])
@login_required
@_aluno_id_responsavel_required
def simular_graduacao_prevista(aluno):
    """Simula e exibe graduações previstas baseado na data informada pelo usuário."""
    try:
        session["modo_painel"] = "responsavel"
        _enriquecer_aluno_painel(aluno)
        from blueprints.aluno.alunos import enriquecer_aluno_para_modal
        enriquecer_aluno_para_modal(aluno)
        
        graduacoes_previstas = []
        previsao_proximo_exame = None
        
        if request.method == "POST":
            # Obter mês/ano informado pelo usuário
            previsao_mes_ano = request.form.get("previsao_mes_ano", "").strip()
            if previsao_mes_ano:
                try:
                    # Converter formato YYYY-MM para date (primeiro dia do mês)
                    from datetime import datetime
                    previsao_proximo_exame = datetime.strptime(previsao_mes_ano + "-01", "%Y-%m-%d").date()
                except ValueError:
                    flash("Data inválida. Use o formato mês/ano.", "danger")
                    return redirect(url_for("painel_responsavel.simular_graduacao_prevista", aluno_id=aluno.get("id")))
        
        # Não usar previsão do banco, só calcular se informado no formulário
        if not previsao_proximo_exame:
            graduacoes_previstas = []
            previsao_input = None
        else:
            # Criar cópia do aluno com a previsão para o cálculo
            aluno_calculo = aluno.copy()
            aluno_calculo["previsao_proximo_exame"] = previsao_proximo_exame
            
            # Calcular graduações previstas usando a data informada
            from blueprints.aluno.painel import _calcular_graduacao_prevista
            graduacoes_previstas = _calcular_graduacao_prevista(aluno_calculo)
            
            # Formatar previsão para exibição no formulário
            if isinstance(previsao_proximo_exame, date):
                previsao_input = previsao_proximo_exame.strftime("%Y-%m")
            else:
                try:
                    from datetime import datetime
                    previsao_input = datetime.strptime(str(previsao_proximo_exame)[:10], "%Y-%m-%d").strftime("%Y-%m")
                except:
                    previsao_input = None
        
        return render_template(
            "painel_responsavel/simular_graduacao_prevista.html",
            aluno=aluno,
            graduacoes_previstas=graduacoes_previstas,
            previsao_proximo_exame_input=previsao_input,
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Erro em simular_graduacao_prevista: {e}", exc_info=True)
        flash(f"Erro ao carregar página: {str(e)}", "danger")
        return redirect(url_for("painel_responsavel.meu_perfil", aluno_id=aluno.get("id")))


@bp_painel_responsavel.route("/simular-categorias", methods=["GET", "POST"])
@login_required
@_responsavel_required
def simular_categorias(alunos):
    """Simula e exibe categorias disponíveis baseado em peso, data de nascimento e sexo."""
    session["modo_painel"] = "responsavel"
    
    aluno_id = request.args.get("aluno_id", type=int) or request.form.get("aluno_id", type=int)
    aluno = None
    
    if aluno_id:
        aluno = _get_aluno_responsavel(aluno_id)
        if not aluno:
            flash("Aluno não encontrado.", "danger")
            return redirect(url_for("painel_responsavel.meu_perfil"))
    elif len(alunos) == 1:
        aluno = _get_aluno_responsavel(alunos[0]["id"])
    
    categorias_disponiveis = []
    peso = None
    data_nascimento = None
    sexo = None
    idade_calculada = None
    
    # Formatar data_nascimento do aluno para o template se não vier do POST
    aluno_data_nasc_str = None
    if aluno:
        aluno_data_nasc = aluno.get("data_nascimento")
        if aluno_data_nasc:
            try:
                if isinstance(aluno_data_nasc, date):
                    aluno_data_nasc_str = aluno_data_nasc.strftime("%Y-%m-%d")
                else:
                    aluno_data_nasc_str = str(aluno_data_nasc)[:10]
            except Exception:
                aluno_data_nasc_str = None
    
    if request.method == "POST":
        peso_str = request.form.get("peso", "").strip()
        data_nascimento = request.form.get("data_nascimento", "").strip()
        sexo = request.form.get("sexo", "").strip()
        
        if peso_str and data_nascimento and sexo:
            try:
                peso = float(peso_str)
                nasc = datetime.strptime(data_nascimento[:10], "%Y-%m-%d").date()
                hoje = date.today()
                idade_calculada = hoje.year - nasc.year
                genero_upper = sexo.upper()
                
                if genero_upper in ("M", "F") and peso > 0:
                    conn = get_db_connection()
                    cur = conn.cursor(dictionary=True)
                    try:
                        # Mapear M/F para MASCULINO/FEMININO
                        genero_db = "MASCULINO" if genero_upper == "M" else "FEMININO" if genero_upper == "F" else genero_upper
                        cur.execute("""
                            SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max, descricao
                            FROM categorias
                            WHERE UPPER(genero) = UPPER(%s)
                            AND (
                                (idade_min IS NULL OR %s >= idade_min)
                                AND (idade_max IS NULL OR %s <= idade_max)
                            )
                            AND (
                                (peso_min IS NULL OR %s >= peso_min)
                                AND (peso_max IS NULL OR %s <= peso_max)
                            )
                            ORDER BY nome_categoria
                        """, (genero_db, idade_calculada, idade_calculada, peso, peso))
                        categorias_disponiveis = cur.fetchall()
                    finally:
                        cur.close()
                        conn.close()
            except Exception as e:
                flash(f"Erro ao calcular categorias: {e}", "danger")
    
    # Garantir que categorias_disponiveis seja sempre uma lista
    if categorias_disponiveis is None:
        categorias_disponiveis = []
    
    return render_template(
        "painel_responsavel/simular_categorias.html",
        alunos=alunos,
        aluno=aluno,
        categorias_disponiveis=categorias_disponiveis,
        peso=peso,
        data_nascimento=data_nascimento or aluno_data_nasc_str,
        sexo=sexo,
        idade_calculada=idade_calculada,
    )


@bp_painel_responsavel.route("/associacao")
@login_required
@_aluno_id_responsavel_required
def associacao(aluno):
    """Associação do aluno."""
    from utils.contexto_logo import buscar_logo_url
    academias = []
    associacao_nome = None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_academia_aluno = aluno.get("id_academia")
        if id_academia_aluno:
            cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_academia_aluno,))
            row = cur.fetchone()
            id_associacao = row.get("id_associacao") if row else None
            if id_associacao:
                cur.execute("SELECT nome FROM associacoes WHERE id = %s", (id_associacao,))
                assoc = cur.fetchone()
                associacao_nome = assoc.get("nome") if assoc else None
                cur.execute("""
                    SELECT id, nome, cidade, uf, email, telefone
                    FROM academias WHERE id_associacao = %s
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
        voltar_url=url_for("painel_responsavel.meu_perfil", aluno_id=aluno["id"]),
    )
