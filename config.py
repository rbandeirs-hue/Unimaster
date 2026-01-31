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
