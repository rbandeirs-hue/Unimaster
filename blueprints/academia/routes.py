# blueprints/academia/routes.py
from datetime import date, timedelta
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
@academia_bp.route("/escolher", methods=["GET", "POST"])
@login_required
def escolher_academia():
    """Escolha da academia na entrada, para quem administra mais de uma.

    Vale para a sessão inteira: dentro do sistema não há troca de academia, o
    que evitava o risco de lançar mensalidade, presença ou aluno na academia
    errada sem perceber. Para trocar, sai e entra de novo.
    """
    ids = _academias_ids_brutas() or []
    destino = (request.args.get("next") or request.form.get("next") or "").strip()
    if not (destino.startswith("/") and not destino.startswith("//")):
        destino = url_for("painel.home")

    # Uma só academia (ou nenhuma): não há o que escolher.
    if len(ids) <= 1:
        if ids:
            session["academia_gerenciamento_id"] = ids[0]
            session["finance_academia_id"] = ids[0]
        return redirect(destino)

    if request.method == "POST":
        escolhida = request.form.get("academia_id", type=int)
        if escolhida in ids:
            session["academia_gerenciamento_id"] = escolhida
            session["finance_academia_id"] = escolhida
            session["modo_painel"] = "academia"
            return redirect(destino)
        flash("Escolha uma das academias da lista.", "warning")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            f"""SELECT a.id, a.nome, a.cidade, a.uf,
                       (SELECT COUNT(*) FROM alunos al
                         WHERE al.id_academia = a.id AND COALESCE(al.ativo,1) = 1) AS alunos
                FROM academias a WHERE a.id IN ({ph}) ORDER BY a.nome""",
            tuple(ids),
        )
        academias = cur.fetchall() or []
    finally:
        cur.close()
        conn.close()

    return render_template(
        "academia/escolher_academia.html",
        academias=academias,
        proximo=destino,
    )


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

        # Quantos viraram aluno — é o desfecho que a tela quer medir.
        # O vínculo é pelo CPF (o cadastro de visitante não guarda aluno_id).
        try:
            cur.execute("""
                SELECT COUNT(*) AS c
                FROM visitantes v
                WHERE v.id_academia = %s AND v.cpf IS NOT NULL AND v.cpf <> ''
                  AND EXISTS (
                      SELECT 1 FROM alunos a
                      WHERE a.id_academia = v.id_academia
                        AND REGEXP_REPLACE(a.cpf, '[^0-9]', '') = REGEXP_REPLACE(v.cpf, '[^0-9]', '')
                  )
            """, (academia_id,))
            stats["convertidos"] = cur.fetchone().get("c", 0) or 0
        except Exception:
            stats["convertidos"] = 0

    except Exception as e:
        flash(f"Erro ao carregar visitantes: {e}", "danger")
        visitantes = []
        stats = {"total_visitantes": 0, "visitantes_ativos": 0,
                 "visitantes_com_aulas": 0, "convertidos": 0}

    # Contadores das abas (as outras três telas de visitantes).
    abas = {"solicitacoes": 0, "diarias": 0, "matriculas": 0}
    try:
        cur.execute("""SELECT COUNT(*) c FROM aulas_experimentais ae
                       JOIN visitantes v ON v.id = ae.visitante_id
                       WHERE v.id_academia = %s AND ae.status = 'pendente'""", (academia_id,))
        abas["solicitacoes"] = cur.fetchone().get("c", 0) or 0
    except Exception:
        pass
    try:
        cur.execute("""SELECT COUNT(*) c FROM pagamentos_diaria p
                       JOIN visitantes v ON v.id = p.visitante_id
                       WHERE v.id_academia = %s AND p.status = 'pendente'""", (academia_id,))
        abas["diarias"] = cur.fetchone().get("c", 0) or 0
    except Exception:
        pass
    try:
        cur.execute("""SELECT COUNT(*) c FROM solicitacoes_mensalidade s
                       JOIN visitantes v ON v.id = s.visitante_id
                       WHERE v.id_academia = %s AND s.status = 'pendente'""", (academia_id,))
        abas["matriculas"] = cur.fetchone().get("c", 0) or 0
    except Exception:
        pass

    try:
        cur.close()
        conn.close()
    except Exception:
        pass

    # Filtros da tela (aplicados em memória: a lista de visitantes é curta).
    busca = (request.args.get("busca") or "").strip()
    status_f = (request.args.get("status") or "").strip().lower()
    ultima_f = (request.args.get("ultima_aula") or "").strip().lower()
    total_sem_filtro = len(visitantes)
    if busca:
        alvo = busca.lower()
        so_digitos = "".join(filter(str.isdigit, busca))
        visitantes = [
            v for v in visitantes
            if alvo in (v.get("nome") or "").lower()
            or (so_digitos and so_digitos in "".join(filter(str.isdigit, str(v.get("telefone") or ""))))
        ]
    if status_f == "ativo":
        visitantes = [v for v in visitantes if v.get("ativo")]
    elif status_f == "inativo":
        visitantes = [v for v in visitantes if not v.get("ativo")]
    if ultima_f in ("30", "90"):
        limite = date.today() - timedelta(days=int(ultima_f))
        def _dt(v):
            d = v.get("ultima_aula")
            return d.date() if hasattr(d, "date") else d
        visitantes = [v for v in visitantes if _dt(v) and _dt(v) >= limite]
    elif ultima_f == "sem":
        visitantes = [v for v in visitantes if not v.get("ultima_aula")]

    return render_template(
        "academia/visitantes/lista.html",
        visitantes=visitantes,
        stats=stats,
        abas=abas,
        academias=academias,
        academia_id=academia_id,
        academia=next((a for a in academias if a.get("id") == academia_id), None),
        busca=busca,
        status_f=status_f,
        ultima_f=ultima_f,
        total_sem_filtro=total_sem_filtro,
        filtrado=bool(busca or status_f or ultima_f),
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


def _academias_ids_brutas():
    """Todas as academias a que o usuário tem direito, sem considerar a trava.

    Usada pela tela de escolha e por quem precisa do conjunto inteiro. No dia a
    dia use `_get_academias_ids()`, que devolve só a academia da sessão.
    """
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


def academia_travada():
    """Academia escolhida na entrada, quando o usuário administra mais de uma.

    A escolha é feita uma vez por sessão e não muda por dentro do sistema: sem
    isso, um `?academia_id=` numa URL trocava o contexto sem ninguém perceber e
    o gestor acabava lançando dados na academia errada.
    """
    aid = session.get("academia_gerenciamento_id")
    if not aid:
        return None
    ids = _academias_ids_brutas() or []
    return aid if aid in ids else None


def precisa_escolher_academia():
    """True quando o usuário administra mais de uma academia e ainda não escolheu."""
    if session.get("modo_painel") not in (None, "", "academia"):
        return False
    ids = _academias_ids_brutas() or []
    if len(ids) <= 1:
        return False
    return academia_travada() is None


def filtrar_academias_da_sessao(academias):
    """Reduz uma lista de academias à escolhida na sessão.

    Várias telas montam a própria lista com SQL próprio para alimentar um
    seletor. Passando por aqui, todas respeitam a escolha feita na entrada sem
    precisar repetir a regra.
    """
    if not academias:
        return academias
    travada = academia_travada()
    if not travada or session.get("modo_painel") != "academia":
        return academias
    def _id(a):
        return a.get("id") if isinstance(a, dict) else getattr(a, "id", None)
    filtradas = [a for a in academias if _id(a) == travada]
    return filtradas or academias


def _get_academias_ids():
    """Academias válidas para esta sessão.

    No modo academia, depois da escolha na entrada, é só a academia escolhida:
    é isso que impede navegar (e gravar) em outra sem passar pela escolha. Nos
    modos associação/federação continua o conjunto inteiro, que é o próprio
    sentido daqueles painéis.
    """
    ids = _academias_ids_brutas()
    if len(ids) <= 1:
        return ids
    if session.get("modo_painel") != "academia":
        return ids
    escolhida = session.get("academia_gerenciamento_id")
    if escolhida and escolhida in ids:
        return [escolhida]
    return ids


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
        session["academia_gerenciamento_id"] = ids[0]
        session["finance_academia_id"] = ids[0]
        return ids[0], academias

    # Mais de uma academia: vale a escolhida na entrada. O `academia_id` da URL
    # é aceito apenas quando é a mesma — links internos o carregam o tempo
    # todo —, nunca para trocar de academia por dentro.
    aid = academia_travada()
    if not aid:
        pedido = request.args.get("academia_id", type=int)
        aid = pedido if (pedido and pedido in ids) else ids[0]
    session["academia_gerenciamento_id"] = aid
    session["finance_academia_id"] = aid
    # Só a academia da sessão vai para as telas: cada uma monta o próprio
    # seletor a partir desta lista, e a lista completa fazia reaparecer a troca
    # de academia por dentro do sistema.
    academias = [a for a in academias if a.get("id") == aid] or academias
    return aid, academias


def _painel_academia_resumo(academia_id):
    """Números do topo do painel: o resumo da academia e o que pede atenção.

    Só leitura — nenhuma escrita, nenhuma regra de negócio. Cada consulta é
    isolada em try/except porque o painel não pode deixar de abrir por causa de
    um contador: na falha, aquele número vem zerado e o resto da tela continua.
    """
    r = {
        "alunos_ativos": 0, "turmas": 0, "modalidades": 0,
        "solicitacoes_pendentes": 0, "mensalidades_atraso": 0,
        "precadastros": 0, "aniversariantes": 0,
    }
    if not academia_id:
        return r

    consultas = {
        "alunos_ativos": (
            "SELECT COUNT(*) c FROM alunos WHERE id_academia=%s AND status='ativo'", (academia_id,)),
        "turmas": (
            "SELECT COUNT(*) c FROM turmas WHERE id_academia=%s", (academia_id,)),
        "modalidades": (
            "SELECT COUNT(*) c FROM academia_modalidades WHERE academia_id=%s", (academia_id,)),
        # Pendente em qualquer ponta: a academia pode ser origem ou destino.
        "solicitacoes_pendentes": (
            """SELECT COUNT(*) c FROM solicitacoes_aprovacao
               WHERE (academia_destino_id=%s OR academia_origem_id=%s) AND status LIKE 'pendente%%'""",
            (academia_id, academia_id)),
        # Mesmo critério do dashboard: atrasada ou pendente já vencida.
        # O recorte é pela academia que emitiu a cobrança (`mensalidades`), não
        # pela academia atual do aluno: quem transfere de unidade levava a dívida
        # antiga junto para a academia de destino.
        "mensalidades_atraso": (
            """SELECT COUNT(*) c FROM mensalidade_aluno ma
               JOIN mensalidades mp ON mp.id = ma.mensalidade_id
               WHERE mp.id_academia=%s
                 AND (ma.status='atrasado' OR (ma.status='pendente' AND ma.data_vencimento < CURDATE()))""",
            (academia_id,)),
        # Ao promover, o pré-cadastro é apagado: o que resta é o que falta converter.
        "precadastros": (
            "SELECT COUNT(*) c FROM pre_cadastro WHERE academia_id=%s", (academia_id,)),
        "aniversariantes": (
            """SELECT COUNT(*) c FROM alunos
               WHERE id_academia=%s AND status='ativo' AND MONTH(data_nascimento)=MONTH(CURDATE())""",
            (academia_id,)),
    }

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for chave, (sql, params) in consultas.items():
            try:
                cur.execute(sql, params)
                r[chave] = (cur.fetchone() or {}).get("c") or 0
            except Exception as e:
                current_app.logger.info("Painel da academia: contador %s falhou (%s)", chave, e)
    finally:
        cur.close()
        conn.close()
    return r


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
def _filtro_alunos_sql(turma_id=None, modalidade_id=None):
    """Recorte de turma/modalidade para consultas que usam a tabela `alunos` como `a`.

    Devolve (fragmento_sql, params). Aluno pode estar em mais de uma turma e em
    mais de uma modalidade, daí o `IN (SELECT ...)` em vez de JOIN — evita
    duplicar linhas e inflar as somas.
    """
    cond, params = "", []
    if turma_id:
        cond += " AND a.id IN (SELECT at.aluno_id FROM aluno_turmas at WHERE at.TurmaID=%s)"
        params.append(turma_id)
    if modalidade_id:
        cond += " AND a.id IN (SELECT am.aluno_id FROM aluno_modalidades am WHERE am.modalidade_id=%s)"
        params.append(modalidade_id)
    return cond, params


def _kpis_mes(cur, academia_id, ano, mes, filtro_cond="", filtro_params=()):
    """KPIs de um mês específico (alunos novos/baixas, receitas/despesas, mensalidades previsto/recebido).

    `filtro_cond`/`filtro_params` restringem a turma/modalidade os indicadores que
    passam por aluno. Receitas e despesas ficam de fora do recorte: são lançamentos
    da academia, sem vínculo com turma.
    """
    import calendar
    ini = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    k = {"ano": ano, "mes": mes}
    fp = tuple(filtro_params)

    cur.execute(
        f"SELECT COUNT(*) c FROM alunos a WHERE a.id_academia=%s AND a.data_matricula BETWEEN %s AND %s{filtro_cond}",
        (academia_id, ini, fim) + fp,
    )
    k["novos"] = cur.fetchone()["c"] or 0
    cur.execute(
        f"SELECT COUNT(*) c FROM alunos a WHERE a.id_academia=%s AND a.data_inativacao BETWEEN %s AND %s{filtro_cond}",
        (academia_id, ini, fim) + fp,
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
        f"""SELECT COALESCE(SUM(ma.valor),0) v FROM mensalidade_aluno ma
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE a.id_academia=%s AND ma.status <> 'cancelado'
              AND ma.data_vencimento BETWEEN %s AND %s{filtro_cond}""",
        (academia_id, ini, fim) + fp,
    )
    k["mens_previsto"] = float(cur.fetchone()["v"] or 0)
    cur.execute(
        f"""SELECT COALESCE(SUM(COALESCE(ma.valor_pago, ma.valor)),0) v FROM mensalidade_aluno ma
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE a.id_academia=%s AND ma.status = 'pago'
              AND ma.data_pagamento BETWEEN %s AND %s{filtro_cond}""",
        (academia_id, ini, fim) + fp,
    )
    k["mens_recebido"] = float(cur.fetchone()["v"] or 0)
    return k


def _get_academia_dashboard(academia_id, ano, mes, turma_id=None, modalidade_id=None):
    """Monta todos os KPIs do dashboard do modo academia para o mês/ano informados.

    `turma_id`/`modalidade_id` recortam tudo o que passa por aluno (quadro de
    alunos, inadimplência, mensalidades), permitindo comparar o desempenho de
    cada turma ou modalidade. Receitas e despesas continuam sendo da academia
    inteira — não têm vínculo com turma —, e a tela avisa isso.
    """
    d = {"ano": ano, "mes": mes}
    fcond, fparams = _filtro_alunos_sql(turma_id, modalidade_id)
    fp = tuple(fparams)
    d["filtrado"] = bool(fcond)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Mês atual e mês anterior (para comparativo)
        atual = _kpis_mes(cur, academia_id, ano, mes, fcond, fp)
        pmes, pano = (12, ano - 1) if mes == 1 else (mes - 1, ano)
        anterior = _kpis_mes(cur, academia_id, pano, pmes, fcond, fp)
        d["atual"] = atual
        d["anterior"] = anterior

        # Quadro de alunos NA POSIÇÃO DO MÊS ESCOLHIDO.
        #
        # Antes isto era um `SELECT ... FROM alunos` sem recorte de data: uma foto
        # do estado de hoje, que não mudava ao trocar o mês — janeiro exibia o
        # mesmo total de agosto. Agora conta quem já estava matriculado até o fim
        # do mês e ainda não tinha sido inativado.
        #
        # Mês corrente (ou futuro) usa o status real de cada aluno, que é exato
        # hoje e permite separar suspenso/formado. Para meses passados só dá para
        # reconstruir ativo/inativo, porque `status` guarda apenas a situação
        # atual — quem saiu sem `data_inativacao` preenchida conta como ativo até
        # aparecer a data.
        import calendar as _cal_pos
        fim_ref = min(date(ano, mes, _cal_pos.monthrange(ano, mes)[1]), date.today())
        mes_corrente = (ano, mes) >= (date.today().year, date.today().month)

        cur.execute(
            f"""SELECT a.status, a.data_inativacao
                FROM alunos a
                WHERE a.id_academia=%s AND (a.data_matricula IS NULL OR a.data_matricula <= %s){fcond}""",
            (academia_id, fim_ref) + fp,
        )
        linhas = cur.fetchall()

        por_status = {}
        for r in linhas:
            saiu = r["data_inativacao"] is not None and r["data_inativacao"] <= fim_ref
            if mes_corrente:
                chave = r["status"] or "ativo"
            else:
                chave = "inativo" if saiu else "ativo"
            por_status[chave] = por_status.get(chave, 0) + 1

        ativos = por_status.get("ativo", 0)
        d["por_status"] = por_status
        d["ativos"] = ativos
        d["inativos"] = por_status.get("inativo", 0)
        d["suspensos"] = por_status.get("suspenso", 0)
        d["formados"] = por_status.get("formado", 0)
        d["total_alunos"] = sum(por_status.values())
        d["posicao_historica"] = not mes_corrente
        d["posicao_data"] = fim_ref

        # Inadimplência (snapshot atual): atrasado OU pendente vencido.
        #
        # Duas restrições que o número precisa respeitar para ser lido junto com
        # "N de M alunos ativos":
        #  • cobrança de valor zero não é dívida — é o caso de quem teve a
        #    mensalidade coberta por desconto integral e ficou com a linha em
        #    aberto; sem isto o aluno aparecia na lista devendo R$ 0,00;
        #  • aluno inativo não entra, senão o numerador podia superar o total de
        #    ativos e o percentual passar de 100%;
        #  • a cobrança conta para a academia que a emitiu (`mensalidades`), não
        #    para a academia atual do aluno — sem isto, uma parcela vencida
        #    deixada para trás numa transferência de unidade era exibida como
        #    inadimplência da academia de destino.
        cond_atraso = (
            "(ma.status='atrasado' OR (ma.status='pendente' AND ma.data_vencimento < CURDATE()))"
            " AND ma.valor > 0 AND a.status = 'ativo'"
        )
        cur.execute(
            f"""SELECT COALESCE(SUM(ma.valor),0) v, COUNT(DISTINCT ma.aluno_id) a
                FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                JOIN mensalidades mp ON mp.id = ma.mensalidade_id
                WHERE mp.id_academia=%s AND {cond_atraso}{fcond}""",
            (academia_id,) + fp,
        )
        row = cur.fetchone()
        d["atrasado_valor"] = float(row["v"] or 0)
        d["inadimplentes_qtd"] = row["a"] or 0
        d["inadimplencia_pct"] = round((d["inadimplentes_qtd"] / ativos * 100), 1) if ativos else 0.0
        d["ticket_medio"] = round((atual["mens_recebido"] / ativos), 2) if ativos else 0.0
        d["saldo_alunos"] = atual["novos"] - atual["baixas"]
        base_churn = ativos + atual["baixas"]
        d["churn_pct"] = round((atual["baixas"] / base_churn * 100), 1) if base_churn else 0.0

        # Percentual do previsto que já entrou, limitado a 100 para a barra.
        d["mens_pct"] = (
            round(atual["mens_recebido"] / atual["mens_previsto"] * 100, 1)
            if atual["mens_previsto"] else 0.0
        )

        # Conciliação: "Receitas" soma a tabela `receitas` (tudo que entrou no
        # caixa, de qualquer origem) e "Mensalidades recebidas" soma as baixas em
        # mensalidade_aluno. São bases diferentes e podem divergir quando uma
        # baixa não gerou lançamento de receita. A tela precisa dizer isso em vez
        # de exibir os dois números lado a lado como se fossem o mesmo.
        cur.execute(
            """SELECT COALESCE(SUM(valor),0) v FROM receitas
               WHERE id_academia=%s AND data BETWEEN %s AND %s AND categoria='Mensalidades'""",
            (academia_id, date(ano, mes, 1),
             date(ano, mes, __import__("calendar").monthrange(ano, mes)[1])),
        )
        d["receitas_mensalidades"] = float(cur.fetchone()["v"] or 0)
        d["conciliacao_dif"] = round(atual["mens_recebido"] - d["receitas_mensalidades"], 2)
        d["conciliacao_ok"] = abs(d["conciliacao_dif"]) < 0.01

        # Nome do mês anterior, para o comparativo dos indicadores ("vs julho").
        _meses_nome = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                       "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
        d["mes_nome"] = _meses_nome[mes - 1]
        d["mes_anterior_nome"] = _meses_nome[pmes - 1]

        # Lista de inadimplentes (top 10 por valor)
        cur.execute(
            f"""SELECT a.id, a.nome, COUNT(*) qtd, COALESCE(SUM(ma.valor),0) total,
                       MIN(ma.data_vencimento) venc
                FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                JOIN mensalidades mp ON mp.id = ma.mensalidade_id
                WHERE mp.id_academia=%s AND {cond_atraso}{fcond}
                GROUP BY a.id, a.nome ORDER BY total DESC, venc ASC LIMIT 10""",
            (academia_id,) + fp,
        )
        d["inadimplentes"] = cur.fetchall()

        # ---- Financeiro avançado ----
        import calendar as _cal
        ini_mes = date(ano, mes, 1)
        fim_mes = date(ano, mes, _cal.monthrange(ano, mes)[1])
        ini_ano = date(ano, 1, 1)

        # MRR (receita recorrente): soma da mensalidade mais recente (não cancelada) de cada aluno ativo
        cur.execute(
            f"""SELECT COALESCE(SUM(t.valor),0) v FROM (
                  SELECT ma.valor
                  FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                  WHERE a.id_academia=%s AND a.status='ativo' AND ma.status<>'cancelado'{fcond}
                    AND ma.id = (SELECT ma2.id FROM mensalidade_aluno ma2
                                 WHERE ma2.aluno_id = ma.aluno_id AND ma2.status<>'cancelado'
                                 ORDER BY ma2.data_vencimento DESC, ma2.id DESC LIMIT 1)
                ) t""",
            (academia_id,) + fp,
        )
        d["mrr"] = float(cur.fetchone()["v"] or 0)

        # Mensalidades vencendo nos próximos 7 dias (ainda pendentes)
        cur.execute(
            f"""SELECT COALESCE(SUM(ma.valor),0) v, COUNT(*) c
                FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                WHERE a.id_academia=%s AND ma.status='pendente'
                  AND ma.data_vencimento BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY){fcond}""",
            (academia_id,) + fp,
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
               WHERE a.id_academia=%s AND ma.status='pago' AND ma.data_pagamento BETWEEN %s AND %s"""
            + fcond + """
               GROUP BY fp.nome ORDER BY total DESC""",
            (academia_id, ini_mes, fim_mes) + fp,
        )
        d["por_forma"] = [{"nome": r["nome"], "total": float(r["total"] or 0)} for r in cur.fetchall()]

        # Série dos últimos 6 meses (para gráfico)
        meses_pt = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
        serie = []
        sm, sy = mes, ano
        for _ in range(6):
            km = _kpis_mes(cur, academia_id, sy, sm, fcond, fp)
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

    turma_id = request.args.get("turma_id", type=int) or None
    modalidade_id = request.args.get("modalidade_id", type=int) or None

    # Opções dos filtros: turmas da academia e modalidades que os alunos dela cursam.
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT TurmaID AS id, Nome AS nome FROM turmas WHERE id_academia=%s ORDER BY Nome",
            (academia_id,),
        )
        turmas_opts = cur.fetchall()
        cur.execute(
            """SELECT DISTINCT md.id, md.nome
               FROM modalidade md
               JOIN aluno_modalidades am ON am.modalidade_id = md.id
               JOIN alunos a ON a.id = am.aluno_id
               WHERE a.id_academia=%s ORDER BY md.nome""",
            (academia_id,),
        )
        modalidades_opts = cur.fetchall()
    except Exception:
        turmas_opts, modalidades_opts = [], []
    finally:
        cur.close()
        conn.close()

    # Filtro inválido para esta academia não pode virar recorte vazio silencioso.
    if turma_id and turma_id not in [t["id"] for t in turmas_opts]:
        turma_id = None
    if modalidade_id and modalidade_id not in [m["id"] for m in modalidades_opts]:
        modalidade_id = None

    stats = _get_academia_stats(academia_id)
    dash_data = _get_academia_dashboard(academia_id, ano, mes, turma_id, modalidade_id)
    # O shell (base_academia.html) usa `academia` para montar o menu lateral e o
    # rodapé; sem ele o item "Professores" some da navegação.
    academia = next((a for a in academias if a.get("id") == academia_id), None)
    return render_template(
        "painel/academia_dash.html",
        stats=stats,
        academias=academias,
        academia=academia,
        academia_id=academia_id,
        dash=dash_data,
        mes=mes,
        ano=ano,
        turmas_opts=turmas_opts,
        modalidades_opts=modalidades_opts,
        turma_id=turma_id,
        modalidade_id=modalidade_id,
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
        resumo=_painel_academia_resumo(academia_id),
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

    # Recorte por papel. Entra como id inteiro, validado adiante contra os papéis
    # existentes, para poder ser embutido no SQL sem mexer nas tuplas de
    # parâmetros das consultas (que são posicionais e montadas em vários ramos).
    papel_id = request.args.get("papel", type=int)
    sql_papel = ""
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)

    # Papéis disponíveis para o filtro (e validação do id recebido).
    try:
        cur.execute(
            "SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) AS chave FROM roles ORDER BY nome"
        )
        papeis_opts = cur.fetchall()
    except Exception:
        papeis_opts = []
    if papel_id and papel_id in {p["id"] for p in papeis_opts}:
        sql_papel = (
            " AND EXISTS (SELECT 1 FROM roles_usuario ru2"
            f" WHERE ru2.usuario_id = u.id AND ru2.role_id = {int(papel_id)})"
        )
    else:
        papel_id = None

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
                    {sql_status}{sql_papel}
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                """, params_count)
            else:
                cur.execute(f"""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE {filtro_academia}
                    {sql_status}{sql_papel}
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
                    {sql_status}{sql_papel}
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
                    {sql_status}{sql_papel}
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
                    {sql_status}{sql_papel}
                    AND (u.nome LIKE %s OR u.email LIKE %s)
                """, (academia_id, f"%{busca}%", f"%{busca}%"))
            else:
                cur.execute(f"""
                    SELECT COUNT(DISTINCT u.id) AS total
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    WHERE ua.academia_id = %s
                    {sql_status}{sql_papel}
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
                    {sql_status}{sql_papel}
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
                    {sql_status}{sql_papel}
                    ORDER BY u.nome
                    LIMIT %s OFFSET %s
                """, (academia_id, por_pagina, offset))

            usuarios = cur.fetchall()

        # Indicadores do topo: retratam a academia/associação inteira, sem os
        # filtros da tela — se encolhessem junto com a busca deixariam de ser
        # referência para o que a listagem está mostrando.
        try:
            if modo_associacao and academia_id is None:
                _ids_stats = [ac["id"] for ac in academias] or [0]
                _ph_stats = ",".join(["%s"] * len(_ids_stats))
                _where_stats = f"ua.academia_id IN ({_ph_stats})"
                _params_stats = tuple(_ids_stats)
            else:
                _where_stats = "ua.academia_id = %s"
                _params_stats = (academia_id,)
            cur.execute(f"""
                SELECT COUNT(DISTINCT u.id) AS total,
                       COUNT(DISTINCT CASE WHEN COALESCE(u.ativo, 1) = 1 THEN u.id END) AS ativos,
                       COUNT(DISTINCT CASE WHEN COALESCE(u.ativo, 1) = 0 THEN u.id END) AS inativos,
                       COUNT(DISTINCT CASE WHEN u.cpf IS NULL OR u.cpf = '' THEN u.id END) AS cpf_pendente
                FROM usuarios u
                INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                WHERE {_where_stats}
            """, _params_stats)
            stats_usuarios = cur.fetchone() or {}
        except Exception:
            stats_usuarios = {}

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
        stats_usuarios = {}
        papeis_opts = []
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "academia/lista_usuarios.html",
        usuarios=usuarios,
        stats_usuarios=stats_usuarios,
        papeis_opts=papeis_opts,
        papel_id=papel_id,
        por_pagina=por_pagina,
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
def _chave_pix_normalizada(academia):
    """Como a chave da academia sai no BR Code, para conferência na tela."""
    try:
        from utils.pix_brcode import limpar_chave

        if not academia or not (academia.get("pix_chave") or "").strip():
            return None
        if not (academia.get("pix_tipo") or "").strip():
            return None
        return limpar_chave(academia.get("pix_chave"), academia.get("pix_tipo"))
    except Exception:
        return None


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

                # Chave PIX da própria academia — independente do gateway. É a
                # segunda opção que o aluno vê na página de pagamento, e a única
                # que continua funcionando com o gateway fora do ar.
                pix_chave = (request.form.get("pix_chave") or "").strip() or None
                pix_tipo = (request.form.get("pix_tipo") or "").strip().lower() or None
                pix_beneficiario = (request.form.get("pix_beneficiario") or "").strip()[:25] or None
                pix_cidade = (request.form.get("pix_cidade") or "").strip()[:15] or None
                if pix_chave:
                    # Chave com tipo errado gera um código que o banco recusa
                    # dizendo que "não existe" — barrar aqui evita o aluno
                    # descobrir isso na hora de pagar.
                    from utils.pix_brcode import validar_chave
                    _erro_pix = validar_chave(pix_chave, pix_tipo)
                    if _erro_pix:
                        flash(f"Chave PIX: {_erro_pix}", "danger")
                        pix_chave = pix_tipo = pix_beneficiario = pix_cidade = None

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
                           sumup_merchant_code=%s, sumup_ambiente=%s, sumup_habilitado=%s,
                           pix_chave=%s, pix_tipo=%s, pix_beneficiario=%s, pix_cidade=%s
                       WHERE id=%s""",
                    (gateway, asaas_habilitado, ambiente, webhook_token, infinitepay_handle,
                     cora_client_id, cora_client_id_prod, cora_ambiente,
                     efi_client_id, efi_pix_key, efi_ambiente,
                     sumup_merchant_code, sumup_ambiente, sumup_habilitado,
                     pix_chave, pix_tipo, pix_beneficiario, pix_cidade, academia_id),
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
        # Mostra na tela exatamente a chave que vai dentro do código PIX: é a
        # única forma de o gestor conferir sem precisar tentar pagar.
        chave_pix_normalizada=_chave_pix_normalizada(academia),
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
        "SELECT id, nome, whatsapp_numero, whatsapp_lembrete_mensalidade, whatsapp_avisos, "
        "COALESCE(whatsapp_aniversario, 0) AS whatsapp_aniversario, whatsapp_conectado_em "
        "FROM academias WHERE id = %s",
        (academia_id,),
    )
    acad = cur.fetchone() or {}
    cur.close(); conn.close()

    from utils import whatsapp as wpp
    from utils import whatsapp_log as wlog
    st = wpp.status(academia_id)

    # Estatísticas reais (log de envios) + estado das automações.
    from datetime import date as _date
    _meses_pt = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    _hoje = _date.today()
    mes_label = f"{_meses_pt[_hoje.month]} de {_hoje.year}"
    stats = wlog.resumo_mes(academia_id)
    automacoes_ativas = sum(1 for k in (
        "whatsapp_lembrete_mensalidade", "whatsapp_avisos", "whatsapp_aniversario"
    ) if acad.get(k))
    ultimos = wlog.ultimos_lotes(academia_id, limite=6)
    ultimo_tipo = wlog.ultimo_por_tipo(academia_id)

    # Modelos ativos — alimentam o seletor da mensagem de teste.
    from utils import whatsapp_templates as tpl
    try:
        _dados = tpl.carregar(academia_id)
        modelos = [{"tipo": t, "label": tpl.TIPOS[t]["label"], "ativo": _dados[t]["ativo"]}
                   for t in tpl.ORDEM]
    except Exception:
        modelos = []

    return render_template(
        "academia/whatsapp.html",
        modelos=modelos,
        academia_id=academia_id, academias=academias, acad=acad,
        academia={"id": academia_id, "nome": acad.get("nome")},
        wpp_status=st.get("status", "offline"), wpp_numero=st.get("number"),
        servico_online=wpp.disponivel(),
        stats=stats, automacoes_ativas=automacoes_ativas,
        ultimos_envios=ultimos, ultimo_por_tipo=ultimo_tipo,
        conectado_em=acad.get("whatsapp_conectado_em"), mes_label=mes_label,
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
            # Marca o início da sessão só na transição desconectado→conectado,
            # para "Sessão ativa desde" não reiniciar a cada poll do QR.
            cur.execute(
                "UPDATE academias SET whatsapp_numero=%s, "
                "whatsapp_conectado_em=COALESCE(whatsapp_conectado_em, NOW()) WHERE id=%s",
                (info["number"], academia_id),
            )
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
        cur.execute("UPDATE academias SET whatsapp_numero=NULL, whatsapp_conectado_em=NULL WHERE id=%s", (academia_id,))
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
    from utils import whatsapp_log as wlog
    # Modelo escolhido no seletor: envia o texto real do modelo com dados de
    # exemplo. Sem modelo, manda a mensagem de teste padrão.
    modelo = (request.form.get("modelo") or "").strip()
    mensagem = "✅ Teste do Unimaster: seu WhatsApp está conectado e pronto para enviar mensagens automáticas."
    if modelo:
        try:
            from utils import whatsapp_templates as tpl
            if modelo in tpl.TIPOS:
                texto, _ativo = tpl.obter(academia_id, modelo)
                ctx = {
                    "nome": "Ana", "aluno": "Ana Beatriz Sousa",
                    "valor": "R$ 70,00", "vencimento": "10/09/2026",
                    "link": "pesv.org.br/pag/8f2c", "pix": "",
                    "academia": "", "mes": "09/2026",
                }
                mensagem = "🧪 (teste) " + tpl.render(texto, ctx)
        except Exception:
            pass
    ok, info = wpp.enviar(academia_id, telefone, mensagem)
    wlog.registrar(academia_id, "teste", "entregue" if ok else "falha", telefone=telefone,
                   erro=(info or {}).get("erro") if isinstance(info, dict) else None)
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
    alunos_raw = cur.fetchall()

    def _tem_tel(a):
        return bool((a.get("responsavel_financeiro_telefone") or a.get("tel_celular") or a.get("telefone") or "").strip())

    # Lista enxuta para o seletor "Selecionar alunos" e para o cálculo de resumo.
    alunos = [{"id": a["id"], "nome": a["nome"], "tem_tel": _tem_tel(a)} for a in alunos_raw]
    total_alunos = len(alunos)
    total_sem_tel = sum(0 if a["tem_tel"] else 1 for a in alunos)

    # Turmas com contagem de alunos e quantos sem telefone (para o resumo por turma).
    cur.execute("SELECT TurmaID AS id, Nome AS nome FROM turmas WHERE id_academia = %s ORDER BY Nome", (academia_id,))
    turmas_raw = cur.fetchall()
    # Mapa aluno_id -> tem_tel para contar por turma sem nova consulta pesada.
    tem_tel_por_aluno = {a["id"]: a["tem_tel"] for a in alunos}
    turmas = []
    for t in turmas_raw:
        cur.execute("SELECT aluno_id FROM aluno_turmas WHERE TurmaID = %s", (t["id"],))
        ids_t = [r["aluno_id"] for r in cur.fetchall() if r["aluno_id"] in tem_tel_por_aluno]
        turmas.append({
            "id": t["id"], "nome": t["nome"],
            "total": len(ids_t),
            "sem_tel": sum(0 if tem_tel_por_aluno.get(i) else 1 for i in ids_t),
        })
    cur.close(); conn.close()

    from utils import whatsapp as wpp
    from utils import whatsapp_templates as tpl
    st = wpp.status(academia_id)
    try:
        _dm = tpl.carregar(academia_id)
        modelos = [{"tipo": t, "label": tpl.TIPOS[t]["label"], "texto": _dm[t]["texto"]} for t in tpl.ORDEM]
    except Exception:
        modelos = []
    nome_acad = next((a.get("nome") for a in (academias or []) if a.get("id") == academia_id), None)
    return render_template(
        "academia/whatsapp_avisos.html",
        academia_id=academia_id, academias=academias,
        academia={"id": academia_id, "nome": nome_acad},
        alunos=alunos, turmas=turmas, modelos=modelos,
        total_alunos=total_alunos, total_sem_tel=total_sem_tel,
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
    turma_nome = ""
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
        try:
            cur.execute("SELECT Nome FROM turmas WHERE TurmaID = %s", (turma_id,))
            turma_nome = ((cur.fetchone() or {}).get("Nome") or "").strip()
        except Exception:
            turma_nome = ""
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
    # Nome da academia para o placeholder {academia}.
    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    nome_acad = ((cur.fetchone() or {}).get("nome") or "").strip()
    cur.close(); conn.close()

    from utils import whatsapp as wpp
    from utils import whatsapp_log as wlog
    import uuid
    lote_id = "aviso-" + uuid.uuid4().hex[:12]
    enviados = falhas = sem_tel = 0
    for a in alunos:
        tel = (a.get("responsavel_financeiro_telefone") or a.get("tel_celular") or a.get("telefone") or "").strip()
        if not tel:
            sem_tel += 1
            wlog.registrar(academia_id, "aviso", "sem_numero", aluno_id=a.get("id"), lote_id=lote_id)
            continue
        # Substitui as variáveis suportadas nos avisos.
        primeiro = (a.get("nome") or "").split(" ")[0]
        texto = (mensagem
                 .replace("{nome}", primeiro)
                 .replace("{aluno}", a.get("nome") or "")
                 .replace("{turma}", turma_nome)
                 .replace("{academia}", nome_acad))
        ok, info = wpp.enviar(academia_id, tel, texto)
        if ok:
            enviados += 1
            wlog.registrar(academia_id, "aviso", "entregue", aluno_id=a.get("id"), telefone=tel, lote_id=lote_id)
        else:
            falhas += 1
            wlog.registrar(academia_id, "aviso", "falha", aluno_id=a.get("id"), telefone=tel,
                           erro=(info or {}).get("erro") if isinstance(info, dict) else None, lote_id=lote_id)
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
    nome_acad = next((a.get("nome") for a in (academias or []) if a.get("id") == academia_id), None)
    from datetime import date as _date
    _meses_pt = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    return render_template(
        "academia/whatsapp_mensagens.html",
        academia_id=academia_id, academias=academias,
        academia={"id": academia_id, "nome": nome_acad}, itens=itens,
        mes_exemplo=_meses_pt[_date.today().month],
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
