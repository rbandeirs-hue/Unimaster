from app.models.base import db
from app.models.inscricao import Inscricao


def listar(competicao_id=None, atleta_id=None):
    q = Inscricao.query
    if competicao_id:
        q = q.filter_by(competicao_id=competicao_id)
    if atleta_id:
        q = q.filter_by(atleta_id=atleta_id)
    return q.all()


def buscar(id):
    return Inscricao.query.get_or_404(id)


def criar(dados):
    atleta_id = dados["atleta_id"]
    competicao_id = dados["competicao_id"]
    cat_id = dados.get("categoria_id")
    q = Inscricao.query.filter_by(atleta_id=atleta_id, competicao_id=competicao_id)
    if cat_id is None:
        if q.filter(Inscricao.categoria_id.is_(None)).first():
            raise ValueError("Atleta já inscrito nesta competição.")
    elif q.filter_by(categoria_id=cat_id).first():
        raise ValueError("Atleta já inscrito nesta categoria da competição.")
    inscricao = Inscricao(**dados)
    db.session.add(inscricao)
    db.session.commit()
    return inscricao


def confirmar(id):
    inscricao = buscar(id)
    inscricao.status = "CONFIRMADO"
    db.session.commit()
    return inscricao


def deletar(id):
    inscricao = buscar(id)
    db.session.delete(inscricao)
    db.session.commit()
