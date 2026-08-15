#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection


def executar():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SHOW COLUMNS FROM graduacao LIKE 'modalidade_id'")
        if not cur.fetchone():
            cur.execute(
                """
                ALTER TABLE graduacao
                ADD COLUMN modalidade_id INT(11) NULL DEFAULT NULL
                COMMENT 'NULL = graduacao generica; preenchido = graduacao especifica da modalidade'
                AFTER categoria
                """
            )
            print("✅ Coluna graduacao.modalidade_id criada.")
        else:
            print("ℹ️ Coluna graduacao.modalidade_id já existe.")

        cur.execute("SHOW INDEX FROM graduacao WHERE Key_name = 'idx_graduacao_modalidade_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE graduacao ADD INDEX idx_graduacao_modalidade_id (modalidade_id)")
            print("✅ Índice idx_graduacao_modalidade_id criado.")
        else:
            print("ℹ️ Índice idx_graduacao_modalidade_id já existe.")

        cur.execute(
            """
            SELECT id
            FROM modalidade
            WHERE LOWER(REPLACE(nome, 'ô', 'o')) LIKE '%judo%'
            ORDER BY id
            LIMIT 1
            """
        )
        row = cur.fetchone()
        judo_id = row["id"] if row else None
        if not judo_id:
            cur.execute("SELECT id FROM modalidade WHERE id = 1 LIMIT 1")
            row = cur.fetchone()
            judo_id = row["id"] if row else None

        if judo_id:
            cur.execute(
                "UPDATE graduacao SET modalidade_id = %s WHERE modalidade_id IS NULL",
                (judo_id,),
            )
            print(f"✅ Graduações sem modalidade classificadas como Judô (modalidade_id={judo_id}).")
        else:
            print("⚠️ Modalidade Judô não encontrada; graduações permanecem sem modalidade.")

        conn.commit()
        print("✅ Migração concluída com sucesso.")
    except Exception as e:
        conn.rollback()
        print(f"❌ Erro ao executar migração: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar()
