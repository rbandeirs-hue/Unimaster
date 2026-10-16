import os
import mysql.connector


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
    """Conexão MySQL — usa variáveis de ambiente ou fallback."""
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "177.153.51.151"),
        user=os.environ.get("DB_USER", "unimaster"),
        password=os.environ.get("DB_PASSWORD", "Un1m@ster_2024"),
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
