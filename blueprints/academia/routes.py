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
# 🔹 Novo Visitante (cadastro manual pela academia)
# ======================================================
@academia_bp.route("/visitantes/novo", methods=["GET", "POST"])
@login_required
def novo_visitante():
    """Cadastro manual de visitante pela academia, com opção de já agendar a aula experimental."""
    from datetime import datetime
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

    cur.execute(
        "SELECT TurmaID AS turma_id, Nome AS turma_nome, DiasHorario FROM turmas WHERE id_academia = %s ORDER BY Nome",
        (academia_id,),
    )
    turmas = cur.fetchall()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip() or None
        telefone = (request.form.get("telefone") or "").strip() or None
        data_nascimento = (request.form.get("data_nascimento") or "").strip() or None
        turma_id = request.form.get("turma_id", type=int)
        data_aula = (request.form.get("data_aula") or "").strip()

        if not nome:
            flash("Informe o nome do visitante.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("academia.novo_visitante", academia_id=academia_id))

        # Se informou turma, precisa de data (e vice-versa)
        agendar = bool(turma_id or data_aula)
        data_aula_obj = None
        if agendar:
            if not turma_id or not data_aula:
                flash("Para agendar a aula experimental, informe turma e data.", "danger")
                cur.close()
                conn.close()
                return redirect(url_for("academia.novo_visitante", academia_id=academia_id))
            try:
                data_aula_obj = datetime.strptime(data_aula, "%Y-%m-%d").date()
            except Exception:
                flash("Data da aula inválida.", "danger")
                cur.close()
                conn.close()
                return redirect(url_for("academia.novo_visitante", academia_id=academia_id))
            if not any(t["turma_id"] == turma_id for t in turmas):
                flash("Turma inválida.", "danger")
                cur.close()
                conn.close()
                return redirect(url_for("academia.novo_visitante", academia_id=academia_id))

        try:
            cur.execute(
                "SELECT aulas_experimentais_permitidas FROM academias WHERE id = %s",
                (academia_id,),
            )
            acad_cfg = cur.fetchone() or {}
            limite_aulas = acad_cfg.get("aulas_experimentais_permitidas")

            cur.execute(
                """
                INSERT INTO visitantes (nome, email, telefone, data_nascimento, usuario_id,
                                        id_academia, aulas_experimentais_permitidas, ativo)
                VALUES (%s, %s, %s, %s, NULL, %s, %s, 1)
                """,
                (nome, email, telefone, data_nascimento or None, academia_id, limite_aulas),
            )
            visitante_id = cur.lastrowid

            if agendar:
                # Cadastrada pela academia já entra aprovada
                cur.execute(
                    """
                    INSERT INTO aulas_experimentais (visitante_id, turma_id, data_aula, presente, aprovado, observacoes, registrado_por)
                    VALUES (%s, %s, %s, 0, 1, %s, %s)
                    """,
                    (visitante_id, turma_id, data_aula, "Cadastrado manualmente pela academia", current_user.id),
                )
                cur.execute(
                    "INSERT IGNORE INTO visitante_turmas (visitante_id, turma_id, data_inscricao) VALUES (%s, %s, %s)",
                    (visitante_id, turma_id, date.today()),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            flash(f"Erro ao cadastrar visitante: {e}", "danger")
            return redirect(url_for("academia.novo_visitante", academia_id=academia_id))

        cur.close()
        conn.close()
        flash(
            f"Visitante '{nome}' cadastrado com sucesso." + (" Aula experimental agendada." if agendar else ""),
            "success",
        )
        return redirect(url_for("academia.detalhes_visitante", visitante_id=visitante_id, academia_id=academia_id))

    cur.close()
    conn.close()
    return render_template(
        "academia/visitantes/novo.html",
        turmas=turmas,
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
        flash(f"Erro ao carregar solicitações de aulas: {e}", "danger")
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
        current_app.logger.error("Erro interno: %s", e, exc_info=True)
        return jsonify({"ok": False, "msg": "Erro interno no servidor. Tente novamente."}), 500


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
        current_app.logger.error("Erro interno: %s", e, exc_info=True)
        return jsonify({"ok": False, "msg": "Erro interno no servidor. Tente novamente."}), 500


# ======================================================
# 🔹 Pagamentos de Diária - Listar e Aprovar
# ======================================================
@academia_bp.route("/visitantes/pagamentos-diaria")
@login_required
def pagamentos_diaria():
    """Lista pagamentos de diária pendentes de confirmação."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin")
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
        cur.execute("""
            SELECT vpd.*, v.nome AS visitante_nome, v.email AS visitante_email,
                   ae.data_aula, t.Nome AS turma_nome
            FROM visitante_pagamentos_diaria vpd
            INNER JOIN visitantes v ON v.id = vpd.visitante_id
            INNER JOIN aulas_experimentais ae ON ae.id = vpd.aula_experimental_id
            INNER JOIN turmas t ON t.TurmaID = ae.turma_id
            WHERE v.id_academia = %s
            ORDER BY vpd.criado_em DESC
        """, (academia_id,))
        pagamentos = cur.fetchall()
    except Exception as e:
        flash(f"Erro ao carregar pagamentos: {e}", "danger")
        pagamentos = []
    finally:
        cur.close()
        conn.close()
    
    return render_template("academia/visitantes/pagamentos_diaria.html",
                         pagamentos=pagamentos, academias=academias, academia_id=academia_id)


@academia_bp.route("/visitantes/pagamentos-diaria/<int:pagamento_id>/confirmar", methods=["POST"])
@login_required
def confirmar_pagamento_diaria(pagamento_id):
    """Confirma pagamento de diária e gera receita."""
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
        # Buscar pagamento
        cur.execute("""
            SELECT vpd.*, v.id_academia, v.nome AS visitante_nome
            FROM visitante_pagamentos_diaria vpd
            INNER JOIN visitantes v ON v.id = vpd.visitante_id
            WHERE vpd.id = %s AND v.id_academia = %s
        """, (pagamento_id, academia_id))
        pagamento = cur.fetchone()
        
        if not pagamento:
            conn.close()
            return jsonify({"ok": False, "msg": "Pagamento não encontrado"}), 404
        
        if pagamento["status"] != "pago":
            conn.close()
            return jsonify({"ok": False, "msg": "Pagamento não está aguardando confirmação"}), 400
        
        # Criar receita
        hoje = date.today().strftime("%Y-%m-%d")
        descricao = f"Diária de visitante - {pagamento['visitante_nome']}"
        valor = float(pagamento["valor"])
        
        cur.execute("""
            INSERT INTO receitas (descricao, valor, data, categoria, id_academia, criado_por)
            VALUES (%s, %s, %s, 'Diária de Visitante', %s, %s)
        """, (descricao, valor, hoje, academia_id, current_user.id))
        receita_id = cur.lastrowid
        
        # Atualizar pagamento e aprovar aula
        cur.execute("""
            UPDATE visitante_pagamentos_diaria 
            SET status = 'confirmado', pagamento_confirmado_em = NOW(), 
                confirmado_por = %s, receita_id = %s
            WHERE id = %s
        """, (current_user.id, receita_id, pagamento_id))
        
        # Aprovar aula experimental
        cur.execute("""
            UPDATE aulas_experimentais 
            SET aprovado = 1 
            WHERE id = %s
        """, (pagamento["aula_experimental_id"],))
        
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "msg": "Pagamento confirmado e receita gerada com sucesso!"})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        current_app.logger.error("Erro interno: %s", e, exc_info=True)
        return jsonify({"ok": False, "msg": "Erro interno no servidor. Tente novamente."}), 500


# ======================================================
# 🔹 Matrículas Realizadas - Listar e Aprovar
# ======================================================
@academia_bp.route("/visitantes/solicitacoes-mensalidade")
@login_required
def solicitacoes_mensalidade():
    """Lista matrículas realizadas pendentes de aprovação."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("admin")
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
        cur.execute("""
            SELECT vsm.*, v.nome AS visitante_nome, v.email AS visitante_email,
                   v.usuario_id, v.id_academia, m.nome AS mensalidade_nome, m.valor AS mensalidade_valor
            FROM visitante_solicitacoes_mensalidade vsm
            INNER JOIN visitantes v ON v.id = vsm.visitante_id
            INNER JOIN mensalidades m ON m.id = vsm.mensalidade_id
            WHERE v.id_academia = %s AND vsm.status = 'pendente'
            ORDER BY vsm.solicitado_em DESC
        """, (academia_id,))
        solicitacoes = cur.fetchall()
    except Exception as e:
        flash(f"Erro ao carregar matrículas: {e}", "danger")
        solicitacoes = []
    finally:
        cur.close()
        conn.close()
    
    return render_template("academia/visitantes/solicitacoes_mensalidade.html",
                         solicitacoes=solicitacoes, academias=academias, academia_id=academia_id)


@academia_bp.route("/visitantes/solicitacoes-mensalidade/<int:solicitacao_id>/aprovar", methods=["POST"])
@login_required
def aprovar_solicitacao_mensalidade(solicitacao_id):
    """Aprova matrícula e promove visitante a aluno."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("admin")
    ):
        return jsonify({"ok": False, "msg": "Acesso negado"}), 403
    
    academia_id, _ = _get_academia_gerenciamento()
    if not academia_id:
        return jsonify({"ok": False, "msg": "Academia não encontrada"}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar solicitação
        cur.execute("""
            SELECT vsm.*, v.*, m.valor AS mensalidade_valor, m.nome AS mensalidade_nome
            FROM visitante_solicitacoes_mensalidade vsm
            INNER JOIN visitantes v ON v.id = vsm.visitante_id
            INNER JOIN mensalidades m ON m.id = vsm.mensalidade_id
            WHERE vsm.id = %s AND v.id_academia = %s AND vsm.status = 'pendente'
        """, (solicitacao_id, academia_id))
        solicitacao = cur.fetchone()
        
        if not solicitacao:
            conn.close()
            return jsonify({"ok": False, "msg": "Solicitação não encontrada"}), 404
        
        # Criar registro de aluno
        from datetime import datetime
        hoje = date.today()
        ano_atual = hoje.year
        
        cur.execute("""
            INSERT INTO alunos (nome, email, telefone, data_nascimento, foto, usuario_id, id_academia, ativo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
        """, (
            solicitacao["nome"],
            solicitacao.get("email"),
            solicitacao.get("telefone"),
            solicitacao.get("data_nascimento"),
            solicitacao.get("foto"),
            solicitacao["usuario_id"],
            academia_id
        ))
        aluno_id = cur.lastrowid
        
        # Vincular mensalidade ao aluno
        cur.execute("""
            INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, valor, status)
            VALUES (%s, %s, %s, 'pendente')
        """, (solicitacao["mensalidade_id"], aluno_id, solicitacao["mensalidade_valor"]))
        
        # Gerar mensalidades até o final do ano
        mes_atual = hoje.month
        for mes in range(mes_atual, 13):  # De mes_atual até dezembro
            data_vencimento = date(ano_atual, mes, 1)
            cur.execute("""
                INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, valor, status, data_vencimento)
                VALUES (%s, %s, %s, 'pendente', %s)
            """, (solicitacao["mensalidade_id"], aluno_id, solicitacao["mensalidade_valor"], data_vencimento))
        
        # Adicionar role "aluno" ao usuário
        cur.execute("SELECT id FROM roles WHERE chave = 'aluno' LIMIT 1")
        role_aluno = cur.fetchone()
        if role_aluno:
            cur.execute("""
                INSERT IGNORE INTO roles_usuario (usuario_id, role_id)
                VALUES (%s, %s)
            """, (solicitacao["usuario_id"], role_aluno["id"]))
        
        # Atualizar solicitação
        cur.execute("""
            UPDATE visitante_solicitacoes_mensalidade 
            SET status = 'aprovado', aprovado_em = NOW(), aprovado_por = %s
            WHERE id = %s
        """, (current_user.id, solicitacao_id))
        
        # Desativar visitante (agora é aluno)
        cur.execute("UPDATE visitantes SET ativo = 0 WHERE id = %s", (solicitacao["visitante_id"],))
        
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "msg": "Visitante promovido a aluno com sucesso! Mensalidades geradas até o final do ano."})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        current_app.logger.error("Erro interno: %s", e, exc_info=True)
        return jsonify({"ok": False, "msg": "Erro interno no servidor. Tente novamente."}), 500


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
def _kpis_mes(cur, academia_id, ano, mes):
    """KPIs de um mês específico (alunos novos/baixas, receitas/despesas, mensalidades previsto/recebido)."""
    import calendar
    ini = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    k = {"ano": ano, "mes": mes}

    cur.execute(
        "SELECT COUNT(*) c FROM alunos WHERE id_academia=%s AND data_matricula BETWEEN %s AND %s",
        (academia_id, ini, fim),
    )
    k["novos"] = cur.fetchone()["c"] or 0
    cur.execute(
        "SELECT COUNT(*) c FROM alunos WHERE id_academia=%s AND data_inativacao BETWEEN %s AND %s",
        (academia_id, ini, fim),
    )
    k["baixas"] = cur.fetchone()["c"] or 0

    cur.execute(
        "SELECT COALESCE(SUM(valor),0) v FROM receitas WHERE id_academia=%s AND data BETWEEN %s AND %s",
        (academia_id, ini, fim),
    )
    k["receitas"] = float(cur.fetchone()["v"] or 0)
    cur.execute(
        "SELECT COALESCE(SUM(valor),0) v FROM despesas WHERE id_academia=%s AND data BETWEEN %s AND %s",
        (academia_id, ini, fim),
    )
    k["despesas"] = float(cur.fetchone()["v"] or 0)
    k["saldo"] = k["receitas"] - k["despesas"]

    cur.execute(
        """SELECT COALESCE(SUM(ma.valor),0) v FROM mensalidade_aluno ma
           JOIN alunos a ON a.id = ma.aluno_id
           WHERE a.id_academia=%s AND ma.status <> 'cancelado'
             AND ma.data_vencimento BETWEEN %s AND %s""",
        (academia_id, ini, fim),
    )
    k["mens_previsto"] = float(cur.fetchone()["v"] or 0)
    cur.execute(
        """SELECT COALESCE(SUM(COALESCE(ma.valor_pago, ma.valor)),0) v FROM mensalidade_aluno ma
           JOIN alunos a ON a.id = ma.aluno_id
           WHERE a.id_academia=%s AND ma.status = 'pago'
             AND ma.data_pagamento BETWEEN %s AND %s""",
        (academia_id, ini, fim),
    )
    k["mens_recebido"] = float(cur.fetchone()["v"] or 0)
    return k


def _get_academia_dashboard(academia_id, ano, mes):
    """Monta todos os KPIs do dashboard do modo academia para o mês/ano informados."""
    d = {"ano": ano, "mes": mes}
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Mês atual e mês anterior (para comparativo)
        atual = _kpis_mes(cur, academia_id, ano, mes)
        pmes, pano = (12, ano - 1) if mes == 1 else (mes - 1, ano)
        anterior = _kpis_mes(cur, academia_id, pano, pmes)
        d["atual"] = atual
        d["anterior"] = anterior

        # Snapshot de alunos por status (atual)
        cur.execute(
            "SELECT status, COUNT(*) c FROM alunos WHERE id_academia=%s GROUP BY status",
            (academia_id,),
        )
        por_status = {(r["status"] or "ativo"): r["c"] for r in cur.fetchall()}
        ativos = por_status.get("ativo", 0)
        d["por_status"] = por_status
        d["ativos"] = ativos
        d["inativos"] = por_status.get("inativo", 0)
        d["suspensos"] = por_status.get("suspenso", 0)
        d["formados"] = por_status.get("formado", 0)
        d["total_alunos"] = sum(por_status.values())

        # Inadimplência (snapshot atual): atrasado OU pendente vencido
        cond_atraso = "(ma.status='atrasado' OR (ma.status='pendente' AND ma.data_vencimento < CURDATE()))"
        cur.execute(
            f"""SELECT COALESCE(SUM(ma.valor),0) v, COUNT(DISTINCT ma.aluno_id) a
                FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                WHERE a.id_academia=%s AND {cond_atraso}""",
            (academia_id,),
        )
        row = cur.fetchone()
        d["atrasado_valor"] = float(row["v"] or 0)
        d["inadimplentes_qtd"] = row["a"] or 0
        d["inadimplencia_pct"] = round((d["inadimplentes_qtd"] / ativos * 100), 1) if ativos else 0.0
        d["ticket_medio"] = round((atual["mens_recebido"] / ativos), 2) if ativos else 0.0
        d["saldo_alunos"] = atual["novos"] - atual["baixas"]
        base_churn = ativos + atual["baixas"]
        d["churn_pct"] = round((atual["baixas"] / base_churn * 100), 1) if base_churn else 0.0

        # Lista de inadimplentes (top 10 por valor)
        cur.execute(
            f"""SELECT a.id, a.nome, COUNT(*) qtd, COALESCE(SUM(ma.valor),0) total,
                       MIN(ma.data_vencimento) venc
                FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                WHERE a.id_academia=%s AND {cond_atraso}
                GROUP BY a.id, a.nome ORDER BY total DESC LIMIT 10""",
            (academia_id,),
        )
        d["inadimplentes"] = cur.fetchall()

        # ---- Financeiro avançado ----
        import calendar as _cal
        ini_mes = date(ano, mes, 1)
        fim_mes = date(ano, mes, _cal.monthrange(ano, mes)[1])
        ini_ano = date(ano, 1, 1)

        # MRR (receita recorrente): soma da mensalidade mais recente (não cancelada) de cada aluno ativo
        cur.execute(
            """SELECT COALESCE(SUM(t.valor),0) v FROM (
                 SELECT ma.valor
                 FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                 WHERE a.id_academia=%s AND a.status='ativo' AND ma.status<>'cancelado'
                   AND ma.id = (SELECT ma2.id FROM mensalidade_aluno ma2
                                WHERE ma2.aluno_id = ma.aluno_id AND ma2.status<>'cancelado'
                                ORDER BY ma2.data_vencimento DESC, ma2.id DESC LIMIT 1)
               ) t""",
            (academia_id,),
        )
        d["mrr"] = float(cur.fetchone()["v"] or 0)

        # Mensalidades vencendo nos próximos 7 dias (ainda pendentes)
        cur.execute(
            """SELECT COALESCE(SUM(ma.valor),0) v, COUNT(*) c
               FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
               WHERE a.id_academia=%s AND ma.status='pendente'
                 AND ma.data_vencimento BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)""",
            (academia_id,),
        )
        row = cur.fetchone()
        d["venc7_valor"] = float(row["v"] or 0)
        d["venc7_qtd"] = row["c"] or 0

        # Acumulado do ano (YTD): de 1º de janeiro até o fim do mês selecionado
        cur.execute(
            "SELECT COALESCE(SUM(valor),0) v FROM receitas WHERE id_academia=%s AND data BETWEEN %s AND %s",
            (academia_id, ini_ano, fim_mes),
        )
        d["receitas_ano"] = float(cur.fetchone()["v"] or 0)
        cur.execute(
            "SELECT COALESCE(SUM(valor),0) v FROM despesas WHERE id_academia=%s AND data BETWEEN %s AND %s",
            (academia_id, ini_ano, fim_mes),
        )
        d["despesas_ano"] = float(cur.fetchone()["v"] or 0)
        d["saldo_ano"] = d["receitas_ano"] - d["despesas_ano"]

        # Receita por forma de pagamento (mensalidades pagas no mês selecionado)
        cur.execute(
            """SELECT COALESCE(fp.nome,'Sem forma') nome,
                      COALESCE(SUM(COALESCE(ma.valor_pago, ma.valor)),0) total
               FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
               LEFT JOIN formas_pagamento fp ON fp.id = ma.id_forma_pagamento
               WHERE a.id_academia=%s AND ma.status='pago' AND ma.data_pagamento BETWEEN %s AND %s
               GROUP BY fp.nome ORDER BY total DESC""",
            (academia_id, ini_mes, fim_mes),
        )
        d["por_forma"] = [{"nome": r["nome"], "total": float(r["total"] or 0)} for r in cur.fetchall()]

        # Série dos últimos 6 meses (para gráfico)
        meses_pt = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
        serie = []
        sm, sy = mes, ano
        for _ in range(6):
            km = _kpis_mes(cur, academia_id, sy, sm)
            serie.append({
                "label": f"{meses_pt[sm-1]}/{str(sy)[2:]}",
                "receitas": km["receitas"],
                "despesas": km["despesas"],
                "novos": km["novos"],
                "baixas": km["baixas"],
            })
            sm, sy = (12, sy - 1) if sm == 1 else (sm - 1, sy)
        serie.reverse()
        d["serie"] = serie
    finally:
        cur.close()
        conn.close()
    return d


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

    hoje = date.today()
    mes = request.args.get("mes", type=int) or hoje.month
    ano = request.args.get("ano", type=int) or hoje.year
    if not (1 <= mes <= 12):
        mes = hoje.month
    if ano < 2000 or ano > 2100:
        ano = hoje.year

    stats = _get_academia_stats(academia_id)
    dash_data = _get_academia_dashboard(academia_id, ano, mes)
    return render_template(
        "painel/academia_dash.html",
        stats=stats,
        academias=academias,
        academia_id=academia_id,
        dash=dash_data,
        mes=mes,
        ano=ano,
    )


def _push_aniv_academia_hoje(anivs_hoje: list, hoje) -> None:
    if not anivs_hoje:
        return
    chave = f"push_aniv_{hoje.isoformat()}"
    if session.get(chave):
        return
    session[chave] = True
    try:
        from utils.push_notifications import enviar_push_usuario
        nomes = ", ".join(a["nome"].split()[0] for a in anivs_hoje[:3])
        sufixo = f" +{len(anivs_hoje)-3}" if len(anivs_hoje) > 3 else ""
        enviar_push_usuario(
            current_user.id,
            title="🎂 Aniversariantes hoje!",
            body=f"{nomes}{sufixo} fazem aniversário hoje. Envie uma mensagem!",
            url="/academia/",
            tag="aniversario",
            require_interaction=True,
        )
    except Exception:
        pass


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

    # Zempo: quantos alunos já têm todos os campos que a CBJ exige e ainda não
    # foram solicitados — é o número acionável do card.
    zempo_prontos = 0
    try:
        from utils import zempo_mapper
        cur.execute(
            """SELECT a.*, g.faixa AS faixa
               FROM alunos a
               LEFT JOIN graduacao g ON g.id = a.graduacao_id
               WHERE a.id_academia = %s AND a.ativo = 1
                 AND (a.zempo IS NULL OR a.zempo = '')
                 AND NOT EXISTS (SELECT 1 FROM zempo_solicitacoes s
                                 WHERE s.aluno_id = a.id
                                   AND s.status IN ('pendente', 'aprovada'))""",
            (academia_id,))
        zempo_prontos = sum(1 for aluno in cur.fetchall()
                            if not zempo_mapper.validar_aluno(aluno))
    except Exception:
        pass

    cur.close()
    conn.close()

    from utils.aniversariantes import aniversariantes_do_mes
    from datetime import date
    hoje = date.today()
    anivs = aniversariantes_do_mes(current_user.id, "academia", mes=hoje.month,
                                   academia_id=academia_id)
    anivs_hoje = [a for a in anivs if a["data_nascimento"] and
                  a["data_nascimento"].day == hoje.day]
    _push_aniv_academia_hoje(anivs_hoje, hoje)
    return render_template(
        "painel/painel_academia.html",
        usuario=current_user,
        academia=academia,
        academias=academias,
        academia_id=academia_id,
        zempo_prontos=zempo_prontos,
        aniversariantes=anivs,
        aniversariantes_hoje=anivs_hoje,
        hoje_dia=hoje.day,
        hoje_mes=hoje.month,
        hoje_ano=hoje.year,
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
    status_filtro = (request.args.get("status") or "ativos").lower()
    if status_filtro not in ("ativos", "inativos", "todos"):
        status_filtro = "ativos"
    # Quando há busca na URL mas não há parâmetro 'page', resetar para página 1
    # Isso garante que a busca seja aplicada em toda a base antes da paginação
    tem_busca = bool(busca)
    tem_page_param = "page" in request.args

    if tem_busca and not tem_page_param:
        # Nova busca: resetar para página 1
        page = 1
    else:
        page = int(request.args.get("page", 1))

    por_pagina = 12
    offset = (page - 1) * por_pagina

    # SQL parcial de status: aplicado em todas as queries
    if status_filtro == "ativos":
        sql_status = "AND COALESCE(u.ativo, 1) = 1"
    elif status_filtro == "inativos":
        sql_status = "AND COALESCE(u.ativo, 1) = 0"
    else:
        sql_status = ""
    
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
                    {sql_status}
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                """, params_count)
            else:
                cur.execute(f"""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE {filtro_academia}
                    {sql_status}
                """, tuple(params_base))
            
            result_total = cur.fetchone()
            total = result_total["total"] if result_total else 0
            total_paginas = ceil(total / por_pagina) if total > 0 else 1
            
            # Buscar usuários com informações das academias vinculadas
            if busca:
                params_query = tuple(params_base) + (f"%{busca}%", f"%{busca}%", por_pagina, offset)
                cur.execute(f"""
                    SELECT DISTINCT u.id, u.nome, u.email, u.cpf, u.foto, u.criado_em,
                           COALESCE(u.ativo, 1) AS ativo,
                           GROUP_CONCAT(DISTINCT ac.nome ORDER BY ac.nome SEPARATOR ', ') AS academias_vinculadas
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    INNER JOIN academias ac ON ac.id = ua.academia_id
                    WHERE {filtro_academia}
                    {sql_status}
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                    GROUP BY u.id, u.nome, u.email, u.cpf, u.foto, u.criado_em, u.ativo
                    ORDER BY u.nome
                    LIMIT %s OFFSET %s
                """, params_query)
            else:
                params_query = tuple(params_base) + (por_pagina, offset)
                cur.execute(f"""
                    SELECT DISTINCT u.id, u.nome, u.email, u.cpf, u.foto, u.criado_em,
                           COALESCE(u.ativo, 1) AS ativo,
                           GROUP_CONCAT(DISTINCT ac.nome ORDER BY ac.nome SEPARATOR ', ') AS academias_vinculadas
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    INNER JOIN academias ac ON ac.id = ua.academia_id
                    WHERE {filtro_academia}
                    {sql_status}
                    GROUP BY u.id, u.nome, u.email, u.cpf, u.foto, u.criado_em, u.ativo
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
                cur.execute(f"""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                    {sql_status}
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                """, (academia_id, f"%{busca}%", f"%{busca}%"))
            else:
                cur.execute(f"""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                    {sql_status}
                """, (academia_id,))
            
            result_total = cur.fetchone()
            total = result_total["total"] if result_total else 0
            total_paginas = ceil(total / por_pagina) if total > 0 else 1
            
            # Buscar usuários vinculados à academia
            if busca:
                cur.execute(f"""
                    SELECT DISTINCT u.id, u.nome, u.email, u.cpf, u.foto, u.criado_em,
                           COALESCE(u.ativo, 1) AS ativo,
                           NULL AS academias_vinculadas
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                    {sql_status}
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                    ORDER BY u.nome
                    LIMIT %s OFFSET %s
                """, (academia_id, f"%{busca}%", f"%{busca}%", por_pagina, offset))
            else:
                cur.execute(f"""
                    SELECT DISTINCT u.id, u.nome, u.email, u.cpf, u.foto, u.criado_em,
                           COALESCE(u.ativo, 1) AS ativo,
                           NULL AS academias_vinculadas
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                    {sql_status}
                    ORDER BY u.nome
                    LIMIT %s OFFSET %s
                """, (academia_id, por_pagina, offset))

            usuarios = cur.fetchall()

        # Anexar roles de cada usuário (uma única consulta)
        if usuarios:
            ids_usuarios = [u["id"] for u in usuarios]
            ph = ",".join(["%s"] * len(ids_usuarios))
            cur.execute(
                f"""
                SELECT ru.usuario_id,
                       r.nome AS role_nome,
                       COALESCE(r.chave, LOWER(REPLACE(r.nome,' ','_'))) AS role_chave
                FROM roles_usuario ru
                JOIN roles r ON r.id = ru.role_id
                WHERE ru.usuario_id IN ({ph})
                ORDER BY r.nome
                """,
                tuple(ids_usuarios),
            )
            roles_por_usuario = {}
            for row in cur.fetchall():
                roles_por_usuario.setdefault(row["usuario_id"], []).append({
                    "nome": row["role_nome"],
                    "chave": (row["role_chave"] or "").lower(),
                })
            for u in usuarios:
                u["roles"] = roles_por_usuario.get(u["id"], [])

    except Exception as e:
        flash(f"Erro ao carregar usuários: {e}", "danger")
        usuarios = []
        total = 0
        total_paginas = 1
        academia_nome = "Academia"
        associacao_nome = None
        academias = []
        academia_id = None
        modo_associacao = False
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
        status_filtro=status_filtro,
        pagina_atual=page,
        total_paginas=total_paginas,
        total_usuarios=total,
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
            secao = request.form.get("secao", "visitantes")

            if secao in ("asaas", "online") and (request.form.get("limpar_gateway") or "").strip():
                # Limpar TODAS as credenciais de um gateway (sem deixar resíduo)
                limpar = (request.form.get("limpar_gateway") or "").strip().lower()
                _cols = {
                    "asaas": ["asaas_api_key=NULL", "asaas_webhook_token=NULL", "asaas_habilitado=0", "asaas_ambiente='sandbox'"],
                    "mercadopago": ["mercadopago_access_token=NULL"],
                    "infinitepay": ["infinitepay_handle=NULL"],
                    "cora": ["cora_client_id=NULL", "cora_ambiente=NULL", "cora_certificate=NULL",
                             "cora_private_key=NULL", "cora_client_id_prod=NULL",
                             "cora_certificate_prod=NULL", "cora_private_key_prod=NULL"],
                    "efi": ["efi_client_id=NULL", "efi_client_secret=NULL", "efi_certificate=NULL", "efi_pix_key=NULL", "efi_ambiente=NULL"],
                    "sumup": ["sumup_api_key=NULL", "sumup_merchant_code=NULL", "sumup_habilitado=0", "sumup_ambiente='producao'"],
                }
                _labels = {"asaas": "Asaas", "mercadopago": "Mercado Pago", "infinitepay": "InfinitePay", "cora": "Cora", "efi": "EFÍ", "sumup": "SumUp"}
                if limpar in _cols:
                    sets = list(_cols[limpar])
                    # Se for o gateway ativo, desativa a cobrança online
                    cur.execute("SELECT gateway_pagamento FROM academias WHERE id=%s", (academia_id,))
                    _row = cur.fetchone() or {}
                    if (_row.get("gateway_pagamento") or "").strip().lower() == limpar:
                        sets.append("gateway_pagamento=''")
                    cur.execute(f"UPDATE academias SET {', '.join(sets)} WHERE id=%s", (academia_id,))
                    conn.commit()
                    flash(f"Dados do {_labels[limpar]} foram limpos.", "success")
                else:
                    flash("Gateway inválido para limpeza.", "danger")

            elif secao in ("asaas", "online"):
                # Cobrança online — a academia escolhe UM gateway e informa as credenciais.
                gateway = (request.form.get("gateway_pagamento") or "").strip().lower()
                if gateway not in ("", "asaas", "mercadopago", "infinitepay", "cora", "efi", "sumup"):
                    gateway = ""

                ambiente = (request.form.get("asaas_ambiente") or "sandbox").strip().lower()
                if ambiente not in ("sandbox", "production"):
                    ambiente = "sandbox"
                webhook_token = (request.form.get("asaas_webhook_token") or "").strip() or None
                infinitepay_handle = (request.form.get("infinitepay_handle") or "").strip() or None
                asaas_habilitado = 1 if gateway == "asaas" else 0

                # Cora — credenciais separadas por ambiente (o Cora emite um trio
                # para stage e outro para produção; um não vale no outro).
                cora_client_id = (request.form.get("cora_client_id") or "").strip() or None
                cora_client_id_prod = (request.form.get("cora_client_id_prod") or "").strip() or None
                cora_ambiente = (request.form.get("cora_ambiente") or "stage").strip().lower()
                if cora_ambiente not in ("stage", "production"):
                    cora_ambiente = "stage"

                # EFÍ (Gerencianet)
                efi_client_id = (request.form.get("efi_client_id") or "").strip() or None
                efi_pix_key = (request.form.get("efi_pix_key") or "").strip() or None
                efi_ambiente = (request.form.get("efi_ambiente") or "homologacao").strip().lower()
                if efi_ambiente not in ("homologacao", "producao"):
                    efi_ambiente = "homologacao"

                # SumUp
                sumup_merchant_code = (request.form.get("sumup_merchant_code") or "").strip() or None
                sumup_ambiente = (request.form.get("sumup_ambiente") or "producao").strip().lower()
                if sumup_ambiente not in ("producao", "sandbox"):
                    sumup_ambiente = "producao"
                sumup_habilitado = 1 if gateway == "sumup" else 0
                nova_chave_sumup = (request.form.get("sumup_api_key") or "").strip()

                # Campos sensíveis (chave/token/certificado) só são sobrescritos se um novo valor for digitado.
                nova_chave_asaas = (request.form.get("asaas_api_key") or "").strip()
                novo_token_mp = (request.form.get("mercadopago_access_token") or "").strip()
                # O Cora entrega certificado e chave num arquivo só. Se o conteúdo
                # colado num dos campos trouxer os dois blocos, usamos as duas metades
                # dele — assim o par sai sempre da mesma geração, mesmo que o outro
                # campo tenha ficado com o texto de uma geração antiga.
                def _cora_par_do_form(campo_cert, campo_key):
                    from utils.cora import separar_pem
                    cert_c, key_c = separar_pem(request.form.get(campo_cert))
                    cert_k, key_k = separar_pem(request.form.get(campo_key))
                    return (cert_c or cert_k or ""), (key_c or key_k or "")

                novo_cora_cert, nova_cora_key = _cora_par_do_form("cora_certificate", "cora_private_key")
                novo_cora_cert_prod, nova_cora_key_prod = _cora_par_do_form(
                    "cora_certificate_prod", "cora_private_key_prod")
                novo_efi_secret = (request.form.get("efi_client_secret") or "").strip()
                novo_efi_cert = (request.form.get("efi_certificate") or "").strip()

                # Cora só pode ser ATIVADO com o trio completo DO AMBIENTE escolhido
                # (Client ID + certificado + chave) — o trio do outro ambiente não serve.
                cora_incompleto = False
                if gateway == "cora":
                    cur.execute(
                        """SELECT cora_certificate, cora_private_key,
                                  cora_certificate_prod, cora_private_key_prod
                           FROM academias WHERE id=%s""",
                        (academia_id,),
                    )
                    _atual = cur.fetchone() or {}
                    if cora_ambiente == "production":
                        cert_ok = bool(novo_cora_cert_prod) or bool(_atual.get("cora_certificate_prod"))
                        key_ok = bool(nova_cora_key_prod) or bool(_atual.get("cora_private_key_prod"))
                        client_ok = bool(cora_client_id_prod)
                    else:
                        cert_ok = bool(novo_cora_cert) or bool(_atual.get("cora_certificate"))
                        key_ok = bool(nova_cora_key) or bool(_atual.get("cora_private_key"))
                        client_ok = bool(cora_client_id)
                    if not (client_ok and cert_ok and key_ok):
                        faltando = []
                        if not client_ok:
                            faltando.append("Client ID")
                        if not cert_ok:
                            faltando.append("Certificado")
                        if not key_ok:
                            faltando.append("Chave privada")
                        _amb_label = "Produção" if cora_ambiente == "production" else "Stage"
                        flash(
                            f"Cora não foi ativado: preencha, no ambiente {_amb_label}, "
                            + ", ".join(faltando)
                            + ". As credenciais informadas foram salvas — complete e salve novamente para ativar.",
                            "warning",
                        )
                        gateway = ""  # não ativa enquanto incompleto
                        cora_incompleto = True

                cur.execute(
                    """UPDATE academias
                       SET gateway_pagamento=%s, asaas_habilitado=%s, asaas_ambiente=%s,
                           asaas_webhook_token=%s, infinitepay_handle=%s,
                           cora_client_id=%s, cora_client_id_prod=%s, cora_ambiente=%s,
                           efi_client_id=%s, efi_pix_key=%s, efi_ambiente=%s,
                           sumup_merchant_code=%s, sumup_ambiente=%s, sumup_habilitado=%s
                       WHERE id=%s""",
                    (gateway, asaas_habilitado, ambiente, webhook_token, infinitepay_handle,
                     cora_client_id, cora_client_id_prod, cora_ambiente,
                     efi_client_id, efi_pix_key, efi_ambiente,
                     sumup_merchant_code, sumup_ambiente, sumup_habilitado, academia_id),
                )
                if nova_chave_sumup:
                    # Digitar a chave manual coloca a academia no modo 'key' (sai do OAuth).
                    cur.execute("UPDATE academias SET sumup_api_key=%s, sumup_conexao='key' WHERE id=%s",
                                (nova_chave_sumup, academia_id))
                if nova_chave_asaas:
                    cur.execute("UPDATE academias SET asaas_api_key=%s WHERE id=%s", (nova_chave_asaas, academia_id))
                if novo_token_mp:
                    cur.execute("UPDATE academias SET mercadopago_access_token=%s WHERE id=%s", (novo_token_mp, academia_id))
                if novo_cora_cert:
                    cur.execute("UPDATE academias SET cora_certificate=%s WHERE id=%s", (novo_cora_cert, academia_id))
                if nova_cora_key:
                    cur.execute("UPDATE academias SET cora_private_key=%s WHERE id=%s", (nova_cora_key, academia_id))
                if novo_cora_cert_prod:
                    cur.execute("UPDATE academias SET cora_certificate_prod=%s WHERE id=%s",
                                (novo_cora_cert_prod, academia_id))
                if nova_cora_key_prod:
                    cur.execute("UPDATE academias SET cora_private_key_prod=%s WHERE id=%s",
                                (nova_cora_key_prod, academia_id))
                if novo_efi_secret:
                    cur.execute("UPDATE academias SET efi_client_secret=%s WHERE id=%s", (novo_efi_secret, academia_id))
                if novo_efi_cert:
                    cur.execute("UPDATE academias SET efi_certificate=%s WHERE id=%s", (novo_efi_cert, academia_id))
                conn.commit()

                # Certificado e chave precisam ser do MESMO par — como cada um é
                # colado num campo, é fácil misturar geração (ou ambiente), e aí o
                # erro só apareceria como SSLError no meio de uma cobrança.
                if any([cora_client_id, cora_client_id_prod, novo_cora_cert, nova_cora_key,
                        novo_cora_cert_prod, nova_cora_key_prod]):
                    cur.execute(
                        """SELECT cora_certificate, cora_private_key,
                                  cora_certificate_prod, cora_private_key_prod
                           FROM academias WHERE id=%s""",
                        (academia_id,),
                    )
                    _cred = cur.fetchone() or {}
                    if cora_ambiente == "production":
                        _cert, _key = _cred.get("cora_certificate_prod"), _cred.get("cora_private_key_prod")
                    else:
                        _cert, _key = _cred.get("cora_certificate"), _cred.get("cora_private_key")
                    from utils.cora import validar_par
                    _problema = validar_par(_cert, _key)
                    if _problema:
                        _amb_label = "Produção" if cora_ambiente == "production" else "Stage"
                        flash(f"Cora ({_amb_label}): {_problema}", "danger")

                if not cora_incompleto:
                    flash("Configuração de cobrança online salva com sucesso!", "success")
            else:
                aulas_permitidas = request.form.get("aulas_experimentais_permitidas", "").strip()
                if aulas_permitidas == "":
                    aulas_permitidas = None
                elif aulas_permitidas.isdigit():
                    aulas_permitidas = int(aulas_permitidas)
                else:
                    aulas_permitidas = None

                valor_diaria = request.form.get("valor_diaria_visitante", "").strip()
                if valor_diaria == "":
                    valor_diaria = None
                else:
                    try:
                        valor_diaria = float(valor_diaria)
                        if valor_diaria < 0:
                            valor_diaria = None
                    except ValueError:
                        valor_diaria = None

                cur.execute("""
                    UPDATE academias
                    SET aulas_experimentais_permitidas = %s, valor_diaria_visitante = %s
                    WHERE id = %s
                """, (aulas_permitidas, valor_diaria, academia_id))
                # Propaga o novo limite para os visitantes da academia (mantém em sincronia)
                cur.execute(
                    "UPDATE visitantes SET aulas_experimentais_permitidas = %s WHERE id_academia = %s",
                    (aulas_permitidas, academia_id),
                )
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
    
    asaas_chave_definida = bool((academia or {}).get("asaas_api_key"))
    mp_token_definido = bool((academia or {}).get("mercadopago_access_token"))
    cora_cert_definido = bool((academia or {}).get("cora_certificate"))
    cora_key_definida = bool((academia or {}).get("cora_private_key"))
    cora_cert_prod_definido = bool((academia or {}).get("cora_certificate_prod"))
    cora_key_prod_definida = bool((academia or {}).get("cora_private_key_prod"))
    efi_secret_definido = bool((academia or {}).get("efi_client_secret"))
    efi_cert_definido = bool((academia or {}).get("efi_certificate"))
    sumup_chave_definida = bool((academia or {}).get("sumup_api_key"))
    sumup_conectado = ((academia or {}).get("sumup_conexao") or "key") == "oauth" \
        and bool((academia or {}).get("sumup_oauth_refresh_token"))
    import os as _os
    sumup_oauth_app_ok = bool(_os.environ.get("SUMUP_OAUTH_CLIENT_ID", "").strip()
                              and _os.environ.get("SUMUP_OAUTH_CLIENT_SECRET", "").strip())
    return render_template(
        "painel/configuracoes_academia.html",
        academia=academia,
        academias=academias,
        academia_id=academia_id,
        asaas_chave_definida=asaas_chave_definida,
        mp_token_definido=mp_token_definido,
        cora_cert_definido=cora_cert_definido,
        cora_key_definida=cora_key_definida,
        cora_cert_prod_definido=cora_cert_prod_definido,
        cora_key_prod_definida=cora_key_prod_definida,
        efi_secret_definido=efi_secret_definido,
        efi_cert_definido=efi_cert_definido,
        sumup_chave_definida=sumup_chave_definida,
        sumup_conectado=sumup_conectado,
        sumup_oauth_app_ok=sumup_oauth_app_ok,
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
        from blueprints.auth.routes import _so_digitos, _valida_cpf
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip()
        cpf = _so_digitos(request.form.get("cpf") or "")
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

        def _render_form_back(msg, cat="danger"):
            flash(msg, cat)
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

        if not nome or not email or not cpf or not senha or not roles_escolhidas:
            return _render_form_back("Preencha todos os campos (incluindo CPF) e selecione ao menos uma Role.")

        if not _valida_cpf(cpf):
            return _render_form_back("CPF inválido. Verifique e tente novamente.")

        # Verificar se email já existe
        cur.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
        if cur.fetchone():
            return _render_form_back("Já existe um usuário com este e-mail.")

        # Verificar se CPF já existe
        cur.execute("SELECT id FROM usuarios WHERE cpf = %s", (cpf,))
        if cur.fetchone():
            return _render_form_back("Já existe um usuário com este CPF.")

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

            # Criar usuário com id_federacao, id_associacao e CPF
            cur.execute(
                """INSERT INTO usuarios (nome, email, cpf, senha, id_academia, id_associacao, id_federacao)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (nome, email, cpf, senha_hash, id_academia_principal, id_associacao_usuario, id_federacao_usuario),
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
            aluno_vinculado_id = None
            if tem_role_aluno:
                aluno_id = request.form.get("aluno_id", type=int)
                if aluno_id:
                    cur.execute(
                        "UPDATE alunos SET usuario_id = %s, cpf = COALESCE(NULLIF(cpf,''), %s) WHERE id = %s AND id_academia = %s",
                        (user_id, cpf, aluno_id, academia_id),
                    )
                    aluno_vinculado_id = aluno_id
                else:
                    # Auto-vincular pelo CPF se houver aluno na academia com mesmo CPF.
                    cur.execute(
                        "SELECT id FROM alunos WHERE id_academia = %s "
                        "AND REGEXP_REPLACE(COALESCE(cpf,''), '[^0-9]', '') = %s "
                        "AND (usuario_id IS NULL OR usuario_id = 0) LIMIT 1",
                        (academia_id, cpf),
                    )
                    candidato = cur.fetchone()
                    if candidato:
                        cur.execute(
                            "UPDATE alunos SET usuario_id = %s WHERE id = %s",
                            (user_id, candidato["id"]),
                        )
                        aluno_vinculado_id = candidato["id"]
                # Se não vinculou a nenhum aluno existente, CRIA o registro de aluno
                # (senão o usuário fica com papel "Aluno" mas não aparece na lista de alunos).
                if aluno_vinculado_id is None:
                    cur.execute(
                        """INSERT INTO alunos (nome, email, telefone, cpf, usuario_id, id_academia,
                                               id_associacao, id_federacao, status, ativo, data_matricula)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ativo',1,CURDATE())""",
                        (nome, email, (request.form.get("telefone") or None), cpf, user_id,
                         id_academia_principal, id_associacao_usuario, id_federacao_usuario),
                    )
                    aluno_vinculado_id = cur.lastrowid

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


# =====================================================================
# 📱 WHATSAPP (Baileys) — conexão por academia + automações
# =====================================================================
def _wpp_papel_ok():
    return (
        current_user.has_role("gestor_academia")
        or current_user.has_role("admin")
        or current_user.has_role("gestor_federacao")
        or current_user.has_role("gestor_associacao")
    )


@academia_bp.route("/whatsapp")
@login_required
def whatsapp_config():
    if not _wpp_papel_ok():
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
    cur.execute(
        "SELECT nome, whatsapp_numero, whatsapp_lembrete_mensalidade, whatsapp_avisos, "
        "COALESCE(whatsapp_aniversario, 0) AS whatsapp_aniversario "
        "FROM academias WHERE id = %s",
        (academia_id,),
    )
    acad = cur.fetchone() or {}
    cur.close(); conn.close()

    from utils import whatsapp as wpp
    st = wpp.status(academia_id)
    return render_template(
        "academia/whatsapp.html",
        academia_id=academia_id, academias=academias, acad=acad,
        wpp_status=st.get("status", "offline"), wpp_numero=st.get("number"),
        servico_online=wpp.disponivel(),
    )


@academia_bp.route("/whatsapp/conectar", methods=["POST"])
@login_required
def whatsapp_conectar():
    if not _wpp_papel_ok():
        return jsonify({"erro": "negado"}), 403
    academia_id, _ = _get_academia_gerenciamento()
    from utils import whatsapp as wpp
    return jsonify(wpp.conectar(academia_id))


@academia_bp.route("/whatsapp/qr")
@login_required
def whatsapp_qr():
    if not _wpp_papel_ok():
        return jsonify({"erro": "negado"}), 403
    academia_id, _ = _get_academia_gerenciamento()
    from utils import whatsapp as wpp
    info = wpp.qrcode(academia_id)
    # ao conectar, guarda o número para exibição
    if info.get("status") == "open" and info.get("number"):
        try:
            conn = get_db_connection(); cur = conn.cursor()
            cur.execute("UPDATE academias SET whatsapp_numero=%s WHERE id=%s", (info["number"], academia_id))
            conn.commit(); cur.close(); conn.close()
        except Exception:
            pass
    return jsonify(info)


@academia_bp.route("/whatsapp/desconectar", methods=["POST"])
@login_required
def whatsapp_desconectar():
    if not _wpp_papel_ok():
        return jsonify({"erro": "negado"}), 403
    academia_id, _ = _get_academia_gerenciamento()
    from utils import whatsapp as wpp
    r = wpp.logout(academia_id)
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE academias SET whatsapp_numero=NULL WHERE id=%s", (academia_id,))
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass
    return jsonify(r)


@academia_bp.route("/whatsapp/configurar", methods=["POST"])
@login_required
def whatsapp_configurar():
    if not _wpp_papel_ok():
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    academia_id, _ = _get_academia_gerenciamento()
    lembrete = 1 if request.form.get("whatsapp_lembrete_mensalidade") == "1" else 0
    avisos = 1 if request.form.get("whatsapp_avisos") == "1" else 0
    aniversario = 1 if request.form.get("whatsapp_aniversario") == "1" else 0
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute(
        "UPDATE academias SET whatsapp_lembrete_mensalidade=%s, whatsapp_avisos=%s, "
        "whatsapp_aniversario=%s WHERE id=%s",
        (lembrete, avisos, aniversario, academia_id),
    )
    conn.commit(); cur.close(); conn.close()
    flash("Preferências de WhatsApp salvas.", "success")
    return redirect(url_for("academia.whatsapp_config", academia_id=academia_id))


@academia_bp.route("/whatsapp/teste", methods=["POST"])
@login_required
def whatsapp_teste():
    if not _wpp_papel_ok():
        return jsonify({"erro": "negado"}), 403
    academia_id, _ = _get_academia_gerenciamento()
    telefone = (request.form.get("telefone") or "").strip()
    if not telefone:
        return jsonify({"ok": False, "erro": "informe um telefone"}), 400
    from utils import whatsapp as wpp
    ok, info = wpp.enviar(
        academia_id, telefone,
        "✅ Teste do Unimaster: seu WhatsApp está conectado e pronto para enviar mensagens automáticas.",
    )
    return jsonify({"ok": ok, "info": info})


@academia_bp.route("/whatsapp/avisos")
@login_required
def whatsapp_avisos():
    if not _wpp_papel_ok():
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
    cur.execute(
        """SELECT id, nome, tel_celular, telefone, responsavel_financeiro_telefone
           FROM alunos WHERE id_academia = %s AND ativo = 1 ORDER BY nome""",
        (academia_id,),
    )
    alunos = cur.fetchall()
    cur.execute("SELECT TurmaID AS id, Nome AS nome FROM turmas WHERE id_academia = %s ORDER BY Nome", (academia_id,))
    turmas = cur.fetchall()
    cur.close(); conn.close()

    from utils import whatsapp as wpp
    st = wpp.status(academia_id)
    return render_template(
        "academia/whatsapp_avisos.html",
        academia_id=academia_id, academias=academias,
        alunos=alunos, turmas=turmas,
        conectado=(st.get("status") == "open"),
    )


@academia_bp.route("/whatsapp/avisos/enviar", methods=["POST"])
@login_required
def whatsapp_avisos_enviar():
    if not _wpp_papel_ok():
        return jsonify({"ok": False, "erro": "negado"}), 403
    academia_id, _ = _get_academia_gerenciamento()
    mensagem = (request.form.get("mensagem") or "").strip()
    destino = (request.form.get("destino") or "todos").strip()
    if not mensagem:
        return jsonify({"ok": False, "erro": "Escreva a mensagem."}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    base = ("SELECT a.id, a.nome, a.tel_celular, a.telefone, a.responsavel_financeiro_telefone "
            "FROM alunos a WHERE a.id_academia = %s AND a.ativo = 1")
    params = [academia_id]
    if destino == "turma":
        turma_id = request.form.get("turma_id", type=int)
        if not turma_id:
            cur.close(); conn.close()
            return jsonify({"ok": False, "erro": "Selecione a turma."}), 400
        base += " AND a.id IN (SELECT aluno_id FROM aluno_turmas WHERE TurmaID = %s)"
        params.append(turma_id)
    elif destino == "selecionados":
        ids = request.form.getlist("aluno_ids")
        ids = [int(i) for i in ids if str(i).isdigit()]
        if not ids:
            cur.close(); conn.close()
            return jsonify({"ok": False, "erro": "Selecione ao menos um aluno."}), 400
        base += " AND a.id IN (%s)" % ",".join(["%s"] * len(ids))
        params.extend(ids)
    cur.execute(base + " ORDER BY a.nome", tuple(params))
    alunos = cur.fetchall()
    cur.close(); conn.close()

    from utils import whatsapp as wpp
    enviados = falhas = sem_tel = 0
    for a in alunos:
        tel = (a.get("responsavel_financeiro_telefone") or a.get("tel_celular") or a.get("telefone") or "").strip()
        if not tel:
            sem_tel += 1
            continue
        # personaliza com o primeiro nome
        primeiro = (a.get("nome") or "").split(" ")[0]
        texto = mensagem.replace("{nome}", primeiro)
        ok, _ = wpp.enviar(academia_id, tel, texto)
        if ok:
            enviados += 1
        else:
            falhas += 1
    return jsonify({"ok": True, "resumo": {"enviados": enviados, "falhas": falhas, "sem_telefone": sem_tel, "total": len(alunos)}})


@academia_bp.route("/whatsapp/mensagens", methods=["GET", "POST"])
@login_required
def whatsapp_mensagens():
    if not _wpp_papel_ok():
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id

    from utils import whatsapp_templates as tpl
    if request.method == "POST":
        for tipo in tpl.TIPOS:
            texto = (request.form.get("texto_" + tipo) or "").strip()
            ativo = request.form.get("ativo_" + tipo) == "1"
            if not texto:
                texto = tpl.padrao(tipo)
            tpl.salvar(academia_id, tipo, texto, ativo)
        flash("Mensagens salvas.", "success")
        return redirect(url_for("academia.whatsapp_mensagens", academia_id=academia_id))

    dados = tpl.carregar(academia_id)
    itens = [{"tipo": t, "label": tpl.TIPOS[t]["label"],
              "texto": dados[t]["texto"], "ativo": dados[t]["ativo"],
              "padrao": tpl.TIPOS[t]["default"]} for t in tpl.ORDEM]
    return render_template(
        "academia/whatsapp_mensagens.html",
        academia_id=academia_id, academias=academias, itens=itens,
    )


# =====================================================
# 🔹 Locais de treino (escolas, projetos, CTs) — por academia
# =====================================================
# Cada local tem um professor. Usados nas inscrições para registrar de onde
# o atleta vem (ex.: alunos de uma escola onde o professor dá aula).

@academia_bp.route("/locais-treino", methods=["GET", "POST"])
@login_required
def locais_treino():
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            acao = request.form.get("acao")
            if acao == "criar":
                nome = (request.form.get("nome") or "").strip()
                professor_id = request.form.get("professor_id", type=int)
                if not nome:
                    flash("Informe o nome do local.", "warning")
                else:
                    cur.execute(
                        """INSERT INTO locais_treino (academia_id, nome, professor_id)
                           VALUES (%s, %s, %s)""",
                        (academia_id, nome, professor_id or None))
                    conn.commit()
                    flash(f"Local '{nome}' cadastrado.", "success")
            elif acao == "excluir":
                local_id = request.form.get("local_id", type=int)
                # Só apaga local da própria academia.
                cur.execute("DELETE FROM locais_treino WHERE id = %s AND academia_id = %s",
                            (local_id, academia_id))
                conn.commit()
                flash("Local removido.", "info")
            return redirect(url_for("academia.locais_treino", academia_id=academia_id))

        cur.execute(
            """SELECT lt.id, lt.nome, lt.ativo, p.nome AS professor_nome
               FROM locais_treino lt
               LEFT JOIN professores p ON p.id = lt.professor_id
               WHERE lt.academia_id = %s ORDER BY lt.nome""", (academia_id,))
        locais = cur.fetchall()
        cur.execute(
            "SELECT id, nome FROM professores WHERE id_academia = %s AND (ativo = 1 OR ativo IS NULL) ORDER BY nome",
            (academia_id,))
        professores = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return render_template("academia/locais_treino.html", locais=locais,
                           professores=professores, academia_id=academia_id,
                           academias=academias)
