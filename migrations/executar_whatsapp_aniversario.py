#!/usr/bin/env python3
"""
Aniversário via WhatsApp: coluna academias.whatsapp_aniversario + tabela whatsapp_envios.

DDL fonte: migrations/add_whatsapp_aniversario.sql
Idempotente: ignora a coluna se ela já existir; a tabela usa IF NOT EXISTS.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_whatsapp_aniversario.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNA = """
ALTER TABLE academias
  ADD COLUMN whatsapp_aniversario TINYINT(1) NOT NULL DEFAULT 0
"""

TABELA = """
CREATE TABLE IF NOT EXISTS whatsapp_envios (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  id_academia   INT          NOT NULL,
  tipo          VARCHAR(40)  NOT NULL,
  referencia_id INT          NOT NULL,
  data_ref      DATE         NOT NULL,
  enviado_em    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_whatsapp_envios (id_academia, tipo, referencia_id, data_ref),
  KEY ix_whatsapp_envios_data (data_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        try:
            cur.execute(COLUNA)
            conn.commit()
            print("✓ Coluna academias.whatsapp_aniversario criada.")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                conn.rollback()
                print("• Coluna academias.whatsapp_aniversario já existia.")
            else:
                raise

        cur.execute(TABELA)
        conn.commit()
        print("✓ Tabela whatsapp_envios criada ou já existente.")
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
