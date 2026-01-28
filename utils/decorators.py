# ======================================================
# utils/decorators.py (VERSÃO RBAC)
# ======================================================

from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user
from config import get_db_connection


# ======================================================
# 🔹 Decorador baseado em ROLE
# ======================================================
def role_required(*roles):
    """
    Exige que o usuário tenha pelo menos um dos roles passados.
    Exemplo:
        @role_required("gestor_academia", "professor")
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            if not current_user.is_authenticated:
                flash("Faça login primeiro.", "warning")
                return redirect(url_for("auth.login"))

            if not any(current_user.has_role(r) for r in roles):
                flash("Acesso negado.", "danger")
                return redirect(url_for("painel.home"))

            return func(*args, **kwargs)
        return wrapper
    return decorator


# ======================================================
# 🔹 Decorador baseado em PERMISSÃO
# ======================================================
def permission_required(*permissions):
    """
    Exige que o usuário tenha uma ou mais permissões específicas.
    Exemplo:
        @permission_required("editar_aluno")
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            if not current_user.is_authenticated:
                flash("Faça login para continuar.", "warning")
                return redirect(url_for("auth.login"))

            if not any(current_user.has_permission(p) for p in permissions):
                flash("Você não tem permissão para isso.", "danger")
                return redirect(url_for("painel.home"))

            return func(*args, **kwargs)

        return wrapper
    return decorator


# ======================================================
# 🔹 Decorador: Acesso restrito por hierarquia
# ======================================================
def aluno_access(permitir_edicao=False):
    """
    Controle de acesso baseado em hierarquia:
      - Federação → vê todos (não edita)
      - Associação → vê alunos das suas academias
      - Academia → vê/edita alunos da própria academia
      - Aluno → vê/edita apenas seu perfil
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            aluno_id = kwargs.get("aluno_id")
            if not aluno_id:
                flash("Aluno não informado.", "warning")
                return redirect(url_for("painel.home"))

            # Buscar aluno + hierarquia
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)

            cur.execute("""
                SELECT 
                    a.id, a.usuario_id, a.id_academia,
                    ac.id_associacao, s.id_federacao
                FROM alunos a
                JOIN academias ac ON ac.id = a.id_academia
                JOIN associacoes s ON s.id = ac.id_associacao
                WHERE a.id = %s
            """, (aluno_id,))

            aluno = cur.fetchone()
            conn.close()

            if not aluno:
                flash("Aluno não encontrado.", "danger")
                return redirect(url_for("painel.home"))

            user = current_user

            # -----------------------------
            # FEDERAÇÃO (ROLE)
            # -----------------------------
            if user.has_role("gestor_federacao"):
                if permitir_edicao:
                    flash("Federação não pode editar alunos.", "warning")
                    return redirect(url_for("painel.home"))
                return func(*args, **kwargs)

            # -----------------------------
            # ASSOCIAÇÃO (ROLE)
            # -----------------------------
            if user.has_role("gestor_associacao"):
                if aluno["id_associacao"] != user.id_associacao:
                    flash("Aluno pertence a outra associação.", "danger")
                    return redirect(url_for("painel.home"))
                return func(*args, **kwargs)

            # -----------------------------
            # ACADEMIA (ROLE)
            # -----------------------------
            if user.has_role("gestor_academia") or user.has_role("professor"):
                if aluno["id_academia"] != user.id_academia:
                    flash("Aluno pertence a outra academia.", "danger")
                    return redirect(url_for("painel.home"))
                return func(*args, **kwargs)

            # -----------------------------
            # ALUNO
            # -----------------------------
            if user.has_role("aluno"):
                if aluno["usuario_id"] != user.id:
                    flash("Você só pode acessar seu próprio perfil.", "danger")
                    return redirect(url_for("painel.home"))
                return func(*args, **kwargs)

            flash("Acesso negado.", "danger")
            return redirect(url_for("painel.home"))

        return wrapper
    return decorator


# ======================================================
# 🔹 Atalho: apenas quem pode editar aluno
# ======================================================
def aluno_edit_required(func):
    """
    Apenas quem tem permissão de editar aluno.
    """
    return permission_required("editar_aluno")(func)
