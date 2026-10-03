#!/usr/bin/env python3
"""
AP-03 — Aula particular cobrada por plano de mensalidade (mensal ou diária).

Na AP-02 a cobrança da particular saía como cobrança avulsa, com valor
digitado na própria particular. Agora ela usa um PLANO (`mensalidades`) e gera
MENSALIDADE do aluno (`mensalidade_aluno`), como qualquer outra:

  mensalidades.periodicidade        já existia ('mensal'); ganha 'diaria' — o
                                    valor do plano é por aula/dia
  aula_particular.mensalidade_id    plano usado pela particular
  aula_particular_cobranca.mensalidade_aluno_id
                                    a mensalidade gerada no mês (a coluna
                                    cobranca_avulsa_id fica para o histórico
                                    do que foi gerado antes)

Particulares já cadastradas (cobrança avulsa) seguem funcionando até alguém
escolher um plano nelas.

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_ap_03_plano_particular.py            # simulação
  .venv/bin/python migrations/executar_ap_03_plano_particular.py --aplicar
  .venv/bin/python migrations/executar_ap_03_plano_particular.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = [
    ("aula_particular", "mensalidade_id",
     "ADD COLUMN mensalidade_id INT(11) NULL COMMENT 'Plano de mensalidade (mensal ou diária)'"),
    ("aula_particular_cobranca", "mensalidade_aluno_id",
     "ADD COLUMN mensalidade_aluno_id INT(11) NULL COMMENT 'Mensalidade gerada no mês'"),
]


def _tem_coluna(cur, tabela, coluna):
    cur.execute("""SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = %s AND COLUMN_NAME = %s""", (tabela, coluna))
    return cur.fetchone() is not None


def _tem_fk(cur, nome):
    cur.execute("""SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_NAME = %s""", (nome,))
    return cur.fetchone() is not None


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if "--reverter" in sys.argv:
            if _tem_fk(cur, "fk_ap_plano"):
                cur.execute("ALTER TABLE aula_particular DROP FOREIGN KEY fk_ap_plano")
            for tabela, coluna, _ddl in COLUNAS:
                if _tem_coluna(cur, tabela, coluna):
                    cur.execute(f"ALTER TABLE {tabela} DROP COLUMN {coluna}")
                    print(f"✓ {tabela}.{coluna} removida.")
            cur.execute("UPDATE mensalidades SET periodicidade = 'mensal' WHERE periodicidade = 'diaria'")
            print(f"✓ {cur.rowcount} plano(s) diário(s) voltaram a mensal.")
            conn.commit()
            return
        if "--aplicar" not in sys.argv:
            print("AP-03 — simulação (nada foi gravado)\n")
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
        if not _tem_fk(cur, "fk_ap_plano"):
            cur.execute("ALTER TABLE aula_particular ADD CONSTRAINT fk_ap_plano FOREIGN KEY (mensalidade_id) "
                        "REFERENCES mensalidades (id) ON DELETE SET NULL")
            conn.commit()
            print("✓ Chave estrangeira fk_ap_plano criada.")
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
