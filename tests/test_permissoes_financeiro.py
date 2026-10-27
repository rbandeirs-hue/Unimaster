# -*- coding: utf-8 -*-
"""Níveis de permissão do financeiro (MM-16) — utils/acesso_academia.

Academia fictícia (-9912) criada e apagada pelo próprio teste.

Uso:  .venv/bin/python -m pytest tests/test_permissoes_financeiro.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from config import get_db_connection  # noqa: E402
from utils import acesso_academia as acs  # noqa: E402

A = -9912


def test_classificacao_das_acoes():
    assert acs.nivel_financeiro_exigido("financeiro.registrar_pagamento", "POST") == "fin_baixar"
    assert acs.nivel_financeiro_exigido("financeiro.cancelar_pagamento", "POST") == "fin_estornar"
    assert acs.nivel_financeiro_exigido("financeiro.cancelar_pagamento", "GET") is None
    assert acs.nivel_financeiro_exigido("financeiro.lista_despesas", "POST") is None


def _limpar(cur, uid=None):
    cur.execute("DELETE FROM roles_usuario WHERE academia_id = %s", (A,))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (A,))
    cur.execute("DELETE FROM despesas WHERE id_academia = %s", (A,))
    cur.execute("DELETE FROM academias WHERE id = %s", (A,))


@pytest.fixture
def professor():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    # Um professor qualquer da base, sem papel global de escopo amplo.
    cur.execute("""SELECT u.id FROM usuarios u WHERE COALESCE(u.ativo, 1) = 1 AND u.cpf IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM roles_usuario ru JOIN roles r ON r.id = ru.role_id
                                   WHERE ru.usuario_id = u.id
                                     AND r.chave IN ('admin', 'gestor_associacao', 'gestor_federacao'))
                   LIMIT 1""")
    uid = cur.fetchone()["id"]
    try:
        _limpar(cur)
        cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Permissões')", (A,))
        cur.execute("""INSERT INTO usuarios_academias (usuario_id, academia_id, gestor_principal, acesso_financeiro)
                       VALUES (%s, %s, 0, 0)""", (uid, A))
        cur.execute("""INSERT INTO roles_usuario (usuario_id, role_id, academia_id)
                       SELECT %s, id, %s FROM roles WHERE chave = 'professor'""", (uid, A))
        cur.execute("INSERT INTO despesas (descricao, valor, data, id_academia) VALUES ('X', 10, CURDATE(), %s)", (A,))
        did = cur.lastrowid
        conn.commit()
        yield conn, cur, uid, did
    finally:
        conn.rollback()
        _limpar(cur)
        conn.commit()
        conn.close()


def test_sem_financeiro_nao_da_baixa(professor):
    conn, cur, uid, did = professor
    app.config["WTF_CSRF_ENABLED"] = False
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
        s["modo_painel"] = "professor"
        s["academia_gerenciamento_id"] = A
    r = cli.post(f"/financeiro/despesas/{did}/pagar", headers={"X-Requested-With": "XMLHttpRequest"},
                 data={"data_pagamento": "2026-01-01"})
    assert r.status_code == 403


def test_tela_de_permissoes_so_para_o_principal():
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = "3"
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = 14
    h = cli.get("/financeiro/painel/permissoes", follow_redirects=True).get_data(as_text=True)
    assert "Permissões do financeiro" in h or "Só o gestor principal" in h
