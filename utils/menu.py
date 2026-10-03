# -*- coding: utf-8 -*-
"""Menu da barra lateral, por modo de acesso.

Por que em Python e não no template
-----------------------------------
O menu vivia como literal Jinja dentro do `base_academia.html`, com os ~20
itens do modo academia e `url_for(..., academia_id=academia_id)` repetido em
cada um. Para atender os oito modos seria o mesmo bloco oito vezes dentro do
layout — impossível de manter e impossível de testar.

Aqui cada modo é uma função que devolve a mesma estrutura:

    [ (rótulo_do_grupo, [Item, Item, ...]), ... ]

Regras que valem para todos os modos:

* item com `href=None` é **omitido** — é assim que a permissão esconde o item,
  sem `{% if %}` no template;
* grupo que ficou sem item visível também some;
* `chave` é o que o template compara com `menu_ativo` para marcar o item atual.
  As chaves são as mesmas usadas pelo mapa `MENU_POR_BLUEPRINT` em app.py.

Nada aqui consulta banco: o escopo (academia_id, federacao_id...) chega pronto
no `ctx`, resolvido pelo context processor.
"""

from collections import namedtuple

from flask import url_for
from flask_login import current_user

Item = namedtuple("Item", "chave icone rotulo href")


def _rota(endpoint, **kwargs):
    """`url_for` que devolve None em vez de estourar.

    A lateral é montada em toda página; um endpoint que sumiu ou um parâmetro
    faltando derrubaria todas as telas de uma vez. Devolvendo None, o item
    apenas não aparece — o sistema segue navegável.
    """
    try:
        return url_for(endpoint, **{k: v for k, v in kwargs.items() if v is not None})
    except Exception:
        return None


def _tem(*papeis):
    for p in papeis:
        try:
            if current_user.has_role(p):
                return True
        except Exception:
            return False
    return False


# ---------------------------------------------------------------- academia
def _menu_academia(ctx):
    # Modalidades da academia: definem o que faz sentido oferecer no menu.
    # Sem a informação, `_tem_judo` fica True e nada é escondido.
    _mods = ctx.get("academia_modalidades") or []
    _tem_judo = ctx.get("academia_tem_judo")
    if _tem_judo is None:
        _tem_judo = (not _mods) or any("jud" in (m.get("nome") or "").lower() for m in _mods)
    aid = ctx.get("academia_id")
    # Duas condições diferentes: o PAPEL do usuário permite ver financeiro, e a
    # ACADEMIA usa o módulo. Academia que só faz o acadêmico não mostra a seção
    # nem para o admin.
    try:
        from utils.modulos import tem_financeiro
        academia_usa_financeiro = tem_financeiro(aid)
    except Exception:
        academia_usa_financeiro = True
    pode_financeiro = academia_usa_financeiro and _tem(
        "gestor_academia", "admin", "professor", "gestor_federacao", "gestor_associacao")
    return [
        ("", [
            Item("gerenciamento", "bi-grid-1x2", "Gerenciamento",
                 _rota("academia.painel_academia", academia_id=aid)),
            Item("indicadores", "bi-speedometer2", "Painel / Indicadores",
                 _rota("academia.dash", academia_id=aid)),
        ]),
        ("Dia a dia", [
            Item("presencas", "bi-clipboard-check", "Presença",
                 _rota("presencas.painel_presenca", academia_id=aid)),
            Item("turmas", "bi-collection", "Turmas",
                 _rota("turmas.lista_turmas", academia_id=aid)),
            Item("aulas_particulares", "bi-person-workspace", "Aulas particulares",
                 _rota("aula_particular.lista", academia_id=aid)),
            Item("ranking", "bi-trophy", "Ranking de frequência",
                 _rota("presencas.ranking_frequencia_pagina")),
            Item("solicitacoes", "bi-inbox", "Aprovar Solicitações",
                 _rota("solicitacoes.lista", academia_id=aid)),
        ]),
        ("Pessoas", [
            Item("alunos", "bi-people", "Alunos",
                 _rota("alunos.lista_alunos", academia_id=aid)),
            Item("professores", "bi-person-badge", "Professores",
                 _rota("professores.lista", academia_id=aid) if aid else None),
            Item("visitantes", "bi-door-open", "Visitantes",
                 _rota("academia.lista_visitantes", academia_id=aid)),
            Item("aniversariantes", "bi-balloon", "Aniversariantes",
                 _rota("aniversariante_live.pagina")),
            Item("precadastro", "bi-person-plus", "Pré-cadastro",
                 _rota("precadastro.lista", academia_id=aid)),
            Item("usuarios", "bi-person-gear", "Usuários",
                 _rota("academia.lista_usuarios", academia_id=aid)),
        ]),
        ("Financeiro", [
            Item("financeiro", "bi-cash-coin", "Financeiro",
                 _rota("financeiro.dashboard", academia_id=aid) if pode_financeiro else None),
        ] if academia_usa_financeiro else []),
        # Relatórios ficam fora de Financeiro de propósito: o catálogo cruza
        # alunos, frequência, graduação e cadastro, não só dinheiro.
        ("Relatórios", [
            Item("relatorios", "bi-file-earmark-bar-graph", "Relatórios",
                 _rota("relatorios.hub", academia_id=aid)),
        ]),
        ("Eventos", [
            Item("eventos", "bi-calendar-event", "Eventos",
                 _rota("eventos_competicoes.lista_eventos", academia_id=aid)),
            Item("competicoes", "bi-trophy-fill", "Competições",
                 _rota("eventos_competicoes.lista_competicoes", academia_id=aid)),
            # Programa, preços, aptos e banca do exame de faixa (kyu do judô).
            Item("exame_faixa", "bi-award", "Exame de faixa",
                 _rota("exame_faixa.alunos", academia_id=aid) if _tem_judo else None),
            Item("calendario", "bi-calendar3", "Calendário",
                 _rota("calendario.index")),
        ]),
        ("Estoque", [
            # O módulo é opcional por academia: sem ele ligado, a seção some.
            # `tem_estoque` é resolvido no context processor, junto do resto do
            # escopo, para o menu não consultar banco.
            Item("estoque", "bi-box-seam", "Estoque",
                 _rota("estoque.painel") if ctx.get("tem_estoque") else None),
        ]),
        ("Academia", [
            # Locais de treino e Modalidades acompanham o Zempo: são telas da
            # operação do judô. Academia de jiu-jitsu não as vê.
            Item("locais", "bi-geo-alt", "Locais de treino",
                 _rota("academia.locais_treino", academia_id=aid)
                 if _tem_judo else None),
            Item("modalidades", "bi-diagram-3", "Modalidades",
                 _rota("configuracoes.modalidades_lista", academia_id=aid)
                 if _tem_judo else None),
            Item("whatsapp", "bi-whatsapp", "WhatsApp",
                 _rota("academia.whatsapp_config", academia_id=aid)),
            # Zempo é o registro nacional do JUDÔ (CBJ). Academia que não dá
            # judô não tem o que fazer com ele.
            Item("zempo", "bi-person-vcard", "Cadastro no Zempo",
                 _rota("zempo.solicitar", academia_id=aid) if _tem_judo else None),
            Item("configuracoes", "bi-gear", "Configurações",
                 _rota("academia.configuracoes_academia", academia_id=aid)),
        ]),
    ]


# ------------------------------------------------------------------- admin
def _menu_admin(ctx):
    return [
        ("", [
            Item("gerenciamento", "bi-grid-1x2", "Gerenciamento",
                 _rota("painel.gerenciamento_admin")),
        ]),
        ("Estrutura", [
            Item("federacoes", "bi-flag", "Federações", _rota("federacao.lista_federacoes")),
            Item("associacoes", "bi-diagram-3", "Associações", _rota("federacao.lista_associacoes")),
            Item("academias", "bi-house-door", "Academias", _rota("associacao.lista_academias")),
            # Atalho direto: a academia independente não pertence a associação
            # nenhuma, então procurá-la dentro de "Associações" é o caminho
            # errado. Quem administra o sistema cadastra a partir daqui.
            Item("academia_nova", "bi-plus-circle", "Nova academia",
                 _rota("associacao.cadastro_academia")),
        ]),
        ("Pessoas", [
            Item("alunos", "bi-people", "Alunos", _rota("alunos.lista_alunos")),
            Item("usuarios", "bi-person-gear", "Usuários", _rota("usuarios.lista_usuarios")),
            Item("duplicados", "bi-person-exclamation", "Cadastros duplicados",
                 _rota("usuarios.duplicados")),
        ]),
        ("Eventos", [
            Item("eventos", "bi-calendar-event", "Eventos",
                 _rota("eventos_competicoes.lista_eventos")),
            Item("competicoes", "bi-trophy-fill", "Competições",
                 _rota("eventos_competicoes.lista_competicoes")),
            Item("exame_faixa", "bi-award", "Exame de faixa", _rota("exame_faixa.exames")),
            Item("calendario", "bi-calendar3", "Calendário", _rota("calendario.index")),
        ]),
        ("Sistema", [
            Item("cadastros", "bi-card-list", "Cadastros básicos", _rota("cadastros.hub")),
            Item("graduacoes", "bi-award", "Graduações", _rota("cadastros.gerenciar_graduacoes")),
            Item("categorias", "bi-tags", "Categorias", _rota("cadastros.gerenciar_categorias")),
            Item("modalidades", "bi-diagram-3", "Modalidades",
                 _rota("configuracoes.modalidades_lista")),
            # Liga/desliga de cada item da lateral por modalidade: é aqui que
            # "isto é do judô" deixa de ser uma decisão de código.
            Item("menu_modalidade", "bi-toggles", "Menu por modalidade",
                 _rota("configuracoes.menu_modalidade")),
            Item("modulo_estoque", "bi-box-seam", "Módulo de estoque",
                 _rota("configuracoes.modulo_estoque")),
            Item("formularios", "bi-ui-checks", "Formulários", _rota("formularios.lista")),
            # Catálogo vivo dos componentes: quem for criar tela nova vê aqui
            # o que já existe, em vez de inventar o quarto botão.
            Item("design", "bi-palette", "Design System", _rota("cadastros.design_system")),
            Item("zempo", "bi-person-vcard", "Zempo", _rota("zempo.migracoes")),
            Item("configuracoes", "bi-gear", "Configurações", _rota("configuracoes.hub")),
        ]),
    ]


# ---------------------------------------------------------------- federação
def _menu_federacao(ctx):
    return [
        ("", [
            Item("gerenciamento", "bi-grid-1x2", "Gerenciamento",
                 _rota("federacao.gerenciamento_federacao")),
            Item("indicadores", "bi-speedometer2", "Painel", _rota("federacao.painel_federacao")),
        ]),
        ("Estrutura", [
            Item("associacoes", "bi-diagram-3", "Associações", _rota("federacao.lista_associacoes")),
            Item("alunos", "bi-people", "Alunos", _rota("alunos.lista_alunos")),
        ]),
        ("Eventos", [
            Item("eventos", "bi-calendar-event", "Eventos",
                 _rota("eventos_competicoes.lista_eventos")),
            Item("competicoes", "bi-trophy-fill", "Competições",
                 _rota("eventos_competicoes.lista_competicoes")),
            Item("calendario", "bi-calendar3", "Calendário", _rota("calendario.index")),
        ]),
        ("Federação", [
            Item("formularios", "bi-ui-checks", "Formulários", _rota("formularios.lista")),
            Item("configuracoes", "bi-gear", "Configurações",
                 _rota("federacao.configuracoes_federacao")),
        ]),
    ]


# --------------------------------------------------------------- associação
def _menu_associacao(ctx):
    return [
        ("", [
            Item("gerenciamento", "bi-grid-1x2", "Gerenciamento",
                 _rota("associacao.gerenciamento_associacao")),
            Item("indicadores", "bi-speedometer2", "Painel",
                 _rota("associacao.painel_associacao")),
        ]),
        ("Estrutura", [
            Item("academias", "bi-house-door", "Academias", _rota("associacao.lista_academias")),
            Item("professores", "bi-person-badge", "Professores",
                 _rota("associacao.lista_professores")),
        ]),
        ("Pessoas", [
            Item("alunos", "bi-people", "Alunos", _rota("alunos.lista_alunos")),
            Item("precadastro", "bi-person-plus", "Pré-cadastro", _rota("associacao.precadastro")),
            Item("usuarios", "bi-person-gear", "Usuários", _rota("academia.lista_usuarios")),
        ]),
        ("Eventos", [
            Item("eventos", "bi-calendar-event", "Eventos",
                 _rota("eventos_competicoes.lista_eventos")),
            Item("competicoes", "bi-trophy-fill", "Competições",
                 _rota("eventos_competicoes.lista_competicoes")),
            Item("exame_faixa", "bi-award", "Exame de faixa", _rota("exame_faixa.exames")),
            Item("calendario", "bi-calendar3", "Calendário", _rota("calendario.index")),
        ]),
        ("Estoque", [
            Item("estoque", "bi-box-seam", "Estoque",
                 _rota("estoque.painel") if ctx.get("tem_estoque") else None),
        ]),
        ("Associação", [
            Item("categorias", "bi-tags", "Categorias", _rota("associacao.gerenciar_categorias")),
            Item("financeiro", "bi-cash-coin", "Formas de pagamento",
                 _rota("financeiro.formas_pagamento")),
            Item("formularios", "bi-ui-checks", "Formulários", _rota("formularios.lista")),
            Item("zempo", "bi-person-vcard", "Zempo", _rota("zempo.migracoes")),
            Item("configuracoes", "bi-gear", "Configurações",
                 _rota("associacao.configuracoes_associacao")),
        ]),
    ]


# ---------------------------------------------------------------- professor
def _menu_professor(ctx):
    aid = ctx.get("academia_id")
    return [
        ("", [
            Item("gerenciamento", "bi-grid-1x2", "Meu painel",
                 _rota("professor.painel_professor")),
        ]),
        ("Dia a dia", [
            Item("presencas", "bi-clipboard-check", "Registrar presença",
                 _rota("presencas.registro_presenca")),
            Item("historico", "bi-clock-history", "Histórico de presença",
                 _rota("presencas.historico_presenca_lista")),
            Item("ata", "bi-file-text", "Ata de presença", _rota("presencas.ata_presenca")),
            Item("turmas", "bi-collection", "Minhas turmas", _rota("professor.minha_turma")),
            Item("aulas_particulares", "bi-person-workspace", "Aulas particulares",
                 _rota("aula_particular.lista")),
            Item("ranking", "bi-trophy", "Ranking de frequência",
                 _rota("presencas.ranking_frequencia_pagina")),
        ]),
        ("Pessoas", [
            Item("alunos", "bi-people", "Alunos", _rota("alunos.lista_alunos", academia_id=aid)),
        ]),
        ("Eventos", [
            Item("eventos", "bi-calendar-event", "Eventos",
                 _rota("eventos_competicoes.lista_eventos", academia_id=aid)),
            Item("exame_faixa", "bi-award", "Exame de faixa",
                 _rota("exame_faixa.alunos", academia_id=aid)),
            Item("calendario", "bi-calendar3", "Calendário", _rota("calendario.index")),
        ]),
    ]


# -------------------------------------------------------------------- aluno
def _menu_aluno(ctx):
    return [
        ("", [
            Item("gerenciamento", "bi-person-circle", "Meu perfil",
                 _rota("painel_aluno.meu_perfil")),
        ]),
        ("Meu treino", [
            Item("turmas", "bi-collection", "Minha turma", _rota("painel_aluno.minha_turma")),
            Item("presencas", "bi-clipboard-check", "Minhas presenças",
                 _rota("painel_aluno.minhas_presencas")),
            Item("ranking", "bi-trophy", "Ranking de frequência",
                 _rota("presencas.ranking_frequencia_pagina")),
            # Currículo de atleta e simuladores são do judô: o currículo sai do
            # registro da federação e a categoria vem da tabela de pesos da CBJ.
            # Aluno só de jiu-jitsu não tem o que fazer com eles.
            Item("curriculo", "bi-award", "Meu currículo",
                 _rota("painel_aluno.curriculo") if ctx.get("pratica_judo", True) else None),
            # Material do próximo exame e das faixas anteriores, e o histórico
            # de exames com as notas.
            Item("exame_estudo", "bi-journal-text", "Exame de faixa — estudo",
                 _rota("exame_faixa.estudo") if ctx.get("pratica_judo", True) else None),
        ]),
        ("Financeiro", [
            Item("financeiro", "bi-cash-coin", "Minhas mensalidades",
                 _rota("painel_aluno.minhas_mensalidades")),
        ]),
        ("Loja", [
            Item("loja", "bi-shop", "Loja da academia", _rota("estoque.loja")),
        ]),
        ("Eventos", [
            Item("eventos", "bi-calendar-event", "Eventos disponíveis",
                 _rota("eventos_competicoes.disponiveis")),
            Item("calendario", "bi-calendar3", "Calendário", _rota("calendario.aluno")),
        ]),
        ("Simuladores", [
            Item("sim_graduacao", "bi-graph-up", "Graduação prevista",
                 _rota("painel_aluno.simular_graduacao_prevista")
                 if ctx.get("pratica_judo", True) else None),
            Item("sim_categoria", "bi-tags", "Categoria de competição",
                 _rota("painel_aluno.simular_categorias")
                 if ctx.get("pratica_judo", True) else None),
            Item("associacao", "bi-diagram-3", "Treinar em outra academia",
                 _rota("painel_aluno.associacao")),
        ]),
    ]


# -------------------------------------------------------------- responsável
def _menu_responsavel(ctx):
    return [
        ("", [
            Item("gerenciamento", "bi-person-circle", "Meu painel",
                 _rota("painel_responsavel.meu_perfil")),
        ]),
        ("Acompanhamento", [
            Item("turmas", "bi-collection", "Turma", _rota("painel_responsavel.minha_turma")),
            Item("presencas", "bi-clipboard-check", "Presenças",
                 _rota("painel_responsavel.minhas_presencas")),
            Item("curriculo", "bi-award", "Currículo",
                 _rota("painel_responsavel.curriculo") if ctx.get("pratica_judo", True) else None),
            Item("exame_estudo", "bi-journal-text", "Exame de faixa — estudo",
                 _rota("exame_faixa.estudo") if ctx.get("pratica_judo", True) else None),
        ]),
        ("Financeiro", [
            Item("financeiro", "bi-cash-coin", "Mensalidades",
                 _rota("painel_responsavel.minhas_mensalidades")),
        ]),
        ("Loja", [
            Item("loja", "bi-shop", "Loja da academia", _rota("estoque.loja")),
        ]),
        ("Eventos", [
            Item("eventos", "bi-calendar-event", "Eventos disponíveis",
                 _rota("eventos_competicoes.disponiveis")),
            Item("calendario", "bi-calendar3", "Calendário",
                 _rota("calendario.aluno_responsavel")),
        ]),
        ("Simuladores", [
            Item("sim_graduacao", "bi-graph-up", "Graduação prevista",
                 _rota("painel_responsavel.simular_graduacao_prevista")
                 if ctx.get("pratica_judo", True) else None),
            Item("sim_categoria", "bi-tags", "Categoria de competição",
                 _rota("painel_responsavel.simular_categorias")
                 if ctx.get("pratica_judo", True) else None),
            Item("associacao", "bi-diagram-3", "Treinar em outra academia",
                 _rota("painel_responsavel.associacao")),
        ]),
    ]


# ---------------------------------------------------------------- visitante
def _menu_visitante(ctx):
    return [
        ("", [
            Item("gerenciamento", "bi-person-circle", "Meu painel", _rota("visitante.painel")),
        ]),
        ("Aulas", [
            Item("presencas", "bi-clipboard-check", "Minhas aulas",
                 _rota("visitante.minhas_aulas")),
            Item("solicitar", "bi-plus-circle", "Solicitar aula",
                 _rota("visitante.solicitar_aula")),
        ]),
        ("Financeiro", [
            Item("financeiro", "bi-cash-coin", "Virar aluno / mensalidade",
                 _rota("visitante.solicitar_mensalidade")),
        ]),
    ]


_POR_MODO = {
    "academia":    _menu_academia,
    "admin":       _menu_admin,
    "federacao":   _menu_federacao,
    "associacao":  _menu_associacao,
    "professor":   _menu_professor,
    "aluno":       _menu_aluno,
    "responsavel": _menu_responsavel,
    "visitante":   _menu_visitante,
}


def menu_do_modo(modo, ctx=None):
    """Grupos visíveis da lateral para `modo`.

    Duas camadas, nesta ordem: o código monta o menu como sempre montou, e em
    cima dele vêm as exceções por modalidade que o administrador configurou.
    Ligar explicitamente devolve um item que o código esconderia; desligar tira
    um que ele mostraria. Sem exceção nenhuma, o resultado é o de antes.
    """
    ctx = ctx or {}
    montar = _POR_MODO.get(modo or "", _menu_academia)
    try:
        from utils.menu_modalidade import decisoes
        ligados, desligados = decisoes(modo, ctx.get("menu_modalidade_ids"))
    except Exception:
        ligados, desligados = set(), set()

    # Acesso do usuário nesta academia (MM-13): área sem permissão e itens só
    # do gestor principal saem do menu. A guarda das rotas bloqueia de verdade.
    bloqueados = set()
    if modo in ("academia", "professor"):
        try:
            from utils import acesso_academia as acs
            ac = acs.acesso(ctx.get("academia_id") or acs.academia_atual())
            for area, chaves in acs.MENU_AREA.items():
                if not ac.get(area, True):
                    bloqueados |= chaves
            if not ac["principal"]:
                bloqueados |= acs.MENU_SO_PRINCIPAL
        except Exception:
            bloqueados = set()

    grupos = []
    for rotulo, itens in montar(ctx):
        visiveis = []
        for it in itens:
            if it.chave in desligados or it.chave in bloqueados:
                continue
            if it.href:
                visiveis.append(it)
            elif it.chave in ligados:
                # O código escondeu, o administrador pediu de volta. Só entra
                # se a rota existir de verdade — item sem destino é pior que
                # item ausente.
                href = _href_do_item(modo, it.chave, ctx)
                if href:
                    visiveis.append(it._replace(href=href))
        if visiveis:
            grupos.append((rotulo, visiveis))
    return grupos


def _href_do_item(modo, chave, ctx):
    """Monta o menu com o contexto permissivo só para recuperar uma rota.

    Chamado apenas quando o administrador ligou um item que o código esconde —
    situação rara, então montar o menu uma segunda vez não pesa.
    """
    permissivo = dict(ctx)
    permissivo["pratica_judo"] = True
    permissivo["academia_tem_judo"] = True
    montar = _POR_MODO.get(modo or "", _menu_academia)
    try:
        for _rotulo, itens in montar(permissivo):
            for it in itens:
                if it.chave == chave:
                    return it.href
    except Exception:
        return None
    return None


def catalogo(modo, ctx=None):
    """Todos os itens de `modo`, escondidos inclusive — para a tela do admin.

    Devolve [(grupo, [Item, ...])] sem filtrar por rota nem por modalidade: a
    tela precisa listar o que existe, não o que este usuário veria.
    """
    permissivo = dict(ctx or {})
    permissivo["pratica_judo"] = True
    permissivo["academia_tem_judo"] = True
    permissivo["menu_modalidade_ids"] = []
    montar = _POR_MODO.get(modo or "", _menu_academia)
    try:
        return [(rotulo, list(itens)) for rotulo, itens in montar(permissivo) if itens]
    except Exception:
        return []
