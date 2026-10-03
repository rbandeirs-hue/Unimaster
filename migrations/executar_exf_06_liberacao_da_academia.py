#!/usr/bin/env python3
"""
EXF-06 — Exame de faixa: o responsável da academia libera o aluno.

Quem ainda não cumpre idade mínima ou carência fica "Aguardando" e não entra
no exame. O responsável da academia pode liberar o aluno mesmo assim — ele
passa a contar como apto, com a pendência mantida como aviso. A liberação fica
em exame_faixa_aluno:

  liberado_de_id   faixa do aluno quando foi liberado — promovido, a
                   liberação deixa de valer sozinha
  liberado_motivo  justificativa do responsável
  liberado_por, liberado_em

Aditiva. --reverter remove as colunas.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_exf_06_liberacao_da_academia.py            # simulação
  .venv/bin/python migrations/executar_exf_06_liberacao_da_academia.py --aplicar
  .venv/bin/python migrations/executar_exf_06_liberacao_da_academia.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = ["liberado_de_id", "liberado_motivo", "liberado_por", "liberado_em"]


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM exame_faixa_aluno")
        existentes = {r[0] for r in cur.fetchall()}
        if "--reverter" in sys.argv:
            for c in COLUNAS:
                if c in existentes:
                    cur.execute(f"ALTER TABLE exame_faixa_aluno DROP COLUMN {c}")
            conn.commit()
            print("✓ EXF-06 revertida.")
            return
        faltam = [c for c in COLUNAS if c not in existentes]
        print(f"• colunas a criar: {faltam or 'nenhuma'}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        if faltam:
            cur.execute("""ALTER TABLE exame_faixa_aluno
                ADD COLUMN liberado_de_id INT NULL,
                ADD COLUMN liberado_motivo VARCHAR(160) NULL,
                ADD COLUMN liberado_por INT NULL,
                ADD COLUMN liberado_em DATETIME NULL""")
        conn.commit()
        print("✓ EXF-06 aplicada.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
