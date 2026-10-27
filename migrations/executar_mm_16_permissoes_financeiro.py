#!/usr/bin/env python3
"""
MM-16 — Permissões do financeiro por nível.

O acesso ao financeiro era tudo ou nada (`acesso_financeiro`): quem via
também dava baixa, cancelava pagamento, isentava juros e excluía receita — e
22 de 23 professores tinham acesso. Agora, no vínculo usuário × academia:

  usuarios_academias.fin_baixar    registrar pagamentos, lançar entradas/saídas
  usuarios_academias.fin_estornar  cancelar pagamento, isentar juros, editar/
                                   excluir lançamento, cancelar cobrança

Os dois nascem LIGADOS (=1): no dia nada muda. O gestor principal desliga em
Financeiro › Configurações › Permissões. Gestor principal, admin e gestores de
associação/federação têm tudo, sempre.

--reverter remove as colunas.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_16_permissoes_financeiro.py            # simulação
  .venv/bin/python migrations/executar_mm_16_permissoes_financeiro.py --aplicar
  .venv/bin/python migrations/executar_mm_16_permissoes_financeiro.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = ("fin_baixar", "fin_estornar")


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM usuarios_academias")
        cols = {r[0] for r in cur.fetchall()}
        if "--reverter" in sys.argv:
            for c in COLUNAS:
                if c in cols:
                    cur.execute(f"ALTER TABLE usuarios_academias DROP COLUMN {c}")
            conn.commit()
            print("✓ MM-16 revertida.")
            return
        faltam = [c for c in COLUNAS if c not in cols]
        cur.execute("SELECT COUNT(*) FROM usuarios_academias")
        print(f"• colunas a criar: {', '.join(faltam) or 'nenhuma'}")
        print(f"• vínculos que nascem com baixa e estorno ligados: {cur.fetchone()[0]}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        for c in faltam:
            cur.execute(f"ALTER TABLE usuarios_academias ADD COLUMN {c} TINYINT(1) NOT NULL DEFAULT 1")
        conn.commit()
        print("✓ MM-16 aplicada.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
