import re
import secrets

from flask import Blueprint, abort, redirect, render_template, url_for
from flask_login import login_required
from app.models.luta import Luta
from app.models.categoria import Categoria
from app.services import luta_service as luta_svc

bp = Blueprint("mesa", __name__)

_AVULSO_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def _valid_avulso_token(t):
    return bool(t and _AVULSO_TOKEN_RE.match(t))


def _iniciais(nome):
    if not nome:
        return "?"
    p = nome.strip().split()
    return (p[0][0] + p[-1][0]).upper() if len(p) >= 2 else nome[:2].upper()


def _resultado_para_mesa(r):
    return {
        "ippon_azul": r.ippon_azul or 0,
        "wazari_azul": r.wazari_azul or 0,
        "yuko_azul": r.yuko_azul or 0,
        "shido_azul": r.shido_azul or 0,
        "ippon_branco": r.ippon_branco or 0,
        "wazari_branco": r.wazari_branco or 0,
        "yuko_branco": r.yuko_branco or 0,
        "shido_branco": r.shido_branco or 0,
        "tempo_luta": r.tempo_luta,
    }


@bp.get("/avulso")
@login_required
def avulso_redirect():
    token = secrets.token_urlsafe(16)
    return redirect(url_for("mesa.avulso_sessao", token=token))


@bp.get("/avulso/<token>")
@login_required
def avulso_sessao(token):
    if not _valid_avulso_token(token):
        abort(404)
    return render_template(
        "mesa.html",
        mesa_avulsa=True,
        avulso_token=token,
        luta=None,
        categoria=None,
        iniciais=_iniciais,
        luta_finalizada=False,
        resultado_mesa=None,
        vencedor_lado_inicial=None,
    )


@bp.get("/<int:luta_id>")
@login_required
def pagina(luta_id):
    luta = Luta.query.get_or_404(luta_id)
    categoria = Categoria.query.get(luta.categoria_id)
    luta_finalizada = luta.resultado is not None
    resultado_mesa = None
    vencedor_lado_inicial = None
    if luta_finalizada and luta.resultado:
        resultado_mesa = _resultado_para_mesa(luta.resultado)
        if luta.vencedor_id and luta.atleta_azul_id == luta.vencedor_id:
            vencedor_lado_inicial = "azul"
        elif luta.vencedor_id and luta.atleta_branco_id == luta.vencedor_id:
            vencedor_lado_inicial = "branco"
        else:
            v = luta_svc._vantagem_por_contagem_resultado(luta.resultado)
            if v > 0 and luta.atleta_azul_id:
                vencedor_lado_inicial = "azul"
            elif v < 0 and luta.atleta_branco_id:
                vencedor_lado_inicial = "branco"
    return render_template(
        "mesa.html",
        luta=luta,
        categoria=categoria,
        iniciais=_iniciais,
        luta_finalizada=luta_finalizada,
        resultado_mesa=resultado_mesa,
        vencedor_lado_inicial=vencedor_lado_inicial,
        mesa_avulsa=False,
        avulso_token=None,
    )
