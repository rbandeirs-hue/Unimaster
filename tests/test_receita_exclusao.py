# -*- coding: utf-8 -*-
"""Excluir receita: só da própria academia.

Antes havia um SELECT de reserva só pelo id, e qualquer receita manual de
qualquer academia podia ser apagada. Usa academias fictícias (-9907 alheia,
-9908 do usuário), criadas e apagadas aqui — nenhuma receita real é tocada.

Uso:  .venv/bin/python -m pytest tests/test_receita_exclusao.py -q
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from config import get_db_connection  # noqa: E402

ALHEIA, PROPRIA, USUARIO = -9907, -9908, 3


def _limpar(cur):
    cur.execute("DELETE FROM receitas WHERE id_academia IN (%s, %s)", (ALHEIA, PROPRIA))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id IN (%s, %s)", (ALHEIA, PROPRIA))
    cur.execute("DELETE FROM roles_usuario WHERE academia_id IN (%s, %s)", (ALHEIA, PROPRIA))
    cur.execute("DELETE FROM academias WHERE id IN (%s, %s)", (ALHEIA, PROPRIA))


@pytest.fixture
def receitas():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        _limpar(cur)
        cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Alheia'), (%s, 'ZZ Própria')", (ALHEIA, PROPRIA))
        cur.execute("INSERT INTO usuarios_academias (usuario_id, academia_id, gestor_principal) VALUES (%s, %s, 1)",
                    (USUARIO, PROPRIA))
        cur.execute("""INSERT INTO roles_usuario (usuario_id, role_id, academia_id)
                       SELECT %s, id, %s FROM roles WHERE chave = 'gestor_academia'""", (USUARIO, PROPRIA))
        ids = {}
        for nome, aid in (("alheia", ALHEIA), ("propria", PROPRIA)):
            cur.execute("""INSERT INTO receitas (descricao, valor, data, categoria, id_academia)
                           VALUES ('Teste exclusão', 10, %s, 'Teste', %s)""", (date.today(), aid))
            ids[nome] = cur.lastrowid
        conn.commit()
        yield conn, cur, ids
    finally:
        conn.rollback()
        _limpar(cur)
        conn.commit()
        conn.close()


def _existe(conn, cur, rid):
    conn.commit()
    cur.execute("SELECT COUNT(*) n FROM receitas WHERE id = %s", (rid,))
    return cur.fetchone()["n"] == 1


def test_nao_apaga_receita_de_outra_academia(receitas):
    conn, cur, ids = receitas
    app.config["WTF_CSRF_ENABLED"] = False
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO)
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = PROPRIA
    h = cli.post(f"/financeiro/receitas/excluir/{ids['alheia']}",
                 data={"academia_id": PROPRIA}, follow_redirects=True).get_data(as_text=True)
    assert "Receita não encontrada" in h
    assert _existe(conn, cur, ids["alheia"])

    cli.post(f"/financeiro/receitas/excluir/{ids['propria']}", data={"academia_id": PROPRIA})
    assert not _existe(conn, cur, ids["propria"])
