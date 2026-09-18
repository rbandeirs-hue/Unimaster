#!/usr/bin/env python3
"""
Data de vencimento da matrícula, para ela entrar na régua de cobrança.

A régua trabalha com `data_vencimento`: é dela que sai o "faltam 5 dias",
"vence hoje", "venceu há 10 dias". A matrícula não tinha data nenhuma —
`pre_cadastro` guarda valor, status e link, mas nada que diga até quando pagar.
Sem isso não havia como cobrá-la automaticamente, e ninguém cobrava.

  pre_cadastro.matricula_vencimento — até quando a matrícula deve ser paga

Nas matrículas que já existem, a data é preenchida com a criação + PRAZO_DIAS.
É a única referência disponível e mantém o histórico coerente: matrícula antiga
já nasce vencida, que é a verdade.

Idempotente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_matricula_vencimento.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

# Prazo padrão para pagar a matrícula, contado da criação do pré-cadastro.
PRAZO_DIAS = 3

COLUNA = "ALTER TABLE pre_cadastro ADD COLUMN matricula_vencimento DATE NULL"

BACKFILL = f"""
UPDATE pre_cadastro
   SET matricula_vencimento = DATE_ADD(DATE(created_at), INTERVAL {PRAZO_DIAS} DAY)
 WHERE matricula_vencimento IS NULL
   AND matricula_valor IS NOT NULL
   AND created_at IS NOT NULL
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
            print("✓ Coluna pre_cadastro.matricula_vencimento criada.")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                conn.rollback()
                print("• Coluna pre_cadastro.matricula_vencimento já existia.")
            else:
                raise

        cur.execute(BACKFILL)
        conn.commit()
        print(f"✓ {cur.rowcount} matrícula(s) receberam vencimento "
              f"(criação + {PRAZO_DIAS} dias).")

        cur.execute(
            """SELECT COUNT(*) FROM pre_cadastro
               WHERE COALESCE(matricula_status,'') NOT IN ('pago','cancelado')
                 AND matricula_valor > 0 AND matricula_vencimento IS NOT NULL"""
        )
        print(f"• {cur.fetchone()[0]} matrícula(s) em aberto entram na régua.")
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
