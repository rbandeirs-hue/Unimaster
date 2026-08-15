#!/usr/bin/env python3
"""
Cria a tabela pagamento_links (links curtos de pagamento).

DDL fonte: migrations/add_pagamento_links.sql
Idempotente: CREATE TABLE IF NOT EXISTS.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_pagamento_links.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402


def executar_migracao():
    sql_path = Path(__file__).resolve().parent / "add_pagamento_links.sql"
    if not sql_path.is_file():
        print(f"❌ Arquivo não encontrado: {sql_path}")
        sys.exit(1)

    ddl = sql_path.read_text(encoding="utf-8")

    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        cur.execute(ddl.strip())
        conn.commit()
        print("✓ Tabela pagamento_links criada ou já existente (IF NOT EXISTS).")
        print("✅ Migração concluída.")
    except Exception as e:
        conn.rollback()
        print("❌ Erro ao executar a migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar_migracao()
