# ======================================================
# 🧩 utils/permissoes.py
# ======================================================
from functools import wraps
from flask import abort
from flask_login import current_user


# ======================================================
# 🔹 Decorador genérico
# ======================================================
def acesso_permitido(perfis_permitidos):
    """
    Verifica se o usuário logado tem permissão para acessar a rota.
    Perfis_permitidos é uma lista de perfis válidos.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)  # Não autenticado
            if not any(
                current_user.has_role(p) or current_user.has_access_level(p)
                for p in perfis_permitidos
            ):
                abort(403)  # Acesso negado
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ======================================================
# 🔹 Decoradores específicos por nível
# ======================================================

def somente_federacao(f):
    """Permite acesso apenas para usuários da federação."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.has_access_level("Federação"):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def somente_associacao(f):
    """Permite acesso apenas para usuários da associação."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.has_access_level("Associação"):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def somente_academia(f):
    """Permite acesso apenas para usuários da academia."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.has_access_level("Academia"):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def somente_admin(f):
    """Permite acesso apenas para administradores gerais."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.has_role("admin"):
            abort(403)
        return f(*args, **kwargs)
    return wrapper
