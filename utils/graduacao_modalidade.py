# -*- coding: utf-8 -*-
"""Graduação por modalidade.

Quem treina judô e jiu-jitsu tem uma faixa em cada. A faixa mora no vínculo do
aluno com a modalidade (`aluno_modalidades.graduacao_id`, migração MM-11).

`alunos.graduacao_id` continua sendo a faixa da modalidade principal: as telas
que ainda não olham a modalidade seguem funcionando com ela. Toda gravação por
aqui mantém as duas coisas coerentes (`sincronizar_principal`).

Antes da migração a coluna não existe: as leituras caem no comportamento antigo
(a faixa única vale para a modalidade dela) e as gravações por modalidade são
ignoradas — nada quebra enquanto a migração não roda.
"""

_tem_coluna = None
_tem_data = None


def tem_data(cur):
    """A coluna aluno_modalidades.data_graduacao existe? (MM-12 aplicada)"""
    global _tem_data
    if _tem_data is None:
        cur.execute("SHOW COLUMNS FROM aluno_modalidades LIKE 'data_graduacao'")
        _tem_data = bool(cur.fetchall())
    return _tem_data


def tem_coluna(cur):
    """A coluna aluno_modalidades.graduacao_id existe? (MM-11 aplicada)"""
    global _tem_coluna
    if _tem_coluna is None:
        cur.execute("SHOW COLUMNS FROM aluno_modalidades LIKE 'graduacao_id'")
        _tem_coluna = bool(cur.fetchall())
    return _tem_coluna


def rotulo_faixa(faixa, graduacao=None, categoria=None):
    """"Marrom", "Branca - 1º grau": só as partes preenchidas (sem o "." de cadastro)."""
    partes = [str(p).strip() for p in (faixa, graduacao, categoria) if p is not None]
    return " - ".join(p for p in partes if p and p not in (".", "-"))


def faixas_por_modalidade(cur, aluno_ids):
    """{aluno_id: [{modalidade_id, modalidade, graduacao_id, faixa, graduacao, rotulo}]}

    Uma linha por modalidade do aluno, em ordem de nome. `graduacao_id` None =
    faixa ainda não informada naquela modalidade.
    """
    ids = sorted({int(i) for i in aluno_ids if i})
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    if tem_coluna(cur):
        col_data = ("am.data_graduacao" if tem_data(cur)
                    else "CASE WHEN am.graduacao_id = a.graduacao_id THEN a.ultimo_exame_faixa END")
        cur.execute(
            f"""SELECT am.aluno_id, am.modalidade_id, md.nome AS modalidade, am.graduacao_id,
                       g.faixa, g.graduacao, {col_data} AS data_graduacao
                FROM aluno_modalidades am
                JOIN alunos a ON a.id = am.aluno_id
                JOIN modalidade md ON md.id = am.modalidade_id
                LEFT JOIN graduacao g ON g.id = am.graduacao_id
                WHERE am.aluno_id IN ({ph})
                ORDER BY md.nome""", tuple(ids))
        linhas = cur.fetchall()
    else:
        # Sem a migração: a faixa única vale só para a modalidade dela (ou para
        # a única modalidade do aluno, se a faixa for genérica).
        cur.execute(
            f"""SELECT am.aluno_id, am.modalidade_id, md.nome AS modalidade,
                       CASE WHEN g.modalidade_id = am.modalidade_id
                              OR (g.modalidade_id IS NULL AND
                                  (SELECT COUNT(*) FROM aluno_modalidades x WHERE x.aluno_id = am.aluno_id) = 1)
                            THEN a.graduacao_id END AS graduacao_id,
                       g.faixa, g.graduacao, g.modalidade_id AS g_mod, a.ultimo_exame_faixa AS data_graduacao
                FROM aluno_modalidades am
                JOIN modalidade md ON md.id = am.modalidade_id
                JOIN alunos a ON a.id = am.aluno_id
                LEFT JOIN graduacao g ON g.id = a.graduacao_id
                WHERE am.aluno_id IN ({ph})
                ORDER BY md.nome""", tuple(ids))
        linhas = cur.fetchall()
        for r in linhas:
            if not r["graduacao_id"]:
                r["faixa"] = r["graduacao"] = r["data_graduacao"] = None
    out = {}
    vistos = set()
    for r in linhas:
        # aluno_modalidades tinha linhas repetidas (sem chave única antes da MM-11).
        if (r["aluno_id"], r["modalidade_id"]) in vistos:
            continue
        vistos.add((r["aluno_id"], r["modalidade_id"]))
        out.setdefault(r["aluno_id"], []).append({
            "modalidade_id": r["modalidade_id"], "modalidade": r["modalidade"],
            "graduacao_id": r["graduacao_id"], "faixa": r.get("faixa"), "graduacao": r.get("graduacao"),
            "data_graduacao": r.get("data_graduacao"),
            "rotulo": rotulo_faixa(r.get("faixa"), r.get("graduacao")) if r["graduacao_id"] else "",
        })
    return out


def faixa_na_modalidade(cur, aluno_id, modalidade_id):
    """A linha da modalidade (ver `faixas_por_modalidade`) ou None."""
    for f in faixas_por_modalidade(cur, [aluno_id]).get(int(aluno_id), []):
        if f["modalidade_id"] == int(modalidade_id):
            return f
    return None


def sincronizar_principal(cur, aluno_id, preferir_modalidade=None):
    """Mantém alunos.graduacao_id = faixa da modalidade principal.

    Principal: a modalidade da faixa que já estava em alunos.graduacao_id, se
    ela ainda tem faixa; senão `preferir_modalidade`; senão a primeira com faixa.
    """
    if not tem_coluna(cur):
        return
    col_data = "am.data_graduacao" if tem_data(cur) else "NULL"
    cur.execute(
        f"""SELECT am.modalidade_id, am.graduacao_id, {col_data} AS data_graduacao
            FROM aluno_modalidades am
            JOIN modalidade md ON md.id = am.modalidade_id
            WHERE am.aluno_id = %s AND am.graduacao_id IS NOT NULL ORDER BY md.nome""", (aluno_id,))
    linhas = cur.fetchall()
    com_faixa = {r["modalidade_id"]: r["graduacao_id"] for r in linhas}
    datas = {r["modalidade_id"]: r["data_graduacao"] for r in linhas}
    if not com_faixa:
        return
    cur.execute(
        """SELECT g.modalidade_id FROM alunos a JOIN graduacao g ON g.id = a.graduacao_id
           WHERE a.id = %s""", (aluno_id,))
    atual = (cur.fetchone() or {}).get("modalidade_id")
    for mod in (atual, preferir_modalidade):
        if mod in com_faixa:
            mod_escolhida = mod
            break
    else:
        mod_escolhida = next(iter(com_faixa))
    cur.execute("UPDATE alunos SET graduacao_id = %s WHERE id = %s", (com_faixa[mod_escolhida], aluno_id))
    # A data única (telas antigas) acompanha a da modalidade principal.
    if tem_data(cur) and datas.get(mod_escolhida):
        cur.execute("UPDATE alunos SET ultimo_exame_faixa = %s WHERE id = %s",
                    (datas[mod_escolhida], aluno_id))


def gravar_faixas(cur, aluno_id, faixas, datas=None):
    """Grava {modalidade_id: graduacao_id|None} nos vínculos do aluno e sincroniza a principal.

    `datas`: {modalidade_id: date|None} — data da última graduação em cada uma
    (só com a MM-12; antes dela fica a data única do cadastro).

    Só toca modalidades que o aluno tem; graduação de outra modalidade é recusada
    (a faixa de judô não entra no jiu-jitsu).
    """
    if not tem_coluna(cur) or not faixas:
        return
    for mod_id, grad_id in faixas.items():
        if grad_id:
            cur.execute("SELECT modalidade_id FROM graduacao WHERE id = %s", (grad_id,))
            g = cur.fetchone()
            if not g or (g.get("modalidade_id") and int(g["modalidade_id"]) != int(mod_id)):
                continue
        cur.execute(
            "UPDATE aluno_modalidades SET graduacao_id = %s WHERE aluno_id = %s AND modalidade_id = %s",
            (grad_id or None, aluno_id, mod_id))
        if datas is not None and int(mod_id) in datas and tem_data(cur):
            cur.execute(
                "UPDATE aluno_modalidades SET data_graduacao = %s WHERE aluno_id = %s AND modalidade_id = %s",
                (datas[int(mod_id)] if grad_id else None, aluno_id, mod_id))
    sincronizar_principal(cur, aluno_id)


def registrar(cur, aluno_id, graduacao_id, data=None):
    """Uma graduação nova (ficha, exame): vai para a modalidade dela.

    Faixa genérica (sem modalidade) vai para a modalidade principal. Devolve o
    modalidade_id que recebeu, ou None.
    """
    if not (tem_coluna(cur) and graduacao_id):
        return None
    cur.execute("SELECT modalidade_id FROM graduacao WHERE id = %s", (graduacao_id,))
    mod = (cur.fetchone() or {}).get("modalidade_id")
    if not mod:
        cur.execute(
            """SELECT g.modalidade_id FROM alunos a JOIN graduacao g ON g.id = a.graduacao_id
               WHERE a.id = %s""", (aluno_id,))
        mod = (cur.fetchone() or {}).get("modalidade_id")
    if not mod:
        return None
    cur.execute(
        "UPDATE aluno_modalidades SET graduacao_id = %s WHERE aluno_id = %s AND modalidade_id = %s",
        (graduacao_id, aluno_id, mod))
    cur.execute("SELECT 1 FROM aluno_modalidades WHERE aluno_id = %s AND modalidade_id = %s",
                (aluno_id, mod))
    if not cur.fetchone():
        return None
    if data and tem_data(cur):
        cur.execute(
            "UPDATE aluno_modalidades SET data_graduacao = %s WHERE aluno_id = %s AND modalidade_id = %s",
            (data, aluno_id, mod))
    sincronizar_principal(cur, aluno_id, preferir_modalidade=mod)
    return mod


def sql_faixa_no_contexto(modalidade_id, alias="a", cur=None):
    """(join_sql, params, on_graduacao_sql, on_params) para listas com modalidade em foco.

    Uso: FROM alunos a {join} ... LEFT JOIN graduacao g ON {on_graduacao}
    (params de `join` antes dos de `on`, na ordem em que aparecem).

    Com modalidade escolhida a faixa é a do aluno NELA — nunca cai na faixa de
    outra modalidade. Sem a migração, vale a principal só se for dessa
    modalidade (ou genérica). Sem modalidade em foco, a principal.
    """
    if cur is not None and modalidade_id:
        tem_coluna(cur)
    if not modalidade_id:
        return "", (), f"g.id = {alias}.graduacao_id", ()
    mid = int(modalidade_id)
    if _tem_coluna:
        join = (f" LEFT JOIN aluno_modalidades am_fx ON am_fx.aluno_id = {alias}.id"
                f" AND am_fx.modalidade_id = %s ")
        return join, (mid,), "g.id = am_fx.graduacao_id", ()
    return "", (), f"g.id = {alias}.graduacao_id AND (g.modalidade_id IS NULL OR g.modalidade_id = %s)", (mid,)


def sincronizar_modalidades(cur, aluno_id, modalidade_ids, escopo=None):
    """Deixa o aluno nestas modalidades SEM apagar o vínculo das que ficam.

    Antes as telas faziam DELETE + INSERT em aluno_modalidades; com a faixa
    morando no vínculo, isso apagaria a graduação a cada salvamento.

    `escopo`: modalidades que a tela oferecia. Só elas podem ser removidas — a
    academia B editando o aluno não apaga o jiu-jitsu que ele faz na academia A
    (a modalidade nem aparecia na tela dela). Sem escopo, vale tudo (legado).
    """
    novos = {int(m) for m in (modalidade_ids or []) if str(m).strip().isdigit()}
    cur.execute("SELECT modalidade_id FROM aluno_modalidades WHERE aluno_id = %s", (aluno_id,))
    atuais = {int(r["modalidade_id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}
    removiveis = atuais - novos
    if escopo is not None:
        removiveis &= {int(m) for m in escopo}
    for mid in removiveis:
        cur.execute("DELETE FROM aluno_modalidades WHERE aluno_id = %s AND modalidade_id = %s",
                    (aluno_id, mid))
    for mid in novos - atuais:
        cur.execute("INSERT IGNORE INTO aluno_modalidades (aluno_id, modalidade_id) VALUES (%s, %s)",
                    (aluno_id, mid))


def proxima_faixa(cur, graduacao_id):
    """Rótulo da faixa seguinte NA MESMA modalidade (pela ordem do cadastro), ou "—".

    Antes a próxima era a de id seguinte na tabela inteira: a "próxima" de uma
    faixa de judô podia sair uma de jiu-jitsu.
    """
    if not graduacao_id:
        return "—"
    cur.execute("SELECT modalidade_id, ordem FROM graduacao WHERE id = %s", (graduacao_id,))
    g = cur.fetchone()
    if not g:
        return "—"
    cur.execute(
        """SELECT faixa, graduacao FROM graduacao
           WHERE modalidade_id <=> %s AND COALESCE(ativo, 1) = 1 AND id <> %s
             AND (COALESCE(ordem, 0) > COALESCE(%s, 0)
                  OR (COALESCE(ordem, 0) = COALESCE(%s, 0) AND id > %s))
           ORDER BY COALESCE(ordem, 0), id LIMIT 1""",
        (g.get("modalidade_id"), graduacao_id, g.get("ordem"), g.get("ordem"), graduacao_id))
    p = cur.fetchone()
    return rotulo_faixa(p.get("faixa"), p.get("graduacao")) if p else "—"


def id_modalidade_judo(cur):
    """Id da modalidade Judô (Zempo e exame de faixa são só de judô)."""
    cur.execute("SELECT id FROM modalidade WHERE nome IN ('Judô', 'Judo', 'JUDÔ', 'JUDO') ORDER BY id LIMIT 1")
    r = cur.fetchone()
    return (r.get("id") if isinstance(r, dict) else r[0]) if r else None


def graduacao_judo_por_nome(cur, faixa):
    """Graduação de JUDÔ com esse nome de faixa (a do Zempo). Antes pegava a primeira
    com o nome, de qualquer modalidade — "AZUL" podia virar a Azul do jiu-jitsu."""
    if not faixa:
        return None
    judo = id_modalidade_judo(cur)
    cur.execute(
        """SELECT id FROM graduacao WHERE UPPER(faixa) = UPPER(%s)
           ORDER BY (modalidade_id <=> %s) DESC, COALESCE(ativo, 1) DESC, COALESCE(ordem, 0), id LIMIT 1""",
        (faixa, judo))
    r = cur.fetchone()
    return (r.get("id") if isinstance(r, dict) else r[0]) if r else None


def aplicar_faixa_importada(cur, aluno_id, graduacao_id):
    """Faixa vinda de fora (Zempo): vai para a modalidade dela. Só cai na faixa
    única quando o aluno ainda não tem modalidade nenhuma (cadastro antigo)."""
    if not graduacao_id:
        return
    if registrar(cur, aluno_id, graduacao_id):
        return
    cur.execute("SELECT COUNT(*) AS n FROM aluno_modalidades WHERE aluno_id = %s", (aluno_id,))
    r = cur.fetchone()
    n = r.get("n") if isinstance(r, dict) else r[0]
    if not n:
        cur.execute("UPDATE alunos SET graduacao_id = %s WHERE id = %s", (graduacao_id, aluno_id))


def modalidade_em_foco():
    """Modalidade escolhida no seletor do topo (sessão), ou None — fora de request também."""
    try:
        from flask import has_request_context, session
        if not has_request_context():
            return None
        from utils.multimodalidade import CHAVE_SESSAO
        v = session.get(CHAVE_SESSAO)
        return int(v) if v else None
    except Exception:
        return None


def sql_join_faixa(alias="a", g="g", modalidade_id=None):
    """Trecho `LEFT JOIN graduacao <g>` que segue a modalidade em foco.

    Substitui o `LEFT JOIN graduacao g ON g.id = a.graduacao_id` das listas:
    com judô no topo, a coluna de faixa mostra a de judô (e "—" para quem não
    tem), nunca a de jiu-jitsu. Sem modalidade em foco, a faixa principal.
    O id vai como inteiro validado — não vem do usuário cru.
    """
    mid = modalidade_id if modalidade_id is not None else modalidade_em_foco()
    if not mid:
        return f"LEFT JOIN graduacao {g} ON {g}.id = {alias}.graduacao_id"
    mid = int(mid)
    if _tem_coluna is None:
        try:
            from config import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            try:
                tem_coluna(c)
            finally:
                c.close()
                conn.close()
        except Exception:
            pass
    if _tem_coluna:
        am = f"am_fx_{g}"
        return (f"LEFT JOIN aluno_modalidades {am} ON {am}.aluno_id = {alias}.id AND {am}.modalidade_id = {mid} "
                f"LEFT JOIN graduacao {g} ON {g}.id = {am}.graduacao_id")
    return (f"LEFT JOIN graduacao {g} ON {g}.id = {alias}.graduacao_id "
            f"AND ({g}.modalidade_id IS NULL OR {g}.modalidade_id = {mid})")


def sql_graduacao_na_modalidade(modalidade_id, alias="a"):
    """Expressão SQL: a graduacao_id do aluno NA modalidade; sem vínculo com ela, a principal.

    Mesma regra de `exame_faixa.usar_faixa_do_programa`: quem tem a modalidade
    mas ainda não tem faixa nela fica sem faixa (NULL), não herda a de outra.
    """
    if not modalidade_id or not _tem_coluna:
        return f"{alias}.graduacao_id"
    mid = int(modalidade_id)
    return (f"(CASE WHEN EXISTS (SELECT 1 FROM aluno_modalidades amx WHERE amx.aluno_id = {alias}.id "
            f"AND amx.modalidade_id = {mid}) THEN (SELECT amx.graduacao_id FROM aluno_modalidades amx "
            f"WHERE amx.aluno_id = {alias}.id AND amx.modalidade_id = {mid} LIMIT 1) "
            f"ELSE {alias}.graduacao_id END)")
