"""Traz `receitas` e `despesas` já existentes para o razão.

O que faz e o que não faz
-------------------------
Cada receita/despesa antiga vira um lançamento efetivado em `fin_lancamentos`,
na conta amarrada à forma de pagamento (ou na conta padrão da academia). A
linha original NÃO é alterada além de gravar `id_lancamento`, que é o que
impede o mesmo dinheiro de ser contado duas vezes se a rotina rodar de novo.

Receitas canceladas ficam de fora: não movimentaram caixa.

A rotina é idempotente — só olha linhas com `id_lancamento IS NULL`.
"""

from decimal import Decimal

from config import get_db_connection
from utils import financeiro_core as fin


def migrar_academia(id_academia, *, usuario_id=None, simular=True):
    """Espelha o legado no razão. Com `simular=True` não grava nada."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    resultado = {"receitas": 0, "despesas": 0, "valor_entradas": Decimal("0"),
                 "valor_saidas": Decimal("0"), "sem_conta": 0, "simulado": simular}
    try:
        conta_geral = fin.conta_padrao(cur, id_academia)
        if not conta_geral:
            resultado["erro"] = ("A academia não tem conta financeira. "
                                 "Rode a preparação de contas antes.")
            return resultado

        cur.execute(
            """SELECT r.id, r.descricao, r.valor, r.data, r.categoria,
                      r.id_forma_pagamento, r.id_mensalidade_aluno, r.id_cobranca_avulsa,
                      r.observacoes, r.criado_por, ma.aluno_id
               FROM receitas r
               LEFT JOIN mensalidade_aluno ma ON ma.id = r.id_mensalidade_aluno
               WHERE r.id_academia = %s AND COALESCE(r.cancelada, 0) = 0
                 AND r.id_lancamento IS NULL AND r.valor > 0
               ORDER BY r.data, r.id""",
            (id_academia,))
        receitas = cur.fetchall()

        for r in receitas:
            id_conta = fin.conta_padrao(cur, id_academia, r["id_forma_pagamento"])
            if not id_conta:
                resultado["sem_conta"] += 1
                continue
            if r["id_mensalidade_aluno"]:
                origem, origem_id = "mensalidade", r["id_mensalidade_aluno"]
            elif r["id_cobranca_avulsa"]:
                origem, origem_id = "cobranca_avulsa", r["id_cobranca_avulsa"]
            else:
                origem, origem_id = "receita", r["id"]

            if not simular:
                lanc = fin.lancar(
                    conn, cur, id_academia=id_academia, id_conta=id_conta,
                    sentido="entrada", valor=r["valor"],
                    descricao=r["descricao"] or "Receita",
                    data_competencia=r["data"], data_efetivacao=r["data"],
                    status="efetivado", origem=origem, origem_id=origem_id,
                    id_forma_pagamento=r["id_forma_pagamento"], id_aluno=r["aluno_id"],
                    observacoes="Importado do histórico de receitas.",
                    usuario_id=usuario_id or r["criado_por"],
                )
                cur.execute("UPDATE receitas SET id_lancamento = %s WHERE id = %s",
                            (lanc, r["id"]))
            resultado["receitas"] += 1
            resultado["valor_entradas"] += Decimal(str(r["valor"] or 0))

        cur.execute(
            """SELECT id, descricao, valor, data, categoria, observacoes, criado_por
               FROM despesas
               WHERE id_academia = %s AND id_lancamento IS NULL AND valor > 0
               ORDER BY data, id""",
            (id_academia,))
        despesas = cur.fetchall()

        for d in despesas:
            if not simular:
                lanc = fin.lancar(
                    conn, cur, id_academia=id_academia, id_conta=conta_geral,
                    sentido="saida", valor=d["valor"],
                    descricao=d["descricao"] or "Despesa",
                    data_competencia=d["data"], data_efetivacao=d["data"],
                    status="efetivado", origem="despesa", origem_id=d["id"],
                    observacoes="Importado do histórico de despesas.",
                    usuario_id=usuario_id or d["criado_por"],
                )
                cur.execute("UPDATE despesas SET id_lancamento = %s WHERE id = %s",
                            (lanc, d["id"]))
            resultado["despesas"] += 1
            resultado["valor_saidas"] += Decimal(str(d["valor"] or 0))

        if simular:
            conn.rollback()
        else:
            conn.commit()
            fin.auditar(cur, id_academia, "fin_lancamentos", None, "importar_legado",
                        valor_novo=resultado["valor_entradas"] - resultado["valor_saidas"],
                        usuario_id=usuario_id,
                        detalhes=f"{resultado['receitas']} receitas, {resultado['despesas']} despesas")
            conn.commit()
        return resultado
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
