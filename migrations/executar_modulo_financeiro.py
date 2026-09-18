#!/usr/bin/env python3
"""
Academia com ou sem módulo financeiro.

Nem toda academia usa o sistema para cobrar: algumas querem só o acadêmico —
alunos, turmas, presença, graduação — e mantêm o financeiro por fora. Até aqui
não havia como dizer isso, e as telas de mensalidade, cobrança e relatório
ficavam à vista de todo mundo.

  academias.modulo_financeiro — 1 (padrão) gere financeiro e acadêmico
                                0 só acadêmico; o financeiro some do menu e as
                                  rotas passam a recusar acesso

Nasce com 1 para não mudar o comportamento de nenhuma academia existente.

Idempotente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_modulo_financeiro.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNA = """
ALTER TABLE academias
  ADD COLUMN modulo_financeiro TINYINT(1) NOT NULL DEFAULT 1
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
            print("✓ Coluna academias.modulo_financeiro criada (padrão: 1 = com financeiro).")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                conn.rollback()
                print("• Coluna academias.modulo_financeiro já existia.")
            else:
                raise
        cur.execute("SELECT COUNT(*) FROM academias WHERE COALESCE(modulo_financeiro,1)=1")
        print(f"• {cur.fetchone()[0]} academia(s) com o financeiro ligado.")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro na migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar_migracao()
