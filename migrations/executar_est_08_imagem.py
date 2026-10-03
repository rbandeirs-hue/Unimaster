#!/usr/bin/env python3
"""
EST-08 — Imagem do produto e da variação, para o catálogo.

Por quê
-------
Catálogo sem foto não é catálogo: o aluno abre a loja e vê uma lista de nomes.
A imagem fica no produto e, opcionalmente, na variação — kimono azul e kimono
branco são o mesmo produto com fotos diferentes, e é a variação que o comprador
escolhe.

Guarda só o nome do arquivo, como o resto do sistema já faz com foto de aluno:
o caminho é montado na tela com `url_for('static', ...)`. Guardar o caminho
inteiro amarra o banco à estrutura de pastas.

Aditiva e reversível. Duas colunas anuláveis; nenhuma linha muda de valor.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_est_08_imagem.py            # simulação
  .venv/bin/python migrations/executar_est_08_imagem.py --aplicar
  .venv/bin/python migrations/executar_est_08_imagem.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = [
    ("estoque_produto", "imagem",
     "VARCHAR(160) DEFAULT NULL COMMENT 'Arquivo em static/uploads/estoque/'"),
    ("estoque_variacao", "imagem",
     "VARCHAR(160) DEFAULT NULL COMMENT 'Sobrepõe a imagem do produto'"),
]


def _tem_coluna(cur, tabela, coluna):
    cur.execute("""SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND COLUMN_NAME = %s""", (tabela, coluna))
    return cur.fetchone() is not None


def simular():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        print("EST-08 — simulação (nada foi gravado)\n")
        for tab, col, _t in COLUNAS:
            print(f"  {'já existe' if _tem_coluna(cur, tab, col) else 'criar   '}  {tab}.{col}")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close(); conn.close()


def executar_migracao():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        for tab, col, tipo in COLUNAS:
            if _tem_coluna(cur, tab, col):
                print(f"• {tab}.{col} já existia.")
                continue
            cur.execute(f"ALTER TABLE {tab} ADD COLUMN {col} {tipo}")
            conn.commit()
            print(f"✓ {tab}.{col} criada.")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback(); print("Erro na migração:", e); sys.exit(1)
    finally:
        cur.close(); conn.close()


def reverter():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        for tab, col, _t in COLUNAS:
            if _tem_coluna(cur, tab, col):
                cur.execute(f"ALTER TABLE {tab} DROP COLUMN {col}")
                conn.commit()
                print(f"✓ {tab}.{col} removida.")
                print("  (os arquivos em static/uploads/estoque/ ficam no disco)")
            else:
                print(f"• {tab}.{col} já não existia.")
    except Exception as e:
        conn.rollback(); print("Erro na reversão:", e); sys.exit(1)
    finally:
        cur.close(); conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    elif "--aplicar" in sys.argv:
        executar_migracao()
    else:
        simular()
