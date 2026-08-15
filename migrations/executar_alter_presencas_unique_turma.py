#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Garante UNIQUE (aluno_id, turma_id, data_presenca, horario_aula) em presencas.
Sem isso, registros do mesmo dia podem sobrescrever chamadas de outra turma/horário.

No servidor, use o Python do virtualenv (onde está mysql-connector-python), não o python3 global:

    /var/www/Unimaster/.venv/bin/python migrations/executar_alter_presencas_unique_turma.py

Alternativa: mysql -u USER -p DB < migrations/alter_presencas_unique_turma.sql
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection


def _index_exists(cursor, name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'presencas' AND INDEX_NAME = %s
        """,
        (name,),
    )
    row = cursor.fetchone()
    return (row["c"] if isinstance(row, dict) else row[0]) > 0


def _column_exists(cursor, name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'presencas' AND COLUMN_NAME = %s
        """,
        (name,),
    )
    row = cursor.fetchone()
    return (row["c"] if isinstance(row, dict) else row[0]) > 0


def executar_migracao():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        if _index_exists(cur, "uk_presenca_aluno_turma_data_hora"):
            print("✓ Índice uk_presenca_aluno_turma_data_hora já existe — nada a fazer.")
            return True

        if not _column_exists(cur, "horario_aula"):
            cur.execute(
                """
                ALTER TABLE presencas
                ADD COLUMN horario_aula TIME NOT NULL DEFAULT '00:00:00' AFTER data_presenca
                """
            )
            print("✓ Coluna horario_aula criada em presencas.")

        cur.execute(
            """
            UPDATE presencas p
            INNER JOIN alunos a ON a.id = p.aluno_id
            SET p.turma_id = COALESCE(p.turma_id, a.TurmaID)
            WHERE p.turma_id IS NULL AND a.TurmaID IS NOT NULL
            """
        )
        if cur.rowcount:
            print(f"✓ Preenchidos turma_id em {cur.rowcount} registro(s) de presenças.")

        try:
            cur.execute(
                """
                UPDATE presencas p
                INNER JOIN turmas t ON t.TurmaID = p.turma_id
                SET p.horario_aula = COALESCE(t.hora_inicio, '00:00:00')
                WHERE (p.horario_aula IS NULL OR p.horario_aula = '00:00:00')
                """
            )
            if cur.rowcount:
                print(f"✓ Preenchido horario_aula em {cur.rowcount} registro(s).")
        except Exception as e:
            print(f"  (aviso) Não foi possível preencher horario_aula por turma: {e}")

        if _index_exists(cur, "uk_presenca_aluno_data"):
            cur.execute("ALTER TABLE presencas DROP INDEX uk_presenca_aluno_data")
            print("✓ Removido índice antigo uk_presenca_aluno_data.")
        if _index_exists(cur, "uk_presenca_aluno_turma_data"):
            cur.execute("ALTER TABLE presencas DROP INDEX uk_presenca_aluno_turma_data")
            print("✓ Removido índice antigo uk_presenca_aluno_turma_data.")

        cur.execute(
            """
            ALTER TABLE presencas
            ADD UNIQUE KEY uk_presenca_aluno_turma_data_hora (aluno_id, turma_id, data_presenca, horario_aula)
            """
        )
        print("✓ Criado uk_presenca_aluno_turma_data_hora (aluno_id, turma_id, data_presenca, horario_aula).")

        if not _index_exists(cur, "idx_presencas_turma"):
            try:
                cur.execute("ALTER TABLE presencas ADD INDEX idx_presencas_turma (turma_id)")
                print("✓ Criado idx_presencas_turma.")
            except Exception as e:
                print(f"  (aviso) idx_presencas_turma: {e}")
        if not _index_exists(cur, "idx_presencas_turma_data_hora"):
            try:
                cur.execute("ALTER TABLE presencas ADD INDEX idx_presencas_turma_data_hora (turma_id, data_presenca, horario_aula)")
                print("✓ Criado idx_presencas_turma_data_hora.")
            except Exception as e:
                print(f"  (aviso) idx_presencas_turma_data_hora: {e}")

        conn.commit()
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
    print("Migração: presencas únicas por aluno + turma + data + horário")
    print("=" * 60)
    ok = executar_migracao()
    print("=" * 60)
    sys.exit(0 if ok else 1)
