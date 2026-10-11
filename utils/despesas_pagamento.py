"""Pagamento de despesas e a visão de entradas x saídas.

A despesa cadastrada é uma conta a pagar. Pagar é dizer DE ONDE o dinheiro
saiu: a conta (caixa, banco, Pix), a forma, a data e o valor — e isso vira um
lançamento de saída no razão (`fin_lancamentos`, utils/financeiro_core.py),
ligado à despesa por `despesas.id_lancamento`. Não há coluna de status na
despesa: ela está paga quando o lançamento dela está efetivado e não foi
estornado. Desfazer o pagamento estorna o lançamento (o histórico fica no
extrato) e solta o vínculo.

Entradas x saídas compara o que de fato entrou (receitas não canceladas, pela
data) com o que de fato saiu (despesas pagas, pela data do pagamento), e põe
ao lado o que ainda está previsto: mensalidades e cobranças em aberto e
despesas a pagar.
"""
from datetime import date, timedelta
from decimal import Decimal

from utils import financeiro_core as fin

# Despesa paga = lançamento efetivado e não estornado. O estorno mantém o
# original 'efetivado' e só preenche id_estorno (ver financeiro_core.estornar).
SQL_PAGA = "(l.id IS NOT NULL AND l.status = 'efetivado' AND l.id_estorno IS NULL)"


class ErroPagamento(fin.ErroFinanceiro):
    pass


def _dec(v):
    return Decimal(str(v or 0))


def contas_e_formas(cur, id_academia):
    """Contas ativas e formas de pagamento ativas (com a conta padrão de cada uma)."""
    cur.execute("""SELECT id, nome, tipo FROM fin_contas
                   WHERE id_academia = %s AND ativo = 1 ORDER BY nome""", (id_academia,))
    contas = cur.fetchall()
    cur.execute("""SELECT id, nome, id_conta_padrao FROM formas_pagamento
                   WHERE id_academia = %s AND COALESCE(ativo, 1) = 1
                   ORDER BY ordem, nome""", (id_academia,))
    return contas, cur.fetchall()


def garantir_conta(conn, cur, id_academia, usuario_id=None):
    """Academia sem conta nenhuma ganha as contas das formas de pagamento
    (ou um Caixa) — sem isso não haveria de onde a despesa sair."""
    cur.execute("SELECT 1 FROM fin_contas WHERE id_academia = %s AND ativo = 1 LIMIT 1", (id_academia,))
    if cur.fetchone():
        return
    fin.preparar_contas(conn, cur, id_academia, usuario_id=usuario_id)


def pagar(conn, cur, despesa_id, ids_academias, *, data_pagamento, id_conta,
          id_forma_pagamento=None, valor=None, observacoes=None, usuario_id=None):
    """Registra o pagamento. Devolve o id do lançamento. Não faz commit."""
    if not ids_academias:
        raise ErroPagamento("Sem academia.")
    ph = ",".join(["%s"] * len(ids_academias))
    cur.execute(
        f"""SELECT d.*, l.status AS l_status, l.id_estorno AS l_estorno
            FROM despesas d LEFT JOIN fin_lancamentos l ON l.id = d.id_lancamento
            WHERE d.id = %s AND d.id_academia IN ({ph}) FOR UPDATE""",
        (despesa_id,) + tuple(ids_academias))
    d = cur.fetchone()
    if not d:
        raise ErroPagamento("Despesa não encontrada.")
    if d["id_lancamento"] and d["l_status"] == "efetivado" and not d["l_estorno"]:
        raise ErroPagamento("Esta despesa já está paga.")
    id_academia = int(d["id_academia"])

    cur.execute("SELECT id FROM fin_contas WHERE id = %s AND id_academia = %s AND ativo = 1",
                (id_conta, id_academia))
    if not cur.fetchone():
        raise ErroPagamento("Escolha a conta de onde o dinheiro saiu.")
    if id_forma_pagamento:
        cur.execute("SELECT id FROM formas_pagamento WHERE id = %s AND id_academia = %s",
                    (id_forma_pagamento, id_academia))
        if not cur.fetchone():
            raise ErroPagamento("Forma de pagamento inválida.")
    valor = _dec(valor if valor not in (None, "") else d["valor"])
    if valor <= 0:
        raise ErroPagamento("Informe o valor pago.")
    if not isinstance(data_pagamento, date):
        raise ErroPagamento("Informe a data do pagamento.")
    if data_pagamento > date.today():
        raise ErroPagamento("A data do pagamento não pode ser no futuro.")

    lanc_id = fin.lancar(
        conn, cur, id_academia=id_academia, id_conta=id_conta, sentido="saida",
        valor=valor, descricao=(d["descricao"] or "Despesa")[:255],
        data_competencia=data_pagamento, data_efetivacao=data_pagamento,
        status="efetivado", origem="despesa", origem_id=despesa_id,
        id_forma_pagamento=id_forma_pagamento or None,
        observacoes=observacoes, usuario_id=usuario_id)
    cur.execute("UPDATE despesas SET id_lancamento = %s WHERE id = %s", (lanc_id, despesa_id))
    return lanc_id


def desfazer(conn, cur, despesa_id, ids_academias, *, motivo=None, usuario_id=None):
    """Estorna o pagamento: a despesa volta a ficar a pagar. Não faz commit."""
    ph = ",".join(["%s"] * len(ids_academias))
    cur.execute(
        f"""SELECT d.id, d.id_lancamento, l.status, l.id_estorno
            FROM despesas d LEFT JOIN fin_lancamentos l ON l.id = d.id_lancamento
            WHERE d.id = %s AND d.id_academia IN ({ph}) FOR UPDATE""",
        (despesa_id,) + tuple(ids_academias))
    d = cur.fetchone()
    if not d:
        raise ErroPagamento("Despesa não encontrada.")
    if not d["id_lancamento"] or d["status"] != "efetivado" or d["id_estorno"]:
        raise ErroPagamento("Esta despesa não está paga.")
    fin.estornar(conn, cur, d["id_lancamento"],
                 motivo=motivo or "Pagamento de despesa desfeito.", usuario_id=usuario_id)
    cur.execute("UPDATE despesas SET id_lancamento = NULL WHERE id = %s", (despesa_id,))


def esta_paga(cur, despesa_id):
    cur.execute(f"""SELECT {SQL_PAGA} AS paga FROM despesas d
                    LEFT JOIN fin_lancamentos l ON l.id = d.id_lancamento
                    WHERE d.id = %s""", (despesa_id,))
    r = cur.fetchone()
    return bool(r and (r["paga"] if isinstance(r, dict) else r[0]))


def listar(cur, id_academia, inicio, fim, situacao=None):
    """Despesas com data (vencimento) no período, com a situação do pagamento."""
    onde = ["d.id_academia = %s", "d.data BETWEEN %s AND %s"]
    if situacao == "pagas":
        onde.append(SQL_PAGA)
    elif situacao == "a_pagar":
        onde.append(f"NOT {SQL_PAGA}")
    cur.execute(
        f"""SELECT d.id, d.descricao, d.valor, d.data, d.categoria,
                   {SQL_PAGA} AS paga, l.valor AS valor_pago, l.data_efetivacao AS data_pagamento,
                   c.nome AS conta_nome, fp.nome AS forma_nome
            FROM despesas d
            LEFT JOIN fin_lancamentos l ON l.id = d.id_lancamento
            LEFT JOIN fin_contas c ON c.id = l.id_conta
            LEFT JOIN formas_pagamento fp ON fp.id = l.id_forma_pagamento
            WHERE {' AND '.join(onde)}
            ORDER BY d.data, d.id""",
        (id_academia, inicio, fim))
    linhas = cur.fetchall()
    hoje = date.today()
    for r in linhas:
        r["paga"] = bool(r["paga"])
        r["vencida"] = not r["paga"] and r["data"] < hoje
    return linhas


# ---------------------------------------------------------------------
# Entradas x saídas
# ---------------------------------------------------------------------
def _fim_do_mes(ano, mes):
    return date(ano + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)


def _meses_ate(ano, mes, qtd):
    out = []
    for _ in range(qtd):
        out.append((ano, mes))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    return list(reversed(out))


def entradas_saidas(cur, id_academia, ano, mes, meses_serie=6):
    inicio, fim = date(ano, mes, 1), _fim_do_mes(ano, mes)
    hoje = date.today()

    # Realizado no mês -------------------------------------------------
    cur.execute("""SELECT COALESCE(NULLIF(TRIM(r.categoria), ''), 'Sem categoria') AS nome,
                          SUM(r.valor) AS total, COUNT(*) AS n
                   FROM receitas r
                   WHERE r.id_academia = %s AND COALESCE(r.cancelada, 0) = 0
                     AND r.data BETWEEN %s AND %s
                   GROUP BY 1 ORDER BY total DESC""", (id_academia, inicio, fim))
    entradas_cat = cur.fetchall()
    cur.execute("""SELECT COALESCE(fp.nome, 'Não informada') AS nome, SUM(r.valor) AS total
                   FROM receitas r LEFT JOIN formas_pagamento fp ON fp.id = r.id_forma_pagamento
                   WHERE r.id_academia = %s AND COALESCE(r.cancelada, 0) = 0
                     AND r.data BETWEEN %s AND %s
                   GROUP BY 1 ORDER BY total DESC""", (id_academia, inicio, fim))
    entradas_forma = cur.fetchall()
    cur.execute(f"""SELECT COALESCE(NULLIF(TRIM(d.categoria), ''), 'Sem categoria') AS nome,
                           SUM(l.valor) AS total, COUNT(*) AS n
                    FROM despesas d JOIN fin_lancamentos l ON l.id = d.id_lancamento
                    WHERE d.id_academia = %s AND {SQL_PAGA}
                      AND l.data_efetivacao BETWEEN %s AND %s
                    GROUP BY 1 ORDER BY total DESC""", (id_academia, inicio, fim))
    saidas_cat = cur.fetchall()
    entradas = sum((_dec(r["total"]) for r in entradas_cat), Decimal("0"))
    saidas = sum((_dec(r["total"]) for r in saidas_cat), Decimal("0"))

    # Previsto (em aberto) com vencimento no mês -----------------------
    cur.execute("""SELECT COALESCE(SUM(ma.valor), 0) AS v, COUNT(*) AS n
                   FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id
                   WHERE m.id_academia = %s AND ma.status IN ('pendente', 'atrasado')
                     AND ma.data_vencimento BETWEEN %s AND %s""", (id_academia, inicio, fim))
    r = cur.fetchone()
    a_receber, n_receber = _dec(r["v"]), int(r["n"])
    cur.execute("""SELECT COALESCE(SUM(valor), 0) AS v, COUNT(*) AS n FROM cobranca_avulsa
                   WHERE id_academia = %s AND status IN ('pendente', 'atrasado')
                     AND data_vencimento BETWEEN %s AND %s""", (id_academia, inicio, fim))
    r = cur.fetchone()
    a_receber += _dec(r["v"]); n_receber += int(r["n"])
    a_pagar_lista = listar(cur, id_academia, inicio, fim, "a_pagar")
    a_pagar = sum((_dec(d["valor"]) for d in a_pagar_lista), Decimal("0"))

    # Despesas vencidas de meses anteriores ainda sem pagamento.
    cur.execute(f"""SELECT COALESCE(SUM(d.valor), 0) AS v, COUNT(*) AS n
                    FROM despesas d LEFT JOIN fin_lancamentos l ON l.id = d.id_lancamento
                    WHERE d.id_academia = %s AND d.data < %s AND NOT {SQL_PAGA}""",
                (id_academia, inicio))
    r = cur.fetchone()
    atrasadas_antes, n_atrasadas_antes = _dec(r["v"]), int(r["n"])

    # Série dos últimos meses ------------------------------------------
    serie_meses = _meses_ate(ano, mes, meses_serie)
    s_ini = date(*serie_meses[0], 1)
    cur.execute("""SELECT YEAR(data) a, MONTH(data) m, SUM(valor) v FROM receitas
                   WHERE id_academia = %s AND COALESCE(cancelada, 0) = 0
                     AND data BETWEEN %s AND %s GROUP BY 1, 2""", (id_academia, s_ini, fim))
    ent_m = {(int(x["a"]), int(x["m"])): _dec(x["v"]) for x in cur.fetchall()}
    cur.execute(f"""SELECT YEAR(l.data_efetivacao) a, MONTH(l.data_efetivacao) m, SUM(l.valor) v
                    FROM despesas d JOIN fin_lancamentos l ON l.id = d.id_lancamento
                    WHERE d.id_academia = %s AND {SQL_PAGA}
                      AND l.data_efetivacao BETWEEN %s AND %s GROUP BY 1, 2""",
                (id_academia, s_ini, fim))
    sai_m = {(int(x["a"]), int(x["m"])): _dec(x["v"]) for x in cur.fetchall()}
    serie = [{"ano": a, "mes": m, "entradas": ent_m.get((a, m), Decimal("0")),
              "saidas": sai_m.get((a, m), Decimal("0"))} for a, m in serie_meses]
    maior = max([Decimal("1")] + [max(s["entradas"], s["saidas"]) for s in serie])
    for s in serie:
        s["resultado"] = s["entradas"] - s["saidas"]
        s["pct_entradas"] = float(s["entradas"] / maior * 100)
        s["pct_saidas"] = float(s["saidas"] / maior * 100)

    return {
        "inicio": inicio, "fim": fim, "mes_corrente": (ano, mes) == (hoje.year, hoje.month),
        "entradas": entradas, "saidas": saidas, "resultado": entradas - saidas,
        "entradas_cat": entradas_cat, "entradas_forma": entradas_forma, "saidas_cat": saidas_cat,
        "a_receber": a_receber, "n_receber": n_receber,
        "a_pagar": a_pagar, "a_pagar_lista": a_pagar_lista,
        "atrasadas_antes": atrasadas_antes, "n_atrasadas_antes": n_atrasadas_antes,
        "previsto": entradas - saidas + a_receber - a_pagar,
        "serie": serie,
    }
