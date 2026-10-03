#!/usr/bin/env python3
"""
MM-11 — Uma graduação por modalidade.

O aluno tinha uma faixa só (alunos.graduacao_id). Quem treina judô e jiu-jitsu
ficava com a faixa da última modalidade salva — a outra se perdia. A faixa
passa a morar no vínculo do aluno com a modalidade:

  aluno_modalidades.graduacao_id   faixa do aluno NAQUELA modalidade

alunos.graduacao_id continua existindo como a faixa da modalidade principal,
para as telas que ainda não foram adaptadas.

aluno_modalidades tinha linhas repetidas (240 em out/2026) e nenhuma chave
única. Com a faixa morando no vínculo, repetição vira ambiguidade: a migração
apaga as repetidas (fica a mais antiga) e cria UNIQUE (aluno_id, modalidade_id).

Preenchimento: a faixa atual vai para a modalidade dela (graduacao.modalidade_id).
Faixa genérica (sem modalidade) vai para o aluno que tem uma modalidade só. A
outra modalidade de quem treina duas fica sem faixa, para a academia informar.

Coluna e chave são aditivas; --reverter remove as duas. As linhas repetidas
apagadas não voltam (eram cópias exatas do mesmo vínculo).

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_11_graduacao_por_modalidade.py            # simulação
  .venv/bin/python migrations/executar_mm_11_graduacao_por_modalidade.py --aplicar
  .venv/bin/python migrations/executar_mm_11_graduacao_por_modalidade.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

PREENCHER_DA_MODALIDADE = """
    UPDATE aluno_modalidades am
    JOIN alunos a ON a.id = am.aluno_id
    JOIN graduacao g ON g.id = a.graduacao_id
    SET am.graduacao_id = a.graduacao_id
    WHERE am.graduacao_id IS NULL AND g.modalidade_id = am.modalidade_id
"""
PREENCHER_GENERICA = """
    UPDATE aluno_modalidades am
    JOIN alunos a ON a.id = am.aluno_id
    JOIN graduacao g ON g.id = a.graduacao_id
    SET am.graduacao_id = a.graduacao_id
    WHERE am.graduacao_id IS NULL AND g.modalidade_id IS NULL
      AND (SELECT COUNT(*) FROM aluno_modalidades x WHERE x.aluno_id = am.aluno_id) = 1
"""


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM aluno_modalidades")
        existentes = {r[0] for r in cur.fetchall()}
        if "--reverter" in sys.argv:
            if "graduacao_id" in existentes:
                cur.execute("ALTER TABLE aluno_modalidades DROP COLUMN graduacao_id")
            cur.execute("SHOW INDEX FROM aluno_modalidades WHERE Key_name = 'uq_aluno_modalidade'")
            if cur.fetchall():
                cur.execute("ALTER TABLE aluno_modalidades DROP INDEX uq_aluno_modalidade")
            conn.commit()
            print("✓ MM-11 revertida.")
            return
        print(f"• coluna graduacao_id: {'já existe' if 'graduacao_id' in existentes else 'a criar'}")
        cur.execute("""SELECT COUNT(*) FROM aluno_modalidades am JOIN alunos a ON a.id = am.aluno_id
                       JOIN graduacao g ON g.id = a.graduacao_id WHERE g.modalidade_id = am.modalidade_id""")
        print(f"• vínculos que recebem a faixa da própria modalidade: {cur.fetchone()[0]} (com repetidos)")
        cur.execute("""SELECT COUNT(DISTINCT am.id) FROM aluno_modalidades am JOIN aluno_modalidades k
                       ON k.aluno_id = am.aluno_id AND k.modalidade_id = am.modalidade_id AND k.id < am.id""")
        print(f"• vínculos repetidos a apagar: {cur.fetchone()[0]}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        cur.execute("""DELETE am FROM aluno_modalidades am
                       JOIN aluno_modalidades k ON k.aluno_id = am.aluno_id
                        AND k.modalidade_id = am.modalidade_id AND k.id < am.id""")
        print(f"• vínculos repetidos apagados: {cur.rowcount}")
        cur.execute("SHOW INDEX FROM aluno_modalidades WHERE Key_name = 'uq_aluno_modalidade'")
        if not cur.fetchall():
            cur.execute("ALTER TABLE aluno_modalidades ADD UNIQUE KEY uq_aluno_modalidade (aluno_id, modalidade_id)")
        if "graduacao_id" not in existentes:
            cur.execute("ALTER TABLE aluno_modalidades ADD COLUMN graduacao_id INT NULL")
        cur.execute(PREENCHER_DA_MODALIDADE)
        n1 = cur.rowcount
        cur.execute(PREENCHER_GENERICA)
        n2 = cur.rowcount
        conn.commit()
        print(f"✓ MM-11 aplicada. Faixas preenchidas: {n1} pela modalidade, {n2} genéricas.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
