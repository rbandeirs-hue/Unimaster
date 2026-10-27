#!/usr/bin/env python3
"""
Receitas antigas → caixa (razão).

Até o commit 96b854f só três caminhos de baixa lançavam a entrada no caixa,
e 367 de 378 receitas ficaram de fora: o extrato não mostrava o dinheiro
recebido e o saldo das contas chegava a ficar negativo. Daqui em diante toda
baixa lança sozinha (utils/financeiro_core.espelhar_receita); este script
traz o histórico.

Regras (as mesmas da baixa):
  - só academias com o controle financeiro ligado (fin_config parcial/total)
    e com ao menos uma conta;
  - receita não cancelada, de valor > 0, ainda sem id_lancamento;
  - conta = a amarrada à forma de pagamento; sem forma, a conta padrão;
  - lançamento efetivado na DATA da receita, origem mensalidade / avulsa /
    receita, e auditoria "importacao" para separar do que foi baixa de fato.

Despesas NÃO entram: despesa sem pagamento registrado é conta a pagar
(utils/despesas_pagamento.py), e lançá-la como paga mudaria o caixa.

Idempotente: rodar de novo só pega o que ainda faltar.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_receitas_no_caixa.py            # simulação
  .venv/bin/python migrations/executar_receitas_no_caixa.py --aplicar
  .venv/bin/python migrations/executar_receitas_no_caixa.py --academia 2 [--aplicar]
"""
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402
from utils import financeiro_core as fin  # noqa: E402


def _arg(nome):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    return None


def main():
    aplicar = "--aplicar" in sys.argv
    so_academia = _arg("--academia")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT f.id_academia, f.modo, a.nome FROM fin_config f
                       JOIN academias a ON a.id = f.id_academia
                       WHERE f.modo IN ('parcial', 'total')""")
        academias = cur.fetchall()
        if so_academia:
            academias = [a for a in academias if str(a["id_academia"]) == so_academia]
        total_n, total_v = 0, Decimal("0")
        for ac in academias:
            aid = ac["id_academia"]
            cur.execute(
                """SELECT r.id, r.descricao, r.valor, r.data, r.id_forma_pagamento,
                          r.id_mensalidade_aluno, r.id_cobranca_avulsa, r.criado_por,
                          COALESCE(r.id_aluno, ma.aluno_id, ca.aluno_id) AS aluno_id
                   FROM receitas r
                   LEFT JOIN mensalidade_aluno ma ON ma.id = r.id_mensalidade_aluno
                   LEFT JOIN cobranca_avulsa ca ON ca.id = r.id_cobranca_avulsa
                   WHERE r.id_academia = %s AND COALESCE(r.cancelada, 0) = 0
                     AND r.id_lancamento IS NULL AND r.valor > 0
                   ORDER BY r.data, r.id""", (aid,))
            receitas = cur.fetchall()
            por_conta = defaultdict(lambda: [0, Decimal("0")])
            sem_conta = 0
            for r in receitas:
                id_conta = fin.conta_padrao(cur, aid, r["id_forma_pagamento"])
                if not id_conta:
                    sem_conta += 1
                    continue
                por_conta[id_conta][0] += 1
                por_conta[id_conta][1] += Decimal(str(r["valor"]))
                if not aplicar:
                    continue
                if r["id_mensalidade_aluno"]:
                    origem, origem_id, entidade = "mensalidade", r["id_mensalidade_aluno"], "mensalidade_aluno"
                elif r["id_cobranca_avulsa"]:
                    origem, origem_id, entidade = "cobranca_avulsa", r["id_cobranca_avulsa"], "cobranca_avulsa"
                else:
                    origem, origem_id, entidade = "receita", r["id"], "receitas"
                lanc = fin.lancar(
                    conn, cur, id_academia=aid, id_conta=id_conta, sentido="entrada",
                    valor=r["valor"], descricao=(r["descricao"] or "Receita")[:255],
                    data_competencia=r["data"], data_efetivacao=r["data"], status="efetivado",
                    origem=origem, origem_id=origem_id, id_forma_pagamento=r["id_forma_pagamento"],
                    id_aluno=r["aluno_id"], usuario_id=r["criado_por"],
                    observacoes="Importado do histórico de receitas.")
                cur.execute("UPDATE receitas SET id_lancamento = %s WHERE id = %s", (lanc, r["id"]))
                fin.auditar(cur, aid, entidade, origem_id, "importacao", valor_novo=r["valor"],
                            usuario_id=r["criado_por"],
                            detalhes=f"receita {r['id']} levada ao caixa (lançamento {lanc})")
            n = sum(v[0] for v in por_conta.values())
            v = sum((v[1] for v in por_conta.values()), Decimal("0"))
            total_n += n
            total_v += v
            print(f"• academia {aid} ({ac['nome']}, modo {ac['modo']}): {n} receita(s), R$ {v:,.2f}"
                  + (f" — {sem_conta} sem conta (rode 'Preparar contas' no Controle)" if sem_conta else ""))
            cur.execute("SELECT id, nome FROM fin_contas WHERE id_academia = %s", (aid,))
            nomes = {c["id"]: c["nome"] for c in cur.fetchall()}
            for cid, (qn, qv) in sorted(por_conta.items(), key=lambda kv: -kv[1][1]):
                print(f"    {nomes.get(cid, cid)}: {qn} · R$ {qv:,.2f}")
            if aplicar:
                conn.commit()
        print(f"Total: {total_n} receita(s), R$ {total_v:,.2f}.")
        if not aplicar:
            print("Simulação. Rode com --aplicar para gravar.")
        else:
            print("✓ Receitas levadas ao caixa.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
