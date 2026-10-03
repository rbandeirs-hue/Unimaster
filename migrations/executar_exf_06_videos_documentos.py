#!/usr/bin/env python3
"""
EXF-06 — Exame de faixa: vídeos das técnicas e documentos do programa.

  exame_faixa_video      um vídeo por técnica (ou kata) por associação. A chave
                         é o nome normalizado da técnica — "O-soto-gari" tem um
                         vídeo só, que aparece em toda faixa que a cobra, inclusive
                         como metade de um par de kaeshi/renraku.
  exame_faixa_documento  arquivo (PDF, imagem, planilha) ou link vinculado ao
                         programa todo (programa_id NULL) ou a uma promoção.

Aditiva. --reverter apaga as duas tabelas (e o que estiver nelas).

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_exf_06_videos_documentos.py            # simulação
  .venv/bin/python migrations/executar_exf_06_videos_documentos.py --aplicar
  .venv/bin/python migrations/executar_exf_06_videos_documentos.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TABELAS = {
    "exame_faixa_video": """
CREATE TABLE IF NOT EXISTS exame_faixa_video (
  id              INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
  id_associacao   INT          NOT NULL,
  grupo           VARCHAR(20)  NOT NULL,
  chave           VARCHAR(120) NOT NULL,
  nome            VARCHAR(160) NOT NULL,
  url             VARCHAR(500) NOT NULL,
  observacao      VARCHAR(255) NULL,
  atualizado_por  INT          NULL,
  atualizado_em   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_exf_video (id_associacao, chave)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    "exame_faixa_documento": """
CREATE TABLE IF NOT EXISTS exame_faixa_documento (
  id              INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
  id_associacao   INT          NOT NULL,
  titulo          VARCHAR(160) NOT NULL,
  arquivo         VARCHAR(255) NULL,
  url             VARCHAR(500) NULL,
  programa_id     INT          NULL,
  enviado_por     INT          NULL,
  criado_em       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_exf_doc_assoc (id_associacao, programa_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
}


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW TABLES LIKE 'exame_faixa_%'")
        existentes = {r[0] for r in cur.fetchall()}
        if "--reverter" in sys.argv:
            for t in TABELAS:
                if t in existentes:
                    cur.execute(f"DROP TABLE {t}")
            conn.commit()
            print("✓ EXF-06 revertida.")
            return
        faltam = [t for t in TABELAS if t not in existentes]
        print(f"• tabelas a criar: {faltam or 'nenhuma'}")
        if "--aplicar" not in sys.argv:
            print("Simulação. Rode com --aplicar para gravar.")
            return
        for t in faltam:
            cur.execute(TABELAS[t])
        conn.commit()
        print("✓ EXF-06 aplicada.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
