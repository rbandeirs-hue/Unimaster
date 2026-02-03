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


def _get_professor_id():
    """Retorna (primeiro professor_id, primeiro id_academia) do current_user."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, id_academia FROM professores WHERE usuario_id = %s AND ativo = 1 LIMIT 1",
            (current_user.id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return (row["id"], row.get("id_academia")) if row else (None, None)
    except Exception:
        return (None, None)


def _get_todos_professor_ids():
    """Retorna lista de professor_id do current_user (pode ter mais de um por academia)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id FROM professores WHERE usuario_id = %s AND ativo = 1 ORDER BY id",
            (current_user.id,),
        )
        ids = [r["id"] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return ids
    except Exception:
        return []


def _get_ids_turmas_professor(professor_id_or_ids):
    """Retorna set de TurmaID vinculadas ao(s) professor(es). Aceita int ou lista."""
    ids = [professor_id_or_ids] if isinstance(professor_id_or_ids, int) else (professor_id_or_ids or [])
    if not ids:
        return set()
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        ph = ",".join(["%s"] * len(ids))
        cur.execute("SELECT TurmaID FROM turma_professor WHERE professor_id IN (%s)" % ph, tuple(ids))
        result = {r["TurmaID"] for r in cur.fetchall()}
        cur.close()
        conn.close()
        return result
    except Exception:
        return set()


def _get_academias_presenca():
    """Retorna (academia_id, academias) para o painel de presenças."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        ids = []
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas:
            cur.close()
            conn.close()
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(vinculadas)), tuple(vinculadas))
            academias = cur.fetchall()
            cur.close()
            conn.close()
            if len(vinculadas) == 1:
                return vinculadas[0], academias
            aid = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
            if aid and aid in vinculadas:
                session["academia_gerenciamento_id"] = aid
                session["finance_academia_id"] = aid
            else:
                aid = vinculadas[0]
                session["academia_gerenciamento_id"] = aid
                session["finance_academia_id"] = aid
            return aid, academias
        if session.get("modo_painel") == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
            cur.close()
            conn.close()
            return None, []
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
            # Professor responsável ou auxiliar (em turma_professor)
            cur.execute("SELECT id_academia FROM professores WHERE usuario_id = %s AND ativo = 1 AND id_academia IS NOT NULL LIMIT 1", (current_user.id,))
            row = cur.fetchone()
            if row and row.get("id_academia"):
                ids = [row["id_academia"]]
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
            session["finance_academia_id"] = aid
        else:
            aid = ids[0]
            session["academia_gerenciamento_id"] = aid
            session["finance_academia_id"] = aid
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
    if modo == "professor":
        back_url = url_for("professor.painel_professor")
    elif modo == "academia":
        back_url = url_for("academia.painel_academia", academia_id=academia_id) if academia_id else url_for("academia.painel_academia")
    else:
        back_url = url_for("painel.home")
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
    aid = request.args.get("academia_id", type=int) or request.form.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    if not aid:
        aid, _ = _get_academias_presenca()
    if not aid:
        return None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas and aid in vinculadas:
            cur.close()
            conn.close()
            return aid
        if current_user.has_role("admin"):
            cur.execute("SELECT 1 FROM academias WHERE id = %s", (aid,))
        elif current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT 1 FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ac.id = %s AND ass.id_federacao = %s",
                (aid, getattr(current_user, "id_federacao", None)),
            )
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT 1 FROM academias WHERE id = %s AND id_associacao = %s", (aid, getattr(current_user, "id_associacao", None)))
        else:
            # Professor responsável ou auxiliar (qualquer um em turma_professor)
            cur.execute("SELECT 1 FROM professores WHERE usuario_id = %s AND id_academia = %s AND ativo = 1", (current_user.id, aid))
        if cur.fetchone():
            ok = True
        else:
            ok = False
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
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

    try:
        if academia_id:
            cursor.execute("SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome", (academia_id,))
        else:
            cursor.execute("SELECT TurmaID, Nome FROM turmas ORDER BY Nome")
        turmas = cursor.fetchall()
        if modo_professor and ids_turmas_professor:
            turmas = [t for t in turmas if t["TurmaID"] in ids_turmas_professor]
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
            if academia_id:
                cursor.execute(
                    """SELECT a.id FROM alunos a
                       LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                       WHERE (at.TurmaID IS NOT NULL OR a.TurmaID = %s) AND a.id_academia = %s""",
                    (turma_selecionada, turma_selecionada, academia_id),
                )
            else:
                cursor.execute("SELECT id FROM alunos WHERE TurmaID=%s", (turma_selecionada,))
            todos_alunos = [row['id'] for row in cursor.fetchall()]
            # Buscar visitantes com aulas experimentais agendadas
            try:
                cursor.execute("""
                    SELECT v.id FROM visitantes v
                    INNER JOIN aulas_experimentais ae ON ae.visitante_id = v.id
                    WHERE ae.turma_id = %s AND ae.data_aula = %s AND v.id_academia = %s AND v.ativo = 1
                """, (turma_selecionada, data_presenca, academia_id))
                for row in cursor.fetchall():
                    vid = f"visitante_{row.get('id')}"
                    if vid not in todos_alunos:
                        todos_alunos.append(vid)
            except Exception:
                pass
        except Exception:
            try:
                cursor.execute("SELECT id FROM alunos WHERE TurmaID=%s", (turma_selecionada,))
                todos_alunos = [row['id'] for row in cursor.fetchall()]
            except Exception:
                todos_alunos = []

        try:
            # Separar alunos e visitantes
            alunos_ids = []
            visitantes_ids = []
            for aluno_id in todos_alunos:
                if isinstance(aluno_id, str) and aluno_id.startswith("visitante_"):
                    visitantes_ids.append(int(aluno_id.replace("visitante_", "")))
                else:
                    alunos_ids.append(aluno_id)
            
            # Registrar presenças de alunos
            for aluno_id in alunos_ids:
                presente = 1 if aluno_id in alunos_selecionados else 0
                # Verificar se é aluno em visita (registrar também na turma original dele)
                cursor.execute("""
                    SELECT s.academia_origem_id, a.TurmaID, a.id_academia
                    FROM solicitacoes_aprovacao s
                    INNER JOIN alunos a ON a.id = s.aluno_id
                    WHERE s.aluno_id = %s AND s.data_visita = %s AND s.status = 'aprovado_destino' 
                      AND s.tipo = 'visita' AND s.turma_id = %s
                    LIMIT 1
                """, (aluno_id, data_presenca, turma_selecionada))
                visita_info = cursor.fetchone()
                
                # Registrar presença na turma atual (academia visitada)
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
                
                # Se é aluno em visita, registrar também na turma original dele
                if visita_info and visita_info.get("TurmaID"):
                    turma_original_id = visita_info["TurmaID"]
                    cursor.execute("""
                        INSERT INTO presencas (aluno_id, turma_id, data_presenca, responsavel_id, responsavel_nome, presente)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            turma_id = VALUES(turma_id),
                            presente = VALUES(presente),
                            responsavel_id = VALUES(responsavel_id),
                            responsavel_nome = VALUES(responsavel_nome),
                            registrado_em = CURRENT_TIMESTAMP
                    """, (aluno_id, turma_original_id, data_presenca, current_user.id, current_user.nome, presente))
            
            # Registrar presenças de visitantes (atualizar aulas_experimentais)
            for visitante_id in visitantes_ids:
                presente = 1 if f"visitante_{visitante_id}" in alunos_selecionados else 0
                # Atualizar aula experimental
                cursor.execute("""
                    UPDATE aulas_experimentais 
                    SET presente = %s, registrado_por = %s
                    WHERE visitante_id = %s AND turma_id = %s AND data_aula = %s
                """, (presente, current_user.id, visitante_id, turma_selecionada, data_presenca))
                
                # Se presente, atualizar contador de aulas realizadas
                if presente:
                    cursor.execute("""
                        UPDATE visitantes 
                        SET aulas_experimentais_realizadas = (
                            SELECT COUNT(*) FROM aulas_experimentais 
                            WHERE visitante_id = %s AND presente = 1 AND data_aula <= CURDATE()
                        )
                        WHERE id = %s
                    """, (visitante_id, visitante_id))
            
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
    if turma_selecionada and academia_id:
        try:
            cursor.execute("SELECT TurmaID FROM turmas WHERE TurmaID = %s AND id_academia = %s", (turma_selecionada, academia_id))
            if not cursor.fetchone():
                turma_selecionada = None
        except Exception:
            turma_selecionada = None
    alunos = []
    alunos_visitantes = []
    if turma_selecionada:
        try:
            if academia_id:
                cursor.execute(
                    """SELECT a.id, a.nome, a.foto FROM alunos a
                       LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                       WHERE (at.TurmaID IS NOT NULL OR a.TurmaID = %s) AND a.id_academia = %s
                       ORDER BY a.nome""",
                    (turma_selecionada, turma_selecionada, academia_id),
                )
            else:
                cursor.execute("SELECT id, nome, foto FROM alunos WHERE TurmaID=%s ORDER BY nome", (turma_selecionada,))
            alunos = cursor.fetchall()
            ids_alunos_turma = {a["id"] for a in alunos}
            
            # Buscar alunos da turma que estão visitando outra academia nesta data
            alunos_visitando_outra_academia = []
            if ids_alunos_turma:
                try:
                    placeholders = ",".join(["%s"] * len(ids_alunos_turma))
                    cursor.execute(f"""
                        SELECT a.id, a.nome, a.foto, s.id AS solicitacao_id, ac_dest.nome AS academia_destino_nome, 
                               s.turma_id AS turma_destino_id, s.academia_destino_id
                        FROM alunos a
                        INNER JOIN solicitacoes_aprovacao s ON s.aluno_id = a.id
                        INNER JOIN academias ac_dest ON ac_dest.id = s.academia_destino_id
                        WHERE a.id IN ({placeholders}) AND s.data_visita = %s AND s.status = 'aprovado_destino' 
                          AND s.tipo = 'visita' AND s.academia_origem_id = %s
                        ORDER BY a.nome
                    """, tuple(ids_alunos_turma) + (data_presenca, academia_id))
                    alunos_visitando_raw = cursor.fetchall()
                    for a in alunos_visitando_raw:
                        a["visitando_outra_academia"] = True
                        a["bloqueado"] = True  # Card bloqueado na turma original
                        alunos_visitando_outra_academia.append(a)
                except Exception:
                    pass
            
            # Buscar visitantes com aulas experimentais agendadas e APROVADAS para esta turma e data
            try:
                cursor.execute("""
                    SELECT v.id, v.nome, v.foto, ae.id AS aula_experimental_id
                    FROM visitantes v
                    INNER JOIN aulas_experimentais ae ON ae.visitante_id = v.id
                    WHERE ae.turma_id = %s AND ae.data_aula = %s AND v.id_academia = %s 
                      AND v.ativo = 1 AND ae.aprovado = 1
                    ORDER BY v.nome
                """, (turma_selecionada, data_presenca, academia_id))
                visitantes_raw = cursor.fetchall()
                for v in visitantes_raw:
                    v["visitante"] = True
                    v["id"] = f"visitante_{v['id']}"  # Prefixo para diferenciar de alunos
                    alunos_visitantes.append(v)
            except Exception:
                pass
            
            # Buscar alunos com solicitações de visita APROVADAS para esta turma e data
            try:
                if ids_alunos_turma:
                    # Se há alunos da turma, excluir da busca de alunos em visita
                    placeholders = ",".join(["%s"] * len(ids_alunos_turma))
                    cursor.execute(f"""
                        SELECT a.id, a.nome, a.foto, s.id AS solicitacao_id, ac_orig.nome AS academia_origem_nome
                        FROM alunos a
                        INNER JOIN solicitacoes_aprovacao s ON s.aluno_id = a.id
                        INNER JOIN academias ac_orig ON ac_orig.id = s.academia_origem_id
                        WHERE s.turma_id = %s AND s.data_visita = %s AND s.academia_destino_id = %s
                          AND s.status = 'aprovado_destino' AND s.tipo = 'visita'
                          AND a.id NOT IN ({placeholders})
                        ORDER BY a.nome
                    """, (turma_selecionada, data_presenca, academia_id) + tuple(ids_alunos_turma))
                else:
                    # Se não há alunos da turma, buscar todos os alunos em visita
                    cursor.execute("""
                        SELECT a.id, a.nome, a.foto, s.id AS solicitacao_id, ac_orig.nome AS academia_origem_nome
                        FROM alunos a
                        INNER JOIN solicitacoes_aprovacao s ON s.aluno_id = a.id
                        INNER JOIN academias ac_orig ON ac_orig.id = s.academia_origem_id
                        WHERE s.turma_id = %s AND s.data_visita = %s AND s.academia_destino_id = %s
                          AND s.status = 'aprovado_destino' AND s.tipo = 'visita'
                        ORDER BY a.nome
                    """, (turma_selecionada, data_presenca, academia_id))
                alunos_visita_raw = cursor.fetchall()
                for a in alunos_visita_raw:
                    a["visitante"] = False  # É aluno, mas visitando outra academia
                    a["aluno_visita"] = True  # Marca como aluno em visita
                    alunos_visitantes.append(a)
            except Exception as e:
                # Se a tabela não existir ou houver erro, continua sem adicionar alunos em visita
                pass
            
            # Adicionar alunos visitando outra academia (cards bloqueados)
            alunos = alunos + alunos_visitantes + alunos_visitando_outra_academia
            alunos.sort(key=lambda x: (x.get("nome") or "").lower())
        except Exception:
            try:
                cursor.execute("SELECT id, nome, foto FROM alunos WHERE TurmaID=%s ORDER BY nome", (turma_selecionada,))
                alunos = cursor.fetchall()
            except Exception:
                alunos = []

        if alunos:
            try:
                # Separar IDs de alunos e visitantes
                aluno_ids_numericos = []
                visitante_ids_numericos = []
                for a in alunos:
                    if isinstance(a.get('id'), str) and a.get('id').startswith('visitante_'):
                        visitante_ids_numericos.append(int(a['id'].replace('visitante_', '')))
                    else:
                        aluno_ids_numericos.append(a['id'])
                
                presencas_registradas = []
                
                # Buscar presenças de alunos (incluindo alunos bloqueados que estão visitando)
                if aluno_ids_numericos:
                    placeholders = ','.join(['%s'] * len(aluno_ids_numericos))
                    cursor.execute(
                        f"SELECT aluno_id FROM presencas WHERE data_presenca=%s AND presente=1 AND aluno_id IN ({placeholders})",
                        [data_presenca] + aluno_ids_numericos
                    )
                    presencas_registradas.extend([row['aluno_id'] for row in cursor.fetchall()])
                    
                    # Para alunos bloqueados (visitando), verificar se foi registrado na academia visitada
                    # Se sim, marcar como presente também na turma original
                    alunos_bloqueados_ids = [a.get("id") for a in alunos if a.get("bloqueado") and a.get("visitando_outra_academia")]
                    if alunos_bloqueados_ids:
                        placeholders_bloq = ','.join(['%s'] * len(alunos_bloqueados_ids))
                        cursor.execute(
                            f"""SELECT DISTINCT aluno_id FROM presencas 
                               WHERE aluno_id IN ({placeholders_bloq}) AND data_presenca = %s AND presente = 1""",
                            alunos_bloqueados_ids + [data_presenca]
                        )
                        presencas_bloqueados = [row['aluno_id'] for row in cursor.fetchall()]
                        for aluno_id in presencas_bloqueados:
                            if aluno_id not in presencas_registradas:
                                presencas_registradas.append(aluno_id)
                
                # Buscar presenças de visitantes (aulas experimentais)
                if visitante_ids_numericos:
                    placeholders = ','.join(['%s'] * len(visitante_ids_numericos))
                    cursor.execute(
                        f"""SELECT visitante_id FROM aulas_experimentais 
                           WHERE data_aula=%s AND presente=1 AND visitante_id IN ({placeholders})""",
                        [data_presenca] + visitante_ids_numericos
                    )
                    for row in cursor.fetchall():
                        presencas_registradas.append(f"visitante_{row['visitante_id']}")
            except Exception:
                presencas_registradas = []

    db.close()
    if modo_professor:
        back_url = url_for("professor.painel_professor")
    else:
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
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

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
        turmas_raw = cursor.fetchall()
        if modo_professor and ids_turmas_professor:
            turmas_raw = [t for t in turmas_raw if t['TurmaID'] in ids_turmas_professor]
        turmas = {t['TurmaID']: t['Nome'] for t in turmas_raw}
    except Exception:
        turmas = {}

    try:
        if academia_id:
            cursor.execute("SELECT id, nome, TurmaID FROM alunos WHERE id_academia = %s ORDER BY nome", (academia_id,))
        else:
            cursor.execute("SELECT id, nome, TurmaID FROM alunos ORDER BY nome")
        alunos = cursor.fetchall()
        if modo_professor and ids_turmas_professor:
            ph = ",".join(["%s"] * len(ids_turmas_professor))
            ids_list = list(ids_turmas_professor)
            cursor.execute(
                f"""SELECT DISTINCT a.id FROM alunos a
                   WHERE a.TurmaID IN ({ph}) OR a.id IN (SELECT aluno_id FROM aluno_turmas WHERE TurmaID IN ({ph}))""",
                ids_list + ids_list,
            )
            ids_ok = {r["id"] for r in cursor.fetchall()}
            alunos = [a for a in alunos if a["id"] in ids_ok]
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
        if modo_professor and ids_turmas_professor:
            ph = ",".join(["%s"] * len(ids_turmas_professor))
            ids_list = list(ids_turmas_professor)
            query += f" AND (a.TurmaID IN ({ph}) OR a.id IN (SELECT aluno_id FROM aluno_turmas WHERE TurmaID IN ({ph})))"
            params.extend(ids_list + ids_list)
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

    if modo_professor:
        back_url = url_for("professor.painel_professor")
    else:
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
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        if academia_id:
            cursor.execute("SELECT id, nome FROM alunos WHERE id_academia = %s ORDER BY nome", (academia_id,))
        else:
            cursor.execute("SELECT id, nome FROM alunos ORDER BY nome")
        alunos = cursor.fetchall()
        if modo_professor and ids_turmas_professor:
            ph = ",".join(["%s"] * len(ids_turmas_professor))
            ids_list = list(ids_turmas_professor)
            cursor.execute(
                f"""SELECT DISTINCT a.id FROM alunos a
                   WHERE a.TurmaID IN ({ph}) OR a.id IN (SELECT aluno_id FROM aluno_turmas WHERE TurmaID IN ({ph}))""",
                ids_list + ids_list,
            )
            ids_ok = {r["id"] for r in cursor.fetchall()}
            alunos = [a for a in alunos if a["id"] in ids_ok]
    except Exception:
        alunos = []
    db.close()

    hoje = datetime.today()
    if modo_professor:
        back_url = url_for("professor.painel_professor")
    else:
        back_url = url_for("presencas.painel_presenca", academia_id=academia_id) if academia_id else url_for("presencas.painel_presenca")
    return render_template('historico_presenca_lista.html', alunos=alunos, hoje=hoje, back_url=back_url, academia_id=academia_id)

# ======================================================
# 🔹 Histórico de Presença (Endpoint AJAX)
# ======================================================
@bp_presencas.route('/historico_presenca_ajax/<int:aluno_id>')
@login_required
def historico_presenca_ajax(aluno_id):
    academia_id = _get_academia_filtro_presencas()
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id, id_academia, TurmaID FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()
    if not aluno:
        db.close()
        return "<p class='alert alert-warning p-2 small'>Aluno não encontrado.</p>"
    if academia_id and aluno.get("id_academia") != academia_id:
        db.close()
        return "<p class='alert alert-warning p-2 small'>Acesso negado.</p>"
    if modo_professor and ids_turmas_professor:
        aluno_turma_ok = aluno.get("TurmaID") in ids_turmas_professor
        if not aluno_turma_ok:
            cursor.execute(
                "SELECT 1 FROM aluno_turmas WHERE aluno_id = %s AND TurmaID IN (%s)" % (aluno_id, ",".join(["%s"] * len(ids_turmas_professor))),
                tuple(ids_turmas_professor),
            )
            aluno_turma_ok = cursor.fetchone() is not None
        if not aluno_turma_ok:
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