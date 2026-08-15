from flask import Blueprint, request
from app.services import academia_service as svc
from app.utils.responses import success, error

bp = Blueprint("academias", __name__)


@bp.get("/")
def listar():
    academias = svc.listar()
    return success([_serialize(a) for a in academias])


@bp.get("/<int:id>")
def buscar(id):
    return success(_serialize(svc.buscar(id)))


@bp.post("/")
def criar():
    dados = request.get_json()
    if not dados or not dados.get("nome"):
        return error("Campo 'nome' é obrigatório.")
    return success(_serialize(svc.criar(dados)), 201)


@bp.put("/<int:id>")
def atualizar(id):
    dados = request.get_json()
    return success(_serialize(svc.atualizar(id, dados)))


@bp.delete("/<int:id>")
def deletar(id):
    svc.deletar(id)
    return success(None, 204)


def _serialize(a):
    return {
        "id": a.id,
        "nome": a.nome,
        "cidade": a.cidade,
        "responsavel": a.responsavel,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
