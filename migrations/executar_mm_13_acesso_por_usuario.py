#!/usr/bin/env python3
"""
MM-13 — Acesso por usuário na academia: gestor principal, modalidades e áreas.

Até aqui o acesso era "papel + vínculo com a academia": todo gestor via tudo,
e o seletor de modalidade do topo só recortava a tela. Agora, por usuário e por
academia (no vínculo usuarios_academias):

  gestor_principal    1 = vê e faz tudo e é quem gerencia o acesso dos outros
  acesso_financeiro   0 = não entra no financeiro (menu e rotas)
  acesso_academico    0 = não entra em presenças, turmas, exame, calendário…

  usuario_academia_modalidade (usuario_id, academia_id, modalidade_id)
      modalidades que o usuário vê NAQUELA academia. Sem linha = todas.

Preenchimento: todo gestor_academia de hoje vira gestor principal das academias
dele (ninguém perde acesso no dia da mudança); áreas começam liberadas.

Aditiva. --reverter remove colunas e tabela.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_13_acesso_por_usuario.py            # simulação
  .venv/bin/python migrations/executar_mm_13_acesso_por_usuario.py --aplicar
  .venv/bin/python migrations/executar_mm_13_acesso_por_usuario.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

PRINCIPAIS = """
    UPDATE usuarios_academias ua
    JOIN roles_usuario ru ON ru.usuario_id = ua.usuario_id
    JOIN roles r ON r.id = ru.role_id AND r.chave = 'gestor_academia'
    SET ua.gestor_principal = 1
"""


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM usuarios_academias")
        cols = {r[0] for r in cur.fetchall()}
        cur.execute("SHOW TABLES LIKE 'usuario_academia_modalidade'")
        tem_tabela = bool(cur.fetchall())
        if "--reverter" in sys.argv:
            for c in ("gestor_principal", "acesso_financeiro", "acesso_academico"):
                if c in cols:
                    cur.execute(f"ALTER TABLE usuarios_academias DROP COLUMN {c}")
            if tem_tabela:
                cur.execute("DROP TABLE usuario_academia_modalidade")
            conn.commit()
            print("✓ MM-13 revertida.")
            return
        faltam = [c for c in ("gestor_principal", "acesso_financeiro", "acesso_academico") if c not in cols]
        print(f"• colunas a criar em usuarios_academias: {faltam or 'nenhuma'}")
        print(f"• tabela usuario_academia_modalidade: {'já existe' if tem_tabela else 'a criar'}")
        cur.execute("""SELECT COUNT(*) FROM usuarios_academias ua
                       JOIN roles_usuario ru ON ru.usuario_id = ua.usuario_id
                       JOIN roles r ON r.id = ru.role_id AND r.chave = 'gestor_academia'""")
        print(f"• vínculos de gestor que viram gestor principal: {cur.fetchone()[0]}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        if "gestor_principal" not in cols:
            cur.execute("ALTER TABLE usuarios_academias ADD COLUMN gestor_principal TINYINT(1) NOT NULL DEFAULT 0")
        if "acesso_financeiro" not in cols:
            cur.execute("ALTER TABLE usuarios_academias ADD COLUMN acesso_financeiro TINYINT(1) NOT NULL DEFAULT 1")
        if "acesso_academico" not in cols:
            cur.execute("ALTER TABLE usuarios_academias ADD COLUMN acesso_academico TINYINT(1) NOT NULL DEFAULT 1")
        if not tem_tabela:
            cur.execute("""CREATE TABLE usuario_academia_modalidade (
                usuario_id INT NOT NULL,
                academia_id INT NOT NULL,
                modalidade_id INT NOT NULL,
                PRIMARY KEY (usuario_id, academia_id, modalidade_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        cur.execute(PRINCIPAIS)
        n = cur.rowcount
        conn.commit()
        print(f"✓ MM-13 aplicada. Gestores principais: {n}.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
