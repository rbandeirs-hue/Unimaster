from flask import Blueprint, request
from flask_login import login_required
from app.services import categoria_service as svc
from app.services import chaveamento_service as chv
from app.utils.responses import success, error

bp = Blueprint("categorias", __name__)


@bp.get("/")
def listar():
    competicao_id = request.args.get("competicao_id", type=int)
    return success([_serialize(c) for c in svc.listar(competicao_id)])


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


@bp.post("/<int:id>/gerar-chave")
@login_required
def gerar_chave(id):
    dados = request.get_json(silent=True) or {}
    atleta_ids = dados.get("atleta_ids")  # opcional — se omitido, usa inscritos confirmados
    try:
        lutas = chv.gerar_chave(id, atleta_ids)
        return success({"lutas_criadas": len(lutas)}, 201)
    except ValueError as e:
        return error(str(e))


@bp.post("/<int:id>/resetar-chave")
@login_required
def resetar_chave(id):
    n = chv.resetar_chave(id)
    return success({"lutas_removidas": n})


def _serialize(c):
    return {
        "id": c.id,
        "catalogo_id": c.catalogo_id,
        "id_classe": c.id_classe,
        "classe_peso": c.classe_peso,
        "nome": c.nome,
        "descricao": c.descricao,
        "ativo": c.ativo,
        "sexo": c.sexo,
        "faixa": c.faixa,
        "idade_min": c.idade_min,
        "idade_max": c.idade_max,
        "peso_min": float(c.peso_min) if c.peso_min is not None else None,
        "peso_max": float(c.peso_max) if c.peso_max is not None else None,
        "competicao_id": c.competicao_id,
    }
