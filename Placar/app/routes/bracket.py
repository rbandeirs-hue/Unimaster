from flask import Blueprint, render_template, jsonify
from app.services.bracket_service import get_bracket

bp = Blueprint("bracket", __name__)


@bp.get("/<int:categoria_id>")
def pagina(categoria_id):
    return render_template("bracket.html", categoria_id=categoria_id)


@bp.get("/api/<int:categoria_id>")
def dados(categoria_id):
    return jsonify(get_bracket(categoria_id))
