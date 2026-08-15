#!/usr/bin/env python3
"""
Cria a tabela aniversario_mensagens (mensagens staff/aluno no card de aniversariantes).

DDL fonte: migrations/create_aniversario_mensagens.sql
Idempotente: CREATE TABLE IF NOT EXISTS.

Uso (na raiz do projeto):
  python3 migrations/executar_aniversario_mensagens.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402


def executar_migracao():
    sql_path = Path(__file__).resolve().parent / "create_aniversario_mensagens.sql"
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
        # Um único statement (CREATE … ;). Evita split por ";" que quebra com comentários iniciais "--".
        cur.execute(ddl.strip())
        conn.commit()
        print("✓ Tabela aniversario_mensagens criada ou já existente (IF NOT EXISTS).")
        print("✅ Migração concluída.")
    except Exception as e:
        conn.rollback()
        print(f"❌ Erro: {e}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar_migracao()
