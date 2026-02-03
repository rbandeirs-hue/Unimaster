import os
import mysql.connector

def get_db_connection():
    """Conexão MySQL — usa variáveis de ambiente ou fallback."""
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "unimaster"),
        password=os.environ.get("DB_PASSWORD", "Un1m@ster_2024"),
        database=os.environ.get("DB_NAME", "unimaster"),
    )

# Configurações de Email para redefinição de senha
MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "True").lower() == "true"
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
