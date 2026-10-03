# -*- coding: utf-8 -*-
"""Acesso de cada usuário dentro de uma academia (MM-13).

O papel (gestor_academia, professor) diz QUE TIPO de usuário a pessoa é; o
vínculo com a academia diz O QUE ela vê lá:

  • gestor principal — vê e faz tudo, e é quem gerencia o acesso dos outros;
  • áreas — financeiro e acadêmico, cada uma liga/desliga;
  • modalidades — quais ela enxerga (sem nada marcado, todas).

Admin, gestor de associação e de federação não passam por aqui: o escopo deles
é a associação inteira. Antes da MM-13 (sem as colunas), todo mundo tem acesso
total — exatamente o comportamento de antes.

O resultado fica em `flask.g` durante a requisição: o menu, o seletor de
modalidade e a guarda das rotas perguntam várias vezes a mesma coisa.
"""
from config import get_db_connection

AREAS = ("financeiro", "academico")

# Blueprints de cada área: a guarda das rotas e o menu usam o mesmo mapa.
BLUEPRINTS_AREA = {
    "financeiro": {"financeiro", "financeiro_painel"},
    "academico": {"presencas", "turmas", "exame_faixa", "calendario", "eventos_competicoes",
                  "competicoes", "aula_particular"},
}
# Itens do menu lateral (chaves de utils/menu.py) de cada área.
MENU_AREA = {
    "financeiro": {"financeiro"},
    "academico": {"presencas", "turmas", "aulas_particulares", "ranking", "exame_faixa",
                  "calendario", "eventos", "competicoes", "ata", "historico"},
}
# Só o gestor principal gerencia usuários e o acesso deles.
MENU_SO_PRINCIPAL = {"usuarios"}

_tem_estrutura = None


def tem_estrutura(cur):
    """MM-13 aplicada?"""
    global _tem_estrutura
    if _tem_estrutura is None:
        cur.execute("SHOW COLUMNS FROM usuarios_academias LIKE 'gestor_principal'")
        _tem_estrutura = bool(cur.fetchall())
    return _tem_estrutura


def _usuario():
    from flask_login import current_user
    return current_user


def escopo_amplo(usuario=None):
    """Admin / associação / federação: fora das restrições por academia."""
    u = usuario or _usuario()
    try:
        return bool(u and u.is_authenticated and (
            u.has_role("admin") or u.has_role("gestor_associacao") or u.has_role("gestor_federacao")))
    except Exception:
        return False


TOTAL = {"total": True, "principal": True, "financeiro": True, "academico": True, "modalidades": None}


def acesso(academia_id, usuario=None):
    """{total, principal, financeiro, academico, modalidades (set ou None = todas)}."""
    u = usuario or _usuario()
    if not academia_id or not u or not getattr(u, "is_authenticated", False):
        return dict(TOTAL)
    if escopo_amplo(u):
        return dict(TOTAL)
    chave = (int(u.id), int(academia_id))
    try:
        from flask import g, has_request_context
        cache = g.setdefault("_acesso_academia", {}) if has_request_context() else {}
    except Exception:
        cache = {}
    if chave in cache:
        return cache[chave]

    eh_gestor = u.has_role("gestor_academia")
    resultado = dict(TOTAL, total=False, principal=eh_gestor)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if tem_estrutura(cur):
            cur.execute(
                """SELECT gestor_principal, acesso_financeiro, acesso_academico
                   FROM usuarios_academias WHERE usuario_id = %s AND academia_id = %s""", chave)
            _linhas = cur.fetchall()
            v = _linhas[0] if _linhas else None
            if v:
                resultado["principal"] = bool(eh_gestor and v["gestor_principal"])
                resultado["financeiro"] = bool(v["acesso_financeiro"])
                resultado["academico"] = bool(v["acesso_academico"])
            cur.execute(
                """SELECT modalidade_id FROM usuario_academia_modalidade
                   WHERE usuario_id = %s AND academia_id = %s""", chave)
            mods = {int(r["modalidade_id"]) for r in cur.fetchall()}
            resultado["modalidades"] = mods or None
        if resultado["principal"]:
            # Principal vê tudo, mesmo que alguém tenha marcado algo antes.
            resultado.update(financeiro=True, academico=True, modalidades=None)
    finally:
        cur.close()
        conn.close()
    cache[chave] = resultado
    return resultado


def academia_atual():
    """Academia aberta nesta sessão (a mesma que o shell usa)."""
    try:
        from flask import session
        aid = session.get("academia_gerenciamento_id") or session.get("finance_academia_id")
        return int(aid) if aid else None
    except Exception:
        return None


def eh_principal(academia_id=None, usuario=None):
    return acesso(academia_id or academia_atual(), usuario)["principal"]


def pode_area(area, academia_id=None, usuario=None):
    return bool(acesso(academia_id or academia_atual(), usuario).get(area, True))


def modalidades_permitidas(academia_id=None, usuario=None):
    """set de modalidade_id, ou None quando pode ver todas."""
    return acesso(academia_id or academia_atual(), usuario)["modalidades"]


def area_do_blueprint(blueprint):
    for area, bps in BLUEPRINTS_AREA.items():
        if blueprint in bps:
            return area
    return None


def gravar(cur, usuario_id, academia_id, principal=None, financeiro=True, academico=True, modalidades=None):
    """Grava o acesso do usuário na academia (tela de edição de usuário).

    `modalidades` vazio/None = todas. Cria o vínculo se ainda não existir
    (professor costuma estar só na tabela `professores`).
    """
    cur.execute("INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)",
                (usuario_id, academia_id))
    sets, params = ["acesso_financeiro = %s", "acesso_academico = %s"], [int(bool(financeiro)), int(bool(academico))]
    if principal is not None:
        sets.append("gestor_principal = %s")
        params.append(int(bool(principal)))
    cur.execute(f"UPDATE usuarios_academias SET {', '.join(sets)} WHERE usuario_id = %s AND academia_id = %s",
                (*params, usuario_id, academia_id))
    cur.execute("DELETE FROM usuario_academia_modalidade WHERE usuario_id = %s AND academia_id = %s",
                (usuario_id, academia_id))
    for mid in sorted({int(m) for m in (modalidades or []) if str(m).strip().isdigit()}):
        cur.execute("""INSERT INTO usuario_academia_modalidade (usuario_id, academia_id, modalidade_id)
                       VALUES (%s, %s, %s)""", (usuario_id, academia_id, mid))


def outros_principais(cur, academia_id, exceto_usuario_id):
    """Quantos OUTROS gestores principais a academia tem (não pode ficar sem nenhum)."""
    cur.execute(
        f"""SELECT COUNT(DISTINCT ua.usuario_id) AS n FROM usuarios_academias ua
            JOIN roles_usuario ru ON ru.usuario_id = ua.usuario_id{sql_papel_na_academia("ru", "ua.academia_id")}
            JOIN roles r ON r.id = ru.role_id AND r.chave = 'gestor_academia'
            JOIN usuarios u ON u.id = ua.usuario_id AND COALESCE(u.ativo, 1) = 1
            WHERE ua.academia_id = %s AND ua.gestor_principal = 1 AND ua.usuario_id <> %s""",
        (academia_id, exceto_usuario_id))
    r = cur.fetchone()
    return int((r.get("n") if isinstance(r, dict) else r[0]) or 0)


def ler(cur, usuario_id, academia_id):
    """Acesso gravado de um usuário (para a tela de edição): {principal,
    financeiro, academico, modalidades:set}. Sem vínculo/MM-13: tudo liberado."""
    out = {"principal": False, "financeiro": True, "academico": True, "modalidades": set()}
    if not tem_estrutura(cur):
        return out
    cur.execute("""SELECT gestor_principal, acesso_financeiro, acesso_academico
                   FROM usuarios_academias WHERE usuario_id = %s AND academia_id = %s""",
                (usuario_id, academia_id))
    v = cur.fetchone()
    if v:
        out.update(principal=bool(v["gestor_principal"]), financeiro=bool(v["acesso_financeiro"]),
                   academico=bool(v["acesso_academico"]))
    cur.execute("""SELECT modalidade_id FROM usuario_academia_modalidade
                   WHERE usuario_id = %s AND academia_id = %s""", (usuario_id, academia_id))
    out["modalidades"] = {int(r["modalidade_id"]) for r in cur.fetchall()}
    return out


def secao_da_tela(cur, usuario_alvo_id, academia_pedida=None):
    """Dados da seção "Acesso em <academia>" da edição de usuário, ou None.

    O acesso é por academia: quem está em duas tem uma configuração em cada.
    A seção mostra uma academia por vez — a pedida (botões no topo da seção),
    senão a aberta no sistema, senão a primeira — entre as academias em que o
    usuário é gestor/professor E quem edita pode mexer (é principal lá, ou
    admin/associação/federação).
    """
    if not tem_estrutura(cur):
        return None
    cur.execute("""SELECT ua.academia_id AS id, ac.nome FROM usuarios_academias ua
                   JOIN academias ac ON ac.id = ua.academia_id
                   WHERE ua.usuario_id = %s ORDER BY ac.nome""", (usuario_alvo_id,))
    academias = []
    for a in cur.fetchall():
        aid = int(a["id"])
        if not (escopo_amplo() or eh_principal(aid)):
            continue
        cur.execute(f"""SELECT r.chave FROM roles_usuario ru JOIN roles r ON r.id = ru.role_id
                        WHERE ru.usuario_id = %s{sql_papel_na_academia("ru", str(aid))}""",
                    (usuario_alvo_id,))
        chaves = {r["chave"] for r in cur.fetchall()}
        if chaves & {"gestor_academia", "professor"}:
            academias.append({"id": aid, "nome": a["nome"], "eh_gestor": "gestor_academia" in chaves})
    if not academias:
        return None
    ids = [a["id"] for a in academias]
    try:
        pedida = int(academia_pedida) if academia_pedida else None
    except (TypeError, ValueError):
        pedida = None
    escolhida = pedida if pedida in ids else (academia_atual() if academia_atual() in ids else ids[0])
    atual = next(a for a in academias if a["id"] == escolhida)
    from utils import multimodalidade as mm
    return {"academia_id": escolhida, "academia_nome": atual["nome"], "eh_gestor": atual["eh_gestor"],
            "academias": academias,
            "modalidades": mm.modalidades_da_academia(escolhida),
            "atual": ler(cur, usuario_alvo_id, escolhida)}


def roles_atribuiveis(cur, usuario=None):
    """ids de papel que o usuário logado pode dar a alguém.

    O formulário já escondia os papéis globais, mas o servidor aceitava
    qualquer id enviado — dava para criar um admin postando o formulário à mão.
    """
    u = usuario or _usuario()
    cur.execute("SELECT id, chave FROM roles")
    todos = {(r["chave"] if isinstance(r, dict) else r[1]): (r["id"] if isinstance(r, dict) else r[0])
             for r in cur.fetchall()}
    if u.has_role("admin"):
        permitidos = set(todos)
    elif u.has_role("gestor_federacao"):
        permitidos = set(todos) - {"admin"}
    elif u.has_role("gestor_associacao"):
        permitidos = set(todos) - {"admin", "gestor_federacao"}
    else:
        permitidos = {"aluno", "professor", "gestor_academia", "responsavel", "visitante"}
    return {todos[c] for c in permitidos if c in todos}


# --------------------------------------------- papel por academia (MM-14)
PAPEIS_DE_ACADEMIA = ("gestor_academia", "professor", "aluno", "responsavel", "visitante")
_tem_papel_academia = None


def tem_papel_por_academia(cur):
    """roles_usuario.academia_id existe? (MM-14 aplicada)"""
    global _tem_papel_academia
    if _tem_papel_academia is None:
        cur.execute("SHOW COLUMNS FROM roles_usuario LIKE 'academia_id'")
        _tem_papel_academia = bool(cur.fetchall())
    return _tem_papel_academia


def academia_dos_papeis():
    """Academia que recorta os papéis do usuário nesta requisição, ou None.

    Só nos modos de equipe (academia/professor) com academia escolhida: é aí
    que "gestor aqui, aluno lá" faz diferença. Nos modos aluno/responsável e
    antes de escolher a academia, valem todos os papéis — é assim que o seletor
    de modo sabe quais modos oferecer.
    """
    try:
        from flask import has_request_context, session
        if not has_request_context():
            return None
        if (session.get("modo_painel") or "") not in ("academia", "professor"):
            return None
        aid = session.get("academia_gerenciamento_id")
        return int(aid) if aid else None
    except Exception:
        return None


def papeis_na_academia(cur, usuario_id, academia_id):
    """ids de papel do usuário que valem nesta academia (os globais incluídos)."""
    if tem_papel_por_academia(cur):
        cur.execute("""SELECT role_id FROM roles_usuario
                       WHERE usuario_id = %s AND academia_id IN (0, %s)""", (usuario_id, academia_id or 0))
    else:
        cur.execute("SELECT role_id FROM roles_usuario WHERE usuario_id = %s", (usuario_id,))
    return {int(r["role_id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}


def _ids_papeis_de_academia(cur):
    ph = ",".join(["%s"] * len(PAPEIS_DE_ACADEMIA))
    cur.execute(f"SELECT id FROM roles WHERE chave IN ({ph})", PAPEIS_DE_ACADEMIA)
    return {int(r["id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}


def _desdobrar_global(cur, usuario_id, role_id):
    """Papel de academia gravado como global (0): vira uma linha por academia
    vinculada, para poder mudar numa sem mexer nas outras."""
    cur.execute("SELECT 1 FROM roles_usuario WHERE usuario_id = %s AND role_id = %s AND academia_id = 0",
                (usuario_id, role_id))
    if not cur.fetchall():
        return
    cur.execute("""INSERT IGNORE INTO roles_usuario (usuario_id, role_id, academia_id)
                   SELECT %s, %s, academia_id FROM usuarios_academias WHERE usuario_id = %s""",
                (usuario_id, role_id, usuario_id))
    cur.execute("DELETE FROM roles_usuario WHERE usuario_id = %s AND role_id = %s AND academia_id = 0",
                (usuario_id, role_id))


def gravar_papeis(cur, usuario_id, marcados, visiveis, academia_id=None):
    """Grava os papéis da tela de usuário.

    Com MM-14 e academia escolhida, os papéis de academia (gestor, professor,
    aluno, responsável, visitante) valem SÓ nesta academia: marcar aqui não faz
    a pessoa gestora nas outras, desmarcar aqui não a tira das outras. Papéis
    globais (admin, associação, federação) seguem com academia 0.
    Só mexe nos `visiveis` (o que a tela mostrava e quem edita pode dar).
    """
    marcados = {int(x) for x in marcados if str(x).isdigit()}
    visiveis = {int(x) for x in visiveis}
    por_academia = tem_papel_por_academia(cur) and academia_id
    de_academia = _ids_papeis_de_academia(cur) if por_academia else set()
    for rid in visiveis:
        if por_academia and rid in de_academia:
            _desdobrar_global(cur, usuario_id, rid)
            if rid in marcados:
                cur.execute("""INSERT IGNORE INTO roles_usuario (usuario_id, role_id, academia_id)
                               VALUES (%s, %s, %s)""", (usuario_id, rid, academia_id))
            else:
                cur.execute("""DELETE FROM roles_usuario
                               WHERE usuario_id = %s AND role_id = %s AND academia_id = %s""",
                            (usuario_id, rid, academia_id))
        else:
            if rid in marcados:
                cur.execute("INSERT IGNORE INTO roles_usuario (usuario_id, role_id) VALUES (%s, %s)",
                            (usuario_id, rid))
            elif tem_papel_por_academia(cur):
                cur.execute("DELETE FROM roles_usuario WHERE usuario_id = %s AND role_id = %s AND academia_id = 0",
                            (usuario_id, rid))
            else:
                cur.execute("DELETE FROM roles_usuario WHERE usuario_id = %s AND role_id = %s",
                            (usuario_id, rid))


def inserir_papeis_novo_usuario(cur, usuario_id, role_ids, academias):
    """Usuário novo: papel de academia em cada academia escolhida; global com 0."""
    role_ids = [int(x) for x in role_ids if str(x).isdigit()]
    if not tem_papel_por_academia(cur) or not academias:
        for rid in role_ids:
            cur.execute("INSERT IGNORE INTO roles_usuario (usuario_id, role_id) VALUES (%s, %s)", (usuario_id, rid))
        return
    de_academia = _ids_papeis_de_academia(cur)
    for rid in role_ids:
        alvos = academias if rid in de_academia else [0]
        for aid in alvos:
            cur.execute("""INSERT IGNORE INTO roles_usuario (usuario_id, role_id, academia_id)
                           VALUES (%s, %s, %s)""", (usuario_id, rid, int(aid)))


def _checar_papel_academia():
    """Garante o cache de `tem_papel_por_academia` sem precisar de cursor."""
    if _tem_papel_academia is None:
        conn = get_db_connection()
        c = conn.cursor()
        try:
            tem_papel_por_academia(c)
        finally:
            c.close()
            conn.close()
    return _tem_papel_academia


def sql_papel_na_academia(alias_ru="ru", expr_academia="ua.academia_id"):
    """Trecho " AND ru.academia_id IN (0, <academia>)" para consultas do tipo
    "gestor/professor DA academia X". Antes da MM-14, vazio (papel global)."""
    if not _checar_papel_academia():
        return ""
    return f" AND {alias_ru}.academia_id IN (0, {expr_academia})"


def inserir_papel(cur, usuario_id, role_id, academia_id=None):
    """Dá um papel ao usuário NAQUELA academia (MM-14); sem a migração ou sem
    academia, global como antes. Papel global (admin, associação, federação)
    sempre vai com academia 0."""
    if academia_id and tem_papel_por_academia(cur) and int(role_id) in _ids_papeis_de_academia(cur):
        cur.execute("""INSERT IGNORE INTO roles_usuario (usuario_id, role_id, academia_id)
                       VALUES (%s, %s, %s)""", (usuario_id, role_id, int(academia_id)))
    else:
        cur.execute("INSERT IGNORE INTO roles_usuario (usuario_id, role_id) VALUES (%s, %s)",
                    (usuario_id, role_id))
