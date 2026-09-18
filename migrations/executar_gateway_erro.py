#!/usr/bin/env python3
"""
Falha de gateway visível: guarda o último erro de emissão de cobrança por academia.

Até aqui, quando o gateway recusava (conta sem checkout externo habilitado,
credencial vencida, API fora), o erro só ia para o log: a matrícula caía em
"pagamento avulso" e o lembrete saía sem link, sem ninguém ser avisado. Foi assim
que 87 mensalidades do Projeto 323 ficaram sem cobrança online por dias.

Duas colunas em `academias`:
  gateway_ultimo_erro     — a mensagem crua devolvida pelo gateway
  gateway_ultimo_erro_em  — quando aconteceu (some quando uma emissão dá certo)

Idempotente: ignora a coluna que já existir.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_gateway_erro.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = [
    ("gateway_ultimo_erro",
     "ALTER TABLE academias ADD COLUMN gateway_ultimo_erro TEXT NULL"),
    ("gateway_ultimo_erro_em",
     "ALTER TABLE academias ADD COLUMN gateway_ultimo_erro_em DATETIME NULL"),
]


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        for nome, ddl in COLUNAS:
            try:
                cur.execute(ddl)
                conn.commit()
                print(f"✓ Coluna academias.{nome} criada.")
            except Exception as e:
                if "Duplicate column" in str(e) or "1060" in str(e):
                    conn.rollback()
                    print(f"• Coluna academias.{nome} já existia.")
                else:
                    raise
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
