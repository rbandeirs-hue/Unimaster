# ============================================================
# 🔥 JUDO ACADEMY — APP PRINCIPAL (100% RBAC por Roles)
# ============================================================

from flask import Flask, redirect, url_for
from flask_login import LoginManager
from config import get_db_connection

# ============================
# 🔹 Blueprints
# ============================
from blueprints.auth.routes import auth_bp
from blueprints.painel.routes import painel_bp
from blueprints.federacao.routes import federacao_bp
from blueprints.associacao.routes import associacao_bp
from blueprints.academia.routes import academia_bp
from blueprints.aluno import bp_alunos, bp_painel_aluno
from blueprints.cadastros import cadastros_bp
from blueprints.usuarios.routes import bp_usuarios
from blueprints.turmas.routes import bp_turmas
from blueprints.presencas.presencas import bp_presencas
from blueprints.professores.routes import bp_professores
from blueprints.configuracoes import bp_configuracoes
from blueprints.financeiro.routes import bp_financeiro

# 🔹 Modelo de Usuário (flask-login)
from blueprints.auth.user_model import Usuario


# ============================================================
# 🔹 Inicialização da aplicação
# ============================================================
app = Flask(__name__)
app.secret_key = "chave-secreta-super-segura"


# ============================================================
# 🔹 Configuração do Login
# ============================================================
login_manager = LoginManager(app)
login_manager.login_view = "auth.login"


# ============================================================
# 🔹 CARREGAR USUÁRIO LOGADO (RBAC)
# ============================================================
@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # 1️⃣ Busca o usuário
    cur.execute("""
        SELECT *
        FROM usuarios
        WHERE id = %s
    """, (user_id,))
    user_row = cur.fetchone()

    if not user_row:
        cur.close()
        conn.close()
        return None

    # 2️⃣ Carrega roles do usuário (tabela roles_usuario)
    roles = Usuario.carregar_roles(user_row["id"])

    # 3️⃣ Carrega permissões derivadas das roles
    permissoes = Usuario.carregar_permissoes(user_row["id"])

    # 4️⃣ Carrega menus liberados (se a tabela existir)
    try:
        menus = Usuario.carregar_menus(user_row["id"])
    except Exception:
        menus = []

    cur.close()
    conn.close()

    # 5️⃣ Retorna objeto completo para flask-login
    return Usuario(
    id=user_row["id"],
    nome=user_row["nome"],
    email=user_row["email"],
    senha=user_row["senha"],
    id_federacao=user_row.get("id_federacao"),
    id_associacao=user_row.get("id_associacao"),
    id_academia=user_row.get("id_academia"),
    roles=roles,
    permissoes=permissoes,
    menus=menus
)
    


# ============================================================
# 🔹 Context processor: múltiplos modos (para botão Trocar modo)
# ============================================================
@app.context_processor
def injetar_modos_e_contexto():
    from datetime import datetime
    from flask_login import current_user
    from flask import session
    from utils.contexto_logo import get_contexto_logo_e_nome

    def tem_multiplos_modos():
        if not hasattr(current_user, 'is_authenticated') or not current_user.is_authenticated:
            return False
        from blueprints.painel.routes import _modos_disponiveis
        modos = _modos_disponiveis()
        return len(modos) > 1

    logo_url, contexto_nome, _ = get_contexto_logo_e_nome(current_user, session)
    return dict(
        tem_multiplos_modos=tem_multiplos_modos,
        contexto_logo_url=logo_url,
        contexto_nome=contexto_nome,
        current_year=datetime.now().year,
    )


# ============================================================
# 🔹 Rota padrão
# ============================================================
@app.route("/")
def index():
    return redirect(url_for("auth.login"))


# ============================================================
# 🔹 Registro dos Blueprints
# ============================================================
app.register_blueprint(auth_bp)         # Login / Logout
app.register_blueprint(painel_bp)       # Painel principal
app.register_blueprint(federacao_bp)    # Gestão da Federação
app.register_blueprint(associacao_bp)   # Gestão da Associação
app.register_blueprint(academia_bp)     # Gestão da Academia

app.register_blueprint(bp_alunos)       # CRUD alunos
app.register_blueprint(bp_painel_aluno) # Painel do aluno

app.register_blueprint(cadastros_bp)    # Hub de Cadastros
app.register_blueprint(bp_usuarios)     # Usuários (lista/cadastro/editar/excluir)
app.register_blueprint(bp_turmas)       # Turmas (CRUD)
app.register_blueprint(bp_presencas)    # Presenças (registro, ata, histórico)
app.register_blueprint(bp_professores)  # Professores (CRUD por academia)
app.register_blueprint(bp_configuracoes)  # Configurações (admin: modalidades)
app.register_blueprint(bp_financeiro)   # Financeiro (dashboard, descontos, mensalidades, receitas, despesas)


# ============================================================
# 🔹 Execução
# ============================================================
if __name__ == "__main__":
    app.run(debug=True)
