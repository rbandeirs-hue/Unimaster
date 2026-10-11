# -*- coding: utf-8 -*-
"""Pagamento de despesa e Entradas x Saídas (utils/despesas_pagamento.py).

O banco é o de verdade: o fluxo de pagar/desfazer roda numa transação que
termina SEMPRE em rollback, e as telas só fazem GET.

Uso:  .venv/bin/python -m pytest tests/test_despesa_pagamento.py -q
"""
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection  # noqa: E402
from utils import despesas_pagamento as dp  # noqa: E402
from utils import financeiro_core as fin  # noqa: E402

ACADEMIA = 14
USUARIO = 3


@pytest.fixture
def transacao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        yield conn, cur
    finally:
        conn.rollback()
        conn.close()


def _nova_despesa(cur, valor="150.00", data=None):
    cur.execute("""INSERT INTO despesas (descricao, valor, data, categoria, id_academia, criado_por)
                   VALUES ('Teste pagamento', %s, %s, 'Teste', %s, %s)""",
                (valor, data or date.today(), ACADEMIA, USUARIO))
    return cur.lastrowid


def _conta(cur):
    cur.execute("SELECT id FROM fin_contas WHERE id_academia = %s AND ativo = 1 ORDER BY id LIMIT 1", (ACADEMIA,))
    return cur.fetchone()["id"]


def test_pagar_e_desfazer(transacao):
    conn, cur = transacao
    did = _nova_despesa(cur)
    conta = _conta(cur)
    saldo_antes = fin.saldo_conta(cur, conta)["saldo"]
    assert not dp.esta_paga(cur, did)

    lanc = dp.pagar(conn, cur, did, [ACADEMIA], data_pagamento=date.today(), id_conta=conta,
                    valor=Decimal("140.00"), usuario_id=USUARIO)
    assert dp.esta_paga(cur, did)
    cur.execute("SELECT sentido, valor, status, origem, origem_id FROM fin_lancamentos WHERE id = %s", (lanc,))
    l = cur.fetchone()
    assert (l["sentido"], l["valor"], l["status"], l["origem"], l["origem_id"]) == \
        ("saida", Decimal("140.00"), "efetivado", "despesa", did)
    assert fin.saldo_conta(cur, conta)["saldo"] == saldo_antes - Decimal("140.00")

    linha = [d for d in dp.listar(cur, ACADEMIA, date.today(), date.today()) if d["id"] == did][0]
    assert linha["paga"] and linha["valor_pago"] == Decimal("140.00")

    with pytest.raises(dp.ErroPagamento):
        dp.pagar(conn, cur, did, [ACADEMIA], data_pagamento=date.today(), id_conta=conta, usuario_id=USUARIO)

    dp.desfazer(conn, cur, did, [ACADEMIA], usuario_id=USUARIO)
    assert not dp.esta_paga(cur, did)
    assert fin.saldo_conta(cur, conta)["saldo"] == saldo_antes


def test_recusas(transacao):
    conn, cur = transacao
    did = _nova_despesa(cur)
    conta = _conta(cur)
    with pytest.raises(dp.ErroPagamento):   # despesa de outra academia
        dp.pagar(conn, cur, did, [1], data_pagamento=date.today(), id_conta=conta)
    with pytest.raises(dp.ErroPagamento):   # conta de outra academia
        cur.execute("SELECT id FROM fin_contas WHERE id_academia <> %s LIMIT 1", (ACADEMIA,))
        dp.pagar(conn, cur, did, [ACADEMIA], data_pagamento=date.today(), id_conta=cur.fetchone()["id"])
    with pytest.raises(dp.ErroPagamento):   # pagamento no futuro
        dp.pagar(conn, cur, did, [ACADEMIA], data_pagamento=date.today() + timedelta(days=1), id_conta=conta)
    with pytest.raises(dp.ErroPagamento):   # desfazer o que não foi pago
        dp.desfazer(conn, cur, did, [ACADEMIA])


def test_entradas_saidas_conta_so_o_pago(transacao):
    conn, cur = transacao
    hoje = date.today()
    antes = dp.entradas_saidas(cur, ACADEMIA, hoje.year, hoje.month)
    did = _nova_despesa(cur, "80.00", hoje)
    meio = dp.entradas_saidas(cur, ACADEMIA, hoje.year, hoje.month)
    assert meio["saidas"] == antes["saidas"]
    assert meio["a_pagar"] == antes["a_pagar"] + Decimal("80.00")
    dp.pagar(conn, cur, did, [ACADEMIA], data_pagamento=hoje, id_conta=_conta(cur))
    depois = dp.entradas_saidas(cur, ACADEMIA, hoje.year, hoje.month)
    assert depois["saidas"] == antes["saidas"] + Decimal("80.00")
    assert depois["a_pagar"] == antes["a_pagar"]
    assert depois["serie"][-1]["saidas"] == depois["saidas"]


@pytest.fixture
def cliente():
    from app import app
    c = app.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(USUARIO)
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = ACADEMIA
    return c


def test_telas(cliente):
    r = cliente.get("/financeiro/despesas?mes=10&ano=2026")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "js-pagar-despesa" in html and "dlgPagarDespesa" in html
    r = cliente.get("/financeiro/painel/fluxo?mes=2026-10")
    assert r.status_code == 200
    assert "Entradas x Saídas" in r.get_data(as_text=True)
    r = cliente.get("/financeiro/despesas/cadastrar")
    assert r.status_code == 200 and 'name="ja_paga"' in r.get_data(as_text=True)


# ---------------------------------------------------------------------
# Ponta a ponta pelas rotas, numa academia fictícia apagada no fim
# ---------------------------------------------------------------------
FICTICIA = -9902


def _limpar_ficticia(cur):
    cur.execute("DELETE FROM fin_auditoria WHERE id_academia = %s", (FICTICIA,))
    cur.execute("UPDATE despesas SET id_lancamento = NULL WHERE id_academia = %s", (FICTICIA,))
    cur.execute("UPDATE fin_lancamentos SET id_estorno = NULL, id_lancamento_origem = NULL WHERE id_academia = %s", (FICTICIA,))
    cur.execute("DELETE FROM fin_lancamentos WHERE id_academia = %s", (FICTICIA,))
    cur.execute("DELETE FROM despesas WHERE id_academia = %s", (FICTICIA,))
    cur.execute("DELETE FROM fin_contas WHERE id_academia = %s", (FICTICIA,))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (FICTICIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (FICTICIA,))


@pytest.fixture
def ficticia():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    _limpar_ficticia(cur)
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Pagamento de despesa')", (FICTICIA,))
    cur.execute("INSERT INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)", (USUARIO, FICTICIA))
    cur.execute("INSERT INTO fin_contas (id_academia, nome, tipo, saldo_inicial) VALUES (%s, 'Caixa', 'caixa', 0)", (FICTICIA,))
    conta = cur.lastrowid
    conn.commit()
    from app import app
    app.config["WTF_CSRF_ENABLED"] = False
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO)
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = FICTICIA
    try:
        yield cli, conn, cur, conta
    finally:
        conn.rollback()
        _limpar_ficticia(cur)
        conn.commit()
        conn.close()


def _despesa(conn, cur, descricao):
    conn.commit()  # enxerga o que as rotas gravaram
    cur.execute("""SELECT d.id, d.id_lancamento, l.valor, l.id_conta FROM despesas d
                   LEFT JOIN fin_lancamentos l ON l.id = d.id_lancamento
                   WHERE d.id_academia = %s AND d.descricao = %s""", (FICTICIA, descricao))
    return cur.fetchone()


def test_rotas_ponta_a_ponta(ficticia):
    cli, conn, cur, conta = ficticia
    hoje = date.today().isoformat()
    base = {"data": hoje, "id_academia": FICTICIA}

    cli.post(f"/financeiro/despesas/cadastrar?academia_id={FICTICIA}",
             data=dict(base, descricao="Luz", valor="90,50", ja_paga="1",
                       data_pagamento=hoje, id_conta=conta))
    luz = _despesa(conn, cur, "Luz")
    assert luz["id_lancamento"] and luz["valor"] == Decimal("90.50") and luz["id_conta"] == conta

    cli.post(f"/financeiro/despesas/cadastrar?academia_id={FICTICIA}",
             data=dict(base, descricao="Aluguel", valor="100"))
    aluguel = _despesa(conn, cur, "Aluguel")
    assert not aluguel["id_lancamento"]

    h = cli.post(f"/financeiro/despesas/{aluguel['id']}/pagar", follow_redirects=True,
                 data={"data_pagamento": hoje, "id_conta": conta, "valor_pago": "100,00"}).get_data(as_text=True)
    assert "Pagamento da despesa registrado" in h
    h = cli.post(f"/financeiro/despesas/excluir/{aluguel['id']}", follow_redirects=True).get_data(as_text=True)
    assert "Desfaça o pagamento" in h and _despesa(conn, cur, "Aluguel")
    h = cli.post(f"/financeiro/despesas/{aluguel['id']}/desfazer-pagamento",
                 follow_redirects=True).get_data(as_text=True)
    assert "Pagamento desfeito" in h and not _despesa(conn, cur, "Aluguel")["id_lancamento"]

    h = cli.get("/financeiro/painel/fluxo").get_data(as_text=True)
    assert "R$ 90,50" in h and "Aluguel" in h   # paga nas saídas; aluguel volta a "a pagar"


def test_trocar_forma_da_entrada(transacao):
    conn, cur = transacao
    cur.execute("""SELECT id FROM formas_pagamento WHERE id_academia = %s AND id_conta_padrao IS NOT NULL
                   AND COALESCE(ativo, 1) = 1 LIMIT 1""", (ACADEMIA,))
    forma = cur.fetchone()["id"]
    cur.execute("""INSERT INTO receitas (descricao, valor, data, categoria, id_academia)
                   VALUES ('Teste forma', 10, %s, 'Teste', %s)""", (date.today(), ACADEMIA))
    rid = cur.lastrowid
    sem = dp.entradas_do_mes(cur, ACADEMIA, date.today(), date.today(), "sem")
    assert rid in [e["id"] for e in sem]
    dp.trocar_forma_receita(conn, cur, rid, ACADEMIA, forma, usuario_id=USUARIO)
    assert rid in [e["id"] for e in dp.entradas_do_mes(cur, ACADEMIA, date.today(), date.today(), forma)]
    with pytest.raises(dp.ErroPagamento):   # entrada de outra academia
        dp.trocar_forma_receita(conn, cur, rid, 1, forma)


def test_trocar_forma_move_o_lancamento_para_a_conta_da_forma(transacao):
    conn, cur = transacao
    cur.execute("""SELECT id, id_conta_padrao FROM formas_pagamento WHERE id_academia = %s
                   AND id_conta_padrao IS NOT NULL ORDER BY id""", (ACADEMIA,))
    formas = cur.fetchall()
    destino = formas[0]
    outra = next(c for c in [_conta(cur)] + [f["id_conta_padrao"] for f in formas]
                 if c != destino["id_conta_padrao"])
    lanc = fin.lancar(conn, cur, id_academia=ACADEMIA, id_conta=outra, sentido="entrada",
                      valor=Decimal("12"), descricao="Teste", data_competencia=date.today(),
                      origem="receita", usuario_id=USUARIO)
    cur.execute("""INSERT INTO receitas (descricao, valor, data, id_academia, id_lancamento)
                   VALUES ('Teste conta', 12, %s, %s, %s)""", (date.today(), ACADEMIA, lanc))
    dp.trocar_forma_receita(conn, cur, cur.lastrowid, ACADEMIA, destino["id"], usuario_id=USUARIO)
    cur.execute("SELECT id_conta, id_forma_pagamento FROM fin_lancamentos WHERE id = %s", (lanc,))
    l = cur.fetchone()
    assert (l["id_conta"], l["id_forma_pagamento"]) == (destino["id_conta_padrao"], destino["id"])


def test_tela_lista_entradas_sem_forma(cliente):
    h = cliente.get("/financeiro/painel/fluxo?mes=2026-10&entradas=sem").get_data(as_text=True)
    assert 'id="entradas"' in h and "receitas/" in h and "/forma" in h
