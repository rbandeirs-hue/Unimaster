# -*- coding: utf-8 -*-
"""Aplica migrações de chave (bracket + chave inteligente) de forma idempotente."""
import os
import sys

# Raiz do projeto (pasta pai de migrations/)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import get_db_connection, DatabaseUnavailableError  # noqa: E402


def _cnt(cur, sql, params):
    cur.execute(sql, params)
    r = cur.fetchone()
    if isinstance(r, dict):
        return int(next(iter(r.values())))
    return int(r[0])


def has_column(cur, table: str, column: str) -> bool:
    return (
        _cnt(
            cur,
            """
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
            """,
            (table, column),
        )
        > 0
    )


def has_constraint(cur, name: str) -> bool:
    return (
        _cnt(
            cur,
            """
            SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = %s
            """,
            (name,),
        )
        > 0
    )


def has_index(cur, table: str, index: str) -> bool:
    return (
        _cnt(
            cur,
            """
            SELECT COUNT(*) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s
            """,
            (table, index),
        )
        > 0
    )


def has_table(cur, name: str) -> bool:
    return (
        _cnt(
            cur,
            """
            SELECT COUNT(*) FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            (name,),
        )
        > 0
    )


def main():
    try:
        conn = get_db_connection()
    except DatabaseUnavailableError as e:
        print(e)
        return 1
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT DATABASE() AS db")
        dbname = cur.fetchone()
        dbname = (dbname or {}).get("db") or "?"
        print(f"Banco: {dbname}")

        if not has_table(cur, "judo_lutas"):
            print("Tabela judo_lutas não existe. Execute antes migrations/add_placar_judo.sql.")
            return 1

        # --- add_bracket_judo.sql ---
        bracket_cols = [
            ("round", "TINYINT UNSIGNED DEFAULT 1 COMMENT '1=1ª rodada, 2=semi, 3=final'"),
            ("posicao_rodada", "SMALLINT UNSIGNED DEFAULT 0 COMMENT 'Posição na rodada'"),
            ("luta_origem_branco_id", "INT NULL COMMENT 'Luta cujo vencedor é o atleta branco aqui'"),
            ("luta_origem_azul_id", "INT NULL COMMENT 'Luta cujo vencedor é o atleta azul aqui'"),
        ]
        for col, definition in bracket_cols:
            if not has_column(cur, "judo_lutas", col):
                cur.execute(f"ALTER TABLE judo_lutas ADD COLUMN {col} {definition}")
                conn.commit()
                print(f"+ coluna judo_lutas.{col}")
            else:
                print(f"  (ok) judo_lutas.{col}")

        if not has_constraint(cur, "fk_judo_luta_origem_branco"):
            cur.execute(
                """
                ALTER TABLE judo_lutas
                ADD CONSTRAINT fk_judo_luta_origem_branco
                FOREIGN KEY (luta_origem_branco_id) REFERENCES judo_lutas(id) ON DELETE SET NULL
                """
            )
            conn.commit()
            print("+ FK fk_judo_luta_origem_branco")
        else:
            print("  (ok) fk_judo_luta_origem_branco")

        if not has_constraint(cur, "fk_judo_luta_origem_azul"):
            cur.execute(
                """
                ALTER TABLE judo_lutas
                ADD CONSTRAINT fk_judo_luta_origem_azul
                FOREIGN KEY (luta_origem_azul_id) REFERENCES judo_lutas(id) ON DELETE SET NULL
                """
            )
            conn.commit()
            print("+ FK fk_judo_luta_origem_azul")
        else:
            print("  (ok) fk_judo_luta_origem_azul")

        if not has_index(cur, "judo_lutas", "idx_judo_lutas_bracket"):
            cur.execute(
                "CREATE INDEX idx_judo_lutas_bracket ON judo_lutas (evento_id, categoria_id, round, posicao_rodada)"
            )
            conn.commit()
            print("+ índice idx_judo_lutas_bracket")
        else:
            print("  (ok) idx_judo_lutas_bracket")

        # --- add_chave_inteligente_judo.sql ---
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS judo_bo3_series (
              id INT AUTO_INCREMENT PRIMARY KEY,
              evento_id INT NOT NULL,
              categoria_id INT NULL,
              categoria_nome VARCHAR(255) NULL,
              atleta_a_nome VARCHAR(255) NOT NULL,
              atleta_a_academia VARCHAR(255) NULL,
              atleta_b_nome VARCHAR(255) NOT NULL,
              atleta_b_academia VARCHAR(255) NULL,
              vitorias_a TINYINT UNSIGNED NOT NULL DEFAULT 0,
              vitorias_b TINYINT UNSIGNED NOT NULL DEFAULT 0,
              concluido TINYINT(1) NOT NULL DEFAULT 0,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_bo3_ev (evento_id),
              CONSTRAINT fk_bo3_ev FOREIGN KEY (evento_id) REFERENCES eventos_competicoes(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.commit()
        print("+ tabela judo_bo3_series (se não existia)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS judo_chave_feed (
              id INT AUTO_INCREMENT PRIMARY KEY,
              destino_luta_id INT NOT NULL,
              destino_lado ENUM('branco', 'azul') NOT NULL,
              tipo ENUM('vencedor', 'perdedor') NOT NULL,
              origem_luta_id INT NOT NULL,
              INDEX idx_dest (destino_luta_id),
              INDEX idx_orig (origem_luta_id),
              CONSTRAINT fk_feed_dest FOREIGN KEY (destino_luta_id) REFERENCES judo_lutas(id) ON DELETE CASCADE,
              CONSTRAINT fk_feed_orig FOREIGN KEY (origem_luta_id) REFERENCES judo_lutas(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.commit()
        print("+ tabela judo_chave_feed (se não existia)")

        intel_cols = [
            ("chave_sistema", "VARCHAR(32) NULL COMMENT 'bo3, round_robin, elim_rep'"),
            ("bo3_serie_id", "INT NULL"),
            ("chave_fase", "VARCHAR(48) NULL COMMENT 'principal, repescagem, terceiro, melhor_de_3'"),
        ]
        for col, definition in intel_cols:
            if not has_column(cur, "judo_lutas", col):
                cur.execute(f"ALTER TABLE judo_lutas ADD COLUMN {col} {definition}")
                conn.commit()
                print(f"+ coluna judo_lutas.{col}")
            else:
                print(f"  (ok) judo_lutas.{col}")

        if not has_constraint(cur, "fk_judo_bo3_serie"):
            cur.execute(
                """
                ALTER TABLE judo_lutas
                ADD CONSTRAINT fk_judo_bo3_serie
                FOREIGN KEY (bo3_serie_id) REFERENCES judo_bo3_series(id) ON DELETE SET NULL
                """
            )
            conn.commit()
            print("+ FK fk_judo_bo3_serie")
        else:
            print("  (ok) fk_judo_bo3_serie")

        print("Concluído.")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"Erro: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
