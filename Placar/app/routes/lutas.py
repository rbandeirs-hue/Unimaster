from flask import Blueprint, request
from flask_login import login_required
from app.services import luta_service as svc
from app.utils.responses import success, error

bp = Blueprint("lutas", __name__)


@bp.get("/")
def listar():
    categoria_id = request.args.get("categoria_id", type=int)
    return success([_serialize(l) for l in svc.listar(categoria_id)])


@bp.get("/<int:id>")
def buscar(id):
    return success(_serialize(svc.buscar(id)))


@bp.post("/")
def criar():
    dados = request.get_json()
    return success(_serialize(svc.criar(dados)), 201)


@bp.post("/<int:id>/resultado")
@login_required
def resultado(id):
    dados = request.get_json()
    try:
        luta = svc.registrar_resultado(id, dados)
        return success(_serialize(luta))
    except ValueError as e:
        return error(str(e))


@bp.put("/<int:id>/resultado")
@login_required
def resultado_atualizar(id):
    dados = request.get_json()
    try:
        luta = svc.atualizar_resultado(id, dados)
        return success(_serialize(luta))
    except ValueError as e:
        return error(str(e))


def _serialize(l):
    return {
        "id": l.id,
        "categoria_id": l.categoria_id,
        "atleta_azul_id": l.atleta_azul_id,
        "atleta_branco_id": l.atleta_branco_id,
        "fase": l.fase,
        "vencedor_id": l.vencedor_id,
        "resultado": _serialize_resultado(l.resultado),
    }


def _serialize_resultado(r):
    if not r:
        return None
    return {
        "ippon_azul": r.ippon_azul,
        "wazari_azul": r.wazari_azul,
        "yuko_azul": r.yuko_azul,
        "shido_azul": r.shido_azul,
        "ippon_branco": r.ippon_branco,
        "wazari_branco": r.wazari_branco,
        "yuko_branco": r.yuko_branco,
        "shido_branco": r.shido_branco,
        "tempo_luta": r.tempo_luta,
    }
