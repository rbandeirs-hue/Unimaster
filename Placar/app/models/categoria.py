from .base import db


class Categoria(db.Model):
    __tablename__ = "categorias"

    id = db.Column(db.Integer, primary_key=True)
    # id da tabela oficial (catálogo), não confundir com PK
    catalogo_id = db.Column(db.Integer, nullable=True, index=True)
    id_classe = db.Column(db.String(50), nullable=True)
    classe_peso = db.Column(db.String(80), nullable=True)
    nome = db.Column(db.String(200))
    descricao = db.Column(db.Text, nullable=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    idade_min = db.Column(db.Integer, nullable=True)
    idade_max = db.Column(db.Integer, nullable=True)
    peso_min = db.Column(db.Numeric(5, 2), nullable=True)
    peso_max = db.Column(db.Numeric(5, 2), nullable=True)
    faixa = db.Column(db.String(50), nullable=True)
    sexo = db.Column(db.Enum("M", "F"))
    competicao_id = db.Column(db.Integer, db.ForeignKey("competicoes.id"))
    # Luta exibida no placar público estável (/placar/categoria/<id>); atualizada pela mesa ao abrir a luta.
    placar_luta_id = db.Column(db.Integer, db.ForeignKey("lutas.id"), nullable=True)

    competicao = db.relationship("Competicao", back_populates="categorias")
    # Duas FKs categorias↔lutas (categoria_id e placar_luta_id): precisa foreign_keys explícito.
    lutas = db.relationship(
        "Luta",
        foreign_keys="[Luta.categoria_id]",
        back_populates="categoria",
        lazy="dynamic",
    )
    placar_luta = db.relationship(
        "Luta",
        foreign_keys=[placar_luta_id],
        uselist=False,
    )
