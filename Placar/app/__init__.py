from flask import Flask
from flask_login import LoginManager
from app.models.base import db
from config import config

login_manager = LoginManager()


def create_app(env="default"):
    app = Flask(__name__)
    app.config.from_object(config[env])

    db.init_app(app)
    _init_login(app)
    _register_blueprints(app)

    return app


def _init_login(app):
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar esta página."
    login_manager.login_message_category = "warning"

    from app.models.usuario import Usuario

    @login_manager.user_loader
    def load_user(user_id):
        return Usuario.query.get(int(user_id))


def _register_blueprints(app):
    from app.routes.auth import bp as auth_bp
    from app.routes.home import bp as home_bp
    from app.routes.admin import bp as admin_bp
    from app.routes.academias import bp as academias_bp
    from app.routes.atletas import bp as atletas_bp
    from app.routes.competicoes import bp as competicoes_bp
    from app.routes.inscricoes import bp as inscricoes_bp
    from app.routes.categorias import bp as categorias_bp
    from app.routes.lutas import bp as lutas_bp
    from app.routes.bracket import bp as bracket_bp
    from app.routes.mesa import bp as mesa_bp
    from app.routes.placar import bp as placar_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(academias_bp,   url_prefix="/api/academias")
    app.register_blueprint(atletas_bp,     url_prefix="/api/atletas")
    app.register_blueprint(competicoes_bp, url_prefix="/api/competicoes")
    app.register_blueprint(inscricoes_bp,  url_prefix="/api/inscricoes")
    app.register_blueprint(categorias_bp,  url_prefix="/api/categorias")
    app.register_blueprint(lutas_bp,       url_prefix="/api/lutas")
    app.register_blueprint(bracket_bp,     url_prefix="/bracket")
    app.register_blueprint(mesa_bp,        url_prefix="/mesa")
    app.register_blueprint(placar_bp,      url_prefix="/placar")
