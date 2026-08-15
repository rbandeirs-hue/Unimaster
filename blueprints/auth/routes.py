# blueprints/auth/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from config import get_db_connection
from .user_model import Usuario
from utils.contexto_logo import buscar_logo_url
from utils.email_utils import enviar_email_redefinicao_senha
from datetime import datetime, timedelta
import secrets
import re


def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _valida_cpf(cpf: str) -> bool:
    """Valida CPF brasileiro (11 dígitos, dígitos verificadores)."""
    cpf = _so_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(cpf[j]) * ((i + 1) - j) for j in range(i))
        d = (soma * 10) % 11
        if d == 10:
            d = 0
        if d != int(cpf[i]):
            return False
    return True

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

_MAX_TENTATIVAS = 5        # bloqueio após N falhas consecutivas
_BLOQUEIO_MINUTOS = 15     # duração do bloqueio


def _chave_brute(ip: str) -> str:
    return f"_bf_{ip}"


def _verificar_bloqueio(ip: str) -> tuple[bool, int]:
    """Retorna (bloqueado, segundos_restantes)."""
    chave = _chave_brute(ip)
    dados = session.get(chave)
    if not dados:
        return False, 0
    tentativas = dados.get("n", 0)
    bloqueado_ate = dados.get("ate")
    if bloqueado_ate:
        ate = datetime.fromisoformat(bloqueado_ate)
        restante = int((ate - datetime.now()).total_seconds())
        if restante > 0:
            return True, restante
        # Bloqueio expirou — limpar
        session.pop(chave, None)
    return False, 0


def _registrar_falha(ip: str):
    chave = _chave_brute(ip)
    dados = session.get(chave, {"n": 0, "ate": None})
    dados["n"] = dados.get("n", 0) + 1
    if dados["n"] >= _MAX_TENTATIVAS:
        dados["ate"] = (datetime.now() + timedelta(minutes=_BLOQUEIO_MINUTOS)).isoformat()
    session[chave] = dados
    session.modified = True


def _limpar_falhas(ip: str):
    session.pop(_chave_brute(ip), None)
    session.modified = True


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
        ip = request.remote_addr or "unknown"
        bloqueado, restante = _verificar_bloqueio(ip)
        if bloqueado:
            minutos = max(1, restante // 60)
            flash(f"Muitas tentativas incorretas. Aguarde {minutos} minuto(s) antes de tentar novamente.", "danger")
            return render_template("login.html")

        identificador = (request.form.get("cpf") or request.form.get("email") or "").strip()
        senha = request.form.get("senha")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # --------------------------------------------
        # 1️⃣ Buscar usuário por CPF (preferencial) ou e-mail (fallback)
        # --------------------------------------------
        cpf_digitos = _so_digitos(identificador)
        usuario = None
        if len(cpf_digitos) == 11:
            cur.execute("""
                SELECT id, nome, email, cpf, senha,
                       id_federacao, id_associacao, id_academia,
                       COALESCE(ativo, 1) AS ativo, foto
                FROM usuarios
                WHERE cpf = %s
            """, (cpf_digitos,))
            usuario = cur.fetchone()

        # Fallback por e-mail SOMENTE se a conta ainda não tem CPF cadastrado
        # (primeiro acesso para quem não tinha CPF antes da troca de modo).
        if not usuario and "@" in identificador:
            cur.execute("""
                SELECT id, nome, email, cpf, senha,
                       id_federacao, id_associacao, id_academia,
                       COALESCE(ativo, 1) AS ativo, foto
                FROM usuarios
                WHERE email = %s AND cpf IS NULL
            """, (identificador,))
            usuario = cur.fetchone()

        if not usuario:
            _registrar_falha(ip)
            flash("CPF ou senha incorretos!", "danger")
            cur.close()
            conn.close()
            return render_template("login.html")

        if not usuario.get("ativo", 1):
            flash("Conta inativa. Contate o administrador.", "warning")
            cur.close()
            conn.close()
            return render_template("login.html")

        # --------------------------------------------
        # 2️⃣ Validar senha
        # --------------------------------------------
        if not check_password_hash(usuario["senha"], senha):
            _registrar_falha(ip)
            flash("CPF ou senha incorretos!", "danger")
            cur.close()
            conn.close()
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
            foto=usuario.get("foto"),
            cpf=usuario.get("cpf")
        )

        # --------------------------------------------
        # 4️⃣ Logar usuário
        # --------------------------------------------
        _limpar_falhas(ip)
        login_user(user_obj)

        # Se entrou pelo fallback de e-mail (sem CPF), forçar cadastro de CPF
        if not usuario.get("cpf"):
            flash("Para continuar, cadastre seu CPF. Ele será o seu novo login.", "info")
            return redirect(url_for("auth.cadastrar_cpf"))

        return redirect(url_for("painel.home"))

    return render_template("login.html")


# =======================================================
# 🔹 CADASTRO OBRIGATÓRIO DE CPF (primeiro acesso após troca)
# =======================================================
@auth_bp.route("/cadastrar-cpf", methods=["GET", "POST"])
@login_required
def cadastrar_cpf():
    # Se já tem CPF cadastrado, não tem por que estar aqui
    if getattr(current_user, "cpf", None):
        return redirect(url_for("painel.home"))

    if request.method == "POST":
        cpf_raw = request.form.get("cpf", "")
        cpf = _so_digitos(cpf_raw)

        if not _valida_cpf(cpf):
            flash("CPF inválido. Verifique e tente novamente.", "danger")
            return render_template("auth/cadastrar_cpf.html")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT id FROM usuarios WHERE cpf = %s AND id <> %s", (cpf, current_user.id))
            if cur.fetchone():
                flash("Este CPF já está em uso por outro usuário. Contate o administrador.", "danger")
                return render_template("auth/cadastrar_cpf.html")

            cur.execute("UPDATE usuarios SET cpf = %s WHERE id = %s", (cpf, current_user.id))
            conn.commit()
            current_user.cpf = cpf
            flash("CPF cadastrado com sucesso! A partir de agora utilize-o para entrar.", "success")
            return redirect(url_for("painel.home"))
        except Exception as e:
            conn.rollback()
            current_app.logger.error(f"Erro ao cadastrar CPF: {e}", exc_info=True)
            flash("Erro ao salvar CPF. Tente novamente.", "danger")
        finally:
            cur.close()
            conn.close()

    return render_template("auth/cadastrar_cpf.html")


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
        # Limitar a 3 solicitações por IP a cada 15 minutos
        ip = request.remote_addr or "unknown"
        chave_reset = f"_rst_{ip}"
        dados_reset = session.get(chave_reset, {"n": 0, "desde": None})
        desde = datetime.fromisoformat(dados_reset["desde"]) if dados_reset.get("desde") else datetime.now()
        if datetime.now() - desde > timedelta(minutes=15):
            dados_reset = {"n": 0, "desde": datetime.now().isoformat()}
        if dados_reset.get("n", 0) >= 3:
            flash("Muitas solicitações. Aguarde 15 minutos antes de tentar novamente.", "warning")
            return render_template("auth/esqueci_senha.html")
        dados_reset["n"] = dados_reset.get("n", 0) + 1
        dados_reset.setdefault("desde", datetime.now().isoformat())
        session[chave_reset] = dados_reset
        session.modified = True

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

