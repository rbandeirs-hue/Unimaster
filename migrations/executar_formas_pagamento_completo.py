#!/usr/bin/env python3
"""
Aplica migrações de formas de pagamento na ordem correta, de forma idempotente:

  1. add_formas_pagamento.sql          — tabela formas_pagamento (IF NOT EXISTS)
  2. add_formas_pagamento_catalogo.sql — catálogo + coluna id_catalogo + índices/FK
  3. ensure_formas_pagamento_columns.sql — id_forma_pagamento em mensalidade_aluno / receitas
  4. seed_formas_pagamento_todas_academias.sql — Dinheiro, PIX, Boleto por academia

Uso (raiz do projeto):
  .venv/bin/python migrations/executar_formas_pagamento_completo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

MIG_DIR = Path(__file__).resolve().parent


def _exec_script(cursor, conn, sql: str) -> None:
    """Executa SQL que pode ter várias instruções (PREPARE/EXECUTE etc.)."""
    try:
        for result in cursor.execute(sql, multi=True):
            if result and getattr(result, "with_rows", False):
                result.fetchall()
    except TypeError:
        cursor.execute(sql)
        if cursor.with_rows:
            cursor.fetchall()


def _table_exists(cursor, name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
        (name,),
    )
    return cursor.fetchone() is not None


def _column_exists(cursor, table: str, col: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
        """,
        (table, col),
    )
    return cursor.fetchone() is not None


def _index_exists(cursor, table: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s
        """,
        (table, index_name),
    )
    return cursor.fetchone() is not None


def _fk_exists(cursor, table: str, constraint: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = DATABASE() AND table_name = %s AND constraint_name = %s
        """,
        (table, constraint),
    )
    return cursor.fetchone() is not None


def run_file_statements(cursor, conn, path: Path) -> None:
    """Executa arquivo .sql linha a linha em blocos separados por ';' (sem procedure)."""
    raw = path.read_text(encoding="utf-8")
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        lines.append(line)
    text = "\n".join(lines)
    parts = [p.strip() for p in text.split(";") if p.strip()]
    for part in parts:
        cursor.execute(part)
        if cursor.with_rows:
            cursor.fetchall()


def main() -> int:
    print("Conectando...")
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro:", e)
        return 1

    conn.autocommit = False
    cur = conn.cursor(buffered=True)

    try:
        # --- 1) formas_pagamento base ---
        p = MIG_DIR / "add_formas_pagamento.sql"
        print(f"→ {p.name}")
        run_file_statements(cur, conn, p)
        conn.commit()

        # --- 2) Catálogo + alterações em formas_pagamento ---
        if not _table_exists(cur, "formas_pagamento_catalogo"):
            print("→ Criando formas_pagamento_catalogo...")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS formas_pagamento_catalogo (
                    id INT(11) NOT NULL AUTO_INCREMENT,
                    id_associacao INT(11) NOT NULL,
                    nome VARCHAR(80) NOT NULL,
                    ordem INT(11) NOT NULL DEFAULT 0,
                    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_cat_assoc_nome (id_associacao, nome),
                    INDEX idx_cat_assoc (id_associacao),
                    CONSTRAINT fk_cat_assoc FOREIGN KEY (id_associacao) REFERENCES associacoes (id)
                      ON DELETE CASCADE ON UPDATE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
                """
            )
            conn.commit()
            print("   OK.")
        else:
            print("→ formas_pagamento_catalogo já existe.")

        if not _column_exists(cur, "formas_pagamento", "id_catalogo"):
            print("→ Adicionando formas_pagamento.id_catalogo...")
            cur.execute(
                """
                ALTER TABLE formas_pagamento
                    ADD COLUMN id_catalogo INT(11) NULL DEFAULT NULL
                    COMMENT 'NULL = forma só desta academia (legado)'
                    AFTER id_academia
                """
            )
            conn.commit()
            print("   OK.")

        if not _index_exists(cur, "formas_pagamento", "idx_fp_catalogo"):
            print("→ Índice idx_fp_catalogo...")
            cur.execute(
                "ALTER TABLE formas_pagamento ADD INDEX idx_fp_catalogo (id_catalogo)"
            )
            conn.commit()

        if not _fk_exists(cur, "formas_pagamento", "fk_fp_catalogo"):
            print("→ FK fk_fp_catalogo...")
            cur.execute(
                """
                ALTER TABLE formas_pagamento
                    ADD CONSTRAINT fk_fp_catalogo FOREIGN KEY (id_catalogo)
                    REFERENCES formas_pagamento_catalogo (id)
                    ON DELETE CASCADE ON UPDATE CASCADE
                """
            )
            conn.commit()

        if not _index_exists(cur, "formas_pagamento", "uk_fp_acad_catalogo"):
            print("→ UNIQUE uk_fp_acad_catalogo...")
            cur.execute(
                """
                ALTER TABLE formas_pagamento
                    ADD UNIQUE KEY uk_fp_acad_catalogo (id_academia, id_catalogo)
                """
            )
            conn.commit()

        # --- 3) Colunas em mensalidade_aluno / receitas ---
        p = MIG_DIR / "ensure_formas_pagamento_columns.sql"
        print(f"→ {p.name}")
        ensure_sql = p.read_text(encoding="utf-8")
        _exec_script(cur, conn, ensure_sql)
        conn.commit()
        print("   OK.")

        # --- 4) Seed formas padrão ---
        p = MIG_DIR / "seed_formas_pagamento_todas_academias.sql"
        print(f"→ {p.name}")
        run_file_statements(cur, conn, p)
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM formas_pagamento")
        n = cur.fetchone()[0]
        print("-" * 50)
        print(f"Concluído. Linhas em formas_pagamento: {n}")

        cur.execute("SELECT COUNT(*) FROM formas_pagamento_catalogo")
        nc = cur.fetchone()[0]
        print(f"Linhas em formas_pagamento_catalogo: {nc}")

        return 0

    except Exception as e:
        conn.rollback()
        print("ERRO:", e)
        import traceback

        traceback.print_exc()
        return 2
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
