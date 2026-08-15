# -*- coding: utf-8 -*-
"""API JSON: mensagens de aniversário (staff ↔ aluno) por mês."""
import re
from datetime import date

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from config import get_db_connection

aniversario_mensagens_bp = Blueprint(
    "aniversario_mensagens",
    __name__,
    url_prefix="/api/aniversario-mensagens",
)


def _ref_mes_ano_ok(s: str) -> bool:
    return bool(s and re.match(r"^\d{4}-\d{2}$", s))


def _get_academias_ids():
    from blueprints.academia.routes import _get_academias_ids as _g

    return _g() or []


def _fetch_aluno(cur, aluno_id: int):
    cur.execute(
        "SELECT id, id_academia, usuario_id, nome FROM alunos WHERE id = %s",
        (aluno_id,),
    )
    return cur.fetchone()


def _staff_may_access_aluno(cur, aluno_id: int):
    """Retorna (True, aluno_row) se staff pode ver/enviar mensagem a este aluno."""
    a = _fetch_aluno(cur, aluno_id)
    if not a:
        return False, None
    aid = a.get("id_academia")
    if not aid:
        return False, a
    if current_user.has_role("admin"):
        return True, a
    is_gestor = (
        current_user.has_role("gestor_academia")
        or current_user.has_role("gestor_associacao")
        or current_user.has_role("gestor_federacao")
    )

    # Professor: aluno da mesma academia onde leciona (lista live ampliada) ou mesma turma
    if current_user.has_role("professor"):
        cur.execute(
            """
            SELECT 1 FROM alunos a2
            WHERE a2.id = %s AND a2.ativo = 1 AND a2.id_academia IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM turma_professor tp
                  INNER JOIN turmas t ON t.TurmaID = tp.TurmaID
                  INNER JOIN professores p ON p.id = tp.professor_id AND p.ativo = 1
                  WHERE p.usuario_id = %s
                    AND t.id_academia IS NOT NULL
                    AND t.id_academia = a2.id_academia
              )
            LIMIT 1
            """,
            (aluno_id, current_user.id),
        )
        if cur.fetchone():
            return True, a
        cur.execute(
            """
            SELECT 1 FROM aluno_turmas at2
            INNER JOIN turma_professor tp ON tp.TurmaID = at2.TurmaID
            INNER JOIN professores p ON p.id = tp.professor_id AND p.ativo = 1
            WHERE at2.aluno_id = %s AND p.usuario_id = %s
            LIMIT 1
            """,
            (aluno_id, current_user.id),
        )
        if cur.fetchone():
            return True, a
        if not is_gestor:
            return False, a

    ids = set(_get_academias_ids())
    if aid not in ids:
        return False, a
    if is_gestor:
        return True, a
    return True, a


def _aluno_eh_proprio(cur, aluno_id: int) -> bool:
    a = _fetch_aluno(cur, aluno_id)
    if not a:
        return False
    return bool(a.get("usuario_id") and a["usuario_id"] == current_user.id)


def _ids_colegas_aniversariantes_mes(ref_mes_ano: str) -> set:
    """IDs de alunos na mesma lista de aniversariantes do mês que o aluno logado vê (turmas em comum)."""
    if not _ref_mes_ano_ok(ref_mes_ano):
        return set()
    if not current_user.has_role("aluno"):
        return set()
    try:
        mes = int(ref_mes_ano.split("-")[1])
    except (IndexError, ValueError):
        return set()
    from utils.aniversariantes import aniversariantes_do_mes

    lista = aniversariantes_do_mes(current_user.id, "aluno", mes=mes)
    out = set()
    for x in lista or []:
        try:
            out.add(int(x["id"]))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _txt(v):
    """Normaliza valor vindo do MySQL (str, bytes, None) para str JSON-safe."""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _serialize_msg(r: dict) -> dict:
    if not r:
        return {}
    ce = r.get("criado_em")
    if hasattr(ce, "isoformat"):
        ce_s = ce.isoformat(sep=" ", timespec="seconds")
    else:
        ce_s = _txt(ce) if ce else ""
    return {
        "id": r.get("id"),
        "aluno_id": r.get("aluno_id"),
        "remetente": _txt(r.get("remetente")) or "staff",
        "corpo": _txt(r.get("corpo")),
        "parent_id": r.get("parent_id"),
        "usuario_id": r.get("usuario_id"),
        "criado_em": ce_s,
        "autor_nome": _txt(r.get("autor_nome")) or None,
    }


@aniversario_mensagens_bp.route("/lote", methods=["GET"])
@login_required
def lote():
    ref = (request.args.get("ref_mes_ano") or "").strip()
    if not _ref_mes_ano_ok(ref):
        hoje = date.today()
        ref = f"{hoje.year}-{hoje.month:02d}"
    raw = (request.args.get("aluno_ids") or "").strip()
    if not raw:
        return jsonify({"ok": True, "por_aluno": {}})
    try:
        aluno_ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    except ValueError:
        return jsonify({"ok": False, "msg": "aluno_ids inválido"}), 400
    aluno_ids = aluno_ids[:120]
    if not aluno_ids:
        return jsonify({"ok": True, "por_aluno": {}})

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT 1 FROM aniversario_mensagens LIMIT 1")
        except Exception as exc:
            errno = getattr(exc, "errno", None)
            err_s = str(exc).lower()
            missing = errno == 1146 or (
                "aniversario_mensagens" in err_s
                and ("doesn't exist" in err_s or "does not exist" in err_s or "unknown table" in err_s)
            )
            if missing:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "msg": "Tabela de mensagens não encontrada. Execute a migração create_aniversario_mensagens.sql.",
                            "detail": str(exc),
                        }
                    ),
                    503,
                )
            raise
        # Obrigatório no mysql-connector: consumir o resultado antes do próximo execute no mesmo cursor
        cur.fetchone()

        colega_ctx = _ids_colegas_aniversariantes_mes(ref)
        permitidos = []
        for aid in aluno_ids:
            ok_staff, _ = _staff_may_access_aluno(cur, aid)
            ok_aluno = _aluno_eh_proprio(cur, aid)
            ok_colega = aid in colega_ctx
            if ok_staff or ok_aluno or ok_colega:
                permitidos.append(aid)

        if not permitidos:
            return jsonify({"ok": True, "por_aluno": {}})

        ph = ",".join(["%s"] * len(permitidos))
        cur.execute(
            f"""
            SELECT m.id, m.aluno_id, m.academia_id, m.ref_mes_ano, m.remetente, m.usuario_id,
                   m.corpo, m.parent_id, m.criado_em,
                   u.nome AS autor_nome
            FROM aniversario_mensagens m
            LEFT JOIN usuarios u ON u.id = m.usuario_id
            WHERE m.ref_mes_ano = %s AND m.aluno_id IN ({ph})
            ORDER BY m.aluno_id ASC, m.criado_em ASC
            """,
            (ref,) + tuple(permitidos),
        )
        rows = cur.fetchall()

        por = {str(i): [] for i in permitidos}
        for r in rows:
            key = str(r.get("aluno_id"))
            if key in por:
                por[key].append(_serialize_msg(r))
        return jsonify({"ok": True, "por_aluno": por, "ref_mes_ano": ref})
    except Exception as exc:
        current_app.logger.exception("aniversario_mensagens.lote")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@aniversario_mensagens_bp.route("", methods=["POST"])
@login_required
def criar():
    data = request.get_json(silent=True) or {}
    try:
        aluno_id = int(data.get("aluno_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "aluno_id obrigatório"}), 400
    corpo = (data.get("corpo") or "").strip()
    if not corpo:
        return jsonify({"ok": False, "msg": "Mensagem vazia"}), 400
    if len(corpo) > 2000:
        corpo = corpo[:2000]
    ref = (data.get("ref_mes_ano") or "").strip()
    if not _ref_mes_ano_ok(ref):
        hoje = date.today()
        ref = f"{hoje.year}-{hoje.month:02d}"
    parent_id = data.get("parent_id")
    if parent_id is not None and parent_id != "":
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "msg": "parent_id inválido"}), 400
    else:
        parent_id = None

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT 1 FROM aniversario_mensagens LIMIT 1")
        except Exception as exc:
            errno = getattr(exc, "errno", None)
            err_s = str(exc).lower()
            missing = errno == 1146 or (
                "aniversario_mensagens" in err_s
                and ("doesn't exist" in err_s or "does not exist" in err_s or "unknown table" in err_s)
            )
            if missing:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "msg": "Tabela de mensagens não encontrada. Execute a migração create_aniversario_mensagens.sql.",
                            "detail": str(exc),
                        }
                    ),
                    503,
                )
            raise
        cur.fetchone()

        a = _fetch_aluno(cur, aluno_id)
        if not a:
            return jsonify({"ok": False, "msg": "Aluno não encontrado"}), 404
        academia_id = a.get("id_academia")
        if not academia_id:
            return jsonify({"ok": False, "msg": "Aluno sem academia"}), 400

        is_own = _aluno_eh_proprio(cur, aluno_id)
        ok_staff, _ = _staff_may_access_aluno(cur, aluno_id)
        colega_ctx = _ids_colegas_aniversariantes_mes(ref)
        cur.execute(
            "SELECT id FROM alunos WHERE usuario_id = %s LIMIT 1", (current_user.id,)
        )
        _row_me = cur.fetchone()
        _me_aid = int(_row_me["id"]) if _row_me and _row_me.get("id") is not None else None
        ok_colega_parabens = (
            _me_aid is not None
            and _me_aid in colega_ctx
            and aluno_id in colega_ctx
            and aluno_id != _me_aid
        )

        if is_own:
            remetente = "aluno"
        elif ok_staff:
            remetente = "staff"
        elif ok_colega_parabens:
            remetente = "aluno"
        else:
            return jsonify({"ok": False, "msg": "Sem permissão"}), 403

        if parent_id:
            cur.execute(
                "SELECT id, aluno_id, ref_mes_ano FROM aniversario_mensagens WHERE id = %s",
                (parent_id,),
            )
            pr = cur.fetchone()
            if not pr or pr.get("aluno_id") != aluno_id or pr.get("ref_mes_ano") != ref:
                return jsonify({"ok": False, "msg": "Resposta inválida"}), 400

        uid = int(current_user.id)
        cur.execute(
            """
            INSERT INTO aniversario_mensagens
            (aluno_id, academia_id, ref_mes_ano, remetente, usuario_id, corpo, parent_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (aluno_id, academia_id, ref, remetente, uid, corpo, parent_id),
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.execute(
            """
            SELECT m.id, m.aluno_id, m.academia_id, m.ref_mes_ano, m.remetente, m.usuario_id,
                   m.corpo, m.parent_id, m.criado_em,
                   u.nome AS autor_nome
            FROM aniversario_mensagens m
            LEFT JOIN usuarios u ON u.id = m.usuario_id
            WHERE m.id = %s
            """,
            (new_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "msg": "Mensagem gravada mas não foi possível recarregar."}), 500
        return jsonify({"ok": True, "mensagem": _serialize_msg(row)})
    except Exception as exc:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        current_app.logger.exception("aniversario_mensagens.criar")
        return jsonify({"ok": False, "msg": str(exc)}), 500
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
