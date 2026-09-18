#!/usr/bin/env python3
"""
Nome do desconto na mensalidade, para quando houver mais de um.

`mensalidade_aluno` guarda o desconto materializado em duas colunas:
`desconto_aplicado` (o valor) e `id_desconto` (qual foi). Com dois descontos
somados — Família + Pontualidade, por exemplo — não existe um `id_desconto`
único, e a tela mostrava o abatimento sem dizer de onde veio.

  desconto_descricao — os nomes somados, ex.: "Família + Desconto Pontualidade"

Preenchida só quando há mais de um; com um desconto só, `id_desconto` continua
mandando e nada muda.

Idempotente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mensalidade_descontos_nomes.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNA = "ALTER TABLE mensalidade_aluno ADD COLUMN desconto_descricao VARCHAR(255) NULL"


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
            print("✓ Coluna mensalidade_aluno.desconto_descricao criada.")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                conn.rollback()
                print("• Coluna mensalidade_aluno.desconto_descricao já existia.")
            else:
                raise
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
