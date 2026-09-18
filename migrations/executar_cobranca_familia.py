#!/usr/bin/env python3
"""
Cobrança familiar: uma cobrança única para as mensalidades de irmãos.

Cria três tabelas:
  familia_cobranca     — a família marcada para cobrar junto (um registro por
                         responsável financeiro, por academia). Os membros NÃO
                         ficam gravados: são os alunos ativos daquela academia
                         com aquele CPF de responsável, então irmão que entra ou
                         sai entra e sai do grupo sozinho.
  cobranca_grupo       — a cobrança de um mês da família (valor, vencimento,
                         status e os campos do gateway).
  cobranca_grupo_item  — quais mensalidade_aluno aquela cobrança cobre. O índice
                         único no mensalidade_aluno_id impede a mesma mensalidade
                         de entrar em dois grupos e ser cobrada duas vezes.

Idempotente: tudo com IF NOT EXISTS.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_cobranca_familia.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TABELAS = [
    ("familia_cobranca", """
CREATE TABLE IF NOT EXISTS familia_cobranca (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  id_academia           INT           NOT NULL,
  responsavel_cpf       VARCHAR(14)   NOT NULL,
  responsavel_nome      VARCHAR(255)  NULL,
  responsavel_email     VARCHAR(255)  NULL,
  responsavel_telefone  VARCHAR(20)   NULL,
  ativo                 TINYINT(1)    NOT NULL DEFAULT 1,
  criado_em             TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em         TIMESTAMP     NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_familia_cobranca (id_academia, responsavel_cpf),
  KEY ix_familia_cobranca_academia (id_academia)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""),
    ("cobranca_grupo", """
CREATE TABLE IF NOT EXISTS cobranca_grupo (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  familia_id        INT            NOT NULL,
  id_academia       INT            NOT NULL,
  competencia       DATE           NOT NULL,
  data_vencimento   DATE           NOT NULL,
  valor_total       DECIMAL(10,2)  NOT NULL DEFAULT 0.00,
  valor_pago        DECIMAL(10,2)  NULL,
  data_pagamento    DATE           NULL,
  status            ENUM('pendente','pago','atrasado','cancelado') NOT NULL DEFAULT 'pendente',
  gateway           VARCHAR(20)    NULL,
  payment_id        VARCHAR(500)   NULL,
  link              TEXT           NULL,
  qrcode            MEDIUMTEXT     NULL,
  copia_cola        TEXT           NULL,
  criado_em         TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em     TIMESTAMP      NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_cobranca_grupo_mes (familia_id, competencia),
  KEY ix_cobranca_grupo_academia (id_academia),
  KEY ix_cobranca_grupo_status (status),
  KEY ix_cobranca_grupo_venc (data_vencimento)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""),
    ("cobranca_grupo_item", """
CREATE TABLE IF NOT EXISTS cobranca_grupo_item (
  id                   INT AUTO_INCREMENT PRIMARY KEY,
  grupo_id             INT            NOT NULL,
  mensalidade_aluno_id INT            NOT NULL,
  aluno_id             INT            NOT NULL,
  valor                DECIMAL(10,2)  NOT NULL DEFAULT 0.00,
  UNIQUE KEY uk_grupo_item_mensalidade (mensalidade_aluno_id),
  KEY ix_grupo_item_grupo (grupo_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""),
]


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        for nome, ddl in TABELAS:
            cur.execute("SHOW TABLES LIKE %s", (nome,))
            existia = cur.fetchone() is not None
            cur.execute(ddl)
            conn.commit()
            print(f"{'•' if existia else '✓'} Tabela {nome} "
                  f"{'já existia' if existia else 'criada'}.")
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
