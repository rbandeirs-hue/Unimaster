# -*- coding: utf-8 -*-
"""Régua de cobrança: em QUE DIAS a mensalidade é cobrada no WhatsApp.

O job continua rodando todo dia (`scripts/enviar_lembretes_whatsapp.py`), mas
quem decide se sai mensagem é a régua: para cada mensalidade calcula-se a
distância em dias até o vencimento (negativo antes, 0 no dia, positivo depois) e
só há envio se aquele número for uma etapa ativa da academia.

Duas réguas:
  individual  — o responsável tem menos de `consolidar_apos` mensalidades
                vencidas; cobra-se a mensalidade, com D-5/D-1/D0/D+3...
  consolidada — atingiu o limiar; passa a sair UMA mensagem com todas as
                pendências, contada a partir do dia em que o limiar foi atingido.

Sem nada gravado a academia roda nos padrões abaixo — assim a régua já entra
valendo para todo mundo sem semear tabela, e quem quiser muda na tela.

Tolerante a falha: se as tabelas ainda não existirem (migração não rodada), tudo
cai nos padrões e o sistema segue funcionando.
"""
from datetime import date, timedelta

from config import get_db_connection

# Padrões pedidos pela operação: dois avisos antes, um no dia e o atraso
# espaçado — nada de cobrança diária.
#
# A cobrança acompanha o atraso por até três meses. Antes a régua terminava no
# dia 25: quem passava disso simplesmente parava de ser cobrado, e uma parcela
# vencida há 40 dias ficava em silêncio. Depois do primeiro mês o intervalo
# abre (de 10 em 10, depois de 15 em 15) — continua presente sem virar
# perseguição.
PADRAO_INDIVIDUAL = [-5, -1, 0, 3, 7, 10, 15, 20, 25, 30, 40, 50, 60, 75, 90,
                     105, 120, 135, 150, 165, 180]
# Depois que o responsável acumula pendências, a conversa muda de tom e de
# frequência: uma consolidada na hora e lembretes espaçados, no mesmo horizonte.
PADRAO_CONSOLIDADA = [0, 7, 15, 30, 45, 60, 90, 120, 150, 180]

# Fim da cobrança automática: seis meses após o vencimento. Passou disso, o caso
# é de tratativa humana — insistir por robô não recupera e desgasta.
LIMITE_DIAS = 180

# `tratativa_apos` tira do automático quem acumulou pendências demais. Estava em
# 3, o que anulava a régua longa: quem deve mensalidade há seis meses tem seis
# parcelas vencidas e saía do automático no terceiro mês. Em 7, o inadimplente
# de seis meses continua sendo cobrado, e só quem passa disso vai para a mão da
# secretaria.
PADRAO_CONFIG = {"hora_envio": 9, "consolidar_apos": 2, "tratativa_apos": 7}

ESCOPOS = ("individual", "consolidada")


def rotulo(dias):
    """'5 dias antes', 'No vencimento', '3 dias depois'."""
    dias = int(dias)
    if dias < 0:
        n = abs(dias)
        return f"{n} dia{'s' if n > 1 else ''} antes"
    if dias == 0:
        return "No vencimento"
    return f"{dias} dia{'s' if dias > 1 else ''} depois"


def rotulo_consolidada(dias):
    dias = int(dias)
    if dias <= 0:
        return "Ao atingir o limite"
    return f"{dias} dia{'s' if dias > 1 else ''} depois"


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def _etapas_padrao(escopo):
    base = PADRAO_INDIVIDUAL if escopo == "individual" else PADRAO_CONSOLIDADA
    return [{"id": None, "dias": d, "ativo": True, "mensagem": None, "escopo": escopo}
            for d in base]


def carregar(academia_id, cur=None):
    """Config + etapas da academia, já com os padrões onde não houver nada.

    Devolve {'hora_envio', 'consolidar_apos', 'tratativa_apos',
             'individual': [etapa...], 'consolidada': [etapa...],
             'personalizada': bool}.
    """
    dados = dict(PADRAO_CONFIG)
    dados["individual"] = _etapas_padrao("individual")
    dados["consolidada"] = _etapas_padrao("consolidada")
    dados["personalizada"] = False
    if not academia_id:
        return dados

    proprio = cur is None
    conn = None
    if proprio:
        try:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
        except Exception:
            return dados
    try:
        try:
            cur.execute(
                "SELECT hora_envio, consolidar_apos, tratativa_apos "
                "FROM cobranca_regua_config WHERE id_academia = %s",
                (academia_id,),
            )
            r = cur.fetchone()
            if r:
                dados["hora_envio"] = int(r.get("hora_envio") or 9)
                dados["consolidar_apos"] = max(2, int(r.get("consolidar_apos") or 2))
                dados["tratativa_apos"] = max(0, int(r.get("tratativa_apos") or 0))
        except Exception:
            pass

        try:
            cur.execute(
                "SELECT id, escopo, dias, ativo, mensagem FROM cobranca_regua_etapa "
                "WHERE id_academia = %s ORDER BY dias",
                (academia_id,),
            )
            linhas = cur.fetchall() or []
        except Exception:
            linhas = []
    finally:
        if proprio and conn is not None:
            try:
                cur.close(); conn.close()
            except Exception:
                pass

    for escopo in ESCOPOS:
        do_escopo = [l for l in linhas if (l.get("escopo") or "individual") == escopo]
        if not do_escopo:
            continue
        dados["personalizada"] = True
        dados[escopo] = sorted(
            [{"id": l["id"], "dias": int(l["dias"]), "ativo": bool(l["ativo"]),
              "mensagem": (l.get("mensagem") or None), "escopo": escopo}
             for l in do_escopo],
            key=lambda e: e["dias"],
        )
    return dados


def etapa_do_dia(etapas, dias):
    """A etapa ATIVA cujo dia bate com `dias`, ou None. É o coração da régua:
    não havendo etapa para hoje, não sai mensagem nenhuma."""
    for e in etapas or []:
        if e.get("ativo") and int(e.get("dias")) == int(dias):
            return e
    return None


def dias_ate(vencimento, hoje=None):
    """Dias corridos entre o vencimento e hoje. Negativo = ainda vai vencer."""
    hoje = hoje or date.today()
    if hasattr(vencimento, "date") and not isinstance(vencimento, date):
        vencimento = vencimento.date()
    return (hoje - vencimento).days


def simular(etapas, vencimento, escopo="individual"):
    """Datas em que a régua falaria com o responsável. Alimenta o simulador da
    tela — validar a configuração no papel evita descobrir o erro no cliente."""
    saida = []
    for e in sorted(etapas or [], key=lambda x: x["dias"]):
        if not e.get("ativo"):
            continue
        d = int(e["dias"])
        saida.append({
            "data": vencimento + timedelta(days=d),
            "dias": d,
            "rotulo": rotulo(d) if escopo == "individual" else rotulo_consolidada(d),
            "acao": ("Lembrete" if d < 0 else ("Vencimento" if d == 0 else "Cobrança")),
        })
    return saida


def suspenso(aluno_row, hoje=None):
    """True quando a cobrança automática daquele aluno está pausada.

    Indeterminada (`cobranca_suspensa`) ou com prazo (`cobranca_suspensa_ate`).
    O job continua processando o aluno — só não fala com ele.
    """
    hoje = hoje or date.today()
    if not aluno_row:
        return False
    if aluno_row.get("cobranca_suspensa"):
        return True
    ate = aluno_row.get("cobranca_suspensa_ate")
    if not ate:
        return False
    if hasattr(ate, "date") and not isinstance(ate, date):
        ate = ate.date()
    try:
        return ate >= hoje
    except TypeError:
        return False


# ---------------------------------------------------------------------------
# Escrita (tela de configuração)
# ---------------------------------------------------------------------------
def salvar_config(academia_id, hora_envio, consolidar_apos, tratativa_apos):
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO cobranca_regua_config
                   (id_academia, hora_envio, consolidar_apos, tratativa_apos)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE hora_envio = VALUES(hora_envio),
                                       consolidar_apos = VALUES(consolidar_apos),
                                       tratativa_apos = VALUES(tratativa_apos)""",
            (academia_id, int(hora_envio), int(consolidar_apos), int(tratativa_apos)),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        cur.close(); conn.close()


def salvar_etapas(academia_id, escopo, etapas):
    """Grava a régua inteira daquele escopo (lista de {dias, ativo, mensagem}).

    Regrava tudo em vez de fazer diff: a régua tem meia dúzia de linhas e o
    formulário manda o estado completo, então sincronizar é mais simples — e
    não deixa etapa órfã quando o gestor exclui uma.
    """
    if escopo not in ESCOPOS:
        return False
    limpas = {}
    for e in etapas or []:
        try:
            d = int(e.get("dias"))
        except (TypeError, ValueError):
            continue
        if d < -365 or d > 365:
            continue
        # Mesmo dia duas vezes é a mesma etapa: a última linha vence.
        limpas[d] = {"dias": d, "ativo": 1 if e.get("ativo") else 0,
                     "mensagem": (e.get("mensagem") or "").strip() or None}

    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM cobranca_regua_etapa WHERE id_academia = %s AND escopo = %s",
            (academia_id, escopo),
        )
        for e in limpas.values():
            cur.execute(
                """INSERT INTO cobranca_regua_etapa (id_academia, escopo, dias, ativo, mensagem)
                   VALUES (%s, %s, %s, %s, %s)""",
                (academia_id, escopo, e["dias"], e["ativo"], e["mensagem"]),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        cur.close(); conn.close()
