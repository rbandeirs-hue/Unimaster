#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remove índice UNIQUE só em responsavel_financeiro_cpf (alunos e pre_cadastro).
O mesmo pai/responsável pode estar em vários alunos — CPF do responsável não deve ser único na tabela.

Use o Python do ambiente virtual do projeto:
    .venv/bin/python migrations/executar_drop_unique_responsavel_financeiro_cpf.py
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection


def _unique_single_column_indexes(cursor, table: str, column: str):
    cursor.execute(
        """
        SELECT DISTINCT INDEX_NAME
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME != 'PRIMARY'
          AND NON_UNIQUE = 0
        """,
        (table,),
    )
    to_drop = []
    for row in cursor.fetchall():
        iname = row["INDEX_NAME"]
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND INDEX_NAME = %s
            ORDER BY SEQ_IN_INDEX
            """,
            (table, iname),
        )
        cols = [r["COLUMN_NAME"] for r in cursor.fetchall()]
        if cols == [column]:
            to_drop.append(iname)
    return to_drop


def _table_exists(cursor, table: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1
        """,
        (table,),
    )
    return cursor.fetchone() is not None


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table, column),
    )
    return cursor.fetchone() is not None


def executar():
    conn = None
    cur = None
    col = "responsavel_financeiro_cpf"
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        total = 0
        for table in ("alunos", "pre_cadastro"):
            if not _table_exists(cur, table) or not _column_exists(cur, table, col):
                print(f"  (pula) {table}: tabela ou coluna {col} inexistente")
                continue
            for iname in _unique_single_column_indexes(cur, table, col):
                if not re.match(r"^[a-zA-Z0-9_]+$", iname):
                    print(f"  (ignora nome de índice inválido: {iname!r})")
                    continue
                cur.execute(f"ALTER TABLE `{table}` DROP INDEX `{iname}`")
                print(f"✓ {table}: removido índice único `{iname}` em {col}")
                total += 1
        conn.commit()
        if total == 0:
            print("✓ Nenhum índice único exclusivo em responsavel_financeiro_cpf encontrado (já ok).")
        return True
    except Exception as e:
        print(f"✗ Erro: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print("Migração: permitir mesmo CPF de responsável financeiro em vários alunos")
    print("=" * 60)
    ok = executar()
    print("=" * 60)
    sys.exit(0 if ok else 1)
