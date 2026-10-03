#!/usr/bin/env python3
"""
CAD-01 — Campos obrigatórios do cadastro do aluno, por academia.

Até aqui o que era obrigatório no cadastro interno do aluno estava fixo no
código: `required` no HTML e uma lista em blueprints/aluno/alunos.py. Uma
academia que não pesa os alunos, ou que não pede o nome do pai, não tinha como
cadastrar ninguém sem inventar o dado. Esta migração cria o lugar onde cada
academia guarda a própria escolha:

  academia_campos_obrigatorios   uma linha por (academia, campo) que a academia
                                 configurou. `obrigatorio` = 1 exige, 0 dispensa.

Sem linha, vale o padrão do catálogo (utils/campos_obrigatorios_aluno.py), que
é exatamente o comportamento de antes — nada muda até alguém salvar a tela de
Configurações da academia.

Aditiva e reversível. Nenhuma linha existente muda.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_cad_01_obrigatorios_academia.py            # simulação
  .venv/bin/python migrations/executar_cad_01_obrigatorios_academia.py --aplicar
  .venv/bin/python migrations/executar_cad_01_obrigatorios_academia.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TABELA = "academia_campos_obrigatorios"

# Sem FK para `academias`: a exclusão de academia no sistema é rara e manual, e
# uma FK aqui obrigaria quem apaga a academia a conhecer mais esta tabela. A
# linha órfã não faz mal — ninguém consulta configuração de academia que não
# existe.
DDL = f"""
CREATE TABLE IF NOT EXISTS {TABELA} (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  academia_id     INT          NOT NULL,
  campo           VARCHAR(60)  NOT NULL,
  obrigatorio     TINYINT(1)   NOT NULL DEFAULT 1,
  atualizado_por  INT          NULL,
  atualizado_em   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_acad_campo (academia_id, campo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _tem_tabela(cur, tabela):
    cur.execute("SHOW TABLES LIKE %s", (tabela,))
    return cur.fetchone() is not None


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        existe = _tem_tabela(cur, TABELA)
        print("CAD-01 — simulação (nada foi gravado)\n")
        print(f"  tabela {TABELA} já existe : {'sim' if existe else 'não'}")
        if existe:
            cur.execute(f"SELECT COUNT(*) AS n, COUNT(DISTINCT academia_id) AS a FROM {TABELA}")
            r = cur.fetchone()
            print(f"  linhas configuradas                    : {r['n']} ({r['a']} academia(s))")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close()
        conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        existia = _tem_tabela(cur, TABELA)
        cur.execute(DDL)
        conn.commit()
        print(f"{'•' if existia else '✓'} Tabela {TABELA} {'já existia' if existia else 'criada'}.")
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
        if _tem_tabela(cur, TABELA):
            cur.execute(f"DROP TABLE {TABELA}")
            conn.commit()
            print(f"✓ Tabela {TABELA} removida — todas as academias voltam ao padrão.")
        else:
            print(f"• Tabela {TABELA} não existe; nada a reverter.")
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
    elif "--aplicar" in sys.argv:
        executar_migracao()
    else:
        simular()
