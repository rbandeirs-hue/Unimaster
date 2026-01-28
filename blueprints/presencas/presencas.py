# ======================================================
# 🧩 Blueprint: Presenças
# ======================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from config import get_db_connection
from datetime import date, datetime
import re # Necessário para o histórico/ajax se mantiver a lógica original

# ⚠️ O nome 'presencas' será usado para referenciar as rotas: url_for('presencas.registro_presenca')
bp_presencas = Blueprint("presencas", __name__)

# ======================================================
# 🔹 Registro de Presença
# ======================================================
@bp_presencas.route('/registro_presenca', methods=['GET', 'POST'])
@login_required
def registro_presenca():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Buscar todas as turmas
    cursor.execute("SELECT TurmaID, Nome FROM Turmas ORDER BY Nome")
    turmas = cursor.fetchall()

    # Seleção da turma e data
    turma_selecionada = request.form.get('turma_id') or request.args.get('turma_id')
    turma_selecionada = int(turma_selecionada) if turma_selecionada else None
    data_presenca = request.form.get('data_presenca') or request.args.get('data_presenca') or date.today().strftime('%Y-%m-%d')

    if request.method == 'POST' and turma_selecionada:
        alunos_selecionados = [int(a) for a in request.form.getlist('aluno_id')]

        cursor.execute("SELECT id FROM alunos WHERE TurmaID=%s", (turma_selecionada,))
        todos_alunos = [row['id'] for row in cursor.fetchall()]

        for aluno_id in todos_alunos:
            presente = 1 if aluno_id in alunos_selecionados else 0

            # Inserir ou atualizar presença por aluno e data
            cursor.execute("""
                INSERT INTO presencas (aluno_id, data_presenca, responsavel_id, responsavel_nome, presente)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    presente = VALUES(presente),
                    responsavel_id = VALUES(responsavel_id),
                    responsavel_nome = VALUES(responsavel_nome),
                    registrado_em = CURRENT_TIMESTAMP
            """, (aluno_id, data_presenca, current_user.id, current_user.nome, presente))

        db.commit()
        db.close()
        flash("Presenças registradas com sucesso!", "success")
        
        # ⚠️ CORREÇÃO/GARANTIA: Referenciando a rota com o prefixo do Blueprint
        return redirect(url_for('presencas.registro_presenca', turma_id=turma_selecionada, data_presenca=data_presenca))

    # Buscar alunos da turma selecionada
    alunos = []
    presencas_registradas = []
    if turma_selecionada:
        cursor.execute("SELECT id, nome FROM alunos WHERE TurmaID=%s ORDER BY nome", (turma_selecionada,))
        alunos = cursor.fetchall()

        if alunos:
            placeholders = ','.join(['%s'] * len(alunos))
            aluno_ids = [a['id'] for a in alunos]
            # Buscar apenas os alunos que tiveram presença (presente=1) na data selecionada
            query = f"""
                SELECT aluno_id 
                FROM presencas 
                WHERE data_presenca=%s AND presente=1 AND aluno_id IN ({placeholders})
            """
            cursor.execute(query, [data_presenca] + aluno_ids)
            presencas_registradas = [row['aluno_id'] for row in cursor.fetchall()]

    db.close()
    return render_template(
        'registro_presenca.html',
        turmas=turmas,
        alunos=alunos,
        turma_selecionada=turma_selecionada,
        data_presenca=data_presenca,
        presencas_registradas=presencas_registradas
    )

# ======================================================
# 🔹 Ata de Presença
# ======================================================
@bp_presencas.route('/ata_presenca', methods=['GET'])
@login_required
def ata_presenca():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    hoje = datetime.today()
    mes_selecionado = int(request.args.get('mes', hoje.month))
    ano_selecionado = int(request.args.get('ano', hoje.year))
    turma_selecionada = int(request.args.get('turma', 0))

    # Buscar turmas
    cursor.execute("SELECT TurmaID, Nome FROM Turmas")
    turmas = {t['TurmaID']: t['Nome'] for t in cursor.fetchall()}

    # Buscar todos os alunos
    cursor.execute("SELECT id, nome, TurmaID FROM alunos ORDER BY nome")
    alunos = cursor.fetchall()
    alunos_por_turma = {}
    for a in alunos:
        alunos_por_turma.setdefault(a['TurmaID'], []).append(a)

    # Buscar presenças
    query = """
        SELECT p.data_presenca, p.aluno_id, p.presente, u.nome AS responsavel, a.TurmaID
        FROM presencas p
        JOIN alunos a ON a.id = p.aluno_id
        JOIN usuarios u ON u.id = p.responsavel_id
        WHERE YEAR(p.data_presenca) = %s
    """
    params = [ano_selecionado]
    if mes_selecionado != 0:
        query += " AND MONTH(p.data_presenca) = %s"
        params.append(mes_selecionado)
    if turma_selecionada != 0:
        query += " AND a.TurmaID = %s"
        params.append(turma_selecionada)

    query += " ORDER BY p.data_presenca"
    cursor.execute(query, tuple(params))
    presencas = cursor.fetchall()
    db.close()

    # Organizar presenças por data e turma
    presencas_por_data = {}
    for p in presencas:
        data_str = p['data_presenca'].strftime("%d/%m/%Y")
        turma_id = p['TurmaID']
        if data_str not in presencas_por_data:
            presencas_por_data[data_str] = {}
        if turma_id not in presencas_por_data[data_str]:
            presencas_por_data[data_str][turma_id] = {
                'presentes': [],
                'responsavel': p['responsavel'],
                'alunos': alunos_por_turma.get(turma_id, [])
            }
        if p['presente'] == 1:
            presencas_por_data[data_str][turma_id]['presentes'].append(p['aluno_id'])

    # 🟢 Corrigido: Agrupar por mês/ano para o template
    presencas_por_mes = {}
    for data, turmas_dict in presencas_por_data.items():
        mes_ano = data[-7:]  # MM/YYYY
        if mes_ano not in presencas_por_mes:
            presencas_por_mes[mes_ano] = {}
        presencas_por_mes[mes_ano][data] = turmas_dict

    presencas_por_mes = dict(sorted(
        presencas_por_mes.items(),
        key=lambda x: datetime.strptime(x[0], "%m/%Y")
    ))

    return render_template('ata_presenca.html',
                            presencas_por_mes=presencas_por_mes,
                            turmas=turmas,
                            mes=mes_selecionado,
                            ano=ano_selecionado,
                            turma_id=turma_selecionada,
                            hoje=hoje)

# ======================================================
# 🔹 Histórico de Presença (Lista de Cards)
# ======================================================
@bp_presencas.route('/historico_presenca_lista')
@login_required
def historico_presenca_lista():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, nome FROM alunos ORDER BY nome")
    alunos = cursor.fetchall()
    db.close()

    hoje = datetime.today()
    return render_template('historico_presenca_lista.html', alunos=alunos, hoje=hoje)

# ======================================================
# 🔹 Histórico de Presença (Endpoint AJAX)
# ======================================================
@bp_presencas.route('/historico_presenca_ajax/<int:aluno_id>')
@login_required
def historico_presenca_ajax(aluno_id):
    # mes=0 => todos os meses do ano informado
    mes = int(request.args.get('mes', 0))
    ano = int(request.args.get('ano', datetime.today().year))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Seleciona presenças do aluno filtrando mês/ano
    if mes == 0:
        cursor.execute("""
            SELECT data_presenca, presente
            FROM presencas
            WHERE aluno_id=%s AND YEAR(data_presenca)=%s
            ORDER BY data_presenca
        """, (aluno_id, ano))
    else:
        cursor.execute("""
            SELECT data_presenca, presente
            FROM presencas
            WHERE aluno_id=%s AND MONTH(data_presenca)=%s AND YEAR(data_presenca)=%s
            ORDER BY data_presenca
        """, (aluno_id, mes, ano))

    registros = cursor.fetchall()
    db.close()

    total = len(registros)
    total_presenca = sum(1 for r in registros if r.get('presente') == 1)
    total_falta = total - total_presenca
    percentual_presenca = round((total_presenca / total * 100), 1) if total > 0 else 0

    # Monta HTML do resumo (será inserido no card)
    html = f"""
    <div class="historico-aluno p-3 border rounded bg-light">
      <ul class="list-group list-group-flush">
        <li class="list-group-item"><strong>Total de Aulas:</strong> {total}</li>
        <li class="list-group-item"><strong>Total de Presenças:</strong> {total_presenca}</li>
        <li class="list-group-item"><strong>Total de Faltas:</strong> {total_falta}</li>
        <li class="list-group-item"><strong>Porcentagem de Presença:</strong> {percentual_presenca}%</li>
      </ul>
    </div>
    """

    return html