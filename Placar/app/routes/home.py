from flask import Blueprint, render_template
from app.models.competicao import Competicao
from app.models.luta import Luta
from app.models.resultado import Resultado
from app.services import chaveamento_service as chv

bp = Blueprint("home", __name__)


@bp.get("/")
def index():
    competicoes = Competicao.query.order_by(Competicao.data.desc()).all()
    return render_template("home.html", competicoes=competicoes)


@bp.get("/competicao/<int:comp_id>")
def competicao(comp_id):
    comp = Competicao.query.get_or_404(comp_id)
    categorias = chv.categorias_com_inscritos(comp_id)

    lutas_por_cat = {}
    n_lutas_por_cat = {}
    for cat in categorias:
        proxima = (
            Luta.query
            .filter_by(categoria_id=cat.id)
            .filter(
                Luta.atleta_azul_id.isnot(None),
                Luta.atleta_branco_id.isnot(None),
            )
            .outerjoin(Resultado, Resultado.luta_id == Luta.id)
            .filter(Resultado.id.is_(None))
            .order_by(Luta.numero_luta)
            .first()
        )
        lutas_por_cat[cat.id] = proxima
        n_lutas_por_cat[cat.id] = Luta.query.filter_by(categoria_id=cat.id).count()

    return render_template(
        "competicao.html",
        comp=comp,
        categorias=categorias,
        lutas_por_cat=lutas_por_cat,
        n_lutas_por_cat=n_lutas_por_cat,
    )
