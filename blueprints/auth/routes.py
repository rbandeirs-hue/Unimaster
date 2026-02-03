# blueprints/auth/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from config import get_db_connection
from .user_model import Usuario
from utils.contexto_logo import buscar_logo_url
from utils.email_utils import enviar_email_redefinicao_senha
from datetime import datetime, timedelta
import secrets

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _get_login_logo():
    """Retorna URL da logo para a tela de login (primeira federação ou academia)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id FROM federacoes ORDER BY nome LIMIT 1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return buscar_logo_url("federacao", row["id"])
    except Exception:
        pass
    return None


# =======================================================
# 🔹 LOGIN (versão RBAC pura)
# =======================================================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # --------------------------------------------
        # 1️⃣ Buscar usuário (SEM tipo_usuario)
        # --------------------------------------------
        cur.execute("""
            SELECT 
                id, nome, email, senha,
                id_federacao, id_associacao, id_academia,
                COALESCE(ativo, 1) AS ativo,
                foto
            FROM usuarios
            WHERE email = %s
        """, (email,))

        usuario = cur.fetchone()

        if not usuario:
            flash("E-mail ou senha incorretos!", "danger")
            return render_template("login.html")

        if not usuario.get("ativo", 1):
            flash("Conta inativa. Contate o administrador.", "warning")
            return render_template("login.html")

        # --------------------------------------------
        # 2️⃣ Validar senha
        # --------------------------------------------
        if not check_password_hash(usuario["senha"], senha):
            flash("E-mail ou senha incorretos!", "danger")
            return render_template("login.html")

        cur.close()
        conn.close()

        # --------------------------------------------
        # 3️⃣ Criar objeto usuário com RBAC real
        # --------------------------------------------
        user_obj = Usuario(
            id=usuario["id"],
            nome=usuario["nome"],
            email=usuario["email"],
            senha=usuario["senha"],
            id_federacao=usuario.get("id_federacao"),
            id_associacao=usuario.get("id_associacao"),
            id_academia=usuario.get("id_academia"),
            roles=Usuario.carregar_roles(usuario["id"]),
            permissoes=Usuario.carregar_permissoes(usuario["id"]),
            menus=Usuario.carregar_menus(usuario["id"]),
            foto=usuario.get("foto")
        )

        # --------------------------------------------
        # 4️⃣ Logar usuário
        # --------------------------------------------
        login_user(user_obj)

        return redirect(url_for("painel.home"))

    return render_template("login.html")


# =======================================================
# 🔹 LOGOUT
# =======================================================
@auth_bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# =======================================================
# 🔹 ESQUECI MINHA SENHA - Solicitar redefinição
# =======================================================
@auth_bp.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    """Página para solicitar redefinição de senha."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        
        if not email:
            flash("Por favor, informe seu e-mail.", "danger")
            return render_template("auth/esqueci_senha.html")
        
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        
        try:
            # Buscar usuário pelo email
            cur.execute("""
                SELECT id, nome, email, COALESCE(ativo, 1) AS ativo
                FROM usuarios
                WHERE email = %s
            """, (email,))
            
            usuario = cur.fetchone()
            
            if not usuario:
                # Por segurança, não revelar se o email existe ou não
                flash("Se o e-mail estiver cadastrado, você receberá um link de redefinição de senha.", "info")
                cur.close()
                conn.close()
                return render_template("auth/esqueci_senha.html")
            
            if not usuario.get("ativo", 1):
                flash("Conta inativa. Contate o administrador.", "warning")
                cur.close()
                conn.close()
                return render_template("auth/esqueci_senha.html")
            
            # Gerar token seguro
            token = secrets.token_urlsafe(32)
            expires_at = datetime.now() + timedelta(hours=1)
            
            # Invalidar tokens anteriores não utilizados
            cur.execute("""
                UPDATE password_reset_tokens
                SET used = 1
                WHERE usuario_id = %s AND used = 0
            """, (usuario["id"],))
            
            # Inserir novo token
            cur.execute("""
                INSERT INTO password_reset_tokens (usuario_id, token, expires_at)
                VALUES (%s, %s, %s)
            """, (usuario["id"], token, expires_at))
            
            conn.commit()
            
            # Enviar email
            base_url = request.url_root.rstrip("/")
            email_enviado = enviar_email_redefinicao_senha(
                email_destino=usuario["email"],
                nome_usuario=usuario["nome"],
                token=token,
                base_url=base_url
            )
            
            if email_enviado:
                flash("Link de redefinição de senha enviado para seu e-mail!", "success")
            else:
                flash("Erro ao enviar email. Verifique as configurações do servidor.", "warning")
                current_app.logger.error(f"Falha ao enviar email para {email}")
            
        except Exception as e:
            conn.rollback()
            current_app.logger.error(f"Erro ao processar solicitação de redefinição de senha: {e}", exc_info=True)
            flash("Erro ao processar solicitação. Tente novamente mais tarde.", "danger")
        finally:
            cur.close()
            conn.close()
        
        return render_template("auth/esqueci_senha.html")
    
    return render_template("auth/esqueci_senha.html")


# =======================================================
# 🔹 REDEFINIR SENHA - Com token
# =======================================================
@auth_bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    """Página para redefinir senha usando o token."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar token válido
        cur.execute("""
            SELECT prt.*, u.id AS usuario_id, u.nome, u.email
            FROM password_reset_tokens prt
            INNER JOIN usuarios u ON u.id = prt.usuario_id
            WHERE prt.token = %s 
            AND prt.used = 0
            AND prt.expires_at > NOW()
        """, (token,))
        
        token_data = cur.fetchone()
        
        if not token_data:
            flash("Link inválido ou expirado. Solicite uma nova redefinição de senha.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("auth.esqueci_senha"))
        
        if request.method == "POST":
            senha = request.form.get("senha", "").strip()
            confirmar_senha = request.form.get("confirmar_senha", "").strip()
            
            if not senha or len(senha) < 6:
                flash("A senha deve ter pelo menos 6 caracteres.", "danger")
                return render_template("auth/redefinir_senha.html", token=token, usuario_nome=token_data["nome"])
            
            if senha != confirmar_senha:
                flash("As senhas não coincidem.", "danger")
                return render_template("auth/redefinir_senha.html", token=token, usuario_nome=token_data["nome"])
            
            # Atualizar senha
            senha_hash = generate_password_hash(senha)
            cur.execute("""
                UPDATE usuarios
                SET senha = %s
                WHERE id = %s
            """, (senha_hash, token_data["usuario_id"]))
            
            # Marcar token como usado
            cur.execute("""
                UPDATE password_reset_tokens
                SET used = 1
                WHERE id = %s
            """, (token_data["id"],))
            
            conn.commit()
            
            flash("Senha redefinida com sucesso! Você já pode fazer login.", "success")
            cur.close()
            conn.close()
            return redirect(url_for("auth.login"))
        
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao redefinir senha: {e}", exc_info=True)
        flash("Erro ao processar redefinição de senha. Tente novamente.", "danger")
    finally:
        cur.close()
        conn.close()
    
    return render_template("auth/redefinir_senha.html", token=token, usuario_nome=token_data.get("nome", ""))

