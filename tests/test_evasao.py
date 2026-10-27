# -*- coding: utf-8 -*-
"""Alerta de evasão (utils/evasao.py). Roda numa transação que sempre volta.

Uso:  .venv/bin/python -m pytest tests/test_evasao.py -q
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection  # noqa: E402
from utils import evasao as ev  # noqa: E402

A = -9905


def test_classifica_quem_sumiu_e_quem_caiu():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Evasão')", (A,))
        cur.execute("""INSERT INTO turmas (Nome, DiasHorario, IdadeMin, IdadeMax, Professor, Classificacao,
                                           Capacidade, id_academia) VALUES ('T', '', 0, 99, '', '', 30, %s)""", (A,))
        turma = cur.lastrowid
        hoje = date.today()

        def aluno(nome, dias_atras, tel="81999990000"):
            cur.execute("INSERT INTO alunos (nome, id_academia, tel_celular) VALUES (%s, %s, %s)", (nome, A, tel))
            aid = cur.lastrowid
            for d in dias_atras:
                cur.execute("""INSERT INTO presencas (aluno_id, turma_id, data_presenca, horario_aula, presente)
                               VALUES (%s, %s, %s, '00:00:00', 1)""", (aid, turma, hoje - timedelta(days=d)))
            return aid

        sumiu = aluno("Sumiu", [40, 45, 50, 55])                       # vinha, parou
        caiu = aluno("Caiu", [5] + list(range(32, 90, 4)))             # ~15 no período base, 1 agora
        firme = aluno("Firme", list(range(2, 30, 4)) + list(range(32, 90, 4)))
        novo = aluno("Novo", [3, 10])                                  # sem histórico: não é alerta
        uma_vez = aluno("Uma vez", [60])                               # base pequena demais

        r = {x["id"]: x for x in ev.alunos_em_risco(cur, A, hoje)}
        assert r[sumiu]["nivel"] == "sumiu" and r[sumiu]["dias_sem_vir"] == 40
        assert r[caiu]["nivel"] == "caindo"
        assert firme not in r and novo not in r and uma_vez not in r
        assert r[sumiu]["whatsapp"] == "5581999990000"
        assert list(r)[0] == sumiu                                     # quem sumiu vem primeiro
        assert ev.resumo(cur, A) == {"total": 2, "sumiu": 1, "caindo": 1}
    finally:
        conn.rollback()
        conn.close()
