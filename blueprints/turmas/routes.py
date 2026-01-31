# ======================================================
# 🧩 Blueprint: Turmas
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
# Importamos current_user para acessar o perfil do usuário logado
from flask_login import login_required, current_user
from config import get_db_connection

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
    elif getattr(current_user, "id_academia", None):
        cursor.execute("SELECT id, nome FROM academias WHERE id = %s", (current_user.id_academia,))
    else:
        return []

    return cursor.fetchall()


def _get_academias_ids():
    """IDs de academias acessíveis (para filtro em modo academia)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
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
        elif getattr(current_user, "id_academia", None):
            ids = [current_user.id_academia]
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
    academia_filtro = request.args.get("academia_id", type=int) or (
        session.get("academia_gerenciamento_id") if session.get("modo_painel") == "academia" else None
    )

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
        filters.append("Nome LIKE %s")
        params.append('%' + busca + '%')
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY Nome"

    cursor.execute(query, tuple(params))
    turmas = cursor.fetchall()

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

    back_url = request.args.get("next") or request.referrer or url_for("turmas.lista_turmas")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    academias = carregar_academias_do_usuario(cursor)
    academia_selecionada = (
        request.args.get("academia_id", type=int)
        or (session.get("academia_gerenciamento_id") if session.get("modo_painel") == "academia" else None)
        or getattr(current_user, "id_academia", None)
    )

    if request.method == 'POST':
        nome = request.form['nome'].strip()
        dias_horario = request.form['dias_horario'].strip()
        idade_min = request.form.get('idade_min')
        idade_max = request.form.get('idade_max')
        professor = request.form['professor'].strip()
        classificacao = request.form['classificacao'].strip()
        capacidade = request.form.get('capacidade')
        observacoes = request.form.get('observacoes', '').strip()
        id_academia = request.form.get('id_academia') or getattr(current_user, "id_academia", None)

        if not id_academia and academias:
            flash("Selecione uma academia.", "danger")
            db.close()
            return redirect(url_for('turmas.cadastro_turma'))

        cursor.execute("SELECT TurmaID FROM turmas WHERE Nome=%s", (nome,))
        if cursor.fetchone():
            flash("Já existe uma turma com este nome.", "danger")
            db.close()
            # 🚨 CORREÇÃO: Garantindo o perfil no redirect de erro (embora o template não seja renderizado diretamente)
            return redirect(url_for('turmas.cadastro_turma'))

        cursor.execute("""
            INSERT INTO turmas (Nome, DiasHorario, IdadeMin, IdadeMax, Professor,
                                 Classificacao, Capacidade, Observacoes, id_academia, DataCriacao)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (nome, dias_horario, idade_min, idade_max, professor, classificacao,
              capacidade, observacoes, id_academia))
        db.commit()
        db.close()
        flash("Turma cadastrada com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    db.close()
    # 🚨 CORREÇÃO: Passando 'perfil' para o template no GET
    return render_template(
        'turmas/cadastro_turma.html',
        perfil=perfil_usuario,
        academias=academias,
        academia_selecionada=academia_selecionada,
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

    back_url = request.args.get("next") or request.referrer or url_for("turmas.lista_turmas")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM turmas WHERE TurmaID=%s", (turma_id,))
    turma = cursor.fetchone()
    if not turma:
        flash("Turma não encontrada.", "danger")
        db.close()
        return redirect(url_for('turmas.lista_turmas'))

    academias = carregar_academias_do_usuario(cursor)

    if request.method == 'POST':
        nome = request.form['nome'].strip()
        dias_horario = request.form['dias_horario'].strip()
        idade_min = request.form.get('idade_min')
        idade_max = request.form.get('idade_max')
        professor = request.form['professor'].strip()
        classificacao = request.form['classificacao'].strip()
        capacidade = request.form.get('capacidade')
        observacoes = request.form.get('observacoes', '').strip()
        id_academia = request.form.get('id_academia') or getattr(current_user, "id_academia", None)

        cursor.execute("""
            UPDATE turmas
            SET Nome=%s, DiasHorario=%s, IdadeMin=%s, IdadeMax=%s,
                Professor=%s, Classificacao=%s, Capacidade=%s, Observacoes=%s, id_academia=%s
            WHERE TurmaID=%s
        """, (nome, dias_horario, idade_min, idade_max, professor,
              classificacao, capacidade, observacoes, id_academia, turma_id))
        db.commit()
        db.close()
        flash("Turma atualizada com sucesso!", "success")
        redirect_url = request.form.get("next") or back_url
        return redirect(redirect_url)

    db.close()
    # 🚨 CORREÇÃO: Passando 'perfil' para o template
    return render_template(
        'turmas/editar_turma.html',
        turma=turma,
        perfil=perfil_usuario,
        academias=academias,
        academia_selecionada=turma.get("id_academia"),
        back_url=back_url
    )