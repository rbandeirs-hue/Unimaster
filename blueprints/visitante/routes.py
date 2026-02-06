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


def _criar_visitante_automatico(conn, cur):
    """Cria registro de visitante automaticamente se não existir."""
    try:
        # Verificar se já existe visitante (ativo ou inativo)
        cur.execute("SELECT id FROM visitantes WHERE usuario_id = %s LIMIT 1", (current_user.id,))
        visitante_existente = cur.fetchone()
        if visitante_existente:
            # Se existe mas está inativo, reativar
            cur.execute("UPDATE visitantes SET ativo = 1 WHERE usuario_id = %s", (current_user.id,))
            conn.commit()
            return True
        
        # Buscar academia vinculada ao usuário
        academia_id = None
        
        # Primeiro: verificar usuarios_academias (prioridade)
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id LIMIT 1", (current_user.id,))
        acad_row = cur.fetchone()
        if acad_row:
            academia_id = acad_row["academia_id"]
        elif getattr(current_user, "id_academia", None):
            academia_id = current_user.id_academia
        
        if not academia_id:
            return False  # Não há academia vinculada
        
        # Verificar se a academia existe
        cur.execute("SELECT id, aulas_experimentais_permitidas FROM academias WHERE id = %s", (academia_id,))
        acad_config = cur.fetchone()
        if not acad_config:
            return False  # Academia não existe
        
        limite_aulas = acad_config.get("aulas_experimentais_permitidas")
        
        # Buscar dados do usuário
        cur.execute("SELECT nome, email FROM usuarios WHERE id = %s", (current_user.id,))
        usuario = cur.fetchone()
        
        if not usuario or not usuario.get("nome"):
            return False  # Usuário não encontrado ou sem nome
        
        # Criar registro de visitante
        cur.execute("""
            INSERT INTO visitantes (nome, email, telefone, usuario_id, id_academia, aulas_experimentais_permitidas, ativo)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
        """, (
            usuario.get("nome"),
            usuario.get("email"),
            None,  # telefone pode ser adicionado depois
            current_user.id,
            academia_id,
            limite_aulas,
        ))
        
        conn.commit()
        return True  # Criado com sucesso
    except Exception as e:
        conn.rollback()
        # Log do erro (sem usar print para produção)
        return False


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
        
        # Se não encontrou, tentar criar automaticamente
        if not visitante:
            resultado = _criar_visitante_automatico(conn, cur)
            if resultado:
                # Buscar novamente após criar
                cur.execute("""
                    SELECT v.*, ac.nome AS academia_nome, ac.aulas_experimentais_permitidas
                    FROM visitantes v
                    INNER JOIN academias ac ON ac.id = v.id_academia
                    WHERE v.usuario_id = %s AND v.ativo = 1
                    LIMIT 1
                """, (current_user.id,))
                visitante = cur.fetchone()
            
            if not visitante:
                flash("Visitante não encontrado. Verifique se você está vinculado a uma academia.", "danger")
                cur.close()
                conn.close()
                return redirect(url_for("painel.home"))
        
        # Buscar aulas experimentais realizadas (apenas as que já passaram)
        cur.execute("""
            SELECT ae.*, t.Nome AS turma_nome, t.DiasHorario
            FROM aulas_experimentais ae
            INNER JOIN turmas t ON t.TurmaID = ae.turma_id
            WHERE ae.visitante_id = %s AND ae.data_aula < CURDATE()
            ORDER BY ae.data_aula DESC
            LIMIT 10
        """, (visitante["id"],))
        aulas_realizadas = cur.fetchall()
        
        # Verificar se há aula pendente/agendada
        cur.execute("""
            SELECT id, data_aula FROM aulas_experimentais
            WHERE visitante_id = %s AND data_aula >= CURDATE()
            ORDER BY data_aula ASC
            LIMIT 1
        """, (visitante["id"],))
        aula_pendente = cur.fetchone()
        
        # Contar total de aulas realizadas
        total_aulas = visitante.get("aulas_experimentais_realizadas", 0)
        limite_aulas = visitante.get("aulas_experimentais_permitidas")
        
    except Exception as e:
        flash(f"Erro ao carregar dados: {e}", "danger")
        visitante = None
        aulas_realizadas = []
        total_aulas = 0
        limite_aulas = None
        aula_pendente = None
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "visitante/painel.html",
        visitante=visitante,
        aulas_realizadas=aulas_realizadas,
        total_aulas=total_aulas,
        limite_aulas=limite_aulas,
        aula_pendente=aula_pendente,
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
        
        # Se não encontrou, tentar criar automaticamente
        if not visitante:
            resultado = _criar_visitante_automatico(conn, cur)
            if resultado:
                # Buscar novamente após criar
                cur.execute("""
                    SELECT v.*, ac.nome AS academia_nome, ac.aulas_experimentais_permitidas
                    FROM visitantes v
                    INNER JOIN academias ac ON ac.id = v.id_academia
                    WHERE v.usuario_id = %s AND v.ativo = 1
                    LIMIT 1
                """, (current_user.id,))
                visitante = cur.fetchone()
            
            if not visitante:
                flash("Visitante não encontrado. Verifique se você está vinculado a uma academia.", "danger")
                cur.close()
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
        
        # Verificar se já existe aula pendente/agendada (não concluída)
        # Uma aula está concluída quando a data já passou (data_aula < CURDATE())
        cur.execute("""
            SELECT id, data_aula FROM aulas_experimentais
            WHERE visitante_id = %s AND data_aula >= CURDATE()
            ORDER BY data_aula ASC
            LIMIT 1
        """, (visitante["id"],))
        aula_pendente = cur.fetchone()
        
        if aula_pendente:
            flash(f"Você já possui uma aula experimental agendada para {aula_pendente['data_aula'].strftime('%d/%m/%Y')}. Aguarde a conclusão ou cancele a aula anterior para solicitar uma nova.", "warning")
            conn.close()
            return redirect(url_for("visitante.minhas_aulas"))
        
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
            
            # Verificar se já tem aula pendente/agendada (não concluída)
            # Uma aula está concluída quando a data já passou (data_aula < CURDATE())
            cur.execute("""
                SELECT id, data_aula FROM aulas_experimentais
                WHERE visitante_id = %s AND data_aula >= CURDATE()
                ORDER BY data_aula ASC
                LIMIT 1
            """, (visitante["id"],))
            aula_pendente = cur.fetchone()
            
            if aula_pendente:
                flash(f"Você já possui uma aula experimental agendada para {aula_pendente['data_aula'].strftime('%d/%m/%Y')}. Aguarde a conclusão ou cancele a aula anterior para solicitar uma nova.", "warning")
                conn.close()
                return redirect(url_for("visitante.minhas_aulas"))
            
            # Verificar se já tem aula nesta turma nesta data (duplicação)
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
            
            # Contar total de aulas (passadas e futuras, incluindo esta)
            cur.execute("""
                SELECT COUNT(*) as total FROM aulas_experimentais 
                WHERE visitante_id = %s
            """, (visitante["id"],))
            total_aulas = cur.fetchone().get("total", 0) + 1
            
            # Verificar se ultrapassou limite e precisa pagar diária
            precisa_pagar_diaria = False
            valor_diaria = None
            if limite_aulas and total_aulas > limite_aulas:
                # Buscar valor da diária da academia
                cur.execute("SELECT valor_diaria_visitante FROM academias WHERE id = %s", (id_academia,))
                acad_diaria = cur.fetchone()
                if acad_diaria and acad_diaria.get("valor_diaria_visitante"):
                    precisa_pagar_diaria = True
                    valor_diaria = float(acad_diaria["valor_diaria_visitante"])
            
            # Registrar aula experimental (pendente de aprovação)
            cur.execute("""
                INSERT INTO aulas_experimentais (visitante_id, turma_id, data_aula, presente, registrado_por, aprovado)
                VALUES (%s, %s, %s, 0, %s, 0)
            """, (visitante["id"], turma_id, data_aula, current_user.id))
            aula_id = cur.lastrowid
            
            # Se precisa pagar diária, criar registro de pagamento pendente
            if precisa_pagar_diaria and valor_diaria:
                cur.execute("""
                    INSERT INTO visitante_pagamentos_diaria (visitante_id, aula_experimental_id, valor, status)
                    VALUES (%s, %s, %s, 'pendente')
                """, (visitante["id"], aula_id, valor_diaria))
            
            # Vincular visitante à turma
            cur.execute("""
                INSERT IGNORE INTO visitante_turmas (visitante_id, turma_id, data_inscricao)
                VALUES (%s, %s, %s)
            """, (visitante["id"], turma_id, date.today()))
            
            conn.commit()
            
            if precisa_pagar_diaria:
                flash(f"Aula experimental solicitada! Como você ultrapassou o limite de {limite_aulas} aulas gratuitas, será necessário pagar uma diária de R$ {valor_diaria:.2f}. A solicitação será analisada pela academia.", "warning")
            else:
                flash("Aula experimental solicitada com sucesso! Aguarde a aprovação da academia.", "success")
            
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
        
        # Se não encontrou, tentar criar automaticamente
        if not visitante:
            resultado = _criar_visitante_automatico(conn, cur)
            if resultado:
                # Buscar novamente após criar
                cur.execute("""
                    SELECT id FROM visitantes WHERE usuario_id = %s AND ativo = 1 LIMIT 1
                """, (current_user.id,))
                visitante = cur.fetchone()
            
            if not visitante:
                flash("Visitante não encontrado. Verifique se você está vinculado a uma academia.", "danger")
                cur.close()
                conn.close()
                return redirect(url_for("visitante.painel"))
        
        # Buscar aulas experimentais com contador e informações de pagamento
        cur.execute("""
            SELECT ae.*, t.Nome AS turma_nome, t.DiasHorario,
                   CASE 
                       WHEN ae.data_aula < CURDATE() THEN 'realizada'
                       WHEN ae.data_aula = CURDATE() THEN 'hoje'
                       ELSE 'agendada'
                   END AS status_aula,
                   v.aulas_experimentais_permitidas AS limite_aulas,
                   (SELECT COUNT(*) FROM aulas_experimentais ae2 
                    WHERE ae2.visitante_id = v.id 
                    AND (ae2.data_aula < ae.data_aula OR (ae2.data_aula = ae.data_aula AND ae2.id <= ae.id))) AS numero_aula,
                   vpd.id AS pagamento_id,
                   vpd.valor AS valor_diaria,
                   vpd.status AS status_pagamento,
                   vpd.comprovante AS comprovante_pagamento
            FROM aulas_experimentais ae
            INNER JOIN turmas t ON t.TurmaID = ae.turma_id
            INNER JOIN visitantes v ON v.id = ae.visitante_id
            LEFT JOIN visitante_pagamentos_diaria vpd ON vpd.aula_experimental_id = ae.id
            WHERE ae.visitante_id = %s
            ORDER BY ae.data_aula DESC, ae.id DESC
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
        
        # Só pode cancelar se ainda não foi realizada (data futura ou hoje, mas ainda não marcada como presente/falta)
        # Verificar se a aula já passou e foi marcada
        hoje = date.today()
        if aula["data_aula"] < hoje:
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


# ======================================================
# 🔹 Pagar Diária
# ======================================================
@bp_visitante.route("/pagar-diaria/<int:pagamento_id>", methods=["GET", "POST"])
@login_required
def pagar_diaria(pagamento_id):
    """Página para visitante enviar comprovante de pagamento de diária."""
    if not current_user.has_role("visitante"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar pagamento
        cur.execute("""
            SELECT vpd.*, v.usuario_id, ae.data_aula, t.Nome AS turma_nome
            FROM visitante_pagamentos_diaria vpd
            INNER JOIN visitantes v ON v.id = vpd.visitante_id
            INNER JOIN aulas_experimentais ae ON ae.id = vpd.aula_experimental_id
            INNER JOIN turmas t ON t.TurmaID = ae.turma_id
            WHERE vpd.id = %s AND v.usuario_id = %s
        """, (pagamento_id, current_user.id))
        pagamento = cur.fetchone()
        
        if not pagamento:
            flash("Pagamento não encontrado.", "danger")
            conn.close()
            return redirect(url_for("visitante.minhas_aulas"))
        
        if pagamento["status"] != "pendente":
            flash("Este pagamento já foi processado.", "warning")
            conn.close()
            return redirect(url_for("visitante.minhas_aulas"))
        
        if request.method == "POST":
            # Upload de comprovante
            comprovante = None
            if "comprovante" in request.files:
                file = request.files["comprovante"]
                if file and file.filename:
                    upload_dir = os.path.join("static", "uploads", "comprovantes")
                    os.makedirs(upload_dir, exist_ok=True)
                    filename = f"diaria_{pagamento_id}_{uuid.uuid4().hex[:8]}.{file.filename.rsplit('.', 1)[1].lower()}"
                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    comprovante = f"uploads/comprovantes/{filename}"
            
            observacoes = request.form.get("observacoes", "").strip() or None
            
            # Atualizar pagamento
            cur.execute("""
                UPDATE visitante_pagamentos_diaria 
                SET comprovante = %s, observacoes = %s, status = 'pago', pagamento_informado_em = NOW()
                WHERE id = %s
            """, (comprovante, observacoes, pagamento_id))
            
            conn.commit()
            flash("Comprovante enviado com sucesso! Aguarde a confirmação da academia.", "success")
            conn.close()
            return redirect(url_for("visitante.minhas_aulas"))
        
    except Exception as e:
        flash(f"Erro: {e}", "danger")
    finally:
        cur.close()
        conn.close()
    
    return render_template("visitante/pagar_diaria.html", pagamento=pagamento)


# ======================================================
# 🔹 Solicitar Mensalidade
# ======================================================
@bp_visitante.route("/solicitar-mensalidade", methods=["GET", "POST"])
@login_required
def solicitar_mensalidade():
    """Página para visitante realizar matrícula e ser promovido a aluno."""
    if not current_user.has_role("visitante"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar visitante
        cur.execute("""
            SELECT v.*, ac.nome AS academia_nome
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
        
        # Verificar se já tem solicitação pendente
        cur.execute("""
            SELECT id FROM visitante_solicitacoes_mensalidade 
            WHERE visitante_id = %s AND status = 'pendente'
        """, (visitante["id"],))
        if cur.fetchone():
            flash("Você já possui uma matrícula pendente.", "warning")
            conn.close()
            return redirect(url_for("visitante.painel"))
        
        # Buscar mensalidades disponíveis da academia
        cur.execute("""
            SELECT id, nome, descricao, valor 
            FROM mensalidades 
            WHERE id_academia = %s AND ativo = 1
            ORDER BY valor ASC
        """, (visitante["id_academia"],))
        mensalidades = cur.fetchall()
        
        if request.method == "POST":
            mensalidade_id = request.form.get("mensalidade_id", type=int)
            observacoes = request.form.get("observacoes", "").strip() or None
            
            if not mensalidade_id:
                flash("Selecione uma mensalidade.", "danger")
                conn.close()
                return render_template("visitante/solicitar_mensalidade.html", 
                                      visitante=visitante, mensalidades=mensalidades)
            
            # Criar solicitação
            cur.execute("""
                INSERT INTO visitante_solicitacoes_mensalidade (visitante_id, mensalidade_id, observacoes)
                VALUES (%s, %s, %s)
            """, (visitante["id"], mensalidade_id, observacoes))
            
            conn.commit()
            flash("Matrícula realizada com sucesso! Aguarde a aprovação da academia.", "success")
            conn.close()
            return redirect(url_for("visitante.painel"))
        
    except Exception as e:
        flash(f"Erro: {e}", "danger")
        mensalidades = []
    finally:
        cur.close()
        conn.close()
    
    return render_template("visitante/solicitar_mensalidade.html", 
                         visitante=visitante, mensalidades=mensalidades)
