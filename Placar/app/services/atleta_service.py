from app.models.base import db
from app.models.atleta import Atleta


def _like_seguro(termo):
    """Escapa % e _ para uso em LIKE/ILIKE."""
    return (
        termo.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def listar(academia_id=None, busca_nome=None):
    q = Atleta.query
    if academia_id:
        q = q.filter_by(academia_id=academia_id)
    if busca_nome:
        t = busca_nome.strip()
        if t:
            frag = _like_seguro(t)
            q = q.filter(Atleta.nome.ilike(f"%{frag}%", escape="\\"))
    return q.order_by(Atleta.nome).all()


def buscar(id):
    return Atleta.query.get_or_404(id)


def criar(dados):
    atleta = Atleta(**dados)
    db.session.add(atleta)
    db.session.commit()
    return atleta


def atualizar(id, dados):
    atleta = buscar(id)
    for campo, valor in dados.items():
        setattr(atleta, campo, valor)
    db.session.commit()
    return atleta


def deletar(id):
    atleta = buscar(id)
    db.session.delete(atleta)
    db.session.commit()
