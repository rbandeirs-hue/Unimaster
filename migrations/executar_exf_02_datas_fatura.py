#!/usr/bin/env python3
"""
EXF-02 — Exame de faixa: dia da prova, prazo de pagamento e fatura.

Na EXF-01 o exame reaproveitava as duas datas do evento: início = dia da
prova, fim = prazo de inscrição. Faltava onde dizer quando as inscrições
ABREM e até quando se PAGA. Agora:

  data_inicio                 abertura das inscrições (como em qualquer evento)
  data_fim                    encerramento das inscrições
  exame_data_prova            dia e hora da prova — é o que vai para o calendário
  exame_prazo_pagamento       vencimento da fatura do exame
  exame_gera_fatura           1 = ao se inscrever, o aluno recebe uma cobrança
                              avulsa "Exame de faixa — de → para" no valor da
                              tabela de preços

Exame já cadastrado com a regra antiga (início = prova) recebe a data da
prova a partir do início, para não perder a informação.

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_exf_02_datas_fatura.py            # simulação
  .venv/bin/python migrations/executar_exf_02_datas_fatura.py --aplicar
  .venv/bin/python migrations/executar_exf_02_datas_fatura.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = [
    ("exame_data_prova",
     "ADD COLUMN exame_data_prova DATETIME NULL COMMENT 'Exame de faixa: dia e hora da prova'"),
    ("exame_prazo_pagamento",
     "ADD COLUMN exame_prazo_pagamento DATE NULL COMMENT 'Exame de faixa: vencimento da fatura'"),
    ("exame_gera_fatura",
     "ADD COLUMN exame_gera_fatura TINYINT(1) NOT NULL DEFAULT 1 "
     "COMMENT 'Exame de faixa: 1 = inscrição gera cobrança avulsa'"),
]


def _tem_coluna(cur, coluna):
    cur.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'eventos_competicoes'
             AND COLUMN_NAME = %s""", (coluna,))
    return cur.fetchone() is not None


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("EXF-02 — simulação (nada foi gravado)\n")
        for nome, _ddl in COLUNAS:
            print(f"  eventos_competicoes.{nome:<24}: {'já existe' if _tem_coluna(cur, nome) else 'será criada'}")
        cur.execute("SELECT COUNT(*) AS n FROM eventos_competicoes WHERE exame_faixa = 1")
        print(f"  exames já cadastrados           : {cur.fetchone()['n']}")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close()
        conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        novas = []
        for nome, ddl in COLUNAS:
            if _tem_coluna(cur, nome):
                print(f"• Coluna {nome} já existia.")
                continue
            cur.execute(f"ALTER TABLE eventos_competicoes {ddl}")
            conn.commit()
            novas.append(nome)
            print(f"✓ Coluna {nome} criada.")
        if "exame_data_prova" in novas:
            cur.execute(
                """UPDATE eventos_competicoes SET exame_data_prova = data_inicio
                   WHERE exame_faixa = 1 AND exame_data_prova IS NULL AND data_inicio IS NOT NULL""")
            print(f"✓ {cur.rowcount} exame(s) antigo(s) com a prova copiada do início.")
            conn.commit()
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro na migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for nome, _ddl in COLUNAS:
            if _tem_coluna(cur, nome):
                cur.execute(f"ALTER TABLE eventos_competicoes DROP COLUMN {nome}")
                conn.commit()
                print(f"✓ Coluna {nome} removida.")
    except Exception as e:
        conn.rollback()
        print("Erro na reversão:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    elif "--aplicar" in sys.argv:
        executar_migracao()
    else:
        simular()
