# -*- coding: utf-8 -*-
"""Baixa de mensalidade com data de pagamento no futuro é recusada.

Usa uma mensalidade em aberto real só para leitura: a recusa acontece antes
de qualquer gravação, e a transação é desfeita de qualquer forma.

Uso:  .venv/bin/python -m pytest tests/test_baixa_data_futura.py -q
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from blueprints.financeiro import routes as fr  # noqa: E402
from config import get_db_connection  # noqa: E402


def test_partes_com_data_futura_recusadas():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT ma.id, m.id_academia FROM mensalidade_aluno ma
                       JOIN mensalidades m ON m.id = ma.mensalidade_id
                       WHERE ma.status IN ('pendente', 'atrasado') LIMIT 1""")
        mid, aid = cur.fetchone()
        amanha = (date.today() + timedelta(days=1)).isoformat()
        with app.test_request_context():
            ok, msg = fr._registrar_pagamento_mensalidade_partes(
                conn, cur, mid, aid, [{"forma_pagamento_id": None, "valor": 1, "data_pagamento": amanha}])
            assert not ok and "futuro" in msg
            assert fr._registrar_pagamento_e_receita(conn, cur, "mensalidade_aluno", mid, aid,
                                                     data_pagamento=amanha) is False
        cur.execute("SELECT status FROM mensalidade_aluno WHERE id = %s", (mid,))
        assert cur.fetchone()[0] in ("pendente", "atrasado")
    finally:
        conn.rollback()
        conn.close()
