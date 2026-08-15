from .base import db


class Luta(db.Model):
    __tablename__ = "lutas"

    id = db.Column(db.Integer, primary_key=True)
    atleta_azul_id = db.Column(db.Integer, db.ForeignKey("atletas.id"))
    atleta_branco_id = db.Column(db.Integer, db.ForeignKey("atletas.id"))
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias.id"))
    fase = db.Column(db.String(50))
    numero_luta = db.Column(db.Integer)
    vencedor_id = db.Column(db.Integer, db.ForeignKey("atletas.id"), nullable=True)
    estado_json = db.Column(db.Text, nullable=True)

    categoria = db.relationship(
        "Categoria",
        foreign_keys=[categoria_id],
        back_populates="lutas",
    )
    atleta_azul = db.relationship("Atleta", foreign_keys=[atleta_azul_id])
    atleta_branco = db.relationship("Atleta", foreign_keys=[atleta_branco_id])
    vencedor = db.relationship("Atleta", foreign_keys=[vencedor_id])
    resultado = db.relationship("Resultado", back_populates="luta", uselist=False)
