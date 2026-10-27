# -*- coding: utf-8 -*-
"""Conferência gateway × sistema (utils/conferencia_gateway.py).

Uso:  .venv/bin/python -m pytest tests/test_conferencia_gateway.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from config import get_db_connection  # noqa: E402
from utils import conferencia_gateway as cg  # noqa: E402


def test_aviso_de_pagamento_nao_baixado_aparece_e_some_quando_resolvido():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ev = None
    try:
        cur.execute("""SELECT ma.id, m.id_academia FROM mensalidade_aluno ma
                       JOIN mensalidades m ON m.id = ma.mensalidade_id
                       WHERE ma.status IN ('pendente', 'atrasado') LIMIT 1""")
        r = cur.fetchone()
        ev = cg.registrar("Teste", "mensalidade", r["id"], 10, resultado="erro", detalhe="teste")
        conn.commit()
        lista = cg.pendencias(cur, r["id_academia"])["aviso_sem_baixa"]
        assert ev in [e["id"] for e in lista]
        cg.resultado(ev, "baixado")
        conn.commit()
        assert ev not in [e["id"] for e in cg.pendencias(cur, r["id_academia"])["aviso_sem_baixa"]]
    finally:
        if ev:
            cur.execute("DELETE FROM gateway_eventos WHERE id = %s", (ev,))
            conn.commit()
        conn.close()


def test_tela_abre():
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = "3"
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = 14
    r = cli.get("/financeiro/painel/conferencia")
    assert r.status_code == 200 and "Conferência" in r.get_data(as_text=True)
