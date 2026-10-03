#!/usr/bin/env python3
"""
EST-07 — `estoque_pedido.id_academia` passa a aceitar nulo.

O defeito
---------
EST-05 foi escrita quando o pedido só podia ser de uma academia. EST-06 criou
a organização independente — estoque sem academia e sem associação —, mas a
coluna continuou `NOT NULL`. Resultado: a loja independente montava o pedido e
o banco recusava na hora de gravar.

O teste `tests/test_estoque_venda.py`, cenário 20, é quem achou.

A regra real é: o pedido precisa de UM vendedor, que é uma academia OU uma
organização. Isso é validado em `utils/estoque_venda.criar_pedido`, onde dá
para explicar o erro a quem está na tela.

Segura: afrouxa uma restrição, não aperta. Nenhuma linha existente é afetada —
e no momento desta migração a tabela está vazia. A reversão só recoloca o
`NOT NULL` se não houver pedido sem academia, senão recusa em vez de apagar.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_est_07_pedido_sem_academia.py            # simulação
  .venv/bin/python migrations/executar_est_07_pedido_sem_academia.py --aplicar
  .venv/bin/python migrations/executar_est_07_pedido_sem_academia.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TIPO = ("INT(11) %s COMMENT 'Quem vende e fica com a margem; "
        "nulo quando o estoque é de uma organização independente'")


def _nulavel(cur):
    cur.execute("""SELECT IS_NULLABLE FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'estoque_pedido'
                     AND COLUMN_NAME = 'id_academia'""")
    r = cur.fetchone()
    return r and r["IS_NULLABLE"] == "YES"


def _sem_academia(cur):
    cur.execute("SELECT COUNT(*) AS n FROM estoque_pedido WHERE id_academia IS NULL")
    return cur.fetchone()["n"]


def simular():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        print("EST-07 — simulação (nada foi gravado)\n")
        print("  id_academia aceita nulo hoje:", "sim" if _nulavel(cur) else "não")
        cur.execute("SELECT COUNT(*) AS n FROM estoque_pedido")
        print("  pedidos na tabela           :", cur.fetchone()["n"])
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close(); conn.close()


def executar_migracao():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        if _nulavel(cur):
            print("• id_academia já aceitava nulo.")
        else:
            cur.execute(f"ALTER TABLE estoque_pedido MODIFY COLUMN id_academia "
                        f"{TIPO % 'DEFAULT NULL'}")
            conn.commit()
            print("✓ estoque_pedido.id_academia passou a aceitar nulo.")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback(); print("Erro na migração:", e); sys.exit(1)
    finally:
        cur.close(); conn.close()


def reverter():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        if not _nulavel(cur):
            print("• id_academia já era NOT NULL.")
            return
        pendentes = _sem_academia(cur)
        if pendentes:
            print(f"Recusado: existem {pendentes} pedido(s) sem academia. "
                  "Voltar o NOT NULL apagaria ou corromperia essas vendas.")
            sys.exit(1)
        cur.execute(f"ALTER TABLE estoque_pedido MODIFY COLUMN id_academia "
                    f"{TIPO % 'NOT NULL'}")
        conn.commit()
        print("✓ id_academia voltou a NOT NULL.")
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
