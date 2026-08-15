from app.models.base import db
from app.models.categoria import Categoria


def listar(competicao_id=None):
    q = Categoria.query
    if competicao_id:
        q = q.filter_by(competicao_id=competicao_id)
    return q.all()


def buscar(id):
    return Categoria.query.get_or_404(id)


def criar(dados):
    categoria = Categoria(**dados)
    db.session.add(categoria)
    db.session.commit()
    return categoria


def atualizar(id, dados):
    categoria = buscar(id)
    for campo, valor in dados.items():
        setattr(categoria, campo, valor)
    db.session.commit()
    return categoria


def deletar(id):
    categoria = buscar(id)
    db.session.delete(categoria)
    db.session.commit()
