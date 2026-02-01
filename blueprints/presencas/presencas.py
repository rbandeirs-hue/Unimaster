# ======================================================
# 🧩 Blueprint: Presenças
# ======================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from config import get_db_connection
from datetime import date, datetime
import re # Necessário para o histórico/ajax se mantiver a lógica original

# ⚠️ O nome 'presencas' será usado para referenciar as rotas: url_for('presencas.registro_presenca')
bp_presencas = Blueprint("presencas", __name__)


def _get_academias_presenca():
    """Retorna (academia_id, academias) para o painel de presenças."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
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
        elif getattr(current_user, "id_academia", None):
            ids = [current_user.id_academia]
        cur.close()
        conn.close()
        if not ids:
            return None, []
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids)), tuple(ids))
        academias = cur.fetchall()
        cur.close()
        conn.close()
        if len(ids) == 1:
            return ids[0], academias
        aid = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
        if aid and aid in ids:
            session["academia_gerenciamento_id"] = aid
        else:
            session["academia_gerenciamento_id"] = ids[0]
            aid = ids[0]
        return aid, academias
    except Exception:
        return None, []


# ======================================================
# 🔹 Painel Presença (Módulo com 3 opções)
# ======================================================
@bp_presencas.route("/presencas", methods=["GET"])
@login_required
def painel_presenca():
    """Hub do módulo Presença: Registrar, Relatório, Histórico."""
    academia_id, academias = _get_academias_presenca()
    academias = academias or []
    modo = session.get("modo_painel")
    back_url = (url_for("academia.painel_academia", academia_id=academia_id) if academia_id else url_for("academia.painel_academia")) if modo == "academia" else url_for("painel.home")
    return render_template(
        "presencas/painel_presenca.html",
        academias=academias,
        academia_id=academia_id,
        back_url=back_url,
    )


# ======================================================
# 🔹 Registro de Presença
# ======================================================
def _get_academia_filtro_presencas():
    """Retorna academia_id para filtrar (ata, historico, registro)."""
    aid = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    if not aid and getattr(current_user, "id_academia", None):
        aid = current_user.id_academia
    if not aid:
        aid, _ = _get_academias_presenca()
    if not aid:
        return None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        if current_user.has_role("admin"):
            cur.execute("SELECT 1 FROM academias WHERE id = %s", (aid,))
        elif current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT 1 FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ac.id = %s AND ass.id_federacao = %s",
                (aid, getattr(current_user, "id_federacao", None)),
            )
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT 1 FROM academias WHERE id = %s AND id_associacao = %s", (aid, getattr(current_user, "id_associacao", None)))
        elif getattr(current_user, "id_academia", None) == aid:
            cur.execute("SELECT 1 FROM academias WHERE id = %s", (aid,))
        else:
            cur.close()
            conn.close()
            return None
        ok = cur.fetchone() is not None
        cur.close()
        conn.close()
        return aid if ok else None
    except Exception:
        return None


@bp_presencas.route('/registro_presenca', methods=['GET', 'POST'])
@login_required
def registro_presenca():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    academia_id = _get_academia_filtro_presencas()

    try:
        if academia_id:
            cursor.execute("SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome", (academia_id,))
        else:
            cursor.execute("SELECT TurmaID, Nome FROM turmas ORDER BY Nome")
        turmas = cursor.fetchall()
    except Exception:
        turmas = []

    # Seleção da turma e data
    turma_selecionada = request.form.get('turma_id') or request.args.get('turma_id')
    turma_selecionada = int(turma_selecionada) if turma_selecionada else None
    data_presenca = request.form.get('data_presenca') or request.args.get('data_presenca') or date.today().strftime('%Y-%m-%d')

    if request.method == 'POST' and turma_selecionada:
        try:
            alunos_selecionados = [int(a) for a in request.form.getlist('aluno_id')]
        except (ValueError, TypeError):
            alunos_selecionados = []

        try:
            cursor.execute("SELECT id FROM alunos WHERE TurmaID=%s", (turma_selecionada,))
            todos_alunos = [row['id'] for row in cursor.fetchall()]
        except Exception:
            todos_alunos = []

        try:
            for aluno_id in todos_alunos:
                presente = 1 if aluno_id in alunos_selecionados else 0
                cursor.execute("""
                    INSERT INTO presencas (aluno_id, turma_id, data_presenca, responsavel_id, responsavel_nome, presente)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        turma_id = VALUES(turma_id),
                        presente = VALUES(presente),
                        responsavel_id = VALUES(responsavel_id),
                        responsavel_nome = VALUES(responsavel_nome),
                        registrado_em = CURRENT_TIMESTAMP
                """, (aluno_id, turma_selecionada, data_presenca, current_user.id, current_user.nome, presente))
            db.commit()
            flash("Presenças registradas com sucesso!", "success")
        except Exception as e:
            db.rollback()
            flash(f"Erro ao registrar presenças: {e}", "danger")

        db.close()
        
        # ⚠️ CORREÇÃO/GARANTIA: Referenciando a rota com o prefixo do Blueprint
        kwargs = {"turma_id": turma_selecionada, "data_presenca": data_presenca}
        if academia_id:
            kwargs["academia_id"] = academia_id
        return redirect(url_for("presencas.registro_presenca", **kwargs))

    alunos = []
    presencas_registradas = []
    if turma_selecionada:
        try:
            cursor.execute("SELECT id, nome, foto FROM alunos WHERE TurmaID=%s ORDER BY nome", (turma_selecionada,))
            alunos = cursor.fetchall()
        except Exception:
            alunos = []

        if alunos:
            try:
                placeholders = ','.join(['%s'] * len(alunos))
                aluno_ids = [a['id'] for a in alunos]
                cursor.execute(
                    f"SELECT aluno_id FROM presencas WHERE data_presenca=%s AND presente=1 AND aluno_id IN ({placeholders})",
                    [data_presenca] + aluno_ids
                )
                presencas_registradas = [row['aluno_id'] for row in cursor.fetchall()]
            except Exception:
                presencas_registradas = []

    db.close()
    back_url = url_for("presencas.painel_presenca", academia_id=academia_id) if academia_id else url_for("presencas.painel_presenca")
    return render_template(
        'registro_presenca.html',
        turmas=turmas,
        alunos=alunos,
        turma_selecionada=turma_selecionada,
        data_presenca=data_presenca,
        presencas_registradas=presencas_registradas,
        academia_id=academia_id,
        back_url=back_url,
    )

# ======================================================
# 🔹 Ata de Presença
# ======================================================
@bp_presencas.route('/ata_presenca', methods=['GET'])
@login_required
def ata_presenca():
    academia_id = _get_academia_filtro_presencas()

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    hoje = datetime.today()
    mes_selecionado = int(request.args.get('mes', hoje.month))
    ano_selecionado = int(request.args.get('ano', hoje.year))
    turma_selecionada = int(request.args.get('turma', 0))

    try:
        if academia_id:
            try:
                cursor.execute("SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome", (academia_id,))
            except Exception:
                cursor.execute("SELECT TurmaID, Nome FROM turmas ORDER BY Nome")
        else:
            cursor.execute("SELECT TurmaID, Nome FROM turmas ORDER BY Nome")
        turmas = {t['TurmaID']: t['Nome'] for t in cursor.fetchall()}
    except Exception:
        turmas = {}

    try:
        if academia_id:
            cursor.execute("SELECT id, nome, TurmaID FROM alunos WHERE id_academia = %s ORDER BY nome", (academia_id,))
        else:
            cursor.execute("SELECT id, nome, TurmaID FROM alunos ORDER BY nome")
        alunos = cursor.fetchall()
    except Exception:
        alunos = []
    alunos_por_turma = {}
    for a in alunos:
        alunos_por_turma.setdefault(a.get('TurmaID'), []).append(a)

    presencas = []
    try:
        query = """
            SELECT p.data_presenca, p.aluno_id, p.presente,
                   COALESCE(u.nome, p.responsavel_nome, '-') AS responsavel, a.TurmaID,
                   p.registrado_em
            FROM presencas p
            JOIN alunos a ON a.id = p.aluno_id
            LEFT JOIN usuarios u ON u.id = p.responsavel_id
            WHERE YEAR(p.data_presenca) = %s
        """
        params = [ano_selecionado]
        if mes_selecionado != 0:
            query += " AND MONTH(p.data_presenca) = %s"
            params.append(mes_selecionado)
        if turma_selecionada != 0:
            query += " AND a.TurmaID = %s"
            params.append(turma_selecionada)
        if academia_id:
            query += " AND a.id_academia = %s"
            params.append(academia_id)
        query += " ORDER BY p.data_presenca"
        cursor.execute(query, tuple(params))
        presencas = cursor.fetchall()
    except Exception as e:
        flash(f"Erro ao carregar presenças: {e}", "danger")

    db.close()

    presencas_por_data = {}
    for p in presencas:
        dp = p.get('data_presenca')
        if not dp:
            continue
        data_str = dp.strftime("%d/%m/%Y") if hasattr(dp, 'strftime') else str(dp)
        turma_id = p.get('TurmaID')
        if data_str not in presencas_por_data:
            presencas_por_data[data_str] = {}
        if turma_id not in presencas_por_data[data_str]:
            presencas_por_data[data_str][turma_id] = {
                'presentes': [],
                'responsavel': p.get('responsavel', '-'),
                'registros_em': [],
                'alunos': alunos_por_turma.get(turma_id, [])
            }
        if p.get('presente') == 1:
            presencas_por_data[data_str][turma_id]['presentes'].append(p.get('aluno_id'))
        reg_em = p.get('registrado_em')
        if reg_em:
            presencas_por_data[data_str][turma_id]['registros_em'].append(reg_em)
    for data_str, turmas_d in presencas_por_data.items():
        for tid, reg in turmas_d.items():
            reg['abertura_registro'] = min(reg['registros_em']) if reg.get('registros_em') else None
            reg.pop('registros_em', None)

    presencas_por_mes = {}
    for data, turmas_dict in presencas_por_data.items():
        mes_ano = data[-7:] if len(data) >= 7 else data
        if mes_ano not in presencas_por_mes:
            presencas_por_mes[mes_ano] = {}
        presencas_por_mes[mes_ano][data] = turmas_dict

    try:
        def _parse_mes_ano(s):
            partes = s.split('/')
            if len(partes) >= 2:
                m, a = int(partes[0]) if partes[0].isdigit() else 1, int(partes[-1]) if partes[-1].isdigit() else 2025
                return (a, m)
            return (2025, 1)
        presencas_por_mes = dict(sorted(presencas_por_mes.items(), key=lambda x: _parse_mes_ano(x[0])))
    except (ValueError, TypeError, IndexError):
        pass

    back_url = url_for("presencas.painel_presenca", academia_id=academia_id) if academia_id else url_for("presencas.painel_presenca")
    return render_template('ata_presenca.html',
                            presencas_por_mes=presencas_por_mes,
                            turmas=turmas,
                            mes=mes_selecionado,
                            ano=ano_selecionado,
                            turma_id=turma_selecionada,
                            hoje=hoje,
                            back_url=back_url,
                            academia_id=academia_id)

# ======================================================
# 🔹 Histórico de Presença (Lista de Cards)
# ======================================================
@bp_presencas.route('/historico_presenca_lista')
@login_required
def historico_presenca_lista():
    academia_id = _get_academia_filtro_presencas()

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        if academia_id:
            cursor.execute("SELECT id, nome FROM alunos WHERE id_academia = %s ORDER BY nome", (academia_id,))
        else:
            cursor.execute("SELECT id, nome FROM alunos ORDER BY nome")
        alunos = cursor.fetchall()
    except Exception:
        alunos = []
    db.close()

    hoje = datetime.today()
    academia_id = _get_academia_filtro_presencas()
    back_url = url_for("presencas.painel_presenca", academia_id=academia_id) if academia_id else url_for("presencas.painel_presenca")
    return render_template('historico_presenca_lista.html', alunos=alunos, hoje=hoje, back_url=back_url, academia_id=academia_id)

# ======================================================
# 🔹 Histórico de Presença (Endpoint AJAX)
# ======================================================
@bp_presencas.route('/historico_presenca_ajax/<int:aluno_id>')
@login_required
def historico_presenca_ajax(aluno_id):
    academia_id = _get_academia_filtro_presencas()

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id, id_academia FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()
    if not aluno:
        db.close()
        return "<p class='alert alert-warning p-2 small'>Aluno não encontrado.</p>"
    if academia_id and aluno.get("id_academia") != academia_id:
        db.close()
        return "<p class='alert alert-warning p-2 small'>Acesso negado.</p>"

    mes = int(request.args.get('mes', 0))
    ano = int(request.args.get('ano', datetime.today().year))

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