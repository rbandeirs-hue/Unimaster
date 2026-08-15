from flask import Blueprint, request
from flask_login import login_required
from app.services import competicao_service as svc
from app.services import chaveamento_service as chv
from app.utils.responses import success, error

bp = Blueprint("competicoes", __name__)


@bp.get("/")
def listar():
    return success([_serialize(c) for c in svc.listar()])


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


@bp.post("/<int:id>/gerar-categorias")
@login_required
def gerar_categorias(id):
    try:
        cats = chv.gerar_categorias(id)
        return success({"categorias_criadas": len(cats)}, 201)
    except ValueError as e:
        return error(str(e))


def _serialize(c):
    return {
        "id": c.id,
        "nome": c.nome,
        "data": c.data.isoformat() if c.data else None,
        "local": c.local,
        "tipo": c.tipo,
        "festival_aproximacao": getattr(c, "festival_aproximacao", False),
    }
