#!/usr/bin/env python3
"""
Régua de cobrança de mensalidades.

Antes, o job diário mandava lembrete para TODA mensalidade vencida, todo dia,
até pagar. A régua troca isso por dias configurados (D-5, D-1, D0, D+3, D+7...):
o job continua rodando todo dia, mas só envia quando o dia bate com uma etapa.

  cobranca_regua_etapa  — as etapas por academia. `dias` é assinado: negativo é
                          antes do vencimento, 0 é no dia, positivo é depois.
                          `escopo` separa a régua individual (uma mensalidade em
                          aberto) da consolidada (várias vencidas, uma mensagem
                          só). `mensagem` sobrepõe o modelo do WhatsApp naquela
                          etapa; NULL usa o modelo de sempre.
  cobranca_regua_config — hora do envio e os limiares de consolidação e de
                          tratativa administrativa, por academia.

Sem linhas gravadas a academia roda com os padrões de `utils/regua_cobranca.py`
(D-5, D-1, D0, D+3, D+7, D+15, D+25), então a migração não precisa semear nada.

Em `alunos`, três colunas para suspender a cobrança de um aluno (acordo,
bolsa, negociação em curso) sem desligar a automação da academia inteira.

Também garante `whatsapp_envios`, a trava anti-duplicidade: ela existe desde o
aniversário, mas a régua depende dela para não repetir a etapa se o job rodar
duas vezes no mesmo dia.

Idempotente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_regua_cobranca.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TABELAS = [
    ("cobranca_regua_etapa", """
CREATE TABLE IF NOT EXISTS cobranca_regua_etapa (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  id_academia  INT          NOT NULL,
  escopo       VARCHAR(12)  NOT NULL DEFAULT 'individual',  -- individual | consolidada
  dias         INT          NOT NULL,                       -- <0 antes, 0 no vencimento, >0 depois
  ativo        TINYINT(1)   NOT NULL DEFAULT 1,
  mensagem     TEXT         NULL,                           -- NULL = usa o modelo do WhatsApp
  criado_em    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_regua_etapa (id_academia, escopo, dias),
  KEY ix_regua_etapa_academia (id_academia)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""),
    ("cobranca_regua_config", """
CREATE TABLE IF NOT EXISTS cobranca_regua_config (
  id_academia      INT        NOT NULL PRIMARY KEY,
  hora_envio       TINYINT    NOT NULL DEFAULT 9,
  consolidar_apos  TINYINT    NOT NULL DEFAULT 2,
  tratativa_apos   TINYINT    NOT NULL DEFAULT 3,
  atualizado_em    TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""),
    ("whatsapp_envios", """
CREATE TABLE IF NOT EXISTS whatsapp_envios (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  id_academia   INT          NOT NULL,
  tipo          VARCHAR(40)  NOT NULL,
  referencia_id INT          NOT NULL,
  data_ref      DATE         NOT NULL,
  enviado_em    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_whatsapp_envios (id_academia, tipo, referencia_id, data_ref),
  KEY ix_whatsapp_envios_data (data_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""),
]

COLUNAS = [
    ("alunos", "cobranca_suspensa",
     "ALTER TABLE alunos ADD COLUMN cobranca_suspensa TINYINT(1) NOT NULL DEFAULT 0"),
    ("alunos", "cobranca_suspensa_ate",
     "ALTER TABLE alunos ADD COLUMN cobranca_suspensa_ate DATE NULL"),
    ("alunos", "cobranca_suspensa_motivo",
     "ALTER TABLE alunos ADD COLUMN cobranca_suspensa_motivo VARCHAR(255) NULL"),
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

        for tabela, coluna, ddl in COLUNAS:
            cur.execute("SHOW COLUMNS FROM %s LIKE %%s" % tabela, (coluna,))
            if cur.fetchone():
                print(f"• Coluna {tabela}.{coluna} já existia.")
                continue
            cur.execute(ddl)
            conn.commit()
            print(f"✓ Coluna {tabela}.{coluna} criada.")

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
