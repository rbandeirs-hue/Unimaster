#!/usr/bin/env python3
"""
MM-12 — Data da graduação por modalidade e modalidade do campeonato.

1) aluno_modalidades.data_graduacao
   Desde a MM-11 a faixa é por modalidade, mas a data da última graduação
   (alunos.ultimo_exame_faixa) continuava uma só: a carência do judô era
   contada a partir da graduação de jiu-jitsu. A data passa a morar junto da
   faixa, no vínculo do aluno com a modalidade.

   Preenchimento: a modalidade da faixa principal recebe alunos.ultimo_exame_faixa;
   as demais, a data mais recente do histórico (aluno_graduacao) com aquela faixa.

2) eventos_competicoes.modalidade_id
   Campeonato sem modalidade não sabia qual faixa do aluno pré-preencher na
   inscrição. Opcional: evento sem modalidade segue como antes. Exames de faixa
   recebem judô (o módulo é só de judô).

Aditiva. --reverter remove as duas colunas.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_12_data_graduacao_e_modalidade_evento.py            # simulação
  .venv/bin/python migrations/executar_mm_12_data_graduacao_e_modalidade_evento.py --aplicar
  .venv/bin/python migrations/executar_mm_12_data_graduacao_e_modalidade_evento.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

DATA_DA_PRINCIPAL = """
    UPDATE aluno_modalidades am
    JOIN alunos a ON a.id = am.aluno_id
    SET am.data_graduacao = a.ultimo_exame_faixa
    WHERE am.data_graduacao IS NULL AND am.graduacao_id IS NOT NULL
      AND am.graduacao_id = a.graduacao_id AND a.ultimo_exame_faixa IS NOT NULL
"""
DATA_DO_HISTORICO = """
    UPDATE aluno_modalidades am
    JOIN (SELECT aluno_id, graduacao_id, MAX(data) AS ultima
          FROM aluno_graduacao GROUP BY aluno_id, graduacao_id) h
      ON h.aluno_id = am.aluno_id AND h.graduacao_id = am.graduacao_id
    SET am.data_graduacao = h.ultima
    WHERE am.data_graduacao IS NULL
"""
EXAMES_SAO_JUDO = """
    UPDATE eventos_competicoes
    SET modalidade_id = (SELECT id FROM modalidade WHERE nome IN ('Judô', 'Judo') ORDER BY id LIMIT 1)
    WHERE modalidade_id IS NULL AND COALESCE(exame_faixa, 0) = 1
"""


def _colunas(cur, tabela):
    cur.execute(f"SHOW COLUMNS FROM {tabela}")
    return {r[0] for r in cur.fetchall()}


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        am = _colunas(cur, "aluno_modalidades")
        ev = _colunas(cur, "eventos_competicoes")
        if "graduacao_id" not in am:
            print("✗ Rode antes a MM-11 (executar_mm_11_graduacao_por_modalidade.py).")
            return
        if "--reverter" in sys.argv:
            if "data_graduacao" in am:
                cur.execute("ALTER TABLE aluno_modalidades DROP COLUMN data_graduacao")
            if "modalidade_id" in ev:
                cur.execute("ALTER TABLE eventos_competicoes DROP COLUMN modalidade_id")
            conn.commit()
            print("✓ MM-12 revertida.")
            return
        print(f"• aluno_modalidades.data_graduacao: {'já existe' if 'data_graduacao' in am else 'a criar'}")
        print(f"• eventos_competicoes.modalidade_id: {'já existe' if 'modalidade_id' in ev else 'a criar'}")
        cur.execute("SELECT COUNT(*) FROM eventos_competicoes WHERE COALESCE(exame_faixa, 0) = 1")
        print(f"• exames de faixa que recebem judô: {cur.fetchone()[0]}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        if "data_graduacao" not in am:
            cur.execute("ALTER TABLE aluno_modalidades ADD COLUMN data_graduacao DATE NULL")
        if "modalidade_id" not in ev:
            cur.execute("ALTER TABLE eventos_competicoes ADD COLUMN modalidade_id INT NULL")
        cur.execute(DATA_DA_PRINCIPAL)
        n1 = cur.rowcount
        cur.execute(DATA_DO_HISTORICO)
        n2 = cur.rowcount
        cur.execute(EXAMES_SAO_JUDO)
        n3 = cur.rowcount
        conn.commit()
        print(f"✓ MM-12 aplicada. Datas: {n1} da faixa principal, {n2} do histórico. "
              f"Exames marcados como judô: {n3}.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
