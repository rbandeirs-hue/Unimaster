# -*- coding: utf-8 -*-
"""Recibo de pagamento em PDF (utils/recibo.py, financeiro.recibo_pdf). Só GET.

Uso:  .venv/bin/python -m pytest tests/test_recibo.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from config import get_db_connection  # noqa: E402
from utils.recibo import por_extenso  # noqa: E402


@pytest.mark.parametrize("valor,texto", [
    ("1", "um real"), ("35", "trinta e cinco reais"), ("100", "cem reais"),
    ("120.50", "cento e vinte reais e cinquenta centavos"), ("1100", "mil e cem reais"),
    ("1234.56", "mil duzentos e trinta e quatro reais e cinquenta e seis centavos"),
    ("0.99", "noventa e nove centavos"),
])
def test_por_extenso(valor, texto):
    assert por_extenso(valor) == texto


def _uma(sql, args=()):
    c = get_db_connection()
    cur = c.cursor(dictionary=True)
    cur.execute(sql, args)
    r = cur.fetchone()
    c.close()
    return r


def _cliente(usuario, academia, modo="academia"):
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(usuario)
        s["_fresh"] = True
        s["modo_painel"] = modo
        s["academia_gerenciamento_id"] = academia
    return cli


PAGA = """SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id
          WHERE m.id_academia = %s AND ma.status = 'pago' AND ma.valor_pago > 0 ORDER BY ma.id DESC LIMIT 1"""


def test_gestor_abre_recibo_da_propria_academia_e_nao_de_outra():
    cli = _cliente(3, 14)
    r = cli.get(f"/financeiro/recibo/mensalidade/{_uma(PAGA, (14,))['id']}.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data[:4] == b"%PDF"
    assert cli.get(f"/financeiro/recibo/mensalidade/{_uma(PAGA, (2,))['id']}.pdf").status_code == 404


def test_cobranca_nao_paga_nao_tem_recibo():
    aberta = _uma("""SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id
                     WHERE m.id_academia = 14 AND ma.status <> 'pago' LIMIT 1""")
    assert _cliente(3, 14).get(f"/financeiro/recibo/mensalidade/{aberta['id']}.pdf").status_code == 404


def test_aluno_abre_o_proprio_recibo():
    r = _uma("""SELECT ma.id, a.usuario_id, a.id_academia FROM mensalidade_aluno ma
                JOIN alunos a ON a.id = ma.aluno_id
                WHERE ma.status = 'pago' AND ma.valor_pago > 0 AND a.usuario_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM roles_usuario ru JOIN roles ro ON ro.id = ru.role_id
                                  WHERE ru.usuario_id = a.usuario_id
                                    AND ro.chave IN ('admin', 'gestor_academia', 'professor', 'gestor_associacao'))
                LIMIT 1""")
    if not r:
        pytest.skip("nenhum aluno-usuário com mensalidade paga")
    cli = _cliente(r["usuario_id"], r["id_academia"], modo="aluno")
    assert cli.get(f"/financeiro/recibo/mensalidade/{r['id']}.pdf").status_code == 200
    outra = _uma("""SELECT ma.id FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                    WHERE ma.status = 'pago' AND ma.valor_pago > 0
                      AND COALESCE(a.usuario_id, 0) <> %s AND a.responsavel_financeiro_cpf IS NULL
                      AND a.id NOT IN (SELECT aluno_id FROM responsavel_alunos WHERE usuario_id = %s)
                    LIMIT 1""", (r["usuario_id"], r["usuario_id"]))
    assert cli.get(f"/financeiro/recibo/mensalidade/{outra['id']}.pdf").status_code == 404
