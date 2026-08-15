from .base import db


class Pagamento(db.Model):
    __tablename__ = "pagamentos"

    id = db.Column(db.Integer, primary_key=True)
    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"))
    competicao_id = db.Column(db.Integer, db.ForeignKey("competicoes.id"))
    valor = db.Column(db.Numeric(10, 2))
    status = db.Column(db.Enum("PAGO", "PENDENTE"), default="PENDENTE")

    academia = db.relationship("Academia", back_populates="pagamentos")
    competicao = db.relationship("Competicao", back_populates="pagamentos")
