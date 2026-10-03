#!/usr/bin/env python3
"""
MM-14 — Papel por academia.

O papel era do usuário, não do vínculo: quem é gestor numa academia e aluno
em outra virava gestor e aluno nas duas. O papel passa a dizer EM QUAL academia
vale:

  roles_usuario.academia_id   academia em que o papel vale; 0 = em todas
                              (admin, gestor de associação/federação)

Preenchimento sem mudar nada no dia: cada papel de academia de hoje (gestor,
professor, aluno, responsável, visitante) vira uma linha por academia vinculada
ao usuário — exatamente o que ele já tinha. Daí cada academia desmarca o que
não vale lá. Usuário sem academia vinculada fica com 0 (como antes).

A chave primária passa a ser (usuario_id, role_id, academia_id).
--reverter volta a uma linha por papel (academia_id some).

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_14_papel_por_academia.py            # simulação
  .venv/bin/python migrations/executar_mm_14_papel_por_academia.py --aplicar
  .venv/bin/python migrations/executar_mm_14_papel_por_academia.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

PAPEIS_DE_ACADEMIA = ("gestor_academia", "professor", "aluno", "responsavel", "visitante")

EXPANDIR = f"""
    INSERT IGNORE INTO roles_usuario (usuario_id, role_id, academia_id)
    SELECT ru.usuario_id, ru.role_id, ua.academia_id
    FROM roles_usuario ru
    JOIN roles r ON r.id = ru.role_id AND r.chave IN ({",".join(["%s"] * len(PAPEIS_DE_ACADEMIA))})
    JOIN usuarios_academias ua ON ua.usuario_id = ru.usuario_id
    WHERE ru.academia_id = 0
"""
APAGAR_GLOBAIS_EXPANDIDOS = f"""
    DELETE ru FROM roles_usuario ru
    JOIN roles r ON r.id = ru.role_id AND r.chave IN ({",".join(["%s"] * len(PAPEIS_DE_ACADEMIA))})
    WHERE ru.academia_id = 0
      AND EXISTS (SELECT 1 FROM usuarios_academias ua WHERE ua.usuario_id = ru.usuario_id)
"""


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM roles_usuario")
        cols = {r[0] for r in cur.fetchall()}
        if "--reverter" in sys.argv:
            if "academia_id" in cols:
                cur.execute("""CREATE TEMPORARY TABLE _ru AS
                               SELECT DISTINCT usuario_id, role_id FROM roles_usuario""")
                cur.execute("ALTER TABLE roles_usuario DROP PRIMARY KEY")
                cur.execute("DELETE FROM roles_usuario")
                cur.execute("ALTER TABLE roles_usuario DROP COLUMN academia_id")
                cur.execute("INSERT INTO roles_usuario (usuario_id, role_id) SELECT usuario_id, role_id FROM _ru")
                cur.execute("ALTER TABLE roles_usuario ADD PRIMARY KEY (usuario_id, role_id)")
            conn.commit()
            print("✓ MM-14 revertida.")
            return
        cur.execute(f"""SELECT COUNT(*) FROM roles_usuario ru
                        JOIN roles r ON r.id = ru.role_id AND r.chave IN ({",".join(["%s"] * len(PAPEIS_DE_ACADEMIA))})
                        JOIN usuarios_academias ua ON ua.usuario_id = ru.usuario_id""", PAPEIS_DE_ACADEMIA)
        print(f"• coluna academia_id: {'já existe' if 'academia_id' in cols else 'a criar'}")
        print(f"• linhas de papel por academia a criar: {cur.fetchone()[0]}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        if "academia_id" not in cols:
            cur.execute("ALTER TABLE roles_usuario ADD COLUMN academia_id INT NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE roles_usuario DROP PRIMARY KEY, ADD PRIMARY KEY (usuario_id, role_id, academia_id)")
        cur.execute(EXPANDIR, PAPEIS_DE_ACADEMIA)
        n1 = cur.rowcount
        cur.execute(APAGAR_GLOBAIS_EXPANDIDOS, PAPEIS_DE_ACADEMIA)
        n2 = cur.rowcount
        conn.commit()
        print(f"✓ MM-14 aplicada. Papéis por academia criados: {n1}; papéis globais substituídos: {n2}.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
