#!/usr/bin/env python3
"""
EXF-03 — Exame de faixa: aluno que pode começar pela Laranja.

Regra da associação: faixa preta de jiu-jitsu ou formado em Educação Física
pode fazer o primeiro exame de judô direto para a faixa Laranja. Não há como
o sistema deduzir isso do cadastro — quem identifica é o professor. Esta
tabela guarda essa marcação, uma linha por aluno:

  exame_faixa_aluno   aluno_id, inicio_laranja, motivo, quem marcou e quando

As outras regras de salto (Cinza aos 6, Azul no ano dos 11, Amarela no ano
dos 15) dependem só da idade e ficam no código (utils/exame_faixa.py).

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_exf_03_inicio_laranja.py            # simulação
  .venv/bin/python migrations/executar_exf_03_inicio_laranja.py --aplicar
  .venv/bin/python migrations/executar_exf_03_inicio_laranja.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TABELA = """
CREATE TABLE IF NOT EXISTS exame_faixa_aluno (
  aluno_id        INT          NOT NULL PRIMARY KEY,
  inicio_laranja  TINYINT(1)   NOT NULL DEFAULT 0,
  motivo          VARCHAR(80)  NULL,
  marcado_por     INT          NULL,
  marcado_em      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_exf_aluno_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _tem_tabela(cur):
    cur.execute("SHOW TABLES LIKE 'exame_faixa_aluno'")
    return cur.fetchone() is not None


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        existe = _tem_tabela(cur)
        if "--reverter" in sys.argv:
            if existe:
                cur.execute("DROP TABLE exame_faixa_aluno")
                conn.commit()
                print("✓ Tabela exame_faixa_aluno removida.")
            else:
                print("• Tabela exame_faixa_aluno já não existia.")
        elif "--aplicar" in sys.argv:
            cur.execute(TABELA)
            conn.commit()
            print(f"{'•' if existe else '✓'} Tabela exame_faixa_aluno {'já existia' if existe else 'criada'}.")
        else:
            print("EXF-03 — simulação (nada foi gravado)\n")
            print(f"  tabela exame_faixa_aluno: {'já existe' if existe else 'será criada'}")
            print("\nPara aplicar:  --aplicar")
    except Exception as e:
        conn.rollback()
        print("Erro:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
