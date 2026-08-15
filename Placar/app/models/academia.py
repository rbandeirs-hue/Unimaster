from .base import db


class Academia(db.Model):
    __tablename__ = "academias"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    cidade = db.Column(db.String(100))
    responsavel = db.Column(db.String(150))
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())

    atletas = db.relationship("Atleta", back_populates="academia", lazy="dynamic")
    pagamentos = db.relationship("Pagamento", back_populates="academia", lazy="dynamic")
