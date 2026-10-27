#!/usr/bin/env python3
"""
Chamada por foto: tabelas de liga/desliga por academia, consentimento e descritor do rosto.

DDL fonte: utils/chamada_foto.py (_DDL). Idempotente: CREATE TABLE IF NOT EXISTS.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_chamada_foto.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402
from utils.chamada_foto import garantir_tabelas  # noqa: E402


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)
    cur = conn.cursor()
    try:
        garantir_tabelas(cur)
        conn.commit()
        print("✓ Tabelas chamada_foto_academia, chamada_foto_consentimento e chamada_foto_descritor prontas.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar_migracao()
