import os
from urllib.parse import quote_plus


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    _user = os.environ.get("DB_USER", "root")
    _pass = quote_plus(os.environ.get("DB_PASS", ""))
    _host = os.environ.get("DB_HOST", "localhost")
    _port = os.environ.get("DB_PORT", "3306")
    _name = os.environ.get("DB_NAME", "placar")

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{_user}:{_pass}@{_host}:{_port}/{_name}"
    )


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
