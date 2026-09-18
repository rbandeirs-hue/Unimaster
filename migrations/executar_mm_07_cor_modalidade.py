#!/usr/bin/env python3
"""
MM-07 — Cada modalidade ganha a sua cor.

Com o contexto operacional, o gestor troca de modalidade dezenas de vezes por
dia e a tela fica igual — só os números mudam. Uma cor por modalidade dá o sinal
que faltava: dá para saber onde se está antes de ler qualquer coisa.

A cor vale para a marca e para o destaque da barra lateral, que hoje é sempre o
mesmo vermelho.

Padrões (editáveis depois na tela de modalidades):
  Judô                 #e4001b  o vermelho que o sistema já usava
  Jiu-Jitsu            #1d4ed8
  Ginástica Artística  #7c3aed
  demais               #e4001b  seguem como estavam

Idempotente: não sobrescreve cor já definida.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_07_cor_modalidade.py
  .venv/bin/python migrations/executar_mm_07_cor_modalidade.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

PADRAO = "#e4001b"
CORES = {"judo": "#e4001b", "jiu": "#1d4ed8", "ginastica": "#7c3aed",
         "karate": "#059669", "muay": "#ea580c", "boxe": "#0891b2"}


def _tem_coluna(cur, tabela, coluna):
    cur.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (tabela, coluna))
    return cur.fetchone() is not None


def _normalizar(texto):
    import unicodedata
    sem = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem if not unicodedata.combining(c)).lower()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if _tem_coluna(cur, "modalidade", "cor"):
            print("• Coluna cor já existia.")
        else:
            cur.execute(
                "ALTER TABLE modalidade ADD COLUMN cor VARCHAR(7) DEFAULT NULL "
                "COMMENT 'Cor da modalidade no shell, em hexadecimal'")
            conn.commit()
            print("✓ Coluna cor criada.")

        cur.execute("SELECT id, nome, cor FROM modalidade ORDER BY id")
        for m in cur.fetchall() or []:
            if m["cor"]:
                print(f"• {m['nome']} já tinha cor {m['cor']}.")
                continue
            nome = _normalizar(m["nome"])
            cor = next((c for termo, c in CORES.items() if termo in nome), PADRAO)
            cur.execute("UPDATE modalidade SET cor = %s WHERE id = %s", (cor, m["id"]))
            print(f"✓ {m['nome']} → {cor}")
        conn.commit()
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro na migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if _tem_coluna(cur, "modalidade", "cor"):
            cur.execute("ALTER TABLE modalidade DROP COLUMN cor")
            conn.commit()
            print("✓ Coluna cor removida.")
        else:
            print("• Coluna cor já não existia.")
    except Exception as e:
        conn.rollback()
        print("Erro na reversão:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    else:
        executar_migracao()
