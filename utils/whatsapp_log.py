"""
Log de envios de WhatsApp — alimenta o painel da academia.

Uma linha por destinatário em `whatsapp_log`, agrupável por `lote_id` (um
disparo em massa). Tudo é best-effort: registrar nunca deve quebrar um envio,
e as consultas devolvem zeros/vazio se a tabela não existir.
"""

from datetime import date

try:
    from db import get_db_connection
except Exception:  # pragma: no cover
    from app import get_db_connection


# Rótulos amigáveis por tipo (para a lista "Últimos envios").
LABELS = {
    "lembrete_vencimento": "Lembrete de mensalidade",
    "lembrete_atraso": "Mensalidade em atraso",
    "confirmacao_pagamento": "Confirmação de pagamento",
    "aniversario": "Parabéns de aniversário",
    "boas_vindas": "Boas-vindas",
    "matricula": "Matrícula confirmada",
    "confirmacao_matricula": "Pagamento da matrícula confirmado",
    "aviso": "Aviso geral",
    "teste": "Mensagem de teste",
}


def rotulo(tipo):
    return LABELS.get(tipo, (tipo or "Mensagem").replace("_", " ").capitalize())


def registrar(academia_id, tipo, status, aluno_id=None, telefone=None,
              erro=None, lote_id=None, cur=None, conn=None):
    """Registra um envio. Se `cur`/`conn` vierem, usa a transação corrente
    (sem commit); senão abre conexão própria e comita. Nunca levanta."""
    if not academia_id or not tipo or not status:
        return
    sql = (
        "INSERT INTO whatsapp_log (id_academia, tipo, lote_id, aluno_id, telefone, status, erro) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)"
    )
    args = (academia_id, tipo, lote_id, aluno_id, telefone,
            (status or "")[:20], (erro or None) and str(erro)[:255])
    try:
        if cur is not None:
            cur.execute(sql, args)
            return
        c = conn or get_db_connection()
        own = conn is None
        cu = c.cursor()
        cu.execute(sql, args)
        if own:
            c.commit()
            cu.close()
            c.close()
    except Exception:
        pass


def registrar_resumo(academia_id, tipo, resumo, lote_id=None):
    """Grava um lote a partir do resumo {enviados, falhas, sem_telefone} das
    funções de envio (que não expõem cada destinatário). Cria N linhas
    sintéticas para o painel refletir os totais."""
    if not academia_id or not resumo:
        return
    try:
        c = get_db_connection()
        cu = c.cursor()
        for _ in range(int(resumo.get("enviados") or 0)):
            cu.execute(
                "INSERT INTO whatsapp_log (id_academia, tipo, lote_id, status) VALUES (%s,%s,%s,'entregue')",
                (academia_id, tipo, lote_id),
            )
        for _ in range(int(resumo.get("falhas") or 0)):
            cu.execute(
                "INSERT INTO whatsapp_log (id_academia, tipo, lote_id, status) VALUES (%s,%s,%s,'falha')",
                (academia_id, tipo, lote_id),
            )
        for _ in range(int(resumo.get("sem_telefone") or 0)):
            cu.execute(
                "INSERT INTO whatsapp_log (id_academia, tipo, lote_id, status) VALUES (%s,%s,%s,'sem_numero')",
                (academia_id, tipo, lote_id),
            )
        c.commit()
        cu.close()
        c.close()
    except Exception:
        pass


def resumo_mes(academia_id, ano=None, mes=None):
    """Totais do mês: {total, entregues, falhas, pct_entregue}."""
    hoje = date.today()
    ano = ano or hoje.year
    mes = mes or hoje.month
    base = {"total": 0, "entregues": 0, "falhas": 0, "pct_entregue": 0}
    try:
        c = get_db_connection()
        cu = c.cursor(dictionary=True)
        cu.execute(
            """SELECT
                 SUM(status IN ('entregue','falha')) AS total,
                 SUM(status = 'entregue') AS entregues,
                 SUM(status = 'falha') AS falhas
               FROM whatsapp_log
               WHERE id_academia=%s AND YEAR(criado_em)=%s AND MONTH(criado_em)=%s""",
            (academia_id, ano, mes),
        )
        r = cu.fetchone() or {}
        cu.close()
        c.close()
    except Exception:
        return base
    total = int(r.get("total") or 0)
    entregues = int(r.get("entregues") or 0)
    falhas = int(r.get("falhas") or 0)
    return {
        "total": total,
        "entregues": entregues,
        "falhas": falhas,
        "pct_entregue": round(entregues * 100 / total) if total else 0,
    }


def ultimos_lotes(academia_id, limite=6):
    """Últimos disparos agrupados por (tipo, lote/minuto): lista de dicts com
    tipo, label, criado_em, total, entregues, falhas."""
    out = []
    try:
        c = get_db_connection()
        cu = c.cursor(dictionary=True)
        # Agrupa por lote quando houver; senão, por tipo+minuto (envios avulsos).
        cu.execute(
            """SELECT tipo,
                      COALESCE(lote_id, CONCAT(tipo,'@',DATE_FORMAT(criado_em,'%%Y%%m%%d%%H%%i'))) AS chave,
                      MAX(criado_em) AS criado_em,
                      COUNT(*) AS total,
                      SUM(status='entregue') AS entregues,
                      SUM(status='falha') AS falhas
               FROM whatsapp_log
               WHERE id_academia=%s
               GROUP BY tipo, chave
               ORDER BY criado_em DESC
               LIMIT %s""",
            (academia_id, int(limite)),
        )
        for r in cu.fetchall():
            out.append({
                "tipo": r["tipo"],
                "label": rotulo(r["tipo"]),
                "criado_em": r["criado_em"],
                "total": int(r.get("total") or 0),
                "entregues": int(r.get("entregues") or 0),
                "falhas": int(r.get("falhas") or 0),
            })
        cu.close()
        c.close()
    except Exception:
        return []
    return out


def ultimo_por_tipo(academia_id):
    """{tipo: {criado_em, total}} do disparo mais recente de cada tipo — usado
    no rótulo 'Último envio' de cada automação."""
    out = {}
    try:
        c = get_db_connection()
        cu = c.cursor(dictionary=True)
        cu.execute(
            """SELECT tipo, MAX(criado_em) AS criado_em
               FROM whatsapp_log WHERE id_academia=%s GROUP BY tipo""",
            (academia_id,),
        )
        rows = cu.fetchall()
        for r in rows:
            cu.execute(
                """SELECT COUNT(*) AS total FROM whatsapp_log
                   WHERE id_academia=%s AND tipo=%s
                     AND criado_em >= (SELECT MAX(criado_em) FROM whatsapp_log WHERE id_academia=%s AND tipo=%s) - INTERVAL 5 MINUTE""",
                (academia_id, r["tipo"], academia_id, r["tipo"]),
            )
            tot = (cu.fetchone() or {}).get("total") or 0
            out[r["tipo"]] = {"criado_em": r["criado_em"], "total": int(tot)}
        cu.close()
        c.close()
    except Exception:
        return {}
    return out
