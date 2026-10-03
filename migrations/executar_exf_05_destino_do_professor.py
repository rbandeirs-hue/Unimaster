#!/usr/bin/env python3
"""
EXF-05 — Exame de faixa: o professor escolhe a faixa de destino.

A regra de idade pode levar o aluno direto a uma faixa acima (salto), mas o
professor pode decidir outra — "pela idade iria para Amarela, mas vai fazer
para Azul". A escolha fica em exame_faixa_aluno:

  destino_programa_id  promoção de destino escolhida (exame_faixa_programa.id)
  destino_de_id        faixa do aluno quando a escolha foi feita — quando o
                       aluno muda de faixa, a escolha deixa de valer sozinha
  destino_motivo       observação do professor
  destino_por, destino_em

Aditiva. --reverter remove as colunas.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_exf_05_destino_do_professor.py            # simulação
  .venv/bin/python migrations/executar_exf_05_destino_do_professor.py --aplicar
  .venv/bin/python migrations/executar_exf_05_destino_do_professor.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = ["destino_programa_id", "destino_de_id", "destino_motivo", "destino_por", "destino_em"]


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
            print("✓ EXF-05 revertida.")
            return
        faltam = [c for c in COLUNAS if c not in existentes]
        print(f"• colunas a criar: {faltam or 'nenhuma'}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        if faltam:
            cur.execute("""ALTER TABLE exame_faixa_aluno
                ADD COLUMN destino_programa_id INT NULL,
                ADD COLUMN destino_de_id INT NULL,
                ADD COLUMN destino_motivo VARCHAR(160) NULL,
                ADD COLUMN destino_por INT NULL,
                ADD COLUMN destino_em DATETIME NULL""")
        conn.commit()
        print("✓ EXF-05 aplicada.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
