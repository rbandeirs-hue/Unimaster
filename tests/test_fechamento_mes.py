# -*- coding: utf-8 -*-
"""Fechamento de mês e receita manual acompanhando o caixa.

Academia fictícia (-9911) criada e apagada pelo próprio teste.

Uso:  .venv/bin/python -m pytest tests/test_fechamento_mes.py -q
"""
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from config import get_db_connection  # noqa: E402
from utils import financeiro_core as fin  # noqa: E402

A, USUARIO = -9911, 3
HOJE = date.today()
MES_PASSADO = (HOJE.replace(day=1) - timedelta(days=1)).replace(day=10)
CHAVE = f"{MES_PASSADO:%Y-%m}"


def _limpar(cur):
    cur.execute("DELETE FROM fin_auditoria WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM fin_fechamentos WHERE id_academia = %s", (A,))
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
        cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Fechamento')", (A,))
        cur.execute("INSERT INTO usuarios_academias (usuario_id, academia_id, gestor_principal) VALUES (%s, %s, 1)", (USUARIO, A))
        cur.execute("""INSERT INTO roles_usuario (usuario_id, role_id, academia_id)
                       SELECT %s, id, %s FROM roles WHERE chave = 'gestor_academia'""", (USUARIO, A))
        cur.execute("INSERT INTO fin_config (id_academia, modo) VALUES (%s, 'parcial')", (A,))
        cur.execute("INSERT INTO fin_contas (id_academia, nome, tipo, saldo_inicial) VALUES (%s, 'Caixa', 'caixa', 0)", (A,))
        cur.execute("INSERT INTO mensalidades (nome, valor, id_academia, ativo) VALUES ('Plano', 100, %s, 1)", (A,))
        plano = cur.lastrowid
        cur.execute("INSERT INTO alunos (nome, id_academia) VALUES ('Aluno Fech', %s)", (A,))
        aluno = cur.lastrowid
        mens = []
        for _ in range(2):
            cur.execute("""INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, data_vencimento, valor, status)
                           VALUES (%s, %s, %s, 100, 'atrasado')""", (plano, aluno, MES_PASSADO))
            mens.append(cur.lastrowid)
        conn.commit()
        app.config["WTF_CSRF_ENABLED"] = False
        cli = app.test_client()
        with cli.session_transaction() as s:
            s["_user_id"] = str(USUARIO)
            s["_fresh"] = True
            s["modo_painel"] = "academia"
            s["academia_gerenciamento_id"] = A
        yield conn, cur, cli, mens
    finally:
        conn.rollback()
        _limpar(cur)
        conn.commit()
        conn.close()


def _pagar(mid, quando):
    from blueprints.financeiro import routes as fr
    from flask_login import login_user
    with app.test_request_context():
        login_user(app.login_manager._user_callback(str(USUARIO)))
        c2 = get_db_connection()
        k = c2.cursor()
        ok = fr._registrar_pagamento_e_receita(c2, k, "mensalidade_aluno", mid, A,
                                               data_pagamento=quando.isoformat())
        c2.commit()
        c2.close()
    return ok


def test_mes_fechado_trava_e_reabrir_exige_motivo(base):
    conn, cur, cli, mens = base
    assert _pagar(mens[0], MES_PASSADO)

    h = cli.post("/financeiro/painel/fechamento", data={"mes": CHAVE, "acao": "fechar"},
                 follow_redirects=True).get_data(as_text=True)
    assert "fechado" in h and "R$ 100,00" in h
    conn.commit()
    assert fin.mes_fechado(cur, A, MES_PASSADO)

    assert _pagar(mens[1], MES_PASSADO) is False                     # baixa no mês fechado
    h = cli.post("/financeiro/mensalidades/cancelar-pagamento", follow_redirects=True,
                 data={"tipo": "mensalidade_aluno", "registro_id": mens[0]}).get_data(as_text=True)
    assert "mês já fechado" in h                                     # cancelamento recusado
    h = cli.post(f"/financeiro/receitas/cadastrar?academia_id={A}", follow_redirects=True,
                 data={"descricao": "Rifa", "valor": "50", "data": MES_PASSADO.isoformat(),
                       "id_academia": A}).get_data(as_text=True)
    assert "está fechado" in h

    h = cli.post("/financeiro/painel/fechamento", data={"mes": CHAVE, "acao": "reabrir", "motivo": ""},
                 follow_redirects=True).get_data(as_text=True)
    assert "Informe o motivo" in h
    cli.post("/financeiro/painel/fechamento", data={"mes": CHAVE, "acao": "reabrir", "motivo": "Teste"})
    conn.commit()
    assert not fin.mes_fechado(cur, A, MES_PASSADO)
    h = cli.post("/financeiro/mensalidades/cancelar-pagamento", follow_redirects=True,
                 data={"tipo": "mensalidade_aluno", "registro_id": mens[0]}).get_data(as_text=True)
    assert "estornada no caixa" in h


def test_editar_receita_manual_move_o_caixa(base):
    conn, cur, cli, mens = base
    cli.post(f"/financeiro/receitas/cadastrar?academia_id={A}",
             data={"descricao": "Patrocínio", "valor": "80", "data": HOJE.isoformat(), "id_academia": A})
    conn.commit()
    cur.execute("SELECT id FROM receitas WHERE id_academia = %s AND descricao = 'Patrocínio'", (A,))
    rid = cur.fetchone()["id"]
    cur.execute("SELECT id FROM fin_contas WHERE id_academia = %s", (A,))
    conta = cur.fetchone()["id"]
    assert fin.saldo_conta(cur, conta)["saldo"] == Decimal("80")

    cli.post(f"/financeiro/receitas/editar/{rid}?academia_id={A}",
             data={"descricao": "Patrocínio", "valor": "120", "data": HOJE.isoformat(), "id_academia": A})
    conn.commit()
    assert fin.saldo_conta(cur, conta)["saldo"] == Decimal("120")     # estorno de 80 + novo de 120

    cli.post(f"/financeiro/receitas/excluir/{rid}", data={"academia_id": A})
    conn.commit()
    assert fin.saldo_conta(cur, conta)["saldo"] == Decimal("0")
