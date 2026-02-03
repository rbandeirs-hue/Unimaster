# Blueprint para Visitante
from flask import Blueprint

bp_visitante = Blueprint("visitante", __name__, url_prefix="/visitante")

# Importar rotas após criar o blueprint
from . import routes
