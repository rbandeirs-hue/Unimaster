import os
import mysql.connector

# Credenciais só no .env (fora do git). Carregado aqui para valer também em
# scripts e migrações que importam config sem passar pelo app.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass


class DatabaseUnavailableError(Exception):
    """Compatibilidade com blueprints de competição quando o banco não responde."""

    pass


# Tempo máximo para ABRIR a conexão. Sem isto, um banco que aceita o TCP mas
# não completa o handshake deixa o pedido pendurado até o timeout do sistema —
# foi o que aconteceu em 16/10/2026, quando uma atualização automática do
# MariaDB travou o serviço por horas. São três workers: bastam três pedidos
# presos para o site inteiro parar de responder, e a tela de login fica
# "rodando e nada" em vez de dar erro.
#
# Vale só para a abertura: consulta demorada continua podendo demorar.
DB_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "5"))


def get_db_connection():
    """Conexão MySQL — credenciais do .env (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME)."""
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        user=os.environ.get("DB_USER", "unimaster"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "unimaster"),
        connection_timeout=DB_CONNECT_TIMEOUT,
    )


# Configurações de Email para redefinição de senha
MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "True").lower() == "true"
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
