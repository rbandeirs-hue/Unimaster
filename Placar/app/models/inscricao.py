from .base import db


class Inscricao(db.Model):
    __tablename__ = "inscricoes"

    id = db.Column(db.Integer, primary_key=True)
    atleta_id = db.Column(db.Integer, db.ForeignKey("atletas.id"))
    competicao_id = db.Column(db.Integer, db.ForeignKey("competicoes.id"))
    # Se preenchido (ex.: festival por área/PDF), o atleta só entra nessa categoria.
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias.id"), nullable=True)
    status = db.Column(db.Enum("PENDENTE", "CONFIRMADO"), default="PENDENTE")

    atleta = db.relationship("Atleta", back_populates="inscricoes")
    competicao = db.relationship("Competicao", back_populates="inscricoes")
