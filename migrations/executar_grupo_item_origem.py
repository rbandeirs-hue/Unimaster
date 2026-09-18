#!/usr/bin/env python3
"""
Cobrança familiar passa a juntar qualquer cobrança do aluno, não só mensalidade.

`cobranca_grupo_item` amarrava cada item a `mensalidade_aluno_id`. Uma família
com duas taxas avulsas — exame de faixa, uniforme — não podia ser unificada:
cada irmão recebia a sua cobrança separada, que é justamente o que o grupo veio
evitar.

O item passa a apontar para (origem, registro_id):

  origem       'mensalidade' ou 'avulsa'
  registro_id  o id na tabela da origem

A chave única muda de `mensalidade_aluno_id` para o par — o que continua
impedindo a mesma cobrança de entrar em dois grupos, agora sem confundir
mensalidade 5 com avulsa 5.

`mensalidade_aluno_id` fica na tabela, aceitando NULL, para não quebrar nada que
ainda leia a coluna antiga.

Idempotente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_grupo_item_origem.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402


def _tem_coluna(cur, tabela, coluna):
    cur.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (tabela, coluna),
    )
    return cur.fetchone() is not None


def _tem_indice(cur, tabela, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s""",
        (tabela, nome),
    )
    return cur.fetchone() is not None


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        if _tem_coluna(cur, "cobranca_grupo_item", "origem"):
            print("• Coluna origem já existia.")
        else:
            cur.execute("ALTER TABLE cobranca_grupo_item "
                        "ADD COLUMN origem VARCHAR(20) NOT NULL DEFAULT 'mensalidade'")
            conn.commit()
            print("✓ Coluna origem criada.")

        if _tem_coluna(cur, "cobranca_grupo_item", "registro_id"):
            print("• Coluna registro_id já existia.")
        else:
            cur.execute("ALTER TABLE cobranca_grupo_item ADD COLUMN registro_id INT NULL")
            conn.commit()
            print("✓ Coluna registro_id criada.")

        cur.execute("""UPDATE cobranca_grupo_item
                          SET registro_id = mensalidade_aluno_id
                        WHERE registro_id IS NULL AND mensalidade_aluno_id IS NOT NULL""")
        conn.commit()
        print(f"✓ {cur.rowcount} item(ns) migrado(s) para registro_id.")

        # A coluna antiga deixa de ser obrigatória: item de avulsa não tem
        # mensalidade nenhuma para apontar.
        cur.execute("ALTER TABLE cobranca_grupo_item MODIFY mensalidade_aluno_id INT NULL")
        conn.commit()
        print("✓ mensalidade_aluno_id agora aceita NULL.")

        if _tem_indice(cur, "cobranca_grupo_item", "uk_grupo_item_mensalidade"):
            cur.execute("ALTER TABLE cobranca_grupo_item DROP INDEX uk_grupo_item_mensalidade")
            conn.commit()
            print("✓ Índice único antigo removido.")
        else:
            print("• Índice único antigo já não existia.")

        if _tem_indice(cur, "cobranca_grupo_item", "uk_grupo_item_origem"):
            print("• Índice único (origem, registro_id) já existia.")
        else:
            cur.execute("ALTER TABLE cobranca_grupo_item "
                        "ADD UNIQUE KEY uk_grupo_item_origem (origem, registro_id)")
            conn.commit()
            print("✓ Índice único (origem, registro_id) criado.")

        cur.execute("ALTER TABLE cobranca_grupo_item MODIFY registro_id INT NOT NULL")
        conn.commit()
        print("✓ registro_id agora é obrigatório.")
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
