#!/usr/bin/env python3
"""
AP-01 — Aula particular.

  aula_particular            o combinado: professor, aluno, dias da semana,
                             horário, local, período e valor por aula.
                             O aluno pode ser da academia (aluno_id) ou de fora
                             (aluno_nome + telefone) — particular é muitas vezes
                             a porta de entrada de quem ainda não é aluno.
  aula_particular_registro   cada aula dada: data, horário, situação
                             (realizada, falta, cancelada, remarcada) e o que
                             foi trabalhado. Uma linha por aula por dia.

dias_semana segue o padrão de `turmas.dias_semana`: 0=Dom … 6=Sáb, "1,3,5".

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_ap_01_aula_particular.py            # simulação
  .venv/bin/python migrations/executar_ap_01_aula_particular.py --aplicar
  .venv/bin/python migrations/executar_ap_01_aula_particular.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TABELAS = [
    ("aula_particular", """
CREATE TABLE IF NOT EXISTS aula_particular (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  academia_id    INT           NOT NULL,
  professor_id   INT           NOT NULL,
  aluno_id       INT           NULL,
  aluno_nome     VARCHAR(150)  NULL COMMENT 'Aluno de fora da academia',
  aluno_telefone VARCHAR(30)   NULL,
  modalidade_id  INT           NULL,
  dias_semana    VARCHAR(20)   NOT NULL COMMENT '0=Dom..6=Sáb, ex.: 1,3',
  hora_inicio    TIME          NOT NULL,
  hora_fim       TIME          NOT NULL,
  local          VARCHAR(150)  NULL,
  valor_aula     DECIMAL(10,2) NULL,
  data_inicio    DATE          NOT NULL,
  data_fim       DATE          NULL,
  ativo          TINYINT(1)    NOT NULL DEFAULT 1,
  observacoes    TEXT          NULL,
  criado_por     INT           NULL,
  criado_em      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em  TIMESTAMP     NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  KEY ix_ap_academia (academia_id, ativo),
  KEY ix_ap_professor (professor_id, ativo),
  KEY ix_ap_aluno (aluno_id),
  CONSTRAINT fk_ap_academia FOREIGN KEY (academia_id) REFERENCES academias (id) ON DELETE CASCADE,
  CONSTRAINT fk_ap_professor FOREIGN KEY (professor_id) REFERENCES professores (id) ON DELETE CASCADE,
  CONSTRAINT fk_ap_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE SET NULL,
  CONSTRAINT fk_ap_modalidade FOREIGN KEY (modalidade_id) REFERENCES modalidade (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""),
    ("aula_particular_registro", """
CREATE TABLE IF NOT EXISTS aula_particular_registro (
  id                  INT AUTO_INCREMENT PRIMARY KEY,
  aula_particular_id  INT          NOT NULL,
  data                DATE         NOT NULL,
  hora_inicio         TIME         NULL,
  hora_fim            TIME         NULL,
  status              VARCHAR(12)  NOT NULL DEFAULT 'realizada'
                      COMMENT 'realizada, falta, cancelada, remarcada',
  conteudo            TEXT         NULL COMMENT 'O que foi trabalhado na aula',
  registrado_por      INT          NULL,
  criado_em           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em       TIMESTAMP    NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_apr_aula_data (aula_particular_id, data),
  KEY ix_apr_data (data),
  CONSTRAINT fk_apr_aula FOREIGN KEY (aula_particular_id)
    REFERENCES aula_particular (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""),
]


def _tem(cur, tabela):
    cur.execute("SHOW TABLES LIKE %s", (tabela,))
    return cur.fetchone() is not None


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if "--reverter" in sys.argv:
            for nome, _ddl in reversed(TABELAS):
                if _tem(cur, nome):
                    cur.execute(f"DROP TABLE {nome}")
                    print(f"✓ Tabela {nome} removida.")
            conn.commit()
            return
        if "--aplicar" not in sys.argv:
            print("AP-01 — simulação (nada foi gravado)\n")
            for nome, _ddl in TABELAS:
                print(f"  {nome}: {'já existe' if _tem(cur, nome) else 'será criada'}")
            print("\nPara aplicar:  --aplicar")
            return
        for nome, ddl in TABELAS:
            existia = _tem(cur, nome)
            cur.execute(ddl)
            conn.commit()
            print(f"{'•' if existia else '✓'} Tabela {nome} {'já existia' if existia else 'criada'}.")
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
