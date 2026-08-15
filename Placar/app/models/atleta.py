from .base import db


class Atleta(db.Model):
    __tablename__ = "atletas"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    data_nascimento = db.Column(db.Date)
    peso = db.Column(db.Numeric(5, 2))
    faixa = db.Column(db.String(50))
    sexo = db.Column(db.Enum("M", "F"))
    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"))
    foto_url = db.Column(db.String(500), nullable=True)

    academia = db.relationship("Academia", back_populates="atletas")
    inscricoes = db.relationship("Inscricao", back_populates="atleta", lazy="dynamic")
