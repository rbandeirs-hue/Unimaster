from app.models.base import db
from app.models.competicao import Competicao


def listar():
    return Competicao.query.all()


def buscar(id):
    return Competicao.query.get_or_404(id)


def criar(dados):
    competicao = Competicao(**dados)
    db.session.add(competicao)
    db.session.commit()
    return competicao


def atualizar(id, dados):
    competicao = buscar(id)
    for campo, valor in dados.items():
        setattr(competicao, campo, valor)
    db.session.commit()
    return competicao


def deletar(id):
    competicao = buscar(id)
    db.session.delete(competicao)
    db.session.commit()
