#!/usr/bin/env python3
"""
AP-02 — Aula particular: tipo de cobrança e cobrança no aluno.

  aula_particular.tipo_cobranca   'mensal' (valor fixo por mês) ou 'por_aula'
                                  (valor por aula × aulas dadas no mês)
  aula_particular.valor_mensal    valor do mês, quando a cobrança é mensal
  aula_particular.dia_vencimento  dia do mês em que a cobrança vence

  aula_particular_cobranca        uma linha por aula particular por mês
                                  (competência AAAA-MM), apontando para a
                                  cobrança gerada em `cobranca_avulsa` — é a
                                  trava que impede cobrar o mesmo mês duas vezes.

A cobrança vai para `cobranca_avulsa` (aparece em "Minhas mensalidades" do
aluno e em Financeiro › Mensalidades por aluno, com lembrete e PIX). A
mensalidade de plano (`mensalidade_aluno`) exige um plano cadastrado, e aula
particular não é plano.

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_ap_02_cobranca_particular.py            # simulação
  .venv/bin/python migrations/executar_ap_02_cobranca_particular.py --aplicar
  .venv/bin/python migrations/executar_ap_02_cobranca_particular.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = [
    ("tipo_cobranca", "ADD COLUMN tipo_cobranca VARCHAR(10) NOT NULL DEFAULT 'por_aula' "
                      "COMMENT 'mensal ou por_aula'"),
    ("valor_mensal", "ADD COLUMN valor_mensal DECIMAL(10,2) NULL COMMENT 'Valor do mês (cobrança mensal)'"),
    ("dia_vencimento", "ADD COLUMN dia_vencimento TINYINT NULL COMMENT 'Dia do vencimento (1-28)'"),
]
TABELA = """
CREATE TABLE IF NOT EXISTS aula_particular_cobranca (
  id                  INT AUTO_INCREMENT PRIMARY KEY,
  aula_particular_id  INT           NOT NULL,
  competencia         CHAR(7)       NOT NULL COMMENT 'AAAA-MM',
  cobranca_avulsa_id  INT           NULL,
  qtd_aulas           INT           NULL,
  valor               DECIMAL(10,2) NOT NULL,
  gerado_por          INT           NULL,
  gerado_em           TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em       TIMESTAMP     NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_apc_aula_comp (aula_particular_id, competencia),
  KEY ix_apc_cobranca (cobranca_avulsa_id),
  CONSTRAINT fk_apc_aula FOREIGN KEY (aula_particular_id) REFERENCES aula_particular (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _tem_coluna(cur, coluna):
    cur.execute("""SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = 'aula_particular' AND COLUMN_NAME = %s""", (coluna,))
    return cur.fetchone() is not None


def _tem_tabela(cur):
    cur.execute("SHOW TABLES LIKE 'aula_particular_cobranca'")
    return cur.fetchone() is not None


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if "--reverter" in sys.argv:
            if _tem_tabela(cur):
                cur.execute("DROP TABLE aula_particular_cobranca")
                print("✓ Tabela aula_particular_cobranca removida.")
            for col, _ddl in COLUNAS:
                if _tem_coluna(cur, col):
                    cur.execute(f"ALTER TABLE aula_particular DROP COLUMN {col}")
                    print(f"✓ aula_particular.{col} removida.")
            conn.commit()
            return
        if "--aplicar" not in sys.argv:
            print("AP-02 — simulação (nada foi gravado)\n")
            for col, _ddl in COLUNAS:
                print(f"  aula_particular.{col}: {'já existe' if _tem_coluna(cur, col) else 'será criada'}")
            print(f"  tabela aula_particular_cobranca: {'já existe' if _tem_tabela(cur) else 'será criada'}")
            cur.execute("SELECT COUNT(*) FROM aula_particular WHERE aluno_id IS NULL")
            print(f"  particulares com aluno de fora (sem cadastro): {cur.fetchone()[0]}")
            print("\nPara aplicar:  --aplicar")
            return
        for col, ddl in COLUNAS:
            if _tem_coluna(cur, col):
                print(f"• aula_particular.{col} já existia.")
            else:
                cur.execute(f"ALTER TABLE aula_particular {ddl}")
                conn.commit()
                print(f"✓ aula_particular.{col} criada.")
        existia = _tem_tabela(cur)
        cur.execute(TABELA)
        conn.commit()
        print(f"{'•' if existia else '✓'} Tabela aula_particular_cobranca {'já existia' if existia else 'criada'}.")
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
