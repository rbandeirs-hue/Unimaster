#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cria a tabela registros_aula_presenca para salvar observações e plano por aula.

Uso recomendado:
    .venv/bin/python migrations/executar_add_registros_aula_presenca.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection


def _table_exists(cursor, table_name):
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        LIMIT 1
        """,
        (table_name,),
    )
    return cursor.fetchone() is not None


def executar_migracao():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if _table_exists(cursor, "registros_aula_presenca"):
            print("✓ Tabela registros_aula_presenca já existe.")
            return True

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS registros_aula_presenca (
                id INT(11) NOT NULL AUTO_INCREMENT,
                turma_id INT(11) NOT NULL,
                academia_id INT(11) NULL DEFAULT NULL,
                data_aula DATE NOT NULL,
                horario_aula TIME NOT NULL DEFAULT '00:00:00',
                observacao TEXT NULL DEFAULT NULL,
                plano_aula_texto LONGTEXT NULL DEFAULT NULL,
                plano_aula_arquivo VARCHAR(255) NULL DEFAULT NULL,
                plano_aula_arquivo_original VARCHAR(255) NULL DEFAULT NULL,
                responsavel_id INT(11) NULL DEFAULT NULL,
                responsavel_nome VARCHAR(255) NULL DEFAULT NULL,
                criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uk_registro_aula_turma_data_hora (turma_id, data_aula, horario_aula),
                KEY idx_registro_aula_data (data_aula),
                KEY idx_registro_aula_turma (turma_id),
                CONSTRAINT fk_registro_aula_turma FOREIGN KEY (turma_id) REFERENCES turmas (TurmaID) ON DELETE CASCADE,
                CONSTRAINT fk_registro_aula_academia FOREIGN KEY (academia_id) REFERENCES academias (id) ON DELETE SET NULL,
                CONSTRAINT fk_registro_aula_usuario FOREIGN KEY (responsavel_id) REFERENCES usuarios (id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
            """
        )
        conn.commit()
        print("✓ Tabela registros_aula_presenca criada com sucesso.")
        return True
    except Exception as e:
        print(f"✗ Erro na migração: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print("Executando migração: add_registros_aula_presenca")
    print("=" * 60)
    ok = executar_migracao()
    print("=" * 60)
    sys.exit(0 if ok else 1)
