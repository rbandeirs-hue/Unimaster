#!/usr/bin/env python3
"""
MM-15 — Domínio próprio e marca da academia.

A academia aponta o domínio dela para o servidor e o sistema passa a abrir
por ele, com o nome, a logo e a cor dela no lugar de Unimaster. Só entra por
ali quem é da academia (utils/dominio_academia.py).

  academias.dominio             domínio sem www, minúsculo ('judoclube.com.br');
                                único — dois cadastros não podem disputar o host
  academias.dominio_status      pendente | ativo | erro (scripts/dominios_academias.py)
  academias.dominio_erro        motivo do último erro, para o gestor ler na tela
  academias.dominio_ativado_em  quando o certificado e o nginx ficaram prontos
  academias.marca_cor           cor da marca, '#rrggbb'
  academias.marca_titulo        nome exibido (vazio = nome da academia)
  academias.marca_texto         frase da tela de entrada

--reverter remove as colunas.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_15_dominio_marca.py            # simulação
  .venv/bin/python migrations/executar_mm_15_dominio_marca.py --aplicar
  .venv/bin/python migrations/executar_mm_15_dominio_marca.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNAS = [
    ("dominio", "VARCHAR(190) NULL"),
    ("dominio_status", "VARCHAR(10) NULL"),
    ("dominio_erro", "VARCHAR(255) NULL"),
    ("dominio_ativado_em", "DATETIME NULL"),
    ("marca_cor", "VARCHAR(7) NULL"),
    ("marca_titulo", "VARCHAR(80) NULL"),
    ("marca_texto", "VARCHAR(160) NULL"),
]


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM academias")
        cols = {r[0] for r in cur.fetchall()}
        cur.execute("SHOW INDEX FROM academias WHERE Key_name = 'uq_academias_dominio'")
        tem_indice = bool(cur.fetchall())
        if "--reverter" in sys.argv:
            if tem_indice:
                cur.execute("ALTER TABLE academias DROP INDEX uq_academias_dominio")
            for nome, _ in COLUNAS:
                if nome in cols:
                    cur.execute(f"ALTER TABLE academias DROP COLUMN {nome}")
            conn.commit()
            print("✓ MM-15 revertida.")
            return
        faltam = [n for n, _ in COLUNAS if n not in cols]
        print(f"• colunas a criar em academias: {', '.join(faltam) or 'nenhuma'}")
        print(f"• índice único do domínio: {'já existe' if tem_indice else 'a criar'}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        for nome, tipo in COLUNAS:
            if nome not in cols:
                cur.execute(f"ALTER TABLE academias ADD COLUMN {nome} {tipo}")
        if not tem_indice:
            cur.execute("ALTER TABLE academias ADD UNIQUE INDEX uq_academias_dominio (dominio)")
        conn.commit()
        print("✓ MM-15 aplicada.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
