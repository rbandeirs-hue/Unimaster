from flask import Blueprint, request
from app.services import atleta_service as svc
from app.utils.responses import success, error

bp = Blueprint("atletas", __name__)


@bp.get("/")
def listar():
    academia_id = request.args.get("academia_id", type=int)
    return success([_serialize(a) for a in svc.listar(academia_id)])


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
        "data_nascimento": a.data_nascimento.isoformat() if a.data_nascimento else None,
        "peso": float(a.peso) if a.peso else None,
        "faixa": a.faixa,
        "sexo": a.sexo,
        "academia_id": a.academia_id,
    }
