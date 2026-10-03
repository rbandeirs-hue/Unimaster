# -*- coding: utf-8 -*-
"""Plano de mensalidade da turma e opções de modalidade/turma dos formulários públicos.

A turma diz qual plano cobra (`turmas.mensalidade_id`, migração PRE-01). A
modalidade não basta para isso: o mesmo Jiu-Jitsu pode ter "Infantil R$ 85" e
"Adulto R$ 110" na mesma academia — quem separa os dois é a turma.

Usos:
  * cadastro/edição de turma: escolher o plano;
  * matrícula pública: o valor da matrícula é a mensalidade da turma escolhida
    (sem plano na turma, vale o valor fixo da academia, como antes);
  * pré-cadastro, matrícula e aula experimental: o candidato escolhe a
    modalidade e só vê as turmas e as faixas dela.
"""


def planos_da_academia(cur, academia_id):
    """Planos ativos que a academia pode ligar a uma turma (os dela e os da associação)."""
    if not academia_id:
        return []
    cur.execute(
        """SELECT m.id, m.nome, m.valor
           FROM mensalidades m
           LEFT JOIN academias ac ON ac.id = %s
           WHERE m.ativo = 1 AND COALESCE(m.periodicidade, 'mensal') <> 'diaria'
             AND (m.id_academia = %s
                  OR (m.id_academia IS NULL AND m.id_associacao IS NOT NULL
                      AND m.id_associacao = ac.id_associacao))
           ORDER BY m.nome""",
        (academia_id, academia_id))
    return cur.fetchall()


def gravar_plano(cur, turma_id, academia_id, bruto):
    """Grava o plano da turma, aceitando só plano que a academia pode usar."""
    plano_id = int(bruto) if bruto and str(bruto).isdigit() else None
    if plano_id and plano_id not in {p["id"] for p in planos_da_academia(cur, academia_id)}:
        plano_id = None
    try:
        cur.execute("UPDATE turmas SET mensalidade_id = %s WHERE TurmaID = %s", (plano_id, turma_id))
    except Exception:
        pass  # PRE-01 não aplicada: a turma segue sem plano


# ------------------------------------------------- formulários públicos
def _como_lista(texto):
    return [int(x) for x in str(texto or "").replace(";", ",").split(",") if x.strip().isdigit()]


def opcoes(cur, academia_id):
    """Modalidades, turmas e faixas da academia, prontas para o formulário público.

    Cada turma traz `modalidades` (ids) e, se tiver plano, `plano_nome`/`valor`;
    cada faixa traz `modalidade_id`. O formulário usa isso para mostrar só o
    que é da modalidade escolhida.
    """
    cur.execute(
        """SELECT m.id, m.nome, m.cor FROM modalidade m
           JOIN academia_modalidades am ON am.modalidade_id = m.id
           WHERE am.academia_id = %s AND m.ativo = 1 ORDER BY m.nome""", (academia_id,))
    mods = cur.fetchall()
    try:
        cur.execute(
            """SELECT t.TurmaID AS id, t.Nome AS nome, t.DiasHorario AS dias, t.IdadeMin, t.IdadeMax,
                      t.hora_inicio, t.hora_fim, t.mensalidade_id,
                      ms.nome AS plano_nome, ms.valor AS plano_valor,
                      GROUP_CONCAT(tm.modalidade_id) AS mods
               FROM turmas t
               LEFT JOIN turma_modalidades tm ON tm.turma_id = t.TurmaID
               LEFT JOIN mensalidades ms ON ms.id = t.mensalidade_id AND ms.ativo = 1
               WHERE t.id_academia = %s
               GROUP BY t.TurmaID ORDER BY t.Nome""", (academia_id,))
    except Exception:
        cur.execute(
            """SELECT t.TurmaID AS id, t.Nome AS nome, t.DiasHorario AS dias, t.IdadeMin, t.IdadeMax,
                      t.hora_inicio, t.hora_fim, NULL AS mensalidade_id,
                      NULL AS plano_nome, NULL AS plano_valor,
                      GROUP_CONCAT(tm.modalidade_id) AS mods
               FROM turmas t LEFT JOIN turma_modalidades tm ON tm.turma_id = t.TurmaID
               WHERE t.id_academia = %s GROUP BY t.TurmaID ORDER BY t.Nome""", (academia_id,))
    turmas = cur.fetchall()
    for t in turmas:
        t["modalidades"] = _como_lista(t.pop("mods", ""))
    ids_mods = [m["id"] for m in mods]
    graduacoes = []
    try:
        cur.execute(
            """SELECT id, faixa, graduacao, modalidade_id FROM graduacao
               WHERE ativo = 1 ORDER BY modalidade_id, ordem, id""")
        graduacoes = [g for g in cur.fetchall()
                      if not g["modalidade_id"] or not ids_mods or g["modalidade_id"] in ids_mods]
    except Exception:
        pass
    return {"modalidades": mods, "turmas": turmas, "graduacoes": graduacoes}


def ler_escolha(form, op, exigir_turma=False):
    """Modalidades e turma escolhidas, validadas contra a academia.

    Devolve (modalidade_ids, turma, erro). Academia com uma modalidade só não
    precisa que o candidato escolha: ela vem marcada.
    """
    ids_validos = {m["id"] for m in op["modalidades"]}
    escolhidas = [int(x) for x in form.getlist("modalidade_ids") if str(x).isdigit()
                  and int(x) in ids_validos]
    if not escolhidas and len(ids_validos) == 1:
        escolhidas = list(ids_validos)
    turma = None
    bruto = form.get("turma_id") or form.get("TurmaID")
    if bruto and str(bruto).isdigit():
        turma = next((t for t in op["turmas"] if t["id"] == int(bruto)), None)
        if not turma:
            return escolhidas, None, "Turma inválida."
        # A turma tem que ser de uma modalidade escolhida (turma sem modalidade
        # cadastrada vale para qualquer uma — não dá para saber).
        if turma["modalidades"] and escolhidas and not set(turma["modalidades"]) & set(escolhidas):
            return escolhidas, None, "A turma escolhida não é da modalidade marcada."
        if not escolhidas and turma["modalidades"]:
            escolhidas = [m for m in turma["modalidades"] if m in ids_validos]
    if ids_validos and not escolhidas:
        return escolhidas, turma, "Escolha a modalidade."
    if exigir_turma and op["turmas"] and not turma:
        return escolhidas, None, "Escolha a turma."
    return escolhidas, turma, None


def modalidade_do_link(op, bruto):
    """`?modalidade=<id>` do link enviado pela academia: trava o formulário nela."""
    if bruto and str(bruto).isdigit() and int(bruto) in {m["id"] for m in op["modalidades"]}:
        return int(bruto)
    return None
