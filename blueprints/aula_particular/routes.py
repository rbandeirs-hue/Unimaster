# ======================================================
# Blueprint: Aula particular
# ======================================================
"""Aulas particulares: o combinado de cada aluno e o registro de cada aula dada.

O professor cadastra o aluno (sempre um aluno cadastrado da academia — a
cobrança cai na conta dele), os dias da semana e o horário. No dia, a tela
"Hoje" lista as particulares que caem naquela data e cada uma se marca com um
clique — realizada, falta, cancelada ou remarcada — com o que foi trabalhado.

Cobrança, por particular:
  * mensal   — valor fixo por mês, gerado para o mês corrente;
  * por aula — valor por aula × aulas dadas no mês, gerado no fechamento.
Vai para `cobranca_avulsa` do aluno ("Aula particular — Setembro/2026"),
uma por mês (trava em `aula_particular_cobranca`). Só a gestão gera.

Escopo:
  * modo professor  — só as particulares do próprio professor, na academia
                      escolhida no topo (o professor tem um registro por academia);
  * modo academia   — gestor e admin veem todas da academia e escolhem o
                      professor; quem é só professor continua vendo só as suas.
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from config import get_db_connection

bp_aula_particular = Blueprint("aula_particular", __name__, url_prefix="/aulas-particulares")

DIAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]
DIAS_LONGOS = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]
TIPOS_COBRANCA = {"mensal": "Mensal (valor fixo por mês)", "por_aula": "Por aula (valor × aulas dadas no mês)"}
MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
         "Setembro", "Outubro", "Novembro", "Dezembro"]
STATUS = {
    "realizada": ("Realizada", "success"),
    "falta": ("Falta do aluno", "danger"),
    "cancelada": ("Cancelada", "info"),
    "remarcada": ("Remarcada", "warning"),
}


# ------------------------------------------------------------------ escopo
def _tem(*papeis):
    return any(current_user.has_role(p) for p in papeis)


def _escopo(cur):
    """Academia em foco, professor (fixo ou None = todos) e opções da tela."""
    modo = session.get("modo_painel") or ""
    gestor = _tem("admin", "gestor_academia") and modo != "professor"

    if gestor:
        from blueprints.eventos_competicoes.routes import _get_ids_academias
        ids = _get_ids_academias(cur) or []
    else:
        cur.execute("SELECT id, id_academia FROM professores WHERE usuario_id = %s AND ativo = 1",
                    (current_user.id,))
        meus = cur.fetchall()
        ids = [r["id_academia"] for r in meus if r["id_academia"]]
    if not ids:
        return None

    aid = request.values.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    if aid not in ids:
        aid = ids[0]
    cur.execute("SELECT id, nome FROM academias WHERE id = %s", (aid,))
    academia = cur.fetchone()

    cur.execute("""SELECT id, nome FROM professores WHERE id_academia = %s AND ativo = 1 ORDER BY nome""",
                (aid,))
    professores = cur.fetchall()
    professor_fixo = None
    if not gestor:
        cur.execute("SELECT id FROM professores WHERE usuario_id = %s AND id_academia = %s AND ativo = 1 LIMIT 1",
                    (current_user.id, aid))
        r = cur.fetchone()
        if not r:
            return None
        professor_fixo = r["id"]
        professores = [p for p in professores if p["id"] == professor_fixo]
    return {"academia_id": aid, "academia": academia, "gestor": gestor,
            "professor_fixo": professor_fixo, "professores": professores}


def _exige_escopo(cur):
    esc = _escopo(cur)
    if esc is None:
        flash("Aula particular é do professor vinculado à academia (ou da gestão).", "warning")
        return None, redirect(url_for("painel.home"))
    return esc, None


def _carregar(cur, esc, ap_id):
    """Aula particular do escopo, ou None."""
    cur.execute(
        f"""SELECT ap.*, COALESCE(a.nome, ap.aluno_nome) AS aluno,
                   COALESCE(a.tel_celular, a.telefone, ap.aluno_telefone) AS telefone,
                   p.nome AS professor_nome, m.nome AS modalidade_nome,
                   pl.nome AS plano_nome, pl.valor AS plano_valor, pl.periodicidade AS plano_periodicidade
            FROM aula_particular ap
            JOIN professores p ON p.id = ap.professor_id
            LEFT JOIN alunos a ON a.id = ap.aluno_id
            LEFT JOIN modalidade m ON m.id = ap.modalidade_id
            LEFT JOIN mensalidades pl ON pl.id = ap.mensalidade_id
            WHERE ap.id = %s AND ap.academia_id = %s""", (ap_id, esc["academia_id"]))
    ap = cur.fetchone()
    if ap and esc["professor_fixo"] and ap["professor_id"] != esc["professor_fixo"]:
        return None
    return _enriquecer(ap) if ap else None


# --------------------------------------------------------------- formato
def _dias(texto):
    return sorted({int(x) for x in str(texto or "").split(",") if x.strip().isdigit() and 0 <= int(x) <= 6})


def _hora(v):
    """TIME do MySQL vem como timedelta."""
    if v is None:
        return ""
    if isinstance(v, timedelta):
        m = int(v.total_seconds() // 60)
        return f"{m // 60:02d}:{m % 60:02d}"
    return v.strftime("%H:%M") if hasattr(v, "strftime") else str(v)[:5]


def _enriquecer(ap):
    ap["dias"] = _dias(ap.get("dias_semana"))
    ap["dias_txt"] = ", ".join(DIAS[d] for d in ap["dias"])
    ap["inicio"] = _hora(ap.get("hora_inicio"))
    ap["fim"] = _hora(ap.get("hora_fim"))
    _aplicar_plano(ap)
    if (ap.get("tipo_cobranca") or "por_aula") == "mensal":
        v = ap.get("valor_mensal")
        ap["valor_txt"] = (_reais(v) + "/mês") if v is not None else "—"
    else:
        v = ap.get("valor_aula")
        ap["valor_txt"] = (_reais(v) + "/aula") if v is not None else "—"
    return ap


def _aplicar_plano(ap):
    """Com plano, o tipo de cobrança e o valor vêm dele (e acompanham se o
    plano mudar no financeiro). Sem plano — particular antiga —, valem os
    campos da própria particular."""
    if not ap.get("mensalidade_id") or ap.get("plano_valor") is None:
        return ap
    if (ap.get("plano_periodicidade") or "mensal") == "diaria":
        ap["tipo_cobranca"], ap["valor_aula"], ap["valor_mensal"] = "por_aula", ap["plano_valor"], None
    else:
        ap["tipo_cobranca"], ap["valor_mensal"], ap["valor_aula"] = "mensal", ap["plano_valor"], None
    return ap


def _rotulo_plano(p):
    sufixo = "/aula" if (p.get("periodicidade") or "mensal") == "diaria" else "/mês"
    return f"{p['nome']} — {_reais(p['valor'])}{sufixo}"


def _reais(v):
    return ("R$ " + f"{float(v):,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


def _no_dia(ap, dia):
    """A particular cai nesta data? (dia da semana, período e ativa)."""
    if not ap.get("ativo"):
        return False
    if ap.get("data_inicio") and dia < ap["data_inicio"]:
        return False
    if ap.get("data_fim") and dia > ap["data_fim"]:
        return False
    return (dia.isoweekday() % 7) in ap["dias"]


def _lista(cur, esc, so_ativas=True, professor_id=None):
    filtros, params = ["ap.academia_id = %s"], [esc["academia_id"]]
    prof = esc["professor_fixo"] or professor_id
    if prof:
        filtros.append("ap.professor_id = %s")
        params.append(prof)
    if so_ativas:
        filtros.append("ap.ativo = 1")
    cur.execute(
        f"""SELECT ap.*, COALESCE(a.nome, ap.aluno_nome) AS aluno,
                   COALESCE(a.tel_celular, a.telefone, ap.aluno_telefone) AS telefone,
                   p.nome AS professor_nome, m.nome AS modalidade_nome,
                   pl.nome AS plano_nome, pl.valor AS plano_valor, pl.periodicidade AS plano_periodicidade
            FROM aula_particular ap
            JOIN professores p ON p.id = ap.professor_id
            LEFT JOIN alunos a ON a.id = ap.aluno_id
            LEFT JOIN modalidade m ON m.id = ap.modalidade_id
            LEFT JOIN mensalidades pl ON pl.id = ap.mensalidade_id
            WHERE {' AND '.join(filtros)}
            ORDER BY ap.hora_inicio, aluno""", tuple(params))
    return [_enriquecer(r) for r in cur.fetchall()]


def _conflitos(cur, academia_id, professor_id, dias, ini, fim, d_ini, d_fim, ignorar_id=None):
    """Outras particulares do mesmo professor que batem dia e horário."""
    cur.execute(
        """SELECT ap.*, COALESCE(a.nome, ap.aluno_nome) AS aluno FROM aula_particular ap
           LEFT JOIN alunos a ON a.id = ap.aluno_id
           WHERE ap.professor_id = %s AND ap.ativo = 1 AND ap.id <> %s
             AND ap.hora_inicio < %s AND ap.hora_fim > %s
             AND (ap.data_fim IS NULL OR ap.data_fim >= %s)
             AND (%s IS NULL OR ap.data_inicio <= %s)""",
        (professor_id, ignorar_id or 0, fim, ini, d_ini, d_fim, d_fim))
    out = []
    for r in cur.fetchall():
        comuns = set(_dias(r["dias_semana"])) & set(dias)
        if comuns:
            out.append(f"{r['aluno']} ({', '.join(DIAS[d] for d in sorted(comuns))} "
                       f"{_hora(r['hora_inicio'])}–{_hora(r['hora_fim'])})")
    return out


# --------------------------------------------------------------- cobrança
def _mes(competencia):
    ano, mes = (int(x) for x in competencia.split("-"))
    ini = date(ano, mes, 1)
    return ini, (ini.replace(day=28) + timedelta(days=4)).replace(day=1)


def _aulas_dadas(cur, ap_id, ini, fim):
    cur.execute("""SELECT COUNT(*) AS n FROM aula_particular_registro
                   WHERE aula_particular_id = %s AND status = 'realizada' AND data >= %s AND data < %s""",
                (ap_id, ini, fim))
    return cur.fetchone()["n"]


def cobranca_do_mes(cur, ap_id, competencia):
    """Cobrança já gerada para o mês, ou None.

    Traz a situação da mensalidade (particular com plano) ou da avulsa
    (gerada antes de a particular ter plano) em `status`, `valor_cobranca`…
    """
    cur.execute(
        """SELECT apc.*,
                  COALESCE(ma.status, ca.status) AS status,
                  COALESCE(ma.data_vencimento, ca.data_vencimento) AS data_vencimento,
                  COALESCE(ma.asaas_payment_id, ca.asaas_payment_id) AS asaas_payment_id,
                  COALESCE(ma.valor, ca.valor) AS valor_cobranca,
                  ma.status_pagamento
           FROM aula_particular_cobranca apc
           LEFT JOIN mensalidade_aluno ma ON ma.id = apc.mensalidade_aluno_id
           LEFT JOIN cobranca_avulsa ca ON ca.id = apc.cobranca_avulsa_id AND apc.mensalidade_aluno_id IS NULL
           WHERE apc.aula_particular_id = %s AND apc.competencia = %s""", (ap_id, competencia))
    return cur.fetchone()


def gerar_cobranca(cur, ap_id, competencia):
    """Gera (ou atualiza) a cobrança do mês na conta do aluno. Retorna (ok, mensagem).

    mensal   → valor_mensal, vence no dia combinado do próprio mês;
    por aula → aulas dadas no mês × valor_aula, vence no dia combinado do mês
               seguinte (a conta só fecha depois que o mês acaba).
    Já gerada e em aberto: se o valor mudou (aula registrada depois), atualiza —
    a menos que já tenha PIX/boleto emitido, que não dá para mudar por fora.
    """
    cur.execute("""SELECT ap.*, a.nome AS aluno, a.dia_vencimento AS dia_aluno,
                          pl.nome AS plano_nome, pl.valor AS plano_valor, pl.periodicidade AS plano_periodicidade
                   FROM aula_particular ap JOIN alunos a ON a.id = ap.aluno_id
                   LEFT JOIN mensalidades pl ON pl.id = ap.mensalidade_id
                   WHERE ap.id = %s""", (ap_id,))
    ap = cur.fetchone()
    if ap:
        _aplicar_plano(ap)
    if not ap:
        return False, "Aula particular sem aluno cadastrado — edite e escolha o aluno."
    try:
        from utils.modulos import tem_financeiro
        if not tem_financeiro(ap["academia_id"]):
            return False, "A academia não usa o módulo financeiro."
    except Exception:
        pass
    ini, fim = _mes(competencia)
    nome_mes = f"{MESES[ini.month]}/{ini.year}"
    qtd = _aulas_dadas(cur, ap_id, ini, fim)
    dia = ap.get("dia_vencimento") or ap.get("dia_aluno") or 10
    dia = max(1, min(int(dia), 28))
    if (ap.get("tipo_cobranca") or "por_aula") == "mensal":
        valor = float(ap.get("valor_mensal") or 0)
        venc = ini.replace(day=dia)
        descricao = f"Aula particular — {nome_mes}"
    else:
        if not qtd:
            return False, f"{ap['aluno']}: nenhuma aula dada em {nome_mes} — nada a cobrar."
        valor = round(qtd * float(ap.get("valor_aula") or 0), 2)
        venc = fim.replace(day=dia)
        descricao = f"Aula particular — {nome_mes} ({qtd} aula{'s' if qtd != 1 else ''})"
    if valor <= 0:
        return False, f"{ap['aluno']}: valor da aula particular não informado."
    venc = max(venc, date.today())

    atual = cobranca_do_mes(cur, ap_id, competencia)
    if atual and (atual.get("status") == "pago" or atual.get("status_pagamento") == "pago"):
        return False, f"{ap['aluno']}: a cobrança de {nome_mes} já foi paga."
    if atual and atual.get("status") in ("pendente", "atrasado"):
        if abs(float(atual["valor_cobranca"] or 0) - valor) < 0.005:
            return False, f"{ap['aluno']}: a cobrança de {nome_mes} já está gerada."
        if atual.get("asaas_payment_id"):
            return False, (f"{ap['aluno']}: o valor de {nome_mes} mudou, mas a cobrança já tem PIX/boleto "
                           "emitido — cancele-a no financeiro e gere de novo.")
        if atual.get("mensalidade_aluno_id"):
            cur.execute("""UPDATE mensalidade_aluno SET valor = %s, valor_original = %s, observacoes = %s
                           WHERE id = %s""", (valor, valor, descricao[:255], atual["mensalidade_aluno_id"]))
        else:
            cur.execute("UPDATE cobranca_avulsa SET valor = %s, descricao = %s WHERE id = %s",
                        (valor, descricao[:255], atual["cobranca_avulsa_id"]))
        cur.execute("UPDATE aula_particular_cobranca SET valor = %s, qtd_aulas = %s WHERE id = %s",
                    (valor, qtd, atual["id"]))
        return True, f"{ap['aluno']}: cobrança de {nome_mes} atualizada para {_reais(valor)}."

    ma_id = cob_id = None
    if ap.get("mensalidade_id"):
        # Com plano: mensalidade do aluno, como qualquer outra — aparece em
        # Mensalidades, entra na régua, no PIX e nos relatórios do plano.
        cur.execute(
            """INSERT INTO mensalidade_aluno
                   (mensalidade_id, aluno_id, data_vencimento, valor, valor_original, desconto_aplicado,
                    status, status_pagamento, observacoes, competencia, snapshot_pacote_nome)
               VALUES (%s,%s,%s,%s,%s,0,'pendente','pendente',%s,%s,%s)""",
            (ap["mensalidade_id"], ap["aluno_id"], venc, valor, valor, descricao[:255],
             competencia, (ap.get("plano_nome") or "")[:150]))
        ma_id = cur.lastrowid
    else:
        cur.execute(
            """INSERT INTO cobranca_avulsa
                   (aluno_id, id_academia, descricao, valor, data_vencimento, status, observacoes, criado_por)
               VALUES (%s,%s,%s,%s,%s,'pendente',%s,%s)""",
            (ap["aluno_id"], ap["academia_id"], descricao[:255], valor, venc,
             f"Aula particular #{ap_id}", current_user.id))
        cob_id = cur.lastrowid
    if atual:  # a anterior foi cancelada: a nova toma o lugar
        cur.execute("""UPDATE aula_particular_cobranca SET cobranca_avulsa_id = %s, mensalidade_aluno_id = %s,
                       valor = %s, qtd_aulas = %s, gerado_por = %s WHERE id = %s""",
                    (cob_id, ma_id, valor, qtd, current_user.id, atual["id"]))
    else:
        cur.execute("""INSERT INTO aula_particular_cobranca
                           (aula_particular_id, competencia, cobranca_avulsa_id, mensalidade_aluno_id,
                            qtd_aulas, valor, gerado_por)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (ap_id, competencia, cob_id, ma_id, qtd, valor, current_user.id))
    tipo_txt = "mensalidade" if ma_id else "cobrança"
    return True, f"{ap['aluno']}: {tipo_txt} de {nome_mes} gerada — {_reais(valor)}, vence {venc:%d/%m/%Y}."


def _competencia_do_form():
    bruto = (request.form.get("competencia") or "").strip()
    try:
        _mes(bruto)
        return bruto
    except (ValueError, TypeError):
        return date.today().strftime("%Y-%m")


@bp_aula_particular.route("/<int:ap_id>/cobrar", methods=["POST"])
@login_required
def cobrar(ap_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ap = _carregar(cur, esc, ap_id)
        if not ap or not esc["gestor"]:
            flash("Só a gestão da academia gera cobrança.", "danger")
            return redirect(url_for("aula_particular.lista"))
        competencia = _competencia_do_form()
        ok, msg = gerar_cobranca(cur, ap_id, competencia)
        conn.commit()
        flash(msg, "success" if ok else "warning")
        return redirect(url_for("aula_particular.historico", ap_id=ap_id, mes=competencia))
    finally:
        cur.close()
        conn.close()


@bp_aula_particular.route("/cobrar-mes", methods=["POST"])
@login_required
def cobrar_mes():
    """Gera as cobranças do mês de todas as particulares ativas da academia."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        if not esc["gestor"]:
            flash("Só a gestão da academia gera cobrança.", "danger")
            return redirect(url_for("aula_particular.lista"))
        competencia = _competencia_do_form()
        ini, fim = _mes(competencia)
        cur.execute("""SELECT id FROM aula_particular WHERE academia_id = %s AND aluno_id IS NOT NULL
                       AND data_inicio < %s AND (data_fim IS NULL OR data_fim >= %s)""",
                    (esc["academia_id"], fim, ini))
        ids = [r["id"] for r in cur.fetchall()]
        geradas, avisos = 0, []
        for i in ids:
            ok, msg = gerar_cobranca(cur, i, competencia)
            if ok:
                geradas += 1
            elif "já está gerada" not in msg:
                avisos.append(msg)
        conn.commit()
        flash(f"{MESES[ini.month]}/{ini.year}: {geradas} cobrança{'s' if geradas != 1 else ''} "
              f"gerada{'s' if geradas != 1 else ''} ou atualizada{'s' if geradas != 1 else ''}.", "success")
        for a in avisos[:8]:
            flash(a, "warning")
        return redirect(url_for("aula_particular.lista"))
    finally:
        cur.close()
        conn.close()


# ------------------------------------------------------------------ telas
@bp_aula_particular.route("/")
@login_required
def lista():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        prof_filtro = request.args.get("professor_id", type=int) if esc["gestor"] else None
        ativas = _lista(cur, esc, True, prof_filtro)

        hoje = date.today()
        dia = hoje
        if request.args.get("dia"):
            try:
                dia = date.fromisoformat(request.args["dia"])
            except ValueError:
                pass
        do_dia = [ap for ap in ativas if _no_dia(ap, dia)]
        if do_dia:
            ids = [ap["id"] for ap in do_dia]
            cur.execute(f"""SELECT * FROM aula_particular_registro
                            WHERE data = %s AND aula_particular_id IN ({','.join(['%s'] * len(ids))})""",
                        (dia, *ids))
            regs = {r["aula_particular_id"]: r for r in cur.fetchall()}
            for ap in do_dia:
                ap["registro"] = regs.get(ap["id"])

        # Agenda da semana: segunda a domingo, horários em ordem.
        agenda = []
        for d in [1, 2, 3, 4, 5, 6, 0]:
            agenda.append({"dia": d, "nome": DIAS_LONGOS[d],
                           "aulas": [ap for ap in ativas if d in ap["dias"]]})

        cur.execute(f"""SELECT COUNT(*) AS n FROM aula_particular_registro r
                        JOIN aula_particular ap ON ap.id = r.aula_particular_id
                        WHERE ap.academia_id = %s AND r.status = 'realizada'
                          AND r.data >= %s {'AND ap.professor_id = %s' if (esc['professor_fixo'] or prof_filtro) else ''}""",
                    (esc["academia_id"], hoje.replace(day=1))
                    + (((esc["professor_fixo"] or prof_filtro),) if (esc["professor_fixo"] or prof_filtro) else ()))
        realizadas_mes = cur.fetchone()["n"]
        return render_template(
            "aula_particular/lista.html", esc=esc, ativas=ativas, do_dia=do_dia, dia=dia, hoje=hoje,
            agenda=agenda, realizadas_mes=realizadas_mes, prof_filtro=prof_filtro, STATUS=STATUS,
            dia_anterior=dia - timedelta(days=1), dia_seguinte=dia + timedelta(days=1),
            nome_dia=DIAS_LONGOS[dia.isoweekday() % 7], MESES=MESES,
            competencias=[(hoje.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"), hoje.strftime("%Y-%m")])
    finally:
        cur.close()
        conn.close()


def _opcoes_form(cur, esc):
    cur.execute("""SELECT id, nome FROM alunos WHERE id_academia = %s AND ativo = 1
                   AND status = 'ativo' ORDER BY nome""", (esc["academia_id"],))
    alunos = cur.fetchall()
    cur.execute("""SELECT m.id, m.nome FROM modalidade m JOIN academia_modalidades am ON am.modalidade_id = m.id
                   WHERE am.academia_id = %s ORDER BY m.nome""", (esc["academia_id"],))
    return alunos, cur.fetchall()


def _planos(cur, academia_id):
    """Planos ativos da academia — mensais e diários — para a particular."""
    cur.execute("""SELECT id, nome, valor, COALESCE(periodicidade, 'mensal') AS periodicidade
                   FROM mensalidades WHERE id_academia = %s AND COALESCE(ativo, 1) = 1
                   ORDER BY periodicidade = 'diaria' DESC, nome""", (academia_id,))
    planos = cur.fetchall()
    from utils.planos_modalidade import filtrar_contexto
    planos = filtrar_contexto(cur, planos, academia_id)
    for p in planos:
        p["rotulo"] = _rotulo_plano(p)
    return planos


@bp_aula_particular.route("/nova", methods=["GET", "POST"])
@bp_aula_particular.route("/<int:ap_id>/editar", methods=["GET", "POST"])
@login_required
def editar(ap_id=None):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ap = None
        if ap_id:
            ap = _carregar(cur, esc, ap_id)
            if not ap:
                flash("Aula particular não encontrada.", "danger")
                return redirect(url_for("aula_particular.lista"))
        alunos, modalidades = _opcoes_form(cur, esc)

        if request.method == "POST":
            f = request.form
            erros = []
            professor_id = esc["professor_fixo"] or f.get("professor_id", type=int)
            if professor_id not in [p["id"] for p in esc["professores"]]:
                erros.append("Escolha o professor.")
            # Sempre aluno cadastrado: a cobrança é gerada na conta dele.
            aluno_id = f.get("aluno_id", type=int)
            aluno_nome = aluno_tel = None
            if aluno_id not in [a["id"] for a in alunos]:
                erros.append("Escolha o aluno (cadastre-o antes, se ainda não for aluno da academia).")
            dias = _dias(",".join(f.getlist("dias")))
            if not dias:
                erros.append("Marque ao menos um dia da semana.")
            ini, fim = (f.get("hora_inicio") or "").strip(), (f.get("hora_fim") or "").strip()
            try:
                t_ini = datetime.strptime(ini, "%H:%M").time()
                t_fim = datetime.strptime(fim, "%H:%M").time()
                if t_fim <= t_ini:
                    erros.append("O horário de término tem que ser depois do início.")
            except ValueError:
                erros.append("Informe o horário de início e de término.")
                t_ini = t_fim = None
            try:
                d_ini = date.fromisoformat(f.get("data_inicio") or date.today().isoformat())
                d_fim = date.fromisoformat(f["data_fim"]) if f.get("data_fim") else None
                if d_fim and d_fim < d_ini:
                    erros.append("O fim do período tem que ser depois do início.")
            except ValueError:
                erros.append("Data inválida.")
                d_ini, d_fim = date.today(), None
            # Plano: um existente da academia ou um novo, criado aqui mesmo.
            planos = _planos(cur, esc["academia_id"])
            plano_escolhido = f.get("mensalidade_id") or ""
            novo_plano = None
            if plano_escolhido == "novo":
                if not esc["gestor"]:
                    erros.append("Só a gestão cria plano novo — escolha um plano existente.")
                novo_plano = {"nome": (f.get("plano_nome") or "").strip()[:120] or "Aula particular",
                              "periodicidade": "diaria" if f.get("plano_periodicidade") == "diaria" else "mensal"}
            else:
                plano_escolhido = int(plano_escolhido) if str(plano_escolhido).isdigit() else None
                if plano_escolhido not in [p["id"] for p in planos]:
                    erros.append("Escolha o plano de mensalidade da aula particular.")

            def _dinheiro(campo, rotulo):
                bruto = (f.get(campo) or "").strip().replace("R$", "").strip()
                if not bruto:
                    return None
                if "," in bruto:
                    bruto = bruto.replace(".", "").replace(",", ".")
                try:
                    v = round(float(bruto), 2)
                    if v < 0:
                        raise ValueError
                    return v
                except ValueError:
                    erros.append(f"{rotulo} inválido.")
                    return None
            if novo_plano is not None:
                novo_plano["valor"] = _dinheiro("plano_valor", "Valor do plano")
                if not novo_plano["valor"]:
                    erros.append("Informe o valor do plano novo.")
            valor = valor_mensal = None
            tipo_cob = "mensal"
            dia_venc = f.get("dia_vencimento", type=int)
            if dia_venc is not None and not (1 <= dia_venc <= 28):
                erros.append("Dia de vencimento deve ser de 1 a 28.")
            mod = f.get("modalidade_id", type=int)
            mod = mod if mod in [m["id"] for m in modalidades] else None
            if erros:
                for e in erros:
                    flash(e, "danger")
                return render_template("aula_particular/form.html", esc=esc, ap=ap, form=f,
                                       alunos=alunos, modalidades=modalidades, DIAS=DIAS,
                                       TIPOS_COBRANCA=TIPOS_COBRANCA, planos=planos)
            if novo_plano is not None:
                cur.execute(
                    """INSERT INTO mensalidades (nome, descricao, valor, id_academia, ativo, periodicidade)
                       VALUES (%s,%s,%s,%s,1,%s)""",
                    (novo_plano["nome"], "Plano de aula particular", novo_plano["valor"],
                     esc["academia_id"], novo_plano["periodicidade"]))
                plano_escolhido = cur.lastrowid
                # Plano nasce na modalidade da particular (valor inteiro nela).
                if mod:
                    from utils.planos_modalidade import gravar as gravar_mods
                    gravar_mods(cur, plano_escolhido, [(mod, novo_plano["valor"], 1)])
                planos.append({"id": plano_escolhido, "periodicidade": novo_plano["periodicidade"]})
            _pl = next(p for p in planos if p["id"] == plano_escolhido)
            tipo_cob = "por_aula" if _pl["periodicidade"] == "diaria" else "mensal"
            dados = (professor_id, aluno_id, aluno_nome, aluno_tel, mod, ",".join(map(str, dias)),
                     t_ini, t_fim, (f.get("local") or "").strip()[:150] or None, valor, d_ini, d_fim,
                     (f.get("observacoes") or "").strip() or None, tipo_cob, valor_mensal, dia_venc,
                     plano_escolhido)
            if ap:
                cur.execute(
                    """UPDATE aula_particular SET professor_id=%s, aluno_id=%s, aluno_nome=%s, aluno_telefone=%s,
                           modalidade_id=%s, dias_semana=%s, hora_inicio=%s, hora_fim=%s, local=%s,
                           valor_aula=%s, data_inicio=%s, data_fim=%s, observacoes=%s,
                           tipo_cobranca=%s, valor_mensal=%s, dia_vencimento=%s, mensalidade_id=%s, ativo=1
                       WHERE id=%s""", dados + (ap["id"],))
                novo_id = ap["id"]
            else:
                cur.execute(
                    """INSERT INTO aula_particular (professor_id, aluno_id, aluno_nome, aluno_telefone,
                           modalidade_id, dias_semana, hora_inicio, hora_fim, local, valor_aula,
                           data_inicio, data_fim, observacoes, tipo_cobranca, valor_mensal,
                           dia_vencimento, mensalidade_id, academia_id, criado_por)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    dados + (esc["academia_id"], current_user.id))
                novo_id = cur.lastrowid
            conn.commit()
            choques = _conflitos(cur, esc["academia_id"], professor_id, dias, t_ini, t_fim, d_ini, d_fim, novo_id)
            flash("Aula particular salva.", "success")
            # Mensal: já deixa a cobrança do mês corrente na conta do aluno.
            if esc["gestor"] and tipo_cob == "mensal" and f.get("gerar_agora"):
                _ok, _msg = gerar_cobranca(cur, novo_id, date.today().strftime("%Y-%m"))
                conn.commit()
                flash(_msg, "success" if _ok else "warning")
            if choques:
                flash("Atenção: o professor já tem particular no mesmo horário — " + "; ".join(choques) + ".",
                      "warning")
            return redirect(url_for("aula_particular.historico", ap_id=novo_id))

        form = {}
        if ap:
            form = {"professor_id": ap["professor_id"], "aluno_id": ap.get("aluno_id"),
                    "origem_aluno": "fora" if not ap.get("aluno_id") and ap.get("aluno_nome") else "academia",
                    "aluno_nome": ap.get("aluno_nome") or "", "aluno_telefone": ap.get("aluno_telefone") or "",
                    "modalidade_id": ap.get("modalidade_id"), "hora_inicio": ap["inicio"], "hora_fim": ap["fim"],
                    "local": ap.get("local") or "", "data_inicio": ap["data_inicio"].isoformat(),
                    "data_fim": ap["data_fim"].isoformat() if ap.get("data_fim") else "",
                    "valor_aula": ("%.2f" % ap["valor_aula"]).replace(".", ",") if ap.get("valor_aula") is not None else "",
                    "valor_mensal": ("%.2f" % ap["valor_mensal"]).replace(".", ",") if ap.get("valor_mensal") is not None else "",
                    "tipo_cobranca": ap.get("tipo_cobranca") or "por_aula",
                    "mensalidade_id": ap.get("mensalidade_id") or "",
                    "dia_vencimento": ap.get("dia_vencimento") or "",
                    "observacoes": ap.get("observacoes") or ""}
        else:
            form = {"data_inicio": date.today().isoformat(), "tipo_cobranca": "mensal",
                    "aluno_id": request.args.get("aluno_id", type=int), "gerar_agora": "1"}
        return render_template("aula_particular/form.html", esc=esc, ap=ap, form=form,
                               alunos=alunos, modalidades=modalidades, DIAS=DIAS,
                               dias_marcados=ap["dias"] if ap else [], TIPOS_COBRANCA=TIPOS_COBRANCA,
                               planos=_planos(cur, esc["academia_id"]))
    finally:
        cur.close()
        conn.close()


@bp_aula_particular.route("/<int:ap_id>/encerrar", methods=["POST"])
@login_required
def encerrar(ap_id):
    """Encerra o combinado: some da agenda, o histórico fica."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ap = _carregar(cur, esc, ap_id)
        if not ap:
            flash("Aula particular não encontrada.", "danger")
            return redirect(url_for("aula_particular.lista"))
        reativar = bool(request.form.get("reativar"))
        cur.execute("UPDATE aula_particular SET ativo = %s, data_fim = %s WHERE id = %s",
                    (1 if reativar else 0, None if reativar else date.today(), ap_id))
        conn.commit()
        flash(f"Aula particular de {ap['aluno']} " + ("reativada." if reativar else "encerrada."), "success")
        return redirect(url_for("aula_particular.historico", ap_id=ap_id))
    finally:
        cur.close()
        conn.close()


@bp_aula_particular.route("/<int:ap_id>/registrar", methods=["POST"])
@login_required
def registrar(ap_id):
    """Registra (ou corrige) a aula de uma data: situação, horário e conteúdo."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    destino = request.form.get("voltar") or url_for("aula_particular.historico", ap_id=ap_id)
    if not destino.startswith("/") or destino.startswith("//"):
        destino = url_for("aula_particular.historico", ap_id=ap_id)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ap = _carregar(cur, esc, ap_id)
        if not ap:
            flash("Aula particular não encontrada.", "danger")
            return redirect(url_for("aula_particular.lista"))
        status = request.form.get("status")
        if status not in STATUS:
            flash("Situação inválida.", "danger")
            return redirect(destino)
        try:
            dia = date.fromisoformat(request.form.get("data") or date.today().isoformat())
        except ValueError:
            flash("Data inválida.", "danger")
            return redirect(destino)
        if dia > date.today():
            flash("Não dá para registrar uma aula que ainda não aconteceu.", "warning")
            return redirect(destino)

        def _t(campo, padrao):
            try:
                return datetime.strptime(request.form.get(campo) or "", "%H:%M").time()
            except ValueError:
                return padrao
        conteudo = (request.form.get("conteudo") or "").strip() or None
        cur.execute(
            """INSERT INTO aula_particular_registro
                   (aula_particular_id, data, hora_inicio, hora_fim, status, conteudo, registrado_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE hora_inicio=VALUES(hora_inicio), hora_fim=VALUES(hora_fim),
                   status=VALUES(status), conteudo=COALESCE(VALUES(conteudo), conteudo),
                   registrado_por=VALUES(registrado_por)""",
            (ap_id, dia, _t("hora_inicio", ap.get("hora_inicio")), _t("hora_fim", ap.get("hora_fim")),
             status, conteudo, current_user.id))
        conn.commit()
        flash(f"{ap['aluno']} — {dia:%d/%m}: {STATUS[status][0].lower()}.", "success")
        return redirect(destino)
    finally:
        cur.close()
        conn.close()


@bp_aula_particular.route("/registro/<int:reg_id>/excluir", methods=["POST"])
@login_required
def excluir_registro(reg_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        cur.execute("SELECT aula_particular_id FROM aula_particular_registro WHERE id = %s", (reg_id,))
        r = cur.fetchone()
        ap = _carregar(cur, esc, r["aula_particular_id"]) if r else None
        if not ap:
            flash("Registro não encontrado.", "danger")
            return redirect(url_for("aula_particular.lista"))
        cur.execute("DELETE FROM aula_particular_registro WHERE id = %s", (reg_id,))
        conn.commit()
        flash("Registro removido.", "success")
        return redirect(url_for("aula_particular.historico", ap_id=ap["id"]))
    finally:
        cur.close()
        conn.close()


@bp_aula_particular.route("/<int:ap_id>")
@login_required
def historico(ap_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ap = _carregar(cur, esc, ap_id)
        if not ap:
            flash("Aula particular não encontrada.", "danger")
            return redirect(url_for("aula_particular.lista"))
        hoje = date.today()
        try:
            ano, mes = (int(x) for x in (request.args.get("mes") or f"{hoje:%Y-%m}").split("-"))
            ini = date(ano, mes, 1)
        except ValueError:
            ini = hoje.replace(day=1)
        fim = (ini.replace(day=28) + timedelta(days=4)).replace(day=1)
        cur.execute(
            """SELECT r.*, u.nome AS registrado_por_nome FROM aula_particular_registro r
               LEFT JOIN usuarios u ON u.id = r.registrado_por
               WHERE r.aula_particular_id = %s AND r.data >= %s AND r.data < %s
               ORDER BY r.data DESC""", (ap_id, ini, fim))
        registros = cur.fetchall()
        for r in registros:
            r["inicio"], r["fim"] = _hora(r.get("hora_inicio")), _hora(r.get("hora_fim"))
        # Dias previstos no mês que ainda não têm registro (até hoje).
        feitos = {r["data"] for r in registros}
        pendentes, d = [], ini
        while d < fim and d <= hoje:
            if _no_dia(ap, d) and d not in feitos:
                pendentes.append(d)
            d += timedelta(days=1)
        previstas, d = 0, ini
        while d < fim:
            previstas += 1 if _no_dia(ap, d) else 0
            d += timedelta(days=1)
        contagem = {k: sum(1 for r in registros if r["status"] == k) for k in STATUS}
        if (ap.get("tipo_cobranca") or "por_aula") == "mensal":
            valor_mes = float(ap["valor_mensal"]) if ap.get("valor_mensal") is not None else None
        else:
            valor_mes = (float(ap["valor_aula"]) * contagem["realizada"]) if ap.get("valor_aula") is not None else None
        cobranca = cobranca_do_mes(cur, ap_id, ini.strftime("%Y-%m"))
        return render_template(
            "aula_particular/historico.html", esc=esc, ap=ap, registros=registros, pendentes=pendentes,
            contagem=contagem, previstas=previstas, valor_mes=valor_mes, STATUS=STATUS, hoje=hoje,
            cobranca=cobranca, competencia=ini.strftime("%Y-%m"),
            mes_ini=ini, mes_ant=(ini - timedelta(days=1)).strftime("%Y-%m"), mes_prox=fim.strftime("%Y-%m"),
            DIAS_LONGOS=DIAS_LONGOS)
    finally:
        cur.close()
        conn.close()
