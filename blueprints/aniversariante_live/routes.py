# -*- coding: utf-8 -*-
"""Modo aniversariante estilo live: JSON + página SPA (parabéns e reações sem texto livre)."""
import calendar
from datetime import date, datetime
from typing import Optional

from flask import Blueprint, current_app, jsonify, render_template, request, session, url_for
from flask_login import current_user, login_required

from config import get_db_connection

# Reutiliza regras de acesso do chat de aniversário (staff / colega / próprio aluno).
import blueprints.aniversario_mensagens as aniv_msg

bp_aniversariante_live = Blueprint(
    "aniversariante_live",
    __name__,
    url_prefix="/aniversariante-live",
)

ACOES_PERMITIDAS = frozenset({"parabens", "heart", "cake", "party", "clap"})

ACAO_EMOJI = {
    "parabens": "🎉",
    "heart": "❤️",
    "cake": "🎂",
    "party": "🥳",
    "clap": "👏",
}


def _ref_mes_ano_default():
    hoje = date.today()
    return f"{hoje.year}-{hoje.month:02d}"


def _parse_data_nascimento(data_nascimento):
    """Retorna datetime.date ou None (normaliza datetime do MySQL)."""
    if not data_nascimento:
        return None
    try:
        if isinstance(data_nascimento, str):
            return datetime.strptime(data_nascimento[:10], "%Y-%m-%d").date()
        if isinstance(data_nascimento, datetime):
            return data_nascimento.date()
        if isinstance(data_nascimento, date):
            return data_nascimento
    except Exception:
        return None
    return None


_MESES_PT = (
    "",
    "jan.",
    "fev.",
    "mar.",
    "abr.",
    "mai.",
    "jun.",
    "jul.",
    "ago.",
    "set.",
    "out.",
    "nov.",
    "dez.",
)


def _texto_dia_mes_aniversario(data_nascimento) -> str:
    """Ex.: '10 de mai.' — sem ano."""
    nasc = _parse_data_nascimento(data_nascimento)
    if not nasc:
        return ""
    return f"{nasc.day} de {_MESES_PT[nasc.month]}"


def _dia_aniversario_em_ano(nasc: date, ano: int) -> date:
    """Data do aniversário (mês/dia do nascimento) no ano informado."""
    try:
        return date(ano, nasc.month, nasc.day)
    except ValueError:
        if nasc.month == 2 and nasc.day == 29:
            return date(ano, 2, 28)
        raise


def _pode_enviar_parabens_desde_anchor_ref(data_nascimento, ref_mes_ano: str) -> bool:
    """
    Libera parabéns/reações no dia do aniversário e também para quem já passou
    (no mês da lista, ou em meses anteriores do ano de referência).
    Aniversários futuros ficam bloqueados.
    """
    nasc = _parse_data_nascimento(data_nascimento)
    if not nasc or not aniv_msg._ref_mes_ano_ok(ref_mes_ano):
        return False
    try:
        y_ref = int(ref_mes_ano[:4])
        m_ref = int(ref_mes_ano[5:7])
    except (TypeError, ValueError, IndexError):
        return False
    if m_ref < 1 or m_ref > 12:
        return False

    today = date.today()
    anchor = _dia_aniversario_em_ano(nasc, y_ref)

    # Mês de referência no passado (ex.: olhando lista de janeiro em março): já passou
    if today.year > y_ref or (today.year == y_ref and today.month > m_ref):
        return True
    # Mês de referência no futuro: ainda não chegou
    if today.year < y_ref or (today.year == y_ref and today.month < m_ref):
        return False
    # Mesmo mês: liberado se hoje for >= dia do aniversário
    return today >= anchor


def _foto_url(foto):
    if not foto:
        return None
    try:
        return url_for("static", filename=f"uploads/{foto}")
    except Exception:
        return f"/static/uploads/{foto}"


def _get_academias_ids():
    from blueprints.academia.routes import _get_academias_ids as _g

    return _g() or []


def _academias_ids_toda_associacao():
    """
    Todas as academias vinculadas à associação do usuário (por id_associacao).

    Não usa usuarios_academias — o gestor da associação vê aniversariantes de
    todas as academias da entidade, alinhado ao painel da associação.
    """
    id_assoc = getattr(current_user, "id_associacao", None)
    if not id_assoc:
        return []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome",
            (id_assoc,),
        )
        return [r["id"] for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def _listar_aniversariantes_mes(mes: int, aluno_escopo: Optional[int] = None):
    """Lista de dicts conforme papel e session['modo_painel'] (aluno / professor / academia / responsável)."""
    from utils.aniversariantes import (
        aniversariantes_do_mes,
        aniversariantes_do_mes_aluno_associacao,
        aniversariantes_do_mes_associacao,
        aniversariantes_do_mes_professor_ampliado,
        aniversariantes_do_mes_por_aluno_id,
    )

    def _sort_rows(rows):
        return sorted(
            rows or [],
            key=lambda x: (
                x["data_nascimento"].day if getattr(x.get("data_nascimento"), "day", None) else 0,
                (x.get("nome") or "").lower(),
            ),
        )

    modo = (session.get("modo_painel") or "").strip()
    ids = _get_academias_ids()

    # Modo responsável: mesma lista que o aluno vinculado veria (turmas em comum); exige ?aluno_id= na live
    if modo == "responsavel" and current_user.has_role("responsavel"):
        if not aluno_escopo:
            return []
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """
                SELECT 1 FROM responsavel_alunos ra
                INNER JOIN alunos a ON a.id = ra.aluno_id AND a.ativo = 1
                WHERE ra.usuario_id = %s AND ra.aluno_id = %s
                LIMIT 1
                """,
                (int(current_user.id), int(aluno_escopo)),
            )
            if not cur.fetchone():
                return []
        finally:
            cur.close()
            conn.close()
        return _sort_rows(aniversariantes_do_mes_por_aluno_id(int(aluno_escopo), mes=mes) or [])

    # Modo aluno: aniversariantes de todas as academias da associação do aluno
    if modo == "aluno" and current_user.has_role("aluno"):
        return _sort_rows(aniversariantes_do_mes_aluno_associacao(current_user.id, mes=mes) or [])

    # Admin e gestor de federação: todas as academias do escopo
    if current_user.has_role("admin") or current_user.has_role("gestor_federacao"):
        if not ids:
            return []
        out = {}
        for aid in ids:
            for row in aniversariantes_do_mes(current_user.id, "academia", mes=mes, academia_id=aid) or []:
                out[row["id"]] = row
        return _sort_rows(list(out.values()))

    # Modo academia: gestor vê só a academia ativa no painel
    if (
        modo == "academia"
        and current_user.has_role("gestor_academia")
        and not current_user.has_role("admin")
    ):
        from blueprints.academia.routes import _get_academia_gerenciamento

        aid, _ = _get_academia_gerenciamento()
        if not aid and ids:
            aid = ids[0]
        if not aid:
            return []
        return _sort_rows(aniversariantes_do_mes(current_user.id, "academia", mes=mes, academia_id=aid))

    # Gestor de academia em outros modos: mescla academias do escopo (comportamento anterior)
    if current_user.has_role("gestor_academia") and not current_user.has_role("admin"):
        if not ids:
            return []
        out = {}
        for aid in ids:
            for row in aniversariantes_do_mes(current_user.id, "academia", mes=mes, academia_id=aid) or []:
                out[row["id"]] = row
        return _sort_rows(list(out.values()))

    if current_user.has_role("gestor_associacao"):
        assoc_ids = _academias_ids_toda_associacao()
        if not assoc_ids:
            return []
        return _sort_rows(aniversariantes_do_mes_associacao(assoc_ids, mes=mes))

    # Professor: todas as academias onde leciona (alunos ativos do mês, não só da turma)
    if current_user.has_role("professor"):
        return _sort_rows(
            aniversariantes_do_mes_professor_ampliado(current_user.id, mes=mes) or []
        )

    if current_user.has_role("aluno"):
        return _sort_rows(aniversariantes_do_mes_aluno_associacao(current_user.id, mes=mes) or [])

    return []


def _responsavel_pode_interagir_live(cur, aluno_destino_id: int, ref: str) -> bool:
    """Responsável pode ver/participar da live dos colegas de turma dos filhos vinculados (ou do próprio filho)."""
    if not current_user.has_role("responsavel"):
        return False
    if not aniv_msg._ref_mes_ano_ok(ref):
        return False
    try:
        mes = int(ref[5:7])
    except (ValueError, IndexError):
        return False
    cur.execute(
        """
        SELECT ra.aluno_id FROM responsavel_alunos ra
        INNER JOIN alunos a ON a.id = ra.aluno_id AND a.ativo = 1
        WHERE ra.usuario_id = %s
        """,
        (int(current_user.id),),
    )
    vinculos = [int(r["aluno_id"]) for r in (cur.fetchall() or [])]
    if not vinculos:
        return False
    if aluno_destino_id in vinculos:
        return True
    from utils.aniversariantes import aniversariantes_do_mes_por_aluno_id

    for vid in vinculos:
        for row in aniversariantes_do_mes_por_aluno_id(vid, mes=mes) or []:
            if int(row.get("id") or 0) == aluno_destino_id:
                return True
    return False


def _pode_interagir_aluno(cur, aluno_id: int, ref: str) -> bool:
    if not aniv_msg._ref_mes_ano_ok(ref):
        return False
    ok_staff, _ = aniv_msg._staff_may_access_aluno(cur, aluno_id)
    if ok_staff:
        return True
    if _responsavel_pode_interagir_live(cur, aluno_id, ref):
        return True
    if aniv_msg._aluno_eh_proprio(cur, aluno_id):
        return True
    colega_ctx = aniv_msg._ids_colegas_aniversariantes_mes(ref)
    cur.execute("SELECT id FROM alunos WHERE usuario_id = %s LIMIT 1", (current_user.id,))
    row_me = cur.fetchone()
    me_aid = int(row_me["id"]) if row_me and row_me.get("id") is not None else None
    return (
        me_aid is not None
        and me_aid in colega_ctx
        and aluno_id in colega_ctx
        and aluno_id != me_aid
    )


def _tabela_live_existe(cur) -> bool:
    try:
        cur.execute("SELECT 1 FROM aniversario_live_eventos LIMIT 1")
        cur.fetchone()
        return True
    except Exception as exc:
        err_s = str(exc).lower()
        errno = getattr(exc, "errno", None)
        missing = errno == 1146 or (
            "aniversario_live_eventos" in err_s
            and ("doesn't exist" in err_s or "does not exist" in err_s or "unknown table" in err_s)
        )
        if missing:
            return False
        raise


def _serialize_evento(r: dict) -> dict:
    uid = r.get("usuario_id")
    nome = r.get("autor_nome") or "Alguém"
    acao = (r.get("acao") or "parabens").lower()
    emoji = ACAO_EMOJI.get(acao, "🎉")
    if acao == "parabens":
        texto = f"{nome} enviou parabéns {emoji}"
    else:
        texto = f"{nome} reagiu {emoji}"
    ce = r.get("criado_em")
    if hasattr(ce, "isoformat"):
        criado_em = ce.isoformat(sep=" ", timespec="seconds")
    else:
        criado_em = str(ce) if ce else ""
    return {
        "id": r.get("id"),
        "aluno_id": r.get("aluno_id"),
        "usuario_id": uid,
        "autor_nome": nome,
        "autor_foto_url": _foto_url(r.get("autor_foto")),
        "acao": acao,
        "emoji": emoji,
        "texto": texto,
        "criado_em": criado_em,
    }


def _voltar_painel_url_seguro():
    """Destino do botão Voltar: ?next= (path interno) ou painel."""
    nxt = (request.args.get("next") or "").strip()
    if (
        nxt.startswith("/")
        and not nxt.startswith("//")
        and not nxt.startswith("/aniversariante-live")
    ):
        return nxt
    return url_for("painel.home")


_MESES_NOMES = (
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)

# Rótulo de cada reação na tela da academia — o backend continua guardando a
# chave curta (heart, cake…), aqui só se dá nome a ela para quem lê.
REACOES_PAINEL = (
    ("clap", "Força e saúde", "bi-hand-thumbs-up"),
    ("party", "Comemorações", "bi-balloon"),
    ("cake", "Bom treino", "bi-award"),
    ("heart", "Carinho", "bi-heart"),
)


def _iniciais(nome: str) -> str:
    partes = (nome or "?").split()
    if not partes:
        return "?"
    return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()


def _idade_no_aniversario(nasc, ano: int):
    """Idade que a pessoa completa (ou completou) no aniversário do ano dado."""
    if not nasc:
        return None
    return ano - nasc.year


def _usuario_eh_staff_academia() -> bool:
    return bool(
        current_user.has_role("gestor_academia")
        or current_user.has_role("admin")
        or current_user.has_role("professor")
        or current_user.has_role("gestor_associacao")
        or current_user.has_role("gestor_federacao")
    )


def _academia_do_painel():
    from blueprints.academia.routes import _get_academia_gerenciamento

    try:
        aid, _ = _get_academia_gerenciamento()
        return aid
    except Exception:
        return None


def _parabenizados_por_whatsapp(cur, academia_id, ano: int, mes: int) -> dict:
    """{aluno_id: data do último parabéns enviado} a partir de whatsapp_envios.

    A tabela pode não existir (migração não rodada): nesse caso a tela mostra
    todo mundo como não parabenizado, em vez de deixar de abrir.
    """
    if not academia_id:
        return {}
    try:
        cur.execute(
            """SELECT referencia_id, MAX(data_ref) AS ultima
               FROM whatsapp_envios
               WHERE id_academia = %s AND tipo = 'aniversario'
                 AND YEAR(data_ref) = %s AND MONTH(data_ref) = %s
               GROUP BY referencia_id""",
            (academia_id, ano, mes),
        )
        return {int(r["referencia_id"]): r["ultima"] for r in cur.fetchall() or []}
    except Exception:
        return {}


def _contagem_parabens_live(cur, ref: str, ids) -> dict:
    """{aluno_id: nº de parabéns publicados na página do aniversariante}."""
    if not ids:
        return {}
    try:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            f"""SELECT aluno_id, COUNT(*) AS c FROM aniversario_live_eventos
                WHERE ref_mes_ano = %s AND acao = 'parabens' AND aluno_id IN ({ph})
                GROUP BY aluno_id""",
            (ref,) + tuple(ids),
        )
        return {int(r["aluno_id"]): int(r["c"] or 0) for r in cur.fetchall() or []}
    except Exception:
        return {}


def _detalhe_aluno_painel(cur, aluno_id: int, ref: str):
    """Ficha do aniversariante selecionado: contato, mural e reações."""
    cur.execute(
        """SELECT a.id, a.nome, a.foto, a.data_nascimento, a.id_academia,
                  a.telefone, a.tel_celular,
                  a.responsavel_nome, a.responsavel_parentesco,
                  a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone,
                  GROUP_CONCAT(t.Nome ORDER BY t.Nome SEPARATOR ', ') AS turmas
           FROM alunos a
           LEFT JOIN aluno_turmas at2 ON at2.aluno_id = a.id
           LEFT JOIN turmas t ON t.TurmaID = at2.TurmaID
           WHERE a.id = %s AND COALESCE(a.ativo, 1) = 1
           GROUP BY a.id""",
        (aluno_id,),
    )
    row = cur.fetchone()
    if not row:
        return None

    reacoes, mural, total_parabens = [], [], 0
    try:
        cur.execute(
            """SELECT acao, COUNT(*) AS c FROM aniversario_live_eventos
               WHERE aluno_id = %s AND ref_mes_ano = %s GROUP BY acao""",
            (aluno_id, ref),
        )
        por_acao = {(r["acao"] or "").lower(): int(r["c"] or 0) for r in cur.fetchall() or []}
        total_parabens = por_acao.get("parabens", 0)
        reacoes = [
            {"chave": k, "rotulo": rot, "icone": ic, "total": por_acao.get(k, 0)}
            for k, rot, ic in REACOES_PAINEL
        ]
    except Exception:
        reacoes = [
            {"chave": k, "rotulo": rot, "icone": ic, "total": 0}
            for k, rot, ic in REACOES_PAINEL
        ]

    try:
        cur.execute(
            """SELECT m.id, m.corpo, m.remetente, m.criado_em, u.nome AS autor_nome,
                      u.perfil AS autor_perfil
               FROM aniversario_mensagens m
               LEFT JOIN usuarios u ON u.id = m.usuario_id
               WHERE m.aluno_id = %s AND m.ref_mes_ano = %s
               ORDER BY m.criado_em DESC, m.id DESC
               LIMIT 40""",
            (aluno_id, ref),
        )
        mural = cur.fetchall() or []
    except Exception:
        mural = []

    telefone = (
        (row.get("responsavel_financeiro_telefone") or "").strip()
        or (row.get("tel_celular") or "").strip()
        or (row.get("telefone") or "").strip()
    )
    responsavel = (
        (row.get("responsavel_financeiro_nome") or "").strip()
        or (row.get("responsavel_nome") or "").strip()
    )
    return {
        "row": row,
        "telefone": telefone,
        "responsavel": responsavel,
        "reacoes": reacoes,
        "total_parabens": total_parabens,
        "mural": mural,
    }


def _painel_academia_contexto(mes: int, aluno_sel_id):
    """Monta a tela de aniversariantes da academia (as duas abas)."""
    hoje = date.today()
    ano = hoje.year
    ref = f"{ano}-{mes:02d}"
    academia_id = _academia_do_painel()

    itens = _listar_aniversariantes_mes(mes) or []

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ids = [int(a["id"]) for a in itens if a.get("id")]
        enviados = _parabenizados_por_whatsapp(cur, academia_id, ano, mes)
        parabens_live = _contagem_parabens_live(cur, ref, ids)

        hoje_lista, proximos, passados = [], [], []
        for a in itens:
            nasc = _parse_data_nascimento(a.get("data_nascimento"))
            if not nasc:
                continue
            dia = nasc.day
            idade = _idade_no_aniversario(nasc, ano)
            no_dia = (mes == hoje.month and dia == hoje.day and ano == hoje.year)
            futuro = (ano, mes, dia) > (hoje.year, hoje.month, hoje.day)
            item = {
                "id": int(a["id"]),
                "nome": a.get("nome") or "",
                "iniciais": _iniciais(a.get("nome")),
                "foto_url": _foto_url(a.get("foto")),
                "turmas": (a.get("turmas") or "").strip(),
                "dia": dia,
                "data_label": f"{dia} de {_MESES_PT[mes][:3]}",
                "idade": idade,
                "idade_label": (f"faz {idade} anos" if (no_dia or futuro) else f"fez {idade} anos"),
                "hoje": no_dia,
                "futuro": futuro,
                "parabenizado": int(a["id"]) in enviados,
                "parabens_live": parabens_live.get(int(a["id"]), 0),
            }
            if no_dia:
                hoje_lista.append(item)
            elif futuro:
                proximos.append(item)
            else:
                passados.append(item)

        # Já passaram: o mais recente primeiro é o que a secretaria procura.
        passados.sort(key=lambda x: x["dia"], reverse=True)

        # Elegível a parabéns = o dia já chegou. É sobre esses que faz sentido
        # medir quem já recebeu mensagem.
        elegiveis = hoje_lista + passados
        parabenizados = sum(1 for x in elegiveis if x["parabenizado"])

        # Seleção: o pedido explícito, senão quem faz aniversário hoje.
        selecionado_id = aluno_sel_id
        if selecionado_id not in ids:
            selecionado_id = (hoje_lista or passados or proximos or [{"id": None}])[0]["id"]

        detalhe = _detalhe_aluno_painel(cur, selecionado_id, ref) if selecionado_id else None
        selecionado = None
        if detalhe:
            base = next((x for x in (hoje_lista + proximos + passados)
                         if x["id"] == selecionado_id), None)
            selecionado = dict(base or {})
            selecionado.update({
                "telefone": detalhe["telefone"],
                "responsavel": detalhe["responsavel"],
                "reacoes": detalhe["reacoes"],
                "total_parabens": detalhe["total_parabens"],
                "mural": detalhe["mural"],
                "ultimo_whatsapp": enviados.get(selecionado_id),
            })
            # Colegas da mesma turma que ainda vêm no mês — o "próximos da turma".
            selecionado["proximos_turma"] = [
                x for x in (hoje_lista + proximos)
                if x["id"] != selecionado_id
            ][:6]
    finally:
        cur.close()
        conn.close()

    mensagem_modelo, modelo_ativo = "", True
    if academia_id:
        try:
            from utils.whatsapp_lembretes import mensagem_aniversario
            linha = None
            if selecionado:
                linha = {"nome": selecionado.get("nome"),
                         "responsavel_financeiro_nome": selecionado.get("responsavel")}
            mensagem_modelo, modelo_ativo = mensagem_aniversario(academia_id, linha)
        except Exception:
            current_app.logger.info("aniversariantes: modelo de WhatsApp indisponível")

    return {
        "mes": mes,
        "ano": ano,
        "ref_mes_ano": ref,
        "meses_nomes": _MESES_NOMES,
        "mes_nome": _MESES_NOMES[mes],
        "hoje_label": f"{hoje.day} de {_MESES_NOMES[hoje.month].lower()}",
        "mes_corrente": mes == hoje.month,
        "aniv_hoje": hoje_lista,
        "aniv_proximos": proximos,
        "aniv_passados": passados,
        "kpis": {
            "no_mes": len(hoje_lista) + len(proximos) + len(passados),
            "hoje": len(hoje_lista),
            "proximos": len(proximos),
            "parabenizados": parabenizados,
            "elegiveis": len(elegiveis),
        },
        "selecionado": selecionado,
        "mensagem_modelo": mensagem_modelo,
        "modelo_ativo": modelo_ativo,
        "academia_id": academia_id,
    }


@bp_aniversariante_live.route("/")
@login_required
def pagina():
    """Aniversariantes do mês.

    No modo academia a tela é a da secretaria (server-side, dentro do shell da
    academia). Nos demais modos — aluno, responsável, professor fora do painel —
    continua a SPA de celebração, que roda no layout deles.
    """
    aluno_escopo = request.args.get("aluno_id", type=int)

    if (session.get("modo_painel") or "") == "academia" and _usuario_eh_staff_academia():
        mes = request.args.get("mes", type=int) or date.today().month
        if mes < 1 or mes > 12:
            mes = date.today().month
        ctx = _painel_academia_contexto(mes, aluno_escopo)
        return render_template("aniversariante_live/painel.html", **ctx)

    return render_template(
        "aniversariante_live/index.html",
        voltar_painel_url=_voltar_painel_url_seguro(),
        aniv_aluno_escopo=aluno_escopo,
    )


@bp_aniversariante_live.route("/whatsapp", methods=["POST"])
@login_required
def api_whatsapp_parabens():
    """Dispara o parabéns por WhatsApp: um aluno, ou todos os de hoje.

    É o envio manual da secretaria — não depende de a automação diária estar
    ligada, só do modelo de mensagem estar ativo.
    """
    if not _usuario_eh_staff_academia():
        return jsonify({"ok": False, "msg": "Sem permissão"}), 403

    data = request.get_json(silent=True) or {}
    forcar = bool(data.get("forcar"))
    from utils.whatsapp_lembretes import enviar_aniversario_aluno

    alvos = data.get("alunos")
    if not alvos:
        aluno_id = data.get("aluno_id")
        alvos = [aluno_id] if aluno_id else []
    try:
        alvos = [int(x) for x in alvos][:60]
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "aluno_id inválido"}), 400
    if not alvos:
        return jsonify({"ok": False, "msg": "Nenhum aniversariante informado."}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        permitidos = [a for a in alvos if aniv_msg._staff_may_access_aluno(cur, a)[0]]
    finally:
        cur.close()
        conn.close()
    if not permitidos:
        return jsonify({"ok": False, "msg": "Sem permissão sobre estes alunos."}), 403

    resultados = [dict(enviar_aniversario_aluno(a, forcar=forcar), aluno_id=a) for a in permitidos]
    enviados = sum(1 for r in resultados if r.get("ok"))
    motivos = [r.get("motivo") for r in resultados if not r.get("ok")]
    return jsonify({
        "ok": enviados > 0,
        "enviados": enviados,
        "total": len(resultados),
        "motivos": motivos,
        "resultados": resultados,
    })


@bp_aniversariante_live.route("/aniversariantes", methods=["GET"])
@login_required
def api_aniversariantes():
    mes = request.args.get("mes", type=int) or date.today().month
    if mes < 1 or mes > 12:
        mes = date.today().month
    aluno_escopo = request.args.get("aluno_id", type=int)
    rows = _listar_aniversariantes_mes(mes, aluno_escopo=aluno_escopo)
    out = []
    for a in rows:
        out.append(
            {
                "id": a.get("id"),
                "nome": a.get("nome") or "",
                "foto_url": _foto_url(a.get("foto")),
                "data_nascimento": a.get("data_nascimento").isoformat()
                if hasattr(a.get("data_nascimento"), "isoformat")
                else (str(a.get("data_nascimento") or "")[:10]),
                "turmas": a.get("turmas") or "",
                "aniversario_dia_mes": _texto_dia_mes_aniversario(a.get("data_nascimento")),
                "pode_enviar_parabens": _pode_enviar_parabens_desde_anchor_ref(
                    a.get("data_nascimento"), f"{date.today().year}-{mes:02d}"
                ),
            }
        )
    return jsonify({"ok": True, "mes": mes, "ref_mes_ano": f"{date.today().year}-{mes:02d}", "itens": out})


@bp_aniversariante_live.route("/aniversariante/<int:aluno_id>", methods=["GET"])
@login_required
def api_aniversariante(aluno_id):
    ref = (request.args.get("ref_mes_ano") or "").strip() or _ref_mes_ano_default()
    if not aniv_msg._ref_mes_ano_ok(ref):
        ref = _ref_mes_ano_default()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT a.id, a.nome, a.foto, a.data_nascimento, ac.nome AS academia_nome
            FROM alunos a
            LEFT JOIN academias ac ON ac.id = a.id_academia
            WHERE a.id = %s AND a.ativo = 1
            """,
            (aluno_id,),
        )
        aluno = cur.fetchone()
        if not aluno:
            return jsonify({"ok": False, "msg": "Aluno não encontrado"}), 404
        if not _pode_interagir_aluno(cur, aluno_id, ref):
            return jsonify({"ok": False, "msg": "Sem permissão"}), 403

        if not _tabela_live_existe(cur):
            return jsonify(
                {
                    "ok": False,
                    "msg": "Tabela aniversario_live_eventos ausente. Execute migrations/create_aniversario_live_eventos.sql",
                }
            ), 503

        cur.execute(
            """
            SELECT COUNT(*) AS c FROM aniversario_live_eventos
            WHERE aluno_id = %s AND ref_mes_ano = %s AND acao = 'parabens'
            """,
            (aluno_id, ref),
        )
        total_parabens = int((cur.fetchone() or {}).get("c") or 0)

        cur.execute(
            """
            SELECT 1 FROM aniversario_live_eventos
            WHERE aluno_id = %s AND ref_mes_ano = %s AND usuario_id = %s AND acao = 'parabens'
            LIMIT 1
            """,
            (aluno_id, ref, int(current_user.id)),
        )
        usuario_ja_enviou_parabens = cur.fetchone() is not None

        cur.execute(
            """
            SELECT e.id, e.aluno_id, e.usuario_id, e.acao, e.criado_em,
                   u.nome AS autor_nome, u.foto AS autor_foto
            FROM aniversario_live_eventos e
            LEFT JOIN usuarios u ON u.id = e.usuario_id
            WHERE e.aluno_id = %s AND e.ref_mes_ano = %s
            ORDER BY e.id DESC
            LIMIT 80
            """,
            (aluno_id, ref),
        )
        event_rows = cur.fetchall() or []
        eventos = [_serialize_evento(x) for x in reversed(event_rows)]
        pode = _pode_enviar_parabens_desde_anchor_ref(aluno.get("data_nascimento"), ref)
        sou_aniversariante = aniv_msg._aluno_eh_proprio(cur, aluno_id)

        return jsonify(
            {
                "ok": True,
                "ref_mes_ano": ref,
                "sou_aniversariante": sou_aniversariante,
                "pode_enviar_parabens": pode,
                "usuario_ja_enviou_parabens": usuario_ja_enviou_parabens,
                "msg_interacao_bloqueada": (
                    None
                    if pode
                    else "Parabéns e reações ficam liberados a partir do dia do aniversário (neste mês/ano da lista)."
                ),
                "aluno": {
                    "id": aluno["id"],
                    "nome": aluno.get("nome") or "",
                    "foto_url": _foto_url(aluno.get("foto")),
                    "academia_nome": (aluno.get("academia_nome") or "").strip() or "",
                    "aniversario_dia_mes": _texto_dia_mes_aniversario(aluno.get("data_nascimento")),
                    "data_nascimento": aluno.get("data_nascimento").isoformat()
                    if hasattr(aluno.get("data_nascimento"), "isoformat")
                    else (str(aluno.get("data_nascimento") or "")[:10]),
                },
                "total_parabens": total_parabens,
                "eventos": eventos,
            }
        )
    except Exception as exc:
        current_app.logger.exception("aniversariante_live.api_aniversariante")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@bp_aniversariante_live.route("/aniversariante/<int:aluno_id>/feed", methods=["GET"])
@login_required
def api_feed(aluno_id):
    """Polling leve: eventos novos + contador (desde último id)."""
    ref = (request.args.get("ref_mes_ano") or "").strip() or _ref_mes_ano_default()
    if not aniv_msg._ref_mes_ano_ok(ref):
        ref = _ref_mes_ano_default()
    since_id = request.args.get("since_id", type=int) or 0

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if not _pode_interagir_aluno(cur, aluno_id, ref):
            return jsonify({"ok": False, "msg": "Sem permissão"}), 403
        if not _tabela_live_existe(cur):
            return jsonify({"ok": False, "msg": "Tabela de eventos não configurada"}), 503

        cur.execute(
            "SELECT data_nascimento FROM alunos WHERE id = %s AND ativo = 1",
            (aluno_id,),
        )
        row_n = cur.fetchone()
        nasc = row_n.get("data_nascimento") if row_n else None
        pode = _pode_enviar_parabens_desde_anchor_ref(nasc, ref)

        cur.execute(
            """
            SELECT COUNT(*) AS c FROM aniversario_live_eventos
            WHERE aluno_id = %s AND ref_mes_ano = %s AND acao = 'parabens'
            """,
            (aluno_id, ref),
        )
        total_parabens = int((cur.fetchone() or {}).get("c") or 0)

        cur.execute(
            """
            SELECT 1 FROM aniversario_live_eventos
            WHERE aluno_id = %s AND ref_mes_ano = %s AND usuario_id = %s AND acao = 'parabens'
            LIMIT 1
            """,
            (aluno_id, ref, int(current_user.id)),
        )
        usuario_ja_enviou_parabens = cur.fetchone() is not None

        cur.execute(
            """
            SELECT e.id, e.aluno_id, e.usuario_id, e.acao, e.criado_em,
                   u.nome AS autor_nome, u.foto AS autor_foto
            FROM aniversario_live_eventos e
            LEFT JOIN usuarios u ON u.id = e.usuario_id
            WHERE e.aluno_id = %s AND e.ref_mes_ano = %s AND e.id > %s
            ORDER BY e.id ASC
            LIMIT 100
            """,
            (aluno_id, ref, since_id),
        )
        novos = [_serialize_evento(x) for x in (cur.fetchall() or [])]
        sou_aniversariante = aniv_msg._aluno_eh_proprio(cur, aluno_id)
        return jsonify(
            {
                "ok": True,
                "total_parabens": total_parabens,
                "eventos": novos,
                "sou_aniversariante": sou_aniversariante,
                "pode_enviar_parabens": pode,
                "usuario_ja_enviou_parabens": usuario_ja_enviou_parabens,
            }
        )
    except Exception as exc:
        current_app.logger.exception("aniversariante_live.api_feed")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@bp_aniversariante_live.route("/parabens", methods=["POST"])
@login_required
def api_parabens():
    data = request.get_json(silent=True) or {}
    try:
        aluno_id = int(data.get("aluno_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "aluno_id obrigatório"}), 400

    acao = (data.get("acao") or "parabens").strip().lower()
    if acao not in ACOES_PERMITIDAS:
        return jsonify({"ok": False, "msg": "Ação inválida (use parabens, heart, cake, party ou clap)."}), 400

    ref = (data.get("ref_mes_ano") or "").strip() or _ref_mes_ano_default()
    if not aniv_msg._ref_mes_ano_ok(ref):
        ref = _ref_mes_ano_default()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if not _pode_interagir_aluno(cur, aluno_id, ref):
            return jsonify({"ok": False, "msg": "Sem permissão"}), 403
        if aniv_msg._aluno_eh_proprio(cur, aluno_id):
            return jsonify(
                {
                    "ok": False,
                    "msg": "Na sua festa você só acompanha as interações dos outros — use os botões nas telas dos colegas.",
                }
            ), 403
        if not _tabela_live_existe(cur):
            return jsonify(
                {
                    "ok": False,
                    "msg": "Tabela aniversario_live_eventos ausente. Execute migrations/create_aniversario_live_eventos.sql",
                }
            ), 503

        cur.execute(
            "SELECT data_nascimento, usuario_id, nome FROM alunos WHERE id = %s AND ativo = 1",
            (aluno_id,),
        )
        row_a = cur.fetchone()
        if not row_a or not _pode_enviar_parabens_desde_anchor_ref(row_a.get("data_nascimento"), ref):
            return jsonify(
                {
                    "ok": False,
                    "msg": "Só é possível enviar parabéns e reações a partir do dia do aniversário (neste mês/ano).",
                }
            ), 403

        if acao == "parabens":
            cur.execute(
                """
                SELECT 1 FROM aniversario_live_eventos
                WHERE aluno_id = %s AND ref_mes_ano = %s AND usuario_id = %s AND acao = 'parabens'
                LIMIT 1
                """,
                (aluno_id, ref, int(current_user.id)),
            )
            if cur.fetchone():
                return jsonify(
                    {
                        "ok": False,
                        "msg": "Você já enviou parabéns para este aniversariante neste mês.",
                        "ja_enviou_parabens": True,
                    }
                ), 409

        cur.execute(
            """
            INSERT INTO aniversario_live_eventos (aluno_id, ref_mes_ano, usuario_id, acao)
            VALUES (%s, %s, %s, %s)
            """,
            (aluno_id, ref, int(current_user.id), acao),
        )
        conn.commit()
        new_id = cur.lastrowid

        cur.execute(
            """
            SELECT COUNT(*) AS c FROM aniversario_live_eventos
            WHERE aluno_id = %s AND ref_mes_ano = %s AND acao = 'parabens'
            """,
            (aluno_id, ref),
        )
        total_parabens = int((cur.fetchone() or {}).get("c") or 0)

        cur.execute(
            """
            SELECT e.id, e.aluno_id, e.usuario_id, e.acao, e.criado_em,
                   u.nome AS autor_nome, u.foto AS autor_foto
            FROM aniversario_live_eventos e
            LEFT JOIN usuarios u ON u.id = e.usuario_id
            WHERE e.id = %s
            """,
            (new_id,),
        )
        row = cur.fetchone()
        evento = _serialize_evento(row) if row else None

        if acao == "parabens":
            try:
                usuario_destino = int(row_a.get("usuario_id") or 0)
            except (TypeError, ValueError):
                usuario_destino = 0
            if usuario_destino and usuario_destino != int(current_user.id):
                try:
                    from utils.push_notifications import enviar_push_usuario

                    nome_aluno = (row_a.get("nome") or "Você").strip() or "Você"
                    nome_autor = (getattr(current_user, "nome", None) or "Alguém").strip() or "Alguém"
                    url_live = f"/aniversariante-live/?next=/painel_aluno/meu-perfil#/live/{aluno_id}"
                    enviar_push_usuario(
                        usuario_destino,
                        title=f"Parabéns para {nome_aluno} 🎉",
                        body=f"{nome_autor} enviou parabéns. Toque para visualizar.",
                        url=url_live,
                        tag=f"aniv-live-{aluno_id}-{ref}",
                        require_interaction=True,
                    )
                except Exception:
                    current_app.logger.exception("aniversariante_live.push_parabens")

        return jsonify({"ok": True, "evento": evento, "total_parabens": total_parabens})
    except Exception as exc:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        current_app.logger.exception("aniversariante_live.api_parabens")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@bp_aniversariante_live.route("/badge-count", methods=["GET"])
@login_required
def api_badge_count():
    """
    Badge do ícone de chat: total de parabéns recebidos pelo aluno logado
    no mês/ano atual (ref padrão YYYY-MM).
    """
    ref = _ref_mes_ano_default()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id FROM alunos WHERE usuario_id = %s AND ativo = 1 LIMIT 1",
            (int(current_user.id),),
        )
        row_aluno = cur.fetchone()
        if not row_aluno:
            return jsonify({"ok": True, "count": 0})
        aluno_id = int(row_aluno["id"])
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM aniversario_live_eventos
            WHERE aluno_id = %s
              AND ref_mes_ano = %s
              AND acao = 'parabens'
              AND usuario_id <> %s
            """,
            (aluno_id, ref, int(current_user.id)),
        )
        count = int((cur.fetchone() or {}).get("c") or 0)
        return jsonify({"ok": True, "count": count})
    except Exception as exc:
        current_app.logger.exception("aniversariante_live.api_badge_count")
        return jsonify({"ok": False, "msg": str(exc), "count": 0}), 500
    finally:
        cur.close()
        conn.close()
