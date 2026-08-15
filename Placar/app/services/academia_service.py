from app.models.base import db
from app.models.academia import Academia


def listar():
    return Academia.query.all()


def buscar(id):
    return Academia.query.get_or_404(id)


def criar(dados):
    academia = Academia(**dados)
    db.session.add(academia)
    db.session.commit()
    return academia


def atualizar(id, dados):
    academia = buscar(id)
    for campo, valor in dados.items():
        setattr(academia, campo, valor)
    db.session.commit()
    return academia


def deletar(id):
    academia = buscar(id)
    db.session.delete(academia)
    db.session.commit()
