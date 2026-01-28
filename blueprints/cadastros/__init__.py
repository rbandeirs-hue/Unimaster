# blueprints/cadastros/__init__.py

from flask import Blueprint

cadastros_bp = Blueprint(
    "cadastros",
    __name__,
    url_prefix="/cadastros"
)

from . import routes
