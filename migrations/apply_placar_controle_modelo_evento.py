"""Aplica add_placar_controle_modelo_evento.sql se a coluna ainda não existir.

Uso (na raiz do projeto): python migrations/apply_placar_controle_modelo_evento.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DatabaseUnavailableError, get_db_connection


def main():
    try:
        conn = get_db_connection()
    except DatabaseUnavailableError as e:
        print(e, file=sys.stderr)
        return 1
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'eventos_competicoes'
              AND COLUMN_NAME = 'placar_controle_modelo'
            """
        )
        if cur.fetchone()[0]:
            print("OK: coluna placar_controle_modelo já existe.")
            return 0
        cur.execute(
            """
            ALTER TABLE eventos_competicoes
              ADD COLUMN placar_controle_modelo VARCHAR(24) NOT NULL DEFAULT 'livre'
                COMMENT 'livre | unimaster (Controle 1) | martialmatch (Controle 2)'
            """
        )
        conn.commit()
        print("OK: coluna placar_controle_modelo criada.")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
