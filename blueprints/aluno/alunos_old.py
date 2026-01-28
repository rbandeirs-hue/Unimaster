# ======================================================
# 🧩 Blueprint: Alunos (CRUD) - Versão RBAC Corrigida
# ======================================================

from flask import render_template, request, redirect, url_for, flash, Blueprint
from flask_login import login_required, current_user
from config import get_db_connection
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import re

bp_alunos = Blueprint('alunos', __name__, url_prefix="/alunos")

# ======================================================
# FUNÇÕES UTILITÁRIAS
# ======================================================

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extrair_numero(valor):
    return int(''.join(filter(str.isdigit, str(valor)))) if valor else 0


# ======================================================
# 🔹 1. LISTA DE ALUNOS (com RBAC)
# ======================================================

@bp_alunos.route('/lista_alunos', methods=['GET'])
@login_required
def lista_alunos():

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    busca = request.args.get('busca', '').strip()
    hoje = date.today()

    # Base
    query = """
        SELECT a.*, ac.nome AS academia_nome, ass.nome AS associacao_nome, fed.nome AS federacao_nome,
               g.faixa AS faixa, g.graduacao AS graduacao, t.Nome AS turma_nome
        FROM alunos a
        LEFT JOIN academias ac ON a.id_academia = ac.id
        LEFT JOIN associacoes ass ON ac.id_associacao = ass.id
        LEFT JOIN federacoes fed ON ass.id_federacao = fed.id
        LEFT JOIN graduacao g ON a.graduacao_id = g.id
        LEFT JOIN turmas t ON a.TurmaID = t.TurmaID
        WHERE 1=1
    """
    params = []

    # ======================================================
    # 🔐 RBAC — CONTROLE DE ACESSO POR ROLE
    # ======================================================

    # SUPERUSER
    if current_user.has_role("admin"):
        pass  # Admin vê tudo

    # FEDERAÇÃO → vê alunos das academias da federação
    elif current_user.has_role("gestor_federacao"):
        query += """
            AND a.id_academia IN (
                SELECT ac.id
                FROM academias ac
                JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ass.id_federacao = %s
            )
        """
        params.append(current_user.id_federacao)

    # ASSOCIAÇÃO → vê alunos das academias da associação
    elif current_user.has_role("gestor_associacao"):
        query += """
            AND a.id_academia IN (
                SELECT id FROM academias WHERE id_associacao = %s
            )
        """
        params.append(current_user.id_associacao)

    # ACADEMIA → vê apenas alunos da própria academia
    elif current_user.has_role("gestor_academia") or current_user.has_role("professor"):
        query += " AND a.id_academia = %s"
        params.append(current_user.id_academia)

    # ALUNO → vê só a si mesmo
    elif current_user.has_role("aluno"):
        query += " AND a.id = %s"
        params.append(current_user.id)

    # Busca
    if busca:
        query += " AND a.nome LIKE %s"
        params.append(f"%{busca}%")

    query += " ORDER BY a.nome"

    cursor.execute(query, tuple(params))
    alunos = cursor.fetchall()

    # Carrega faixas
    cursor.execute("SELECT * FROM graduacao ORDER BY id")
    faixas = cursor.fetchall()

    # Aprov. especial
    cursor.execute("""
        SELECT aluno_id, faixa_aprovada, aprovado_por, data_aprovacao
        FROM aprovacoes_faixa_professor
    """)
    aprovacoes = {a["aluno_id"]: a for a in cursor.fetchall()}

    db.close()

    # ======================================================
    # 🔹 CÁLCULO DE FAIXAS (mantido)
    # ======================================================

    for aluno in alunos:

        nasc = aluno.get("data_nascimento")
        exame = aluno.get("ultimo_exame_faixa")

        if isinstance(nasc, str):
            try:
                nasc = datetime.strptime(nasc, "%Y-%m-%d").date()
            except:
                nasc = None

        if isinstance(exame, str):
            try:
                exame = datetime.strptime(exame, "%Y-%m-%d").date()
            except:
                exame = None

        aluno["idade_real"] = (
            hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
        ) if nasc else None

        aluno["idade_ano_civil"] = hoje.year - nasc.year if nasc else None
        idade_civil = aluno["idade_ano_civil"] or 0
        faixa_atual = (aluno.get("faixa") or "").lower()

        aluno["data_nascimento_formatada"] = nasc.strftime("%d/%m/%Y") if nasc else "-"
        aluno["ultimo_exame_faixa_formatada"] = exame.strftime("%d/%m/%Y") if exame else "-"

        faixa_sugerida = "-"
        regra_especial = "-"

        # Regras automáticas
        if idade_civil <= 6:
            faixa_sugerida = "Branca / Cinza"
        elif idade_civil == 7:
            faixa_sugerida = "Cinza"
        elif idade_civil == 11:
            faixa_sugerida = "Azul"
        elif idade_civil == 15:
            faixa_sugerida = "Amarela"
        elif "azul" in faixa_atual and idade_civil <= 12:
            faixa_sugerida = "Azul / Amarela"
        elif "amarela" in faixa_atual and idade_civil <= 13:
            faixa_sugerida = "Amarela / Laranja"

        # Aprovação manual
        aprov = aprovacoes.get(aluno["id"])
        if idade_civil >= 11 and aprov:
            faixa_sugerida = aprov["faixa_aprovada"]
            regra_especial = (
                f"Aprovado por {aprov['aprovado_por']} em "
                f"{aprov['data_aprovacao'].strftime('%d/%m/%Y')}"
            )

        aluno["faixa_sugerida"] = faixa_sugerida
        aluno["regra_especial"] = regra_especial

        # Próxima faixa
        faixa_atual_id = aluno.get("graduacao_id")
        proxima = None

        for i, f in enumerate(faixas):
            if f["id"] == faixa_atual_id and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                break

        if not proxima:
            aluno.update({
                "proxima_faixa": "Última faixa",
                "aptidao_status": "-",
                "aptidao": "Sem próxima faixa",
                "motivo": "",
                "data_elegivel": "-",
                "faltam_dias": 0,
            })
            continue

        idade_minima = extrair_numero(proxima.get("idade_minima"))
        carencia_meses = extrair_numero(proxima.get("carencia_meses"))
        carencia_dias = extrair_numero(proxima.get("carencia_dias"))

        delta = relativedelta(months=carencia_meses) if carencia_meses else relativedelta(days=carencia_dias)
        data_carencia = exame + delta if exame else None
        data_idade_minima = nasc + relativedelta(years=idade_minima) if nasc else None

        data_elegivel = max(data_carencia, data_idade_minima) if (data_carencia and data_idade_minima) else (data_carencia or data_idade_minima)
        faltam = max(0, (data_elegivel - hoje).days) if data_elegivel else 0

        idade_ok = aluno["idade_real"] and aluno["idade_real"] >= idade_minima
        carencia_ok = data_carencia and hoje >= data_carencia
        idade_data_ok = data_idade_minima and hoje >= data_idade_minima

        aluno["proxima_faixa"] = f"{proxima['faixa']} {proxima['graduacao']}"
        aluno["data_elegivel"] = data_elegivel.strftime("%d/%m/%Y") if data_elegivel else "-"
        aluno["faltam_dias"] = faltam

        if idade_ok and idade_data_ok and carencia_ok:
            aluno["aptidao_status"] = "Apto"
            aluno["aptidao"] = f"Apto para exame de faixa {aluno['proxima_faixa']}"
            aluno["motivo"] = ""
        else:
            motivos = []
            if not idade_ok:
                motivos.append(f"Idade mínima: {idade_minima} anos")
            if not (carencia_ok and idade_data_ok):
                motivos.append(
                    f"Elegível em {aluno['data_elegivel']} (faltam {faltam} dias)"
                )
            aluno["aptidao_status"] = "Inapto"
            aluno["aptidao"] = "Inapto"
            aluno["motivo"] = "; ".join(motivos)

    return render_template("alunos/lista_alunos.html", alunos=alunos, busca=busca)


# ======================================================
# 🔹 2. CADASTRAR ALUNO
# ======================================================

@bp_alunos.route('/cadastrar_aluno', methods=['GET', 'POST'])
@login_required
def cadastrar_aluno():

    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("gestor_associacao") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("admin")
    ):
        flash('Você não tem permissão para cadastrar alunos.', 'danger')
        return redirect(url_for('alunos.lista_alunos'))

    if request.method == 'POST':

        nome = request.form.get('nome')
        data_nascimento_str = request.form.get('data_nascimento')
        graduacao_id = request.form.get('graduacao_id')
        id_academia = current_user.id_academia

        db = get_db_connection()
        cursor = db.cursor()

        try:
            cursor.execute("""
                INSERT INTO alunos (nome, data_nascimento, graduacao_id, id_academia, TurmaID, status, data_cadastro)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                nome,
                data_nascimento_str,
                graduacao_id,
                id_academia,
                None,
                'Ativo',
                datetime.now().date()
            ))

            db.commit()
            flash(f'Aluno "{nome}" cadastrado com sucesso!', 'success')
            return redirect(url_for('alunos.lista_alunos'))

        except Exception as e:
            db.rollback()
            flash(f'Erro ao cadastrar aluno: {e}', 'danger')
        finally:
            db.close()

    return render_template('alunos/cadastro_aluno.html')


# ======================================================
# 🔹 3. EDITAR ALUNO
# ======================================================

@bp_alunos.route('/editar_aluno/<int:aluno_id>', methods=['GET', 'POST'])
@login_required
def editar_aluno(aluno_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()

    if not aluno:
        flash('Aluno não encontrado.', 'danger')
        db.close()
        return redirect(url_for('alunos.lista_alunos'))

    pode_editar = (
        current_user.has_role("gestor_academia") and aluno.get('id_academia') == current_user.id_academia
    ) or current_user.has_role("admin")

    if not pode_editar:
        flash('Você não tem permissão para editar este aluno.', 'danger')
        db.close()
        return redirect(url_for('alunos.lista_alunos'))

    if request.method == 'POST':

        nome = request.form.get('nome')
        status = request.form.get('status')

        try:
            cursor.execute("""
                UPDATE alunos SET nome=%s, status=%s
                WHERE id=%s
            """, (nome, status, aluno_id))

            db.commit()

            flash(f'Dados do aluno "{nome}" atualizados com sucesso!', 'success')
            return redirect(url_for('alunos.lista_alunos'))

        except Exception as e:
            db.rollback()
            flash(f'Erro ao atualizar aluno: {e}', 'danger')
        finally:
            db.close()

    db.close()
    return render_template('alunos/editar_aluno.html', aluno=aluno)


# ======================================================
# 🔹 4. EXCLUIR ALUNO
# ======================================================

@bp_alunos.route('/excluir_aluno/<int:aluno_id>', methods=['POST'])
@login_required
def excluir_aluno(aluno_id):

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id, nome, id_academia FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()

    if not aluno:
        flash('Aluno não encontrado.', 'danger')
        db.close()
        return redirect(url_for('alunos.lista_alunos'))

    pode_excluir = (
        current_user.has_role("gestor_academia") and aluno["id_academia"] == current_user.id_academia
    ) or current_user.has_role("admin")

    if not pode_excluir:
        flash('Você não tem permissão para excluir este aluno.', 'danger')
        db.close()
        return redirect(url_for('alunos.lista_alunos'))

    try:
        cursor.execute("DELETE FROM alunos WHERE id=%s", (aluno_id,))
        db.commit()

        flash(f'Aluno "{aluno["nome"]}" excluído com sucesso!', 'success')

    except Exception as e:
        db.rollback()
        flash(f'Erro ao excluir aluno: {e}', 'danger')

    finally:
        db.close()

    return redirect(url_for('alunos.lista_alunos'))
