from .base import db


class Competicao(db.Model):
    __tablename__ = "competicoes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150))
    data = db.Column(db.Date)
    local = db.Column(db.String(150))
    tipo = db.Column(db.Enum("OFICIAL", "FESTIVAL"), default="OFICIAL")
    # True: inscrições sem categoria fixa; atleta entra em toda categoria em que encaixa (peso/idade/sexo).
    festival_aproximacao = db.Column(db.Boolean, default=False, nullable=False)

    categorias = db.relationship("Categoria", back_populates="competicao", lazy="dynamic")
    inscricoes = db.relationship("Inscricao", back_populates="competicao", lazy="dynamic")
    pagamentos = db.relationship("Pagamento", back_populates="competicao", lazy="dynamic")
