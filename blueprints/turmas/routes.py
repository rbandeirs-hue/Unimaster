# ======================================================
# 🧩 Blueprint: Turmas
# ======================================================
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
# Importamos current_user para acessar o perfil do usuário logado
from flask_login import login_required, current_user
from config import get_db_connection
from utils.modalidades import filtro_visibilidade_sql

bp_turmas = Blueprint("turmas", __name__)

# ======================================================
# 🔹 Academias disponíveis conforme o perfil
# ======================================================
def carregar_academias_do_usuario(cursor):
    if current_user.has_role("admin"):
        cursor.execute("SELECT id, nome FROM academias ORDER BY nome")
    elif current_user.has_role("gestor_federacao"):
        cursor.execute("""
            SELECT ac.id, ac.nome
            FROM academias ac
            JOIN associacoes ass ON ass.id = ac.id_associacao
            WHERE ass.id_federacao = %s
            ORDER BY ac.nome
        """, (getattr(current_user, "id_federacao", None),))
    elif current_user.has_role("gestor_associacao"):
        cursor.execute("""
            SELECT id, nome
            FROM academias
            WHERE id_associacao = %s
            ORDER BY nome
        """, (getattr(current_user, "id_associacao", None),))
    else:
        cursor.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        ids = [r["academia_id"] for r in cursor.fetchall()]
        if ids:
            ph = ",".join(["%s"] * len(ids))
            cursor.execute(f"SELECT id, nome FROM academias WHERE id IN ({ph}) ORDER BY nome", tuple(ids))
        else:
            return []

    return cursor.fetchall()


def _get_academias_ids():
    """IDs de academias acessíveis (prioridade: usuarios_academias, alinhado ao gerenciamento)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas:
            cur.close()
            conn.close()
            return vinculadas
        # Modo academia: gestor_academia/professor só veem academias de usuarios_academias (não id_academia)
        if session.get("modo_painel") == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
            cur.close()
            conn.close()
            return []
        ids = []
        if current_user.has_role("admin"):
            cur.execute("SELECT id FROM academias ORDER BY nome")
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT ac.id FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s ORDER BY ac.nome",
                (getattr(current_user, "id_federacao", None),),
            )
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome", (getattr(current_user, "id_associacao", None),))
            ids = [r["id"] for r in cur.fetchall()]
        else:
            ids = []
        cur.close()
        conn.close()
        return ids
    except Exception:
        return []


# Função auxiliar para obter o perfil de forma segura
def get_user_profile():
    """Retorna o perfil do usuário logado ou 'Visitante' se não estiver definido."""
    # Assumimos que o objeto current_user tem um atributo 'perfil'
    return getattr(current_user, 'perfil', 'Visitante')

# ======================================================
# 🔹 Página principal do módulo Turmas (Painel de Opções)
# Corrigido para passar a variável 'perfil'
# ======================================================
@bp_turmas.route('/turmas/painel', methods=['GET'])
@login_required
def painel_turmas():
    perfil_usuario = get_user_profile()
    # 🚨 CORREÇÃO: Passando 'perfil' para o template
    return render_template('turma.html', perfil=perfil_usuario)


# ======================================================
# 🔹 Listar Turmas
# Corrigido para passar a variável 'perfil'
# ======================================================
@bp_turmas.route('/turmas', methods=['GET'])
@login_required
def lista_turmas():
    perfil_usuario = get_user_profile()
    ids_acessiveis = _get_academias_ids()
    academia_filtro = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    if academia_filtro and academia_filtro in ids_acessiveis:
        session["academia_gerenciamento_id"] = academia_filtro
        session["finance_academia_id"] = academia_filtro

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    busca = request.args.get('busca', '').strip()
    query = "SELECT * FROM turmas"
    params = []
    filters = []

    if academia_filtro and academia_filtro in ids_acessiveis:
        filters.append("id_academia = %s")
        params.append(academia_filtro)
    if busca:
        filters.append("(Nome LIKE %s OR Professor LIKE %s OR DiasHorario LIKE %s)")
        params.extend(['%' + busca + '%', '%' + busca + '%', '%' + busca + '%'])
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY Nome"

    cursor.execute(query, tuple(params))
    turmas = cursor.fetchall()

    # Contagem de alunos por turma (aluno_turmas + alunos.TurmaID legado)
    turma_ids = [t["TurmaID"] for t in turmas]
    matricula_por_turma = {}
    if turma_ids:
        ph = ",".join(["%s"] * len(turma_ids))
        cursor.execute(
            f"""SELECT TurmaID, COUNT(DISTINCT aluno_id) AS c FROM aluno_turmas WHERE TurmaID IN ({ph}) GROUP BY TurmaID""",
            tuple(turma_ids),
        )
        for r in cursor.fetchall():
            matricula_por_turma[r["TurmaID"]] = r["c"]
        for tid in turma_ids:
            cursor.execute(
                """SELECT COUNT(*) AS c FROM alunos a WHERE a.TurmaID = %s
                   AND a.id NOT IN (SELECT aluno_id FROM aluno_turmas WHERE TurmaID = %s)""",
                (tid, tid),
            )
            legado = cursor.fetchone()
            if legado and legado["c"]:
                matricula_por_turma[tid] = matricula_por_turma.get(tid, 0) + legado["c"]
    # Modalidade por turma
    modalidades_por_turma = {}
    if turma_ids:
        cursor.execute(
            """SELECT tm.turma_id, m.id, m.nome
               FROM turma_modalidades tm
               JOIN modalidade m ON m.id = tm.modalidade_id
               WHERE tm.turma_id IN (%s)
               ORDER BY m.nome""" % ",".join(["%s"] * len(turma_ids)),
            tuple(turma_ids),
        )
        for r in cursor.fetchall():
            tid = r["turma_id"]
            if tid not in modalidades_por_turma:
                modalidades_por_turma[tid] = []
            modalidades_por_turma[tid].append({"id": r["id"], "nome": r["nome"]})

    def _fmt_horario_turma(t):
        ds = t.get("dias_semana")
        hi, hf = t.get("hora_inicio"), t.get("hora_fim")
        if ds and (hi or hf):
            dias_nomes = {'0':'Dom','1':'Seg','2':'Ter','3':'Qua','4':'Qui','5':'Sex','6':'Sáb'}
            dias_str = '/'.join(dias_nomes.get(d,'') for d in (ds or '').split(',') if d)
            hi_str = hi.strftime("%H:%M") if hasattr(hi, "strftime") else (str(hi)[:5] if hi else "")
            hf_str = hf.strftime("%H:%M") if hasattr(hf, "strftime") else (str(hf)[:5] if hf else "")
            if hi_str and hf_str:
                return f"{dias_str} - {hi_str} às {hf_str}"
            return dias_str or t.get("DiasHorario") or "—"
        return t.get("DiasHorario") or "—"

    for t in turmas:
        t["horario_display"] = _fmt_horario_turma(t)
        cnt = matricula_por_turma.get(t["TurmaID"], 0)
        cap = t.get("Capacidade") or 0
        controla = t.get("controla_limite") or 0
        t["matricula_count"] = cnt
        if controla and cap > 0:
            t["vagas_display"] = f"{cnt}/{cap}"
            t["pode_matricular"] = cnt < cap
            t["vagas_ilimitada"] = False
            t["vagas_cheia"] = cnt >= cap
        else:
            t["vagas_display"] = "ilimitada"
            t["pode_matricular"] = True
            t["vagas_ilimitada"] = True
            t["vagas_cheia"] = False
        mods = modalidades_por_turma.get(t["TurmaID"], [])
        t["modalidade_nome"] = ", ".join(m["nome"] for m in mods) if mods else "Sem modalidade"
        t["modalidade_id"] = mods[0]["id"] if mods else None
        t["modalidades"] = mods

    # Professor responsável (para exibir no card)
    responsavel_por_turma = {}
    if turma_ids:
        cursor.execute(
            """SELECT tp.TurmaID, p.nome
               FROM turma_professor tp
               JOIN professores p ON p.id = tp.professor_id
               WHERE tp.TurmaID IN (%s) AND tp.tipo = 'responsavel'""" % ",".join(["%s"] * len(turma_ids)),
            tuple(turma_ids),
        )
        for r in cursor.fetchall():
            responsavel_por_turma[r["TurmaID"]] = r["nome"]
    for t in turmas:
        t["professor_responsavel_nome"] = responsavel_por_turma.get(t["TurmaID"]) or t.get("Professor") or "—"

    # Agrupar turmas por modalidade
    turmas_por_modalidade = {}
    for t in turmas:
        key = t["modalidade_nome"]
        if key not in turmas_por_modalidade:
            turmas_por_modalidade[key] = []
        turmas_por_modalidade[key].append(t)
    # Ordenar: "Sem modalidade" por último
    def _ord_key(k):
        return (1, k) if k == "Sem modalidade" else (0, k)
    turmas_agrupadas = [(k, turmas_por_modalidade[k]) for k in sorted(turmas_por_modalidade.keys(), key=_ord_key)]

    academias = []
    academia_id_sel = None
    if len(ids_acessiveis) > 1 and (session.get("modo_painel") == "academia" or request.args.get("academia_id")):
        try:
            cursor.execute(
                "SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids_acessiveis)),
                tuple(ids_acessiveis),
            )
            academias = cursor.fetchall()
            academia_id_sel = academia_filtro or ids_acessiveis[0]
        except Exception:
            pass

    db.close()

    return render_template('turmas/lista_turmas.html',
                           turmas=turmas,
                           turmas_agrupadas=turmas_agrupadas,
                           busca=busca,
                           perfil=perfil_usuario,
                           academias=academias or [],
                           academia_id=academia_id_sel)


# ======================================================
# 🔹 Cadastrar Turma
# Corrigido para passar a variável 'perfil'
# ======================================================
@bp_turmas.route('/turmas/cadastro', methods=['GET', 'POST'])
@login_required
def cadastro_turma():
    perfil_usuario = get_user_profile()

    acad_id = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    back_url = request.args.get("next") or request.referrer or (url_for("academia.painel_academia", academia_id=acad_id) if acad_id else url_for("academia.painel_academia"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    academias = carregar_academias_do_usuario(cursor)
    ids_acad = [a["id"] for a in academias] if academias else _get_academias_ids()
    if acad_id and ids_acad and acad_id in ids_acad:
        session["academia_gerenciamento_id"] = acad_id
        session["finance_academia_id"] = acad_id
    academia_selecionada = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id") or (ids_acad[0] if ids_acad else None)

    if request.method == 'POST':
        nome = request.form['nome'].strip()
        dias_semana_list = request.form.getlist('dias_semana')
        dias_semana = ','.join(sorted(dias_semana_list)) if dias_semana_list else None
        hora_inicio = request.form.get('hora_inicio') or None
        hora_fim = request.form.get('hora_fim') or None
        if not dias_semana or not hora_inicio or not hora_fim:
            flash("Marque ao menos um dia da semana e informe hora início e fim.", "danger")
            db.close()
            return redirect(url_for('turmas.cadastro_turma'))
        dias_nomes = {'0':'Dom','1':'Seg','2':'Ter','3':'Qua','4':'Qui','5':'Sex','6':'Sáb'}
        dias_display = '/'.join(dias_nomes.get(d,'') for d in dias_semana.split(',') if d)
        dias_horario = f"{dias_display} - {hora_inicio[:5]} às {hora_fim[:5]}"
        idade_min = request.form.get('idade_min')
        idade_max = request.form.get('idade_max')
        professor_responsavel_id = request.form.get("professor_responsavel_id")
        professor_responsavel_id = int(professor_responsavel_id) if professor_responsavel_id and str(professor_responsavel_id).isdigit() else None
        professor_auxiliar_ids = [int(x) for x in request.form.getlist('professor_auxiliar_ids') if x and str(x).isdigit()]
        classificacao = request.form['classificacao'].strip()
        capacidade = request.form.get('capacidade')
        controla_limite = 1 if request.form.get('controla_limite') == '1' else 0
        observacoes = request.form.get('observacoes', '').strip()
        id_academia = request.form.get('id_academia') or getattr(current_user, "id_academia", None)

        if not id_academia and academias:
            flash("Selecione uma academia.", "danger")
            db.close()
            return redirect(url_for('turmas.cadastro_turma'))

        if not professor_responsavel_id:
            flash("Selecione o professor responsável.", "danger")
            db.close()
            return redirect(url_for('turmas.cadastro_turma'))

        cursor.execute("SELECT nome FROM professores WHERE id = %s", (professor_responsavel_id,))
        row = cursor.fetchone()
        professor_nomes = [row.get("nome", "")] if row else []
        for pid in professor_auxiliar_ids:
            if pid == professor_responsavel_id:
                continue
            cursor.execute("SELECT nome FROM professores WHERE id = %s", (pid,))
            r = cursor.fetchone()
            if r:
                professor_nomes.append(r.get("nome", ""))
        professor_nome = ", ".join(professor_nomes)

        cursor.execute("SELECT TurmaID FROM turmas WHERE Nome=%s", (nome,))
        if cursor.fetchone():
            flash("Já existe uma turma com este nome.", "danger")
            db.close()
            return redirect(url_for('turmas.cadastro_turma'))

        try:
            cursor.execute("""
                INSERT INTO turmas (Nome, DiasHorario, IdadeMin, IdadeMax, Professor,
                                     Classificacao, Capacidade, controla_limite, Observacoes, id_academia, DataCriacao,
                                     dias_semana, hora_inicio, hora_fim)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,%s,%s)
            """, (nome, dias_horario, idade_min, idade_max, professor_nome, classificacao,
                  capacidade, controla_limite, observacoes, id_academia, dias_semana, hora_inicio, hora_fim))
        except Exception as e:
            err = str(e).lower()
            if "unknown column" in err or "dias_semana" in err:
                cursor.execute("""
                    INSERT INTO turmas (Nome, DiasHorario, IdadeMin, IdadeMax, Professor,
                                         Classificacao, Capacidade, controla_limite, Observacoes, id_academia, DataCriacao)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                """, (nome, dias_horario, idade_min, idade_max, professor_nome, classificacao,
                      capacidade, controla_limite, observacoes, id_academia))
            else:
                raise
        turma_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO turma_professor (TurmaID, professor_id, tipo) VALUES (%s, %s, 'responsavel')",
            (turma_id, professor_responsavel_id),
        )
        for pid in professor_auxiliar_ids:
            if pid != professor_responsavel_id:
                cursor.execute(
                    "INSERT INTO turma_professor (TurmaID, professor_id, tipo) VALUES (%s, %s, 'auxiliar')",
                    (turma_id, pid),
                )
        modalidade_id = request.form.get("modalidade_id")
        if modalidade_id and str(modalidade_id).isdigit():
            cursor.execute(
                "INSERT INTO turma_modalidades (turma_id, modalidade_id) VALUES (%s, %s)",
                (turma_id, int(modalidade_id)),
            )
        db.commit()
        db.close()
        flash("Turma cadastrada com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    # Modalidades liberadas pela academia (academia_modalidades), excluindo privadas sem acesso
    modalidades = []
    id_acad_mod = academia_selecionada or (request.form.get("id_academia") if request.method == "POST" else None)
    id_assoc_mod = None
    if id_acad_mod:
        cursor.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_acad_mod,))
        r = cursor.fetchone()
        id_assoc_mod = r.get("id_associacao") if r else None
        extra_mod, extra_params_mod = filtro_visibilidade_sql(id_academia=id_acad_mod, id_associacao=id_assoc_mod)
        cursor.execute(
            """
            SELECT m.id, m.nome FROM modalidade m
            INNER JOIN academia_modalidades am ON am.modalidade_id = m.id
            WHERE am.academia_id = %s AND m.ativo = 1
            """ + extra_mod + """
            ORDER BY m.nome
            """,
            (id_acad_mod,) + extra_params_mod,
        )
        modalidades = cursor.fetchall()
    if not modalidades and (id_acad_mod or id_assoc_mod):
        extra, extra_params = filtro_visibilidade_sql(id_academia=id_acad_mod, id_associacao=id_assoc_mod)
        cursor.execute("SELECT id, nome FROM modalidade m WHERE m.ativo = 1" + extra + " ORDER BY m.nome", extra_params)
        modalidades = cursor.fetchall()
    if not modalidades:
        cursor.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY nome")
        modalidades = cursor.fetchall()

    # Carregar professores da academia (inclui os que têm modalidades liberadas, sem exigir vínculo usuário)
    professores = []
    if academia_selecionada:
        cursor.execute(
            """SELECT p.id, p.nome FROM professores p
               WHERE p.id_academia = %s AND p.ativo = 1 ORDER BY p.nome""",
            (academia_selecionada,),
        )
        professores = cursor.fetchall()
    elif academias:
        ids_acad = [a["id"] for a in academias]
        cursor.execute(
            """SELECT p.id, p.nome, p.id_academia FROM professores p
               WHERE p.id_academia IN (%s) AND p.ativo = 1 ORDER BY p.nome"""
            % ",".join(["%s"] * len(ids_acad)),
            tuple(ids_acad),
        )
        professores = cursor.fetchall()

    # Mapa professor_id -> [modalidade_ids] para filtro por modalidade
    prof_modalidades = {}
    if professores:
        pids = [p["id"] for p in professores]
        cursor.execute(
            """SELECT professor_id, modalidade_id FROM professor_modalidade
               WHERE professor_id IN (%s)"""
            % ",".join(["%s"] * len(pids)),
            tuple(pids),
        )
        for r in cursor.fetchall():
            pid, mid = r.get("professor_id"), r.get("modalidade_id")
            if pid is not None and mid is not None:
                prof_modalidades.setdefault(pid, []).append(mid)

    db.close()
    return render_template(
        'turmas/cadastro_turma.html',
        perfil=perfil_usuario,
        academias=academias,
        academia_selecionada=academia_selecionada,
        professores=professores,
        modalidades=modalidades,
        prof_modalidades=prof_modalidades,
        back_url=back_url
    )


# ======================================================
# 🔹 Editar Turma
# Corrigido para passar a variável 'perfil'
# ======================================================
@bp_turmas.route('/turmas/editar/<int:turma_id>', methods=['GET', 'POST'])
@login_required
def editar_turma(turma_id):
    perfil_usuario = get_user_profile()

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM turmas WHERE TurmaID=%s", (turma_id,))
    turma = cursor.fetchone()
    acad_id = turma.get("id_academia") if turma else request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    back_url = request.args.get("next") or request.referrer or (url_for("academia.painel_academia", academia_id=acad_id) if acad_id else url_for("academia.painel_academia"))
    if not turma:
        flash("Turma não encontrada.", "danger")
        db.close()
        return redirect(url_for('turmas.lista_turmas'))

    academias = carregar_academias_do_usuario(cursor)
    ids_acad = [a["id"] for a in academias] if academias else _get_academias_ids()
    academia_turma = turma.get("id_academia")

    # Professores da academia (mesmo critério do cadastro: todos os ativos da academia)
    professores = []
    if academia_turma:
        cursor.execute(
            """SELECT p.id, p.nome FROM professores p
               WHERE p.id_academia = %s AND p.ativo = 1 ORDER BY p.nome""",
            (academia_turma,),
        )
        professores = cursor.fetchall()
    elif academias:
        ids_acad = [a["id"] for a in academias]
        cursor.execute(
            """SELECT p.id, p.nome, p.id_academia FROM professores p
               WHERE p.id_academia IN (%s) AND p.ativo = 1 ORDER BY p.nome"""
            % ",".join(["%s"] * len(ids_acad)),
            tuple(ids_acad),
        )
        professores = cursor.fetchall()

    # Professor responsável e auxiliares
    professor_responsavel_id = None
    professor_auxiliar_ids = []
    cursor.execute("SELECT professor_id, tipo FROM turma_professor WHERE TurmaID = %s", (turma_id,))
    for row in cursor.fetchall():
        if (row.get("tipo") or "").lower() == "responsavel":
            professor_responsavel_id = row.get("professor_id")
        else:
            professor_auxiliar_ids.append(row.get("professor_id"))
    if professor_responsavel_id is None and turma.get("Professor") and professores:
        for p in professores:
            if p.get("nome") == turma.get("Professor"):
                professor_responsavel_id = p.get("id")
                break

    # Modalidades liberadas pela academia da turma, excluindo privadas sem acesso
    id_acad_turma = turma.get("id_academia")
    id_assoc_turma = None
    if id_acad_turma:
        cursor.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_acad_turma,))
        r = cursor.fetchone()
        id_assoc_turma = r.get("id_associacao") if r else None
        extra_ed, extra_params_ed = filtro_visibilidade_sql(id_academia=id_acad_turma, id_associacao=id_assoc_turma)
        cursor.execute(
            """
            SELECT m.id, m.nome FROM modalidade m
            INNER JOIN academia_modalidades am ON am.modalidade_id = m.id
            WHERE am.academia_id = %s AND m.ativo = 1
            """ + extra_ed + """
            ORDER BY m.nome
            """,
            (id_acad_turma,) + extra_params_ed,
        )
        modalidades = cursor.fetchall()
    if not modalidades and (id_acad_turma or id_assoc_turma):
        extra, extra_params = filtro_visibilidade_sql(id_academia=id_acad_turma, id_associacao=id_assoc_turma)
        cursor.execute("SELECT id, nome FROM modalidade m WHERE m.ativo = 1" + extra + " ORDER BY m.nome", extra_params)
        modalidades = cursor.fetchall()
    if not modalidades:
        cursor.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY nome")
        modalidades = cursor.fetchall()
    cursor.execute("SELECT modalidade_id FROM turma_modalidades WHERE turma_id = %s LIMIT 1", (turma_id,))
    row_mod = cursor.fetchone()
    turma_modalidade_id = row_mod.get("modalidade_id") if row_mod else None

    # Mapa professor_id -> [modalidade_ids] para filtro por modalidade
    prof_modalidades = {}
    if professores:
        pids = [p["id"] for p in professores]
        cursor.execute(
            """SELECT professor_id, modalidade_id FROM professor_modalidade
               WHERE professor_id IN (%s)"""
            % ",".join(["%s"] * len(pids)),
            tuple(pids),
        )
        for r in cursor.fetchall():
            pid, mid = r.get("professor_id"), r.get("modalidade_id")
            if pid is not None and mid is not None:
                prof_modalidades.setdefault(pid, []).append(mid)

    if request.method == 'POST':
        nome = request.form['nome'].strip()
        dias_semana_list = request.form.getlist('dias_semana')
        dias_semana = ','.join(sorted(dias_semana_list)) if dias_semana_list else None
        hora_inicio = request.form.get('hora_inicio') or None
        hora_fim = request.form.get('hora_fim') or None
        if not dias_semana or not hora_inicio or not hora_fim:
            flash("Marque ao menos um dia da semana e informe hora início e fim.", "danger")
            db.close()
            return redirect(url_for('turmas.editar_turma', turma_id=turma_id))
        dias_nomes = {'0':'Dom','1':'Seg','2':'Ter','3':'Qua','4':'Qui','5':'Sex','6':'Sáb'}
        dias_display = '/'.join(dias_nomes.get(d,'') for d in dias_semana.split(',') if d)
        dias_horario = f"{dias_display} - {hora_inicio[:5]} às {hora_fim[:5]}"
        idade_min = request.form.get('idade_min')
        idade_max = request.form.get('idade_max')
        professor_responsavel_id = request.form.get("professor_responsavel_id")
        professor_responsavel_id = int(professor_responsavel_id) if professor_responsavel_id and str(professor_responsavel_id).isdigit() else None
        professor_auxiliar_ids = [int(x) for x in request.form.getlist('professor_auxiliar_ids') if x and str(x).isdigit()]
        classificacao = request.form['classificacao'].strip()
        capacidade = request.form.get('capacidade')
        controla_limite = 1 if request.form.get('controla_limite') == '1' else 0
        observacoes = request.form.get('observacoes', '').strip()
        id_academia = request.form.get('id_academia') or (ids_acad[0] if ids_acad else None)

        professor_nome = turma.get("Professor", "")
        if professor_responsavel_id:
            cursor.execute("SELECT nome FROM professores WHERE id = %s", (professor_responsavel_id,))
            r = cursor.fetchone()
            professor_nomes = [r.get("nome", "")] if r else []
            for pid in professor_auxiliar_ids:
                if pid == professor_responsavel_id:
                    continue
                cursor.execute("SELECT nome FROM professores WHERE id = %s", (pid,))
                r = cursor.fetchone()
                if r:
                    professor_nomes.append(r.get("nome", ""))
            professor_nome = ", ".join(professor_nomes)

        if not professor_responsavel_id:
            flash("Selecione o professor responsável.", "danger")
            db.close()
            return redirect(url_for('turmas.editar_turma', turma_id=turma_id))

        try:
            cursor.execute("""
                UPDATE turmas
                SET Nome=%s, DiasHorario=%s, IdadeMin=%s, IdadeMax=%s,
                    Professor=%s, Classificacao=%s, Capacidade=%s, controla_limite=%s, Observacoes=%s, id_academia=%s,
                    dias_semana=%s, hora_inicio=%s, hora_fim=%s
                WHERE TurmaID=%s
            """, (nome, dias_horario, idade_min, idade_max, professor_nome,
                  classificacao, capacidade, controla_limite, observacoes, id_academia,
                  dias_semana, hora_inicio, hora_fim, turma_id))
        except Exception as e:
            err = str(e).lower()
            if "unknown column" in err or "dias_semana" in err:
                cursor.execute("""
                    UPDATE turmas
                    SET Nome=%s, DiasHorario=%s, IdadeMin=%s, IdadeMax=%s,
                        Professor=%s, Classificacao=%s, Capacidade=%s, controla_limite=%s, Observacoes=%s, id_academia=%s
                    WHERE TurmaID=%s
                """, (nome, dias_horario, idade_min, idade_max, professor_nome,
                      classificacao, capacidade, controla_limite, observacoes, id_academia, turma_id))
            else:
                raise
        cursor.execute("DELETE FROM turma_professor WHERE TurmaID = %s", (turma_id,))
        cursor.execute(
            "INSERT INTO turma_professor (TurmaID, professor_id, tipo) VALUES (%s, %s, 'responsavel')",
            (turma_id, professor_responsavel_id),
        )
        for pid in professor_auxiliar_ids:
            if pid != professor_responsavel_id:
                cursor.execute(
                    "INSERT INTO turma_professor (TurmaID, professor_id, tipo) VALUES (%s, %s, 'auxiliar')",
                    (turma_id, pid),
                )
        cursor.execute("DELETE FROM turma_modalidades WHERE turma_id = %s", (turma_id,))
        modalidade_id = request.form.get("modalidade_id")
        if modalidade_id and str(modalidade_id).isdigit() and id_academia:
            cursor.execute(
                "SELECT 1 FROM academia_modalidades WHERE academia_id = %s AND modalidade_id = %s",
                (id_academia, int(modalidade_id)),
            )
            if cursor.fetchone():
                cursor.execute(
                    "INSERT INTO turma_modalidades (turma_id, modalidade_id) VALUES (%s, %s)",
                    (turma_id, int(modalidade_id)),
                )
        db.commit()
        db.close()
        flash("Turma atualizada com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    def _fmt_time(v):
        if v is None:
            return ""
        if hasattr(v, "strftime"):
            return v.strftime("%H:%M")
        if isinstance(v, str) and len(v) >= 5:
            return v[:5]
        return str(v)[:5] if v else ""

    hora_inicio_display = _fmt_time(turma.get("hora_inicio"))
    hora_fim_display = _fmt_time(turma.get("hora_fim"))

    db.close()
    return render_template(
        'turmas/editar_turma.html',
        turma=turma,
        perfil=perfil_usuario,
        academias=academias,
        academia_selecionada=turma.get("id_academia"),
        professores=professores,
        professor_responsavel_id=professor_responsavel_id,
        professor_auxiliar_ids=professor_auxiliar_ids,
        modalidades=modalidades,
        turma_modalidade_id=turma_modalidade_id,
        prof_modalidades=prof_modalidades,
        back_url=back_url,
        hora_inicio_display=hora_inicio_display,
        hora_fim_display=hora_fim_display,
    )


# ======================================================
# 🔹 Alunos da academia (para modal matricular)
# ======================================================
def _calcular_idade(data_nascimento):
    """Retorna idade em anos completos ou None se não for possível calcular."""
    if not data_nascimento:
        return None
    if isinstance(data_nascimento, str):
        try:
            data_nascimento = datetime.strptime(data_nascimento[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
    hoje = date.today()
    idade = hoje.year - data_nascimento.year
    if (hoje.month, hoje.day) < (data_nascimento.month, data_nascimento.day):
        idade -= 1
    return idade if idade >= 0 else None


@bp_turmas.route('/turmas/<int:turma_id>/alunos-disponiveis')
@login_required
def alunos_disponiveis_turma(turma_id):
    """Retorna alunos da academia da turma que ainda NÃO estão nessa turma
    e cuja idade é compatível com IdadeMin/IdadeMax da turma."""
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT id_academia, IdadeMin, IdadeMax FROM turmas WHERE TurmaID = %s",
            (turma_id,),
        )
        turma = cursor.fetchone()
        if not turma or not turma.get("id_academia"):
            db.close()
            return jsonify([])
        id_academia = int(turma["id_academia"])
        ids_acessiveis = [int(x) for x in _get_academias_ids()]
        if id_academia not in ids_acessiveis:
            db.close()
            return jsonify([])
        idade_min = turma.get("IdadeMin")
        idade_max = turma.get("IdadeMax")
        cursor.execute(
            """SELECT a.id, a.nome, a.foto, a.data_nascimento
               FROM alunos a
               WHERE a.id_academia = %s AND a.ativo = 1 AND a.status = 'ativo'
               ORDER BY a.nome""",
            (id_academia,),
        )
        todos = cursor.fetchall()
        cursor.execute(
            """SELECT aluno_id FROM aluno_turmas WHERE TurmaID = %s""",
            (turma_id,),
        )
        ids_na_turma = {r["aluno_id"] for r in cursor.fetchall()}
        cursor.execute(
            """SELECT id FROM alunos WHERE TurmaID = %s""",
            (turma_id,),
        )
        for r in cursor.fetchall():
            ids_na_turma.add(r["id"])
        disponiveis = []
        for a in todos:
            if a["id"] in ids_na_turma:
                continue
            if idade_min is not None or idade_max is not None:
                idade_aluno = _calcular_idade(a.get("data_nascimento"))
                if idade_aluno is None:
                    continue
                imin = int(idade_min) if idade_min is not None else 0
                imax = int(idade_max) if idade_max is not None else 999
                if idade_aluno < imin or idade_aluno > imax:
                    continue
            disponiveis.append(a)
        for a in disponiveis:
            a.pop("data_nascimento", None)
            a["foto_url"] = url_for("static", filename="uploads/" + a["foto"]) if a.get("foto") else None
        db.close()
        return jsonify(disponiveis)
    except Exception as e:
        try:
            db.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


# ======================================================
# 🔹 Alunos vinculados à turma
# ======================================================
@bp_turmas.route('/turmas/<int:turma_id>/alunos-vinculados')
@login_required
def alunos_vinculados_turma(turma_id):
    """Retorna alunos já matriculados na turma."""
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id_academia FROM turmas WHERE TurmaID = %s", (turma_id,))
        turma = cursor.fetchone()
        if not turma:
            db.close()
            return jsonify([])
        ids_acessiveis = [int(x) for x in _get_academias_ids()]
        id_acad = turma.get("id_academia")
        if id_acad is None:
            db.close()
            return jsonify([])
        id_academia = int(id_acad)
        if id_academia not in ids_acessiveis:
            db.close()
            return jsonify([])
        cursor.execute(
            """SELECT a.id, a.nome, a.foto
               FROM alunos a
               JOIN aluno_turmas at ON at.aluno_id = a.id
               WHERE at.TurmaID = %s AND a.id_academia = %s
               ORDER BY a.nome""",
            (turma_id, id_academia),
        )
        vinculados = cursor.fetchall()
        cursor.execute(
            """SELECT id, nome, foto FROM alunos WHERE TurmaID = %s AND id_academia = %s""",
            (turma_id, id_academia),
        )
        legado = cursor.fetchall()
        ids_v = {a["id"] for a in vinculados}
        for a in legado:
            if a["id"] not in ids_v:
                vinculados.append(a)
        for a in vinculados:
            a["foto_url"] = url_for("static", filename="uploads/" + a["foto"]) if a.get("foto") else None
        db.close()
        return jsonify(vinculados)
    except Exception as e:
        try:
            db.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


# ======================================================
# 🔹 Matricular aluno na turma
# ======================================================
@bp_turmas.route('/turmas/<int:turma_id>/matricular/<int:aluno_id>', methods=['POST'])
@login_required
def matricular_aluno(turma_id, aluno_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT id_academia, IdadeMin, IdadeMax FROM turmas WHERE TurmaID = %s",
        (turma_id,),
    )
    turma = cursor.fetchone()
    if not turma:
        db.close()
        return jsonify({"ok": False, "msg": "Turma não encontrada"}), 404
    ids_acessiveis = _get_academias_ids()
    if turma.get("id_academia") and turma["id_academia"] not in ids_acessiveis:
        db.close()
        return jsonify({"ok": False, "msg": "Sem permissão"}), 403
    cursor.execute(
        "SELECT id, id_academia, data_nascimento FROM alunos WHERE id = %s",
        (aluno_id,),
    )
    aluno = cursor.fetchone()
    if not aluno or str(aluno.get("id_academia")) != str(turma.get("id_academia")):
        db.close()
        return jsonify({"ok": False, "msg": "Aluno não pertence à academia da turma"}), 400
    cursor.execute(
        "SELECT 1 FROM aluno_turmas WHERE aluno_id = %s AND TurmaID = %s",
        (aluno_id, turma_id),
    )
    if cursor.fetchone():
        db.close()
        return jsonify({"ok": False, "msg": "Aluno já matriculado"}), 400
    # Verificar se é exceção (pula validação de idade)
    excecao = request.args.get("excecao") == "1" or request.form.get("excecao") == "1"
    
    idade_min = turma.get("IdadeMin")
    idade_max = turma.get("IdadeMax")
    if not excecao and (idade_min is not None or idade_max is not None):
        idade_aluno = _calcular_idade(aluno.get("data_nascimento"))
        if idade_aluno is None:
            db.close()
            return jsonify({"ok": False, "msg": "Aluno sem data de nascimento. Verifique a faixa etária da turma."}), 400
        imin = int(idade_min) if idade_min is not None else 0
        imax = int(idade_max) if idade_max is not None else 999
        if idade_aluno < imin or idade_aluno > imax:
            db.close()
            return jsonify({
                "ok": False,
                "msg": f"Idade do aluno ({idade_aluno} anos) fora da faixa da turma ({imin}-{imax} anos).",
            }), 400
    cursor.execute(
        "INSERT INTO aluno_turmas (aluno_id, TurmaID) VALUES (%s, %s)",
        (aluno_id, turma_id),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True, "msg": "Aluno matriculado com sucesso!"})


# ======================================================
# 🔹 Buscar aluno por nome (modo exceção - independente da idade)
# ======================================================
@bp_turmas.route('/turmas/<int:turma_id>/buscar-aluno-excecao')
@login_required
def buscar_aluno_excecao(turma_id):
    """Busca alunos por nome independente da idade (para matrícula com exceção)."""
    try:
        nome = request.args.get("nome", "").strip()
        if not nome or len(nome) < 2:
            return jsonify([])
        
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT id_academia FROM turmas WHERE TurmaID = %s",
            (turma_id,),
        )
        turma = cursor.fetchone()
        if not turma or not turma.get("id_academia"):
            db.close()
            return jsonify([])
        
        id_academia = int(turma["id_academia"])
        ids_acessiveis = [int(x) for x in _get_academias_ids()]
        if id_academia not in ids_acessiveis:
            db.close()
            return jsonify([])
        
        # Buscar alunos por nome (independente da idade)
        cursor.execute(
            """SELECT a.id, a.nome, a.foto
               FROM alunos a
               WHERE a.id_academia = %s 
                 AND a.ativo = 1 
                 AND a.status = 'ativo'
                 AND a.nome LIKE %s
               ORDER BY a.nome
               LIMIT 50""",
            (id_academia, f"%{nome}%"),
        )
        alunos = cursor.fetchall()
        
        # Excluir alunos já matriculados
        cursor.execute(
            """SELECT aluno_id FROM aluno_turmas WHERE TurmaID = %s""",
            (turma_id,),
        )
        ids_na_turma = {r["aluno_id"] for r in cursor.fetchall()}
        cursor.execute(
            """SELECT id FROM alunos WHERE TurmaID = %s""",
            (turma_id,),
        )
        for r in cursor.fetchall():
            ids_na_turma.add(r["id"])
        
        disponiveis = [a for a in alunos if a["id"] not in ids_na_turma]
        
        # Adicionar URL da foto
        for a in disponiveis:
            a["foto_url"] = url_for("static", filename="uploads/" + a["foto"]) if a.get("foto") else None
        
        db.close()
        return jsonify(disponiveis)
    except Exception as e:
        try:
            db.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


# ======================================================
# 🔹 Remover aluno da turma
# ======================================================
@bp_turmas.route('/turmas/<int:turma_id>/remover/<int:aluno_id>', methods=['POST'])
@login_required
def remover_aluno_turma(turma_id, aluno_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id_academia FROM turmas WHERE TurmaID = %s", (turma_id,))
    turma = cursor.fetchone()
    if not turma:
        db.close()
        return jsonify({"ok": False, "msg": "Turma não encontrada"}), 404
    ids_acessiveis = _get_academias_ids()
    if turma.get("id_academia") and turma["id_academia"] not in ids_acessiveis:
        db.close()
        return jsonify({"ok": False, "msg": "Sem permissão"}), 403
    cursor.execute("SELECT id, id_academia FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()
    if not aluno or str(aluno.get("id_academia")) != str(turma.get("id_academia")):
        db.close()
        return jsonify({"ok": False, "msg": "Aluno não pertence à academia da turma"}), 400
    # Remove de aluno_turmas
    cursor.execute("DELETE FROM aluno_turmas WHERE aluno_id = %s AND TurmaID = %s", (aluno_id, turma_id))
    # Remove legado: se aluno.TurmaID apontava para esta turma, limpar
    cursor.execute("UPDATE alunos SET TurmaID = NULL WHERE id = %s AND TurmaID = %s", (aluno_id, turma_id))
    db.commit()
    db.close()
    return jsonify({"ok": True, "msg": "Aluno removido da turma."})