import os
import click
from app import create_app
from app.models.base import db

app = create_app(os.environ.get("FLASK_ENV", "development"))


@app.cli.command("init-db")
def init_db():
    """Cria todas as tabelas no banco."""
    with app.app_context():
        db.create_all()
        print("Banco de dados inicializado.")


@app.cli.command("upgrade-db-categorias")
def upgrade_db_categorias():
    """
    Adiciona colunas do catálogo (catalogo_id, id_classe, …) na tabela categorias.
    Necessário após atualizar o código se o MySQL ainda não tiver essas colunas.
    Uso: flask upgrade-db-categorias
    """
    from sqlalchemy import inspect, text

    with app.app_context():
        insp = inspect(db.engine)
        if not insp.has_table("categorias"):
            click.echo("Tabela categorias não existe. Execute: flask init-db")
            return

        dialect = db.engine.dialect.name
        cols = {c["name"] for c in insp.get_columns("categorias")}

        adds = []
        if "catalogo_id" not in cols:
            adds.append("ALTER TABLE categorias ADD COLUMN catalogo_id INT NULL")
        if "id_classe" not in cols:
            adds.append("ALTER TABLE categorias ADD COLUMN id_classe VARCHAR(50) NULL")
        if "classe_peso" not in cols:
            adds.append("ALTER TABLE categorias ADD COLUMN classe_peso VARCHAR(80) NULL")
        if "descricao" not in cols:
            adds.append("ALTER TABLE categorias ADD COLUMN descricao TEXT NULL")
        if "ativo" not in cols:
            adds.append(
                "ALTER TABLE categorias ADD COLUMN ativo TINYINT(1) NOT NULL DEFAULT 1"
            )

        for sql in adds:
            db.session.execute(text(sql))
            db.session.commit()
            click.echo(sql)

        if not adds:
            click.echo("Nenhuma coluna nova (já estavam presentes).")

        if dialect in ("mysql", "mariadb"):
            click.echo("Ajustando tipos (nome 200, idade/peso/faixa NULL)...")
            try:
                db.session.execute(
                    text(
                        """
                        ALTER TABLE categorias
                        MODIFY COLUMN nome VARCHAR(200) NULL,
                        MODIFY COLUMN idade_min INT NULL,
                        MODIFY COLUMN idade_max INT NULL,
                        MODIFY COLUMN peso_min DECIMAL(5,2) NULL,
                        MODIFY COLUMN peso_max DECIMAL(5,2) NULL,
                        MODIFY COLUMN faixa VARCHAR(50) NULL
                        """
                    )
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                click.echo(f"Aviso MODIFY: {e}")

            insp = inspect(db.engine)
            idx_names = {ix["name"] for ix in insp.get_indexes("categorias")}
            if "ix_categorias_catalogo_id" not in idx_names:
                try:
                    db.session.execute(
                        text(
                            "CREATE INDEX ix_categorias_catalogo_id ON categorias (catalogo_id)"
                        )
                    )
                    db.session.commit()
                    click.echo("Índice ix_categorias_catalogo_id criado.")
                except Exception as e:
                    db.session.rollback()
                    click.echo(f"Índice: {e}")
        else:
            click.echo(
                f"Dialeto '{dialect}': colunas adicionadas via ADD. "
                "Para SQLite novo, prefira flask init-db em banco limpo."
            )

        click.echo("Pronto. Recarregue a aplicação.")


@app.cli.command("upgrade-db-inscricoes-categoria")
def upgrade_db_inscricoes_categoria():
    """
    Adiciona inscricoes.categoria_id (inscrição por categoria, ex.: festival/PDF).
    Uso: flask upgrade-db-inscricoes-categoria
    """
    from sqlalchemy import inspect, text

    with app.app_context():
        insp = inspect(db.engine)
        if not insp.has_table("inscricoes"):
            click.echo("Tabela inscricoes não existe. Execute: flask init-db")
            return

        cols = {c["name"] for c in insp.get_columns("inscricoes")}
        if "categoria_id" in cols:
            click.echo("Coluna categoria_id já existe em inscricoes.")
            return

        dialect = db.engine.dialect.name
        if dialect in ("mysql", "mariadb"):
            db.session.execute(
                text("ALTER TABLE inscricoes ADD COLUMN categoria_id INT NULL")
            )
            db.session.commit()
            try:
                db.session.execute(
                    text(
                        "ALTER TABLE inscricoes ADD CONSTRAINT fk_inscricoes_categoria "
                        "FOREIGN KEY (categoria_id) REFERENCES categorias(id)"
                    )
                )
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                click.echo(f"Aviso FK (coluna criada): {e}")
        else:
            db.session.execute(
                text("ALTER TABLE inscricoes ADD COLUMN categoria_id INTEGER NULL")
            )
            db.session.commit()
        click.echo("Coluna inscricoes.categoria_id adicionada.")


@app.cli.command("upgrade-db-competicao-festival-ap")
def upgrade_db_competicao_festival_ap():
    """
    Adiciona competicoes.festival_aproximacao (modo festival por peso/idade).
    Uso: flask upgrade-db-competicao-festival-ap
    """
    from sqlalchemy import inspect, text

    with app.app_context():
        insp = inspect(db.engine)
        if not insp.has_table("competicoes"):
            click.echo("Tabela competicoes não existe. Execute: flask init-db")
            return

        cols = {c["name"] for c in insp.get_columns("competicoes")}
        if "festival_aproximacao" in cols:
            click.echo("Coluna festival_aproximacao já existe em competicoes.")
            return

        dialect = db.engine.dialect.name
        if dialect in ("mysql", "mariadb"):
            db.session.execute(
                text(
                    "ALTER TABLE competicoes ADD COLUMN festival_aproximacao "
                    "TINYINT(1) NOT NULL DEFAULT 0"
                )
            )
        else:
            db.session.execute(
                text(
                    "ALTER TABLE competicoes ADD COLUMN festival_aproximacao "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            )
        db.session.commit()
        click.echo("Coluna competicoes.festival_aproximacao adicionada.")


@app.cli.command("upgrade-db-categoria-placar-luta")
def upgrade_db_categoria_placar_luta():
    """
    Adiciona categorias.placar_luta_id (URL fixa /placar/categoria/<id>).
    Uso: flask upgrade-db-categoria-placar-luta
    """
    from sqlalchemy import inspect, text

    with app.app_context():
        insp = inspect(db.engine)
        if not insp.has_table("categorias"):
            click.echo("Tabela categorias não existe. Execute: flask init-db")
            return

        cols = {c["name"] for c in insp.get_columns("categorias")}
        if "placar_luta_id" in cols:
            click.echo("Coluna placar_luta_id já existe em categorias.")
            return

        dialect = db.engine.dialect.name
        if dialect in ("mysql", "mariadb"):
            db.session.execute(
                text(
                    "ALTER TABLE categorias ADD COLUMN placar_luta_id INT NULL, "
                    "ADD CONSTRAINT fk_categorias_placar_luta "
                    "FOREIGN KEY (placar_luta_id) REFERENCES lutas(id)"
                )
            )
        else:
            db.session.execute(
                text(
                    "ALTER TABLE categorias ADD COLUMN placar_luta_id INTEGER NULL "
                    "REFERENCES lutas(id)"
                )
            )
        db.session.commit()
        click.echo("Coluna categorias.placar_luta_id adicionada.")


@app.cli.command("import-festival-2026")
def import_festival_2026():
    """
    Importa competição Festival Judô ArteFísica 2026 (lista transcrita do PDF).
    Executar na raiz do projeto. Idempotente: não duplica se a competição já existir.
    """
    import sys

    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)
    from seed_festival_2026 import import_festival_arte_fisica_2026

    with app.app_context():
        import_festival_arte_fisica_2026(skip_if_exists=True)


@app.cli.command("create-admin")
@click.argument("email")
@click.password_option(confirmation_prompt=True)
def create_admin(email, password):
    """Cria um usuário administrador. Uso: flask create-admin admin@clube.com"""
    with app.app_context():
        from app.models.usuario import Usuario
        if Usuario.query.filter_by(email=email).first():
            print(f"Erro: já existe um usuário com e-mail '{email}'.")
            return
        u = Usuario(email=email.lower(), papel="admin")
        u.set_senha(password)
        db.session.add(u)
        db.session.commit()
        print(f"Admin criado: {email}")


if __name__ == "__main__":
    import sys

    print(
        "Não use app.run() aqui. Exemplo: cd Placar && export FLASK_APP=run:app && flask run",
        file=sys.stderr,
    )
    sys.exit(2)
