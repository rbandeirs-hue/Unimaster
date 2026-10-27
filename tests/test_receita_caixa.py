# -*- coding: utf-8 -*-
"""Receita → caixa: toda baixa entra no caixa uma vez, com auditoria, e o
cancelamento estorna (utils/financeiro_core.espelhar_receita / estornar_receitas).

Academia fictícia (-9910) criada e apagada pelo próprio teste.

Uso:  .venv/bin/python -m pytest tests/test_receita_caixa.py -q
"""
import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from config import get_db_connection  # noqa: E402

A, USUARIO = -9910, 3


def _limpar(cur):
    cur.execute("DELETE FROM fin_auditoria WHERE id_academia = %s", (A,))
    cur.execute("""DELETE cm FROM carteira_movimentos cm JOIN alunos a ON a.id = cm.aluno_id
                   WHERE a.id_academia = %s""", (A,))
    cur.execute("UPDATE receitas SET id_lancamento = NULL WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM receitas WHERE id_academia = %s", (A,))
    cur.execute("UPDATE fin_lancamentos SET id_estorno = NULL, id_lancamento_origem = NULL WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM fin_lancamentos WHERE id_academia = %s", (A,))
    cur.execute("""DELETE ma FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id
                   WHERE m.id_academia = %s""", (A,))
    cur.execute("DELETE FROM mensalidades WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM formas_pagamento WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM fin_contas WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM fin_config WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM roles_usuario WHERE academia_id = %s", (A,))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (A,))
    cur.execute("DELETE FROM academias WHERE id = %s", (A,))


@pytest.fixture
def base():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        _limpar(cur)
        cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Caixa')", (A,))
        cur.execute("INSERT INTO usuarios_academias (usuario_id, academia_id, gestor_principal) VALUES (%s, %s, 1)", (USUARIO, A))
        cur.execute("""INSERT INTO roles_usuario (usuario_id, role_id, academia_id)
                       SELECT %s, id, %s FROM roles WHERE chave = 'gestor_academia'""", (USUARIO, A))
        cur.execute("INSERT INTO fin_config (id_academia, modo) VALUES (%s, 'parcial')", (A,))
        cur.execute("INSERT INTO fin_contas (id_academia, nome, tipo, saldo_inicial) VALUES (%s, 'Caixa', 'caixa', 0)", (A,))
        caixa = cur.lastrowid
        cur.execute("INSERT INTO fin_contas (id_academia, nome, tipo, saldo_inicial) VALUES (%s, 'Pix', 'pix', 0)", (A,))
        pix = cur.lastrowid
        cur.execute("INSERT INTO formas_pagamento (id_academia, nome, id_conta_padrao, ativo, ordem) VALUES (%s, 'PIX', %s, 1, 1)", (A, pix))
        forma = cur.lastrowid
        cur.execute("INSERT INTO mensalidades (nome, valor, id_academia, ativo) VALUES ('Plano', 100, %s, 1)", (A,))
        plano = cur.lastrowid
        cur.execute("INSERT INTO alunos (nome, id_academia) VALUES ('Aluno Caixa', %s)", (A,))
        aluno = cur.lastrowid
        mens = []
        for _ in range(2):
            cur.execute("""INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, data_vencimento, valor, status)
                           VALUES (%s, %s, %s, 100, 'pendente')""", (plano, aluno, date.today()))
            mens.append(cur.lastrowid)
        conn.commit()
        yield conn, cur, dict(caixa=caixa, pix=pix, forma=forma, mens=mens)
    finally:
        conn.rollback()
        _limpar(cur)
        conn.commit()
        conn.close()


def _lancamentos(conn, cur):
    conn.commit()
    cur.execute("""SELECT id, id_conta, sentido, valor, origem, id_estorno FROM fin_lancamentos
                   WHERE id_academia = %s ORDER BY id""", (A,))
    return cur.fetchall()


def _auditoria(conn, cur, acao):
    conn.commit()
    cur.execute("SELECT COUNT(*) n FROM fin_auditoria WHERE id_academia = %s AND acao = %s", (A, acao))
    return cur.fetchone()["n"]


def test_baixa_manual_entra_uma_vez_no_caixa_e_cancelamento_estorna(base):
    conn, cur, d = base
    from blueprints.financeiro import routes as fr
    from flask_login import login_user
    with app.test_request_context():
        login_user(app.login_manager._user_callback(str(USUARIO)))
        c2 = get_db_connection()
        k2 = c2.cursor()
        assert fr._registrar_pagamento_e_receita(c2, k2, "mensalidade_aluno", d["mens"][0], A,
                                                 id_forma_pagamento=d["forma"],
                                                 data_pagamento=date.today().isoformat())
        c2.commit()
        c2.close()

    ls = _lancamentos(conn, cur)
    assert len(ls) == 1, ls                                        # uma vez só
    assert (ls[0]["id_conta"], ls[0]["sentido"], ls[0]["valor"]) == (d["pix"], "entrada", Decimal("100.00"))
    cur.execute("SELECT id_lancamento FROM receitas WHERE id_mensalidade_aluno = %s", (d["mens"][0],))
    assert cur.fetchone()["id_lancamento"] == ls[0]["id"]
    assert _auditoria(conn, cur, "baixa") == 1

    app.config["WTF_CSRF_ENABLED"] = False
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO)
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = A
    h = cli.post("/financeiro/mensalidades/cancelar-pagamento", follow_redirects=True,
                 data={"tipo": "mensalidade_aluno", "registro_id": d["mens"][0],
                       "motivo": "Lançado no aluno errado"}).get_data(as_text=True)
    assert "estornada no caixa" in h
    ls = _lancamentos(conn, cur)
    assert len(ls) == 2 and ls[0]["id_estorno"] == ls[1]["id"] and ls[1]["sentido"] == "saida"
    cur.execute("""SELECT motivo FROM fin_auditoria WHERE id_academia = %s AND acao = 'cancelar_pagamento'""", (A,))
    assert cur.fetchone()["motivo"] == "Lançado no aluno errado"
    from utils import financeiro_core as fin
    assert fin.saldo_conta(cur, d["pix"])["saldo"] == 0


def test_baixa_pelo_gateway_entra_no_caixa(base):
    conn, cur, d = base
    from blueprints.financeiro import routes as fr
    with app.test_request_context():
        fr._baixar_cobranca_paga("mensalidade", d["mens"][1], 100.0, "infinitepay")
    ls = _lancamentos(conn, cur)
    assert len(ls) == 1 and ls[0]["sentido"] == "entrada" and ls[0]["valor"] == Decimal("100.00")
    assert ls[0]["id_conta"] == d["caixa"]                         # sem forma: conta padrão
    assert _auditoria(conn, cur, "baixa") == 1
