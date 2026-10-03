#!/usr/bin/env python3
"""
PM-01 — Plano por modalidade, com o valor dividido entre as modalidades.

Todo plano passa a dizer a que modalidade(s) da academia pertence
(`mensalidade_modalidade`, que já existia). Num combo — "Judô e Jiu-Jitsu
R$ 180" — cada modalidade recebe a sua parte do valor (Judô 90, Jiu-Jitsu 90),
que soma o total. É o que permite dizer quanto da receita é de cada modalidade
sem chutar meio a meio.

  mensalidade_modalidade.valor   parte do valor do plano que é desta modalidade

Preenchimento automático só do que é certo: plano de UMA modalidade recebe o
valor inteiro. Combo fica com a parte em branco — a academia divide na tela de
Planos, que passa a exigir a divisão. Plano sem modalidade nenhuma segue
aparecendo em todo lugar até alguém vinculá-lo.

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_pm_01_valor_por_modalidade.py            # simulação
  .venv/bin/python migrations/executar_pm_01_valor_por_modalidade.py --aplicar
  .venv/bin/python migrations/executar_pm_01_valor_por_modalidade.py --reverter
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402


def _tem_coluna(cur):
    cur.execute("""SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = 'mensalidade_modalidade' AND COLUMN_NAME = 'valor'""")
    return cur.fetchone() is not None


def _resumo(cur):
    cur.execute("""SELECT m.id, m.nome, m.valor, m.id_academia, COUNT(mm.id) AS n
                   FROM mensalidades m LEFT JOIN mensalidade_modalidade mm ON mm.mensalidade_id = m.id
                   WHERE COALESCE(m.ativo, 1) = 1 GROUP BY m.id""")
    planos = cur.fetchall()
    return ([p for p in planos if p["n"] == 1], [p for p in planos if p["n"] > 1],
            [p for p in planos if p["n"] == 0])


def main():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if "--reverter" in sys.argv:
            if _tem_coluna(cur):
                cur.execute("ALTER TABLE mensalidade_modalidade DROP COLUMN valor")
                conn.commit()
                print("✓ mensalidade_modalidade.valor removida.")
            return
        simples, combos, sem = _resumo(cur)
        if "--aplicar" not in sys.argv:
            print("PM-01 — simulação (nada foi gravado)\n")
            print(f"  coluna mensalidade_modalidade.valor : {'já existe' if _tem_coluna(cur) else 'será criada'}")
            print(f"  planos de uma modalidade (valor inteiro automático): {len(simples)}")
            print(f"  combos (a academia divide na tela de Planos)       : {len(combos)}")
            for p in combos:
                print(f"      #{p['id']} {p['nome']} — R$ {p['valor']}")
            print(f"  planos ativos sem modalidade (vincular na tela)     : {len(sem)}")
            for p in sem:
                print(f"      #{p['id']} {p['nome']} (academia {p['id_academia']})")
            print("\nPara aplicar:  --aplicar")
            return
        if _tem_coluna(cur):
            print("• Coluna mensalidade_modalidade.valor já existia.")
        else:
            cur.execute("ALTER TABLE mensalidade_modalidade ADD COLUMN valor DECIMAL(10,2) NULL "
                        "COMMENT 'Parte do valor do plano que é desta modalidade'")
            conn.commit()
            print("✓ Coluna mensalidade_modalidade.valor criada.")
        cur.execute("""UPDATE mensalidade_modalidade mm JOIN mensalidades m ON m.id = mm.mensalidade_id
                       SET mm.valor = m.valor
                       WHERE mm.valor IS NULL
                         AND (SELECT COUNT(*) FROM (SELECT mensalidade_id FROM mensalidade_modalidade) x
                              WHERE x.mensalidade_id = mm.mensalidade_id) = 1""")
        print(f"✓ {cur.rowcount} plano(s) de uma modalidade com o valor inteiro na modalidade.")
        conn.commit()
        print(f"• {len(combos)} combo(s) aguardando a divisão do valor na tela de Planos.")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
