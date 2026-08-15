from flask import Blueprint, request
from app.services import inscricao_service as svc
from app.utils.responses import success, error

bp = Blueprint("inscricoes", __name__)


@bp.get("/")
def listar():
    competicao_id = request.args.get("competicao_id", type=int)
    atleta_id = request.args.get("atleta_id", type=int)
    return success([_serialize(i) for i in svc.listar(competicao_id, atleta_id)])


@bp.get("/<int:id>")
def buscar(id):
    return success(_serialize(svc.buscar(id)))


@bp.post("/")
def criar():
    dados = request.get_json()
    if not dados or not dados.get("atleta_id") or not dados.get("competicao_id"):
        return error("Campos 'atleta_id' e 'competicao_id' são obrigatórios.")
    try:
        return success(_serialize(svc.criar(dados)), 201)
    except ValueError as e:
        return error(str(e))


@bp.patch("/<int:id>/confirmar")
def confirmar(id):
    return success(_serialize(svc.confirmar(id)))


@bp.delete("/<int:id>")
def deletar(id):
    svc.deletar(id)
    return success(None, 204)


def _serialize(i):
    return {
        "id": i.id,
        "atleta_id": i.atleta_id,
        "competicao_id": i.competicao_id,
        "status": i.status,
    }
