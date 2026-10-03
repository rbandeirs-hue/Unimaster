#!/usr/bin/env python3
"""
EXF-04 — Exame de faixa da academia e cancelamento de inscrição.

1. `eventos_competicoes.exame_academia_id`: a academia pode marcar o próprio
   exame de faixa, sem a associação. NULL = exame da associação (aberto a
   todas as academias dela); preenchido = exame só daquela academia. O
   programa e a tabela de preços continuam os da associação.

2. `eventos_competicoes_inscricoes.status` ganha 'cancelada': inscrição
   cancelada pela banca sai das listas mas fica registrada (e a fatura dela
   é cancelada junto).

3. Exames da associação já criados passam a valer para todas as academias
   (adesão marcada), porque as inscrições abrem para todos os alunos.

Aditiva. --reverter desfaz 1 e 2 (a adesão marcada fica).

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_exf_04_exame_da_academia.py            # simulação
  .venv/bin/python migrations/executar_exf_04_exame_da_academia.py --aplicar
  .venv/bin/python migrations/executar_exf_04_exame_da_academia.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

ENUM_COM = "ENUM('rascunho','confirmada','enviada','cancelada') NOT NULL DEFAULT 'confirmada'"
ENUM_SEM = "ENUM('rascunho','confirmada','enviada') NOT NULL DEFAULT 'confirmada'"


def _tem_coluna(cur):
    cur.execute("SHOW COLUMNS FROM eventos_competicoes LIKE 'exame_academia_id'")
    return cur.fetchone() is not None


def _tem_cancelada(cur):
    cur.execute("SHOW COLUMNS FROM eventos_competicoes_inscricoes LIKE 'status'")
    return "cancelada" in str(cur.fetchone()[1])


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        coluna, cancelada = _tem_coluna(cur), _tem_cancelada(cur)
        if "--reverter" in sys.argv:
            if coluna:
                cur.execute("ALTER TABLE eventos_competicoes DROP COLUMN exame_academia_id")
            if cancelada:
                cur.execute("UPDATE eventos_competicoes_inscricoes SET status = 'rascunho' WHERE status = 'cancelada'")
                cur.execute(f"ALTER TABLE eventos_competicoes_inscricoes MODIFY status {ENUM_SEM}")
            conn.commit()
            print("✓ EXF-04 revertida.")
            return

        print(f"• exame_academia_id: {'já existe' if coluna else 'será criada'}")
        print(f"• status 'cancelada': {'já existe' if cancelada else 'será acrescentado'}")
        cur.execute("""SELECT COUNT(*) FROM eventos_competicoes_adesao ea
                       JOIN eventos_competicoes ec ON ec.id = ea.evento_id
                       WHERE ec.exame_faixa = 1 AND ea.aderiu = 0""")
        print(f"• adesões de exame a marcar: {cur.fetchone()[0]}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        if not coluna:
            cur.execute("ALTER TABLE eventos_competicoes ADD COLUMN exame_academia_id INT NULL AFTER exame_gera_fatura, "
                        "ADD INDEX idx_ec_exame_academia (exame_academia_id)")
        if not cancelada:
            cur.execute(f"ALTER TABLE eventos_competicoes_inscricoes MODIFY status {ENUM_COM}")
        cur.execute("""UPDATE eventos_competicoes_adesao ea
                       JOIN eventos_competicoes ec ON ec.id = ea.evento_id
                       SET ea.aderiu = 1, ea.data_adesao = COALESCE(ea.data_adesao, NOW())
                       WHERE ec.exame_faixa = 1 AND ea.aderiu = 0""")
        conn.commit()
        print("✓ EXF-04 aplicada.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
