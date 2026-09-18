#!/usr/bin/env python3
"""
Remove as mensalidades da ArteFísica anteriores a setembro/2026.

Pedido do gestor: zerar o histórico de cobranças da academia 2 até agosto/2026,
mantendo de setembro em diante. A decisão de incluir as PAGAS foi dele, depois
de ver o impacto — são R$ 39,6 mil de receita que saem dos relatórios e
R$ 32,5 mil que saem do saldo das contas.

Apaga, nesta ordem (o inverso da dependência):

  fin_lancamentos   origem='mensalidade' apontando para as alvo — é o que forma
                    o saldo das contas; sem apagar, o extrato manteria entradas
                    de uma cobrança que não existe mais.
  receitas          ligadas às alvo. A chave estrangeira é SET NULL, então sem
                    isto elas sobreviveriam órfãs e os relatórios mostrariam
                    entrada sem lastro.
  cobranca_grupo_item  itens de cobrança familiar que as cubram.
  whatsapp_envios   marcas da régua daquelas cobranças (trava de duplicidade).
  mensalidade_aluno as cobranças em si.

ISTO NÃO TEM DESFAZER. A volta é restaurar o backup feito antes:
  /var/backups/unimaster/unimaster_pre_limpeza_artefisica_20260918_193620.sql.gz

Antes de apagar, grava um manifesto CSV com tudo que será removido, para que
exista registro do que havia mesmo sem abrir o dump.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_limpeza_artefisica_ate_ago2026.py            # simula
  .venv/bin/python migrations/executar_limpeza_artefisica_ate_ago2026.py --aplicar
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

ACADEMIA = 2
CORTE = "2026-09-01"          # mantém tudo com vencimento a partir daqui
MANIFESTO = "/var/backups/unimaster/limpeza_artefisica_%s.csv"

SQL_ALVO = """
SELECT ma.id
FROM mensalidade_aluno ma
JOIN mensalidades m ON m.id = ma.mensalidade_id
WHERE m.id_academia = %s AND ma.data_vencimento < %s
"""

SQL_MANIFESTO = """
SELECT ma.id, a.nome AS aluno, m.nome AS plano, ma.data_vencimento, ma.valor,
       ma.valor_pago, ma.status, ma.status_pagamento, ma.data_pagamento,
       ma.desconto_aplicado, ma.contrato_id
FROM mensalidade_aluno ma
JOIN mensalidades m ON m.id = ma.mensalidade_id
JOIN alunos a ON a.id = ma.aluno_id
WHERE m.id_academia = %s AND ma.data_vencimento < %s
ORDER BY ma.data_vencimento, a.nome
"""


def _ids(cur):
    cur.execute(SQL_ALVO, (ACADEMIA, CORTE))
    return [r[0] if not isinstance(r, dict) else r["id"] for r in cur.fetchall() or []]


def _gravar_manifesto(cur):
    cur.execute(SQL_MANIFESTO, (ACADEMIA, CORTE))
    linhas = cur.fetchall() or []
    destino = MANIFESTO % datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(destino, "w", newline="", encoding="utf-8") as f:
        if linhas:
            w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
            w.writeheader()
            for r in linhas:
                w.writerow(r)
    return destino, len(linhas)


def executar(simular=True):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ids = _ids(cur)
        if not ids:
            print("Nenhuma mensalidade anterior a %s na academia %s." % (CORTE, ACADEMIA))
            return 0
        ph = ",".join(["%s"] * len(ids))
        t = tuple(ids)

        cur.execute(f"""SELECT COUNT(*) n, COALESCE(SUM(valor),0) v FROM fin_lancamentos
                        WHERE origem = 'mensalidade' AND origem_id IN ({ph})""", t)
        lanc = cur.fetchone()
        cur.execute(f"""SELECT COUNT(*) n, COALESCE(SUM(valor),0) v FROM receitas
                        WHERE id_mensalidade_aluno IN ({ph})""", t)
        rec = cur.fetchone()

        print(f"Alvo: {len(ids)} mensalidade(s) da academia {ACADEMIA} "
              f"com vencimento anterior a {CORTE}")
        print(f"  lançamentos no razão: {lanc['n']} (R$ {float(lanc['v']):.2f})")
        print(f"  receitas ligadas:     {rec['n']} (R$ {float(rec['v']):.2f})")

        if simular:
            print("\nSIMULAÇÃO — nada foi apagado. Rode com --aplicar para valer.")
            return len(ids)

        destino, n = _gravar_manifesto(cur)
        print(f"\n✓ Manifesto com {n} linha(s): {destino}")

        cur.execute(f"""DELETE FROM fin_lancamentos
                        WHERE origem = 'mensalidade' AND origem_id IN ({ph})""", t)
        print(f"✓ {cur.rowcount} lançamento(s) removidos do razão.")

        cur.execute(f"DELETE FROM receitas WHERE id_mensalidade_aluno IN ({ph})", t)
        print(f"✓ {cur.rowcount} receita(s) removidas.")

        cur.execute(f"""DELETE FROM cobranca_grupo_item
                        WHERE origem = 'mensalidade' AND registro_id IN ({ph})""", t)
        print(f"✓ {cur.rowcount} item(ns) de cobrança familiar removidos.")

        cur.execute(f"""DELETE FROM whatsapp_envios
                        WHERE id_academia = %s AND tipo LIKE 'regua%%'
                          AND referencia_id IN ({ph})""", (ACADEMIA,) + t)
        print(f"✓ {cur.rowcount} marca(s) da régua removidas.")

        cur.execute(f"DELETE FROM mensalidade_aluno WHERE id IN ({ph})", t)
        print(f"✓ {cur.rowcount} mensalidade(s) removidas.")

        conn.commit()
        print("\nConcluído. A volta é só pelo backup.")
        return len(ids)
    except Exception as e:
        conn.rollback()
        print("Erro — nada foi apagado:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar(simular="--aplicar" not in sys.argv)
