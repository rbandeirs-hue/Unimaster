from .base import db


class Resultado(db.Model):
    __tablename__ = "resultados"

    id = db.Column(db.Integer, primary_key=True)
    luta_id = db.Column(db.Integer, db.ForeignKey("lutas.id"))
    ippon_azul   = db.Column(db.Integer, default=0)
    wazari_azul  = db.Column(db.Integer, default=0)
    yuko_azul    = db.Column(db.Integer, default=0)
    shido_azul   = db.Column(db.Integer, default=0)
    ippon_branco  = db.Column(db.Integer, default=0)
    wazari_branco = db.Column(db.Integer, default=0)
    yuko_branco   = db.Column(db.Integer, default=0)
    shido_branco  = db.Column(db.Integer, default=0)
    tempo_luta = db.Column(db.Integer)  # segundos

    luta = db.relationship("Luta", back_populates="resultado")
