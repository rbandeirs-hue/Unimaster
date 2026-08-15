from flask import Blueprint, render_template
from flask_login import login_required, current_user
from config import get_db_connection
from werkzeug.security import generate_password_hash

bp_admin = Blueprint('admin', __name__)

# ======================================================
# 🔹 Criar primeiro admin (executado 1x)
# ======================================================
def criar_primeiro_admin():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Verifica se há usuários cadastrados
    cursor.execute("SELECT COUNT(*) AS total FROM usuarios")
    total = cursor.fetchone()['total']

    if total == 0:
        # Cria tipos de usuário se não existirem
        cursor.execute("SELECT COUNT(*) AS c FROM tipo_usuario")
        tipo_count = cursor.fetchone()['c']
        if tipo_count == 0:
            cursor.executemany("""
                INSERT INTO tipo_usuario (id, nome)
                VALUES (%s, %s)
            """, [
                (1, 'Aluno'),
                (2, 'Professor'),
                (3, 'Supervisor'),
                (4, 'Admin'),
            ])
            db.commit()

        # Cria usuário administrador
        import os
        nome = "Administrador"
        email = os.environ.get("ADMIN_SEED_EMAIL", "admin@judo.com")
        senha = os.environ.get("ADMIN_SEED_PASSWORD", "admin123")
        hashed = generate_password_hash(senha)

        cursor.execute("""
            INSERT INTO usuarios (nome, email, senha, perfil, tipo_id)
            VALUES (%s, %s, %s, 'Admin', 4)
        """, (nome, email, hashed))
        db.commit()

        print("Primeiro admin criado com sucesso:")
        print(f"   Email: {email}")
        print("   Senha: (definida via ADMIN_SEED_PASSWORD ou padrao)")

    db.close()


# Executa ao carregar o módulo
criar_primeiro_admin()


# ======================================================
# 🔹 Dashboard (área administrativa)
# ======================================================
@bp_admin.route('/dashboard')
@login_required
def dashboard():
    """
    Página principal do painel administrativo.
    Exibe o nome e o perfil do usuário logado.
    """
    return render_template('dashboard.html', nome=current_user.nome, perfil=current_user.perfil)
