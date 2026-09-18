# blueprints/cadastros/__init__.py

from flask import Blueprint

cadastros_bp = Blueprint(
    "cadastros",
    __name__,
    url_prefix="/cadastros"
)

# Aluno, responsável e visitante não entram aqui nem digitando a URL:
# o hub de cadastros é da administração da academia.
from utils.permissoes import somente_gestao  # noqa: E402
cadastros_bp.before_request(somente_gestao())

from . import routes
