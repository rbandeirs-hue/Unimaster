#!/usr/bin/env python3
"""Cria tabela aniversario_live_eventos (modo live de aniversário)."""
from pathlib import Path

from config import get_db_connection


def main():
    sql_path = Path(__file__).resolve().parent / "create_aniversario_live_eventos.sql"
    sql = sql_path.read_text(encoding="utf-8")
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        conn.commit()
        print("OK: aniversario_live_eventos criada ou já existente.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
