#!/usr/bin/env python3
"""
Histórico de graduação do aluno.

A ficha montava a lista de graduações a partir de `examefaixa_judo` (o módulo de
exame de faixa do judô, que está vazio) e, no fim, acrescentava sempre uma linha
"Faixa Branca — data da matrícula". Quem entrou na academia já graduado aparecia
com uma faixa branca que nunca existiu, e não havia onde registrar a graduação
real: o botão "Registrar graduação" levava para a edição do aluno, que só troca a
faixa ATUAL e não guarda de onde ela veio.

  aluno_graduacao — uma linha por graduação, com a data em que aconteceu

Independente do módulo de exame: serve para academia de qualquer modalidade e
para lançar o histórico antigo de quem chegou graduado.

Idempotente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_aluno_graduacao.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TABELA = """
CREATE TABLE IF NOT EXISTS aluno_graduacao (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  aluno_id      INT           NOT NULL,
  graduacao_id  INT           NULL,
  faixa         VARCHAR(50)   NOT NULL,
  grau          VARCHAR(20)   NULL,
  data          DATE          NOT NULL,
  origem        VARCHAR(40)   NOT NULL DEFAULT 'Registro manual',
  observacao    VARCHAR(255)  NULL,
  registrado_por INT          NULL,
  criado_em     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_aluno_graduacao_aluno (aluno_id, data),
  KEY ix_aluno_graduacao_grad (graduacao_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        cur.execute("SHOW TABLES LIKE 'aluno_graduacao'")
        existia = cur.fetchone() is not None
        cur.execute(TABELA)
        conn.commit()
        print(f"{'•' if existia else '✓'} Tabela aluno_graduacao "
              f"{'já existia' if existia else 'criada'}.")

        # Quem já tem faixa e data da última graduação no cadastro entra no
        # histórico: é informação real que estava lá, só sem linha do tempo.
        cur.execute(
            """INSERT INTO aluno_graduacao (aluno_id, graduacao_id, faixa, grau, data, origem)
               SELECT a.id, a.graduacao_id, g.faixa, g.graduacao, a.ultimo_exame_faixa,
                      'Cadastro'
               FROM alunos a
               JOIN graduacao g ON g.id = a.graduacao_id
               WHERE a.ultimo_exame_faixa IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM aluno_graduacao ag WHERE ag.aluno_id = a.id)"""
        )
        conn.commit()
        print(f"✓ {cur.rowcount} graduação(ões) do cadastro migrada(s) para o histórico.")
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
