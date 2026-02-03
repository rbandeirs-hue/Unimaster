# blueprints/academia/routes.py
from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, session, request, jsonify, current_app
from flask_login import login_required, current_user
from config import get_db_connection
from werkzeug.security import generate_password_hash
from math import ceil
from blueprints.auth.user_model import Usuario

academia_bp = Blueprint("academia", __name__, url_prefix="/academia")


def _calcular_idade_visitante(data_nascimento):
    """Calcula idade a partir da data de nascimento."""
    if not data_nascimento:
        return None
    try:
        from datetime import datetime
        if isinstance(data_nascimento, str):
            nasc = datetime.strptime(data_nascimento[:10], "%Y-%m-%d").date()
        else:
            nasc = data_nascimento
        hoje = date.today()
        idade = hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
        return idade
    except Exception:
        return None


# ======================================================
# 🔹 MÓDULO DE VISITANTES - ACADEMIA
# ======================================================

# ======================================================
# 🔹 Lista de Visitantes (Histórico)
# ======================================================
@academia_bp.route("/visitantes")
@login_required
def lista_visitantes():
    """Lista todos os visitantes da academia com histórico."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    
    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar todos os visitantes da academia
        cur.execute("""
            SELECT v.*, u.email AS usuario_email,
                   COUNT(DISTINCT ae.id) AS total_aulas,
                   COUNT(DISTINCT CASE WHEN ae.presente = 1 THEN ae.id END) AS aulas_presentes,
                   MAX(ae.data_aula) AS ultima_aula
            FROM visitantes v
            LEFT JOIN usuarios u ON u.id = v.usuario_id
            LEFT JOIN aulas_experimentais ae ON ae.visitante_id = v.id
            WHERE v.id_academia = %s
            GROUP BY v.id
            ORDER BY v.criado_em DESC
        """, (academia_id,))
        visitantes = cur.fetchall()
        
        # Processar dados
        for v in visitantes:
            v["idade"] = _calcular_idade_visitante(v.get("data_nascimento"))
            if v.get("foto"):
                v["foto_url"] = f"uploads/{v['foto']}"
            else:
                v["foto_url"] = None
        
        # Estatísticas
        cur.execute("""
            SELECT 
                COUNT(*) AS total_visitantes,
                COUNT(CASE WHEN ativo = 1 THEN 1 END) AS visitantes_ativos,
                COUNT(DISTINCT ae.visitante_id) AS visitantes_com_aulas
            FROM visitantes v
            LEFT JOIN aulas_experimentais ae ON ae.visitante_id = v.id
            WHERE v.id_academia = %s
        """, (academia_id,))
        stats = cur.fetchone()
        
    except Exception as e:
        flash(f"Erro ao carregar visitantes: {e}", "danger")
        visitantes = []
        stats = {"total_visitantes": 0, "visitantes_ativos": 0, "visitantes_com_aulas": 0}
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "academia/visitantes/lista.html",
        visitantes=visitantes,
        stats=stats,
        academias=academias,
        academia_id=academia_id,
    )


# ======================================================
# 🔹 Detalhes do Visitante
# ======================================================
@academia_bp.route("/visitantes/<int:visitante_id>")
@login_required
def detalhes_visitante(visitante_id):
    """Detalhes e histórico completo de um visitante."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar visitante
        cur.execute("""
            SELECT v.*, u.email AS usuario_email, ac.nome AS academia_nome
            FROM visitantes v
            LEFT JOIN usuarios u ON u.id = v.usuario_id
            LEFT JOIN academias ac ON ac.id = v.id_academia
            WHERE v.id = %s AND v.id_academia = %s
        """, (visitante_id, academia_id))
        visitante = cur.fetchone()
        
        if not visitante:
            flash("Visitante não encontrado.", "danger")
            conn.close()
            return redirect(url_for("academia.lista_visitantes", academia_id=academia_id))
        
        visitante["idade"] = _calcular_idade_visitante(visitante.get("data_nascimento"))
        
        # Buscar histórico completo de aulas
        cur.execute("""
            SELECT ae.*, t.Nome AS turma_nome, t.DiasHorario,
                   u.nome AS registrado_por_nome
            FROM aulas_experimentais ae
            INNER JOIN turmas t ON t.TurmaID = ae.turma_id
            LEFT JOIN usuarios u ON u.id = ae.registrado_por
            WHERE ae.visitante_id = %s
            ORDER BY ae.data_aula DESC
        """, (visitante_id,))
        historico_aulas = cur.fetchall()
        
    except Exception as e:
        flash(f"Erro ao carregar dados: {e}", "danger")
        visitante = None
        historico_aulas = []
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "academia/visitantes/detalhes.html",
        visitante=visitante,
        historico_aulas=historico_aulas,
        academias=academias,
        academia_id=academia_id,
    )


# ======================================================
# 🔹 Solicitações de Aulas Experimentais (Aprovação)
# ======================================================
@academia_bp.route("/visitantes/solicitacoes")
@login_required
def solicitacoes_aulas():
    """Lista solicitações de aulas experimentais pendentes de aprovação."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    
    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar aulas experimentais agendadas (pendentes e futuras)
        cur.execute("""
            SELECT ae.*, v.nome AS visitante_nome, v.foto AS visitante_foto,
                   v.email AS visitante_email, v.telefone AS visitante_telefone,
                   v.data_nascimento AS visitante_data_nascimento,
                   t.Nome AS turma_nome, t.DiasHorario,
                   CASE 
                       WHEN ae.data_aula < CURDATE() THEN 'realizada'
                       WHEN ae.data_aula = CURDATE() THEN 'hoje'
                       ELSE 'agendada'
                   END AS status_aula
            FROM aulas_experimentais ae
            INNER JOIN visitantes v ON v.id = ae.visitante_id
            INNER JOIN turmas t ON t.TurmaID = ae.turma_id
            WHERE v.id_academia = %s
            ORDER BY ae.data_aula ASC, ae.registrado_em DESC
        """, (academia_id,))
        solicitacoes = cur.fetchall()
        
        # Separar por status e aprovação
        # Pendentes: agendadas e não aprovadas
        pendentes = [s for s in solicitacoes if s["status_aula"] == "agendada" and not s.get("aprovado")]
        # Hoje: aulas de hoje (aprovadas ou não)
        hoje = [s for s in solicitacoes if s["status_aula"] == "hoje"]
        # Realizadas: aulas passadas
        realizadas = [s for s in solicitacoes if s["status_aula"] == "realizada"]
        
        # Processar dados
        for s in solicitacoes:
            s["idade"] = _calcular_idade_visitante(s.get("visitante_data_nascimento"))
            if s.get("visitante_foto"):
                s["foto_url"] = f"uploads/{s['visitante_foto']}"
            else:
                s["foto_url"] = None
        
    except Exception as e:
        flash(f"Erro ao carregar solicitações: {e}", "danger")
        pendentes = []
        hoje = []
        realizadas = []
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "academia/visitantes/solicitacoes.html",
        pendentes=pendentes,
        hoje=hoje,
        realizadas=realizadas,
        academias=academias,
        academia_id=academia_id,
    )


# ======================================================
# 🔹 Aprovar/Rejeitar Solicitação
# ======================================================
@academia_bp.route("/visitantes/solicitacoes/<int:aula_id>/aprovar", methods=["POST"])
@login_required
def aprovar_solicitacao(aula_id):
    """Aprova uma solicitação de aula experimental."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin")
    ):
        return jsonify({"ok": False, "msg": "Acesso negado"}), 403
    
    academia_id, _ = _get_academia_gerenciamento()
    if not academia_id:
        return jsonify({"ok": False, "msg": "Academia não encontrada"}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Verificar se a aula pertence à academia
        cur.execute("""
            SELECT ae.*, v.id_academia
            FROM aulas_experimentais ae
            INNER JOIN visitantes v ON v.id = ae.visitante_id
            WHERE ae.id = %s AND v.id_academia = %s
        """, (aula_id, academia_id))
        aula = cur.fetchone()
        
        if not aula:
            conn.close()
            return jsonify({"ok": False, "msg": "Solicitação não encontrada"}), 404
        
        # Marcar como aprovado
        cur.execute("""
            UPDATE aulas_experimentais 
            SET aprovado = 1 
            WHERE id = %s
        """, (aula_id,))
        
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "msg": "Solicitação aprovada com sucesso! O visitante aparecerá na chamada."})
        
    except Exception as e:
        conn.close()
        return jsonify({"ok": False, "msg": f"Erro: {e}"}), 500


# ======================================================
# 🔹 Cancelar/Rejeitar Solicitação
# ======================================================
@academia_bp.route("/visitantes/solicitacoes/<int:aula_id>/cancelar", methods=["POST"])
@login_required
def cancelar_solicitacao(aula_id):
    """Cancela/rejeita uma solicitação de aula experimental."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin")
    ):
        return jsonify({"ok": False, "msg": "Acesso negado"}), 403
    
    academia_id, _ = _get_academia_gerenciamento()
    if not academia_id:
        return jsonify({"ok": False, "msg": "Academia não encontrada"}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Verificar se a aula pertence à academia
        cur.execute("""
            SELECT ae.*, v.id_academia
            FROM aulas_experimentais ae
            INNER JOIN visitantes v ON v.id = ae.visitante_id
            WHERE ae.id = %s AND v.id_academia = %s
        """, (aula_id, academia_id))
        aula = cur.fetchone()
        
        if not aula:
            conn.close()
            return jsonify({"ok": False, "msg": "Solicitação não encontrada"}), 404
        
        # Só pode cancelar se ainda não foi realizada
        if aula["data_aula"] < date.today():
            conn.close()
            return jsonify({"ok": False, "msg": "Não é possível cancelar uma aula já realizada"}), 400
        
        # Deletar aula experimental
        cur.execute("DELETE FROM aulas_experimentais WHERE id = %s", (aula_id,))
        
        # Atualizar contador de aulas realizadas
        cur.execute("""
            UPDATE visitantes 
            SET aulas_experimentais_realizadas = (
                SELECT COUNT(*) FROM aulas_experimentais 
                WHERE visitante_id = %s AND presente = 1 AND data_aula <= CURDATE()
            )
            WHERE id = %s
        """, (aula["visitante_id"], aula["visitante_id"]))
        
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "msg": "Solicitação cancelada com sucesso"})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "msg": f"Erro: {e}"}), 500
def _get_academias_ids():
    """Retorna IDs de academias acessíveis (prioridade: usuarios_academias, igual ao financeiro)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ids = []
    try:
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
    except Exception:
        pass
    cur.close()
    conn.close()
    return ids


def _get_academia_filtro():
    """Retorna academia_id ativa (session ou primeira) e lista de academias para seleção."""
    ids = _get_academias_ids()
    if not ids:
        return None, []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    if len(ids) == 1:
        aid = ids[0]
        session["academia_gerenciamento_id"] = aid
        session["finance_academia_id"] = aid
        session["academia_usuarios_id"] = aid
        cur.execute("SELECT id, nome FROM academias WHERE id = %s", (aid,))
        ac = cur.fetchone()
        cur.close()
        conn.close()
        return aid, [ac] if ac else []
    aid = (
        request.args.get("academia_id", type=int)
        or session.get("academia_gerenciamento_id")
        or session.get("academia_usuarios_id")
    )
    if aid and aid in ids:
        session["academia_usuarios_id"] = aid
        session["academia_gerenciamento_id"] = aid
        session["finance_academia_id"] = aid
    else:
        aid = ids[0]
        session["academia_usuarios_id"] = aid
        session["academia_gerenciamento_id"] = aid
        session["finance_academia_id"] = aid
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids)), tuple(ids))
    academias = cur.fetchall()
    cur.close()
    conn.close()
    return aid, academias


def _get_academia_gerenciamento():
    """Retorna academia_id ativa para gerenciamento e lista de academias para seleção."""
    ids = _get_academias_ids()
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


def _get_academia_stats(academia_id=None):
    """Retorna stats da academia. Usa academia_id passado ou current_user.id_academia."""
    stats = {"alunos": 0, "turmas": 0, "professores": 0, "receitas_mes": 0.0, "despesas_mes": 0.0}
    aid = academia_id or getattr(current_user, "id_academia", None)
    if not aid:
        return stats
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) as c FROM alunos WHERE id_academia = %s", (aid,))
        stats["alunos"] = cur.fetchone().get("c") or 0
        cur.execute("SELECT COUNT(*) as c FROM turmas WHERE id_academia = %s", (aid,))
        stats["turmas"] = cur.fetchone().get("c") or 0
        cur.execute("SELECT COUNT(*) as c FROM professores WHERE id_academia = %s", (aid,))
        stats["professores"] = cur.fetchone().get("c") or 0
        mes, ano = date.today().month, date.today().year
        cur.execute(
            "SELECT COALESCE(SUM(valor), 0) as total FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
            (aid, mes, ano),
        )
        stats["receitas_mes"] = float(cur.fetchone().get("total") or 0)
        cur.execute(
            "SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
            (aid, mes, ano),
        )
        stats["despesas_mes"] = float(cur.fetchone().get("total") or 0)
        cur.close()
        conn.close()
    except Exception:
        pass
    return stats


# =====================================================
# 🔹 Dash da Academia (apenas estatísticas)
# =====================================================
@academia_bp.route("/dash")
@login_required
def dash():
    if not (current_user.has_role("gestor_academia") or current_user.has_role("professor") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id
    stats = _get_academia_stats(academia_id)
    return render_template("painel/academia_dash.html", stats=stats, academias=academias, academia_id=academia_id)


# =====================================================
# 🔹 Painel da Academia (Gerenciamento - cards)
# =====================================================
@academia_bp.route("/")
@login_required
def painel_academia():

    # =====================================================
    # 🔥 RBAC — Perfis permitidos:
    #  - gestor_academia
    #  - professor
    #  - admin
    #  - gestor_federacao / gestor_associacao (com academias)
    # =====================================================
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
    academia = cur.fetchone()
    cur.close()
    conn.close()

    return render_template(
        "painel/painel_academia.html",
        usuario=current_user,
        academia=academia,
        academias=academias,
        academia_id=academia_id,
    )


# =====================================================
# 🔹 Lista de Usuários da Academia
# =====================================================
@academia_bp.route("/usuarios")
@login_required
def lista_usuarios():
    """Lista usuários vinculados à academia ou à associação."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    # Verificar se está no modo associação
    origem_associacao = request.args.get("origem") == "associacao"
    modo_associacao = (
        origem_associacao or 
        (session.get("modo_painel") == "associacao" and current_user.has_role("gestor_associacao"))
    )
    
    busca = request.args.get("busca", "").strip()
    page = int(request.args.get("page", 1))
    por_pagina = 10
    offset = (page - 1) * por_pagina
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    
    try:
        if modo_associacao and current_user.has_role("gestor_associacao"):
            # Modo associação: buscar usuários de todas as academias da associação
            associacao_id = getattr(current_user, "id_associacao", None)
            if not associacao_id:
                flash("Associação não encontrada.", "warning")
                cur.close()
                conn.close()
                return redirect(url_for("painel.home"))
            
            # Buscar academias da associação
            cur.execute("SELECT id, nome FROM academias WHERE id_associacao = %s ORDER BY nome", (associacao_id,))
            academias = cur.fetchall()
            
            if not academias:
                flash("Nenhuma academia encontrada nesta associação.", "warning")
                cur.close()
                conn.close()
                return redirect(url_for("associacao.gerenciamento_associacao"))
            
            academia_ids = [ac["id"] for ac in academias]
            academia_id_selecionada = request.args.get("academia_id", type=int)
            
            # Se uma academia específica foi selecionada, filtrar por ela; senão, mostrar todas
            if academia_id_selecionada and academia_id_selecionada in academia_ids:
                filtro_academia = "ua.academia_id = %s"
                params_base = [academia_id_selecionada]
                academia_nome = next((ac["nome"] for ac in academias if ac["id"] == academia_id_selecionada), "Academia")
                academia_id = academia_id_selecionada
            else:
                # Mostrar usuários de todas as academias da associação
                placeholders = ",".join(["%s"] * len(academia_ids))
                filtro_academia = f"ua.academia_id IN ({placeholders})"
                params_base = academia_ids
                academia_nome = "Associação"
                academia_id = None
            
            # Contar total de usuários
            if busca:
                params_count = tuple(params_base) + (f"%{busca}%", f"%{busca}%")
                cur.execute(f"""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE {filtro_academia}
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                """, params_count)
            else:
                cur.execute(f"""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE {filtro_academia}
                """, tuple(params_base))
            
            result_total = cur.fetchone()
            total = result_total["total"] if result_total else 0
            total_paginas = ceil(total / por_pagina) if total > 0 else 1
            
            # Buscar usuários com informações das academias vinculadas
            if busca:
                params_query = tuple(params_base) + (f"%{busca}%", f"%{busca}%", por_pagina, offset)
                cur.execute(f"""
                    SELECT DISTINCT u.id, u.nome, u.email, u.criado_em,
                           COALESCE(u.ativo, 1) AS ativo,
                           GROUP_CONCAT(DISTINCT ac.nome ORDER BY ac.nome SEPARATOR ', ') AS academias_vinculadas
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    INNER JOIN academias ac ON ac.id = ua.academia_id
                    WHERE {filtro_academia}
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                    GROUP BY u.id, u.nome, u.email, u.criado_em, u.ativo
                    ORDER BY u.nome
                    LIMIT %s OFFSET %s
                """, params_query)
            else:
                params_query = tuple(params_base) + (por_pagina, offset)
                cur.execute(f"""
                    SELECT DISTINCT u.id, u.nome, u.email, u.criado_em,
                           COALESCE(u.ativo, 1) AS ativo,
                           GROUP_CONCAT(DISTINCT ac.nome ORDER BY ac.nome SEPARATOR ', ') AS academias_vinculadas
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    INNER JOIN academias ac ON ac.id = ua.academia_id
                    WHERE {filtro_academia}
                    GROUP BY u.id, u.nome, u.email, u.criado_em, u.ativo
                    ORDER BY u.nome
                    LIMIT %s OFFSET %s
                """, params_query)
            
            usuarios = cur.fetchall()
            
            # Buscar nome da associação
            cur.execute("SELECT nome FROM associacoes WHERE id = %s", (associacao_id,))
            result_assoc = cur.fetchone()
            associacao_nome = result_assoc["nome"] if result_assoc else None
            
        else:
            # Modo academia: comportamento original
            academia_id, academias = _get_academia_gerenciamento()
            if not academia_id:
                flash("Nenhuma academia disponível.", "warning")
                cur.close()
                conn.close()
                return redirect(url_for("painel.home"))
            
            session["modo_painel"] = "academia"
            session["academia_gerenciamento_id"] = academia_id
            
            # Buscar nome da academia
            cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
            result_academia = cur.fetchone()
            academia_nome = result_academia["nome"] if result_academia else "Academia"
            associacao_nome = None
            
            # Contar total de usuários vinculados à academia
            if busca:
                cur.execute("""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                """, (academia_id, f"%{busca}%", f"%{busca}%"))
            else:
                cur.execute("""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                """, (academia_id,))
            
            result_total = cur.fetchone()
            total = result_total["total"] if result_total else 0
            total_paginas = ceil(total / por_pagina) if total > 0 else 1
            
            # Buscar usuários vinculados à academia
            if busca:
                cur.execute("""
                    SELECT DISTINCT u.id, u.nome, u.email, u.criado_em,
                           COALESCE(u.ativo, 1) AS ativo,
                           NULL AS academias_vinculadas
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                    ORDER BY u.nome
                    LIMIT %s OFFSET %s
                """, (academia_id, f"%{busca}%", f"%{busca}%", por_pagina, offset))
            else:
                cur.execute("""
                    SELECT DISTINCT u.id, u.nome, u.email, u.criado_em,
                           COALESCE(u.ativo, 1) AS ativo,
                           NULL AS academias_vinculadas
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                    ORDER BY u.nome
                    LIMIT %s OFFSET %s
                """, (academia_id, por_pagina, offset))
            
            usuarios = cur.fetchall()
        
    except Exception as e:
        flash(f"Erro ao carregar usuários: {e}", "danger")
        usuarios = []
        total_paginas = 1
        academia_nome = "Academia"
        associacao_nome = None
        academias = []
        academia_id = None
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "academia/lista_usuarios.html",
        usuarios=usuarios,
        academias=academias if modo_associacao else academias,
        academia_id=academia_id if not modo_associacao else (academia_id if academia_id else None),
        academia_nome=academia_nome,
        associacao_nome=associacao_nome,
        modo_associacao=modo_associacao,
        busca=busca,
        pagina_atual=page,
        total_paginas=total_paginas,
    )


# =====================================================
# 🔹 Configurações da Academia
# =====================================================
@academia_bp.route("/configuracoes", methods=["GET", "POST"])
@login_required
def configuracoes_academia():
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    
    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        if request.method == "POST":
            aulas_permitidas = request.form.get("aulas_experimentais_permitidas", "").strip()
            if aulas_permitidas == "":
                aulas_permitidas = None
            elif aulas_permitidas.isdigit():
                aulas_permitidas = int(aulas_permitidas)
            else:
                aulas_permitidas = None
            
            cur.execute("""
                UPDATE academias 
                SET aulas_experimentais_permitidas = %s 
                WHERE id = %s
            """, (aulas_permitidas, academia_id))
            conn.commit()
            flash("Configurações salvas com sucesso!", "success")
        
        cur.execute("SELECT * FROM academias WHERE id = %s", (academia_id,))
        academia = cur.fetchone()
        
    except Exception as e:
        flash(f"Erro ao processar configurações: {e}", "danger")
        cur.execute("SELECT * FROM academias WHERE id = %s", (academia_id,))
        academia = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "painel/configuracoes_academia.html",
        academia=academia,
        academias=academias,
        academia_id=academia_id,
    )


# =====================================================
# 🔹 Cadastro de Usuário na Academia
# =====================================================
@academia_bp.route("/usuarios/cadastro", methods=["GET", "POST"])
@login_required
def cadastro_usuario():
    """Cadastra novo usuário vinculado à academia."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    
    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id
    
    back_url = request.args.get("next") or request.referrer or url_for("academia.lista_usuarios")
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    # Buscar roles disponíveis
    cur.execute("""
        SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) as chave 
        FROM roles 
        WHERE chave IN ('aluno', 'professor', 'gestor_academia', 'gestor_associacao', 'responsavel', 'visitante')
           OR nome IN ('Aluno', 'Professor', 'Gestor Academia', 'Gestor Associação', 'Responsável', 'Visitante')
        ORDER BY 
            CASE chave
                WHEN 'aluno' THEN 1
                WHEN 'professor' THEN 2
                WHEN 'gestor_academia' THEN 3
                WHEN 'gestor_associacao' THEN 4
                WHEN 'responsavel' THEN 5
                WHEN 'visitante' THEN 6
                ELSE 7
            END
    """)
    roles = cur.fetchall()
    
    # Buscar alunos para vínculo (aluno e responsavel)
    cur.execute(
        """SELECT id, nome, usuario_id FROM alunos WHERE id_academia = %s AND ativo = 1 AND status = 'ativo'
           ORDER BY nome""",
        (academia_id,),
    )
    todos_alunos = cur.fetchall()
    alunos_para_aluno = [a for a in todos_alunos if not a.get("usuario_id")]
    alunos_para_responsavel = todos_alunos
    
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip()
        senha = (request.form.get("senha") or "").strip()
        roles_escolhidas = request.form.getlist("roles")
        academias_escolhidas = []
        
        # Processar academias selecionadas
        for x in request.form.getlist("academias"):
            try:
                aid = int(x)
                if aid == academia_id or any(ac["id"] == aid for ac in academias):
                    academias_escolhidas.append(aid)
            except (ValueError, TypeError):
                pass
        
        # Se não selecionou nenhuma, usar a academia atual
        if not academias_escolhidas:
            academias_escolhidas = [academia_id]
        
        if not nome or not email or not senha or not roles_escolhidas:
            flash("Preencha todos os campos e selecione ao menos uma Role.", "danger")
            cur.close()
            conn.close()
            return render_template(
                "academia/cadastro_usuario.html",
                roles=roles,
                academias=academias,
                academia_id=academia_id,
                academia_fixa=len(academias) == 1,
                academia_nome_cadastro=academias[0]["nome"] if academias else "",
                alunos_para_aluno=alunos_para_aluno,
                alunos_para_responsavel=alunos_para_responsavel,
                back_url=back_url,
            )
        
        # Verificar se email já existe
        cur.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
        if cur.fetchone():
            flash("Já existe um usuário com este e-mail.", "danger")
            cur.close()
            conn.close()
            return render_template(
                "academia/cadastro_usuario.html",
                roles=roles,
                academias=academias,
                academia_id=academia_id,
                academia_fixa=len(academias) == 1,
                academia_nome_cadastro=academias[0]["nome"] if academias else "",
                alunos_para_aluno=alunos_para_aluno,
                alunos_para_responsavel=alunos_para_responsavel,
                back_url=back_url,
            )
        
        try:
            senha_hash = generate_password_hash(senha)
            id_academia_principal = academias_escolhidas[0]
            
            # Buscar id_associacao e id_federacao da academia selecionada
            cur.execute("""
                SELECT ac.id_associacao, ass.id_federacao
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ac.id = %s
            """, (id_academia_principal,))
            acad_info = cur.fetchone()
            id_associacao_usuario = acad_info.get("id_associacao") if acad_info else None
            id_federacao_usuario = acad_info.get("id_federacao") if acad_info else None
            
            # Criar usuário com id_federacao e id_associacao
            cur.execute(
                """INSERT INTO usuarios (nome, email, senha, id_academia, id_associacao, id_federacao) 
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (nome, email, senha_hash, id_academia_principal, id_associacao_usuario, id_federacao_usuario),
            )
            user_id = cur.lastrowid
            
            # Vincular roles
            for role_id in roles_escolhidas:
                cur.execute(
                    "INSERT INTO roles_usuario (usuario_id, role_id) VALUES (%s, %s)",
                    (user_id, role_id),
                )
            
            # Vincular academias
            for aid in academias_escolhidas:
                cur.execute(
                    "INSERT INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)",
                    (user_id, aid),
                )
            
            # Vincular aluno se role aluno está selecionada
            tem_role_aluno = any(
                r.get("chave") == "aluno" and str(r.get("id")) in roles_escolhidas 
                for r in roles
            )
            if tem_role_aluno:
                aluno_id = request.form.get("aluno_id", type=int)
                if aluno_id:
                    cur.execute(
                        "UPDATE alunos SET usuario_id = %s WHERE id = %s AND id_academia = %s",
                        (user_id, aluno_id, academia_id),
                    )
            
            # Vincular responsável aos alunos selecionados
            tem_role_responsavel = any(
                r.get("chave") == "responsavel" and str(r.get("id")) in roles_escolhidas 
                for r in roles
            )
            if tem_role_responsavel:
                aluno_ids_responsavel = [int(x) for x in request.form.getlist("aluno_ids") if str(x).strip().isdigit()]
                for aid in aluno_ids_responsavel:
                    cur.execute(
                        "INSERT IGNORE INTO responsavel_alunos (usuario_id, aluno_id) VALUES (%s, %s)",
                        (user_id, aid),
                    )
            
            # Criar registro de professor se role professor está selecionada
            tem_role_professor = any(
                r.get("chave") == "professor" and str(r.get("id")) in roles_escolhidas 
                for r in roles
            )
            if tem_role_professor:
                cur.execute("SELECT id FROM professores WHERE usuario_id = %s", (user_id,))
                if not cur.fetchone():
                    cur.execute(
                        """
                        INSERT INTO professores (nome, email, telefone, usuario_id, id_academia, ativo)
                        VALUES (%s, %s, NULL, %s, %s, 1)
                        """,
                        (nome, email, user_id, id_academia_principal),
                    )
            
            # Criar registro de visitante se role visitante está selecionada
            tem_role_visitante = any(
                r.get("chave") == "visitante" and str(r.get("id")) in roles_escolhidas 
                for r in roles
            )
            if tem_role_visitante:
                cur.execute("SELECT id FROM visitantes WHERE usuario_id = %s", (user_id,))
                if not cur.fetchone():
                    cur.execute("SELECT aulas_experimentais_permitidas FROM academias WHERE id = %s", (id_academia_principal,))
                    acad_row = cur.fetchone()
                    limite_aulas = acad_row.get("aulas_experimentais_permitidas") if acad_row else None
                    cur.execute(
                        """
                        INSERT INTO visitantes (nome, email, telefone, usuario_id, id_academia, aulas_experimentais_permitidas, ativo)
                        VALUES (%s, %s, NULL, %s, %s, %s, 1)
                        """,
                        (nome, email, user_id, id_academia_principal, limite_aulas),
                    )
            
            conn.commit()
            flash("Usuário cadastrado com sucesso!", "success")
            redirect_url = request.form.get("next") or back_url
            cur.close()
            conn.close()
            return redirect(redirect_url)
            
        except Exception as e:
            conn.rollback()
            current_app.logger.error(f"Erro ao cadastrar usuário: {e}", exc_info=True)
            flash(f"Erro ao cadastrar usuário: {e}", "danger")
            cur.close()
            conn.close()
            return render_template(
                "academia/cadastro_usuario.html",
                roles=roles,
                academias=academias,
                academia_id=academia_id,
                academia_fixa=len(academias) == 1,
                academia_nome_cadastro=academias[0]["nome"] if academias else "",
                alunos_para_aluno=alunos_para_aluno,
                alunos_para_responsavel=alunos_para_responsavel,
                back_url=back_url,
            )
    
    cur.close()
    conn.close()
    
    return render_template(
        "academia/cadastro_usuario.html",
        roles=roles,
        academias=academias,
        academia_id=academia_id,
        academia_fixa=len(academias) == 1,
        academia_nome_cadastro=academias[0]["nome"] if academias else "",
        alunos_para_aluno=alunos_para_aluno,
        alunos_para_responsavel=alunos_para_responsavel,
        back_url=back_url,
    )


@academia_bp.route("/usuarios/api/alunos-para-vinculo/<int:academia_id>")
@login_required
def api_alunos_para_vinculo(academia_id):
    """API para buscar alunos disponíveis para vínculo (aluno e responsavel)."""
    ids = _get_academias_ids()
    if academia_id not in ids:
        return jsonify({"ok": False, "msg": "Sem permissão"}), 403
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT id, nome, usuario_id FROM alunos WHERE id_academia = %s AND ativo = 1 AND status = 'ativo'
               ORDER BY nome""",
            (academia_id,),
        )
        todos_alunos = cur.fetchall()
        disponiveis_aluno = [a for a in todos_alunos if not a.get("usuario_id")]
        cur.close()
        conn.close()
        return jsonify({
            "ok": True,
            "disponiveis_aluno": disponiveis_aluno,
            "alunos": todos_alunos,
        })
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"ok": False, "msg": str(e)}), 500
