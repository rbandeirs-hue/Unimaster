# -*- coding: utf-8 -*-
"""
Blueprint de Web Push Notifications.

Rotas:
  GET  /push/vapid-public-key   → retorna a chave pública VAPID
  POST /push/subscribe          → salva uma subscription
  POST /push/unsubscribe        → remove uma subscription
  POST /push/test               → envia uma notificação de teste ao usuário logado
  GET  /push/in-app                     → lista notificações in-app (dropdown)
  GET  /push/in-app/unread-count        → quantidade não lida
  POST /push/in-app/marcar-lida         → JSON { "ref_id": int, "ref_tipo"?: str }
  POST /push/in-app/marcar-todas-lidas
  POST /push/in-app/limpar-lidas        → oculta só as já lidas
"""
import sys

from datetime import date, datetime
from urllib.parse import quote

from flask import Blueprint, request, jsonify, current_app, session, url_for
from extensions import csrf
from flask_login import login_required, current_user

from config import get_db_connection
from utils.in_app_notificacoes import (
    REF_TIPO_ANIVERSARIO_HOJE,
    REF_TIPO_PARABENS_LIVE,
    ensure_in_app_notif_estado_table,
)
from utils.push_notifications import (
    VAPID_PUBLIC_KEY,
    enviar_push_usuario,
    obter_qtd_push_subscriptions,
    salvar_subscription,
    remover_subscription,
)

bp_notificacoes = Blueprint("notificacoes", __name__)


def _aluno_ativo_id(cur, usuario_id: int):
    cur.execute(
        "SELECT id FROM alunos WHERE usuario_id = %s AND ativo = 1 LIMIT 1",
        (usuario_id,),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None


def _next_path_aniversariante_live() -> str:
    """Caminho `next` coerente com o modo de painel (ex.: /professor/)."""
    modo = session.get("modo_painel")
    try:
        if modo == "professor":
            return url_for("professor.painel_professor")
        if modo == "academia":
            return url_for("academia.painel_academia")
        if modo == "associacao":
            return url_for("associacao.gerenciamento_associacao")
        if modo == "federacao":
            return url_for("federacao.gerenciamento_federacao")
        if modo == "aluno":
            return url_for("painel_aluno.meu_perfil")
        if modo == "responsavel":
            return url_for("painel_responsavel.painel")
        if modo == "visitante":
            return url_for("visitante.painel")
        if modo == "admin":
            return url_for("painel.home")
    except Exception:
        pass
    return url_for("painel.home")


def _build_aniv_live_link(aluno_id: int) -> str:
    next_path = _next_path_aniversariante_live()
    return f"/aniversariante-live/?next={quote(next_path, safe='/')}#/live/{int(aluno_id)}"


def _hoje_mes_dia():
    h = date.today()
    return h.month, h.day, h


def _formatar_data_hora_br(criado) -> str:
    """Ex.: 04/05/2026 às 14:32 — para exibir só em parabéns com data real."""
    if isinstance(criado, datetime):
        return criado.strftime("%d/%m/%Y às %H:%M")
    if isinstance(criado, date):
        return criado.strftime("%d/%m/%Y")
    return ""


@bp_notificacoes.route("/push/vapid-public-key")
def vapid_public_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})


@bp_notificacoes.route("/push/subscribe", methods=["POST"])
@login_required
def subscribe():
    data = request.get_json(silent=True) or {}
    user_agent = request.headers.get("User-Agent", "")[:255]
    ok, err_msg = salvar_subscription(current_user.id, data, user_agent)
    if ok:
        return jsonify({"status": "ok"}), 201
    code = 503 if err_msg and "push_subscriptions" in err_msg.lower() else 400
    return jsonify({"status": "erro", "msg": err_msg or "Dados inválidos"}), code


@bp_notificacoes.route("/push/unsubscribe", methods=["POST"])
@login_required
def unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    if endpoint:
        remover_subscription(endpoint)
    return jsonify({"status": "ok"})


@bp_notificacoes.route("/push/test", methods=["POST"])
@login_required
def push_test():
    """
    Envia notificação de teste ao usuário logado.
    Aceita opcionalmente `subscription` (PushSubscription.toJSON()) para gravar
    neste aparelho antes do envio — evita o caso “ativo no navegador mas vazio no MySQL”.
    """
    data = request.get_json(silent=True) or {}
    ua = request.headers.get("User-Agent", "")[:255]
    sub = data.get("subscription")
    if isinstance(sub, dict) and sub.get("endpoint"):
        ok_save, err_save = salvar_subscription(current_user.id, sub, ua)
        if not ok_save:
            return (
                jsonify(
                    {
                        "ok": False,
                        "enviados": 0,
                        "msg": err_save
                        or "Não foi possível salvar a assinatura no servidor. Verifique a tabela push_subscriptions e permissões do MySQL.",
                    }
                ),
                400,
            )
    try:
        import pywebpush  # noqa: F401 — tem de existir no mesmo Python que corre gunicorn/uwsgi.
    except ImportError:
        qtd_db = obter_qtd_push_subscriptions(current_user.id)
        exe = sys.executable
        return jsonify(
            {
                "ok": False,
                "enviados": 0,
                "inscricoes_servidor": qtd_db,
                "msg": (
                    "O pacote pywebpush não está instalado no interpretador Python que está a executar esta "
                    "aplicação (não basta instalá-lo doutro Python). Copie o caminho em python_executable e "
                    "use como_instalar. Reinicie o serviço da app em seguida."
                ),
                "python_executable": exe,
                "como_instalar": f"{exe} -m pip install pywebpush==2.3.0",
                "como_instalar_debian_pep668": f"{exe} -m pip install --break-system-packages pywebpush==2.3.0",
                "detalhes": [
                    "Dica: em systemd, confira ExecStart — se apontar para outro Python ou outro .venv, "
                    "instale pywebpush nesse binário ou altere o serviço para usar .venv/bin/gunicorn."
                ],
            }
        )
    qtd_db = obter_qtd_push_subscriptions(current_user.id)
    erros = []
    try:
        n = enviar_push_usuario(
            current_user.id,
            "Unimaster — teste",
            "Se você viu isto, o push está funcionando neste aparelho.",
            url="/",
            erros_envio=erros,
        )
    except Exception as exc:
        current_app.logger.exception("push_test")
        return jsonify({"ok": False, "enviados": 0, "msg": str(exc)}), 500
    if n == 0:
        if qtd_db == 0:
            return jsonify(
                {
                    "ok": False,
                    "enviados": 0,
                    "msg": (
                        "Nenhuma assinatura no servidor para esta conta. "
                        "Use o botão acima (grava e envia) ou o sino no topo e permita notificações neste navegador."
                    ),
                }
            )
        msg = (
            f"Há {qtd_db} assinatura(s) salva(s), mas nenhum envio foi aceite pelo serviço de push. "
            "Se aparecer HTTP 401 ou 403, o par VAPID no .env não corresponde ao usado quando o navegador "
            "se inscreveu: alinhe VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY com o site ou apague os registos "
            "desta conta em push_subscriptions e volte a gravar neste aparelho."
        )
        if erros:
            msg += " Abaixo aparecem linhas técnicas por dispositivo; confira também os logs do servidor."
        else:
            msg += (
                " Confirme também que o processo da app usa o Python onde está instalado pywebpush "
                "(pip install pywebpush no mesmo interpretador do gunicorn/uwsgi)."
            )
        detalhes = list(dict.fromkeys(erros))[:12]
        payload = {
            "ok": False,
            "enviados": 0,
            "inscricoes_servidor": qtd_db,
            "msg": msg,
            "detalhes": detalhes,
        }
        if detalhes and all("pywebpush não disponível" in x for x in detalhes):
            exe = sys.executable
            payload["python_executable"] = exe
            payload["como_instalar"] = f"{exe} -m pip install pywebpush==2.3.0"
            payload["como_instalar_debian_pep668"] = (
                f"{exe} -m pip install --break-system-packages pywebpush==2.3.0"
            )
        return jsonify(payload)
    return jsonify({"ok": True, "enviados": n, "msg": f"Enviado para {n} dispositivo(s) registrado(s)."})


@bp_notificacoes.route("/push/in-app", methods=["GET"])
@login_required
def in_app_list():
    """
    Lista notificações in-app para o cabeçalho (dropdown).
    Inclui: aniversariantes do dia (toda a base de alunos ativos) e parabéns recebidos (aluno do utilizador).
    """
    uid = int(current_user.id)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    items = []
    try:
        ensure_in_app_notif_estado_table(cur)
        conn.commit()
        m_hoje, d_hoje, dia_ref = _hoje_mes_dia()

        cur.execute(
            """
            SELECT a.id, a.nome, COALESCE(s.lida, 0) AS lida
            FROM alunos a
            LEFT JOIN in_app_notif_estado s
              ON s.usuario_id = %s
             AND s.ref_tipo = %s
             AND s.ref_id = a.id
            WHERE a.ativo = 1
              AND a.data_nascimento IS NOT NULL
              AND MONTH(a.data_nascimento) = %s
              AND DAY(a.data_nascimento) = %s
              AND (s.oculta IS NULL OR s.oculta = 0)
            ORDER BY a.nome ASC
            LIMIT 100
            """,
            (uid, REF_TIPO_ANIVERSARIO_HOJE, m_hoje, d_hoje),
        )
        for r in cur.fetchall() or []:
            aid = int(r.get("id") or 0)
            if aid <= 0:
                continue
            nome = (r.get("nome") or "Aluno").strip() or "Aluno"
            lida = bool(int(r.get("lida") or 0))
            criado_iso = f"{dia_ref.isoformat()}T08:00:00"
            msg2 = "Toque para dar parabéns."
            items.append(
                {
                    "id": f"aniv-hoje-{aid}",
                    "ref_id": aid,
                    "ref_tipo": REF_TIPO_ANIVERSARIO_HOJE,
                    "tipo": "aniversario_hoje",
                    "lida": lida,
                    "linha1": nome,
                    "linha2": msg2,
                    "data_br": None,
                    "titulo": nome,
                    "texto": msg2,
                    "criado_em": criado_iso,
                    "link": _build_aniv_live_link(aid),
                }
            )

        aluno_id = _aluno_ativo_id(cur, uid)
        if aluno_id:
            cur.execute(
                """
                SELECT e.id, e.criado_em, e.aluno_id, e.acao, u.nome AS autor_nome,
                       COALESCE(s.lida, 0) AS lida
                FROM aniversario_live_eventos e
                LEFT JOIN usuarios u ON u.id = e.usuario_id
                LEFT JOIN in_app_notif_estado s
                  ON s.usuario_id = %s
                 AND s.ref_tipo = %s
                 AND s.ref_id = e.id
                WHERE e.aluno_id = %s
                  AND e.usuario_id <> %s
                  AND e.acao = 'parabens'
                  AND (s.oculta IS NULL OR s.oculta = 0)
                ORDER BY e.criado_em DESC
                LIMIT 40
                """,
                (uid, REF_TIPO_PARABENS_LIVE, aluno_id, uid),
            )
            for r in cur.fetchall() or []:
                autor = (r.get("autor_nome") or "Alguém").strip() or "Alguém"
                criado = r.get("criado_em")
                if isinstance(criado, datetime):
                    criado_iso = criado.isoformat(timespec="seconds")
                else:
                    criado_iso = str(criado) if criado else ""
                aid = int(r.get("aluno_id") or aluno_id)
                eid = int(r.get("id") or 0)
                lida = bool(int(r.get("lida") or 0))
                msg2 = "Toque para dar parabéns."
                d_br = _formatar_data_hora_br(criado) if isinstance(criado, datetime) else ""
                items.append(
                    {
                        "id": f"parabens-{eid}",
                        "ref_id": eid,
                        "ref_tipo": REF_TIPO_PARABENS_LIVE,
                        "tipo": "parabens",
                        "lida": lida,
                        "linha1": autor,
                        "linha2": msg2,
                        "data_br": d_br or None,
                        "titulo": autor,
                        "texto": msg2,
                        "criado_em": criado_iso,
                        "link": _build_aniv_live_link(aid),
                    }
                )
    except Exception as exc:
        current_app.logger.exception("notificacoes.in_app_list")
        return jsonify({"ok": False, "msg": str(exc), "items": []}), 500
    finally:
        cur.close()
        conn.close()

    return jsonify({"ok": True, "items": items})


@bp_notificacoes.route("/push/in-app/unread-count", methods=["GET"])
@login_required
def in_app_unread_count():
    uid = int(current_user.id)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ensure_in_app_notif_estado_table(cur)
        conn.commit()
        m_hoje, d_hoje, _dia = _hoje_mes_dia()
        total = 0

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM alunos a
            LEFT JOIN in_app_notif_estado s
              ON s.usuario_id = %s
             AND s.ref_tipo = %s
             AND s.ref_id = a.id
            WHERE a.ativo = 1
              AND a.data_nascimento IS NOT NULL
              AND MONTH(a.data_nascimento) = %s
              AND DAY(a.data_nascimento) = %s
              AND (s.oculta IS NULL OR s.oculta = 0)
              AND (s.lida IS NULL OR s.lida = 0)
            """,
            (uid, REF_TIPO_ANIVERSARIO_HOJE, m_hoje, d_hoje),
        )
        total += int((cur.fetchone() or {}).get("c") or 0)

        aluno_id = _aluno_ativo_id(cur, uid)
        if aluno_id:
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM aniversario_live_eventos e
                LEFT JOIN in_app_notif_estado s
                  ON s.usuario_id = %s
                 AND s.ref_tipo = %s
                 AND s.ref_id = e.id
                WHERE e.aluno_id = %s
                  AND e.usuario_id <> %s
                  AND e.acao = 'parabens'
                  AND (s.oculta IS NULL OR s.oculta = 0)
                  AND (s.lida IS NULL OR s.lida = 0)
                """,
                (uid, REF_TIPO_PARABENS_LIVE, aluno_id, uid),
            )
            total += int((cur.fetchone() or {}).get("c") or 0)

        return jsonify({"ok": True, "count": total})
    except Exception as exc:
        current_app.logger.exception("notificacoes.in_app_unread_count")
        return jsonify({"ok": False, "msg": str(exc), "count": 0}), 500
    finally:
        cur.close()
        conn.close()


@bp_notificacoes.route("/push/in-app/marcar-lida", methods=["POST"])
@login_required
def in_app_marcar_lida():
    data = request.get_json(silent=True) or {}
    try:
        ref_id = int(data.get("ref_id") or 0)
    except (TypeError, ValueError):
        ref_id = 0
    if ref_id <= 0:
        return jsonify({"ok": False, "msg": "ref_id inválido"}), 400
    ref_tipo = (data.get("ref_tipo") or REF_TIPO_PARABENS_LIVE).strip()
    if ref_tipo not in (REF_TIPO_PARABENS_LIVE, REF_TIPO_ANIVERSARIO_HOJE):
        return jsonify({"ok": False, "msg": "ref_tipo inválido"}), 400

    uid = int(current_user.id)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ensure_in_app_notif_estado_table(cur)
        conn.commit()
        if ref_tipo == REF_TIPO_PARABENS_LIVE:
            aluno_id = _aluno_ativo_id(cur, uid)
            if not aluno_id:
                return jsonify({"ok": False, "msg": "Sem aluno vinculado"}), 403
            cur.execute(
                """
                SELECT e.id FROM aniversario_live_eventos e
                WHERE e.id = %s AND e.aluno_id = %s AND e.usuario_id <> %s
                  AND e.acao = 'parabens'
                LIMIT 1
                """,
                (ref_id, aluno_id, uid),
            )
            if not cur.fetchone():
                return jsonify({"ok": False, "msg": "Notificação não encontrada"}), 404
        else:
            m_hoje, d_hoje, _dia = _hoje_mes_dia()
            cur.execute(
                """
                SELECT a.id FROM alunos a
                WHERE a.id = %s AND a.ativo = 1
                  AND a.data_nascimento IS NOT NULL
                  AND MONTH(a.data_nascimento) = %s
                  AND DAY(a.data_nascimento) = %s
                LIMIT 1
                """,
                (ref_id, m_hoje, d_hoje),
            )
            if not cur.fetchone():
                return jsonify({"ok": False, "msg": "Aniversariante não encontrado para hoje"}), 404

        cur.execute(
            """
            INSERT INTO in_app_notif_estado (usuario_id, ref_tipo, ref_id, lida, oculta)
            VALUES (%s, %s, %s, 1, 0)
            ON DUPLICATE KEY UPDATE lida = 1, oculta = 0
            """,
            (uid, ref_tipo, ref_id),
        )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as exc:
        conn.rollback()
        current_app.logger.exception("notificacoes.in_app_marcar_lida")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@bp_notificacoes.route("/push/in-app/marcar-todas-lidas", methods=["POST"])
@login_required
def in_app_marcar_todas_lidas():
    uid = int(current_user.id)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ensure_in_app_notif_estado_table(cur)
        conn.commit()
        m_hoje, d_hoje, _dia = _hoje_mes_dia()
        n = 0

        cur.execute(
            """
            INSERT INTO in_app_notif_estado (usuario_id, ref_tipo, ref_id, lida, oculta)
            SELECT %s, %s, a.id, 1, 0
            FROM alunos a
            LEFT JOIN in_app_notif_estado s
              ON s.usuario_id = %s AND s.ref_tipo = %s AND s.ref_id = a.id
            WHERE a.ativo = 1
              AND a.data_nascimento IS NOT NULL
              AND MONTH(a.data_nascimento) = %s
              AND DAY(a.data_nascimento) = %s
              AND (s.oculta IS NULL OR s.oculta = 0)
            ON DUPLICATE KEY UPDATE lida = 1, oculta = 0
            """,
            (
                uid,
                REF_TIPO_ANIVERSARIO_HOJE,
                uid,
                REF_TIPO_ANIVERSARIO_HOJE,
                m_hoje,
                d_hoje,
            ),
        )
        n += cur.rowcount

        aluno_id = _aluno_ativo_id(cur, uid)
        if aluno_id:
            cur.execute(
                """
                INSERT INTO in_app_notif_estado (usuario_id, ref_tipo, ref_id, lida, oculta)
                SELECT %s, %s, e.id, 1, 0
                FROM aniversario_live_eventos e
                LEFT JOIN in_app_notif_estado s
                  ON s.usuario_id = %s AND s.ref_tipo = %s AND s.ref_id = e.id
                WHERE e.aluno_id = %s
                  AND e.usuario_id <> %s
                  AND e.acao = 'parabens'
                  AND (s.oculta IS NULL OR s.oculta = 0)
                ON DUPLICATE KEY UPDATE lida = 1, oculta = 0
                """,
                (uid, REF_TIPO_PARABENS_LIVE, uid, REF_TIPO_PARABENS_LIVE, aluno_id, uid),
            )
            n += cur.rowcount

        conn.commit()
        return jsonify({"ok": True, "atualizadas": n})
    except Exception as exc:
        conn.rollback()
        current_app.logger.exception("notificacoes.in_app_marcar_todas_lidas")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@bp_notificacoes.route("/push/in-app/limpar-lidas", methods=["POST"])
@login_required
def in_app_limpar_lidas():
    uid = int(current_user.id)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        ensure_in_app_notif_estado_table(cur)
        conn.commit()
        cur.execute(
            """
            UPDATE in_app_notif_estado
            SET oculta = 1
            WHERE usuario_id = %s
              AND lida = 1
              AND oculta = 0
            """,
            (uid,),
        )
        n = cur.rowcount
        conn.commit()
        return jsonify({"ok": True, "ocultadas": n})
    except Exception as exc:
        conn.rollback()
        current_app.logger.exception("notificacoes.in_app_limpar_lidas")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@bp_notificacoes.route("/push/dispatch-aniversariantes-hoje", methods=["GET", "POST"])
@csrf.exempt
def dispatch_aniversariantes_hoje():
    """
    Envia (uma vez por dia por aluno, registrado em push_aniversario_dia_envio) notificações
    push para todos os usuários com assinatura: fulano faz aniversário hoje + botão para o live.

    Protegido por token no query string ou JSON/body: mesmo valor da env CRON_PUSH_TOKEN.
    Agendar no cron de servidor, ex.: diariamente às 08:00:
      curl -sS "https://SEU_DOMINIO/push/dispatch-aniversariantes-hoje?token=SEU_TOKEN"
    """
    token = (request.args.get("token") or "").strip()
    if not token and request.is_json:
        token = (request.get_json(silent=True) or {}).get("token") or ""
        token = str(token).strip()

    from utils.aniversariantes_push_diario import executar_push_aniversariantes_do_dia, validar_token_cron

    ok_tok, err_tok = validar_token_cron(token)
    if not ok_tok:
        return jsonify({"ok": False, "msg": err_tok}), 503 if "não configurado" in err_tok else 401

    force = request.args.get("force") == "1"
    try:
        resumo = executar_push_aniversariantes_do_dia(force=force)
    except Exception as exc:
        current_app.logger.exception("dispatch_aniversariantes_hoje")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    return jsonify(resumo)
