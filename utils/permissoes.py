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


# ======================================================
# 🔹 Gestão x painéis próprios (aluno / responsável / visitante)
# ======================================================
# Aluno e responsável entravam nas telas de gestão só digitando a URL: a maioria
# das rotas de `alunos`, `turmas`, `presencas`, `precadastro` e `solicitacoes`
# tinha apenas `@login_required`. Um responsável abria a lista com os 287 alunos
# de todas as academias, com os botões de inativar e excluir à mostra.
#
# A trava é um `before_request` por blueprint, e não decorador rota a rota, para
# valer também nas rotas que forem criadas depois.
PAPEIS_GESTAO = ("admin", "gestor_federacao", "gestor_associacao",
                 "gestor_academia", "professor")


def eh_gestao():
    """True se o usuário tem algum papel que administra a academia."""
    try:
        if not current_user.is_authenticated:
            return False
        return any(current_user.has_role(p) for p in PAPEIS_GESTAO)
    except Exception:
        return False


def _painel_do_usuario():
    """Para onde mandar quem não administra — o painel do próprio papel."""
    from flask import url_for
    try:
        if current_user.has_role("responsavel"):
            return url_for("painel_responsavel.meu_perfil")
        if current_user.has_role("aluno"):
            return url_for("painel_aluno.meu_perfil")
        if current_user.has_role("visitante"):
            return url_for("visitante.painel")
    except Exception:
        pass
    from flask import url_for as _u
    return _u("painel.home")


def somente_gestao(livres=()):
    """`before_request` que barra quem não administra a academia.

    `livres` são endpoints (nome curto, sem o blueprint) que o próprio aluno ou
    responsável usa de forma legítima — o ranking de frequência, por exemplo,
    que está no menu deles.
    """
    from flask import request, flash, redirect

    def guarda():
        if not current_user.is_authenticated:
            return None          # `login_required` da rota cuida disso
        if eh_gestao():
            return None
        endpoint = (request.endpoint or "").split(".")[-1]
        if endpoint in livres:
            return None
        flash("Esta área é da administração da academia.", "warning")
        return redirect(_painel_do_usuario())

    return guarda


def aluno_e_do_usuario(aluno_id):
    """True se o aluno é o próprio usuário ou um filho do responsável.

    É o que permite manter "Meu perfil → Editar" funcionando sem abrir a ficha
    de qualquer aluno da base: a rota de edição é a mesma da secretaria.
    """
    try:
        from config import get_db_connection
        uid = getattr(current_user, "id", None)
        if not uid or not aluno_id:
            return False
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM alunos WHERE id = %s AND usuario_id = %s", (aluno_id, uid))
            if cur.fetchone():
                return True
            cur.execute(
                "SELECT 1 FROM responsavel_alunos WHERE usuario_id = %s AND aluno_id = %s",
                (uid, aluno_id),
            )
            return cur.fetchone() is not None
        finally:
            cur.close()
            conn.close()
    except Exception:
        return False


def somente_gestao_alunos():
    """Trava do blueprint de alunos, com a exceção da própria ficha.

    Aluno e responsável continuam abrindo a edição do próprio cadastro (e o
    responsável, a dos filhos) porque é assim que o "Meu perfil" funciona — mas
    só desses registros, não da base inteira.
    """
    from flask import request, flash, redirect

    LIVRES_PROPRIAS = ("editar_aluno", "ficha_aluno")

    def guarda():
        if not current_user.is_authenticated:
            return None
        if eh_gestao():
            return None
        endpoint = (request.endpoint or "").split(".")[-1]
        if endpoint in LIVRES_PROPRIAS:
            alvo = (request.view_args or {}).get("aluno_id")
            if aluno_e_do_usuario(alvo):
                return None
            flash("Você só pode abrir o seu cadastro.", "warning")
            return redirect(_painel_do_usuario())
        flash("Esta área é da administração da academia.", "warning")
        return redirect(_painel_do_usuario())

    return guarda
