# -*- coding: utf-8 -*-
"""Ranking de frequência (presenças em aula) por turma — pódio e listagem completa."""

from collections import defaultdict
from datetime import date, timedelta

MES_COMPLETO = (
    "",
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)

MAX_INTERVALO_DIAS = 400

# Só conta presença se o aluno está matriculado na turma daquela chamada
# (evita visitante/avulso ou presença registrada em turma em que não é aluno).
SQL_MATRICULADO_NA_TURMA_DA_PRESENCA = """(
    EXISTS (
        SELECT 1 FROM aluno_turmas am
        WHERE am.aluno_id = p.aluno_id
          AND am.TurmaID = COALESCE(p.turma_id, a.TurmaID)
    )
    OR (
        NOT EXISTS (SELECT 1 FROM aluno_turmas am2 WHERE am2.aluno_id = p.aluno_id)
        AND a.TurmaID IS NOT NULL
        AND COALESCE(p.turma_id, a.TurmaID) = a.TurmaID
    )
)"""


def _turmas_ids_nomes(turmas_info):
    ids = []
    nomes = {}
    seen_tid = set()
    for t in turmas_info or []:
        tid = t.get("TurmaID") if "TurmaID" in t else t.get("turmaid") or t.get("turma_id")
        if tid is None:
            continue
        tid = int(tid)
        if tid in seen_tid:
            continue
        seen_tid.add(tid)
        ids.append(tid)
        nomes[tid] = (t.get("Nome") or t.get("nome") or "Turma").strip() or "Turma"
    return ids, nomes


def _agrupar_top3(rows):
    """rows: dict com tid, aluno_id, nome, c."""
    full = _agrupar_todos_por_turma(rows)
    result = {}
    for tid, lst in full.items():
        result[tid] = []
        for pos, item in enumerate(lst[:3], 1):
            result[tid].append({**item, "lugar": pos})
    return result


def _agrupar_todos_por_turma(rows):
    """Retorna dict tid -> lista de alunos ordenada por total (com lugar)."""
    by_tid = defaultdict(list)
    for r in rows:
        tid = r.get("tid")
        if tid is None:
            continue
        by_tid[tid].append(
            {
                "aluno_id": r.get("aluno_id"),
                "nome": (r.get("nome") or "").strip() or "—",
                "foto": (r.get("foto") or "").strip() or None,
                "total": int(r.get("c") or 0),
            }
        )
    for tid, lst in by_tid.items():
        lst.sort(key=lambda x: (-x["total"], (x["nome"] or "").lower()))
        for i, item in enumerate(lst, 1):
            item["lugar"] = i
    return dict(by_tid)


def _executar_contagem_presencas(cursor, ids, where_extra, params_extra):
    if not ids:
        return []
    ph = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT COALESCE(p.turma_id, a.TurmaID) AS tid, p.aluno_id,
               MAX(a.nome) AS nome, MAX(a.foto) AS foto, COUNT(*) AS c
        FROM presencas p
        INNER JOIN alunos a ON a.id = p.aluno_id
        WHERE p.presente = 1
          AND COALESCE(p.turma_id, a.TurmaID) IN ({ph})
          AND {SQL_MATRICULADO_NA_TURMA_DA_PRESENCA}
          {where_extra}
        GROUP BY COALESCE(p.turma_id, a.TurmaID), p.aluno_id
        """,
        tuple(ids) + tuple(params_extra),
    )
    return cursor.fetchall()


def ranking_frequencia_por_turmas(
    cursor, turmas_info, ref_date=None, mes=None, ano=None, data_inicio=None, data_fim=None
):
    """
    Pódio (top 3) por turma.
    - Coluna esquerda: mês civil (mes/ano) **ou** intervalo [data_inicio, data_fim] se ambos válidos.
    - Coluna direita: total no ano civil `ano`.
    """
    ref = ref_date or date.today()
    mes = int(mes) if mes is not None else ref.month
    ano = int(ano) if ano is not None else ref.year
    if mes < 1 or mes > 12:
        mes = ref.month
    if ano < 2000 or ano > 2100:
        ano = ref.year

    ids, nomes = _turmas_ids_nomes(turmas_info)
    if not ids:
        return []

    usar_intervalo = (
        data_inicio is not None
        and data_fim is not None
        and isinstance(data_inicio, date)
        and isinstance(data_fim, date)
        and data_inicio <= data_fim
    )
    if usar_intervalo and (data_fim - data_inicio).days > MAX_INTERVALO_DIAS:
        data_fim = data_inicio + timedelta(days=MAX_INTERVALO_DIAS)

    if usar_intervalo:
        where_mes = "AND p.data_presenca BETWEEN %s AND %s"
        params_mes = (data_inicio, data_fim)
        mes_rotulo = f"{data_inicio.strftime('%d/%m/%Y')} – {data_fim.strftime('%d/%m/%Y')}"
    else:
        where_mes = "AND YEAR(p.data_presenca) = %s AND MONTH(p.data_presenca) = %s"
        params_mes = (ano, mes)
        mes_rotulo = f"{MES_COMPLETO[mes].capitalize()} de {ano}"

    rows_mes = _executar_contagem_presencas(cursor, ids, where_mes, params_mes)
    top_mes = _agrupar_top3(rows_mes)

    where_ano = "AND YEAR(p.data_presenca) = %s"
    params_ano = (ano,)
    rows_ano = _executar_contagem_presencas(cursor, ids, where_ano, params_ano)
    top_ano = _agrupar_top3(rows_ano)

    ano_rotulo = str(ano)

    out = []
    for tid in sorted(ids, key=lambda i: (nomes.get(i) or "").lower()):
        out.append(
            {
                "turma_id": tid,
                "turma_nome": nomes.get(tid, "Turma"),
                "mes_rotulo": mes_rotulo,
                "ano_rotulo": ano_rotulo,
                "top3_mes": top_mes.get(tid, []),
                "top3_ano": top_ano.get(tid, []),
            }
        )
    return out


def ranking_completo_por_turmas(
    cursor, turmas_info, ref_date=None, mes=None, ano=None, data_inicio=None, data_fim=None
):
    """
    Mesmos critérios que o pódio, porém lista **todos** os alunos por turma (ordenados por presenças).
    Retorna lista de dicts: turma_id, turma_nome, periodo_rotulo, alunos_periodo, ano_rotulo, alunos_ano.
    """
    ref = ref_date or date.today()
    mes = int(mes) if mes is not None else ref.month
    ano = int(ano) if ano is not None else ref.year
    if mes < 1 or mes > 12:
        mes = ref.month
    if ano < 2000 or ano > 2100:
        ano = ref.year

    ids, nomes = _turmas_ids_nomes(turmas_info)
    if not ids:
        return []

    usar_intervalo = (
        data_inicio is not None
        and data_fim is not None
        and isinstance(data_inicio, date)
        and isinstance(data_fim, date)
        and data_inicio <= data_fim
    )
    if usar_intervalo and (data_fim - data_inicio).days > MAX_INTERVALO_DIAS:
        data_fim = data_inicio + timedelta(days=MAX_INTERVALO_DIAS)

    if usar_intervalo:
        where_mes = "AND p.data_presenca BETWEEN %s AND %s"
        params_mes = (data_inicio, data_fim)
        periodo_rotulo = f"{data_inicio.strftime('%d/%m/%Y')} – {data_fim.strftime('%d/%m/%Y')}"
    else:
        where_mes = "AND YEAR(p.data_presenca) = %s AND MONTH(p.data_presenca) = %s"
        params_mes = (ano, mes)
        periodo_rotulo = f"{MES_COMPLETO[mes].capitalize()} de {ano}"

    rows_p = _executar_contagem_presencas(cursor, ids, where_mes, params_mes)
    alunos_por_turma_p = _agrupar_todos_por_turma(rows_p)

    where_ano = "AND YEAR(p.data_presenca) = %s"
    rows_a = _executar_contagem_presencas(cursor, ids, where_ano, (ano,))
    alunos_por_turma_a = _agrupar_todos_por_turma(rows_a)

    ano_rotulo = str(ano)
    out = []
    for tid in sorted(ids, key=lambda i: (nomes.get(i) or "").lower()):
        out.append(
            {
                "turma_id": tid,
                "turma_nome": nomes.get(tid, "Turma"),
                "periodo_rotulo": periodo_rotulo,
                "alunos_periodo": alunos_por_turma_p.get(tid, []),
                "ano_rotulo": ano_rotulo,
                "alunos_ano": alunos_por_turma_a.get(tid, []),
            }
        )
    return out
