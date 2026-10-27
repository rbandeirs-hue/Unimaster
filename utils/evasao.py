"""Alerta de evasão: alunos ativos que pararam de treinar ou estão vindo menos.

O aluno some do tatame semanas antes de cancelar a matrícula. Avisar a
academia nesse intervalo — e dar o WhatsApp à mão — é o que dá chance de
trazê-lo de volta.

Critério, por academia (só presenças em turmas DESTA academia):
  base   = presenças nos 60 dias anteriores aos últimos 30 (do dia 31 ao 90)
  ult30  = presenças nos últimos 30 dias
  esperado em 30 dias = base / 2

  sumiu   — treinava (base >= 2) e não veio nenhuma vez nos últimos 30 dias
  caindo  — vinha com regularidade (esperado >= 4) e agora veio no máximo a
            metade do esperado

Só entra aluno ativo, vinculado à academia (principal ou adicional).
"""
from datetime import date, timedelta

JANELA = 30
BASE_DIAS = 60
MIN_BASE_SUMIU = 2
MIN_ESPERADO_CAINDO = 4


def alunos_em_risco(cur, academia_id, hoje=None):
    hoje = hoje or date.today()
    ini_ult = hoje - timedelta(days=JANELA)
    ini_base = ini_ult - timedelta(days=BASE_DIAS)
    cur.execute(
        """SELECT a.id, a.nome, a.foto, a.data_nascimento,
                  COALESCE(NULLIF(a.tel_celular, ''), NULLIF(a.telefone, ''),
                           NULLIF(a.responsavel_financeiro_telefone, '')) AS telefone,
                  a.responsavel_nome,
                  SUM(p.data_presenca >= %s) AS ult30,
                  SUM(p.data_presenca < %s) AS base,
                  MAX(p.data_presenca) AS ultima
           FROM alunos a
           JOIN presencas p ON p.aluno_id = a.id AND p.presente = 1
                            AND p.data_presenca >= %s AND p.data_presenca <= %s
           JOIN turmas t ON t.TurmaID = p.turma_id AND t.id_academia = %s
           WHERE COALESCE(a.ativo, 1) = 1 AND COALESCE(a.status, 'ativo') <> 'inativo'
             AND (a.id_academia = %s OR EXISTS (
                  SELECT 1 FROM alunos_academias aa WHERE aa.aluno_id = a.id AND aa.academia_id = %s))
           GROUP BY a.id, a.nome, a.foto, a.data_nascimento, telefone, a.responsavel_nome""",
        (ini_ult, ini_ult, ini_base, hoje, academia_id, academia_id, academia_id))
    out = []
    for r in cur.fetchall():
        ult30, base = int(r["ult30"] or 0), int(r["base"] or 0)
        esperado = base / (BASE_DIAS / JANELA)
        if ult30 == 0 and base >= MIN_BASE_SUMIU:
            nivel = "sumiu"
        elif esperado >= MIN_ESPERADO_CAINDO and ult30 <= esperado / 2:
            nivel = "caindo"
        else:
            continue
        r.update(ult30=ult30, base=base, esperado=round(esperado, 1), nivel=nivel,
                 dias_sem_vir=(hoje - r["ultima"]).days if r["ultima"] else None,
                 whatsapp=_whatsapp(r["telefone"]))
        out.append(r)
    # Quem sumiu primeiro, e entre eles quem está há mais tempo sem vir.
    out.sort(key=lambda r: (r["nivel"] != "sumiu", -(r["dias_sem_vir"] or 0)))
    return out


def resumo(cur, academia_id):
    lista = alunos_em_risco(cur, academia_id)
    return {"total": len(lista),
            "sumiu": sum(1 for r in lista if r["nivel"] == "sumiu"),
            "caindo": sum(1 for r in lista if r["nivel"] == "caindo")}


def _whatsapp(tel):
    d = "".join(ch for ch in str(tel or "") if ch.isdigit())
    if len(d) in (10, 11):
        d = "55" + d
    return d if len(d) >= 12 else None
