# -*- coding: utf-8 -*-
"""Teste de fumaça do shell: toda tela abre, em todo modo de acesso.

Por que existe
--------------
A migração leva ~180 telas de um layout para o outro. Revisar uma a uma no
navegador não é viável, e o tipo de erro que a migração produz (variável que
o context processor não injeta mais, endpoint que sumiu da lateral, bloco
renomeado) aparece como 500 na hora de renderizar — exatamente o que um GET
detecta.

Só faz GET, e ainda assim pula endpoints que produzem efeito (enviar, gerar,
sincronizar, excluir...). O banco é o de verdade: nada aqui pode escrever.

Uso:  .venv/bin/python -m pytest tests/test_shell_smoke.py -q
      .venv/bin/python tests/test_shell_smoke.py          (relatório detalhado)
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Um usuário por modo. O 3 acumula quase todos os papéis; federação e
# visitante têm titulares próprios.
USUARIO_POR_MODO = {
    "admin": 3,
    "academia": 3,
    "associacao": 3,
    "federacao": 9,
    "professor": 3,
    "aluno": 3,
    "responsavel": 3,
    "visitante": 271,
}

# O único gestor de federação da base não tem CPF cadastrado, e o sistema
# desvia quem está nessa situação para /auth/cadastrar-cpf antes de qualquer
# tela. Logo, o modo federação não chega a ser exercido pelas rotas: a
# lateral dele é conferida por `test_menu_de_todo_modo_tem_itens`.
MODOS_SEM_USUARIO_COMPLETO = {"federacao"}

# Nada que mude estado. O casamento é sobre o nome do endpoint.
PROIBIDO = re.compile(
    r"(dispatch|enviar|notificar|push|sincroniz|migra|executar|excluir|deletar|"
    r"remover|apagar|gerar|criar|cadastrar|salvar|atualizar|editar|aplicar|"
    r"baixa|pagar|cancelar|aprovar|rejeitar|promover|vincular|consolidar|"
    r"logout|toggle|import|export|backup|reset|limpar|marcar)"
)


def _rotas_visitaveis(app):
    for r in app.url_map.iter_rules():
        if "GET" not in (r.methods or ()):
            continue
        if r.arguments:                      # exige parâmetro: fora do escopo
            continue
        if r.endpoint.startswith("static"):
            continue
        if PROIBIDO.search(r.endpoint.lower()):
            continue
        yield r.endpoint, str(r.rule)


# Sem uma academia escolhida, o modo academia redireciona tudo para a tela de
# escolha e o teste passaria sem visitar nada.
ACADEMIA_TESTE = 1


def _cliente(app, modo):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(USUARIO_POR_MODO[modo])
        sess["_fresh"] = True
        sess["modo_painel"] = modo
        if modo in ("academia", "professor"):
            sess["academia_gerenciamento_id"] = ACADEMIA_TESTE
    return c


def coletar_falhas():
    from app import app
    app.config["WTF_CSRF_ENABLED"] = False
    falhas = []
    visitadas = 0
    for modo in USUARIO_POR_MODO:
        c = _cliente(app, modo)
        for endpoint, rule in _rotas_visitaveis(app):
            visitadas += 1
            try:
                resp = c.get(rule, follow_redirects=False)
            except Exception as e:                       # erro fora do Flask
                falhas.append((modo, endpoint, "EXC", "%s: %s" % (type(e).__name__, e)))
                continue
            if resp.status_code >= 500:
                corpo = resp.get_data(as_text=True)
                falhas.append((modo, endpoint, resp.status_code, corpo[-400:]))
    return visitadas, falhas


def test_nenhuma_tela_devolve_500():
    visitadas, falhas = coletar_falhas()
    assert visitadas > 0, "nenhuma rota visitada — o mapa de rotas está vazio?"
    resumo = "\n".join("  [%s] %s -> %s" % (m, e, s) for m, e, s, _ in falhas)
    assert not falhas, "%d tela(s) com erro 500:\n%s" % (len(falhas), resumo)


def test_menu_de_todo_modo_tem_itens():
    """Todo modo tem lateral navegável — inclusive os que as rotas não alcançam.

    Sem isto, um modo cujo usuário de teste não consegue entrar (federação)
    passaria despercebido com a lateral vazia.
    """
    from app import app
    from utils.menu import menu_do_modo

    with app.test_request_context("/"):
        for modo in USUARIO_POR_MODO:
            grupos = menu_do_modo(modo, {"academia_id": ACADEMIA_TESTE})
            itens = [i for _, itens in grupos for i in itens]
            assert itens, "menu vazio no modo %s" % modo
            assert all(i.href for i in itens), "item sem rota no modo %s" % modo


if __name__ == "__main__":
    visitadas, falhas = coletar_falhas()
    print("visitas: %d   falhas: %d" % (visitadas, len(falhas)))
    for modo, endpoint, status, corpo in falhas:
        print("\n=== [%s] %s -> %s" % (modo, endpoint, status))
        print(corpo.strip()[-400:])
    sys.exit(1 if falhas else 0)
