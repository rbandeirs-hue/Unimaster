#!/usr/bin/env python3
"""
Pacote (plano de mensalidade) padrão do aluno: `alunos.plano_mensalidade_id`.

DDL: embutida aqui (o .gitignore ignora *.sql, então o runner não depende do
arquivo estar presente). Cópia legível em migrations/add_aluno_plano_padrao.sql.
Idempotente: coluna e índice já existentes são pulados.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_add_aluno_plano_padrao.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

DDL = [
    # A geração mensal replica o mensalidade_id da última cobrança; sem esta
    # coluna, trocar de pacote só valia depois de alguém editar uma cobrança.
    """ALTER TABLE alunos
         ADD COLUMN plano_mensalidade_id INT(11) NULL DEFAULT NULL
         COMMENT 'Pacote padrão do aluno (mensalidades.id). NULL = herda da última cobrança'""",
    "ALTER TABLE alunos ADD INDEX idx_alunos_plano_mensalidade (plano_mensalidade_id)",
]

JA_EXISTE = ("duplicate column", "duplicate key name")


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("❌ Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        for comando in DDL:
            limpo = " ".join(comando.split())
            try:
                cur.execute(comando)
                conn.commit()
                print(f"✓ {limpo[:80]}")
            except Exception as err:
                if any(m in str(err).lower() for m in JA_EXISTE):
                    print(f"ℹ Já existe, pulando: {limpo[:80]}")
                    conn.rollback()
                else:
                    raise

        cur2 = conn.cursor(dictionary=True)
        cur2.execute("DESCRIBE alunos")
        if not any(c["Field"] == "plano_mensalidade_id" for c in cur2.fetchall()):
            cur2.close()
            print("⚠ Coluna alunos.plano_mensalidade_id não encontrada após a migração")
            sys.exit(1)
        cur2.close()
        print("✅ Migração concluída.")
    except Exception as e:
        conn.rollback()
        print("❌ Erro ao executar a migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar_migracao()
