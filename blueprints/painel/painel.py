# ======================================================
# blueprints/painel/painel.py
# ======================================================

from flask import Blueprint, render_template, redirect, url_for, flash, session
from config import get_db_connection
from utils.decorators import requer_perfil

bp_painel = Blueprint('painel', __name__, url_prefix='/painel')


# ======================================================
# 🔹 Redireciona conforme o perfil do usuário
# ======================================================
@bp_painel.route('/')
def painel_home():

    # usuário não logado
    if 'usuario' not in session:
        return redirect(url_for('auth.login'))

    perfil = session['usuario']['tipo']  # vem do login: tipo_nome

    if perfil == "Admin":
        return redirect(url_for('painel.painel_admin'))
    elif perfil == "Federação":
        return redirect(url_for('painel.painel_federacao'))
    elif perfil == "Associação":
        return redirect(url_for('painel.painel_associacao'))
    elif perfil == "Academia":
        return redirect(url_for('painel.painel_academia'))
    elif perfil == "Aluno":
        return redirect(url_for('painel.painel_aluno'))
    else:
        flash("Perfil desconhecido. Contate o administrador.", "danger")
        return redirect(url_for('index'))


# ======================================================
# 🔹 Painel da Federação → Ver todas as associações
# ======================================================
@bp_painel.route('/admin')
def painel_admin():
    # Apenas Admin acessa esse
    if 'usuario' not in session:
        return redirect(url_for('auth.login'))

    if session['usuario']['tipo'] != "Admin":
        flash("Acesso negado.", "danger")
        return redirect(url_for('index'))

    return render_template('painel/admin.html', usuario=session['usuario'])


@bp_painel.route('/federacao')
@requer_perfil(["Federação"])
def painel_federacao():

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, nome FROM federacoes")
    associacoes = cursor.fetchall()
    db.close()

    return render_template('painel/federacao.html', associacoes=associacoes)


# ======================================================
# 🔹 Painel da Associação → Ver academias da associação
# ======================================================
@bp_painel.route('/associacao')
@requer_perfil(["Associação"])
def painel_associacao():

    id_associacao = session['usuario'].get('id_associacao')

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, nome 
        FROM associacoes 
        WHERE id = %s
    """, (id_associacao,))

    academias = cursor.fetchall()
    db.close()

    return render_template('painel/associacao.html', academias=academias)


# ======================================================
# 🔹 Painel da Academia → Ver alunos da academia
# ======================================================
@bp_painel.route('/academia')
@requer_perfil(["Academia"])
def painel_academia():

    id_academia = session['usuario'].get('id_academia')

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, nome, graduacao, ativo
        FROM academias
        WHERE id = %s
    """, (id_academia,))

    alunos = cursor.fetchall()
    db.close()

    return render_template('painel/academia.html', alunos=alunos)


# ======================================================
# 🔹 Painel do Aluno → Ver seus próprios dados
# ======================================================
@bp_painel.route('/aluno')
@requer_perfil(["Aluno"])
def painel_aluno():

    id_usuario = session['usuario']['id']

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT nome, graduacao, data_nascimento, id_academia
        FROM alunos
        WHERE usuario_id = %s
    """, (id_usuario,))

    aluno = cursor.fetchone()
    db.close()

    return render_template('painel/aluno.html', aluno=aluno)
