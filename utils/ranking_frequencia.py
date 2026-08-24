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


def _periodo_ranking(tipo, mes, ano, data_inicio, data_fim):
    """Trecho de WHERE, parâmetros e rótulo do período escolhido."""
    usar_intervalo = (
        tipo == "periodo"
        and isinstance(data_inicio, date)
        and isinstance(data_fim, date)
        and data_inicio <= data_fim
    )
    if usar_intervalo:
        if (data_fim - data_inicio).days > MAX_INTERVALO_DIAS:
            data_fim = data_inicio + timedelta(days=MAX_INTERVALO_DIAS)
        return (
            "AND p.data_presenca BETWEEN %s AND %s",
            (data_inicio, data_fim),
            f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
        )
    if tipo == "ano":
        return "AND YEAR(p.data_presenca) = %s", (ano,), f"Ano de {ano}"
    return (
        "AND YEAR(p.data_presenca) = %s AND MONTH(p.data_presenca) = %s",
        (ano, mes),
        f"{MES_COMPLETO[mes].capitalize()} de {ano}",
    )


ORDENS_RANKING = ("aproveitamento", "periodo", "presencas")


def ordem_ranking_padrao(tipo: str) -> str:
    """No mês, aproveitamento; em recortes longos, número de presenças.

    Num mês o aproveitamento é justo: quem entrou no dia 20 comparece a poucas
    chamadas e não deve ser punido por aulas anteriores à matrícula.

    Num período de vários meses qualquer percentual distorce, porque o
    denominador muda de aluno para aluno: dois treinos em duas chamadas dão
    100% e passam à frente de quem treina desde o começo. Trocar o denominador
    pelas chamadas da turma ajuda, mas ainda compara turmas que tiveram 2
    chamadas com turmas que tiveram 90. Só a contagem de presenças é
    diretamente comparável entre todos — por isso ela é o padrão aqui.
    """
    return "aproveitamento" if tipo == "mes" else "presencas"


def ranking_frequencia_geral(
    cursor, turmas_info, tipo="mes", mes=None, ano=None, data_inicio=None,
    data_fim=None, ordenar=None
):
    """Ranking único do período. `ordenar` escolhe o critério da classificação.

    Diferente do pódio por turma, aqui todas as turmas do escopo entram em uma
    lista só — é a leitura que a tela da academia usa.

    Cada aluno sai com duas medidas, porque elas respondem perguntas
    diferentes:

    * `frequencia` (aproveitamento) — presenças ÷ chamadas em que o aluno
      estava matriculado. Mede assiduidade de quem está lá: quem entrou no meio
      do período não é penalizado por aulas anteriores à matrícula.
    * `frequencia_periodo` — presenças ÷ todas as chamadas das turmas dele no
      período. Mede presença sobre o período inteiro, e é o que permite
      comparar um veterano com um recém-chegado.

    `ordenar`: "aproveitamento", "periodo" ou "presencas" (contagem absoluta).
    """
    ref = date.today()
    mes = int(mes) if mes is not None else ref.month
    ano = int(ano) if ano is not None else ref.year
    if mes < 1 or mes > 12:
        mes = ref.month
    if ano < 2000 or ano > 2100:
        ano = ref.year

    where_periodo, params_periodo, periodo_rotulo = _periodo_ranking(
        tipo, mes, ano, data_inicio, data_fim
    )

    vazio = {
        "periodo_rotulo": periodo_rotulo,
        "ordenar": ordenar if ordenar in ORDENS_RANKING else ordem_ranking_padrao(tipo),
        "aulas": 0,
        "presencas": 0,
        "faltas": 0,
        "frequencia_media": 0,
        "alunos": [],
        "turmas": [],
        "abaixo_60": [],
        "faixas": [],
    }

    ids, nomes = _turmas_ids_nomes(turmas_info)
    if not ids:
        return vazio

    ph = ",".join(["%s"] * len(ids))
    base_where = f"""
        WHERE COALESCE(p.turma_id, a.TurmaID) IN ({ph})
          AND {SQL_MATRICULADO_NA_TURMA_DA_PRESENCA}
          {where_periodo}
    """
    params = tuple(ids) + tuple(params_periodo)

    # Uma linha por aluno em cada turma em que ele teve chamada no período.
    cursor.execute(
        f"""
        SELECT COALESCE(p.turma_id, a.TurmaID) AS tid, p.aluno_id,
               MAX(a.nome) AS nome, MAX(a.foto) AS foto,
               COUNT(*) AS aulas, SUM(p.presente = 1) AS presencas
        FROM presencas p
        INNER JOIN alunos a ON a.id = p.aluno_id
        {base_where}
        GROUP BY COALESCE(p.turma_id, a.TurmaID), p.aluno_id
        """,
        params,
    )
    linhas = cursor.fetchall()

    # Chamadas do período por turma: dias distintos com registro.
    cursor.execute(
        f"""
        SELECT COALESCE(p.turma_id, a.TurmaID) AS tid,
               COUNT(DISTINCT p.data_presenca) AS chamadas
        FROM presencas p
        INNER JOIN alunos a ON a.id = p.aluno_id
        {base_where}
        GROUP BY COALESCE(p.turma_id, a.TurmaID)
        """,
        params,
    )
    chamadas_por_turma = {r["tid"]: int(r["chamadas"] or 0) for r in cursor.fetchall()}

    # O aluno pode treinar em mais de uma turma: os números somam, e a turma
    # exibida é aquela em que ele mais teve chamada no período.
    por_aluno = {}
    por_turma = defaultdict(lambda: {"aulas": 0, "presencas": 0, "alunos": set()})
    for r in linhas:
        tid = r.get("tid")
        aid = r.get("aluno_id")
        if tid is None or aid is None:
            continue
        aulas = int(r.get("aulas") or 0)
        presencas = int(r.get("presencas") or 0)
        if aulas <= 0:
            continue

        bloco = por_turma[tid]
        bloco["aulas"] += aulas
        bloco["presencas"] += presencas
        bloco["alunos"].add(aid)

        item = por_aluno.get(aid)
        if item is None:
            item = {
                "aluno_id": aid,
                "nome": (r.get("nome") or "").strip() or "—",
                "foto": (r.get("foto") or "").strip() or None,
                "aulas": 0,
                "presencas": 0,
                "turma_id": tid,
                "turma_nome": nomes.get(tid, "Turma"),
                "_aulas_turma_principal": 0,
                "_turmas": set(),
            }
            por_aluno[aid] = item
        item["aulas"] += aulas
        item["presencas"] += presencas
        item["_turmas"].add(tid)
        if aulas > item["_aulas_turma_principal"]:
            item["_aulas_turma_principal"] = aulas
            item["turma_id"] = tid
            item["turma_nome"] = nomes.get(tid, "Turma")

    ordenar = ordenar if ordenar in ORDENS_RANKING else ordem_ranking_padrao(tipo)

    alunos = []
    for item in por_aluno.values():
        item.pop("_aulas_turma_principal", None)
        turmas_do_aluno = item.pop("_turmas", set())
        item["faltas"] = item["aulas"] - item["presencas"]
        item["frequencia"] = round(item["presencas"] * 100 / item["aulas"])
        # Denominador do período: todas as chamadas das turmas onde ele treina,
        # inclusive as anteriores à matrícula dele.
        chamadas_periodo = sum(chamadas_por_turma.get(t, 0) for t in turmas_do_aluno)
        item["chamadas_periodo"] = chamadas_periodo
        item["frequencia_periodo"] = (
            round(item["presencas"] * 100 / chamadas_periodo) if chamadas_periodo else 0
        )
        alunos.append(item)

    # Empates caem no critério seguinte mais informativo: mais presenças, e
    # depois melhor aproveitamento.
    ordens = {
        "aproveitamento": lambda x: (-x["frequencia"], -x["presencas"], (x["nome"] or "").lower()),
        "periodo": lambda x: (-x["frequencia_periodo"], -x["presencas"], (x["nome"] or "").lower()),
        "presencas": lambda x: (-x["presencas"], -x["frequencia_periodo"], (x["nome"] or "").lower()),
    }
    alunos.sort(key=ordens[ordenar])
    for pos, item in enumerate(alunos, 1):
        item["lugar"] = pos

    turmas = []
    for tid, bloco in por_turma.items():
        if not bloco["aulas"]:
            continue
        turmas.append(
            {
                "turma_id": tid,
                "turma_nome": nomes.get(tid, "Turma"),
                "chamadas": chamadas_por_turma.get(tid, 0),
                "alunos": len(bloco["alunos"]),
                "presencas": bloco["presencas"],
                "frequencia_media": round(bloco["presencas"] * 100 / bloco["aulas"]),
            }
        )
    turmas.sort(key=lambda t: (-t["frequencia_media"], (t["turma_nome"] or "").lower()))

    total_aulas = sum(i["aulas"] for i in alunos)
    total_presencas = sum(i["presencas"] for i in alunos)
    # Mesmos cortes de cor usados no histórico de presença.
    faixas = [
        ("90% ou mais", "alta", lambda f: f >= 90),
        ("70% a 89%", "alta", lambda f: 70 <= f < 90),
        ("60% a 69%", "media", lambda f: 60 <= f < 70),
        ("Abaixo de 60%", "baixa", lambda f: f < 60),
    ]
    return {
        "periodo_rotulo": periodo_rotulo,
        "ordenar": ordenar,
        "aulas": sum(chamadas_por_turma.values()),
        "presencas": total_presencas,
        "faltas": total_aulas - total_presencas,
        "frequencia_media": round(total_presencas * 100 / total_aulas) if total_aulas else 0,
        "alunos": alunos,
        "turmas": turmas,
        # Lista de cobrança: quem está pior aparece primeiro.
        "abaixo_60": sorted(
            (i for i in alunos if i["frequencia"] < 60),
            key=lambda i: (i["frequencia"], (i["nome"] or "").lower()),
        ),
        "faixas": [
            {
                "rotulo": rotulo,
                "tom": tom,
                "alunos": sum(1 for i in alunos if teste(i["frequencia"])),
            }
            for rotulo, tom, teste in faixas
        ],
    }


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
