# ======================================================
# Blueprint: Visitante - Aulas Experimentais
# ======================================================
from datetime import date, datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required, current_user
from config import get_db_connection
from werkzeug.security import generate_password_hash
import os
import uuid
import base64

# Importar o blueprint do __init__.py
from . import bp_visitante


def _calcular_idade(data_nascimento):
    """Calcula idade a partir da data de nascimento."""
    if not data_nascimento:
        return None
    try:
        if isinstance(data_nascimento, str):
            nasc = datetime.strptime(data_nascimento[:10], "%Y-%m-%d").date()
        else:
            nasc = data_nascimento
        hoje = date.today()
        idade = hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
        return idade
    except Exception:
        return None


def _get_academia_id():
    """Retorna ID da academia do visitante."""
    if current_user.has_role("admin"):
        return request.args.get("academia_id", type=int) or session.get("academia_id")
    return getattr(current_user, "id_academia", None) or session.get("academia_id")


def _salvar_foto_base64(data_url, prefixo="visitante"):
    """Salva foto a partir de dataURL (base64)."""
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        if "," in data_url:
            _, encoded = data_url.split(",", 1)
        else:
            encoded = data_url
        img_data = base64.b64decode(encoded)
    except Exception:
        return None
    
    upload_dir = os.path.join("static", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{prefixo}_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(upload_dir, filename)
    
    with open(filepath, "wb") as f:
        f.write(img_data)
    return filename


# ======================================================
# 🔹 Painel do Visitante
# ======================================================
@bp_visitante.route("/")
@bp_visitante.route("/painel")
@login_required
def painel():
    """Painel principal do visitante."""
    if not current_user.has_role("visitante"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar dados do visitante
        cur.execute("""
            SELECT v.*, ac.nome AS academia_nome, ac.aulas_experimentais_permitidas
            FROM visitantes v
            INNER JOIN academias ac ON ac.id = v.id_academia
            WHERE v.usuario_id = %s AND v.ativo = 1
            LIMIT 1
        """, (current_user.id,))
        visitante = cur.fetchone()
        
        if not visitante:
            flash("Visitante não encontrado.", "danger")
            conn.close()
            return redirect(url_for("painel.home"))
        
        # Buscar aulas experimentais realizadas
        cur.execute("""
            SELECT ae.*, t.Nome AS turma_nome, t.DiasHorario
            FROM aulas_experimentais ae
            INNER JOIN turmas t ON t.TurmaID = ae.turma_id
            WHERE ae.visitante_id = %s
            ORDER BY ae.data_aula DESC
            LIMIT 10
        """, (visitante["id"],))
        aulas_realizadas = cur.fetchall()
        
        # Contar total de aulas realizadas
        total_aulas = visitante.get("aulas_experimentais_realizadas", 0)
        limite_aulas = visitante.get("aulas_experimentais_permitidas")
        
    except Exception as e:
        flash(f"Erro ao carregar dados: {e}", "danger")
        visitante = None
        aulas_realizadas = []
        total_aulas = 0
        limite_aulas = None
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "visitante/painel.html",
        visitante=visitante,
        aulas_realizadas=aulas_realizadas,
        total_aulas=total_aulas,
        limite_aulas=limite_aulas,
    )


# ======================================================
# 🔹 Solicitar Aula Experimental
# ======================================================
@bp_visitante.route("/solicitar-aula", methods=["GET", "POST"])
@login_required
def solicitar_aula():
    """Página para visitante solicitar aula experimental."""
    if not current_user.has_role("visitante"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar visitante
        cur.execute("""
            SELECT v.*, ac.nome AS academia_nome, ac.aulas_experimentais_permitidas
            FROM visitantes v
            INNER JOIN academias ac ON ac.id = v.id_academia
            WHERE v.usuario_id = %s AND v.ativo = 1
            LIMIT 1
        """, (current_user.id,))
        visitante = cur.fetchone()
        
        if not visitante:
            flash("Visitante não encontrado.", "danger")
            conn.close()
            return redirect(url_for("visitante.painel"))
        
        id_academia = visitante["id_academia"]
        data_nascimento = visitante.get("data_nascimento")
        idade = _calcular_idade(data_nascimento)
        
        # Verificar limite de aulas
        limite_aulas = visitante.get("aulas_experimentais_permitidas")
        aulas_realizadas = visitante.get("aulas_experimentais_realizadas", 0)
        
        if limite_aulas and aulas_realizadas >= limite_aulas:
            flash(f"Você já realizou todas as {limite_aulas} aulas experimentais permitidas.", "warning")
            conn.close()
            return redirect(url_for("visitante.painel"))
        
        # Buscar turmas disponíveis filtradas por idade
        if idade is not None:
            cur.execute("""
                SELECT t.TurmaID, t.Nome, t.DiasHorario, t.IdadeMin, t.IdadeMax,
                       t.Capacidade, t.controla_limite,
                       COUNT(DISTINCT at.aluno_id) AS alunos_matriculados,
                       COUNT(DISTINCT vt.visitante_id) AS visitantes_inscritos
                FROM turmas t
                LEFT JOIN aluno_turmas at ON at.TurmaID = t.TurmaID
                LEFT JOIN visitante_turmas vt ON vt.turma_id = t.TurmaID
                WHERE t.id_academia = %s
                  AND (t.IdadeMin IS NULL OR %s >= t.IdadeMin)
                  AND (t.IdadeMax IS NULL OR %s <= t.IdadeMax)
                GROUP BY t.TurmaID, t.Nome, t.DiasHorario, t.IdadeMin, t.IdadeMax, t.Capacidade, t.controla_limite
                HAVING (t.Capacidade IS NULL OR t.Capacidade = 0 OR 
                       (alunos_matriculados + visitantes_inscritos) < t.Capacidade)
                ORDER BY t.Nome
            """, (id_academia, idade, idade))
        else:
            cur.execute("""
                SELECT t.TurmaID, t.Nome, t.DiasHorario, t.IdadeMin, t.IdadeMax,
                       t.Capacidade, t.controla_limite,
                       COUNT(DISTINCT at.aluno_id) AS alunos_matriculados,
                       COUNT(DISTINCT vt.visitante_id) AS visitantes_inscritos
                FROM turmas t
                LEFT JOIN aluno_turmas at ON at.TurmaID = t.TurmaID
                LEFT JOIN visitante_turmas vt ON vt.turma_id = t.TurmaID
                WHERE t.id_academia = %s
                GROUP BY t.TurmaID, t.Nome, t.DiasHorario, t.IdadeMin, t.IdadeMax, t.Capacidade, t.controla_limite
                HAVING (t.Capacidade IS NULL OR t.Capacidade = 0 OR 
                       (alunos_matriculados + visitantes_inscritos) < t.Capacidade)
                ORDER BY t.Nome
            """, (id_academia,))
        
        turmas_disponiveis = cur.fetchall()
        
        if request.method == "POST":
            turma_id = request.form.get("turma_id", type=int)
            data_aula = request.form.get("data_aula")
            
            if not turma_id or not data_aula:
                flash("Selecione uma turma e uma data.", "danger")
                conn.close()
                return render_template(
                    "visitante/solicitar_aula.html",
                    visitante=visitante,
                    turmas_disponiveis=turmas_disponiveis,
                    idade=idade,
                )
            
            # Validar data (não pode ser no passado)
            try:
                data_aula_obj = datetime.strptime(data_aula, "%Y-%m-%d").date()
                if data_aula_obj < date.today():
                    flash("Não é possível solicitar aula para uma data passada.", "danger")
                    conn.close()
                    return render_template(
                        "visitante/solicitar_aula.html",
                        visitante=visitante,
                        turmas_disponiveis=turmas_disponiveis,
                        idade=idade,
                    )
            except Exception:
                flash("Data inválida.", "danger")
                conn.close()
                return render_template(
                    "visitante/solicitar_aula.html",
                    visitante=visitante,
                    turmas_disponiveis=turmas_disponiveis,
                    idade=idade,
                )
            
            # Verificar se já tem aula nesta turma nesta data
            cur.execute("""
                SELECT id FROM aulas_experimentais
                WHERE visitante_id = %s AND turma_id = %s AND data_aula = %s
            """, (visitante["id"], turma_id, data_aula))
            if cur.fetchone():
                flash("Você já tem uma aula experimental agendada para esta turma nesta data.", "warning")
                conn.close()
                return render_template(
                    "visitante/solicitar_aula.html",
                    visitante=visitante,
                    turmas_disponiveis=turmas_disponiveis,
                    idade=idade,
                )
            
            # Verificar limite de aulas
            if limite_aulas and aulas_realizadas >= limite_aulas:
                flash(f"Você já realizou todas as {limite_aulas} aulas experimentais permitidas.", "warning")
                conn.close()
                return redirect(url_for("visitante.painel"))
            
            # Registrar aula experimental
            cur.execute("""
                INSERT INTO aulas_experimentais (visitante_id, turma_id, data_aula, presente, registrado_por)
                VALUES (%s, %s, %s, 0, %s)
            """, (visitante["id"], turma_id, data_aula, current_user.id))
            
            # Vincular visitante à turma
            cur.execute("""
                INSERT IGNORE INTO visitante_turmas (visitante_id, turma_id, data_inscricao)
                VALUES (%s, %s, %s)
            """, (visitante["id"], turma_id, date.today()))
            
            conn.commit()
            flash("Aula experimental solicitada com sucesso! Você aparecerá na chamada no dia agendado.", "success")
            conn.close()
            return redirect(url_for("visitante.minhas_aulas"))
        
    except Exception as e:
        flash(f"Erro: {e}", "danger")
        turmas_disponiveis = []
        idade = None
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "visitante/solicitar_aula.html",
        visitante=visitante,
        turmas_disponiveis=turmas_disponiveis,
        idade=idade,
    )


# ======================================================
# 🔹 Minhas Aulas Experimentais
# ======================================================
@bp_visitante.route("/minhas-aulas")
@login_required
def minhas_aulas():
    """Lista aulas experimentais do visitante."""
    if not current_user.has_role("visitante"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar visitante
        cur.execute("""
            SELECT id FROM visitantes WHERE usuario_id = %s AND ativo = 1 LIMIT 1
        """, (current_user.id,))
        visitante = cur.fetchone()
        
        if not visitante:
            flash("Visitante não encontrado.", "danger")
            conn.close()
            return redirect(url_for("visitante.painel"))
        
        # Buscar aulas experimentais
        cur.execute("""
            SELECT ae.*, t.Nome AS turma_nome, t.DiasHorario,
                   CASE 
                       WHEN ae.data_aula < CURDATE() THEN 'realizada'
                       WHEN ae.data_aula = CURDATE() THEN 'hoje'
                       ELSE 'agendada'
                   END AS status_aula
            FROM aulas_experimentais ae
            INNER JOIN turmas t ON t.TurmaID = ae.turma_id
            WHERE ae.visitante_id = %s
            ORDER BY ae.data_aula DESC
        """, (visitante["id"],))
        aulas = cur.fetchall()
        
    except Exception as e:
        flash(f"Erro ao carregar aulas: {e}", "danger")
        aulas = []
    finally:
        cur.close()
        conn.close()
    
    return render_template("visitante/minhas_aulas.html", aulas=aulas)


# ======================================================
# 🔹 Cancelar Aula Experimental
# ======================================================
@bp_visitante.route("/cancelar-aula/<int:aula_id>", methods=["POST"])
@login_required
def cancelar_aula(aula_id):
    """Cancela uma aula experimental agendada."""
    if not current_user.has_role("visitante"):
        return jsonify({"ok": False, "msg": "Acesso negado"}), 403
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Verificar se a aula pertence ao visitante
        cur.execute("""
            SELECT ae.*, v.usuario_id
            FROM aulas_experimentais ae
            INNER JOIN visitantes v ON v.id = ae.visitante_id
            WHERE ae.id = %s AND v.usuario_id = %s
        """, (aula_id, current_user.id))
        aula = cur.fetchone()
        
        if not aula:
            conn.close()
            return jsonify({"ok": False, "msg": "Aula não encontrada"}), 404
        
        # Só pode cancelar se ainda não foi realizada (data futura)
        if aula["data_aula"] < date.today():
            conn.close()
            return jsonify({"ok": False, "msg": "Não é possível cancelar uma aula já realizada"}), 400
        
        # Deletar aula experimental
        cur.execute("DELETE FROM aulas_experimentais WHERE id = %s", (aula_id,))
        
        # Atualizar contador de aulas realizadas (se necessário)
        cur.execute("""
            UPDATE visitantes 
            SET aulas_experimentais_realizadas = (
                SELECT COUNT(*) FROM aulas_experimentais 
                WHERE visitante_id = %s AND presente = 1 AND data_aula < CURDATE()
            )
            WHERE id = %s
        """, (aula["visitante_id"], aula["visitante_id"]))
        
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "msg": "Aula cancelada com sucesso"})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "msg": f"Erro: {e}"}), 500
