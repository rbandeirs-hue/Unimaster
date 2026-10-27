# -*- coding: utf-8 -*-
"""Check-in por QR Code (blueprints/presencas/checkin.py).

As regras rodam sem banco; o fluxo completo usa uma academia fictícia
(-9904) criada e apagada pelo próprio teste.

Uso:  .venv/bin/python -m pytest tests/test_checkin_qr.py -q
"""
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from blueprints.presencas import checkin as ck  # noqa: E402
from config import get_db_connection  # noqa: E402

FICTICIA = -9904
USUARIO = 3


def test_codigo_gira_e_expira():
    with app.app_context():
        agora = 1_000_000_000
        cod = ck.codigo_atual(17, agora)
        assert ck.codigo_valido(17, cod, agora)
        assert ck.codigo_valido(17, cod, agora + 2 * ck.JANELA_SEG)        # ainda dentro dos 3 min
        assert not ck.codigo_valido(17, cod, agora + 3 * ck.JANELA_SEG)    # expirou
        assert not ck.codigo_valido(18, cod, agora)                        # outra turma
        assert not ck.codigo_valido(17, cod[:-1] + ("0" if cod[-1] != "0" else "1"), agora)
        assert not ck.codigo_valido(17, "lixo", agora)


def test_horario_da_aula():
    turma = {"dias_semana": "2,4", "hora_inicio": timedelta(hours=19), "hora_fim": timedelta(hours=20)}
    terca = datetime(2026, 10, 27, 19, 10)          # terça
    assert ck.motivo_fora_de_hora(turma, terca) is None
    assert ck.motivo_fora_de_hora(turma, terca.replace(hour=18, minute=5)) is None   # 55 min antes
    assert "abre" in ck.motivo_fora_de_hora(turma, terca.replace(hour=17, minute=50))
    assert "terminou" in ck.motivo_fora_de_hora(turma, terca.replace(hour=20, minute=45))
    assert "Hoje não" in ck.motivo_fora_de_hora(turma, datetime(2026, 10, 28, 19, 10))  # quarta
    assert ck.motivo_fora_de_hora({"dias_semana": None, "hora_inicio": None}, terca) is None
    assert ck.horario_aula(turma) == "19:00:00"


def _limpar(cur):
    cur.execute("DELETE p FROM presencas p JOIN turmas t ON t.TurmaID = p.turma_id WHERE t.id_academia = %s", (FICTICIA,))
    cur.execute("DELETE at FROM aluno_turmas at JOIN turmas t ON t.TurmaID = at.TurmaID WHERE t.id_academia = %s", (FICTICIA,))
    cur.execute("DELETE FROM turmas WHERE id_academia = %s", (FICTICIA,))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (FICTICIA,))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (FICTICIA,))
    cur.execute("DELETE FROM roles_usuario WHERE academia_id = %s", (FICTICIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (FICTICIA,))


@pytest.fixture
def turma_ficticia():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        dados = _preparar(conn, cur)
    except Exception:
        # Sem isto a transação ficava aberta segurando as linhas, e o teste
        # seguinte esperava o lock até estourar.
        conn.rollback()
        _limpar(cur)
        conn.commit()
        conn.close()
        raise
    app.config["WTF_CSRF_ENABLED"] = False
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO)
        s["_fresh"] = True
        s["modo_painel"] = "aluno"
    try:
        yield (cli, conn, cur) + dados
    finally:
        conn.rollback()
        _limpar(cur)
        conn.commit()
        conn.close()


def _preparar(conn, cur):
    _limpar(cur)
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Check-in')", (FICTICIA,))
    cur.execute("INSERT INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)", (USUARIO, FICTICIA))
    # Professor só nesta academia: é quem abre a tela do QR.
    cur.execute("""INSERT INTO roles_usuario (usuario_id, role_id, academia_id)
                   SELECT %s, id, %s FROM roles WHERE chave = 'professor'""", (USUARIO, FICTICIA))
    # Sem dias nem horário: o check-in vale a qualquer hora (o teste não depende do relógio).
    cur.execute("""INSERT INTO turmas (Nome, DiasHorario, IdadeMin, IdadeMax, Professor, Classificacao,
                                       Capacidade, id_academia)
                   VALUES ('Turma QR', '', 0, 99, '', '', 30, %s)""", (FICTICIA,))
    turma = cur.lastrowid
    cur.execute("INSERT INTO alunos (nome, id_academia, usuario_id) VALUES ('Aluno QR', %s, %s)", (FICTICIA, USUARIO))
    aluno = cur.lastrowid
    cur.execute("INSERT INTO aluno_turmas (aluno_id, TurmaID) VALUES (%s, %s)", (aluno, turma))
    cur.execute("INSERT INTO alunos (nome, id_academia) VALUES ('Outro aluno', %s)", (FICTICIA,))
    outro = cur.lastrowid
    cur.execute("INSERT INTO aluno_turmas (aluno_id, TurmaID) VALUES (%s, %s)", (outro, turma))
    conn.commit()
    return turma, aluno, outro


def test_fluxo_completo(turma_ficticia):
    cli, conn, cur, turma, aluno, outro = turma_ficticia

    # A tela pede o código como chamada de dados, igual ao JavaScript dela.
    j = cli.get(f"/presencas/checkin/{turma}/codigo",
                headers={"X-Requested-With": "XMLHttpRequest"}).get_json()
    assert "<svg" in j["svg"] and f"/checkin/{turma}/" in j["url"]
    caminho = re.sub(r"^https?://[^/]+", "", j["url"])

    h = cli.get(caminho).get_data(as_text=True)
    assert "Confirmar presença" in h and "Aluno QR" in h and "Outro aluno" not in h
    lido_em = re.search(r'name="lido_em" value="(\d+)"', h).group(1)
    assin = re.search(r'name="assin" value="([0-9a-f]+)"', h).group(1)

    # Aluno de outra pessoa não entra, mesmo forçando o id no POST.
    h = cli.post(caminho, data={"lido_em": lido_em, "assin": assin,
                                "aluno_id": [aluno, outro]}).get_data(as_text=True)
    assert "Presença registrada" in h
    conn.commit()
    cur.execute("SELECT aluno_id, presente, responsavel_nome FROM presencas WHERE turma_id = %s AND data_presenca = %s",
                (turma, date.today()))
    linhas = cur.fetchall()
    assert [(r["aluno_id"], r["presente"]) for r in linhas] == [(aluno, 1)]
    assert linhas[0]["responsavel_nome"].startswith("Check-in QR")

    with cli.session_transaction() as sess:   # a tela é aberta pela equipe
        sess["modo_painel"] = "academia"
        sess["academia_gerenciamento_id"] = FICTICIA
    tela = cli.get(f"/presencas/checkin/{turma}/tela").get_data(as_text=True)
    assert "Aluno QR" in tela


def test_codigo_vencido_e_assinatura_falsa(turma_ficticia):
    cli, conn, cur, turma, aluno, outro = turma_ficticia
    with app.app_context():
        velho = ck.codigo_atual(turma, time.time() - 10 * ck.JANELA_SEG)
    h = cli.get(f"/checkin/{turma}/{velho}").get_data(as_text=True)
    assert "expirou" in h and "Confirmar presença" not in h
    h = cli.post(f"/checkin/{turma}/{velho}", data={"lido_em": int(time.time()), "assin": "0" * 12,
                                                    "aluno_id": aluno}).get_data(as_text=True)
    assert "O tempo para confirmar acabou" in h
    conn.commit()
    cur.execute("SELECT COUNT(*) n FROM presencas WHERE turma_id = %s", (turma,))
    assert cur.fetchone()["n"] == 0


def test_login_volta_para_o_checkin():
    cli = app.test_client()
    r = cli.get("/checkin/1/123-abc")
    assert r.status_code == 302 and "next=" in r.headers["Location"]


def test_filho_ligado_so_pelo_cpf_do_responsavel():
    """Responsável cujo vínculo com o filho é só o CPF no cadastro (com pontuação)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT cpf FROM usuarios WHERE id = %s", (USUARIO,))
        cpf = cur.fetchone()["cpf"]
        formatado = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
        cur.execute("""INSERT INTO turmas (Nome, DiasHorario, IdadeMin, IdadeMax, Professor, Classificacao,
                                           Capacidade, id_academia) VALUES ('T', '', 0, 99, '', '', 30, %s)""",
                    (FICTICIA,))
        turma = cur.lastrowid
        cur.execute("""INSERT INTO alunos (nome, id_academia, responsavel_financeiro_cpf)
                       VALUES ('Filho pelo CPF', %s, %s)""", (FICTICIA, formatado))
        filho = cur.lastrowid
        cur.execute("INSERT INTO aluno_turmas (aluno_id, TurmaID) VALUES (%s, %s)", (filho, turma))
        assert filho in [a["id"] for a in ck.alunos_do_usuario_na_turma(cur, USUARIO, turma)]
        assert ck.alunos_do_usuario_na_turma(cur, 999999, turma) == []
    finally:
        conn.rollback()
        conn.close()
