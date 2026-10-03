#!/usr/bin/env python3
"""
PRE-01 — Plano de mensalidade da turma e aviso pós-aula experimental.

  turmas.mensalidade_id
      Qual plano de mensalidade a turma cobra. A modalidade sozinha não diz o
      preço: na mesma academia o Jiu-Jitsu pode ter "Infantil R$ 85" e "Adulto
      R$ 110". Com o plano na turma, a matrícula pública cobra o valor da
      mensalidade da turma escolhida, e a promoção do pré-cadastro já sugere o
      plano certo. NULL = a matrícula segue o valor fixo da academia, como antes.

  aulas_experimentais.pos_aula_enviado_em
      Quando saiu a mensagem de pós-aula (feedback + convite para matrícula).
      É a trava que impede o mesmo visitante de receber o convite duas vezes —
      a rotina diária roda de hora em hora.

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_pre_01_turma_plano_pos_aula.py            # simulação
  .venv/bin/python migrations/executar_pre_01_turma_plano_pos_aula.py --aplicar
  .venv/bin/python migrations/executar_pre_01_turma_plano_pos_aula.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = [
    ("turmas", "mensalidade_id",
     "ADD COLUMN mensalidade_id INT(11) NULL "
     "COMMENT 'Plano de mensalidade da turma; define o valor da matrícula pública'"),
    ("aulas_experimentais", "pos_aula_enviado_em",
     "ADD COLUMN pos_aula_enviado_em DATETIME NULL "
     "COMMENT 'Envio da mensagem de feedback + convite para matrícula'"),
]


def _tem_coluna(cur, tabela, coluna):
    cur.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (tabela, coluna))
    return cur.fetchone() is not None


def _tem_fk(cur, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
           WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_NAME = %s""", (nome,))
    return cur.fetchone() is not None


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if "--reverter" in sys.argv:
            if _tem_fk(cur, "fk_turma_mensalidade"):
                cur.execute("ALTER TABLE turmas DROP FOREIGN KEY fk_turma_mensalidade")
            for tabela, coluna, _ddl in COLUNAS:
                if _tem_coluna(cur, tabela, coluna):
                    cur.execute(f"ALTER TABLE {tabela} DROP COLUMN {coluna}")
                    print(f"✓ {tabela}.{coluna} removida.")
            conn.commit()
            return
        if "--aplicar" not in sys.argv:
            print("PRE-01 — simulação (nada foi gravado)\n")
            for tabela, coluna, _ddl in COLUNAS:
                print(f"  {tabela}.{coluna}: {'já existe' if _tem_coluna(cur, tabela, coluna) else 'será criada'}")
            print("\nPara aplicar:  --aplicar")
            return
        for tabela, coluna, ddl in COLUNAS:
            if _tem_coluna(cur, tabela, coluna):
                print(f"• {tabela}.{coluna} já existia.")
                continue
            cur.execute(f"ALTER TABLE {tabela} {ddl}")
            conn.commit()
            print(f"✓ {tabela}.{coluna} criada.")
        if not _tem_fk(cur, "fk_turma_mensalidade"):
            # Apagar um plano não pode apagar a turma: ela só perde o preço.
            cur.execute("ALTER TABLE turmas ADD CONSTRAINT fk_turma_mensalidade "
                        "FOREIGN KEY (mensalidade_id) REFERENCES mensalidades (id) ON DELETE SET NULL")
            conn.commit()
            print("✓ Chave estrangeira fk_turma_mensalidade criada.")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
