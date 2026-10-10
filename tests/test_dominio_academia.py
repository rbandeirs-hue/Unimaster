# -*- coding: utf-8 -*-
"""Domínio próprio e marca da academia (MM-15).

O banco é o de verdade e nada aqui escreve: o host da academia é simulado
trocando `academia_do_host`, para valer antes de a MM-15 ser aplicada.

Uso:  .venv/bin/python -m pytest tests/test_dominio_academia.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import dominio_academia as dom  # noqa: E402

HOST = "judoteste.com.br"
MARCA = {"id": 1, "nome": "Academia Teste", "titulo": "Judô Teste Clube",
         "texto": "Frase da academia teste", "cor": "#123abc"}


@pytest.mark.parametrize("entrada,saida", [
    ("JudoClube.com.br", "judoclube.com.br"),
    ("https://www.judoclube.com.br/login?x=1", "judoclube.com.br"),
    ("judoclube.com.br:443", "judoclube.com.br"),
    ("academiajudô.com.br", "xn--academiajud-dfb.com.br"),
    ("", None),
    ("   ", None),
])
def test_normalizar(entrada, saida):
    assert dom.normalizar(entrada) == saida


@pytest.mark.parametrize("entrada", [
    "judoclube", "judo clube.com", "-judo.com.br", "1.2.3.4", "rmservicosnet.com.br",
    "academia.rmservicosnet.com.br", "a" * 64 + ".com",
])
def test_normalizar_recusa(entrada):
    with pytest.raises(dom.DominioInvalido):
        dom.normalizar(entrada)


def test_cor_valida():
    assert dom.cor_valida("#AABBCC") == "#aabbcc"
    assert dom.cor_valida("red") is None
    assert dom.cor_valida("#abc") is None


def test_host_do_sistema_nao_e_academia():
    assert dom.academia_do_host("rmservicosnet.com.br") is None
    assert dom.academia_do_host("www.rmservicosnet.com.br:443") is None


def test_dominios_do_servidor_inclui_outros_sites():
    hosts = dom.dominios_do_servidor()
    assert "rmservicosnet.com.br" in hosts
    if os.path.exists("/etc/nginx/sites-enabled/pesvidas"):
        assert "pesvidas.com.br" in hosts


def test_vinculo_real_com_a_academia():
    # Usuário 3 é da academia 1 na base (o mesmo do teste de fumaça).
    assert dom.usuario_e_da_academia(3, 1)
    assert not dom.usuario_e_da_academia(3, 999999)


@pytest.fixture
def app(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    monkeypatch.setattr(dom, "academia_do_host",
                        lambda host: dict(MARCA) if dom.host_da_requisicao(host) == HOST else None)
    return flask_app


def test_login_pelo_dominio_mostra_a_marca(app):
    html = app.test_client().get("/auth/login", base_url=f"https://{HOST}").get_data(as_text=True)
    assert "Judô Teste Clube" in html
    assert "Frase da academia teste" in html
    assert "--auth-red: #123abc" in html
    assert ">Unimaster<" not in html


def test_login_no_endereco_principal_continua_unimaster(app):
    html = app.test_client().get("/auth/login", base_url="https://rmservicosnet.com.br").get_data(as_text=True)
    assert "Unimaster" in html
    assert "Judô Teste Clube" not in html


def _logado(app, usuario_id=3):
    c = app.test_client()
    with c.session_transaction(base_url=f"https://{HOST}") as s:
        s["_user_id"] = str(usuario_id)
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = MARCA["id"]
    return c


def test_quem_nao_e_da_academia_e_desconectado(app, monkeypatch):
    monkeypatch.setattr(dom, "pode_entrar", lambda u, aid: False)
    c = _logado(app)
    r = c.get("/painel/", base_url=f"https://{HOST}")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    with c.session_transaction(base_url=f"https://{HOST}") as s:
        assert "_user_id" not in s


def test_quem_e_da_academia_ve_a_marca_no_shell(app, monkeypatch):
    monkeypatch.setattr(dom, "pode_entrar", lambda u, aid: True)
    c = _logado(app)
    r = c.get("/academia/configuracoes", base_url=f"https://{HOST}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "--sh-red: #123abc" in html
    assert "Judô Teste Clube" in html


def test_link_curto_usa_dominio_da_academia_no_ar(monkeypatch):
    from utils import links_curtos as lc
    monkeypatch.setattr(dom, "dominio_ativo", lambda aid: HOST if aid == 1 else None)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://rmservicosnet.com.br")
    assert lc.base_url(1) == f"https://{HOST}"
    assert lc.base_url(2) == "https://rmservicosnet.com.br"
    assert lc.base_url() == "https://rmservicosnet.com.br"


def test_dominio_ativo_sem_dominio_cadastrado():
    dom.esquecer_cache()
    assert dom.dominio_ativo(None) is None
    assert dom.dominio_ativo(999999) is None
