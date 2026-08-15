# ======================================================
# Blueprint: Financeiro (mensalidades, receitas, despesas, descontos)
# ======================================================
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from utils.upload_seguro import validar_upload, nome_seguro, UploadInvalido
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from config import get_db_connection
from utils.alunos_academias import filtro_alunos_da_academia
from extensions import csrf

bp_financeiro = Blueprint("financeiro", __name__, url_prefix="/financeiro")

COMPROVANTE_EXT = {"png", "jpg", "jpeg", "gif", "pdf"}


def _form_wants_json_response():
    """POST do modal de pagamento envia _ajax=1 e/ou cabeçalho típico de XHR."""
    if request.form.get("_ajax") == "1":
        return True
    ax = (request.headers.get("X-Requested-With") or "").lower()
    return ax == "xmlhttprequest"


def _upsert_aluno_desconto_com_pacotes(cur, aluno_id, desconto_id, dt_ini, dt_fim, aplica_todos, ids_list):
    """Insere/atualiza vínculo aluno_desconto com escopo de pacotes. Fallback sem colunas novas."""
    pacotes_json = None if aplica_todos else json.dumps(sorted(set(ids_list)))
    try:
        cur.execute(
            """
            INSERT INTO aluno_desconto (aluno_id, desconto_id, data_inicio, data_fim, ativo, aplica_todos_pacotes, pacotes_mensalidade_ids)
            VALUES (%s, %s, %s, %s, 1, %s, %s)
            ON DUPLICATE KEY UPDATE data_inicio = VALUES(data_inicio), data_fim = VALUES(data_fim), ativo = 1,
            aplica_todos_pacotes = VALUES(aplica_todos_pacotes), pacotes_mensalidade_ids = VALUES(pacotes_mensalidade_ids)
            """,
            (
                aluno_id,
                desconto_id,
                dt_ini,
                dt_fim,
                1 if aplica_todos else 0,
                pacotes_json,
            ),
        )
        return
    except Exception:
        try:
            cur.execute(
                """
                INSERT INTO aluno_desconto (aluno_id, desconto_id, data_inicio, data_fim, ativo)
                VALUES (%s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE data_inicio = VALUES(data_inicio), data_fim = VALUES(data_fim), ativo = 1
                """,
                (aluno_id, desconto_id, dt_ini, dt_fim),
            )
        except Exception:
            cur.execute(
                "SELECT id FROM aluno_desconto WHERE aluno_id = %s AND desconto_id = %s",
                (aluno_id, desconto_id),
            )
            ex = cur.fetchone()
            if ex:
                cur.execute(
                    "UPDATE aluno_desconto SET data_inicio = %s, data_fim = %s, ativo = 1 WHERE id = %s",
                    (dt_ini, dt_fim, ex["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO aluno_desconto (aluno_id, desconto_id, data_inicio, data_fim, ativo) VALUES (%s, %s, %s, %s, 1)",
                    (aluno_id, desconto_id, dt_ini, dt_fim),
                )


def _desconto_aplica_ao_plano(ma, aplica_todos, pacotes_raw):
    """Se aplica_todos_pacotes (truthy), vale para qualquer plano; senão só para ids em JSON."""
    if aplica_todos:
        return True
    mid = ma.get("mensalidade_id")
    if mid is None:
        return False
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return False
    try:
        ids = json.loads(pacotes_raw or "[]")
        if not isinstance(ids, list):
            return False
        allow = {int(x) for x in ids}
        return mid in allow
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def _status_efetivo(status, data_venc, status_pagamento=None):
    """Retorna status efetivo: pendente_aprovacao -> aguardando_confirmacao, pendente vencido -> atrasado."""
    if status_pagamento == "pendente_aprovacao":
        return "aguardando_confirmacao"
    # Pagamento confirmado (inclui isenção por desconto integral) sempre vale como pago,
    # mesmo que a coluna status tenha ficado defasada (ex.: 'atrasado').
    if status_pagamento == "pago":
        return "pago"
    if status and status not in ("pendente",):
        return status
    try:
        venc = data_venc if isinstance(data_venc, date) else (date.fromisoformat(str(data_venc)[:10]) if data_venc else None)
        if venc and venc < date.today():
            return "atrasado"
    except Exception:
        pass
    return status or "pendente"


def _valor_com_desconto(ma, aluno_id, id_academia, hoje=None):
    """Retorna (valor_integral, valor_desconto, valor_final, desconto_nome) para exibição.
    desconto_nome: nome do desconto (ex. 'Família'). Vazio se sem desconto."""
    hoje = hoje or date.today()
    valor_base = float(ma.get("valor") or 0)
    valor_original = float(ma.get("valor_original") or 0) or valor_base
    desconto_aplicado = float(ma.get("desconto_aplicado") or 0)
    id_acad = ma.get("id_academia") or id_academia
    desconto_nome = ""
    if desconto_aplicado > 0:
        id_desc = ma.get("id_desconto")
        if id_desc:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute("SELECT nome FROM descontos WHERE id = %s", (id_desc,))
                d = cur.fetchone()
                if d and d.get("nome"):
                    desconto_nome = str(d["nome"]).strip()
            except Exception:
                pass
            conn.close()
        return valor_original, desconto_aplicado, valor_base, desconto_nome
    try:
        venc = ma.get("data_vencimento")
        data_vigencia = venc if isinstance(venc, date) else (date.fromisoformat(str(venc)[:10]) if venc else hoje)
    except Exception:
        data_vigencia = hoje
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT d.nome, d.tipo, d.valor, COALESCE(d.aplicar_apenas_pagamento_em_dia, 1) AS aplicar_apenas_pagamento_em_dia,
                   COALESCE(ad.aplica_todos_pacotes, 1) AS aplica_todos_pacotes,
                   ad.pacotes_mensalidade_ids
            FROM aluno_desconto ad
            JOIN descontos d ON d.id = ad.desconto_id AND d.ativo = 1
            WHERE ad.aluno_id = %s AND ad.ativo = 1
            AND (ad.data_inicio IS NULL OR ad.data_inicio <= %s)
            AND (ad.data_fim IS NULL OR ad.data_fim >= %s)
            AND d.id_academia = %s
            LIMIT 1
        """, (aluno_id, data_vigencia, data_vigencia, id_acad or id_academia))
        d = cur.fetchone()
    except Exception:
        try:
            cur.execute("""
                SELECT d.nome, d.tipo, d.valor, COALESCE(d.aplicar_apenas_pagamento_em_dia, 1) AS aplicar_apenas_pagamento_em_dia
                FROM aluno_desconto ad
                JOIN descontos d ON d.id = ad.desconto_id AND d.ativo = 1
                WHERE ad.aluno_id = %s AND ad.ativo = 1
                AND (ad.data_inicio IS NULL OR ad.data_inicio <= %s)
                AND (ad.data_fim IS NULL OR ad.data_fim >= %s)
                AND d.id_academia = %s
                LIMIT 1
            """, (aluno_id, data_vigencia, data_vigencia, id_acad or id_academia))
            d = cur.fetchone()
            if d:
                d["aplica_todos_pacotes"] = 1
                d["pacotes_mensalidade_ids"] = None
        except Exception:
            d = None
    conn.close()
    if not d:
        return valor_base, 0, valor_base, ""
    _at_pac = d.get("aplica_todos_pacotes")
    if _at_pac is None:
        _at_pac = 1
    else:
        try:
            _at_pac = int(_at_pac)
        except (TypeError, ValueError):
            _at_pac = 1
    if not _desconto_aplica_ao_plano(ma, _at_pac, d.get("pacotes_mensalidade_ids")):
        return valor_base, 0, valor_base, ""
    desconto_nome = str(d.get("nome") or "").strip()
    atrasado = False
    try:
        venc = ma.get("data_vencimento")
        venc = venc if isinstance(venc, date) else (date.fromisoformat(str(venc)[:10]) if venc else None)
        atrasado = venc and venc < hoje
    except Exception:
        pass
    if d.get("aplicar_apenas_pagamento_em_dia") and atrasado:
        return valor_base, 0, valor_base, desconto_nome or ""
    tipo = d.get("tipo") or "percentual"
    val_desc = float(d.get("valor") or 0)
    if tipo == "percentual":
        desconto = valor_base * (val_desc / 100)
    else:
        desconto = min(val_desc, valor_base)
    return valor_base, round(desconto, 2), round(valor_base - desconto, 2), desconto_nome


def _desconto_id_vigente(cur, aluno_id, id_academia, data_vigencia):
    """Retorna o id do desconto ativo do aluno vigente na data (ou None)."""
    try:
        cur.execute(
            """SELECT ad.desconto_id
               FROM aluno_desconto ad
               JOIN descontos d ON d.id = ad.desconto_id AND d.ativo = 1
               WHERE ad.aluno_id = %s AND ad.ativo = 1
                 AND (ad.data_inicio IS NULL OR ad.data_inicio <= %s)
                 AND (ad.data_fim IS NULL OR ad.data_fim >= %s)
                 AND d.id_academia = %s
               LIMIT 1""",
            (aluno_id, data_vigencia, data_vigencia, id_academia),
        )
        r = cur.fetchone()
        return r.get("desconto_id") if r else None
    except Exception:
        return None


def _quitar_mensalidades_isentas_por_desconto(conn, cur, aluno_id, academia_id, criado_por=None):
    """Quita (status pago, valor 0, receita 0) as mensalidades em aberto do aluno cujo
    desconto vigente cobre 100% do valor. Idempotente. Retorna a quantidade quitada."""
    hoje = date.today()
    try:
        cur.execute(
            """SELECT ma.id, ma.aluno_id, ma.mensalidade_id, ma.valor, ma.valor_original,
                      ma.data_vencimento, m.nome AS plano_nome, a.nome AS aluno_nome
               FROM mensalidade_aluno ma
               JOIN mensalidades m ON m.id = ma.mensalidade_id
               JOIN alunos a ON a.id = ma.aluno_id
               WHERE ma.aluno_id = %s
                 AND ma.status IN ('pendente', 'atrasado')
                 AND COALESCE(ma.status_pagamento, '') <> 'pago'""",
            (aluno_id,),
        )
        rows = cur.fetchall()
    except Exception:
        return 0
    n = 0
    for ma in rows:
        ma2 = dict(ma)
        ma2["id_academia"] = academia_id
        _vi, vd, vf, _nome = _valor_com_desconto(ma2, aluno_id, academia_id, hoje=hoje)
        if float(vd or 0) <= 0 or float(vf or 0) > 0:
            continue  # sem desconto aplicável ou não é integral
        venc = ma.get("data_vencimento")
        try:
            data_pg = venc.strftime("%Y-%m-%d") if hasattr(venc, "strftime") else (str(venc)[:10] if venc else hoje.strftime("%Y-%m-%d"))
        except Exception:
            data_pg = hoje.strftime("%Y-%m-%d")
        valor_orig = float(ma.get("valor_original") or 0) or float(ma.get("valor") or 0)
        desc_id = _desconto_id_vigente(cur, aluno_id, academia_id, data_pg)
        cur.execute(
            """UPDATE mensalidade_aluno
               SET valor_original = %s, desconto_aplicado = %s, valor = 0, id_desconto = %s,
                   status = 'pago', status_pagamento = 'pago', data_pagamento = %s, valor_pago = 0
               WHERE id = %s""",
            (valor_orig, round(float(vd), 2), desc_id, data_pg, ma["id"]),
        )
        try:
            cur.execute("SELECT id FROM receitas WHERE id_mensalidade_aluno = %s LIMIT 1", (ma["id"],))
            if not cur.fetchone():
                descricao = f"Mensalidade {ma.get('plano_nome') or 'Plano'} - {ma.get('aluno_nome') or 'Aluno'} (Desconto integral)"
                try:
                    cur.execute(
                        "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, criado_por) VALUES (%s, 0, %s, 'Mensalidades', %s, %s, %s)",
                        (descricao, data_pg, academia_id, ma["id"], criado_por),
                    )
                except Exception:
                    cur.execute(
                        "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno) VALUES (%s, 0, %s, 'Mensalidades', %s, %s)",
                        (descricao, data_pg, academia_id, ma["id"]),
                    )
        except Exception:
            pass
        n += 1
    return n


def _ma_enriquecer_exibicao(ma, aluno_id, id_academia, hoje=None):
    """Preenche tem_juros, multa/juros, valores integral/desconto/final (igual lista mensalidades)."""
    hoje = hoje or date.today()
    from blueprints.aluno.painel import _calcular_valor_com_juros_multas

    valor_display, _vo_juros, multa_val, juros_val = _calcular_valor_com_juros_multas(ma, hoje)
    ma["multa_val"] = multa_val
    ma["juros_val"] = juros_val
    ma["tem_juros"] = (multa_val or 0) + (juros_val or 0) > 0
    ma_orig_val = ma.get("valor")
    if ma["tem_juros"]:
        ma["valor"] = valor_display
    ma["status_efetivo"] = _status_efetivo(
        ma.get("status"), ma.get("data_vencimento"), ma.get("status_pagamento")
    )
    vi, vd, vf, desconto_nome = _valor_com_desconto(ma, aluno_id, id_academia, hoje)
    if ma.get("tem_juros"):
        ma["valor"] = ma_orig_val
    ma["valor_integral"] = vi
    ma["valor_desconto"] = vd
    ma["valor_final"] = vf
    ma["desconto_nome"] = desconto_nome
    ma["tem_desconto"] = vd > 0
    return ma


def _fp_catalog_table_exists(cursor):
    try:
        cursor.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = 'formas_pagamento_catalogo'
            LIMIT 1
            """
        )
        return cursor.fetchone() is not None
    except Exception:
        return False


def _ensure_catalog_sync_academia(cursor, id_academia):
    """Com catálogo: garante Dinheiro/PIX/Boleto no catálogo da associação e uma linha em formas_pagamento por item."""
    cursor.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_academia,))
    row = cursor.fetchone()
    if not row or not row.get("id_associacao"):
        return False
    id_assoc = int(row["id_associacao"])
    for ordem, nome in enumerate(["Dinheiro", "PIX", "Boleto"], start=1):
        cursor.execute(
            """
            INSERT IGNORE INTO formas_pagamento_catalogo (id_associacao, nome, ordem)
            VALUES (%s, %s, %s)
            """,
            (id_assoc, nome, ordem),
        )
    cursor.execute(
        "SELECT id, nome, ordem FROM formas_pagamento_catalogo WHERE id_associacao = %s ORDER BY ordem, nome",
        (id_assoc,),
    )
    for cat in cursor.fetchall():
        cursor.execute(
            """
            INSERT INTO formas_pagamento (id_academia, nome, ordem, ativo, id_catalogo)
            VALUES (%s, %s, %s, 1, %s)
            ON DUPLICATE KEY UPDATE nome = VALUES(nome), ordem = VALUES(ordem)
            """,
            (id_academia, cat["nome"], int(cat["ordem"] or 0), cat["id"]),
        )
    return True


def _ensure_formas_padrao(cursor, id_academia):
    """Garante Dinheiro, PIX e Boleto (catálogo da associação + linhas na academia, ou modo legado)."""
    if not id_academia:
        return
    if _fp_catalog_table_exists(cursor):
        try:
            if _ensure_catalog_sync_academia(cursor, id_academia):
                return
        except Exception:
            pass
    try:
        cursor.execute(
            "SELECT COUNT(*) AS c FROM formas_pagamento WHERE id_academia = %s",
            (id_academia,),
        )
        one = cursor.fetchone()
        c = one.get("c", 0) if isinstance(one, dict) else (one[0] if one else 0)
        if c and int(c) > 0:
            return
        for ordem, nome in enumerate(["Dinheiro", "PIX", "Boleto"], start=1):
            cursor.execute(
                """
                INSERT IGNORE INTO formas_pagamento (id_academia, nome, ordem, ativo)
                VALUES (%s, %s, %s, 1)
                """,
                (id_academia, nome, ordem),
            )
    except Exception:
        pass


def _normaliza_forma_academia_catalogo_row(row):
    """ativo/fp_id consistentes para o template (MySQL pode devolver tipos que no Jinja viram truthy errado)."""
    if not row:
        return row
    v = row.get("ativo")
    try:
        row["ativo"] = 1 if int(v) != 0 else 0
    except (TypeError, ValueError):
        row["ativo"] = 1 if v in (True, "1", "t", "true", "yes") else 0
    fid = row.get("fp_id")
    if fid is not None:
        try:
            row["fp_id"] = int(fid)
        except (TypeError, ValueError):
            row["fp_id"] = None
    return row


def _sync_catalog_item_to_academias(cursor, id_associacao, catalog_id, nome, ordem):
    """Cria/atualiza linhas em formas_pagamento para todas as academias da associação."""
    cursor.execute("SELECT id FROM academias WHERE id_associacao = %s", (id_associacao,))
    for r in cursor.fetchall():
        aid = r["id"]
        cursor.execute(
            """
            INSERT INTO formas_pagamento (id_academia, nome, ordem, ativo, id_catalogo)
            VALUES (%s, %s, %s, 1, %s)
            ON DUPLICATE KEY UPDATE nome = VALUES(nome), ordem = VALUES(ordem)
            """,
            (aid, nome[:80], int(ordem), catalog_id),
        )


def _ids_academia_mensalidade_para_formas(ma_row, id_academia_sessao):
    """
    Academias em que a forma de pagamento pode estar cadastrada: plano (mensalidades),
    unidade do aluno e a da sessão. Evita rejeitar PIX/dinheiro quando o select veio
    de outra unidade ainda alinhada ao negócio.
    """
    out = []
    for key in ("id_academia", "aluno_id_academia"):
        v = ma_row.get(key) if ma_row else None
        if v is not None:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                pass
    if id_academia_sessao is not None:
        try:
            out.append(int(id_academia_sessao))
        except (TypeError, ValueError):
            pass
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _forma_pagamento_ativa_em_academias(vcur, forma_id, ids_academias):
    if forma_id <= 0 or not ids_academias:
        return False
    ph = ",".join(["%s"] * len(ids_academias))
    vcur.execute(
        f"SELECT id FROM formas_pagamento WHERE id = %s AND ativo = 1 AND id_academia IN ({ph})",
        (forma_id,) + tuple(ids_academias),
    )
    return vcur.fetchone() is not None


def _parse_valor(val: str):
    """Converte string para valor decimal (aceita , ou .)."""
    if not val:
        return None
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except (ValueError, InvalidOperation):
        return None


def _get_academias_for_select():
    """Retorna lista de academias para dropdown (quando usuário tem múltiplas)."""
    ids = _get_academias_ids()
    if not ids:
        return []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT id, nome FROM academias WHERE id IN ({placeholders}) ORDER BY nome", tuple(ids))
    rows = cur.fetchall()
    conn.close()
    return rows


def _get_academias_ids():
    """Retorna IDs de academias acessíveis pelo usuário (prioridade: usuarios_academias)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ids = []
    try:
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas:
            conn.close()
            return vinculadas
        # Modo academia: sem vínculo em usuarios_academias, usar sessão / usuário (senão IN () quebra e financeiro falha)
        if session.get("modo_painel") == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
            aid = session.get("academia_gerenciamento_id") or session.get("finance_academia_id") or getattr(current_user, "id_academia", None)
            conn.close()
            try:
                if aid is not None:
                    return [int(aid)]
            except (TypeError, ValueError):
                pass
            return []
        if current_user.has_role("admin"):
            cur.execute("SELECT id FROM academias")
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT ac.id FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s",
                (getattr(current_user, "id_federacao", None),),
            )
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (getattr(current_user, "id_associacao", None),))
            ids = [r["id"] for r in cur.fetchall()]
    except Exception:
        pass
    conn.close()
    return ids


def _get_academia_id():
    """Academia ativa para o financeiro (session ou primeira disponível).
    Sincroniza com academia_gerenciamento_id para aplicar o filtro em todos os acessos."""
    ids = _get_academias_ids()
    if not ids:
        return None
    if len(ids) == 1:
        aid = ids[0]
        session["finance_academia_id"] = aid
        session["academia_gerenciamento_id"] = aid
        return aid
    # Prioridade: request > academia_gerenciamento (seleção global) > finance_academia_id
    aid = (
        request.args.get("academia_id", type=int)
        or session.get("academia_gerenciamento_id")
        or session.get("finance_academia_id")
    )
    if aid and aid in ids:
        session["finance_academia_id"] = aid
        session["academia_gerenciamento_id"] = aid
        return aid
    aid = ids[0]
    session["finance_academia_id"] = aid
    session["academia_gerenciamento_id"] = aid
    return aid


def _financeiro_exige_modo_academia():
    """Garante que o módulo financeiro (gestão) só seja acessível em modo academia.
    Exceções: informar_pagamento_mensalidade; formas_pagamento em modo Associação ou modo Academia (gestor)."""
    if not current_user.is_authenticated:
        return None
    endpoint = request.endpoint or ""
    if endpoint in ("financeiro.informar_pagamento_mensalidade", "financeiro.cobrancas_por_aluno_json"):
        return None
    if not endpoint.startswith("financeiro."):
        return None
    # Formas de pagamento: modo Associação (gestor assoc.) ou modo Academia (gestor academia / admin)
    if endpoint == "financeiro.formas_pagamento":
        modo_fp = session.get("modo_painel")
        pode_assoc = modo_fp == "associacao" and (
            current_user.has_role("gestor_associacao") or current_user.has_role("admin")
        )
        pode_acad = modo_fp == "academia" and (
            current_user.has_role("gestor_academia") or current_user.has_role("admin")
        )
        if pode_assoc or pode_acad:
            return None
        flash(
            "Formas de pagamento: use o modo Academia (gestor) ou modo Associação (gestor da associação).",
            "warning",
        )
        modo = session.get("modo_painel")
        if modo == "academia":
            return redirect(url_for("financeiro.dashboard"))
        if modo == "associacao":
            return redirect(url_for("associacao.gerenciamento_associacao"))
        if modo == "admin":
            return redirect(url_for("painel.gerenciamento_admin"))
        if modo == "federacao":
            return redirect(url_for("federacao.gerenciamento_federacao"))
        if modo == "aluno":
            return redirect(url_for("painel_aluno.painel"))
        if modo == "responsavel":
            return redirect(url_for("painel_responsavel.meu_perfil"))
        return redirect(url_for("painel.home"))
    if session.get("modo_painel") == "academia":
        return None
    # Redirecionar para o painel do modo atual
    modo = session.get("modo_painel")
    if modo == "admin":
        return redirect(url_for("painel.gerenciamento_admin"))
    if modo == "federacao":
        return redirect(url_for("federacao.gerenciamento_federacao"))
    if modo == "associacao":
        return redirect(url_for("associacao.gerenciamento_associacao"))
    if modo == "aluno":
        return redirect(url_for("painel_aluno.painel"))
    if modo == "responsavel":
        return redirect(url_for("painel_responsavel.meu_perfil"))
    return redirect(url_for("painel.home"))


@bp_financeiro.before_request
def _before_financeiro():
    r = _financeiro_exige_modo_academia()
    if r is not None:
        return r


@bp_financeiro.route("/")
@bp_financeiro.route("/dashboard")
@login_required
def dashboard():
    """Entrada do financeiro — hoje leva ao painel novo (layout próprio).

    O endpoint segue chamado `dashboard` de propósito: todos os
    `url_for('financeiro.dashboard')` espalhados pelos templates passam a cair
    no painel novo sem precisar de alteração. Para voltar ao antigo, troque
    este redirect por `return dashboard_classico()`.
    """
    return redirect(url_for("financeiro_painel.dashboard",
                            academia_id=request.args.get("academia_id")))


@bp_financeiro.route("/dashboard-classico")
@login_required
def dashboard_classico():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    mes_arg = request.args.get("mes")
    mes = int(mes_arg) if (mes_arg and str(mes_arg).isdigit() and 1 <= int(mes_arg) <= 12) else (date.today().month if "mes" not in request.args else None)
    ano = request.args.get("ano", type=int) or date.today().year
    if ano < 2000 or ano > 2100:
        ano = date.today().year

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
        ac = cur.fetchone()
        academia_nome = ac["nome"] if ac else None
    except Exception:
        academia_nome = None

    receitas_mes = despesas_mes = 0.0
    if mes:
        try:
            cur.execute(
                "SELECT COALESCE(SUM(valor), 0) as total FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
                (academia_id, mes, ano),
            )
            receitas_mes = float(cur.fetchone().get("total") or 0)
        except Exception:
            pass
        try:
            cur.execute(
                "SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
                (academia_id, mes, ano),
            )
            despesas_mes = float(cur.fetchone().get("total") or 0)
        except Exception:
            pass
    else:
        try:
            cur.execute(
                "SELECT COALESCE(SUM(valor), 0) as total FROM receitas WHERE id_academia = %s AND YEAR(data) = %s",
                (academia_id, ano),
            )
            receitas_mes = float(cur.fetchone().get("total") or 0)
        except Exception:
            pass
        try:
            cur.execute(
                "SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE id_academia = %s AND YEAR(data) = %s",
                (academia_id, ano),
            )
            despesas_mes = float(cur.fetchone().get("total") or 0)
        except Exception:
            pass

    # Mensalidades: via mensalidades.id_academia ou alunos.id_academia (fallback)
    msg_geradas = msg_pagas = msg_pendentes = msg_atrasadas = 0
    projecao = 0.0
    hoje = date.today()
    rows = []
    has_mes = mes and 1 <= mes <= 12
    mes_ano_clause = "AND MONTH(ma.data_vencimento) = %s AND YEAR(ma.data_vencimento) = %s" if has_mes else "AND YEAR(ma.data_vencimento) = %s"
    mes_ano_params = (mes, ano) if has_mes else (ano,)
    for q in [
        (f"""
            SELECT ma.status, ma.status_pagamento, ma.valor, ma.data_vencimento
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE (m.id_academia = %s OR (m.id_academia IS NULL AND a.id_academia = %s))
            {mes_ano_clause}
            AND ma.status != 'cancelado'
        """, (academia_id, academia_id) + mes_ano_params),
        (f"""
            SELECT ma.status, ma.valor, ma.data_vencimento
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            WHERE m.id_academia = %s
            {mes_ano_clause}
            AND ma.status != 'cancelado'
        """, (academia_id,) + mes_ano_params),
        (f"""
            SELECT ma.status, ma.valor, ma.data_vencimento
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE a.id_academia = %s
            {mes_ano_clause}
            AND ma.status != 'cancelado'
        """, (academia_id,) + mes_ano_params),
    ]:
        try:
            cur.execute(q[0], q[1])
            rows = cur.fetchall()
            for r in rows:
                r.setdefault("status_pagamento", None)
            break
        except Exception:
            continue
    for r in rows:
        msg_geradas += 1
        val = float(r.get("valor") or 0)
        st = (r.get("status") or "").lower()
        st_pag = (r.get("status_pagamento") or "").lower()
        if st == "pago" or st_pag == "pago":
            msg_pagas += 1
        elif st == "atrasado":
            msg_atrasadas += 1
            projecao += val
        elif st == "pendente":
            venc = r.get("data_vencimento")
            try:
                v = venc if isinstance(venc, date) else (date.fromisoformat(str(venc)[:10]) if venc else None)
                if v and v < hoje:
                    msg_atrasadas += 1
                    projecao += val
                else:
                    msg_pendentes += 1
                    projecao += val
            except Exception:
                msg_pendentes += 1
                projecao += val

    conn.close()

    # Mês selecionado é passado? (para card Projeção: atual/futuro = azul "Mensalidades a receber"; passado = vermelho "Em Atraso")
    hoje = date.today()
    mes_eh_passado = False
    if mes and 1 <= mes <= 12 and ano:
        if ano < hoje.year or (ano == hoje.year and mes < hoje.month):
            mes_eh_passado = True

    return render_template(
        "financeiro/dashboard.html",
        academia_nome=academia_nome,
        receitas_mes=receitas_mes,
        despesas_mes=despesas_mes,
        academia_id=academia_id,
        mes=mes,
        ano=ano,
        ano_atual=date.today().year,
        msg_geradas=msg_geradas,
        msg_pagas=msg_pagas,
        msg_pendentes=msg_pendentes,
        msg_atrasadas=msg_atrasadas,
        projecao=round(projecao, 2),
        mes_eh_passado=mes_eh_passado,
    )


@bp_financeiro.route("/descontos")
@login_required
def lista_descontos():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome, tipo, valor, COALESCE(aplicar_apenas_pagamento_em_dia, 1) AS aplicar_apenas_pagamento_em_dia FROM descontos WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    except Exception:
        cur.execute(
            "SELECT id, nome, tipo, valor FROM descontos WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    descontos = cur.fetchall()
    conn.close()
    return render_template(
        "financeiro/descontos/lista_descontos.html",
        descontos=descontos,
        academia_id=academia_id,
    )


@bp_financeiro.route("/descontos/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar_desconto():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        tipo = request.form.get("tipo") or "percentual"
        valor_str = request.form.get("valor") or ""
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aplicar_apenas = 1 if "1" in request.form.getlist("aplicar_apenas_pagamento_em_dia") else 0

        if not nome:
            flash("Informe o nome do desconto.", "danger")
            return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)
        valor = _parse_valor(valor_str)
        if valor is None or valor < 0:
            flash("Informe um valor válido.", "danger")
            return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)
        if tipo == "percentual" and (valor > 100 or valor < 0):
            flash("Percentual deve estar entre 0 e 100.", "danger")
            return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """INSERT INTO descontos (nome, descricao, tipo, valor, id_academia, ativo, aplicar_apenas_pagamento_em_dia)
                       VALUES (%s, %s, %s, %s, %s, 1, %s)""",
                    (nome, descricao, tipo, valor, id_acad, aplicar_apenas),
                )
            except Exception as col_err:
                if "aplicar_apenas_pagamento_em_dia" in str(col_err) or "Unknown column" in str(col_err):
                    cur.execute(
                        "INSERT INTO descontos (nome, descricao, tipo, valor, id_academia, ativo) VALUES (%s, %s, %s, %s, %s, 1)",
                        (nome, descricao, tipo, valor, id_acad),
                    )
                else:
                    raise
            conn.commit()
            conn.close()
            flash("Desconto cadastrado com sucesso.", "success")
            return redirect(url_for("financeiro.lista_descontos", academia_id=academia_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Erro ao salvar desconto: {e}", "danger")
            return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)

    return render_template("financeiro/descontos/cadastrar_desconto.html", academias=academias, academia_id=academia_id)


@bp_financeiro.route("/descontos/editar/<int:desconto_id>", methods=["GET", "POST"])
@login_required
def editar_desconto(desconto_id):
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(
            f"SELECT id, nome, descricao, tipo, valor, id_academia, ativo, COALESCE(aplicar_apenas_pagamento_em_dia, 1) AS aplicar_apenas_pagamento_em_dia FROM descontos WHERE id = %s AND id_academia IN ({ph})",
            (desconto_id,) + tuple(ids),
        )
    except Exception:
        cur.execute(
            f"SELECT id, nome, descricao, tipo, valor, id_academia, ativo FROM descontos WHERE id = %s AND id_academia IN ({ph})",
            (desconto_id,) + tuple(ids),
        )
    desconto = cur.fetchone()
    if desconto and "aplicar_apenas_pagamento_em_dia" not in desconto:
        desconto["aplicar_apenas_pagamento_em_dia"] = 1
    conn.close()

    if not desconto:
        flash("Desconto não encontrado.", "warning")
        return redirect(url_for("financeiro.lista_descontos"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        tipo = request.form.get("tipo") or "percentual"
        valor_str = request.form.get("valor") or ""
        id_acad = request.form.get("id_academia", type=int) or desconto.get("id_academia") or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aplicar_apenas = 1 if "1" in request.form.getlist("aplicar_apenas_pagamento_em_dia") else 0
        ativo = 1 if "1" in request.form.getlist("ativo") else 0

        if not nome:
            flash("Informe o nome do desconto.", "danger")
            desconto["nome"] = request.form.get("nome")
            desconto["descricao"] = request.form.get("descricao")
            desconto["tipo"] = tipo
            desconto["valor"] = valor_str
            return render_template("financeiro/descontos/editar_desconto.html", desconto=desconto, academias=academias, academia_id=academia_id)
        valor = _parse_valor(valor_str)
        if valor is None or valor < 0:
            flash("Informe um valor válido.", "danger")
            desconto["nome"] = nome
            desconto["descricao"] = descricao
            desconto["tipo"] = tipo
            desconto["valor"] = valor_str
            return render_template("financeiro/descontos/editar_desconto.html", desconto=desconto, academias=academias, academia_id=academia_id)
        if tipo == "percentual" and (valor > 100 or valor < 0):
            flash("Percentual deve estar entre 0 e 100.", "danger")
            return render_template("financeiro/descontos/editar_desconto.html", desconto=desconto, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """UPDATE descontos SET nome=%s, descricao=%s, tipo=%s, valor=%s, id_academia=%s, ativo=%s, aplicar_apenas_pagamento_em_dia=%s
                       WHERE id=%s""",
                    (nome, descricao, tipo, valor, id_acad, ativo, aplicar_apenas, desconto_id),
                )
            except Exception as col_err:
                if "aplicar_apenas_pagamento_em_dia" in str(col_err) or "Unknown column" in str(col_err):
                    cur.execute(
                        "UPDATE descontos SET nome=%s, descricao=%s, tipo=%s, valor=%s, id_academia=%s, ativo=%s WHERE id=%s",
                        (nome, descricao, tipo, valor, id_acad, ativo, desconto_id),
                    )
                else:
                    raise
            conn.commit()
            conn.close()
            flash("Desconto atualizado.", "success")
            return redirect(url_for("financeiro.lista_descontos", academia_id=academia_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Erro ao atualizar: {e}", "danger")

    return render_template("financeiro/descontos/editar_desconto.html", desconto=desconto, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/mensalidades")
@login_required
def painel_mensalidades():
    """Hub do módulo Mensalidades: Cadastro, Mensalidades alunos, Gerar cobrança."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    return render_template(
        "financeiro/mensalidades/painel_mensalidades.html",
        academias=academias,
        academia_id=academia_id,
    )


@bp_financeiro.route("/formas-pagamento", methods=["GET", "POST"])
@login_required
def formas_pagamento():
    """Catálogo na associação (se migrations aplicadas); academia só ativa/desativa. Sem catálogo: comportamento anterior."""
    modo_fp = session.get("modo_painel")
    pode_assoc = modo_fp == "associacao" and (
        current_user.has_role("gestor_associacao") or current_user.has_role("admin")
    )
    pode_acad = modo_fp == "academia" and (
        current_user.has_role("gestor_academia") or current_user.has_role("admin")
    )
    if not (pode_assoc or pode_acad):
        flash("Acesso permitido ao gestor da associação (modo Associação) ou ao gestor da academia (modo Academia).", "danger")
        if modo_fp == "academia":
            aid = _get_academia_id()
            if aid:
                return redirect(url_for("academia.configuracoes_academia", academia_id=aid))
            return redirect(url_for("painel.home"))
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    use_catalog = _fp_catalog_table_exists(cur)

    # ── Modo Associação + catálogo: só itens globais da associação ─────────────
    if use_catalog and pode_assoc:
        id_assoc = getattr(current_user, "id_associacao", None)
        if current_user.has_role("admin") and not id_assoc:
            id_assoc = request.args.get("associacao_id", type=int)
        if not id_assoc:
            conn.close()
            flash("Associação não identificada.", "warning")
            return redirect(url_for("associacao.gerenciamento_associacao"))

        if request.method == "POST":
            acao = (request.form.get("acao") or "").strip()
            try:
                if acao == "adicionar_catalogo":
                    nome = (request.form.get("nome") or "").strip()
                    if nome:
                        cur.execute(
                            """
                            SELECT COALESCE(MAX(ordem), 0) + 1 AS o
                            FROM formas_pagamento_catalogo WHERE id_associacao = %s
                            """,
                            (id_assoc,),
                        )
                        row_o = cur.fetchone() or {}
                        ordem = int(row_o.get("o") or 1)
                        cur.execute(
                            """
                            INSERT INTO formas_pagamento_catalogo (id_associacao, nome, ordem)
                            VALUES (%s, %s, %s)
                            """,
                            (id_assoc, nome[:80], ordem),
                        )
                        cid = cur.lastrowid
                        _sync_catalog_item_to_academias(cur, id_assoc, cid, nome[:80], ordem)
                        conn.commit()
                        flash(
                            "Forma incluída no catálogo e criada em todas as academias (ativas). "
                            "Cada academia pode desativar as que não usar.",
                            "success",
                        )
                    else:
                        flash("Informe o nome da forma de pagamento.", "warning")
                elif acao == "excluir_catalogo" and request.form.get("catalogo_id", type=int):
                    cid = request.form.get("catalogo_id", type=int)
                    cur.execute(
                        """
                        DELETE FROM formas_pagamento_catalogo
                        WHERE id = %s AND id_associacao = %s
                        """,
                        (cid, id_assoc),
                    )
                    conn.commit()
                    flash("Forma removida do catálogo.", "success")
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                flash("Ocorreu um erro. Tente novamente mais tarde.", "danger")
            conn.close()
            redir_kw = {}
            if current_user.has_role("admin"):
                redir_kw["associacao_id"] = id_assoc
            return redirect(url_for("financeiro.formas_pagamento", **redir_kw))

        cur.execute(
            """
            SELECT id, nome, ordem FROM formas_pagamento_catalogo
            WHERE id_associacao = %s ORDER BY ordem, nome
            """,
            (id_assoc,),
        )
        cat_rows = cur.fetchall()
        conn.close()
        back_url = url_for("associacao.gerenciamento_associacao")
        return render_template(
            "financeiro/formas_pagamento.html",
            academias=[],
            academia_id=None,
            formas=[],
            formas_catalogo=cat_rows,
            use_catalog=True,
            modo_catalogo_associacao=True,
            id_associacao=id_assoc,
            back_url=back_url,
            formas_modo_contexto=modo_fp,
        )

    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        conn.close()
        return redirect(url_for("painel.home"))

    ac_param = request.args.get("academia_id", type=int) or request.form.get("academia_id", type=int)
    ids = _get_academias_ids()
    if ac_param and ids and ac_param in ids:
        session["finance_academia_id"] = ac_param
        session["academia_gerenciamento_id"] = ac_param
        academia_id = ac_param

    cur = conn.cursor(dictionary=True)

    # ── Modo Academia + catálogo: lista do catálogo da associação + toggle ativo ──
    if use_catalog and pode_acad:
        if request.method == "POST":
            acao = (request.form.get("acao") or "").strip()
            try:
                if acao == "toggle_academia_cat":
                    fp_id = request.form.get("fp_id", type=int)
                    cid = request.form.get("catalogo_id", type=int)
                    if fp_id:
                        cur.execute(
                            """
                            UPDATE formas_pagamento
                            SET ativo = IF(ativo = 1, 0, 1)
                            WHERE id = %s AND id_academia = %s
                            """,
                            (fp_id, academia_id),
                        )
                    elif cid:
                        cur.execute(
                            """
                            SELECT c.nome, c.ordem
                            FROM formas_pagamento_catalogo c
                            INNER JOIN academias ac ON ac.id = %s AND ac.id_associacao = c.id_associacao
                            WHERE c.id = %s
                            """,
                            (academia_id, cid),
                        )
                        cr = cur.fetchone()
                        if cr:
                            cur.execute(
                                """
                                INSERT INTO formas_pagamento (id_academia, nome, ordem, ativo, id_catalogo)
                                VALUES (%s, %s, %s, 1, %s)
                                ON DUPLICATE KEY UPDATE ativo = 1
                                """,
                                (
                                    academia_id,
                                    cr["nome"],
                                    int(cr["ordem"] or 0),
                                    cid,
                                ),
                            )
                    conn.commit()
                    flash("Situação atualizada.", "success")
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                flash("Ocorreu um erro. Tente novamente mais tarde.", "danger")
            conn.close()
            return redirect(url_for("financeiro.formas_pagamento", academia_id=academia_id))

        rows = []
        try:
            _ensure_formas_padrao(cur, academia_id)
            cur.execute(
                """
                SELECT c.id AS catalogo_id, c.nome, c.ordem,
                       fp.id AS fp_id, COALESCE(fp.ativo, 0) AS ativo
                FROM formas_pagamento_catalogo c
                INNER JOIN academias ac ON ac.id = %s AND ac.id_associacao = c.id_associacao
                LEFT JOIN formas_pagamento fp
                  ON fp.id_catalogo = c.id AND fp.id_academia = ac.id
                ORDER BY c.ordem, c.nome
                """,
                (academia_id,),
            )
            rows = cur.fetchall()
            for _r in rows:
                _normaliza_forma_academia_catalogo_row(_r)
        except Exception as e:
            flash(f"Tabela/catálogo indisponível: {e}", "warning")
        conn.close()
        back_url = url_for("academia.configuracoes_academia", academia_id=academia_id)
        academias = _get_academias_for_select()
        return render_template(
            "financeiro/formas_pagamento.html",
            academias=academias,
            academia_id=academia_id,
            formas=rows,
            formas_catalogo=[],
            use_catalog=True,
            modo_catalogo_associacao=False,
            id_associacao=None,
            back_url=back_url,
            formas_modo_contexto=modo_fp,
        )

    # ── Legado (sem tabela de catálogo): igual ao comportamento anterior ────────
    if request.method == "POST":
        acao = (request.form.get("acao") or "").strip()
        try:
            if acao == "adicionar":
                nome = (request.form.get("nome") or "").strip()
                if nome:
                    _ensure_formas_padrao(cur, academia_id)
                    cur.execute(
                        "SELECT COALESCE(MAX(ordem), 0) + 1 AS o FROM formas_pagamento WHERE id_academia = %s",
                        (academia_id,),
                    )
                    row_o = cur.fetchone() or {}
                    ordem = int(row_o.get("o") or 1)
                    cur.execute(
                        """
                        INSERT INTO formas_pagamento (id_academia, nome, ordem, ativo)
                        VALUES (%s, %s, %s, 1)
                        """,
                        (academia_id, nome[:80], ordem),
                    )
                    conn.commit()
                    flash("Forma de pagamento adicionada.", "success")
                else:
                    flash("Informe o nome da forma de pagamento.", "warning")
            elif acao == "toggle" and request.form.get("id", type=int):
                fid = request.form.get("id", type=int)
                cur.execute(
                    """
                    UPDATE formas_pagamento
                    SET ativo = IF(ativo = 1, 0, 1)
                    WHERE id = %s AND id_academia = %s
                    """,
                    (fid, academia_id),
                )
                conn.commit()
                flash("Situação atualizada.", "success")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash("Ocorreu um erro. Tente novamente mais tarde.", "danger")
        conn.close()
        return redirect(url_for("financeiro.formas_pagamento", academia_id=academia_id))

    academias = _get_academias_for_select()
    rows = []
    try:
        _ensure_formas_padrao(cur, academia_id)
        cur.execute(
            """
            SELECT id, nome, ordem, ativo
            FROM formas_pagamento
            WHERE id_academia = %s
            ORDER BY ordem, nome
            """,
            (academia_id,),
        )
        rows = cur.fetchall()
    except Exception as e:
        flash(
            "Tabela indisponível. Execute o script migrations/add_formas_pagamento.sql no banco. "
            f"Detalhe: {e}",
            "warning",
        )
    conn.close()

    if modo_fp == "academia":
        back_url = url_for("academia.configuracoes_academia", academia_id=academia_id)
    else:
        back_url = url_for("associacao.gerenciamento_associacao")

    return render_template(
        "financeiro/formas_pagamento.html",
        academias=academias,
        academia_id=academia_id,
        formas=rows,
        formas_catalogo=[],
        use_catalog=False,
        modo_catalogo_associacao=False,
        id_associacao=None,
        back_url=back_url,
        formas_modo_contexto=modo_fp,
    )


@bp_financeiro.route("/mensalidades/planos")
@login_required
def lista_planos_mensalidades():
    """Lista planos de mensalidade (cadastro)."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome, valor, COALESCE(aplicar_juros_multas, 0) AS aplicar_juros_multas FROM mensalidades WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    except Exception:
        cur.execute(
            "SELECT id, nome, valor FROM mensalidades WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    mensalidades = cur.fetchall()
    conn.close()
    return render_template(
        "financeiro/mensalidades/lista_planos_mensalidades.html",
        mensalidades=mensalidades,
        academia_id=academia_id,
    )


def _atualizar_status_atrasadas(academia_id):
    """Atualiza mensalidades pendentes vencidas para atrasado."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id SET ma.status = 'atrasado' WHERE m.id_academia = %s AND ma.status = 'pendente' AND ma.data_vencimento < CURDATE()",
            (academia_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def _marcar_atrasadas_global():
    """Marca como 'atrasado' todas as mensalidades pendentes vencidas (todas as academias). Retorna a quantidade."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE mensalidade_aluno SET status = 'atrasado' WHERE status = 'pendente' AND data_vencimento < CURDATE()"
        )
        n = cur.rowcount or 0
        conn.commit()
        return n
    except Exception:
        conn.rollback()
        return 0
    finally:
        conn.close()


def _gerar_mensalidades_mes(academia_id, ano, mes):
    """Gera as mensalidades do mês para alunos ATIVOS, replicando a última cobrança não cancelada
    de cada um (mesmo plano, turma, valor e dia de vencimento). Pula quem já tem cobrança não
    cancelada no mês alvo. Retorna (geradas, pulados)."""
    import calendar
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    geradas = 0
    pulados = 0
    try:
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        # Escopo por academia = academia do PLANO (mensalidades.id_academia), não a
        # academia principal do aluno. Assim um aluno vinculado a mais de uma academia
        # gera cobrança em cada academia onde tem plano, sem misturar. Inclui alunos
        # vinculados (alunos_academias), não só os que têm esta como principal.
        _trecho_al, _al_params = filtro_alunos_da_academia(academia_id, alias="a")
        cur.execute(
            f"""
            SELECT ma.aluno_id, ma.mensalidade_id, ma.turma_id, ma.valor, DAY(ma.data_vencimento) AS dia
            FROM mensalidade_aluno ma
            JOIN alunos a ON a.id = ma.aluno_id
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            WHERE {_trecho_al} AND a.status = 'ativo'
              AND ma.status <> 'cancelado' AND m.id_academia = %s
              AND ma.id = (SELECT ma2.id FROM mensalidade_aluno ma2
                           JOIN mensalidades m2 ON m2.id = ma2.mensalidade_id
                           WHERE ma2.aluno_id = ma.aluno_id AND ma2.status <> 'cancelado'
                                 AND m2.id_academia = %s
                           ORDER BY ma2.data_vencimento DESC, ma2.id DESC LIMIT 1)
            """,
            (*_al_params, academia_id, academia_id),
        )
        templates = cur.fetchall()
        for t in templates:
            dia = min(int(t.get("dia") or 1), ultimo_dia)
            venc = date(ano, mes, dia)
            cur.execute(
                """SELECT 1 FROM mensalidade_aluno
                   WHERE aluno_id=%s AND mensalidade_id=%s AND status<>'cancelado'
                     AND YEAR(data_vencimento)=%s AND MONTH(data_vencimento)=%s LIMIT 1""",
                (t["aluno_id"], t["mensalidade_id"], ano, mes),
            )
            if cur.fetchone():
                pulados += 1
                continue

            # Desconto integral (valor final = 0): nada a pagar, já nasce PAGA.
            ma_calc = {
                "valor": t["valor"],
                "mensalidade_id": t["mensalidade_id"],
                "id_academia": academia_id,
                "data_vencimento": venc,
            }
            _vi, _vd, valor_final, _dn = _valor_com_desconto(
                ma_calc, t["aluno_id"], academia_id, hoje=venc)
            isenta = float(valor_final or 0) <= 0

            if isenta:
                status_ins, stpag, dt_pag, valor_pago = "pago", "pago", venc, 0
            else:
                status_ins, stpag, dt_pag, valor_pago = "pendente", "pendente", None, None

            if t.get("turma_id"):
                cur.execute(
                    "INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, turma_id, data_vencimento, valor, status, status_pagamento, data_pagamento, valor_pago) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (t["mensalidade_id"], t["aluno_id"], t["turma_id"], venc, t["valor"], status_ins, stpag, dt_pag, valor_pago),
                )
            else:
                cur.execute(
                    "INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, data_vencimento, valor, status, status_pagamento, data_pagamento, valor_pago) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (t["mensalidade_id"], t["aluno_id"], venc, t["valor"], status_ins, stpag, dt_pag, valor_pago),
                )
            geradas += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return geradas, pulados


@bp_financeiro.route("/cron/rotina-diaria", methods=["GET"])
def cron_rotina_diaria():
    """Rotina diária (cron com token): marca atrasadas e, no dia 1 (ou com ?gerar=1),
    gera as mensalidades do mês para todas as academias.
    Uso: GET /financeiro/cron/rotina-diaria?token=SEU_TOKEN[&gerar=1]"""
    from utils.aniversariantes_push_diario import validar_token_cron
    ok, err = validar_token_cron(request.args.get("token"))
    if not ok:
        return jsonify({"ok": False, "msg": err}), 403

    atrasadas = _marcar_atrasadas_global()

    hoje = date.today()
    gerar = request.args.get("gerar") == "1" or hoje.day == 1
    geradas = 0
    academias_processadas = 0
    sumup_cobradas = 0
    if gerar:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM academias")
        ids = [r[0] for r in cur.fetchall()]
        conn.close()
        for aid in ids:
            try:
                g, _p = _gerar_mensalidades_mes(aid, hoje.year, hoje.month)
                geradas += g
                academias_processadas += 1
            except Exception as e:
                current_app.logger.error(f"Cron gerar mensalidades academia {aid}: {e}")
            # SumUp: recorrência por cartão salvo exige que NÓS iniciemos a cobrança
            # (o gateway não faz débito automático). Dispara após gerar as mensalidades.
            try:
                sumup_cobradas += _cobrar_sumup_recorrentes(aid)
            except Exception as e:
                current_app.logger.error(f"Cron SumUp recorrente academia {aid}: {e}")
    return jsonify({
        "ok": True,
        "atrasadas_marcadas": atrasadas,
        "mensalidades_geradas": geradas,
        "academias_processadas": academias_processadas,
        "sumup_recorrentes_cobradas": sumup_cobradas,
    })


@bp_financeiro.route("/mensalidades/gerar-mes", methods=["POST"])
@login_required
def gerar_mensalidades_mes_manual():
    """Gera manualmente as mensalidades do mês para os alunos ativos da academia atual."""
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("financeiro.painel_mensalidades"))
    hoje = date.today()
    mes = request.form.get("mes", type=int) or hoje.month
    ano = request.form.get("ano", type=int) or hoje.year
    if not (1 <= mes <= 12):
        mes = hoje.month
    if ano < 2000 or ano > 2100:
        ano = hoje.year
    try:
        geradas, pulados = _gerar_mensalidades_mes(academia_id, ano, mes)
        flash(
            f"{geradas} mensalidade(s) gerada(s) para {mes:02d}/{ano}. "
            + (f"{pulados} aluno(s) já tinham cobrança no mês." if pulados else ""),
            "success" if geradas else "info",
        )
    except Exception as e:
        flash(f"Erro ao gerar mensalidades: {e}", "danger")
    return redirect(url_for("financeiro.painel_mensalidades", academia_id=academia_id))


def _dados_relatorio(academia_id, ano, mes):
    """Coleta dados do relatório financeiro do mês: totais, por categoria e inadimplentes."""
    import calendar
    ini = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    d = {"ano": ano, "mes": mes}
    try:
        cur.execute(
            """SELECT COALESCE(NULLIF(categoria,''),'Sem categoria') cat, COALESCE(SUM(valor),0) total, COUNT(*) qtd
               FROM receitas WHERE id_academia=%s AND (cancelada=0 OR cancelada IS NULL)
                 AND data BETWEEN %s AND %s GROUP BY cat ORDER BY total DESC""",
            (academia_id, ini, fim),
        )
        d["receitas_cat"] = [{"cat": r["cat"], "total": float(r["total"] or 0), "qtd": r["qtd"]} for r in cur.fetchall()]
        cur.execute(
            """SELECT COALESCE(NULLIF(categoria,''),'Sem categoria') cat, COALESCE(SUM(valor),0) total, COUNT(*) qtd
               FROM despesas WHERE id_academia=%s AND data BETWEEN %s AND %s
               GROUP BY cat ORDER BY total DESC""",
            (academia_id, ini, fim),
        )
        d["despesas_cat"] = [{"cat": r["cat"], "total": float(r["total"] or 0), "qtd": r["qtd"]} for r in cur.fetchall()]
        d["receitas_total"] = sum(r["total"] for r in d["receitas_cat"])
        d["despesas_total"] = sum(x["total"] for x in d["despesas_cat"])
        d["saldo"] = d["receitas_total"] - d["despesas_total"]

        cond = "(ma.status='atrasado' OR (ma.status='pendente' AND ma.data_vencimento < CURDATE()))"
        cur.execute(
            f"""SELECT a.id, a.nome, COUNT(*) qtd, COALESCE(SUM(ma.valor),0) total, MIN(ma.data_vencimento) venc
                FROM mensalidade_aluno ma JOIN alunos a ON a.id=ma.aluno_id
                WHERE a.id_academia=%s AND {cond}
                GROUP BY a.id, a.nome ORDER BY total DESC""",
            (academia_id,),
        )
        d["inadimplentes"] = cur.fetchall()
        d["inadimplencia_total"] = sum(float(i["total"] or 0) for i in d["inadimplentes"])
    finally:
        cur.close()
        conn.close()
    return d


@bp_financeiro.route("/relatorios")
@login_required
def relatorios():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    hoje = date.today()
    mes = request.args.get("mes", type=int) or hoje.month
    ano = request.args.get("ano", type=int) or hoje.year
    if not (1 <= mes <= 12):
        mes = hoje.month
    if ano < 2000 or ano > 2100:
        ano = hoje.year
    _academias = _get_academias_for_select()
    rel = _dados_relatorio(academia_id, ano, mes)
    return render_template(
        "financeiro/relatorios.html",
        rel=rel, academias=_academias, academia_id=academia_id, mes=mes, ano=ano,
    )


@bp_financeiro.route("/relatorios/export")
@login_required
def relatorios_export():
    from flask import Response
    import csv, io
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    hoje = date.today()
    mes = request.args.get("mes", type=int) or hoje.month
    ano = request.args.get("ano", type=int) or hoje.year
    tipo = (request.args.get("tipo") or "receitas").strip()
    rel = _dados_relatorio(academia_id, ano, mes)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if tipo == "despesas":
        w.writerow(["Categoria", "Qtd", "Total (R$)"])
        for r in rel["despesas_cat"]:
            w.writerow([r["cat"], r["qtd"], f'{r["total"]:.2f}'])
        w.writerow(["TOTAL", "", f'{rel["despesas_total"]:.2f}'])
        nome = f"despesas_{ano}_{mes:02d}.csv"
    elif tipo == "inadimplentes":
        w.writerow(["Aluno", "Cobranças", "Total em atraso (R$)", "Vencimento + antigo"])
        for i in rel["inadimplentes"]:
            venc = i["venc"].strftime("%d/%m/%Y") if i.get("venc") else ""
            w.writerow([i["nome"], i["qtd"], f'{float(i["total"] or 0):.2f}', venc])
        w.writerow(["TOTAL", "", f'{rel["inadimplencia_total"]:.2f}', ""])
        nome = f"inadimplentes_{ano}_{mes:02d}.csv"
    else:
        w.writerow(["Categoria", "Qtd", "Total (R$)"])
        for r in rel["receitas_cat"]:
            w.writerow([r["cat"], r["qtd"], f'{r["total"]:.2f}'])
        w.writerow(["TOTAL", "", f'{rel["receitas_total"]:.2f}'])
        nome = f"receitas_{ano}_{mes:02d}.csv"

    csv_bytes = "﻿" + buf.getvalue()  # BOM p/ acentos no Excel
    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={nome}"},
    )


# ======================================================
# 🔹 Cobrança digital (Asaas — PIX / Boleto)
# ======================================================
def _asaas_config_academia(academia_id):
    """Retorna {habilitado, api_key, ambiente, webhook_token} da academia (ou None)."""
    if not academia_id:
        return None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT asaas_habilitado, asaas_api_key, asaas_ambiente, asaas_webhook_token
               FROM academias WHERE id = %s""",
            (academia_id,),
        )
        return cur.fetchone()
    except Exception:
        return None
    finally:
        conn.close()


def _gateway_config_academia(academia_id):
    """Retorna as credenciais de todos os gateways + o gateway ativo da academia."""
    if not academia_id:
        return None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT id, gateway_pagamento, asaas_habilitado, asaas_api_key, asaas_ambiente,
                      asaas_webhook_token, mercadopago_access_token, infinitepay_handle,
                      cora_client_id, cora_ambiente, cora_certificate, cora_private_key,
                      cora_client_id_prod, cora_certificate_prod, cora_private_key_prod,
                      efi_client_id, efi_client_secret, efi_certificate, efi_pix_key, efi_ambiente,
                      sumup_api_key, sumup_merchant_code, sumup_ambiente, sumup_habilitado,
                      sumup_conexao, sumup_oauth_access_token, sumup_oauth_refresh_token, sumup_oauth_expira_em
               FROM academias WHERE id = %s""",
            (academia_id,),
        )
        return cur.fetchone()
    except Exception:
        return None
    finally:
        conn.close()


def _gateway_ativo(cfg):
    """Retorna o nome do gateway ativo E configurado da academia, ou '' se nenhum."""
    if not cfg:
        return ""
    g = (cfg.get("gateway_pagamento") or "").strip().lower()
    if g == "asaas" and (cfg.get("asaas_api_key") or "").strip():
        return "asaas"
    if g == "mercadopago" and (cfg.get("mercadopago_access_token") or "").strip():
        return "mercadopago"
    if g == "infinitepay" and (cfg.get("infinitepay_handle") or "").strip():
        return "infinitepay"
    if g == "efi" and (cfg.get("efi_client_id") or "").strip() and (cfg.get("efi_certificate") or "").strip() \
            and (cfg.get("efi_pix_key") or "").strip():
        return "efi"
    if g == "cora" and _cora_configurado(cfg):
        return "cora"
    if g == "sumup" and _sumup_configurado(cfg):
        return "sumup"
    return ""


def _cora_ambiente(cfg):
    """'production' ou 'stage' (padrão) da academia."""
    return "production" if (cfg or {}).get("cora_ambiente") == "production" else "stage"


def _cora_credenciais(cfg):
    """(client_id, certificado, chave) do ambiente ativo da academia.

    O Cora emite credenciais distintas por ambiente — a de stage devolve 401
    invalid_client em produção —, por isso cada trio é guardado à parte: as
    colunas sem sufixo são as de stage, as `_prod` as de produção.
    """
    cfg = cfg or {}
    if _cora_ambiente(cfg) == "production":
        return (cfg.get("cora_client_id_prod"), cfg.get("cora_certificate_prod"),
                cfg.get("cora_private_key_prod"))
    return (cfg.get("cora_client_id"), cfg.get("cora_certificate"),
            cfg.get("cora_private_key"))


def _cora_configurado(cfg):
    """True se a academia tem o trio exigido pelo mTLS do Cora NO AMBIENTE ATIVO."""
    if not cfg:
        return False
    return all((v or "").strip() for v in _cora_credenciais(cfg))


def _cora_client(cfg):
    """Constrói o CoraClient com as credenciais do ambiente ativo da academia."""
    from utils.cora import CoraClient
    client_id, certificado, chave = _cora_credenciais(cfg)
    return CoraClient(client_id, certificado, chave, cfg.get("cora_ambiente"))


def _sumup_configurado(cfg):
    """True se a academia tem SumUp utilizável: chave manual OU conexão OAuth, com merchant."""
    if not cfg:
        return False
    tem_merchant = bool((cfg.get("sumup_merchant_code") or "").strip())
    conexao = (cfg.get("sumup_conexao") or "key").strip().lower()
    if conexao == "oauth":
        return tem_merchant and bool((cfg.get("sumup_oauth_refresh_token") or "").strip())
    return tem_merchant and bool((cfg.get("sumup_api_key") or "").strip())


def _sumup_oauth_app():
    """Credenciais do app OAuth da plataforma (um app para todas as academias).
    Definidas por ambiente: SUMUP_OAUTH_CLIENT_ID / SUMUP_OAUTH_CLIENT_SECRET.
    redirect_uri aponta para o nosso callback."""
    import os
    cid = os.environ.get("SUMUP_OAUTH_CLIENT_ID", "").strip()
    csec = os.environ.get("SUMUP_OAUTH_CLIENT_SECRET", "").strip()
    try:
        redirect_uri = url_for("financeiro.sumup_oauth_callback", _external=True)
    except Exception:
        redirect_uri = os.environ.get("SUMUP_OAUTH_REDIRECT", "").strip()
    return cid, csec, redirect_uri


def _sumup_client(cfg):
    """Constrói um SumUpClient para a academia, no modo configurado:
      - 'oauth': usa o access_token (renovando com refresh_token se expirado, e
        persistindo o novo token na academia).
      - 'key' (padrão): usa a chave secreta manual.
    Retorna None se não estiver configurado."""
    from utils.sumup import SumUpClient
    if not _sumup_configurado(cfg):
        return None
    merchant = (cfg.get("sumup_merchant_code") or "").strip()
    ambiente = cfg.get("sumup_ambiente") or "producao"
    conexao = (cfg.get("sumup_conexao") or "key").strip().lower()
    if conexao != "oauth":
        return SumUpClient(cfg.get("sumup_api_key"), merchant, ambiente)
    # Modo OAuth: garante um access_token válido
    token = (cfg.get("sumup_oauth_access_token") or "").strip()
    expira = cfg.get("sumup_oauth_expira_em")
    precisa_renovar = True
    if token and expira:
        try:
            precisa_renovar = expira <= (datetime.now() + timedelta(seconds=120))
        except Exception:
            precisa_renovar = True
    if precisa_renovar:
        cid, csec, _ = _sumup_oauth_app()
        refresh = (cfg.get("sumup_oauth_refresh_token") or "").strip()
        if cid and csec and refresh:
            try:
                from utils.sumup import oauth_refresh
                j = oauth_refresh(cid, csec, refresh)
                token = j.get("access_token") or token
                novo_refresh = j.get("refresh_token") or refresh
                expira_dt = datetime.now() + timedelta(seconds=int(j.get("expires_in") or 3600))
                _sumup_salvar_tokens(cfg.get("id"), token, novo_refresh, expira_dt)
            except Exception as e:
                current_app.logger.error(f"SumUp OAuth refresh (academia {cfg.get('id')}): {e}")
    return SumUpClient(token, merchant, ambiente)


def _sumup_salvar_tokens(academia_id, access_token, refresh_token, expira_em):
    """Persiste os tokens OAuth renovados na academia."""
    if not academia_id:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE academias SET sumup_oauth_access_token=%s, sumup_oauth_refresh_token=%s,
                   sumup_oauth_expira_em=%s WHERE id=%s""",
            (access_token, refresh_token, expira_em, academia_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def gerar_cobranca_matricula(academia_id, *, nome, cpf, email, telefone, valor, precad_id,
                             descricao=None, endereco=None):
    """Gera uma cobrança de MATRÍCULA pelo gateway ativo da academia (PIX/link + QR).
    Usado pelo formulário público de matrícula (sem login). `endereco` (cep/street/
    neighborhood/number/complement) pré-preenche o checkout InfinitePay. Retorna dict
    normalizado ou None se não houver gateway / valor inválido (→ pagamento avulso)."""
    if not academia_id or not valor or float(valor) < 5:
        return None
    cfg = _gateway_config_academia(academia_id)
    if not _gateway_ativo(cfg):
        return None
    return _emitir_cobranca_online(
        cfg, "PIX",
        nome=nome, cpf=cpf, email=email, telefone=telefone,
        valor=float(valor), vencimento=date.today(),
        descricao=descricao or f"Matrícula - {nome}",
        origem="precadastro", registro_id=precad_id, endereco=endereco,
    )


def _gateway_tem_recorrencia(cfg, gw):
    """True se o gateway informado tem credencial para recorrência."""
    if not cfg:
        return False
    if gw == "asaas":
        return bool((cfg.get("asaas_api_key") or "").strip())
    if gw == "mercadopago":
        return bool((cfg.get("mercadopago_access_token") or "").strip())
    if gw == "sumup":
        return _sumup_configurado(cfg)
    return False


def _gateways_recorrencia(cfg):
    """Lista de gateways de recorrência configurados na academia."""
    out = []
    if _gateway_tem_recorrencia(cfg, "asaas"):
        out.append("asaas")
    if _gateway_tem_recorrencia(cfg, "mercadopago"):
        out.append("mercadopago")
    if _gateway_tem_recorrencia(cfg, "sumup"):
        out.append("sumup")
    return out


def _gateway_recorrencia(cfg):
    """Gateway usado para recorrência. RESPEITA o gateway escolhido nas configurações:
    se o gateway ativo suportar recorrência (Asaas, Mercado Pago ou SumUp) e tiver
    credencial, usa ele. Só cai para outro configurado quando o ativo não suporta
    recorrência (ex.: InfinitePay/EFÍ)."""
    if not cfg:
        return ""
    g = (cfg.get("gateway_pagamento") or "").strip().lower()
    if g in ("asaas", "mercadopago", "sumup") and _gateway_tem_recorrencia(cfg, g):
        return g
    if _gateway_tem_recorrencia(cfg, "asaas"):
        return "asaas"
    if _gateway_tem_recorrencia(cfg, "mercadopago"):
        return "mercadopago"
    if _gateway_tem_recorrencia(cfg, "sumup"):
        return "sumup"
    return ""


def _opcoes_recorrencia(cfg):
    """Opções de recorrência (método) do gateway escolhido para a academia.
    Asaas: cartão + PIX recorrente. Mercado Pago / SumUp: cartão (sem PIX recorrente)."""
    gw = _gateway_recorrencia(cfg)
    if gw == "asaas":
        return [
            {"val": "asaas:cartao", "label": "Cartão — débito automático", "metodo": "cartao"},
            {"val": "asaas:pix", "label": "PIX recorrente", "metodo": "pix"},
        ]
    if gw == "mercadopago":
        return [{"val": "mercadopago:cartao", "label": "Cartão — débito automático", "metodo": "cartao"}]
    if gw == "sumup":
        return [{"val": "sumup:cartao", "label": "Cartão — débito automático", "metodo": "cartao"}]
    return []


def _online_habilitado_academia(academia_id):
    """True se a academia tem algum gateway de cobrança online ativo e configurado."""
    return bool(_gateway_ativo(_gateway_config_academia(academia_id)))


def _dados_pagador(row):
    """Define o pagador da cobrança online: SEMPRE o responsável financeiro quando
    informado (nome + CPF). Se o aluno não tiver responsável financeiro cadastrado,
    usa os dados do próprio aluno.

    O telefone do responsável financeiro (obrigatório no cadastro) é priorizado,
    com fallback para o telefone do aluno — usado p.ex. no checkout InfinitePay.

    `row` deve conter: nome, cpf, telefone e, quando houver, responsavel_financeiro_nome /
    responsavel_financeiro_cpf / responsavel_financeiro_telefone.
    Retorna (nome, cpf, telefone) — CPF apenas com dígitos.
    """
    resp_tel = (str(row.get("responsavel_financeiro_telefone") or "").strip()) or row.get("telefone")
    resp_cpf = "".join(filter(str.isdigit, str(row.get("responsavel_financeiro_cpf") or "")))
    if resp_cpf:
        resp_nome = (str(row.get("responsavel_financeiro_nome") or "").strip()) or row.get("nome")
        return resp_nome, resp_cpf, resp_tel
    aluno_cpf = "".join(filter(str.isdigit, str(row.get("cpf") or "")))
    return row.get("nome"), aluno_cpf, resp_tel


def _endereco_aluno(row):
    """Monta o endereço do aluno no formato esperado pela InfinitePay (objeto address).

    `city`/`state` são ignorados pela InfinitePay, mas o boleto registrado do Cora
    exige o endereço completo — por isso vão sempre no dict.
    """
    return {
        "cep": row.get("cep"),
        "street": row.get("rua"),
        "neighborhood": row.get("bairro"),
        "number": row.get("numero"),
        "complement": row.get("complemento"),
        "city": row.get("cidade"),
        "state": row.get("estado"),
    }


@bp_financeiro.route("/cobranca/<origem>/<int:registro_id>/status")
@login_required
def status_cobranca(origem, registro_id):
    """Diz se a cobrança já foi paga — a tela consulta enquanto o QR está aberto.

    Normalmente a baixa vem do webhook do gateway; com `?gw=1` a rota também
    pergunta ao Cora, o que confirma o pagamento na hora e serve de rede de
    segurança se o webhook falhar. A tela alterna as duas formas para não
    martelar a API do banco.
    """
    if origem not in ("mensalidade", "avulsa"):
        return jsonify({"erro": "origem inválida"}), 400

    ids = _get_academias_ids()
    if not ids:
        return jsonify({"erro": "sem academia"}), 403
    ph = ",".join(["%s"] * len(ids))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if origem == "mensalidade":
            cur.execute(
                f"""SELECT ma.id, ma.status, ma.status_pagamento, ma.gateway, ma.asaas_payment_id,
                           a.id_academia
                    FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                    WHERE ma.id=%s AND a.id_academia IN ({ph})""",
                (registro_id,) + tuple(ids),
            )
        else:
            cur.execute(
                f"""SELECT id, status, NULL AS status_pagamento, gateway, asaas_payment_id, id_academia
                    FROM cobranca_avulsa WHERE id=%s AND id_academia IN ({ph})""",
                (registro_id,) + tuple(ids),
            )
        rec = cur.fetchone()
    finally:
        conn.close()

    if not rec:
        return jsonify({"erro": "não encontrada"}), 404

    pago = (rec.get("status") or "").lower() == "pago" or rec.get("status_pagamento") == "pago"

    if not pago and request.args.get("gw") == "1" and (rec.get("gateway") or "") == "cora" \
            and rec.get("asaas_payment_id"):
        cfg = _gateway_config_academia(rec["id_academia"])
        if _cora_configurado(cfg):
            try:
                inv = _cora_client(cfg).consultar(rec["asaas_payment_id"]) or {}
                if str(inv.get("status") or "").upper() in ("PAID", "SETTLED"):
                    valor_pago = None
                    try:
                        cents = inv.get("total_paid") or inv.get("total_amount")
                        valor_pago = float(cents) / 100.0 if cents else None
                    except (TypeError, ValueError):
                        valor_pago = None
                    _baixar_cobranca_paga(origem, registro_id, valor_pago, "Cora")
                    pago = True
            except Exception as e:
                current_app.logger.info(
                    "Consulta de status no Cora falhou (%s %s): %s", origem, registro_id, e
                )

    return jsonify({"pago": pago, "status": (rec.get("status") or "").lower()})


def _cancelar_no_gateway(cfg, gateway, payment_id):
    """Cancela a cobrança anterior no gateway, quando ele permite. Best-effort.

    Usado ao trocar o tipo (PIX <-> boleto) de um registro que já tinha cobrança:
    sem isso ficariam duas cobranças abertas para a mesma dívida, e o pagador
    poderia pagar as duas.
    """
    gateway = (gateway or "").lower()
    if not payment_id:
        return
    if gateway != "cora":
        # Só o cliente do Cora expõe cancelamento hoje; nos demais a cobrança
        # antiga fica aberta e precisa ser cancelada no painel do gateway.
        current_app.logger.info(
            "Cobrança anterior %s (%s) não foi cancelada: gateway sem cancelamento pela API.",
            payment_id, gateway or "?",
        )
        return
    try:
        _cora_client(cfg).cancelar(payment_id)
    except Exception as e:
        current_app.logger.warning(
            "Não deu para cancelar a cobrança anterior no Cora (%s): %s", payment_id, e
        )


def _cobranca_online_em_aberto(rec):
    """True se o registro já tem cobrança online emitida e ainda não paga."""
    return bool((rec.get("asaas_payment_id") or "").strip()
                and (rec.get("status") or "").lower() in ("pendente", "atrasado"))


def _cobranca_gateway_ainda_vale(cfg, gateway, payment_id):
    """A cobrança emitida ainda é pagável no gateway?

    False só quando dá para confirmar que morreu (cancelada no app do banco, por
    exemplo) — aí faz sentido emitir outra. None quando não há como perguntar, e
    nesse caso a decisão fica com o estado gravado aqui.
    """
    if (gateway or "").lower() != "cora" or not payment_id:
        return None
    try:
        status = str((_cora_client(cfg).consultar(payment_id) or {}).get("status") or "").upper()
    except Exception as e:
        current_app.logger.info("Não deu para consultar a invoice %s no Cora: %s", payment_id, e)
        return None
    return status in ("DRAFT", "OPEN", "IN_PAYMENT", "LATE")


def _emitir_cobranca_online(cfg, tipo, *, nome, cpf, email, telefone, valor, vencimento,
                            descricao, origem, registro_id, endereco=None):
    """Cria a cobrança no gateway ATIVO da academia. Retorna dict normalizado:
    {gateway, payment_id, tipo, boleto_url, pix_qrcode, pix_copia_cola}.
    Para InfinitePay, tipo='LINK' e boleto_url contém o link de checkout.
    endereco (dict): pré-preenche o endereço no checkout InfinitePay (mesmo do aluno)."""
    gw = _gateway_ativo(cfg)
    ext = f"{origem}-{registro_id}"
    if gw == "asaas":
        row = {
            "nome": nome, "cpf": cpf, "email": email, "telefone": telefone,
            "valor": valor, "data_vencimento": vencimento, "id": registro_id,
            "asaas_api_key": cfg.get("asaas_api_key"), "asaas_ambiente": cfg.get("asaas_ambiente"),
        }
        r = _emitir_cobranca_asaas(row, tipo, descricao)
    elif gw == "mercadopago":
        from utils.mercadopago import MercadoPagoClient
        r = MercadoPagoClient(cfg.get("mercadopago_access_token")).criar_cobranca(
            tipo, valor, vencimento, nome, cpf, email, telefone,
            descricao=descricao, external_reference=ext,
        )
    elif gw == "infinitepay":
        from utils.infinitepay import InfinitePayClient
        try:
            webhook_url = url_for("financeiro.webhook_infinitepay", _external=True)
        except Exception:
            webhook_url = None
        r = InfinitePayClient(cfg.get("infinitepay_handle")).criar_link(
            valor, descricao, order_nsu=ext, webhook_url=webhook_url,
            nome=nome, email=email, telefone=telefone, endereco=endereco,
        )
        # QR Code do link de checkout (InfinitePay não devolve QR PIX próprio)
        try:
            from utils.qrcode_util import gerar_qr_base64
            r["pix_qrcode"] = gerar_qr_base64(r.get("boleto_url"))
        except Exception:
            pass
    elif gw == "efi":
        # EFÍ (API Pix): gera sempre cobrança Pix (QR + copia e cola).
        from utils.efi import EfiClient
        cli = EfiClient(
            cfg.get("efi_client_id"), cfg.get("efi_client_secret"),
            cfg.get("efi_certificate"), cfg.get("efi_pix_key"), cfg.get("efi_ambiente"),
        )
        r = cli.criar_cobranca_pix(
            valor, nome=nome, cpf=cpf, descricao=descricao, external_reference=ext,
        )
    elif gw == "cora":
        # Cora: boleto registrado que já vem com QR Code PIX — o pagador escolhe.
        r = _cora_client(cfg).criar_cobranca(
            tipo, valor, vencimento, nome, cpf, email=email, telefone=telefone,
            descricao=descricao, external_reference=ext, endereco=endereco,
        )
    elif gw == "sumup":
        # SumUp: cria um checkout e hospeda o widget de pagamento numa página nossa.
        # O "link" enviado ao pagador é a nossa página /pagamento/sumup/<checkout_id>,
        # onde ele paga com cartão (e PIX/boleto se habilitados na conta SumUp).
        import uuid as _uuid
        cli = _sumup_client(cfg)
        try:
            return_url = url_for("financeiro.webhook_sumup", _external=True)
        except Exception:
            return_url = None
        try:
            redirect_url = url_for("financeiro.sumup_retorno", ref=ext, _external=True)
        except Exception:
            redirect_url = None
        # A SumUp exige checkout_reference único; sufixo evita colisão na regeração.
        # A resolução (status/webhook) é por checkout_id, não pela referência.
        ref_sumup = f"{ext}-{_uuid.uuid4().hex[:8]}"
        chk = cli.criar_checkout(
            valor, descricao, ref_sumup,
            return_url=return_url, redirect_url=redirect_url, email=email,
        )
        checkout_id = chk.get("id")
        try:
            pagina = url_for("financeiro.sumup_pagamento", checkout_id=checkout_id, _external=True)
        except Exception:
            pagina = None
        r = {
            "payment_id": str(checkout_id),
            "tipo": "LINK",
            "boleto_url": pagina,
            "pix_qrcode": None,
            "pix_copia_cola": None,
        }
        # QR Code do link da página de pagamento (a SumUp não devolve QR próprio aqui)
        try:
            from utils.qrcode_util import gerar_qr_base64
            r["pix_qrcode"] = gerar_qr_base64(pagina)
        except Exception:
            pass
    else:
        raise RuntimeError("Nenhum gateway de cobrança online configurado para esta academia.")
    r["gateway"] = gw
    return r


def _asaas_habilitado_academia(academia_id):
    """Compat.: True se a academia tem cobrança online ativa (qualquer gateway)."""
    return _online_habilitado_academia(academia_id)


def _emitir_cobranca_asaas(row, tipo, descricao):
    """Cria a cobrança no Asaas a partir de um registro (mensalidade ou avulsa).

    `row` precisa conter: nome, cpf, email, telefone, valor, data_vencimento, id (=external_reference)
    e as credenciais da academia (asaas_api_key, asaas_ambiente).
    Retorna dict {payment_id, tipo, boleto_url, pix_qrcode, pix_copia_cola}.
    """
    from utils.asaas import AsaasClient
    cli = AsaasClient(row.get("asaas_api_key"), row.get("asaas_ambiente"))
    if not cli.configurado:
        raise RuntimeError("Chave de API do Asaas não configurada para esta academia.")
    customer_id = cli.criar_ou_obter_cliente(row["nome"], row["cpf"], row.get("email"), row.get("telefone"))
    pay = cli.criar_cobranca(
        customer_id, row["valor"], row["data_vencimento"], tipo,
        descricao=descricao, external_reference=row["id"],
    )
    pix_qr = None
    pix_payload = None
    if tipo == "PIX":
        try:
            qr = cli.obter_pix_qrcode(pay["id"])
            pix_qr = qr.get("encodedImage")
            pix_payload = qr.get("payload")
        except Exception:
            pass
    return {
        "payment_id": pay["id"],
        "tipo": tipo,
        "boleto_url": pay.get("bankSlipUrl") or pay.get("invoiceUrl"),
        "pix_qrcode": pix_qr,
        "pix_copia_cola": pix_payload,
    }


@bp_financeiro.route("/mensalidades/<int:ma_id>/asaas", methods=["POST"])
@login_required
def gerar_cobranca_asaas(ma_id):
    """Gera uma cobrança PIX/Boleto no Asaas para uma mensalidade do aluno."""
    academia_id = _get_academia_id()
    destino = request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id)
    tipo = (request.form.get("tipo") or "PIX").upper()
    if tipo not in ("PIX", "BOLETO"):
        tipo = "PIX"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id, ma.valor, ma.data_vencimento, ma.status,
                      ma.asaas_payment_id, ma.asaas_tipo, ma.gateway,
                      a.nome, a.cpf, a.email, a.telefone, a.id_academia,
                      a.responsavel_financeiro_nome, a.responsavel_financeiro_cpf,
                      a.responsavel_financeiro_telefone,
                      a.cep, a.rua, a.numero, a.complemento, a.bairro, a.cidade, a.estado
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               WHERE ma.id = %s""",
            (ma_id,),
        )
        ma = cur.fetchone()
        if not ma:
            flash("Cobrança não encontrada.", "danger")
            return redirect(destino)
        if academia_id and ma["id_academia"] != academia_id and not current_user.has_role("admin"):
            flash("Sem permissão para esta cobrança.", "danger")
            return redirect(destino)
        cfg = _gateway_config_academia(ma["id_academia"])
        if not _gateway_ativo(cfg):
            flash("Cobrança online não está habilitada para esta academia. "
                  "Ative em Configurações da academia → Financeiro.", "warning")
            return redirect(destino)

        # Já emitida: não gera outra. Clicar de novo no PIX/boleto criava uma
        # cobrança nova no gateway a cada clique, deixando várias abertas para a
        # mesma mensalidade. Mesmo tipo => reaproveita; tipo diferente => cancela
        # a anterior antes de emitir a nova.
        if _cobranca_online_em_aberto(ma) and \
                _cobranca_gateway_ainda_vale(cfg, ma.get("gateway"), ma.get("asaas_payment_id")) is not False:
            if (ma.get("asaas_tipo") or "").upper() in (tipo, "LINK"):
                flash("Esta mensalidade já tem cobrança online emitida — use o QR Code e o "
                      "copia e cola que já estão na tela.", "info")
                return redirect(destino)
            _cancelar_no_gateway(cfg, ma.get("gateway"), ma.get("asaas_payment_id"))

        pag_nome, pag_cpf, pag_tel = _dados_pagador(ma)
        r = _emitir_cobranca_online(
            cfg, tipo, nome=pag_nome, cpf=pag_cpf, email=ma.get("email"),
            telefone=pag_tel, valor=ma["valor"], vencimento=ma["data_vencimento"],
            descricao=f"Mensalidade - {ma['nome']}", origem="mensalidade", registro_id=ma_id,
            endereco=_endereco_aluno(ma),
        )
        cur.execute(
            """UPDATE mensalidade_aluno
               SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                   asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s, gateway=%s
               WHERE id=%s""",
            (r["payment_id"], r["tipo"], r["boleto_url"], r["pix_qrcode"], r["pix_copia_cola"], r["gateway"], ma_id),
        )
        conn.commit()
        flash("Cobrança online gerada com sucesso.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao gerar cobrança online (ma {ma_id}): {e}", exc_info=True)
        flash(f"Erro ao gerar cobrança online: {e}", "danger")
    finally:
        conn.close()
    return redirect(destino)


@bp_financeiro.route("/avulsas/<int:av_id>/asaas", methods=["POST"])
@login_required
def gerar_cobranca_asaas_avulsa(av_id):
    """Gera uma cobrança PIX/Boleto no Asaas para uma cobrança avulsa."""
    academia_id = _get_academia_id()
    destino = request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id)
    tipo = (request.form.get("tipo") or "PIX").upper()
    if tipo not in ("PIX", "BOLETO"):
        tipo = "PIX"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ca.id, ca.valor, ca.data_vencimento, ca.descricao, ca.status,
                      ca.asaas_payment_id, ca.asaas_tipo, ca.gateway,
                      a.nome, a.cpf, a.email, a.telefone, ca.id_academia,
                      a.responsavel_financeiro_nome, a.responsavel_financeiro_cpf,
                      a.responsavel_financeiro_telefone,
                      a.cep, a.rua, a.numero, a.complemento, a.bairro, a.cidade, a.estado
               FROM cobranca_avulsa ca
               JOIN alunos a ON a.id = ca.aluno_id
               WHERE ca.id = %s""",
            (av_id,),
        )
        ca = cur.fetchone()
        if not ca:
            flash("Cobrança não encontrada.", "danger")
            return redirect(destino)
        if academia_id and ca["id_academia"] != academia_id and not current_user.has_role("admin"):
            flash("Sem permissão para esta cobrança.", "danger")
            return redirect(destino)
        cfg = _gateway_config_academia(ca["id_academia"])
        if not _gateway_ativo(cfg):
            flash("Cobrança online não está habilitada para esta academia. "
                  "Ative em Configurações da academia → Financeiro.", "warning")
            return redirect(destino)

        # Mesma regra da mensalidade: não emitir duas cobranças para a mesma dívida.
        if _cobranca_online_em_aberto(ca) and \
                _cobranca_gateway_ainda_vale(cfg, ca.get("gateway"), ca.get("asaas_payment_id")) is not False:
            if (ca.get("asaas_tipo") or "").upper() in (tipo, "LINK"):
                flash("Esta cobrança já tem PIX/boleto emitido — use o QR Code e o "
                      "copia e cola que já estão na tela.", "info")
                return redirect(destino)
            _cancelar_no_gateway(cfg, ca.get("gateway"), ca.get("asaas_payment_id"))

        descricao = (ca.get("descricao") or "Cobrança avulsa") + f" - {ca['nome']}"
        pag_nome, pag_cpf, pag_tel = _dados_pagador(ca)
        r = _emitir_cobranca_online(
            cfg, tipo, nome=pag_nome, cpf=pag_cpf, email=ca.get("email"),
            telefone=pag_tel, valor=ca["valor"], vencimento=ca["data_vencimento"],
            descricao=descricao, origem="avulsa", registro_id=av_id,
            endereco=_endereco_aluno(ca),
        )
        cur.execute(
            """UPDATE cobranca_avulsa
               SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                   asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s, gateway=%s
               WHERE id=%s""",
            (r["payment_id"], r["tipo"], r["boleto_url"], r["pix_qrcode"], r["pix_copia_cola"], r["gateway"], av_id),
        )
        conn.commit()
        flash("Cobrança online gerada com sucesso.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao gerar cobrança online (avulsa {av_id}): {e}", exc_info=True)
        flash(f"Erro ao gerar cobrança online: {e}", "danger")
    finally:
        conn.close()
    return redirect(destino)


# =====================================================================
# 🔁 ASSINATURA RECORRENTE (cobrança automática no cartão)
# =====================================================================
def _emitir_assinatura_recorrente(cfg, gw, *, nome, cpf, email, telefone, valor,
                                  descricao, external_reference, academia_id, metodo="cartao"):
    """Cria a assinatura recorrente no gateway ativo. Retorna {subscription_id, url}.
    metodo: 'cartao' (débito automático no cartão) ou 'pix' (PIX recorrente).
    Suportado por Asaas (link recorrente, cartão ou PIX) e Mercado Pago (cartão)."""
    metodo = "pix" if str(metodo).lower() == "pix" else "cartao"
    if gw == "asaas":
        from utils.asaas import AsaasClient
        cli = AsaasClient(cfg.get("asaas_api_key"), cfg.get("asaas_ambiente"))
        return cli.criar_assinatura_recorrente(
            valor, descricao, external_reference=external_reference, nome=nome, metodo=metodo,
        )
    if gw == "mercadopago":
        if metodo == "pix":
            raise RuntimeError("O Mercado Pago não oferece PIX recorrente por aqui — use cartão, "
                               "ou selecione o Asaas para PIX recorrente.")
        from utils.mercadopago import MercadoPagoClient
        try:
            back_url = url_for("financeiro.mensalidades_alunos", academia_id=academia_id, _external=True)
        except Exception:
            back_url = url_for("painel.home", _external=True)
        return MercadoPagoClient(cfg.get("mercadopago_access_token")).criar_assinatura_recorrente(
            valor, descricao, payer_email=email, back_url=back_url, external_reference=external_reference,
        )
    if gw == "sumup":
        if metodo == "pix":
            raise RuntimeError("A SumUp não oferece PIX recorrente — use cartão, ou selecione o Asaas para PIX recorrente.")
        # SumUp: recorrência por CARTÃO SALVO. Criamos um cliente e um checkout de
        # 'setup' (tokeniza o cartão + cobra a 1ª mensalidade). Nas mensalidades
        # seguintes cobramos server-side com o token (ver _cobrar_sumup_recorrentes).
        import uuid as _uuid
        cli = _sumup_client(cfg)
        customer_id = str(external_reference)  # ex.: 'assinatura-<aluno_id>' — id estável do pagador
        cli.criar_ou_obter_cliente(customer_id, nome=nome, email=email, telefone=telefone)
        try:
            return_url = url_for("financeiro.webhook_sumup", _external=True)
        except Exception:
            return_url = None
        try:
            redirect_url = url_for("financeiro.sumup_retorno", _external=True)
        except Exception:
            redirect_url = None
        # checkout_reference único (a SumUp recusa repetido); o customer_id é que fica estável.
        chk = cli.criar_checkout(
            valor, descricao, f"{external_reference}-{_uuid.uuid4().hex[:8]}",
            return_url=return_url, redirect_url=redirect_url, email=email,
            customer_id=customer_id, purpose="SETUP_RECURRING_PAYMENT",
        )
        checkout_id = chk.get("id")
        try:
            pagina = url_for("financeiro.sumup_pagamento", checkout_id=checkout_id, _external=True)
        except Exception:
            pagina = None
        return {"subscription_id": customer_id, "url": pagina, "checkout_id": checkout_id}
    raise RuntimeError("A assinatura recorrente está disponível apenas com Asaas, Mercado Pago ou SumUp.")


def _baixar_mensalidade_recorrente(aluno_id, valor_pago, gateway_nome):
    """Baixa automática de uma cobrança recorrente: marca como paga a mensalidade
    em aberto mais antiga do aluno (pendente/atrasado) e lança a receita."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Marca a assinatura do aluno como ATIVA (pagamento recorrente confirmado)
        cur.execute(
            "UPDATE assinaturas_recorrentes SET status='ativa' WHERE aluno_id=%s AND status<>'cancelada'",
            (aluno_id,),
        )
        conn.commit()
        cur.execute(
            """SELECT ma.id, ma.valor, a.id_academia
               FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
               WHERE ma.aluno_id = %s AND ma.status IN ('pendente','atrasado')
               ORDER BY ma.data_vencimento ASC, ma.id ASC LIMIT 1""",
            (aluno_id,),
        )
        rec = cur.fetchone()
        if not rec:
            current_app.logger.info(f"Recorrência {gateway_nome}: aluno {aluno_id} sem mensalidade em aberto para baixar.")
            return
    finally:
        conn.close()
    _baixar_cobranca_paga("mensalidade", rec["id"], valor_pago, f"{gateway_nome} recorrente")


def _cobrar_sumup_recorrentes(academia_id):
    """Dispara a cobrança mensal das assinaturas SumUp ATIVAS da academia (cartão salvo).
    Diferente de Asaas/Mercado Pago (débito automático pelo gateway), a SumUp exige que
    NÓS iniciemos a cobrança do cartão tokenizado. Para cada assinatura ativa com uma
    mensalidade em aberto, cobra e, se aprovada, dá baixa. Best-effort (logado)."""
    cfg = _gateway_config_academia(academia_id) or {}
    if not (_gateway_tem_recorrencia(cfg, "sumup")):
        return 0
    cli = _sumup_client(cfg)
    if not cli:
        return 0
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cobradas = 0
    try:
        cur.execute(
            """SELECT s.aluno_id, s.subscription_id, s.valor
               FROM assinaturas_recorrentes s
               WHERE s.gateway='sumup' AND s.status='ativa' AND s.id_academia=%s""",
            (academia_id,),
        )
        assinaturas = cur.fetchall()
        for s in assinaturas:
            # Mensalidade em aberto mais antiga do aluno
            cur.execute(
                """SELECT ma.id, ma.valor FROM mensalidade_aluno ma
                   WHERE ma.aluno_id=%s AND ma.status IN ('pendente','atrasado')
                   ORDER BY ma.data_vencimento ASC, ma.id ASC LIMIT 1""",
                (s["aluno_id"],),
            )
            ma = cur.fetchone()
            if not ma:
                continue
            valor = float(ma.get("valor") or s.get("valor") or 0)
            if valor <= 0:
                continue
            try:
                res = cli.cobrar_recorrente(
                    s["subscription_id"], valor, "Mensalidade (recorrente)",
                    f"assinatura-{s['aluno_id']}",
                )
                if str(res.get("status") or "").upper() == "PAID":
                    _baixar_mensalidade_recorrente(s["aluno_id"], valor, "SumUp")
                    cobradas += 1
            except Exception as e:
                current_app.logger.error(f"SumUp recorrente aluno {s['aluno_id']}: {e}")
    finally:
        conn.close()
    return cobradas


@bp_financeiro.route("/aluno/<int:aluno_id>/assinatura-recorrente", methods=["POST"])
@login_required
def criar_assinatura_recorrente(aluno_id):
    """Cria (ou regenera) o link de assinatura recorrente no cartão para um aluno."""
    academia_id = _get_academia_id()
    destino = request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id)
    _valor_raw = (request.form.get("valor") or "").strip().replace(".", "").replace(",", ".") \
        if ("," in (request.form.get("valor") or "")) else (request.form.get("valor") or "").strip()
    try:
        valor = float(_valor_raw) if _valor_raw else None
    except (TypeError, ValueError):
        valor = None
    metodo = "pix" if (request.form.get("metodo") or "cartao").strip().lower() == "pix" else "cartao"
    gateway_escolhido = (request.form.get("gateway") or "").strip().lower()
    # Campo combinado "gateway:metodo" (ex.: "asaas:pix"), se enviado
    _opcao = (request.form.get("opcao_recorrencia") or "").strip().lower()
    if ":" in _opcao:
        _g, _m = _opcao.split(":", 1)
        gateway_escolhido = _g
        metodo = "pix" if _m == "pix" else "cartao"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT a.id, a.nome, a.cpf, a.email, a.telefone, a.id_academia,
                      a.responsavel_financeiro_nome, a.responsavel_financeiro_cpf,
                      a.responsavel_financeiro_telefone
               FROM alunos a WHERE a.id = %s""",
            (aluno_id,),
        )
        al = cur.fetchone()
        if not al:
            flash("Aluno não encontrado.", "danger")
            return redirect(destino)
        if academia_id and al["id_academia"] != academia_id and not current_user.has_role("admin"):
            flash("Sem permissão para este aluno.", "danger")
            return redirect(destino)

        cfg = _gateway_config_academia(al["id_academia"])
        # Usa o gateway escolhido (se tiver credencial); senão, o padrão de recorrência
        if gateway_escolhido in ("asaas", "mercadopago", "sumup") and _gateway_tem_recorrencia(cfg, gateway_escolhido):
            gw = gateway_escolhido
        else:
            gw = _gateway_recorrencia(cfg)
        if gw not in ("asaas", "mercadopago", "sumup"):
            flash("A mensalidade recorrente exige Asaas, Mercado Pago ou SumUp configurado. "
                  "Informe as credenciais em Configurações da academia → Financeiro.", "warning")
            return redirect(destino)
        if gw == "sumup" and metodo == "pix":
            flash("A SumUp não oferece PIX recorrente — use cartão, ou selecione o Asaas para PIX recorrente.", "warning")
            return redirect(destino)

        if not valor or valor < 5:
            flash("Informe um valor válido para a recorrência (mínimo R$ 5,00).", "warning")
            return redirect(destino)

        if gw == "mercadopago" and metodo == "pix":
            flash("PIX recorrente não está disponível no Mercado Pago. Use cartão, ou selecione o Asaas para PIX recorrente.", "warning")
            return redirect(destino)

        pag_nome, pag_cpf, pag_tel = _dados_pagador(al)
        if gw == "mercadopago" and not (al.get("email") or "").strip():
            flash("Para assinatura no Mercado Pago é necessário o e-mail do aluno. Cadastre o e-mail e tente novamente.", "warning")
            return redirect(destino)

        ext = f"assinatura-{aluno_id}"
        res = _emitir_assinatura_recorrente(
            cfg, gw, nome=pag_nome, cpf=pag_cpf, email=al.get("email"), telefone=pag_tel,
            valor=valor, descricao=f"Mensalidade - {al['nome']}",
            external_reference=ext, academia_id=al["id_academia"], metodo=metodo,
        )

        cur.execute(
            "SELECT id FROM assinaturas_recorrentes WHERE aluno_id=%s AND gateway=%s LIMIT 1",
            (aluno_id, gw),
        )
        ex = cur.fetchone()
        if ex:
            cur.execute(
                """UPDATE assinaturas_recorrentes
                   SET subscription_id=%s, checkout_url=%s, valor=%s, metodo=%s, status='pendente',
                       id_academia=%s, sumup_setup_checkout_id=%s
                   WHERE id=%s""",
                (res["subscription_id"], res["url"], valor, metodo, al["id_academia"],
                 res.get("checkout_id"), ex["id"]),
            )
            assinatura_id = ex["id"]
        else:
            cur.execute(
                """INSERT INTO assinaturas_recorrentes
                   (aluno_id, id_academia, gateway, metodo, subscription_id, checkout_url, valor, status, sumup_setup_checkout_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'pendente',%s)""",
                (aluno_id, al["id_academia"], gw, metodo, res["subscription_id"], res["url"], valor,
                 res.get("checkout_id")),
            )
            assinatura_id = cur.lastrowid
        conn.commit()
        return redirect(url_for("financeiro.assinatura_recorrente_link", assinatura_id=assinatura_id))
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao criar assinatura recorrente (aluno {aluno_id}): {e}", exc_info=True)
        _msg = str(e)
        if "invalid_access_token" in _msg or "chave de API" in _msg.lower() or "access_token" in _msg.lower():
            flash("Credenciais inválidas no gateway de recorrência. Verifique a chave de API do Asaas "
                  "(ou o Access Token do Mercado Pago) e o ambiente (Sandbox/Produção) em "
                  "Configurações da academia → Financeiro.", "danger")
        else:
            flash(f"Erro ao criar assinatura recorrente: {e}", "danger")
        return redirect(destino)
    finally:
        conn.close()


@bp_financeiro.route("/assinatura-recorrente/<int:assinatura_id>")
@login_required
def assinatura_recorrente_link(assinatura_id):
    """Mostra o link (e QR) da assinatura recorrente para enviar ao aluno."""
    academia_id = _get_academia_id()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT s.*, a.nome AS aluno_nome, a.id_academia
               FROM assinaturas_recorrentes s JOIN alunos a ON a.id = s.aluno_id
               WHERE s.id = %s""",
            (assinatura_id,),
        )
        s = cur.fetchone()
    finally:
        conn.close()
    if not s:
        flash("Assinatura não encontrada.", "danger")
        return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
    if academia_id and s["id_academia"] != academia_id and not current_user.has_role("admin"):
        flash("Sem permissão.", "danger")
        return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
    from utils.qrcode_util import gerar_qr_base64
    qr = gerar_qr_base64(s.get("checkout_url"))
    back_url = request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id)
    return render_template("financeiro/assinatura_link.html", s=s, qr=qr, back_url=back_url)


@bp_financeiro.route("/assinaturas-recorrentes")
@login_required
def assinaturas_recorrentes():
    """Lista todas as assinaturas recorrentes da academia, classificadas por forma de pagamento."""
    academia_id = _get_academia_id()
    filtro = (request.args.get("forma") or "").strip().lower()  # cartao | pix | ''
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        params = []
        where = "1=1"
        if academia_id:
            where += " AND s.id_academia = %s"
            params.append(academia_id)
        if filtro in ("cartao", "pix"):
            where += " AND s.metodo = %s"
            params.append(filtro)
        cur.execute(
            f"""SELECT s.*, a.nome AS aluno_nome, ac.nome AS academia_nome
                FROM assinaturas_recorrentes s
                JOIN alunos a ON a.id = s.aluno_id
                LEFT JOIN academias ac ON ac.id = s.id_academia
                WHERE {where}
                ORDER BY (s.status='ativa') DESC, s.criado_em DESC""",
            tuple(params),
        )
        assinaturas = cur.fetchall()
        # Resumo por forma
        resumo = {"cartao": 0, "pix": 0, "ativas": 0, "pendentes": 0, "canceladas": 0}
        for s in assinaturas:
            if (s.get("metodo") or "cartao") == "pix":
                resumo["pix"] += 1
            else:
                resumo["cartao"] += 1
            st = s.get("status") or "pendente"
            resumo["ativas" if st == "ativa" else ("canceladas" if st == "cancelada" else "pendentes")] += 1
    finally:
        conn.close()
    return render_template(
        "financeiro/assinaturas_recorrentes.html",
        assinaturas=assinaturas, resumo=resumo, academia_id=academia_id, filtro=filtro,
    )


@bp_financeiro.route("/assinatura-recorrente/<int:assinatura_id>/cancelar", methods=["POST"])
@login_required
def cancelar_assinatura_recorrente(assinatura_id):
    """Cancela uma assinatura recorrente (marca como cancelada e tenta cancelar no gateway)."""
    academia_id = _get_academia_id()
    destino = request.referrer or url_for("financeiro.assinaturas_recorrentes", academia_id=academia_id)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM assinaturas_recorrentes WHERE id = %s", (assinatura_id,))
        s = cur.fetchone()
        if not s:
            flash("Assinatura não encontrada.", "danger")
            return redirect(destino)
        if academia_id and s["id_academia"] != academia_id and not current_user.has_role("admin"):
            flash("Sem permissão.", "danger")
            return redirect(destino)
        # Best-effort: cancelar no gateway
        try:
            cfg = _gateway_config_academia(s["id_academia"])
            if s["gateway"] == "asaas" and s.get("subscription_id"):
                from utils.asaas import AsaasClient
                _cli = AsaasClient(cfg.get("asaas_api_key"), cfg.get("asaas_ambiente"))
                import requests as _rq
                _rq.delete(f"{_cli._base_url()}/paymentLinks/{s['subscription_id']}", headers=_cli._headers(), timeout=20)
            elif s["gateway"] == "mercadopago" and s.get("subscription_id"):
                import requests as _rq
                _rq.put(
                    f"https://api.mercadopago.com/preapproval/{s['subscription_id']}",
                    headers={"Authorization": f"Bearer {cfg.get('mercadopago_access_token')}", "Content-Type": "application/json"},
                    json={"status": "cancelled"}, timeout=20,
                )
        except Exception as e:
            current_app.logger.error(f"Cancelar assinatura {assinatura_id} no gateway falhou: {e}")
        cur.execute("UPDATE assinaturas_recorrentes SET status='cancelada' WHERE id=%s", (assinatura_id,))
        conn.commit()
        flash("Assinatura recorrente cancelada.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao cancelar assinatura {assinatura_id}: {e}", exc_info=True)
        flash("Erro ao cancelar a assinatura.", "danger")
    finally:
        conn.close()
    return redirect(destino)


@bp_financeiro.route("/webhook/asaas", methods=["POST"])
@csrf.exempt
def webhook_asaas():
    """Recebe eventos do Asaas e dá baixa automática na mensalidade quando o pagamento é confirmado."""
    data = request.get_json(silent=True) or {}
    event = data.get("event")
    pay = data.get("payment") or {}
    payment_id = pay.get("id")
    if not payment_id:
        return jsonify({"ok": False, "msg": "sem payment id"}), 400

    if event in ("PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            # Localiza a cobrança: primeiro em mensalidades, depois em avulsas.
            cur.execute(
                """SELECT 'mensalidade' AS origem, ma.id, ma.status, ma.valor,
                          a.id_academia, ac.asaas_webhook_token
                   FROM mensalidade_aluno ma
                   JOIN alunos a ON a.id = ma.aluno_id
                   JOIN academias ac ON ac.id = a.id_academia
                   WHERE ma.asaas_payment_id = %s LIMIT 1""",
                (payment_id,),
            )
            rec = cur.fetchone()
            if not rec:
                cur.execute(
                    """SELECT 'avulsa' AS origem, ca.id, ca.status, ca.valor,
                              ca.id_academia, ac.asaas_webhook_token
                       FROM cobranca_avulsa ca
                       JOIN academias ac ON ac.id = ca.id_academia
                       WHERE ca.asaas_payment_id = %s LIMIT 1""",
                    (payment_id,),
                )
                rec = cur.fetchone()
            # Pagamento de uma ASSINATURA RECORRENTE (não está em mensalidade/avulsa).
            if not rec:
                _ext = str(pay.get("externalReference") or "")
                if _ext.startswith("assinatura-") and _ext.split("-", 1)[1].isdigit():
                    conn.close()
                    _baixar_mensalidade_recorrente(int(_ext.split("-", 1)[1]), pay.get("value"), "Asaas")
                    return jsonify({"ok": True})
                # Matrícula (pré-cadastro) — localiza pelo payment_id armazenado
                cur.execute("SELECT id FROM pre_cadastro WHERE matricula_payment_id=%s LIMIT 1", (str(payment_id),))
                if cur.fetchone():
                    conn.close()
                    _baixar_matricula_paga(payment_id=payment_id)
                    return jsonify({"ok": True})
            # Validação opcional de segurança por academia: se a academia definiu um
            # token de webhook, o header enviado pelo Asaas precisa coincidir.
            _wh_token = ((rec or {}).get("asaas_webhook_token") or "").strip()
            if _wh_token and request.headers.get("asaas-access-token", "").strip() != _wh_token:
                conn.close()
                return jsonify({"ok": False, "msg": "token inválido"}), 403
            if rec and rec["status"] != "pago":
                valor_pago = pay.get("value") or rec["valor"]
                # 1) Baixa do status (parte crítica) — commitada antes da receita.
                if rec["origem"] == "mensalidade":
                    cur.execute(
                        """UPDATE mensalidade_aluno
                           SET status='pago', status_pagamento='pago', data_pagamento=CURDATE(), valor_pago=%s
                           WHERE id=%s""",
                        (valor_pago, rec["id"]),
                    )
                else:
                    cur.execute(
                        """UPDATE cobranca_avulsa
                           SET status='pago', data_pagamento=CURDATE(), valor_pago=%s
                           WHERE id=%s""",
                        (valor_pago, rec["id"]),
                    )
                conn.commit()
                # Confirmação de pagamento no WhatsApp (mensalidade ou avulsa, paga online)
                try:
                    from utils.whatsapp_lembretes import enviar_confirmacao_pagamento
                    enviar_confirmacao_pagamento(
                        rec["id"],
                        "mensalidade_aluno" if rec["origem"] == "mensalidade" else "cobranca_avulsa",
                    )
                except Exception:
                    pass
                # 2) Lançamento da receita — falha aqui não desfaz a baixa.
                try:
                    if rec["origem"] == "mensalidade":
                        cur.execute(
                            """INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno)
                               VALUES (%s, %s, CURDATE(), 'Mensalidades', %s, %s)""",
                            ("Mensalidade (Asaas)", valor_pago, rec["id_academia"], rec["id"]),
                        )
                    else:
                        cur.execute(
                            """INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_cobranca_avulsa)
                               VALUES (%s, %s, CURDATE(), 'Cobrança avulsa', %s, %s)""",
                            ("Cobrança avulsa (Asaas)", valor_pago, rec["id_academia"], rec["id"]),
                        )
                    conn.commit()
                except Exception as e2:
                    conn.rollback()
                    current_app.logger.error(f"Webhook Asaas: baixa OK, receita falhou ({rec['origem']} {rec['id']}): {e2}")
        except Exception as e:
            conn.rollback()
            current_app.logger.error(f"Webhook Asaas erro: {e}", exc_info=True)
        finally:
            conn.close()
    return jsonify({"ok": True})


def _baixar_cobranca_paga(origem, registro_id, valor_pago, gateway_nome):
    """Dá baixa numa cobrança paga (mensalidade/avulsa) e lança a receita. Best-effort.

    Confirma o status primeiro (commit) e lança a receita em transação separada,
    de modo que falha na receita não desfaz a baixa.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if origem == "mensalidade":
            cur.execute(
                """SELECT ma.id, ma.status, ma.valor, a.id_academia
                   FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                   WHERE ma.id = %s""",
                (registro_id,),
            )
        else:
            cur.execute(
                "SELECT id, status, valor, id_academia FROM cobranca_avulsa WHERE id = %s",
                (registro_id,),
            )
        rec = cur.fetchone()
        if not rec or rec["status"] == "pago":
            return
        vp = valor_pago or rec["valor"]
        if origem == "mensalidade":
            cur.execute(
                """UPDATE mensalidade_aluno
                   SET status='pago', status_pagamento='pago', data_pagamento=CURDATE(), valor_pago=%s
                   WHERE id=%s""",
                (vp, rec["id"]),
            )
        else:
            cur.execute(
                "UPDATE cobranca_avulsa SET status='pago', data_pagamento=CURDATE(), valor_pago=%s WHERE id=%s",
                (vp, rec["id"]),
            )
        conn.commit()
        # Confirmação de pagamento no WhatsApp (mensalidade ou avulsa, paga online)
        try:
            from utils.whatsapp_lembretes import enviar_confirmacao_pagamento
            enviar_confirmacao_pagamento(rec["id"], "mensalidade_aluno" if origem == "mensalidade" else "cobranca_avulsa")
        except Exception:
            pass
        try:
            if origem == "mensalidade":
                cur.execute(
                    """INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno)
                       VALUES (%s, %s, CURDATE(), 'Mensalidades', %s, %s)""",
                    (f"Mensalidade ({gateway_nome})", vp, rec["id_academia"], rec["id"]),
                )
            else:
                cur.execute(
                    """INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_cobranca_avulsa)
                       VALUES (%s, %s, CURDATE(), 'Cobrança avulsa', %s, %s)""",
                    (f"Cobrança avulsa ({gateway_nome})", vp, rec["id_academia"], rec["id"]),
                )
            conn.commit()
        except Exception as e2:
            conn.rollback()
            current_app.logger.error(f"Webhook {gateway_nome}: baixa OK, receita falhou ({origem} {registro_id}): {e2}")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Baixa {gateway_nome} erro ({origem} {registro_id}): {e}")
    finally:
        conn.close()


def _achar_cobranca_por_payment_id(payment_id, gateway):
    """Retorna (origem, id, id_academia) da cobrança com asaas_payment_id=payment_id."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id, a.id_academia FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               WHERE ma.asaas_payment_id = %s LIMIT 1""",
            (str(payment_id),),
        )
        r = cur.fetchone()
        if r:
            return ("mensalidade", r["id"], r["id_academia"])
        cur.execute(
            "SELECT id, id_academia FROM cobranca_avulsa WHERE asaas_payment_id = %s LIMIT 1",
            (str(payment_id),),
        )
        r = cur.fetchone()
        if r:
            return ("avulsa", r["id"], r["id_academia"])
        return (None, None, None)
    finally:
        conn.close()


def _baixar_matricula_paga(*, precad_id=None, payment_id=None):
    """Marca a matrícula (pré-cadastro) como paga. Localiza por id direto ou pelo
    payment_id/txid armazenado em pre_cadastro.matricula_payment_id."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if precad_id:
            cur.execute("UPDATE pre_cadastro SET matricula_status='pago' WHERE id=%s", (precad_id,))
        elif payment_id:
            cur.execute(
                "UPDATE pre_cadastro SET matricula_status='pago' WHERE matricula_payment_id=%s",
                (str(payment_id),),
            )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Baixa matrícula falhou: {e}")
        return False
    finally:
        conn.close()


@bp_financeiro.route("/webhook/mercadopago", methods=["POST", "GET"])
@csrf.exempt
def webhook_mercadopago():
    """Recebe notificações do Mercado Pago e dá baixa quando o pagamento é aprovado."""
    data = request.get_json(silent=True) or {}
    payment_id = (
        (data.get("data") or {}).get("id")
        or request.args.get("id")
        or request.args.get("data.id")
    )
    topic = data.get("type") or data.get("topic") or request.args.get("topic") or request.args.get("type")
    if not payment_id:
        return jsonify({"ok": True})
    if topic and "payment" not in str(topic):
        return jsonify({"ok": True})
    try:
        origem, rid, id_acad = _achar_cobranca_por_payment_id(payment_id, "mercadopago")
        if not origem:
            # Pode ser um pagamento de ASSINATURA RECORRENTE (não armazenado por nós).
            _mp_tentar_baixa_recorrente(payment_id)
            return jsonify({"ok": True})
        cfg = _gateway_config_academia(id_acad)
        from utils.mercadopago import MercadoPagoClient
        status = MercadoPagoClient((cfg or {}).get("mercadopago_access_token")).status_pagamento(payment_id)
        if status in ("approved", "authorized"):
            _baixar_cobranca_paga(origem, rid, None, "Mercado Pago")
    except Exception as e:
        current_app.logger.error(f"Webhook Mercado Pago erro: {e}", exc_info=True)
    return jsonify({"ok": True})


def _mp_tentar_baixa_recorrente(payment_id):
    """Tenta baixar um pagamento recorrente do Mercado Pago. Como o webhook não diz
    a academia, tentamos os tokens das academias que têm assinatura MP até achar o
    pagamento; ao localizar com external_reference 'assinatura-<aluno_id>' aprovado,
    dá baixa na mensalidade em aberto do aluno. Best-effort."""
    import requests as _rq
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT DISTINCT ac.id, ac.mercadopago_access_token AS token
               FROM assinaturas_recorrentes s JOIN academias ac ON ac.id = s.id_academia
               WHERE s.gateway='mercadopago'
                 AND ac.mercadopago_access_token IS NOT NULL AND ac.mercadopago_access_token <> ''"""
        )
        contas = cur.fetchall()
    finally:
        conn.close()
    for c in contas:
        try:
            r = _rq.get(
                f"{ 'https://api.mercadopago.com' }/v1/payments/{payment_id}",
                headers={"Authorization": f"Bearer {c['token']}"}, timeout=20,
            )
            if not r.ok:
                continue
            j = r.json() or {}
            ext = str(j.get("external_reference") or "")
            aprovado = j.get("status") in ("approved", "authorized")
            if ext.startswith("assinatura-") and ext.split("-", 1)[1].isdigit():
                if aprovado:
                    _baixar_mensalidade_recorrente(int(ext.split("-", 1)[1]), j.get("transaction_amount"), "Mercado Pago")
                return True
            if ext.startswith("precadastro-") and ext.split("-", 1)[1].isdigit():
                if aprovado:
                    _baixar_matricula_paga(precad_id=int(ext.split("-", 1)[1]))
                return True
        except Exception:
            continue
    return False


@bp_financeiro.route("/webhook/infinitepay", methods=["POST"])
@csrf.exempt
def webhook_infinitepay():
    """Recebe o webhook da InfinitePay (link pago) e dá baixa pela referência order_nsu."""
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    order_nsu = data.get("order_nsu") or data.get("orderNsu") or (data.get("invoice") or {}).get("order_nsu")
    if not order_nsu or "-" not in str(order_nsu):
        return jsonify({"ok": True})
    origem, _, rid = str(order_nsu).rpartition("-")
    if origem not in ("mensalidade", "avulsa", "precadastro") or not rid.isdigit():
        return jsonify({"ok": True})
    valor_pago = None
    try:
        cents = data.get("paid_amount") or data.get("amount")
        if cents:
            valor_pago = float(cents) / 100.0
    except Exception:
        valor_pago = None
    try:
        if origem == "precadastro":
            _baixar_matricula_paga(precad_id=int(rid))
        else:
            _baixar_cobranca_paga(origem, int(rid), valor_pago, "InfinitePay")
    except Exception as e:
        current_app.logger.error(f"Webhook InfinitePay erro: {e}", exc_info=True)
    return jsonify({"ok": True})


@bp_financeiro.route("/webhook/cora", methods=["POST"])
@csrf.exempt
def webhook_cora():
    """Recebe a notificação do Cora (boleto/PIX pago) e dá baixa na cobrança.

    O Cora notifica SEM corpo — tudo vem em cabeçalhos (verificado em stage):
        Webhook-Event-Type : invoice.PAID
        Webhook-Resource-Id: inv_...
        Webhook-Event-Id   : evt_...
    Nem `includeResource` nem `expandable` no cadastro mudam isso. Por isso o
    pagamento é confirmado consultando a invoice na API com as credenciais da
    academia dona da cobrança — o que, de quebra, torna inofensivo um POST
    forjado, já que nada do que chega no request é tomado como verdade.

    A URL precisa estar cadastrada na conta do Cora (POST /endpoints/, resource
    'invoice', trigger 'paid') pelo botão da tela de configurações, que chama
    `cora_registrar_webhook` — e o cadastro vale por ambiente.

    Mesmo assim ainda lemos um corpo JSON quando ele vier: se o Cora passar a
    enviar o recurso, a resolução pelo `code` continua funcionando.
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), {})
    entidade = _cora_extrair_invoice(data)

    evento = str(request.headers.get("Webhook-Event-Type")
                 or data.get("trigger") or data.get("event") or data.get("type") or "").lower()
    status = str(entidade.get("status") or data.get("status") or "").upper()
    invoice_id = str(request.headers.get("Webhook-Resource-Id")
                     or entidade.get("id") or data.get("id") or "").strip()

    # Só interessa o pagamento efetivado.
    if "paid" not in evento and status not in ("PAID", "IN_PAYMENT", "SETTLED"):
        # Só cadastramos invoice.paid, então um evento não classificado é anômalo.
        current_app.logger.warning(
            "Webhook Cora ignorado (não é pagamento): evento=%r status=%r invoice=%r",
            evento or None, status or None, invoice_id or None,
        )
        return jsonify({"ok": True})

    if not invoice_id:
        current_app.logger.warning("Webhook Cora sem id da invoice (evento=%r).", evento or None)
        return jsonify({"ok": True})

    origem, rid, id_academia = _cora_resolver_invoice(invoice_id)
    inv, id_academia = _cora_confirmar_invoice(invoice_id, id_academia)
    if inv is None:
        current_app.logger.warning(
            "Webhook Cora: invoice %s não confirmada em nenhuma academia com Cora configurado.",
            invoice_id,
        )
        return jsonify({"ok": True})

    status_api = str(inv.get("status") or "").upper()
    if status_api not in ("PAID", "SETTLED"):
        current_app.logger.warning(
            "Webhook Cora: invoice %s notificada como paga, mas a API devolveu status=%r — sem baixa.",
            invoice_id, status_api or None,
        )
        return jsonify({"ok": True})

    valor_pago = None
    try:
        cents = inv.get("total_paid") or inv.get("total_amount")
        if cents:
            valor_pago = float(cents) / 100.0
    except (TypeError, ValueError):
        valor_pago = None

    if origem is None:
        # A cobrança não foi encontrada pelo id da invoice: usa a nossa
        # referência ('origem-id'), gravada no `code` na emissão.
        origem, rid = _cora_referencia_do_code(str(inv.get("code") or ""))

    if origem is None:
        current_app.logger.warning(
            "Webhook Cora sem referência resolvível: invoice=%s code=%r academia=%s",
            invoice_id, inv.get("code"), id_academia,
        )
        return jsonify({"ok": True})

    try:
        if origem == "precadastro":
            _baixar_matricula_paga(precad_id=rid)
        else:
            _baixar_cobranca_paga(origem, rid, valor_pago, "Cora")
    except Exception as e:
        current_app.logger.error(f"Webhook Cora erro: {e}", exc_info=True)
    return jsonify({"ok": True})


def _cora_referencia_do_code(code):
    """Traduz o `code` da invoice ('mensalidade-12') em (origem, id)."""
    code = str(code or "")
    if "-" in code:
        origem, _, rid = code.rpartition("-")
        if origem in ("mensalidade", "avulsa", "precadastro") and rid.isdigit():
            return origem, int(rid)
    return None, None


def _cora_resolver_invoice(invoice_id):
    """(origem, registro_id, id_academia) da cobrança com esse id de invoice."""
    origem, rid, id_acad = _achar_cobranca_por_payment_id(invoice_id, "cora")
    if origem:
        return origem, rid, id_acad
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, academia_id FROM pre_cadastro WHERE matricula_payment_id=%s LIMIT 1",
            (str(invoice_id),),
        )
        r = cur.fetchone()
        if r:
            return ("precadastro", r["id"], r["academia_id"])
    except Exception:
        pass
    finally:
        conn.close()
    return (None, None, None)


def _cora_academias_configuradas():
    """Ids das academias com credenciais do Cora em qualquer ambiente.

    A checagem do trio completo do ambiente ativo fica com `_cora_configurado`,
    em quem consome esta lista.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id FROM academias
               WHERE COALESCE(cora_client_id,'')<>'' OR COALESCE(cora_client_id_prod,'')<>''"""
        )
        return [r[0] for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def _cora_confirmar_invoice(invoice_id, id_academia=None):
    """Consulta a invoice na API do Cora — a fonte de verdade do webhook.

    Sabendo a academia, consulta só a dela; senão varre as academias com Cora
    configurado até uma reconhecer o id (cada conta só enxerga as próprias
    invoices). Devolve (dados, id_academia) ou (None, None).
    """
    ids = [id_academia] if id_academia else _cora_academias_configuradas()
    for aid in ids:
        cfg = _gateway_config_academia(aid)
        if not _cora_configurado(cfg):
            continue
        try:
            return _cora_client(cfg).consultar(invoice_id), aid
        except Exception as e:
            current_app.logger.info(
                "Webhook Cora: invoice %s não é da academia %s (%s)", invoice_id, aid, e
            )
    return None, None


def _cora_extrair_invoice(data):
    """Acha o objeto da invoice dentro do payload do webhook do Cora.

    O corpo do evento envelopa o recurso de um jeito que a documentação não
    fixa (já apareceu solto e sob 'invoice'/'data'/'payload'/'entity'), então
    procuramos em largura o primeiro dict que pareça uma invoice: id 'inv_…',
    ou um 'code' junto de 'status'. Cai no próprio payload se não achar.
    """
    if not isinstance(data, dict):
        return {}

    def parece_invoice(d):
        if not isinstance(d, dict):
            return False
        if str(d.get("id") or "").startswith("inv_"):
            return True
        return bool(d.get("code")) and bool(d.get("status"))

    fila, visitados = [data], 0
    while fila and visitados < 50:
        atual = fila.pop(0)
        visitados += 1
        if parece_invoice(atual):
            return atual
        for v in atual.values():
            if isinstance(v, dict):
                fila.append(v)
    return data


def _base_publica_https():
    """Base pública do sistema em https, sem barra no fim.

    O Cora só aceita webhook em HTTPS. Como a app roda atrás do nginx sem
    ProxyFix, `request.url_root` vem como http:// — por isso o esquema sai do
    X-Forwarded-Proto (ou é forçado a https em qualquer host que não seja local).
    """
    from utils.links_curtos import base_url
    base = (base_url() or "").rstrip("/")
    if base.startswith("https://"):
        return base
    host = (request.host or "").split(":")[0].lower()
    proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")
    if base.startswith("http://") and (proto == "https" or not local):
        return "https://" + base[len("http://"):]
    return base


@bp_financeiro.route("/cora/webhook/registrar", methods=["POST"])
@login_required
def cora_registrar_webhook():
    """Cadastra o nosso endpoint de webhook na conta Cora da academia.

    O Cora não tem tela para isso: o registro é programático (POST /endpoints/)
    e vale só para o ambiente em que foi feito — stage e produção precisam de
    cadastros separados. Trocar o ambiente da academia exige clicar de novo.
    """
    academia_id = request.form.get("academia_id", type=int) or _get_academia_id()
    destino = url_for("academia.configuracoes_academia", academia_id=academia_id, _anchor="financeiro")
    if not academia_id or academia_id not in _get_academias_ids():
        flash("Selecione uma academia válida.", "warning")
        return redirect(destino)

    cfg = _gateway_config_academia(academia_id)
    if not _cora_configurado(cfg):
        _amb = "Produção" if _cora_ambiente(cfg) == "production" else "Stage"
        flash(f"Informe o Client ID, o certificado e a chave privada do Cora no ambiente {_amb} "
              "antes de registrar o webhook.", "warning")
        return redirect(destino)

    url_webhook = _base_publica_https() + url_for("financeiro.webhook_cora")
    try:
        res = _cora_client(cfg).sincronizar_webhooks(url_webhook)
    except Exception as e:
        current_app.logger.error(f"Cora registrar webhook (academia {academia_id}): {e}", exc_info=True)
        flash(f"Não foi possível registrar o webhook no Cora: {e}", "danger")
        return redirect(destino)

    ambiente = "Stage (testes)" if res["ambiente"] == "stage" else "Produção"
    partes = []
    if res["criados"]:
        partes.append("cadastrado(s): " + ", ".join(res["criados"]))
    if res["atualizados"]:
        partes.append("recadastrado(s): " + ", ".join(res["atualizados"]))
    if res["existentes"]:
        partes.append("já existia(m): " + ", ".join(res["existentes"]))
    if res["erros"]:
        flash(f"Webhook do Cora ({ambiente}) com pendências — " + " | ".join(res["erros"]), "danger")
    if partes:
        flash(f"Webhook {res['url']} no Cora ({ambiente}) — " + "; ".join(partes) + ".", "success")
    elif not res["erros"]:
        flash("Nenhum evento a registrar no Cora.", "info")
    return redirect(destino)


@bp_financeiro.route("/webhook/efi", methods=["POST"])
@bp_financeiro.route("/webhook/efi/pix", methods=["POST"])
@csrf.exempt
def webhook_efi():
    """Recebe a notificação Pix da EFÍ e dá baixa pelo txid da cobrança.
    A EFÍ adiciona '/pix' ao final da URL do webhook — por isso aceitamos ambas as rotas."""
    data = request.get_json(silent=True) or {}
    pix_list = data.get("pix") or []
    if not isinstance(pix_list, list):
        return jsonify({"ok": True})
    for p in pix_list:
        try:
            txid = p.get("txid")
            if not txid:
                continue
            origem, rid, _ = _achar_cobranca_por_payment_id(txid, "efi")
            valor_pago = None
            try:
                if p.get("valor"):
                    valor_pago = float(p["valor"])
            except (TypeError, ValueError):
                valor_pago = None
            if origem:
                _baixar_cobranca_paga(origem, rid, valor_pago, "EFÍ")
            elif not _baixar_matricula_paga(payment_id=txid):
                pass  # txid não corresponde a cobrança nem matrícula conhecida
        except Exception as e:
            current_app.logger.error(f"Webhook EFÍ erro: {e}", exc_info=True)
    return jsonify({"ok": True})


# ============================================================
# SumUp — página de pagamento hospedada (widget de cartão + PIX/boleto server-side)
# ============================================================
def _sumup_resolver_checkout(checkout_id):
    """Localiza a cobrança/matrícula pelo checkout_id (armazenado em asaas_payment_id /
    matricula_payment_id). Retorna (origem, registro_id, id_academia) ou (None, None, None)."""
    origem, rid, id_acad = _achar_cobranca_por_payment_id(checkout_id, "sumup")
    if origem:
        return origem, rid, id_acad
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, academia_id FROM pre_cadastro WHERE matricula_payment_id=%s LIMIT 1",
            (str(checkout_id),),
        )
        r = cur.fetchone()
        if r:
            return ("precadastro", r["id"], r["academia_id"])
    finally:
        conn.close()
    return (None, None, None)


def _sumup_client_por_checkout(checkout_id):
    """Retorna (SumUpClient, origem, rid, id_academia) para um checkout, ou (None,...)."""
    origem, rid, id_acad = _sumup_resolver_checkout(checkout_id)
    if not origem:
        return (None, None, None, None)
    cfg = _gateway_config_academia(id_acad) or {}
    cli = _sumup_client(cfg)
    return (cli, origem, rid, id_acad)


def _sumup_dar_baixa(origem, rid, valor_pago=None):
    """Dá baixa (pago) na cobrança/matrícula após confirmação de pagamento SumUp."""
    if origem == "precadastro":
        _baixar_matricula_paga(precad_id=int(rid))
    else:
        _baixar_cobranca_paga(origem, int(rid), valor_pago, "SumUp")


@bp_financeiro.route("/pagamento/sumup/<checkout_id>", methods=["GET"])
def sumup_pagamento(checkout_id):
    """Página pública de pagamento SumUp: mostra o widget de cartão e as opções de
    PIX/boleto (se habilitadas na conta). Não exige login (o pagador não é usuário)."""
    cli, origem, rid, id_acad = _sumup_client_por_checkout(checkout_id)
    if not cli or not cli.configurado:
        return render_template("financeiro/sumup_pagamento.html",
                               erro="Cobrança não encontrada ou gateway indisponível.",
                               checkout_id=checkout_id), 404
    dados = cli.obter_checkout(checkout_id)
    if not dados:
        return render_template("financeiro/sumup_pagamento.html",
                               erro="Não foi possível carregar a cobrança.",
                               checkout_id=checkout_id), 502
    # Une os métodos do checkout (fonte de verdade) com os da conta — o endpoint por
    # checkout às vezes restringe (ex.: só 'card'), enquanto a conta oferece PIX/boleto.
    _m_chk = cli.listar_metodos(checkout_id)
    _m_mer = cli.listar_metodos_merchant(dados.get("amount"))
    metodos = list(dict.fromkeys((_m_chk or []) + (_m_mer or [])))
    pago = str(dados.get("status") or "").upper() == "PAID"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome FROM academias WHERE id=%s", (id_acad,))
        _a = cur.fetchone() or {}
    finally:
        conn.close()
    return render_template(
        "financeiro/sumup_pagamento.html",
        checkout_id=checkout_id,
        valor=dados.get("amount"),
        moeda=dados.get("currency") or "BRL",
        descricao=dados.get("description") or "",
        academia_nome=_a.get("nome") or "",
        metodos=metodos,
        tem_cartao=("card" in metodos or not metodos),
        tem_pix=("pix" in metodos or "qr_code_pix" in metodos),
        metodo_pix=("pix" if "pix" in metodos else ("qr_code_pix" if "qr_code_pix" in metodos else None)),
        tem_boleto=("boleto" in metodos),
        pago=pago,
        erro=None,
    )


@bp_financeiro.route("/pagamento/sumup/<checkout_id>/processar", methods=["POST"])
@csrf.exempt
def sumup_processar_apm(checkout_id):
    """Processa PIX/boleto server-side e devolve o artifact (código/QR/boleto) em JSON."""
    metodo = (request.form.get("metodo") or (request.get_json(silent=True) or {}).get("metodo") or "").strip()
    if metodo not in ("pix", "qr_code_pix", "boleto"):
        return jsonify({"ok": False, "erro": "método inválido"}), 400
    cli, origem, rid, id_acad = _sumup_client_por_checkout(checkout_id)
    if not cli or not cli.configurado:
        return jsonify({"ok": False, "erro": "cobrança não encontrada"}), 404
    try:
        art = cli.processar_apm(checkout_id, metodo)
    except Exception as e:
        current_app.logger.error(f"SumUp processar {metodo} ({checkout_id}): {e}")
        return jsonify({"ok": False, "erro": "falha ao gerar o pagamento"}), 502
    # A imagem de QR da SumUp vem por URL autenticada; geramos o QR localmente a
    # partir do código copia-e-cola (funciona no navegador do pagador).
    art["pix_qrcode_b64"] = None
    if art.get("pix_copia_cola"):
        try:
            from utils.qrcode_util import gerar_qr_base64
            art["pix_qrcode_b64"] = gerar_qr_base64(art["pix_copia_cola"])
        except Exception:
            pass
    return jsonify({"ok": True, **art})


@bp_financeiro.route("/pagamento/sumup/<checkout_id>/status", methods=["GET"])
def sumup_status(checkout_id):
    """Consulta o status do checkout (para polling da página). Dá baixa se pago."""
    cli, origem, rid, id_acad = _sumup_client_por_checkout(checkout_id)
    if not cli or not cli.configurado:
        return jsonify({"ok": False, "pago": False}), 404
    dados = cli.obter_checkout(checkout_id)
    pago = str(dados.get("status") or "").upper() == "PAID"
    if pago:
        try:
            _sumup_dar_baixa(origem, rid, dados.get("amount"))
        except Exception as e:
            current_app.logger.error(f"SumUp baixa status ({checkout_id}): {e}")
    return jsonify({"ok": True, "pago": pago, "status": dados.get("status")})


@bp_financeiro.route("/pagamento/sumup/retorno", methods=["GET"])
def sumup_retorno(ref=None):
    """Landing após o redirect do pagamento (SCA/redirect). Mostra a página de status."""
    checkout_id = request.args.get("checkout_id") or ""
    return render_template("financeiro/sumup_retorno.html", checkout_id=checkout_id)


@bp_financeiro.route("/webhook/sumup", methods=["POST", "GET"])
@csrf.exempt
def webhook_sumup():
    """Webhook da SumUp (return_url do checkout). Confirma o pagamento consultando o
    checkout e dá baixa quando status == PAID."""
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    checkout_id = (
        data.get("checkout_id") or data.get("id")
        or (data.get("payload") or {}).get("checkout_id")
        or (data.get("payload") or {}).get("id")
        or request.args.get("checkout_id") or request.args.get("id")
    )
    if not checkout_id:
        return jsonify({"ok": True})
    try:
        cli, origem, rid, id_acad = _sumup_client_por_checkout(checkout_id)
        if cli and cli.configurado and origem and cli.checkout_pago(checkout_id):
            dados = cli.obter_checkout(checkout_id)
            _sumup_dar_baixa(origem, rid, dados.get("amount"))
        elif not origem:
            # Pode ser o pagamento de SETUP de uma assinatura recorrente SumUp:
            # ativa a assinatura e dá baixa na 1ª mensalidade.
            _sumup_ativar_assinatura_por_checkout(checkout_id)
    except Exception as e:
        current_app.logger.error(f"Webhook SumUp erro: {e}", exc_info=True)
    return jsonify({"ok": True})


def _sumup_ativar_assinatura_por_checkout(checkout_id):
    """Se o checkout for o SETUP de uma assinatura SumUp e estiver pago, ativa a
    assinatura (status='ativa') e baixa a mensalidade em aberto do aluno."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT aluno_id, id_academia, valor FROM assinaturas_recorrentes
               WHERE gateway='sumup' AND sumup_setup_checkout_id=%s LIMIT 1""",
            (str(checkout_id),),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return
    cfg = _gateway_config_academia(row["id_academia"])
    cli = _sumup_client(cfg)
    if cli and cli.configurado and cli.checkout_pago(checkout_id):
        # Marca a assinatura como ativa e baixa a 1ª mensalidade em aberto do aluno.
        _baixar_mensalidade_recorrente(row["aluno_id"], row.get("valor"), "SumUp")


# ------------------------------------------------------------------ SumUp OAuth
def _sumup_state_serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.secret_key or "sumup", salt="sumup-oauth")


@bp_financeiro.route("/sumup/oauth/conectar", methods=["GET"])
@login_required
def sumup_oauth_conectar():
    """Inicia o fluxo OAuth: redireciona o gestor para autorizar a conta SumUp."""
    academia_id = request.args.get("academia_id", type=int) or _get_academia_id()
    destino = url_for("academia.configuracoes_academia", academia_id=academia_id, _anchor="financeiro")
    if not academia_id or academia_id not in _get_academias_ids():
        flash("Selecione uma academia válida.", "warning")
        return redirect(destino)
    client_id, client_secret, redirect_uri = _sumup_oauth_app()
    if not client_id or not client_secret:
        flash("O app OAuth da SumUp não está configurado no servidor "
              "(SUMUP_OAUTH_CLIENT_ID / SUMUP_OAUTH_CLIENT_SECRET).", "danger")
        return redirect(destino)
    import os
    from utils.sumup import oauth_authorize_url, OAUTH_SCOPES
    # Scopes configuráveis: enquanto a SumUp não aprova 'payments' (verificação manual),
    # use SUMUP_OAUTH_SCOPES sem 'payments' para testar a conexão. Depois de aprovado,
    # inclua 'payments' na env para o modo OAuth conseguir criar cobrança.
    scopes = os.environ.get("SUMUP_OAUTH_SCOPES", "").strip() or OAUTH_SCOPES
    state = _sumup_state_serializer().dumps({"academia_id": academia_id})
    return redirect(oauth_authorize_url(client_id, redirect_uri, state, scopes=scopes))


@bp_financeiro.route("/sumup/oauth/callback", methods=["GET"])
@login_required
def sumup_oauth_callback():
    """Recebe o retorno do OAuth, troca o code por tokens e vincula à academia."""
    code = request.args.get("code")
    state = request.args.get("state")
    erro = request.args.get("error")
    academia_id = None
    try:
        academia_id = (_sumup_state_serializer().loads(state, max_age=1800) or {}).get("academia_id")
    except Exception:
        academia_id = None
    destino = url_for("academia.configuracoes_academia", academia_id=academia_id, _anchor="financeiro") if academia_id \
        else url_for("academia.configuracoes_academia", _anchor="financeiro")
    if erro or not code or not academia_id:
        flash("Conexão com a SumUp cancelada ou inválida.", "warning")
        return redirect(destino)
    if academia_id not in _get_academias_ids():
        flash("Sem permissão para esta academia.", "danger")
        return redirect(destino)
    client_id, client_secret, redirect_uri = _sumup_oauth_app()
    try:
        from utils.sumup import oauth_exchange_code, obter_merchant_code
        tok = oauth_exchange_code(client_id, client_secret, code, redirect_uri)
        access = tok.get("access_token")
        refresh = tok.get("refresh_token")
        expira = datetime.now() + timedelta(seconds=int(tok.get("expires_in") or 3600))
        merchant = obter_merchant_code(access) or ""
    except Exception as e:
        current_app.logger.error(f"SumUp OAuth callback (academia {academia_id}): {e}")
        flash("Falha ao conectar com a SumUp. Tente novamente.", "danger")
        return redirect(destino)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Conectou → já ativa a SumUp como gateway da academia (o gestor clicou em
        # "Conectar" justamente para usá-la; assim não precisa marcar/salvar de novo).
        cur.execute(
            """UPDATE academias SET sumup_conexao='oauth', sumup_oauth_access_token=%s,
                   sumup_oauth_refresh_token=%s, sumup_oauth_expira_em=%s,
                   sumup_merchant_code=COALESCE(NULLIF(%s,''), sumup_merchant_code),
                   sumup_habilitado=1, gateway_pagamento='sumup'
               WHERE id=%s""",
            (access, refresh, expira, merchant, academia_id),
        )
        conn.commit()
        flash("Conta SumUp conectada e ativada como gateway!"
              + (f" (merchant {merchant})" if merchant else ""), "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"SumUp OAuth salvar (academia {academia_id}): {e}")
        flash("Conectou, mas houve erro ao salvar. Tente de novo.", "danger")
    finally:
        conn.close()
    return redirect(destino)


@bp_financeiro.route("/sumup/oauth/desconectar", methods=["POST"])
@login_required
def sumup_oauth_desconectar():
    """Remove a conexão OAuth da academia (volta ao modo de chave manual)."""
    academia_id = request.form.get("academia_id", type=int) or _get_academia_id()
    destino = url_for("academia.configuracoes_academia", academia_id=academia_id, _anchor="financeiro")
    if not academia_id or academia_id not in _get_academias_ids():
        flash("Selecione uma academia válida.", "warning")
        return redirect(destino)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE academias SET sumup_conexao='key', sumup_oauth_access_token=NULL,
                   sumup_oauth_refresh_token=NULL, sumup_oauth_expira_em=NULL
               WHERE id=%s""",
            (academia_id,),
        )
        conn.commit()
        flash("Conta SumUp desconectada.", "success")
    except Exception:
        conn.rollback()
        flash("Erro ao desconectar.", "danger")
    finally:
        conn.close()
    return redirect(destino)


@bp_financeiro.route("/mensalidades/<int:ma_id>/lembrete-whatsapp", methods=["POST"])
@login_required
def lembrete_whatsapp_individual(ma_id):
    """Envia o lembrete de uma mensalidade pelo WhatsApp da academia."""
    academia_id = _get_academia_id()
    if not academia_id:
        return jsonify({"ok": False, "erro": "academia não definida"}), 400
    from utils import whatsapp_lembretes as lem
    ok, msg = lem.enviar_um(academia_id, ma_id)
    return jsonify({"ok": ok, "msg": msg})


@bp_financeiro.route("/mensalidades/lembretes-whatsapp", methods=["POST"])
@login_required
def lembretes_whatsapp_lote():
    """Envia lembretes em lote para mensalidades pendentes/atrasadas da academia."""
    academia_id = _get_academia_id()
    if not academia_id:
        return jsonify({"ok": False, "erro": "academia não definida"}), 400
    try:
        dias = int(request.form.get("dias", 3))
    except (TypeError, ValueError):
        dias = 3
    from utils import whatsapp_lembretes as lem
    # botão manual ignora o toggle (envia mesmo se a automação diária estiver off)
    resumo = lem.enviar_lote(academia_id, dias_antes=dias, somente_ativadas=False)
    return jsonify({"ok": True, "resumo": resumo})


@bp_financeiro.route("/mensalidades/alunos")
@login_required
def mensalidades_alunos():
    """Mensalidades e cobranças avulsas por aluno com dashboard, filtros e confirmação."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    _atualizar_status_atrasadas(academia_id)

    # Aplicar mês e ano atuais como padrão apenas quando NÃO vierem na URL.
    # Importante: quando o usuário escolher "Todos os meses" (mes vazio), NÃO filtrar por mês.
    hoje = date.today()
    mes_arg = request.args.get("mes", default=None, type=str)
    if mes_arg is None:
        # Param não veio: usar mês atual como padrão
        mes = hoje.month
    else:
        mes = int(mes_arg) if mes_arg and mes_arg.isdigit() and 1 <= int(mes_arg) <= 12 else None

    ano_arg = request.args.get("ano", type=int)
    if ano_arg is None:
        ano = hoje.year
    else:
        ano = ano_arg if (2000 <= ano_arg <= 2100) else hoje.year
    
    # Se NEM mês NEM ano foram informados na URL, redirecionar com os valores padrão
    if mes_arg is None and ano_arg is None:
        busca = (request.args.get("busca") or "").strip()
        filtro_status = (request.args.get("status") or "").strip().lower()
        if filtro_status not in ("pago", "pendente", "atrasado", "aguardando_confirmacao"):
            filtro_status = None
        params = {"academia_id": academia_id, "mes": mes, "ano": ano}
        if busca:
            params["busca"] = busca
        if filtro_status:
            params["status"] = filtro_status
        return redirect(url_for("financeiro.mensalidades_alunos", **params))
    
    busca = (request.args.get("busca") or "").strip()
    filtro_status = (request.args.get("status") or "").strip().lower()
    if filtro_status not in ("pago", "pendente", "atrasado", "aguardando_confirmacao"):
        filtro_status = None
    academias = _get_academias_for_select()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    where_ma = ["m.id_academia = %s", "ma.status != 'cancelado'"]
    params_ma = [academia_id]
    # Aplicar filtro de mês apenas quando definido (quando o usuário NÃO escolhe "Todos os meses")
    if mes is not None and 1 <= mes <= 12:
        where_ma.append("MONTH(ma.data_vencimento) = %s")
        params_ma.append(mes)
    if ano:
        where_ma.append("YEAR(ma.data_vencimento) = %s")
        params_ma.append(ano)
    if busca:
        where_ma.append("a.nome LIKE %s")
        params_ma.append(f"%{busca}%")

    try:
        cur.execute(f"""
            SELECT ma.id, ma.mensalidade_id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                   ma.status_pagamento, ma.comprovante_url, ma.observacoes,
                   ma.valor_original, ma.desconto_aplicado, ma.id_desconto, ma.turma_id,
                   ma.asaas_boleto_url, ma.asaas_pix_copia_cola, ma.asaas_pix_qrcode, ma.asaas_tipo,
                   COALESCE(ma.remover_juros, 0) AS remover_juros,
                   m.nome as plano_nome, m.id_academia, a.id as aluno_id, a.nome as aluno_nome, a.foto as aluno_foto,
                   COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
                   COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
                   COALESCE(m.percentual_juros_dia, 0.033) AS percentual_juros_dia,
                   t.Nome as turma_nome
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            LEFT JOIN turmas t ON t.TurmaID = ma.turma_id
            WHERE {' AND '.join(where_ma)}
            ORDER BY ma.data_vencimento DESC
            LIMIT 200
        """, params_ma)
        rows = cur.fetchall()
    except Exception:
        try:
            where_fb = ["m.id_academia = %s", "ma.status != 'cancelado'"]
            if mes and 1 <= mes <= 12:
                where_fb.append("MONTH(ma.data_vencimento) = %s")
            if ano:
                where_fb.append("YEAR(ma.data_vencimento) = %s")
            if busca:
                where_fb.append("a.nome LIKE %s")
            params_fb = [academia_id]
            if mes and 1 <= mes <= 12:
                params_fb.append(mes)
            if ano:
                params_fb.append(ano)
            if busca:
                params_fb.append(f"%{busca}%")
            cur.execute(f"""
                SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                       ma.status_pagamento, ma.comprovante_url, ma.observacoes,
                       m.nome as plano_nome, m.id_academia, a.id as aluno_id, a.nome as aluno_nome, a.foto as aluno_foto
                FROM mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                JOIN alunos a ON a.id = ma.aluno_id
                WHERE {' AND '.join(where_fb)}
                ORDER BY ma.data_vencimento DESC
                LIMIT 200
            """, params_fb)
            rows = cur.fetchall()
            for r in rows:
                r.setdefault("remover_juros", 0)
                r.setdefault("aplicar_juros_multas", 0)
                r.setdefault("percentual_multa_mes", 2)
                r.setdefault("percentual_juros_dia", 0.033)
                r.setdefault("status_pagamento", None)
                r.setdefault("comprovante_url", None)
                r.setdefault("observacoes", None)
                r.setdefault("valor_original", None)
                r.setdefault("desconto_aplicado", 0)
                r.setdefault("id_desconto", None)
                r.setdefault("turma_id", None)
                r.setdefault("turma_nome", None)
                r.setdefault("mensalidade_id", None)
        except Exception:
            rows = []

    from blueprints.aluno.painel import _calcular_valor_com_juros_multas

    mensalidades = []
    for ma in rows:
        valor_display, valor_original, multa_val, juros_val = _calcular_valor_com_juros_multas(ma, hoje)
        ma["valor_display"] = valor_display
        ma["valor_original"] = valor_original
        ma["multa_val"] = multa_val
        ma["juros_val"] = juros_val
        ma["tem_juros"] = (multa_val or 0) + (juros_val or 0) > 0
        ma_orig_val = ma.get("valor")
        if ma["tem_juros"]:
            ma["valor"] = valor_display
        ma["status_efetivo"] = _status_efetivo(ma.get("status"), ma.get("data_vencimento"), ma.get("status_pagamento"))
        ma["comentario_informado"] = ma.get("comentario_informado") or ma.get("observacoes")
        vi, vd, vf, desconto_nome = _valor_com_desconto(ma, ma.get("aluno_id"), academia_id, hoje)
        if ma.get("tem_juros"):
            ma["valor"] = ma_orig_val
        ma["valor_integral"] = vi
        ma["valor_desconto"] = vd
        ma["valor_final"] = vf
        ma["desconto_nome"] = desconto_nome
        ma["tem_desconto"] = vd > 0
        if not filtro_status or ma.get("status_efetivo") == filtro_status:
            mensalidades.append(ma)

    try:
        cur.execute(f"""
            SELECT ma.id, ma.status, ma.status_pagamento, ma.data_vencimento, m.id_academia, a.id as aluno_id
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE {' AND '.join(where_ma)}
        """, params_ma)
        all_ma = cur.fetchall()
    except Exception:
        try:
            cur.execute(f"""
                SELECT ma.id, ma.status, ma.status_pagamento, ma.data_vencimento, m.id_academia, a.id as aluno_id
                FROM mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                JOIN alunos a ON a.id = ma.aluno_id
                WHERE m.id_academia = %s AND ma.status != 'cancelado'
            """, (academia_id,))
            all_ma = cur.fetchall()
        except Exception:
            all_ma = []
    contagens = {"pago": 0, "pendente": 0, "atrasado": 0, "aguardando_confirmacao": 0}
    for r in all_ma:
        if r.get("status_pagamento") == "pendente_aprovacao":
            contagens["aguardando_confirmacao"] = contagens.get("aguardando_confirmacao", 0) + 1
        elif r.get("status") == "pago":
            contagens["pago"] = contagens.get("pago", 0) + 1
        else:
            s = r.get("status")
            if s == "pendente":
                try:
                    venc = r.get("data_vencimento")
                    venc = venc if isinstance(venc, date) else date.fromisoformat(str(venc)[:10]) if venc else None
                    if venc and venc < hoje:
                        s = "atrasado"
                except Exception:
                    pass
            contagens[s] = contagens.get(s, 0) + 1

    avulsas = []
    try:
        where_av = ["id_academia = %s", "status != 'cancelado'"]
        params_av = [academia_id]
        if mes and 1 <= mes <= 12:
            where_av.append("MONTH(data_vencimento) = %s")
            params_av.append(mes)
        if ano:
            where_av.append("YEAR(data_vencimento) = %s")
            params_av.append(ano)
        if busca:
            try:
                cur.execute("SELECT id FROM alunos WHERE nome LIKE %s AND id_academia = %s", (f"%{busca}%", academia_id))
            except Exception:
                cur.execute("SELECT id FROM alunos WHERE nome LIKE %s", (f"%{busca}%",))
            ids_busca = [x["id"] for x in cur.fetchall()]
            if ids_busca:
                ph = ",".join(["%s"] * len(ids_busca))
                where_av.append(f"aluno_id IN ({ph})")
                params_av.extend(ids_busca)
            else:
                where_av.append("1=0")
        cur.execute(f"""
            SELECT id, descricao, valor, data_vencimento, data_pagamento, valor_pago, status, aluno_id,
                   asaas_payment_id, asaas_tipo, asaas_boleto_url, asaas_pix_copia_cola, asaas_pix_qrcode
            FROM cobranca_avulsa WHERE {' AND '.join(where_av)}
            ORDER BY data_vencimento DESC
            LIMIT 200
        """, params_av)
        avulsas = cur.fetchall()
        for av in avulsas:
            cur.execute("SELECT nome, foto FROM alunos WHERE id = %s", (av["aluno_id"],))
            r = cur.fetchone()
            av["aluno_nome"] = r.get("nome", "-") if r else "-"
            av["aluno_foto"] = r.get("foto") if r else None
        if filtro_status and filtro_status != "aguardando_confirmacao":
            avulsas = [a for a in avulsas if (a.get("status") or "").lower() == filtro_status]
        elif filtro_status == "aguardando_confirmacao":
            avulsas = []
    except Exception:
        pass

    formas_lista = []
    try:
        _ensure_formas_padrao(cur, academia_id)
        cur.execute(
            """
            SELECT id, nome FROM formas_pagamento
            WHERE id_academia = %s AND ativo = 1
            ORDER BY ordem, nome
            """,
            (academia_id,),
        )
        formas_lista = cur.fetchall()
    except Exception:
        pass

    # Forma de recorrência por aluno (cartão/PIX recorrente) — para classificação
    forma_recorrencia_por_aluno = {}
    try:
        _ids = list({m.get("aluno_id") for m in mensalidades if m.get("aluno_id")}
                    | {a.get("aluno_id") for a in avulsas if a.get("aluno_id")})
        if _ids:
            _ph = ",".join(["%s"] * len(_ids))
            cur.execute(
                f"""SELECT s.aluno_id, s.gateway, s.metodo, s.status
                    FROM assinaturas_recorrentes s
                    INNER JOIN (SELECT aluno_id, MAX(id) AS mid FROM assinaturas_recorrentes
                                WHERE aluno_id IN ({_ph}) AND status <> 'cancelada'
                                GROUP BY aluno_id) u ON u.mid = s.id""",
                tuple(_ids),
            )
            for r in cur.fetchall():
                forma_recorrencia_por_aluno[r["aluno_id"]] = {
                    "metodo": r.get("metodo") or "cartao",
                    "status": r.get("status") or "pendente",
                    "gateway": r.get("gateway"),
                }
    except Exception:
        forma_recorrencia_por_aluno = {}

    conn.close()

    return render_template(
        "financeiro/mensalidades/mensalidades_alunos.html",
        academia_id=academia_id,
        academias=academias,
        mensalidades=mensalidades,
        avulsas=avulsas,
        forma_recorrencia_por_aluno=forma_recorrencia_por_aluno,
        contagens=contagens,
        mes=mes,
        ano=ano,
        busca=busca,
        filtro_status=filtro_status,
        ano_atual=date.today().year,
        formas_lista=formas_lista,
        asaas_on=_asaas_habilitado_academia(academia_id),
        gateway_ativo=_gateway_ativo(_gateway_config_academia(academia_id)),
        recorrencia_gw=_gateway_recorrencia(_gateway_config_academia(academia_id)),
        recorrencia_opcoes=_opcoes_recorrencia(_gateway_config_academia(academia_id)),
    )


@bp_financeiro.route("/mensalidades/checar-disponibilidade", methods=["GET"])
@login_required
def checar_disponibilidade_mensalidade():
    """Verifica se já existe mensalidade no período. Mensal: bloqueia se o mês já tem.
    Anual: permite gerar o que falta; bloqueia só se todos os meses do período já existem."""
    academia_id = _get_academia_id()
    if not academia_id:
        return jsonify({"error": "sem_academia"}), 400

    aluno_id = request.args.get("aluno_id", type=int)
    plano_id = request.args.get("plano_id", type=int)
    tipo = (request.args.get("tipo") or "").lower()
    ano = request.args.get("ano", type=int)
    mes = request.args.get("mes", type=int)
    mes_inicial = request.args.get("mes_inicial", type=int)

    if not aluno_id or not plano_id or tipo not in ("mensal", "anual") or not ano:
        return jsonify({"error": "parametros_invalidos"}), 400

    ids = _get_academias_ids()
    if academia_id not in ids:
        return jsonify({"error": "sem_permissao"}), 403

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if tipo == "mensal":
            if not mes or mes < 1 or mes > 12:
                return jsonify({"error": "mes_invalido"}), 400
            cur.execute(
                """SELECT COUNT(*) AS total
                   FROM mensalidade_aluno ma
                   JOIN mensalidades m ON m.id = ma.mensalidade_id
                   WHERE ma.aluno_id = %s AND ma.mensalidade_id = %s AND m.id_academia = %s
                     AND YEAR(ma.data_vencimento) = %s AND MONTH(ma.data_vencimento) = %s
                     AND ma.status != 'cancelado'""",
                (aluno_id, plano_id, academia_id, ano, mes),
            )
            row = cur.fetchone() or {"total": 0}
            total = row.get("total", 0) or 0
            if total > 0:
                return jsonify({"disponivel": False, "mensagem": "Este aluno já possui mensalidade para esta competência.", "total": int(total)})
            return jsonify({"disponivel": True, "mensagem": "", "total": 0})

        # Anual: período = mes_inicial até 12 (default 1). Bloqueia só se todos os meses do período já têm cobrança.
        mes_ini = (mes_inicial if mes_inicial and 1 <= mes_inicial <= 12 else 1)
        cur.execute(
            """SELECT DISTINCT MONTH(ma.data_vencimento) AS mes
               FROM mensalidade_aluno ma
               JOIN mensalidades m ON m.id = ma.mensalidade_id
               WHERE ma.aluno_id = %s AND ma.mensalidade_id = %s AND m.id_academia = %s
                 AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'
                 AND MONTH(ma.data_vencimento) BETWEEN %s AND 12""",
            (aluno_id, plano_id, academia_id, ano, mes_ini),
        )
        meses_com_cobranca = {r["mes"] for r in cur.fetchall() if r.get("mes")}
        meses_no_periodo = set(range(mes_ini, 13))
        todos_preenchidos = meses_no_periodo.issubset(meses_com_cobranca)
        if todos_preenchidos:
            return jsonify({
                "disponivel": False,
                "mensagem": "Este aluno já possui todas as mensalidades deste período no ano. Nenhum mês faltando para gerar.",
                "total": len(meses_com_cobranca),
            })
        return jsonify({"disponivel": True, "mensagem": "", "total": len(meses_com_cobranca)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


def _fmt_data_json(val):
    if val is None:
        return None
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    s = str(val)
    return s[:10] if len(s) >= 10 else s


@bp_financeiro.route("/mensalidades/cobrancas-por-aluno", methods=["GET"])
@login_required
def cobrancas_por_aluno_json():
    """Lista mensalidades e cobranças avulsas de um aluno (JSON) para modal na lista de alunos."""
    academia_id = _get_academia_id()
    if not academia_id:
        return jsonify({"error": "sem_academia"}), 400

    ids = _get_academias_ids()
    if academia_id not in ids:
        return jsonify({"error": "sem_permissao"}), 403

    aluno_id = request.args.get("aluno_id", type=int)
    if not aluno_id:
        return jsonify({"error": "aluno_invalido"}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Enxerga o aluno pela academia principal OU por vínculo adicional
        # (alunos_academias): o financeiro por academia já filtra as cobranças
        # por m.id_academia / cobranca_avulsa.id_academia mais abaixo.
        _trecho_al, _al_params = filtro_alunos_da_academia(academia_id, alias="alunos")
        cur.execute(
            f"SELECT id, nome FROM alunos WHERE id = %s AND {_trecho_al}",
            (aluno_id, *_al_params),
        )
        aluno = cur.fetchone()
        if not aluno:
            return jsonify({"error": "aluno_nao_encontrado"}), 404

        _atualizar_status_atrasadas(academia_id)

        mens_rows = []
        try:
            cur.execute(
                """
                SELECT ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                       ma.status_pagamento, m.nome AS plano_nome
                FROM mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                WHERE ma.aluno_id = %s AND m.id_academia = %s AND ma.status != 'cancelado'
                ORDER BY ma.data_vencimento DESC
                LIMIT 120
                """,
                (aluno_id, academia_id),
            )
            for r in cur.fetchall() or []:
                mens_rows.append(
                    {
                        "tipo": "mensalidade",
                        "plano_nome": r.get("plano_nome") or "Mensalidade",
                        "data_vencimento": _fmt_data_json(r.get("data_vencimento")),
                        "data_pagamento": _fmt_data_json(r.get("data_pagamento")),
                        "valor": float(r.get("valor") or 0),
                        "valor_pago": float(r.get("valor_pago") or 0) if r.get("valor_pago") is not None else None,
                        "status": (r.get("status") or "").lower(),
                        "status_efetivo": _status_efetivo(
                            r.get("status"), r.get("data_vencimento"), r.get("status_pagamento")
                        ),
                    }
                )
        except Exception:
            mens_rows = []

        avulsas_rows = []
        try:
            cur.execute(
                """
                SELECT id, descricao, valor, data_vencimento, data_pagamento, valor_pago, status
                FROM cobranca_avulsa
                WHERE aluno_id = %s AND id_academia = %s AND status != 'cancelado'
                ORDER BY data_vencimento DESC
                LIMIT 60
                """,
                (aluno_id, academia_id),
            )
            for r in cur.fetchall() or []:
                avulsas_rows.append(
                    {
                        "tipo": "avulsa",
                        "descricao": r.get("descricao") or "Cobrança avulsa",
                        "data_vencimento": _fmt_data_json(r.get("data_vencimento")),
                        "data_pagamento": _fmt_data_json(r.get("data_pagamento")),
                        "valor": float(r.get("valor") or 0),
                        "valor_pago": float(r.get("valor_pago") or 0) if r.get("valor_pago") is not None else None,
                        "status": (r.get("status") or "").lower(),
                    }
                )
        except Exception:
            avulsas_rows = []

        return jsonify(
            {
                "aluno_nome": aluno.get("nome") or "",
                "mensalidades": mens_rows,
                "avulsas": avulsas_rows,
            }
        )
    finally:
        cur.close()
        conn.close()


@bp_financeiro.route("/mensalidades/buscar-alunos")
@login_required
def buscar_alunos_mensalidades():
    """Busca alunos da academia para aplicar desconto."""
    acad_id = request.args.get("academia_id", type=int) or _get_academia_id()
    busca = (request.args.get("busca") or "").strip()[:100]
    ids = _get_academias_ids()
    if not acad_id or acad_id not in ids:
        return jsonify([])
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Inclui alunos com esta academia como principal E os vinculados a ela.
        _trecho_al, _al_params = filtro_alunos_da_academia(acad_id, alias="a")
        if busca:
            cur.execute(
                f"SELECT a.id, a.nome, a.foto FROM alunos a WHERE {_trecho_al} AND a.ativo = 1 AND a.nome LIKE %s ORDER BY a.nome LIMIT 50",
                (*_al_params, f"%{busca}%"),
            )
        else:
            cur.execute(
                f"SELECT a.id, a.nome, a.foto FROM alunos a WHERE {_trecho_al} AND a.ativo = 1 ORDER BY a.nome LIMIT 30",
                tuple(_al_params),
            )
        rows = cur.fetchall()
        for r in rows:
            r["foto_url"] = url_for("static", filename="uploads/" + r["foto"]) if r.get("foto") else None
    except Exception:
        try:
            cur.execute(
                f"SELECT a.id, a.nome, a.foto FROM alunos a WHERE {filtro_alunos_da_academia(acad_id)[0]}"
                " AND a.ativo = 1 ORDER BY a.nome LIMIT 30",
                tuple(filtro_alunos_da_academia(acad_id)[1]),
            )
            rows = cur.fetchall()
            for r in rows:
                r["foto_url"] = url_for("static", filename="uploads/" + r["foto"]) if r.get("foto") else None
        except Exception:
            rows = []
    conn.close()
    return jsonify(rows)


@bp_financeiro.route("/mensalidades/alunos-por-academia")
@bp_financeiro.route("/mensalidades/alunos-por-academia/<int:acad_id>")
@login_required
def alunos_por_academia(acad_id=None):
    """Retorna alunos da academia. Se turma_id: só alunos da turma.
    Se plano_id, ano e mes_inicial: disabled=True para quem já tem mensalidade no período."""
    try:
        ids = _get_academias_ids()
        try:
            ids = [int(x) for x in ids]
        except (TypeError, ValueError):
            ids = []
        if not ids:
            return jsonify([])
        if acad_id is None:
            acad_id = request.args.get("academia_id", type=int)
        if not acad_id or acad_id not in ids:
            acad_id = ids[0]
        turma_id = request.args.get("turma_id", type=int)
        plano_id = request.args.get("plano_id", type=int)
        ano = request.args.get("ano", type=int)
        mes_inicial = request.args.get("mes_inicial", type=int)
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        rows = []
        meses = list(range(mes_inicial, 13)) if (plano_id and ano and mes_inicial and 1 <= mes_inicial <= 12) else []
        meses_ph = ",".join(["%s"] * len(meses)) if meses else ""
        try:
            if turma_id and meses:
                cur.execute(
                    """SELECT DISTINCT a.id, a.nome
                       FROM alunos a
                       LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                       LEFT JOIN mensalidade_aluno ma ON ma.aluno_id = a.id
                         AND ma.mensalidade_id = %s
                         AND YEAR(ma.data_vencimento) = %s
                         AND MONTH(ma.data_vencimento) IN (""" + meses_ph + """)
                         AND ma.status != 'cancelado'
                       WHERE a.id_academia = %s
                         AND (at.TurmaID IS NOT NULL OR a.TurmaID = %s)
                         AND ma.id IS NULL
                       ORDER BY a.nome""",
                    (turma_id, plano_id, ano) + tuple(meses) + (acad_id, turma_id),
                )
                rows = cur.fetchall()
            elif turma_id:
                cur.execute(
                    """SELECT DISTINCT a.id, a.nome FROM alunos a
                       LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                       WHERE {_f} AND (at.TurmaID IS NOT NULL OR a.TurmaID = %s)
                       ORDER BY a.nome""".format(_f=filtro_alunos_da_academia(acad_id)[0]),
                    (turma_id, *filtro_alunos_da_academia(acad_id)[1], turma_id),
                )
                rows = cur.fetchall()
            else:
                cur.execute(
                    "SELECT id, nome FROM alunos WHERE id_academia = %s ORDER BY nome",
                    (acad_id,),
                )
                rows = cur.fetchall()
        except Exception:
            try:
                if turma_id and meses:
                    cur.execute(
                        """SELECT DISTINCT a.id, a.nome
                           FROM alunos a
                           LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                           LEFT JOIN mensalidade_aluno ma ON ma.aluno_id = a.id
                             AND ma.mensalidade_id = %s
                             AND YEAR(ma.data_vencimento) = %s
                             AND MONTH(ma.data_vencimento) IN (""" + meses_ph + """)
                             AND ma.status != 'cancelado'
                           WHERE a.id_academia = %s
                             AND (at.TurmaID IS NOT NULL OR a.TurmaID = %s)
                             AND ma.id IS NULL
                           ORDER BY a.nome""",
                        (turma_id, plano_id, ano) + tuple(meses) + (acad_id, turma_id),
                    )
                    rows = cur.fetchall()
                elif turma_id:
                    cur.execute(
                        "SELECT id, nome FROM alunos WHERE id_academia = %s AND TurmaID = %s ORDER BY nome",
                        (acad_id, turma_id),
                    )
                    rows = cur.fetchall()
                else:
                    cur.execute(
                        "SELECT id, nome FROM alunos WHERE id_academia = %s ORDER BY nome",
                        (acad_id,),
                    )
                    rows = cur.fetchall()
            except Exception:
                rows = []
        conn.close()
        out = [{"id": int(r.get("id") or 0), "nome": str(r.get("nome") or ""), "disabled": False} for r in rows]
        return jsonify(out)
    except Exception:
        return jsonify([])


def _auto_gerar_asaas(registros, metodo):
    """Best-effort: cria cobranças no Asaas para registros recém-gerados.

    registros: lista de dicts com origem ('mensalidade'|'avulsa'), id, aluno_id,
               id_academia, valor, data_vencimento, descricao e mensalidade_id (opcional).
    Para mensalidades, usa o valor líquido (com desconto). Ignora valores < R$5.
    Retorna (geradas, ignoradas, falhas).
    """
    metodo = (metodo or "").upper()
    if metodo not in ("PIX", "BOLETO", "LINK") or not registros:
        return (0, 0, 0)
    geradas = ignoradas = falhas = 0
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cred_cache = {}
    aluno_cache = {}
    try:
        for reg in registros:
            acad = reg.get("id_academia")
            if acad not in cred_cache:
                cred_cache[acad] = _gateway_config_academia(acad) or {}
            cfg = cred_cache[acad]
            if not _gateway_ativo(cfg):
                ignoradas += 1
                continue
            valor = float(reg.get("valor") or 0)
            if reg.get("origem") == "mensalidade":
                ma = {
                    "valor": valor, "data_vencimento": reg.get("data_vencimento"),
                    "mensalidade_id": reg.get("mensalidade_id"), "id_academia": acad,
                }
                _, _, valor, _ = _valor_com_desconto(ma, reg.get("aluno_id"), acad)
                valor = float(valor or 0)
            if valor < 5:
                ignoradas += 1
                continue
            aid = reg.get("aluno_id")
            if aid not in aluno_cache:
                cur.execute(
                    "SELECT nome, cpf, email, telefone, "
                    "responsavel_financeiro_nome, responsavel_financeiro_cpf, "
                    "responsavel_financeiro_telefone, "
                    "cep, rua, numero, complemento, bairro, cidade, estado "
                    "FROM alunos WHERE id=%s",
                    (aid,),
                )
                aluno_cache[aid] = cur.fetchone() or {}
            al = aluno_cache[aid]
            pag_nome, pag_cpf, pag_tel = _dados_pagador(al)
            try:
                r = _emitir_cobranca_online(
                    cfg, metodo, nome=pag_nome, cpf=pag_cpf, email=al.get("email"),
                    telefone=pag_tel, valor=valor, vencimento=reg.get("data_vencimento"),
                    descricao=reg.get("descricao") or "Cobrança",
                    origem=reg.get("origem"), registro_id=reg["id"],
                    endereco=_endereco_aluno(al),
                )
                tabela = "mensalidade_aluno" if reg.get("origem") == "mensalidade" else "cobranca_avulsa"
                cur.execute(
                    f"""UPDATE {tabela}
                        SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                            asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s, gateway=%s
                        WHERE id=%s""",
                    (r["payment_id"], r["tipo"], r["boleto_url"], r["pix_qrcode"], r["pix_copia_cola"], r["gateway"], reg["id"]),
                )
                conn.commit()
                geradas += 1
            except Exception as e:
                conn.rollback()
                current_app.logger.error(f"Auto cobrança online falhou ({reg.get('origem')} {reg.get('id')}): {e}")
                falhas += 1
    finally:
        conn.close()
    return (geradas, ignoradas, falhas)


def _flash_resumo_asaas(geradas, ignoradas, falhas, metodo):
    rotulo = "link de pagamento" if metodo == "LINK" else metodo
    if geradas:
        flash(f"Cobrança online ({rotulo}) gerada para {geradas} cobrança(s). O aluno já pode pagar.", "success")
    if ignoradas:
        flash(f"{ignoradas} cobrança(s) sem cobrança online (valor abaixo de R$ 5,00 ou gateway indisponível).", "warning")
    if falhas:
        flash(
            f"{falhas} cobrança(s) não puderam gerar a cobrança online. "
            "Verifique: dados do aluno (CPF/e-mail) e as credenciais do gateway. "
            "No Mercado Pago, a conta precisa ter uma CHAVE PIX cadastrada para gerar PIX "
            "(erro 'collector user without key'). Veja o detalhe no log do sistema.",
            "warning",
        )


def _aplica_desconto_valor(valor_base, tipo, dval):
    """Aplica um desconto (percentual ou valor_fixo) a um valor. Retorna (desconto, valor_final)."""
    valor_base = float(valor_base or 0)
    dval = float(dval or 0)
    if (tipo or "percentual") == "percentual":
        desc = valor_base * (dval / 100.0)
    else:
        desc = min(dval, valor_base)
    desc = round(desc, 2)
    return desc, max(0.0, round(valor_base - desc, 2))


def _resolver_desconto_form(cur_dict, form, id_acad):
    """Resolve o desconto escolhido no modal de cobrança (cadastrado ou avulso/manual).
    Retorna (tipo, valor, nome, desconto_id) ou None quando não há desconto."""
    raw = (form.get("desconto_id") or "").strip()
    if not raw:
        return None
    if raw == "avulso":
        tipo = (form.get("desconto_manual_tipo") or "percentual").strip()
        if tipo not in ("percentual", "valor_fixo"):
            tipo = "percentual"
        val = _parse_valor(form.get("desconto_manual_valor") or "")
        if val is None or val <= 0:
            return None
        return (tipo, float(val), "Desconto avulso", None)
    if raw.isdigit():
        try:
            cur_dict.execute(
                "SELECT nome, tipo, valor FROM descontos WHERE id = %s AND id_academia = %s",
                (int(raw), id_acad),
            )
            d = cur_dict.fetchone()
        except Exception:
            d = None
        if d:
            return ((d.get("tipo") or "percentual"), float(d.get("valor") or 0), d.get("nome") or "Desconto", int(raw))
    return None


@bp_financeiro.route("/mensalidades/gerar-cobranca", methods=["GET", "POST"])
@login_required
def gerar_cobranca():
    """Gerar cobrança avulsa ou mensalidade para aluno(s)."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()

    if request.method == "POST":
        tipo = request.form.get("tipo") or "avulso"
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aluno_ids_raw = request.form.getlist("aluno_id")
        if not aluno_ids_raw:
            aluno_ids_raw = [request.form.get("aluno_id")] if request.form.get("aluno_id") else []
        aluno_ids = [int(x) for x in aluno_ids_raw if x and str(x).isdigit()]

        if not aluno_ids:
            flash("Selecione ao menos um aluno.", "danger")
            return _render_gerar_cobranca(academias, academia_id, id_acad, None, None, None, None)

        def _redirect_after_gerar():
            next_url = (request.form.get("next") or "").strip()
            if next_url and next_url.startswith("/") and "//" not in next_url:
                return redirect(next_url)
            return redirect(url_for("financeiro.gerar_cobranca", academia_id=id_acad))

        # mensal = uma única mensalidade no mês escolhido; ano = de mes_inicial até dezembro
        eh_mensal_unico = tipo == "mensal"

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            if tipo == "avulso":
                if len(aluno_ids) > 1:
                    flash("Para cobrança avulsa, selecione apenas um aluno.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad, None, None, None, None)
                data_venc = request.form.get("data_vencimento", "").strip()
                if not data_venc:
                    flash("Informe a data de vencimento.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad, None, None, None, None)
                descricao = (request.form.get("descricao") or "").strip() or "Cobrança avulsa"
                valor_str = request.form.get("valor") or ""
                valor = _parse_valor(valor_str)
                if valor is None or valor < 0:
                    flash("Informe um valor válido.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad, None, None, None, None)

                # Desconto opcional na cobrança avulsa (cadastrado ou avulso/manual)
                valor_original = valor
                obs_desconto = None
                curd = conn.cursor(dictionary=True)
                desc_sel = _resolver_desconto_form(curd, request.form, id_acad)
                curd.close()
                if desc_sel:
                    d_tipo, d_val, d_nome, _d_id = desc_sel
                    desc_aplicado, valor = _aplica_desconto_valor(valor_original, d_tipo, d_val)
                    obs_desconto = (
                        f"Desconto '{d_nome}' aplicado: "
                        f"R$ {valor_original:.2f} - R$ {desc_aplicado:.2f} = R$ {valor:.2f}"
                    )

                isenta = float(valor or 0) <= 0
                st_ins = "pago" if isenta else "pendente"
                dt_pag = data_venc if isenta else None
                vpg = 0 if isenta else None
                try:
                    cur.execute(
                        """INSERT INTO cobranca_avulsa (aluno_id, id_academia, descricao, valor, data_vencimento, status, data_pagamento, valor_pago, observacoes, criado_por)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (aluno_ids[0], id_acad, descricao, valor, data_venc, st_ins, dt_pag, vpg, obs_desconto, current_user.id),
                    )
                except Exception:
                    cur.execute(
                        "INSERT INTO cobranca_avulsa (aluno_id, id_academia, descricao, valor, data_vencimento, status) VALUES (%s, %s, %s, %s, %s, %s)",
                        (aluno_ids[0], id_acad, descricao, valor, data_venc, st_ins),
                    )
                av_id = cur.lastrowid
                # Receita R$ 0 quando isenta por desconto integral
                if isenta and av_id:
                    try:
                        cur.execute("SELECT nome FROM alunos WHERE id = %s", (aluno_ids[0],))
                        _an = cur.fetchone()
                        _anome = (_an[0] if isinstance(_an, (list, tuple)) else (_an.get("nome") if _an else "")) or "Aluno"
                        cur.execute(
                            "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, criado_por) VALUES (%s, 0, %s, 'Cobranças avulsas', %s, %s)",
                            (f"{descricao} - {_anome} (Desconto integral)", data_venc, id_acad, current_user.id),
                        )
                    except Exception:
                        pass
                conn.commit()
                conn.close()
                flash("Cobrança avulsa gerada." + (" Isenta por desconto integral (registrada como paga)." if isenta else ""), "success")
                metodo = (request.form.get("asaas_metodo") or "").upper()
                if metodo in ("PIX", "BOLETO", "LINK") and av_id:
                    g, ig, fl = _auto_gerar_asaas([{
                        "origem": "avulsa", "id": av_id, "aluno_id": aluno_ids[0],
                        "id_academia": id_acad, "valor": valor, "data_vencimento": data_venc,
                        "descricao": descricao,
                    }], metodo)
                    _flash_resumo_asaas(g, ig, fl, metodo)
                return _redirect_after_gerar()
            else:
                plano_id = request.form.get("mensalidade_id", type=int)
                turma_id = request.form.get("turma_id", type=int)
                ano_ref = request.form.get("ano_ref", type=int) or date.today().year
                mes_inicial = request.form.get("mes_inicial", type=int) or (1 if not eh_mensal_unico else None)
                dia_venc = min(28, max(1, request.form.get("dia_vencimento", type=int) or 10))
                if eh_mensal_unico and (not mes_inicial or mes_inicial < 1 or mes_inicial > 12):
                    flash("Selecione o mês para a mensalidade.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad, None, None, None, None)
                if not plano_id:
                    flash("Selecione o plano de mensalidade.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad, None, None, None, None)
                cur.execute("SELECT id, nome, valor FROM mensalidades WHERE id = %s AND id_academia = %s", (plano_id, id_acad))
                plano = cur.fetchone()
                if not plano:
                    flash("Plano de mensalidade não encontrado.", "danger")
                    conn.close()
                    return _render_gerar_cobranca(academias, academia_id, id_acad, None, None, None, None)
                valor_plano = float(plano[2] if isinstance(plano, (list, tuple)) else plano.get("valor", 0))
                dias_por_mes = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
                geradas = 0
                ja_existentes = 0
                duplicidades_detalhe = []
                nomes_por_id = {}
                criadas_mens = []
                plano_nome = (plano[1] if isinstance(plano, (list, tuple)) else plano.get("nome", "")) or "Mensalidade"
                # Desconto escolhido no modal (cadastrado ou avulso) aplicado a TODAS as parcelas do período.
                curd = conn.cursor(dictionary=True)
                desc_mod = _resolver_desconto_form(curd, request.form, id_acad)
                curd.close()
                # Se não veio turma_id (porque a tela não tem mais seleção de turma),
                # tenta buscar a TurmaID do aluno para preencher o campo ao registrar.
                turma_por_aluno = {}
                if not turma_id and aluno_ids:
                    try:
                        ph = ",".join(["%s"] * len(aluno_ids))
                        cur.execute(f"SELECT id, TurmaID FROM alunos WHERE id IN ({ph})", tuple(aluno_ids))
                        for sid, tid in cur.fetchall():
                            if tid is not None:
                                turma_por_aluno[int(sid)] = int(tid)
                    except Exception:
                        turma_por_aluno = {}
                if aluno_ids:
                    try:
                        ph = ",".join(["%s"] * len(aluno_ids))
                        cur.execute(f"SELECT id, nome FROM alunos WHERE id IN ({ph})", tuple(aluno_ids))
                        for sid, snome in cur.fetchall():
                            nomes_por_id[int(sid)] = snome
                    except Exception:
                        nomes_por_id = {}
                # Mensal: apenas o mês escolhido. Anual: do mês inicial até dezembro.
                mes_fim = (mes_inicial + 1) if eh_mensal_unico else 13
                for mes in range(mes_inicial, mes_fim):
                    dia = min(dia_venc, dias_por_mes.get(mes, 28))
                    data_venc = f"{ano_ref}-{mes:02d}-{dia:02d}"
                    for aid in aluno_ids:
                        try:
                            cur.execute(
                                """SELECT 1 FROM mensalidade_aluno
                                   WHERE aluno_id = %s AND mensalidade_id = %s
                                   AND data_vencimento = %s AND status != 'cancelado'""",
                                (aid, plano_id, data_venc),
                            )
                            if cur.fetchone():
                                ja_existentes += 1
                                nome_aluno = nomes_por_id.get(aid) or f"Aluno #{aid}"
                                duplicidades_detalhe.append(f"{nome_aluno} ({mes:02d}/{ano_ref})")
                                continue
                            tid = turma_id if turma_id else turma_por_aluno.get(aid)
                            if desc_mod is not None:
                                # Desconto escolhido no modal: aplica ao valor do plano e materializa as colunas.
                                d_tipo, d_val, _d_nome, d_id = desc_mod
                                desc_aplicado, valor_final = _aplica_desconto_valor(valor_plano, d_tipo, d_val)
                                if valor_final <= 0:
                                    st, stp, dtp, vpg = "pago", "pago", data_venc, 0
                                else:
                                    st, stp, dtp, vpg = "pendente", "pendente", None, None
                                if tid:
                                    cur.execute(
                                        """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, turma_id, data_vencimento, valor, valor_original, desconto_aplicado, id_desconto, status, status_pagamento, data_pagamento, valor_pago)
                                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                        (plano_id, aid, tid, data_venc, valor_final, valor_plano, desc_aplicado, d_id, st, stp, dtp, vpg),
                                    )
                                else:
                                    cur.execute(
                                        """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, data_vencimento, valor, valor_original, desconto_aplicado, id_desconto, status, status_pagamento, data_pagamento, valor_pago)
                                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                        (plano_id, aid, data_venc, valor_final, valor_plano, desc_aplicado, d_id, st, stp, dtp, vpg),
                                    )
                                valor_reg = valor_final
                            else:
                                # Desconto integral já atribuído ao aluno (valor final = 0): já nasce PAGA.
                                _vi, _vd, _vf, _dn = _valor_com_desconto(
                                    {"valor": valor_plano, "mensalidade_id": plano_id,
                                     "id_academia": id_acad, "data_vencimento": data_venc},
                                    aid, id_acad, hoje=date.fromisoformat(data_venc))
                                if float(_vf or 0) <= 0:
                                    st, stp, dtp, vpg = "pago", "pago", data_venc, 0
                                else:
                                    st, stp, dtp, vpg = "pendente", "pendente", None, None
                                if tid:
                                    cur.execute(
                                        """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, turma_id, data_vencimento, valor, status, status_pagamento, data_pagamento, valor_pago)
                                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                        (plano_id, aid, tid, data_venc, valor_plano, st, stp, dtp, vpg),
                                    )
                                else:
                                    cur.execute(
                                        """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, data_vencimento, valor, status, status_pagamento, data_pagamento, valor_pago)
                                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                                        (plano_id, aid, data_venc, valor_plano, st, stp, dtp, vpg),
                                    )
                                valor_reg = valor_plano
                            criadas_mens.append({
                                "origem": "mensalidade", "id": cur.lastrowid, "aluno_id": aid,
                                "id_academia": id_acad, "valor": valor_reg, "data_vencimento": data_venc,
                                "mensalidade_id": plano_id, "descricao": f"Mensalidade {plano_nome}",
                            })
                            geradas += 1
                        except Exception:
                            pass
                conn.commit()
                if geradas == 0 and ja_existentes > 0:
                    if eh_mensal_unico:
                        alunos_dup = sorted({item.split(" (")[0] for item in duplicidades_detalhe})
                        nomes_preview = ", ".join(alunos_dup[:5])
                        if len(alunos_dup) > 5:
                            nomes_preview += "..."
                        flash(
                            f"Não foi gerada cobrança: já existe mensalidade na competência {mes_inicial:02d}/{ano_ref} para {len(alunos_dup)} aluno(s) ({nomes_preview}).",
                            "warning",
                        )
                    else:
                        flash("Nenhuma cobrança nova foi gerada: todas as competências do período já existem.", "warning")
                elif eh_mensal_unico:
                    flash("Mensalidade gerada para o mês selecionado.", "success")
                    if ja_existentes > 0:
                        flash(f"{ja_existentes} aluno(s) já tinham cobrança nessa competência e foram ignorados.", "warning")
                elif mes_inicial == 1:
                    flash(f"{geradas} cobrança(s) gerada(s) para o ano (todos os meses).", "success")
                    if ja_existentes > 0:
                        flash(f"{ja_existentes} competência(s) já possuíam cobrança e não foram duplicadas.", "warning")
                else:
                    flash(f"{geradas} cobrança(s) gerada(s) do mês {mes_inicial} até dezembro.", "success")
                    if ja_existentes > 0:
                        flash(f"{ja_existentes} competência(s) já possuíam cobrança e não foram duplicadas.", "warning")
                conn.close()
                metodo = (request.form.get("asaas_metodo") or "").upper()
                if metodo in ("PIX", "BOLETO", "LINK") and criadas_mens:
                    g, ig, fl = _auto_gerar_asaas(criadas_mens, metodo)
                    _flash_resumo_asaas(g, ig, fl, metodo)
                return _redirect_after_gerar()
        except Exception as e:
            conn.rollback()
            flash(f"Erro ao gerar cobrança: {e}", "danger")
        conn.close()
        next_url = (request.form.get("next") or "").strip()
        if next_url and next_url.startswith("/") and "//" not in next_url:
            return redirect(next_url)
        return redirect(url_for("financeiro.gerar_cobranca", academia_id=academia_id))

    academia_sel = request.args.get("academia_id", type=int) or academia_id
    if academia_sel not in ids:
        academia_sel = academia_id
    # Nesta tela não é mais necessário filtrar por turma.
    turma_id = None
    plano_id = request.args.get("plano_id", type=int)
    ano_ref = request.args.get("ano_ref", type=int)
    mes_inicial = request.args.get("mes_inicial", type=int)
    return _render_gerar_cobranca(academias, academia_id, academia_sel, turma_id, plano_id, ano_ref, mes_inicial)


@bp_financeiro.route("/mensalidades/aplicar-desconto", methods=["GET", "POST"])
@login_required
def aplicar_desconto():
    """Aplicar desconto ao aluno com vigência; se 100% marca mensalidades como pagas."""
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    if academia_id not in ids:
        academia_id = ids[0] if ids else None

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome, tipo, valor FROM descontos WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_id,),
        )
    except Exception:
        cur.execute(
            "SELECT id, nome, tipo, valor FROM descontos WHERE id_academia = %s ORDER BY nome",
            (academia_id,),
        )
    descontos = cur.fetchall()

    pacotes_mensalidades = []
    try:
        cur.execute(
            "SELECT id, nome FROM mensalidades WHERE id_academia = %s AND COALESCE(ativo, 1) = 1 ORDER BY nome",
            (academia_id,),
        )
        pacotes_mensalidades = cur.fetchall()
    except Exception:
        try:
            cur.execute(
                "SELECT id, nome FROM mensalidades WHERE id_academia = %s ORDER BY nome",
                (academia_id,),
            )
            pacotes_mensalidades = cur.fetchall()
        except Exception:
            pacotes_mensalidades = []

    if request.method == "POST":
        acao = request.form.get("acao")
        if acao == "cancelar":
            aluno_id = request.form.get("aluno_id", type=int)
            desconto_id = request.form.get("desconto_id", type=int)
            ad_id = request.form.get("aluno_desconto_id", type=int)
            if not aluno_id or not desconto_id:
                flash("Parâmetros inválidos.", "danger")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            try:
                cur.execute(
                    "UPDATE aluno_desconto SET ativo = 0 WHERE aluno_id = %s AND desconto_id = %s",
                    (aluno_id, desconto_id),
                )
                try:
                    cur.execute(
                        """SELECT ma.id, ma.valor_original, ma.desconto_aplicado, ma.status, ma.valor
                           FROM mensalidade_aluno ma
                           JOIN mensalidades m ON m.id = ma.mensalidade_id
                           WHERE ma.aluno_id = %s AND ma.id_desconto = %s AND ma.status != 'cancelado'""",
                        (aluno_id, desconto_id),
                    )
                except Exception:
                    rows = []
                else:
                    rows = cur.fetchall()
                for r in rows:
                    desconto_100 = (float(r.get("valor") or 0) == 0 and float(r.get("desconto_aplicado") or 0) > 0)
                    valor_orig = float(r.get("valor_original") or 0)
                    if valor_orig <= 0:
                        valor_orig = float(r.get("valor") or 0) + float(r.get("desconto_aplicado") or 0)
                    if valor_orig <= 0:
                        cur.execute("SELECT m.valor FROM mensalidades m JOIN mensalidade_aluno ma ON ma.mensalidade_id = m.id WHERE ma.id = %s", (r["id"],))
                        v = cur.fetchone()
                        valor_orig = float(v.get("valor", 0) or 0) if v else 0
                    try:
                        if desconto_100 and (r.get("status") or "").lower() == "pago":
                            cur.execute(
                                """UPDATE mensalidade_aluno SET valor = %s, valor_original = NULL, desconto_aplicado = 0, id_desconto = NULL, status = 'pendente', data_pagamento = NULL
                                   WHERE id = %s""",
                                (valor_orig, r["id"]),
                            )
                        else:
                            cur.execute(
                                """UPDATE mensalidade_aluno SET valor = %s, valor_original = NULL, desconto_aplicado = 0, id_desconto = NULL WHERE id = %s""",
                                (valor_orig, r["id"]),
                            )
                    except Exception:
                        try:
                            cur.execute("UPDATE mensalidade_aluno SET valor = %s, status = 'pendente', data_pagamento = NULL WHERE id = %s", (valor_orig, r["id"]))
                        except Exception:
                            cur.execute("UPDATE mensalidade_aluno SET valor = %s WHERE id = %s", (valor_orig, r["id"]))
                conn.commit()
                flash("Desconto cancelado. Mensalidades revertidas.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Erro ao cancelar: {e}", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        if acao == "editar":
            ad_id = request.form.get("aluno_desconto_id", type=int)
            aluno_id = request.form.get("aluno_id", type=int)
            desconto_atual = request.form.get("desconto_id", type=int)
            novo_desconto_id = request.form.get("novo_desconto_id", type=int)
            data_inicio = (request.form.get("data_inicio") or "").strip()
            data_fim = (request.form.get("data_fim") or "").strip()
            if not ad_id or not aluno_id or not novo_desconto_id:
                flash("Parâmetros inválidos.", "danger")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            cur.execute(
                "SELECT ad.id, ad.desconto_id FROM aluno_desconto ad JOIN descontos d ON d.id = ad.desconto_id WHERE ad.id = %s AND d.id_academia = %s AND ad.ativo = 1",
                (ad_id, academia_id),
            )
            ad_row = cur.fetchone()
            if not ad_row:
                flash("Vínculo não encontrado.", "warning")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            desconto_atual = ad_row.get("desconto_id") or desconto_atual
            cur.execute(
                "SELECT id FROM descontos WHERE id = %s AND id_academia = %s",
                (novo_desconto_id, academia_id),
            )
            if not cur.fetchone():
                flash("Desconto não encontrado.", "danger")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            try:
                dt_ini = date.fromisoformat(data_inicio) if data_inicio else date.today()
                dt_fim = date.fromisoformat(data_fim) if data_fim else date(2099, 12, 31)
            except Exception:
                dt_ini = date.today()
                dt_fim = date(2099, 12, 31)
            aplica_todos_ed = request.form.get("aplica_todos_pacotes", "1") == "1"
            if not pacotes_mensalidades:
                aplica_todos_ed = True
            raw_pac_ed = request.form.getlist("pacotes_mensalidade_id")
            permitidos_ed = {int(p["id"]) for p in pacotes_mensalidades}
            pacotes_ids_ed = []
            for x in raw_pac_ed:
                try:
                    xi = int(x)
                    if xi in permitidos_ed:
                        pacotes_ids_ed.append(xi)
                except (TypeError, ValueError):
                    pass
            if not aplica_todos_ed and not pacotes_ids_ed:
                flash("Selecione ao menos um pacote ou marque Aplicar a todos os pacotes.", "warning")
                conn.close()
                return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
            pacotes_json_ed = None if aplica_todos_ed else json.dumps(sorted(set(pacotes_ids_ed)))
            try:
                if novo_desconto_id == desconto_atual:
                    try:
                        cur.execute(
                            """
                            UPDATE aluno_desconto SET data_inicio = %s, data_fim = %s,
                            aplica_todos_pacotes = %s, pacotes_mensalidade_ids = %s
                            WHERE id = %s AND aluno_id = %s
                            """,
                            (
                                dt_ini,
                                dt_fim,
                                1 if aplica_todos_ed else 0,
                                pacotes_json_ed,
                                ad_id,
                                aluno_id,
                            ),
                        )
                    except Exception:
                        cur.execute(
                            "UPDATE aluno_desconto SET data_inicio = %s, data_fim = %s WHERE id = %s AND aluno_id = %s",
                            (dt_ini, dt_fim, ad_id, aluno_id),
                        )
                else:
                    cur.execute(
                        "SELECT id FROM aluno_desconto WHERE aluno_id = %s AND desconto_id = %s AND ativo = 1",
                        (aluno_id, novo_desconto_id),
                    )
                    existente = cur.fetchone()
                    if existente and existente.get("id") != ad_id:
                        cur.execute(
                            "UPDATE aluno_desconto SET data_inicio = %s, data_fim = %s WHERE id = %s",
                            (dt_ini, dt_fim, existente["id"]),
                        )
                        cur.execute("UPDATE aluno_desconto SET ativo = 0 WHERE id = %s", (ad_id,))
                    else:
                        try:
                            cur.execute(
                                """
                                UPDATE aluno_desconto SET desconto_id = %s, data_inicio = %s, data_fim = %s,
                                aplica_todos_pacotes = %s, pacotes_mensalidade_ids = %s WHERE id = %s
                                """,
                                (
                                    novo_desconto_id,
                                    dt_ini,
                                    dt_fim,
                                    1 if aplica_todos_ed else 0,
                                    pacotes_json_ed,
                                    ad_id,
                                ),
                            )
                        except Exception:
                            cur.execute(
                                "UPDATE aluno_desconto SET desconto_id = %s, data_inicio = %s, data_fim = %s WHERE id = %s",
                                (novo_desconto_id, dt_ini, dt_fim, ad_id),
                            )
                conn.commit()
                flash("Desconto atualizado.", "success")
            except Exception as e:
                conn.rollback()
                flash(f"Erro ao atualizar: {e}", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        aluno_id = request.form.get("aluno_id", type=int)
        desconto_id = request.form.get("desconto_id", type=int)
        data_inicio = (request.form.get("data_inicio") or "").strip()
        data_fim = (request.form.get("data_fim") or "").strip()
        if not aluno_id or not desconto_id:
            flash("Selecione o aluno e o desconto.", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        cur.execute(
            "SELECT id, nome, tipo, valor FROM descontos WHERE id = %s AND id_academia = %s",
            (desconto_id, academia_id),
        )
        d = cur.fetchone()
        if not d:
            flash("Desconto não encontrado.", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        cur.execute("SELECT id FROM alunos WHERE id = %s AND id_academia = %s", (aluno_id, academia_id))
        if not cur.fetchone():
            flash("Aluno não encontrado.", "danger")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

        try:
            dt_ini = date.fromisoformat(data_inicio) if data_inicio else date.today()
            dt_fim = date.fromisoformat(data_fim) if data_fim else date(2099, 12, 31)
        except Exception:
            dt_ini = date.today()
            dt_fim = date(2099, 12, 31)

        aplica_todos = request.form.get("aplica_todos_pacotes", "1") == "1"
        if not pacotes_mensalidades:
            aplica_todos = True
        raw_pacotes = request.form.getlist("pacotes_mensalidade_id")
        permitidos_pac = {int(p["id"]) for p in pacotes_mensalidades}
        pacotes_ids = []
        for x in raw_pacotes:
            try:
                xi = int(x)
                if xi in permitidos_pac:
                    pacotes_ids.append(xi)
            except (TypeError, ValueError):
                pass
        if not aplica_todos and not pacotes_ids:
            flash("Selecione ao menos um pacote ou marque Aplicar a todos os pacotes.", "warning")
            conn.close()
            return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))
        pacotes_set = None if aplica_todos else set(pacotes_ids)

        tipo = d.get("tipo") or "percentual"
        val_desc = float(d.get("valor") or 0)

        _upsert_aluno_desconto_com_pacotes(
            cur, aluno_id, desconto_id, dt_ini, dt_fim, aplica_todos, pacotes_ids
        )

        try:
            cur.execute(
                """SELECT ma.id, ma.mensalidade_id, ma.valor, ma.data_vencimento, ma.status, ma.valor_original,
                          m.nome as plano_nome, a.nome as aluno_nome
                   FROM mensalidade_aluno ma
                   JOIN mensalidades m ON m.id = ma.mensalidade_id
                   JOIN alunos a ON a.id = ma.aluno_id
                   WHERE ma.aluno_id = %s AND m.id_academia = %s AND ma.status IN ('pendente', 'atrasado')
                   AND ma.data_vencimento >= %s AND ma.data_vencimento <= %s
                   AND (ma.id_desconto IS NULL OR ma.id_desconto = %s)""",
                (aluno_id, academia_id, dt_ini, dt_fim, desconto_id),
            )
            mensalidades = cur.fetchall()
        except Exception:
            try:
                cur.execute(
                    """SELECT ma.id, ma.mensalidade_id, ma.valor, ma.data_vencimento, ma.status, ma.valor_original,
                              m.nome as plano_nome, a.nome as aluno_nome
                       FROM mensalidade_aluno ma
                       JOIN mensalidades m ON m.id = ma.mensalidade_id
                       JOIN alunos a ON a.id = ma.aluno_id
                       WHERE ma.aluno_id = %s AND (m.id_academia = %s OR a.id_academia = %s)
                       AND ma.status IN ('pendente', 'atrasado')
                       AND ma.data_vencimento >= %s AND ma.data_vencimento <= %s""",
                    (aluno_id, academia_id, academia_id, dt_ini, dt_fim),
                )
                mensalidades = cur.fetchall()
            except Exception:
                mensalidades = []

        hoje_str = date.today().strftime("%Y-%m-%d")
        aplicadas = 0
        teve_100 = False
        for ma in mensalidades:
            if pacotes_set is not None:
                try:
                    mid = int(ma.get("mensalidade_id"))
                except (TypeError, ValueError):
                    continue
                if mid not in pacotes_set:
                    continue
            valor_base = float(ma.get("valor") or 0)
            valor_orig = float(ma.get("valor_original") or 0) or valor_base
            if tipo == "percentual":
                desconto_val = valor_base * (val_desc / 100)
            else:
                desconto_val = min(val_desc, valor_base)
            valor_final = round(valor_base - desconto_val, 2)
            if valor_final < 0:
                valor_final = 0
            desconto_100 = valor_final <= 0
            if desconto_100:
                teve_100 = True

            try:
                if desconto_100:
                    cur.execute(
                        """UPDATE mensalidade_aluno SET valor_original = %s, desconto_aplicado = %s, valor = 0, id_desconto = %s, status = 'pago', status_pagamento = 'pago', valor_pago = 0, data_pagamento = %s WHERE id = %s""",
                        (valor_orig, round(desconto_val, 2), desconto_id, hoje_str, ma["id"]),
                    )
                    venc = ma.get("data_vencimento")
                    try:
                        data_receita = venc.strftime("%Y-%m-%d") if hasattr(venc, "strftime") else str(venc)[:10] if venc else hoje_str
                    except Exception:
                        data_receita = hoje_str
                    descricao = f"Mensalidade {ma.get('plano_nome') or 'Plano'} - {ma.get('aluno_nome') or 'Aluno'} (Desconto integral)"
                    try:
                        cur.execute(
                            "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, criado_por) VALUES (%s, 0, %s, 'Mensalidades', %s, %s, %s)",
                            (descricao, data_receita, academia_id, ma["id"], current_user.id),
                        )
                    except Exception:
                        try:
                            cur.execute(
                                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno) VALUES (%s, 0, %s, 'Mensalidades', %s, %s)",
                                (descricao, data_receita, academia_id, ma["id"]),
                            )
                        except Exception:
                            pass
                else:
                    cur.execute(
                        """UPDATE mensalidade_aluno SET valor_original = %s, desconto_aplicado = %s, valor = %s, id_desconto = %s WHERE id = %s""",
                        (valor_orig, round(desconto_val, 2), valor_final, desconto_id, ma["id"]),
                    )
            except Exception:
                try:
                    cur.execute(
                        "UPDATE mensalidade_aluno SET valor = %s WHERE id = %s",
                        (valor_final, ma["id"]),
                    )
                except Exception:
                    pass
            aplicadas += 1

        # Rede de segurança: quita qualquer mensalidade em aberto que fique integral pelo
        # desconto vigente (cobre casos gerados fora deste laço/pacotes dinâmicos).
        try:
            _quitar_mensalidades_isentas_por_desconto(
                conn, cur, aluno_id, academia_id, criado_por=getattr(current_user, "id", None)
            )
        except Exception:
            pass

        conn.commit()
        conn.close()
        flash(f"Desconto aplicado. {aplicadas} mensalidade(s) atualizada(s)." + (" Mensalidades com 100% marcadas como pagas." if teve_100 and aplicadas else ""), "success")
        return redirect(url_for("financeiro.aplicar_desconto", academia_id=academia_id))

    vinculos = []
    try:
        cur.execute("""
            SELECT ad.id, ad.aluno_id, ad.desconto_id, ad.data_inicio, ad.data_fim, ad.ativo,
                   COALESCE(ad.aplica_todos_pacotes, 1) AS aplica_todos_pacotes,
                   ad.pacotes_mensalidade_ids,
                   a.nome as aluno_nome, d.nome as desconto_nome, d.tipo as desconto_tipo, d.valor as desconto_valor
            FROM aluno_desconto ad
            JOIN alunos a ON a.id = ad.aluno_id
            JOIN descontos d ON d.id = ad.desconto_id
            WHERE a.id_academia = %s AND ad.ativo = 1
            ORDER BY ad.data_fim DESC
        """, (academia_id,))
        vinculos = cur.fetchall()
    except Exception:
        try:
            cur.execute("""
                SELECT ad.id, ad.aluno_id, ad.desconto_id, ad.data_inicio, ad.data_fim, ad.ativo,
                       a.nome as aluno_nome, d.nome as desconto_nome, d.tipo as desconto_tipo, d.valor as desconto_valor
                FROM aluno_desconto ad
                JOIN alunos a ON a.id = ad.aluno_id
                JOIN descontos d ON d.id = ad.desconto_id
                WHERE d.id_academia = %s AND ad.ativo = 1
                ORDER BY ad.data_fim DESC
            """, (academia_id,))
            vinculos = cur.fetchall()
            for v in vinculos:
                v.setdefault("desconto_tipo", "percentual")
                v.setdefault("desconto_valor", 0)
        except Exception:
            vinculos = []
    plano_nome_por_id = {p["id"]: p["nome"] for p in pacotes_mensalidades}
    for v in vinculos:
        v.setdefault("aplica_todos_pacotes", 1)
        v.setdefault("pacotes_mensalidade_ids", None)
        try:
            v["pacotes_ids_list"] = [int(x) for x in json.loads(v.get("pacotes_mensalidade_ids") or "[]")]
        except Exception:
            v["pacotes_ids_list"] = []
        if int(v.get("aplica_todos_pacotes") or 1):
            v["pacotes_resumo"] = "Todos os pacotes"
        else:
            try:
                raw_ids = json.loads(v.get("pacotes_mensalidade_ids") or "[]")
                nomes = [plano_nome_por_id.get(int(i), f"#{i}") for i in raw_ids]
                v["pacotes_resumo"] = ", ".join(nomes) if nomes else "—"
            except Exception:
                v["pacotes_resumo"] = "—"
    conn.close()

    return render_template(
        "financeiro/mensalidades/aplicar_desconto.html",
        academias=academias,
        academia_id=academia_id,
        descontos=descontos,
        pacotes_mensalidades=pacotes_mensalidades,
        vinculos=vinculos,
    )


def _registrar_pagamento_e_receita(conn, cur, tipo, registro_id, id_academia, id_forma_pagamento=None):
    """Atualiza status para pago e cria receita. valor efetivo = valor_final (juros/desconto). id_forma_pagamento opcional."""
    hoje = date.today().strftime("%Y-%m-%d")
    if tipo == "mensalidade_aluno":
        dcur = conn.cursor(dictionary=True)
        dcur.execute(
            """
            SELECT ma.id, ma.aluno_id, ma.valor, ma.data_vencimento, ma.status, ma.status_pagamento,
                   ma.valor_original, ma.desconto_aplicado, ma.id_desconto,
                   COALESCE(ma.remover_juros, 0) AS remover_juros,
                   m.nome AS plano_nome, m.id_academia, a.id_academia AS aluno_id_academia, a.nome AS aluno_nome,
                   COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
                   COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
                   COALESCE(m.percentual_juros_dia, 0.033) AS percentual_juros_dia
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE ma.id = %s
            """,
            (registro_id,),
        )
        ma = dcur.fetchone()
        dcur.close()
        if not ma or ma.get("aluno_nome") is None:
            return False
        _ma_enriquecer_exibicao(ma, ma["aluno_id"], ma.get("id_academia") or id_academia)
        valor = float(ma.get("valor_final") or ma.get("valor") or 0)
        valor = round(valor, 2)
        descricao = f"Mensalidade {ma.get('plano_nome')} - {ma.get('aluno_nome')}"
        id_acad = ma.get("id_academia") or id_academia
        ids_fp_check = _ids_academia_mensalidade_para_formas(ma, id_academia)
        if not ids_fp_check and id_acad is not None:
            try:
                ids_fp_check = [int(id_acad)]
            except (TypeError, ValueError):
                pass
        id_fp = id_forma_pagamento
        if id_fp:
            vcur = conn.cursor(dictionary=True)
            try:
                if not _forma_pagamento_ativa_em_academias(vcur, id_fp, ids_fp_check):
                    id_fp = None
            except Exception:
                id_fp = None
            vcur.close()
        try:
            if id_fp:
                cur.execute(
                    """
                    UPDATE mensalidade_aluno
                    SET status='pago', status_pagamento='pago', data_pagamento=%s, valor_pago=%s, id_forma_pagamento=%s
                    WHERE id=%s
                    """,
                    (hoje, valor, id_fp, registro_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE mensalidade_aluno
                    SET status='pago', status_pagamento='pago', data_pagamento=%s, valor_pago=%s
                    WHERE id=%s
                    """,
                    (hoje, valor, registro_id),
                )
        except Exception:
            cur.execute(
                "UPDATE mensalidade_aluno SET status='pago', data_pagamento=%s, valor_pago=%s WHERE id=%s",
                (hoje, valor, registro_id),
            )
        try:
            if id_fp:
                cur.execute(
                    """
                    INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, id_forma_pagamento, criado_por)
                    VALUES (%s, %s, %s, 'Mensalidades', %s, %s, %s, %s)
                    """,
                    (descricao, valor, hoje, id_acad, registro_id, id_fp, current_user.id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, criado_por)
                    VALUES (%s, %s, %s, 'Mensalidades', %s, %s, %s)
                    """,
                    (descricao, valor, hoje, id_acad, registro_id, current_user.id),
                )
        except Exception:
            try:
                cur.execute(
                    "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, criado_por) VALUES (%s, %s, %s, 'Mensalidades', %s, %s, %s)",
                    (descricao, valor, hoje, id_acad, registro_id, current_user.id),
                )
            except Exception:
                cur.execute(
                    "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno) VALUES (%s, %s, %s, 'Mensalidades', %s, %s)",
                    (descricao, valor, hoje, id_acad, registro_id),
                )
    else:
        cur.execute(
            "SELECT ca.id, ca.valor, ca.descricao, a.nome, ca.id_academia FROM cobranca_avulsa ca JOIN alunos a ON a.id = ca.aluno_id WHERE ca.id = %s",
            (registro_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        valor = float(row[1])
        descricao = (row[2] or "Cobrança avulsa") + (" - %s" % row[3] if row[3] else "")
        id_acad = row[4] if len(row) > 4 and row[4] else id_academia
        cur.execute(
            "UPDATE cobranca_avulsa SET status='pago', data_pagamento=%s, valor_pago=%s WHERE id=%s",
            (hoje, valor, registro_id),
        )
        try:
            cur.execute(
                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_cobranca_avulsa, criado_por) VALUES (%s, %s, %s, 'Cobrança avulsa', %s, %s, %s)",
                (descricao, valor, hoje, id_acad, registro_id, current_user.id),
            )
        except Exception:
            cur.execute(
                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia) VALUES (%s, %s, %s, 'Cobrança avulsa', %s)",
                (descricao, valor, hoje, id_acad),
            )
    return True


def _definir_remover_juros_mensalidade_pagamento(conn, cur, registro_id):
    """Marca remover_juros=1 na cobrança (remove multa e juros no cálculo). Ignora se coluna não existir."""
    try:
        cur.execute(
            "UPDATE mensalidade_aluno SET remover_juros = 1 WHERE id = %s",
            (registro_id,),
        )
        return True
    except Exception as ex:
        if "Unknown column 'remover_juros'" in str(ex):
            return False
        raise


def _aplicar_desconto_mensalidade_no_pagamento(conn, cur, registro_id, desconto_id, academia_id):
    """
    Aplica desconto nesta mensalidade no momento do pagamento:
    1) Se existir vínculo ativo em aluno_desconto, usa vigência e restrição de pacotes;
    2) Senão, aceita qualquer desconto ativo da academia do plano (uso pontual, sem vínculo).
    Retorna (True, None) ou (False, mensagem).
    """
    dcur = conn.cursor(dictionary=True)
    try:
        dcur.execute(
            """
            SELECT ma.id, ma.aluno_id, ma.mensalidade_id, ma.valor, ma.valor_original, ma.desconto_aplicado,
                   ma.id_desconto, ma.data_vencimento, ma.status, ma.status_pagamento,
                   m.id_academia AS plano_academia
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            WHERE ma.id = %s
              AND ma.status IN ('pendente', 'atrasado', 'aguardando_confirmacao')
            """,
            (registro_id,),
        )
        ma = dcur.fetchone()
        if not ma:
            return False, "Cobrança não encontrada ou não permite aplicar desconto."
        if ma.get("id_desconto"):
            try:
                if int(ma["id_desconto"]) == int(desconto_id):
                    return True, None
            except (TypeError, ValueError):
                pass
            return False, "Esta cobrança já possui outro desconto aplicado."
        if float(ma.get("desconto_aplicado") or 0) > 0.009:
            return False, "Esta cobrança já possui desconto aplicado."

        venc = ma.get("data_vencimento")
        if isinstance(venc, datetime):
            venc = venc.date()
        elif isinstance(venc, str):
            try:
                venc = date.fromisoformat(venc[:10])
            except ValueError:
                venc = None
        if venc is None:
            venc = date.today()

        id_acad_plano = ma.get("plano_academia") or academia_id
        try:
            id_acad_plano = int(id_acad_plano) if id_acad_plano is not None else None
        except (TypeError, ValueError):
            id_acad_plano = None

        adrow = None
        try:
            dcur.execute(
                """
                SELECT COALESCE(ad.aplica_todos_pacotes, 1) AS aplica_todos_pacotes,
                       ad.pacotes_mensalidade_ids, d.tipo, d.valor
                FROM aluno_desconto ad
                JOIN descontos d ON d.id = ad.desconto_id AND d.ativo = 1
                WHERE ad.aluno_id = %s AND ad.desconto_id = %s AND ad.ativo = 1
                  AND d.id_academia = %s
                  AND (ad.data_inicio IS NULL OR ad.data_inicio <= %s)
                  AND (ad.data_fim IS NULL OR ad.data_fim >= %s)
                LIMIT 1
                """,
                (ma["aluno_id"], desconto_id, id_acad_plano, venc, venc),
            )
            adrow = dcur.fetchone()
        except Exception as ex_ad:
            _em = str(ex_ad)
            if "aplica_todos_pacotes" not in _em and "pacotes_mensalidade_ids" not in _em:
                raise
            dcur.execute(
                """
                SELECT d.tipo, d.valor
                FROM aluno_desconto ad
                JOIN descontos d ON d.id = ad.desconto_id AND d.ativo = 1
                WHERE ad.aluno_id = %s AND ad.desconto_id = %s AND ad.ativo = 1
                  AND d.id_academia = %s
                  AND (ad.data_inicio IS NULL OR ad.data_inicio <= %s)
                  AND (ad.data_fim IS NULL OR ad.data_fim >= %s)
                LIMIT 1
                """,
                (ma["aluno_id"], desconto_id, id_acad_plano, venc, venc),
            )
            _rw = dcur.fetchone()
            if _rw:
                adrow = {
                    "aplica_todos_pacotes": 1,
                    "pacotes_mensalidade_ids": None,
                    "tipo": _rw.get("tipo"),
                    "valor": _rw.get("valor"),
                }
        if not adrow:
            if id_acad_plano is None:
                return False, "Não foi possível identificar a academia do plano para aplicar o desconto."
            dcur.execute(
                """
                SELECT d.tipo, d.valor
                FROM descontos d
                WHERE d.id = %s AND d.ativo = 1 AND d.id_academia = %s
                LIMIT 1
                """,
                (desconto_id, id_acad_plano),
            )
            drow = dcur.fetchone()
            if not drow:
                return False, "Desconto inválido, inativo ou não pertence à academia do plano."
            adrow = {
                "aplica_todos_pacotes": 1,
                "pacotes_mensalidade_ids": None,
                "tipo": drow.get("tipo"),
                "valor": drow.get("valor"),
            }

        ma_mini = {"mensalidade_id": ma.get("mensalidade_id")}
        if not _desconto_aplica_ao_plano(
            ma_mini,
            adrow.get("aplica_todos_pacotes"),
            adrow.get("pacotes_mensalidade_ids"),
        ):
            return False, "Este desconto não se aplica ao plano desta cobrança."

        valor_base = float(ma.get("valor") or 0)
        valor_orig = float(ma.get("valor_original") or 0) or valor_base
        tipo = (adrow.get("tipo") or "percentual").lower()
        val_d = float(adrow.get("valor") or 0)
        if tipo == "percentual":
            desconto_val = round(valor_base * (val_d / 100.0), 2)
        else:
            desconto_val = round(min(val_d, valor_base), 2)
        desconto_val = min(round(desconto_val, 2), round(valor_base, 2))
        valor_final = round(max(0.0, valor_base - desconto_val), 2)

        cur.execute(
            """
            UPDATE mensalidade_aluno
            SET valor_original = %s, desconto_aplicado = %s, valor = %s, id_desconto = %s
            WHERE id = %s
            """,
            (valor_orig, desconto_val, valor_final, desconto_id, registro_id),
        )
        return True, None
    finally:
        dcur.close()


def _preprocessar_mensalidade_quitar_opcional(conn, cur, registro_id, partes, academia_id):
    """
    Antes de quitar: aplica desconto vinculado (opcional) e/ou remove multa+juros
    (manual ou automático quando todas as datas de pagamento são <= vencimento).
    Retorna (True, None) ou (False, mensagem).
    """
    desconto_pid = request.form.get("desconto_pagamento_id", type=int)
    if desconto_pid:
        ok_ad, msg_ad = _aplicar_desconto_mensalidade_no_pagamento(
            conn, cur, registro_id, desconto_pid, academia_id
        )
        if not ok_ad:
            return False, msg_ad

    forcar_rj = str(request.form.get("remover_juros_manual") or "").strip().lower() in (
        "1",
        "on",
        "true",
    )
    venc_dt = None
    dcv = conn.cursor(dictionary=True)
    try:
        dcv.execute(
            "SELECT data_vencimento FROM mensalidade_aluno WHERE id = %s",
            (registro_id,),
        )
        rv = dcv.fetchone()
        if rv and rv.get("data_vencimento"):
            vn = rv["data_vencimento"]
            if isinstance(vn, datetime):
                venc_dt = vn.date()
            elif isinstance(vn, date):
                venc_dt = vn
            else:
                try:
                    venc_dt = date.fromisoformat(str(vn)[:10])
                except ValueError:
                    venc_dt = None
    finally:
        dcv.close()

    auto_rj = False
    if venc_dt and partes:
        try:
            auto_rj = all(
                date.fromisoformat(str(p.get("data_pagamento") or "")[:10]) <= venc_dt
                for p in partes
            )
        except (ValueError, TypeError):
            auto_rj = False

    if forcar_rj or auto_rj:
        _definir_remover_juros_mensalidade_pagamento(conn, cur, registro_id)
    return True, None


def _registrar_pagamento_mensalidade_partes(conn, cur, registro_id, id_academia, partes):
    """
    Quita mensalidade com uma ou mais linhas (forma, valor, data cada).
    partes: list of dicts forma_pagamento_id (int), valor (float), data_pagamento (str YYYY-MM-DD).
    Retorna (True, None) ou (False, mensagem_erro).
    """
    if not partes:
        return False, "Informe ao menos uma linha de pagamento."
    dcur = conn.cursor(dictionary=True)
    dcur.execute(
        """
        SELECT ma.id, ma.aluno_id, ma.valor, ma.data_vencimento, ma.status, ma.status_pagamento,
               ma.valor_original, ma.desconto_aplicado, ma.id_desconto,
               COALESCE(ma.remover_juros, 0) AS remover_juros,
               m.nome AS plano_nome, m.id_academia, a.id_academia AS aluno_id_academia, a.nome AS aluno_nome,
               COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
               COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
               COALESCE(m.percentual_juros_dia, 0.033) AS percentual_juros_dia
        FROM mensalidade_aluno ma
        JOIN mensalidades m ON m.id = ma.mensalidade_id
        JOIN alunos a ON a.id = ma.aluno_id
        WHERE ma.id = %s
        """,
        (registro_id,),
    )
    ma = dcur.fetchone()
    dcur.close()
    if not ma or ma.get("aluno_nome") is None:
        return False, "Mensalidade não encontrada."
    _ma_enriquecer_exibicao(ma, ma["aluno_id"], ma.get("id_academia") or id_academia)
    valor_total = round(float(ma.get("valor_final") or ma.get("valor") or 0), 2)
    total_zero = valor_total <= 0.001
    descricao_base = f"Mensalidade {ma.get('plano_nome')} - {ma.get('aluno_nome')}"
    id_acad = ma.get("id_academia") or id_academia
    ids_acad_formas = _ids_academia_mensalidade_para_formas(ma, id_academia)
    if not ids_acad_formas and id_acad is not None:
        try:
            ids_acad_formas = [int(id_acad)]
        except (TypeError, ValueError):
            pass

    # Se o banco ainda não tem linhas em formas_pagamento para esta academia, criar Dinheiro/PIX/Boleto
    # antes de validar (evita "inválida ou inativa" com tabela vazia).
    _seed_ids = []
    for _x in (ids_acad_formas or []) + ([id_acad] if id_acad is not None else []):
        try:
            _xi = int(_x)
            if _xi not in _seed_ids:
                _seed_ids.append(_xi)
        except (TypeError, ValueError):
            pass
    for _aid in _seed_ids:
        try:
            _ensure_formas_padrao(cur, _aid)
        except Exception:
            pass

    linhas = []
    datas_dt = []
    soma = 0.0
    for p in partes:
        try:
            fid = int(p.get("forma_pagamento_id") or 0)
            val = round(float(p.get("valor") or 0), 2)
            dstr = (p.get("data_pagamento") or "").strip()[:10]
            dt = date.fromisoformat(dstr)
        except (ValueError, TypeError):
            return False, "Valor, forma ou data inválidos em uma das linhas."
        if val < 0 or not dstr:
            return False, "Cada linha deve ter data de pagamento e valor válido (não negativo)."
        if not total_zero and val <= 0:
            return False, "Cada linha deve ter valor maior que zero."
        if val > 0.001 and fid <= 0:
            return False, "Informe a forma de pagamento nas linhas com valor maior que zero."
        if fid > 0:
            vcur = conn.cursor(dictionary=True)
            try:
                if not _forma_pagamento_ativa_em_academias(vcur, fid, ids_acad_formas):
                    vcur.close()
                    return False, "Forma de pagamento inválida ou inativa."
            except Exception:
                vcur.close()
                return False, "Erro ao validar forma de pagamento."
            vcur.close()
        soma = round(soma + val, 2)
        datas_dt.append(dt)
        linhas.append((fid, val, dt.strftime("%Y-%m-%d"), dt))

    # UI e _ma_enriquecer podem arredondar centavos de forma ligeiramente diferente
    _tol = 0.001 if total_zero else 0.05
    if abs(soma - valor_total) > _tol:
        return False, (
            f"A soma das parcelas (R$ {soma:.2f}) deve igualar o total devido (R$ {valor_total:.2f})."
        )

    data_ma = max(datas_dt).strftime("%Y-%m-%d")
    _fp0 = linhas[0][0] if linhas else None
    try:
        _fp0_ok = _fp0 is not None and int(_fp0) > 0
    except (TypeError, ValueError):
        _fp0_ok = False
    id_fp_unico = _fp0 if len(linhas) == 1 and _fp0_ok else None

    try:
        if id_fp_unico:
            cur.execute(
                """
                UPDATE mensalidade_aluno
                SET status='pago', status_pagamento='pago', data_pagamento=%s, valor_pago=%s, id_forma_pagamento=%s
                WHERE id=%s
                """,
                (data_ma, soma, id_fp_unico, registro_id),
            )
        else:
            cur.execute(
                """
                UPDATE mensalidade_aluno
                SET status='pago', status_pagamento='pago', data_pagamento=%s, valor_pago=%s, id_forma_pagamento=NULL
                WHERE id=%s
                """,
                (data_ma, soma, registro_id),
            )
    except Exception:
        cur.execute(
            "UPDATE mensalidade_aluno SET status='pago', data_pagamento=%s, valor_pago=%s WHERE id=%s",
            (data_ma, soma, registro_id),
        )

    sufixo = 0
    for fid, val, d_sql, _dt in linhas:
        if val <= 0:
            continue
        sufixo += 1
        desc = descricao_base if len(linhas) == 1 else f"{descricao_base} (parte {sufixo})"
        try:
            cur.execute(
                """
                INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, id_forma_pagamento, criado_por)
                VALUES (%s, %s, %s, 'Mensalidades', %s, %s, %s, %s)
                """,
                (desc, val, d_sql, id_acad, registro_id, fid, current_user.id),
            )
        except Exception:
            try:
                cur.execute(
                    """
                    INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno, criado_por)
                    VALUES (%s, %s, %s, 'Mensalidades', %s, %s, %s)
                    """,
                    (desc, val, d_sql, id_acad, registro_id, current_user.id),
                )
            except Exception:
                cur.execute(
                    "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, id_mensalidade_aluno) VALUES (%s, %s, %s, 'Mensalidades', %s, %s)",
                    (desc, val, d_sql, id_acad, registro_id),
                )
    return True, None


def _parse_partes_pagamento_json(raw):
    """Interpreta JSON da lista de parcelas. Retorna (lista|None, mensagem_erro|None)."""
    if not raw or not str(raw).strip():
        return None, None
    try:
        arr = json.loads(raw)
    except json.JSONDecodeError:
        return None, "Formato de pagamentos inválido."
    if not isinstance(arr, list) or len(arr) < 1:
        return None, "Informe ao menos uma linha com data de pagamento."
    out = []
    for item in arr:
        if not isinstance(item, dict):
            return None, "Cada linha de pagamento deve ser um objeto válido."
        try:
            fid = int(item.get("forma_pagamento_id") or 0)
            val = float(item.get("valor") or 0)
            dstr = (item.get("data_pagamento") or "").strip()[:10]
            date.fromisoformat(dstr)
        except (ValueError, TypeError):
            return None, "Em cada linha informe valor e data (AAAA-MM-DD)."
        if val < 0 or not dstr:
            return None, "Cada linha precisa de valor não negativo e data de pagamento."
        if val > 0.001 and fid <= 0:
            return None, "Linhas com valor maior que zero precisam de forma de pagamento."
        out.append(
            {
                "forma_pagamento_id": fid,
                "valor": round(val, 2),
                "data_pagamento": dstr,
            }
        )
    return out, None


@bp_financeiro.route("/mensalidades/informar-pagamento", methods=["POST"])
@login_required
def informar_pagamento_mensalidade():
    """Aluno informa pagamento com comprovante e comentário. Status -> aguardando_confirmacao."""
    registro_id = request.form.get("registro_id", type=int)
    comentario = (request.form.get("comentario") or "").strip() or None
    arquivo = request.files.get("comprovante")
    if not registro_id:
        flash("Parâmetros inválidos.", "danger")
        return redirect(request.referrer or url_for("painel_aluno.minhas_mensalidades"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT ma.id, ma.aluno_id, a.usuario_id
        FROM mensalidade_aluno ma
        JOIN alunos a ON a.id = ma.aluno_id
        WHERE ma.id = %s AND ma.status IN ('pendente','atrasado')
    """, (registro_id,))
    row = cur.fetchone()
    if not row or row.get("usuario_id") != current_user.id:
        conn.close()
        flash("Mensalidade não encontrada ou não pertence a você.", "warning")
        return redirect(request.referrer or url_for("painel_aluno.minhas_mensalidades"))

    comprovante_fn = None
    if arquivo and arquivo.filename:
        try:
            ext = validar_upload(arquivo, categorias=["comprovante"])
        except UploadInvalido as e:
            flash(str(e), "danger")
            return redirect(request.referrer or url_for("painel_aluno.minhas_mensalidades"))
        fn = f"comprovantes/{nome_seguro(f'comprovante_{registro_id}', ext)}"
        folder = os.path.join(current_app.root_path, "static", "uploads", "comprovantes")
        os.makedirs(folder, exist_ok=True)
        arquivo.save(os.path.join(current_app.root_path, "static", "uploads", fn))
        comprovante_fn = fn

    try:
        if comprovante_fn:
            try:
                cur.execute(
                    "UPDATE mensalidade_aluno SET status_pagamento='pendente_aprovacao', comprovante_url=%s, observacoes=%s WHERE id=%s",
                    (comprovante_fn, comentario, registro_id),
                )
            except Exception:
                try:
                    cur.execute(
                        "UPDATE mensalidade_aluno SET status_pagamento='pendente_aprovacao', observacoes=%s WHERE id=%s",
                        (comentario, registro_id),
                    )
                except Exception:
                    cur.execute(
                        "UPDATE mensalidade_aluno SET observacoes=%s WHERE id=%s",
                        (comentario, registro_id),
                    )
        else:
            try:
                cur.execute(
                    "UPDATE mensalidade_aluno SET status_pagamento='pendente_aprovacao', observacoes=%s WHERE id=%s",
                    (comentario, registro_id),
                )
            except Exception:
                cur.execute(
                    "UPDATE mensalidade_aluno SET observacoes=%s WHERE id=%s",
                    (comentario, registro_id),
                )
        conn.commit()
        flash("Pagamento informado. Aguarde a confirmação do gestor.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao enviar: {e}", "danger")
    conn.close()
    return redirect(request.referrer or url_for("painel_aluno.minhas_mensalidades"))


@bp_financeiro.route("/mensalidades/confirmar-pagamento/<int:registro_id>", methods=["POST"])
@login_required
def confirmar_pagamento_mensalidade(registro_id):
    """Gestor confirma pagamento informado pelo aluno. Gera receita e marca como pago."""
    wants_json = _form_wants_json_response()
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Sem acesso.", "danger")
        return redirect(request.referrer or url_for("financeiro.painel_mensalidades"))
    ids = _get_academias_ids()

    def redirect_out():
        next_url = (request.form.get("next") or "").strip()
        if next_url.startswith("/") and "//" not in next_url:
            return redirect(next_url)
        return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))

    pj = (request.form.get("pagamentos_json") or "").strip()
    partes, err = _parse_partes_pagamento_json(pj if pj else None)
    if err:
        flash(err, "warning")
        return redirect_out()

    id_fp = request.form.get("forma_pagamento_id", type=int)
    if not partes:
        if not id_fp:
            flash("Selecione a forma de pagamento.", "warning")
            return redirect_out()
        conn_fp = get_db_connection()
        cur_fp = conn_fp.cursor(dictionary=True)
        try:
            cur_fp.execute(
                "SELECT id FROM formas_pagamento WHERE id = %s AND id_academia = %s AND ativo = 1",
                (id_fp, academia_id),
            )
            ok_fp = cur_fp.fetchone()
        except Exception:
            conn_fp.close()
            flash("Cadastre formas de pagamento ou execute migrations/add_formas_pagamento.sql.", "danger")
            return redirect_out()
        conn_fp.close()
        if not ok_fp:
            flash("Forma de pagamento inválida ou inativa.", "warning")
            return redirect_out()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            f"SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id WHERE ma.id = %s AND m.id_academia IN ({ph}) AND ma.status_pagamento = 'pendente_aprovacao'",
            (registro_id,) + tuple(ids),
        )
        if not cur.fetchone():
            conn.close()
            flash("Mensalidade não encontrada ou não está aguardando confirmação.", "warning")
            return redirect_out()
        if partes:
            ok_pre, msg_pre = _preprocessar_mensalidade_quitar_opcional(
                conn, cur, registro_id, partes, academia_id
            )
            if not ok_pre:
                conn.rollback()
                conn.close()
                msg_pre = msg_pre or "Não foi possível preparar o pagamento."
                flash(msg_pre, "warning")
                if wants_json:
                    return jsonify({"ok": False, "erro": msg_pre}), 400
                return redirect_out()
            ok_m, msg_m = _registrar_pagamento_mensalidade_partes(
                conn, cur, registro_id, academia_id, partes
            )
            if not ok_m:
                conn.rollback()
                conn.close()
                msg_m = msg_m or "Não foi possível confirmar."
                flash(msg_m, "warning")
                if wants_json:
                    return jsonify({"ok": False, "erro": msg_m}), 400
                return redirect_out()
        else:
            _registrar_pagamento_e_receita(
                conn, cur, "mensalidade_aluno", registro_id, academia_id, id_fp
            )
        conn.commit()
        try:
            from utils.whatsapp_lembretes import enviar_confirmacao_pagamento
            enviar_confirmacao_pagamento(registro_id)
        except Exception:
            pass
        flash("Pagamento confirmado e receita gerada.", "success")
        if wants_json:
            conn.close()
            return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        if wants_json:
            conn.close()
            return jsonify({"ok": False, "erro": str(e)}), 400
        flash("Ocorreu um erro. Tente novamente mais tarde.", "danger")
    conn.close()
    return redirect_out()


@bp_financeiro.route("/mensalidades/api-por-status")
@login_required
def api_mensalidades_por_status():
    """Retorna JSON com mensalidades filtradas por status (para modal)."""
    academia_id = request.args.get("academia_id", type=int) or _get_academia_id()
    status = request.args.get("status")
    mes = request.args.get("mes", type=int)
    ano_arg = request.args.get("ano")
    ano = int(ano_arg) if (ano_arg and str(ano_arg).isdigit() and 2000 <= int(ano_arg) <= 2100) else None
    busca = (request.args.get("busca") or "").strip()
    if not academia_id or status not in ("pago", "pendente", "atrasado", "aguardando_confirmacao"):
        return jsonify([])
    ids = _get_academias_ids()
    if academia_id not in ids:
        return jsonify([])
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    hoje = date.today()
    where_cl = ["m.id_academia = %s", "ma.status != 'cancelado'"]
    params = [academia_id]
    if mes and 1 <= mes <= 12:
        where_cl.append("MONTH(ma.data_vencimento) = %s")
        params.append(mes)
    if ano and 2000 <= ano <= 2100:
        where_cl.append("YEAR(ma.data_vencimento) = %s")
        params.append(ano)
    if busca:
        where_cl.append("a.nome LIKE %s")
        params.append(f"%{busca}%")
    try:
        cur.execute(f"""
            SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.status,
                   ma.status_pagamento, ma.comprovante_url, ma.observacoes,
                   m.nome as plano_nome, a.id as aluno_id, a.nome as aluno_nome, a.foto as aluno_foto
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE {' AND '.join(where_cl)}
            ORDER BY a.nome, ma.data_vencimento DESC
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    conn.close()
    resultado = []
    for ma in rows:
        se = _status_efetivo(ma.get("status"), ma.get("data_vencimento"), ma.get("status_pagamento"))
        if se != status:
            continue
        vi, vd, vf, desconto_nome = _valor_com_desconto(ma, ma.get("aluno_id"), academia_id, hoje)
        ma["valor_integral"] = vi
        ma["valor_desconto"] = vd
        ma["valor_final"] = vf
        ma["desconto_nome"] = desconto_nome
        ma["tem_desconto"] = vd > 0
        ma["foto_url"] = url_for("static", filename="uploads/" + ma["aluno_foto"]) if ma.get("aluno_foto") else None
        ma["comprovante_url"] = url_for("static", filename="uploads/" + ma["comprovante_url"]) if ma.get("comprovante_url") else None
        resultado.append(ma)
    return jsonify(resultado)


@bp_financeiro.route("/mensalidades/cancelar-cobranca", methods=["POST"])
@login_required
def cancelar_cobranca():
    """Cancela mensalidade ou cobrança avulsa (status pendente/atrasado)."""
    tipo = request.form.get("tipo")
    registro_id = request.form.get("registro_id", type=int)
    academia_id = _get_academia_id()
    if not registro_id or tipo not in ("mensalidade_aluno", "cobranca_avulsa"):
        flash("Parâmetros inválidos.", "danger")
        return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))

    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        ph = ",".join(["%s"] * len(ids))
        if tipo == "mensalidade_aluno":
            cur.execute(
                f"SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id WHERE ma.id = %s AND m.id_academia IN ({ph}) AND ma.status IN ('pendente','atrasado')",
                (registro_id,) + tuple(ids),
            )
        else:
            cur.execute(
                f"SELECT id FROM cobranca_avulsa WHERE id = %s AND id_academia IN ({ph}) AND status IN ('pendente','atrasado')",
                (registro_id,) + tuple(ids),
            )
        if not cur.fetchone():
            flash("Cobrança não encontrada ou não pode ser cancelada.", "warning")
            conn.close()
            return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
        if tipo == "mensalidade_aluno":
            cur.execute("UPDATE mensalidade_aluno SET status = 'cancelado' WHERE id = %s", (registro_id,))
        else:
            cur.execute("UPDATE cobranca_avulsa SET status = 'cancelado' WHERE id = %s", (registro_id,))
        conn.commit()
        flash("Cobrança cancelada.", "success")
    except Exception as e:
        conn.rollback()
        flash("Ocorreu um erro. Tente novamente mais tarde.", "danger")
    conn.close()
    return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))


@bp_financeiro.route("/mensalidades/cancelar-cobrancas-lote", methods=["POST"])
@login_required
def cancelar_cobrancas_lote():
    """Cancela múltiplas mensalidades em lote (status pendente/atrasado)."""
    registro_ids = request.form.getlist("registro_id", type=int)
    academia_id = request.form.get("academia_id", type=int) or _get_academia_id()
    if not registro_ids:
        flash("Selecione pelo menos uma mensalidade para excluir.", "warning")
        return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))

    ids = _get_academias_ids()
    ph = ",".join(["%s"] * len(ids))
    conn = get_db_connection()
    cur = conn.cursor()
    canceladas = 0
    try:
        for rid in registro_ids:
            cur.execute(
                f"SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id WHERE ma.id = %s AND m.id_academia IN ({ph}) AND ma.status IN ('pendente','atrasado')",
                (rid,) + tuple(ids),
            )
            if cur.fetchone():
                cur.execute("UPDATE mensalidade_aluno SET status = 'cancelado' WHERE id = %s", (rid,))
                canceladas += 1
        conn.commit()
        flash(f"{canceladas} mensalidade(s) excluída(s).", "success" if canceladas else "info")
    except Exception as e:
        conn.rollback()
        flash("Ocorreu um erro. Tente novamente mais tarde.", "danger")
    conn.close()
    ref = request.referrer or ""
    if "mensalidades/alunos" in ref:
        return redirect(ref)
    return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))


@bp_financeiro.route("/mensalidades/cancelar-pagamento", methods=["POST"])
@login_required
def cancelar_pagamento():
    """Cancela pagamento de mensalidade ou cobrança avulsa (reverte para pendente e cancela receita)."""
    tipo = request.form.get("tipo")
    registro_id = request.form.get("registro_id", type=int)
    academia_id = _get_academia_id()
    if not registro_id or tipo not in ("mensalidade_aluno", "cobranca_avulsa"):
        flash("Parâmetros inválidos.", "danger")
        return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))

    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ph = ",".join(["%s"] * len(ids))
        if tipo == "mensalidade_aluno":
            cur.execute(
                f"SELECT ma.id FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id WHERE ma.id = %s AND m.id_academia IN ({ph}) AND ma.status = 'pago'",
                (registro_id,) + tuple(ids),
            )
        else:
            cur.execute(
                f"SELECT id FROM cobranca_avulsa WHERE id = %s AND id_academia IN ({ph}) AND status = 'pago'",
                (registro_id,) + tuple(ids),
            )
        if not cur.fetchone():
            flash("Cobrança não encontrada ou não está paga.", "warning")
            conn.close()
            return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
        
        # Excluir receitas associadas (uma ou várias linhas em pagamento misto)
        if tipo == "mensalidade_aluno":
            try:
                cur.execute("DELETE FROM receitas WHERE id_mensalidade_aluno = %s", (registro_id,))
            except Exception:
                receita = None
                try:
                    cur.execute("SELECT id FROM receitas WHERE id_mensalidade_aluno = %s", (registro_id,))
                    receita = cur.fetchone()
                except Exception:
                    pass
                if receita:
                    cur.execute("DELETE FROM receitas WHERE id = %s", (receita["id"],))
            
            # Reverter status da mensalidade (pendente ou atrasado conforme vencimento)
            try:
                cur.execute(
                    """
                    UPDATE mensalidade_aluno SET
                      status = CASE
                        WHEN data_vencimento IS NOT NULL AND data_vencimento < CURDATE() THEN 'atrasado'
                        ELSE 'pendente'
                      END,
                      status_pagamento = NULL,
                      data_pagamento = NULL,
                      valor_pago = NULL,
                      id_forma_pagamento = NULL
                    WHERE id = %s
                    """,
                    (registro_id,),
                )
            except Exception:
                try:
                    cur.execute(
                        """
                        UPDATE mensalidade_aluno SET
                          status = CASE
                            WHEN data_vencimento IS NOT NULL AND data_vencimento < CURDATE() THEN 'atrasado'
                            ELSE 'pendente'
                          END,
                          status_pagamento = NULL,
                          data_pagamento = NULL,
                          valor_pago = NULL
                        WHERE id = %s
                        """,
                        (registro_id,),
                    )
                except Exception:
                    cur.execute(
                        "UPDATE mensalidade_aluno SET status='pendente', data_pagamento=NULL, valor_pago=NULL WHERE id=%s",
                        (registro_id,),
                    )
        else:
            # Buscar e excluir receita associada
            receita = None
            try:
                cur.execute("SELECT id FROM receitas WHERE id_cobranca_avulsa = %s", (registro_id,))
                receita = cur.fetchone()
            except Exception:
                pass
            
            if receita:
                # Sempre excluir a receita ao cancelar pagamento
                cur.execute("DELETE FROM receitas WHERE id = %s", (receita["id"],))
            
            # Reverter status da cobrança avulsa
            cur.execute("UPDATE cobranca_avulsa SET status='pendente', data_pagamento=NULL, valor_pago=NULL WHERE id=%s", (registro_id,))
        
        conn.commit()
        flash("Pagamento cancelado. Status revertido para pendente e receita excluída.", "success")
    except Exception as e:
        conn.rollback()
        flash("Ocorreu um erro. Tente novamente mais tarde.", "danger")
    conn.close()
    next_url = (request.form.get("next") or "").strip()
    if next_url.startswith("/") and "//" not in next_url:
        return redirect(next_url)
    ref = request.referrer or ""
    if "mensalidades/alunos" in ref or not ref:
        return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
    return redirect(ref)


@bp_financeiro.route("/mensalidades/remover-juros", methods=["POST"])
@login_required
def remover_juros_mensalidade():
    """Remove juros e multa de uma mensalidade (ex: pagou em dia mas informou fora do vencimento)."""
    registro_id = request.form.get("registro_id", type=int)
    academia_id = request.form.get("academia_id", type=int) or _get_academia_id()
    if not registro_id:
        flash("Parâmetros inválidos.", "danger")
        return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))

    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            f"""SELECT ma.id FROM mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                WHERE ma.id = %s AND m.id_academia IN ({ph})
                AND ma.status IN ('pendente','atrasado','aguardando_confirmacao')""",
            (registro_id,) + tuple(ids),
        )
        if not cur.fetchone():
            flash("Mensalidade não encontrada ou já paga.", "warning")
            conn.close()
            return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
        cur.execute(
            "UPDATE mensalidade_aluno SET remover_juros = 1 WHERE id = %s",
            (registro_id,),
        )
        conn.commit()
        flash("Juros e multa removidos desta mensalidade.", "success")
    except Exception as col_err:
        if "Unknown column 'remover_juros'" in str(col_err):
            flash("Recurso ainda não disponível. Execute a migration add_mensalidade_aluno_remover_juros.sql", "warning")
        else:
            conn.rollback()
            flash(f"Erro: {col_err}", "danger")
    conn.close()
    return redirect(request.referrer or url_for("financeiro.mensalidades_alunos", academia_id=academia_id))


@bp_financeiro.route("/mensalidades/registrar-pagamento", methods=["POST"])
@login_required
def registrar_pagamento():
    """Registra pagamento de mensalidade ou cobrança avulsa e gera receita."""
    wants_json = _form_wants_json_response()
    tipo = request.form.get("tipo")
    registro_id = request.form.get("registro_id", type=int)
    academia_id = _get_academia_id()
    id_fp = request.form.get("forma_pagamento_id", type=int)
    if not registro_id or tipo not in ("mensalidade_aluno", "cobranca_avulsa"):
        flash("Parâmetros inválidos.", "danger")
        if wants_json:
            return jsonify({"ok": False, "erro": "Parâmetros inválidos."}), 400
        return redirect(request.referrer or url_for("financeiro.painel_mensalidades"))

    def redirect_after():
        next_url = (request.form.get("next") or "").strip()
        if next_url.startswith("/") and "//" not in next_url:
            return redirect(next_url)
        ref = request.referrer or ""
        if "mensalidades/alunos" in ref or not ref:
            return redirect(url_for("financeiro.mensalidades_alunos", academia_id=academia_id))
        return redirect(ref)

    pj = (request.form.get("pagamentos_json") or "").strip()
    partes, err = _parse_partes_pagamento_json(pj if pj else None)
    if err:
        flash(err, "warning")
        if wants_json:
            return jsonify({"ok": False, "erro": err}), 400
        return redirect_after()

    if tipo == "mensalidade_aluno" and not partes:
        if not id_fp:
            flash("Selecione a forma de pagamento.", "warning")
            if wants_json:
                return jsonify({"ok": False, "erro": "Selecione a forma de pagamento."}), 400
            return redirect_after()
        conn_fp = get_db_connection()
        cur_fp = conn_fp.cursor(dictionary=True)
        try:
            cur_fp.execute(
                "SELECT id FROM formas_pagamento WHERE id = %s AND id_academia = %s AND ativo = 1",
                (id_fp, academia_id),
            )
            ok_fp = cur_fp.fetchone()
        except Exception:
            conn_fp.close()
            msg_fp = "Cadastre formas de pagamento ou execute migrations/add_formas_pagamento.sql."
            flash(msg_fp, "danger")
            if wants_json:
                return jsonify({"ok": False, "erro": msg_fp}), 400
            return redirect_after()
        conn_fp.close()
        if not ok_fp:
            flash("Forma de pagamento inválida ou inativa.", "warning")
            if wants_json:
                return jsonify({"ok": False, "erro": "Forma de pagamento inválida ou inativa."}), 400
            return redirect_after()

    ids = _get_academias_ids()
    if not ids:
        aid_fb = session.get("academia_gerenciamento_id") or session.get("finance_academia_id") or getattr(current_user, "id_academia", None)
        try:
            if aid_fb is not None:
                ids = [int(aid_fb)]
        except (TypeError, ValueError):
            ids = []
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        ph = ",".join(["%s"] * len(ids)) if ids else ""
        if tipo == "mensalidade_aluno":
            if not ids:
                conn.close()
                msg_nf = "Nenhuma academia no contexto do usuário. Abra o financeiro pelo painel da academia."
                flash(msg_nf, "warning")
                if wants_json:
                    return jsonify({"ok": False, "erro": msg_nf}), 400
                return redirect(request.referrer or url_for("financeiro.painel_mensalidades"))
            cur.execute(
                f"""
                SELECT ma.id FROM mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                JOIN alunos a ON a.id = ma.aluno_id
                WHERE ma.id = %s
                  AND ma.status IN ('pendente','atrasado','aguardando_confirmacao')
                  AND (m.id_academia IN ({ph}) OR a.id_academia IN ({ph}))
                """,
                (registro_id,) + tuple(ids) + tuple(ids),
            )
        else:
            if not ids:
                conn.close()
                msg_nf = "Nenhuma academia no contexto do usuário."
                flash(msg_nf, "warning")
                if wants_json:
                    return jsonify({"ok": False, "erro": msg_nf}), 400
                return redirect(request.referrer or url_for("financeiro.painel_mensalidades"))
            cur.execute(
                f"SELECT id FROM cobranca_avulsa WHERE id = %s AND id_academia IN ({ph}) AND status IN ('pendente','atrasado')",
                (registro_id,) + tuple(ids),
            )
        if not cur.fetchone():
            msg_nf = "Cobrança não encontrada ou já paga."
            flash(msg_nf, "warning")
            conn.close()
            if wants_json:
                return jsonify({"ok": False, "erro": msg_nf}), 400
            return redirect(request.referrer or url_for("financeiro.painel_mensalidades"))
        if tipo == "mensalidade_aluno" and partes:
            ok_pre, msg_pre = _preprocessar_mensalidade_quitar_opcional(
                conn, cur, registro_id, partes, academia_id
            )
            if not ok_pre:
                conn.rollback()
                msg_pre = msg_pre or "Não foi possível preparar o pagamento."
                flash(msg_pre, "warning")
                conn.close()
                if wants_json:
                    return jsonify({"ok": False, "erro": msg_pre}), 400
                return redirect_after()
            ok_m, msg_m = _registrar_pagamento_mensalidade_partes(
                conn, cur, registro_id, academia_id, partes
            )
            if not ok_m:
                conn.rollback()
                msg_m = msg_m or "Não foi possível registrar."
                flash(msg_m, "warning")
                conn.close()
                if wants_json:
                    return jsonify({"ok": False, "erro": msg_m}), 400
                return redirect_after()
        else:
            _registrar_pagamento_e_receita(
                conn,
                cur,
                tipo,
                registro_id,
                academia_id,
                id_fp if tipo == "mensalidade_aluno" else None,
            )
        conn.commit()
        if tipo in ("mensalidade_aluno", "cobranca_avulsa"):
            try:
                from utils.whatsapp_lembretes import enviar_confirmacao_pagamento
                enviar_confirmacao_pagamento(registro_id, tipo)
            except Exception:
                pass
        flash("Pagamento registrado e receita gerada.", "success")
        if wants_json:
            conn.close()
            return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        if wants_json:
            conn.close()
            return jsonify({"ok": False, "erro": str(e)}), 400
        flash("Ocorreu um erro. Tente novamente mais tarde.", "danger")
    conn.close()
    return redirect_after()


def _render_gerar_cobranca(academias, academia_id, academia_sel, turma_id=None, plano_id=None, ano_ref=None, mes_inicial=None):
    if not academia_sel and academia_id:
        academia_sel = academia_id
    if not academia_sel and academias:
        first = academias[0] if academias else None
        academia_sel = first.get("id") if first and isinstance(first, dict) else (first[0] if first else None)
    ids = _get_academias_ids()
    if academia_sel and ids and academia_sel not in ids:
        academia_sel = academia_id
    if not academia_sel:
        return render_template(
            "financeiro/mensalidades/gerar_cobranca.html",
            academias=academias or [],
            academia_id=academia_id,
            academia_sel=None,
            planos=[],
            turmas=[],
            alunos_iniciais=[],
            ano_atual=date.today().year,
            filtro_turma_id=None,
            filtro_plano_id=None,
            filtro_ano_ref=date.today().year,
            filtro_mes_inicial=date.today().month,
        )
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    planos = []
    turmas = []
    alunos_iniciais = []
    try:
        cur.execute(
            "SELECT id, nome, valor FROM mensalidades WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
            (academia_sel,),
        )
        planos = cur.fetchall()
    except Exception:
        pass
    try:
        cur.execute(
            "SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome",
            (academia_sel,),
        )
        turmas = cur.fetchall()
        turma_ids_da_academia = {t.get("TurmaID") or t.get("turmaid") for t in turmas}
        if turma_id and turma_id not in turma_ids_da_academia:
            turma_id = None
    except Exception:
        try:
            cur.execute(
                "SELECT TurmaID, nome as Nome FROM turmas WHERE id_academia = %s ORDER BY nome",
                (academia_sel,),
            )
            turmas = cur.fetchall()
            turma_ids_da_academia = {t.get("TurmaID") or t.get("turmaid") for t in turmas}
            if turma_id and turma_id not in turma_ids_da_academia:
                turma_id = None
        except Exception:
            turmas = []
            turma_id = None
    plano_ids_da_academia = {p.get("id") for p in planos}
    if plano_id and plano_ids_da_academia and plano_id not in plano_ids_da_academia:
        plano_id = None
    turma_id = turma_id or None
    plano_id = plano_id or None
    ano_ref = ano_ref or date.today().year
    mes_inicial = mes_inicial or date.today().month
    meses = list(range(mes_inicial, 13)) if (plano_id and ano_ref and 1 <= mes_inicial <= 12) else []
    # ja_possui_ids: tem pelo menos uma mensalidade no período (mes_inicial..dez)
    # exclude_ids: tem TODAS as mensalidades do período (mes_inicial..dez) -> desabilita checkbox
    ja_possui_ids = set()
    exclude_ids = set()
    if plano_id and meses:
        try:
            cur.execute(
                """SELECT DISTINCT ma.aluno_id
                   FROM mensalidade_aluno ma
                   WHERE ma.mensalidade_id = %s
                     AND YEAR(ma.data_vencimento) = %s
                     AND MONTH(ma.data_vencimento) BETWEEN %s AND 12
                     AND ma.status != 'cancelado'""",
                (plano_id, ano_ref, mes_inicial),
            )
            for r in cur.fetchall():
                if r and r.get("aluno_id") is not None:
                    ja_possui_ids.add(r.get("aluno_id"))
        except Exception:
            pass

        try:
            qtd_meses_periodo = 12 - mes_inicial + 1
            cur.execute(
                """SELECT ma.aluno_id FROM mensalidade_aluno ma
                   WHERE ma.mensalidade_id = %s AND YEAR(ma.data_vencimento) = %s
                     AND MONTH(ma.data_vencimento) BETWEEN %s AND 12 AND ma.status != 'cancelado'
                   GROUP BY ma.aluno_id
                   HAVING COUNT(DISTINCT MONTH(ma.data_vencimento)) = %s""",
                (plano_id, ano_ref, mes_inicial, qtd_meses_periodo),
            )
            for r in cur.fetchall():
                if r and r.get("aluno_id") is not None:
                    exclude_ids.add(r.get("aluno_id"))
        except Exception:
            pass
    try:
        if turma_id:
            cur.execute(
                """SELECT DISTINCT a.id, a.nome, a.foto FROM alunos a
                   LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                   WHERE a.id_academia = %s AND (at.TurmaID IS NOT NULL OR a.TurmaID = %s)
                   ORDER BY a.nome""",
                (turma_id, academia_sel, turma_id),
            )
        else:
            cur.execute(
                "SELECT id, nome, foto FROM alunos WHERE id_academia = %s ORDER BY nome",
                (academia_sel,),
            )
        for r in cur.fetchall():
            aid = int(r.get("id") or 0)
            ja_tem = aid in exclude_ids
            ja_possui = aid in ja_possui_ids
            alunos_iniciais.append({
                "id": aid,
                "nome": str(r.get("nome") or ""),
                "foto": r.get("foto"),
                "disabled": ja_tem,
                "ja_possui": ja_possui,
            })
    except Exception:
        try:
            cur.execute(
                "SELECT id, nome, foto FROM alunos WHERE id_academia = %s ORDER BY nome",
                (academia_sel,),
            )
            for r in cur.fetchall():
                aid = int(r.get("id") or 0)
                ja_tem = aid in exclude_ids
                ja_possui = aid in ja_possui_ids
                alunos_iniciais.append({
                    "id": aid,
                    "nome": str(r.get("nome") or ""),
                    "foto": r.get("foto"),
                    "disabled": ja_tem,
                    "ja_possui": ja_possui,
                })
        except Exception:
            pass
    conn.close()
    return render_template(
        "financeiro/mensalidades/gerar_cobranca.html",
        academias=academias,
        academia_id=academia_id,
        academia_sel=academia_sel,
        planos=planos,
        turmas=turmas,
        alunos_iniciais=alunos_iniciais,
        ano_atual=date.today().year,
        filtro_turma_id=turma_id,
        filtro_plano_id=plano_id,
        filtro_ano_ref=ano_ref,
        filtro_mes_inicial=mes_inicial,
    )


@bp_financeiro.route("/mensalidades/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar_mensalidade():
    """Cadastrar novo plano de mensalidade."""
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        valor_str = request.form.get("valor") or ""
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aplicar_juros = 1 if "1" in request.form.getlist("aplicar_juros_multas") else 0
        ativo = 1 if "1" in request.form.getlist("ativo") else 0

        if not nome:
            flash("Informe o nome do plano.", "danger")
            return render_template("financeiro/mensalidades/cadastrar_mensalidade.html", academias=academias, academia_id=academia_id)
        valor = _parse_valor(valor_str)
        if valor is None or valor < 0:
            flash("Informe um valor válido.", "danger")
            return render_template("financeiro/mensalidades/cadastrar_mensalidade.html", academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """INSERT INTO mensalidades (nome, descricao, valor, id_academia, ativo, aplicar_juros_multas, percentual_multa_mes, percentual_juros_dia)
                       VALUES (%s, %s, %s, %s, %s, %s, 2.00, 0.0333)""",
                    (nome, descricao, valor, id_acad, ativo, aplicar_juros),
                )
            except Exception as col_err:
                if "aplicar_juros_multas" in str(col_err) or "Unknown column" in str(col_err):
                    cur.execute(
                        "INSERT INTO mensalidades (nome, descricao, valor, id_academia, ativo) VALUES (%s, %s, %s, %s, %s)",
                        (nome, descricao, valor, id_acad, ativo),
                    )
                else:
                    raise
            conn.commit()
            conn.close()
            flash("Plano de mensalidade cadastrado com sucesso.", "success")
            return redirect(url_for("financeiro.lista_planos_mensalidades", academia_id=academia_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Erro ao salvar: {e}", "danger")
            return render_template("financeiro/mensalidades/cadastrar_mensalidade.html", academias=academias, academia_id=academia_id)

    return render_template("financeiro/mensalidades/cadastrar_mensalidade.html", academias=academias, academia_id=academia_id)


@bp_financeiro.route("/receitas")
@login_required
def lista_receitas():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    mes = request.args.get("mes", date.today().month, type=int)
    ano = request.args.get("ano", date.today().year, type=int)

    receitas = []
    total_mes = 0.0
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        # Sempre tentar buscar os campos id_mensalidade_aluno e id_cobranca_avulsa
        try:
            cur.execute(
                "SELECT id, descricao, valor, data, categoria, id_mensalidade_aluno, id_cobranca_avulsa FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
                (academia_id, mes, ano),
            )
            receitas = cur.fetchall()
        except Exception:
            # Se falhar, tentar sem esses campos e depois adicionar como None
            try:
                cur.execute(
                    "SELECT id, descricao, valor, data, categoria FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
                    (academia_id, mes, ano),
                )
                receitas = cur.fetchall()
            except Exception:
                receitas = []
        
        # Garantir que todos os registros tenham os campos id_mensalidade_aluno e id_cobranca_avulsa
        # e normalizar valores 0, None, ou string vazia para None
        for r in receitas:
            if "id_mensalidade_aluno" not in r:
                r["id_mensalidade_aluno"] = None
            else:
                # Normalizar: None, 0, '0', '' -> None
                val = r.get("id_mensalidade_aluno")
                if val is None or val == 0 or val == '0' or val == '':
                    r["id_mensalidade_aluno"] = None
                else:
                    r["id_mensalidade_aluno"] = int(val) if val else None
            
            if "id_cobranca_avulsa" not in r:
                r["id_cobranca_avulsa"] = None
            else:
                # Normalizar: None, 0, '0', '' -> None
                val = r.get("id_cobranca_avulsa")
                if val is None or val == 0 or val == '0' or val == '':
                    r["id_cobranca_avulsa"] = None
                else:
                    r["id_cobranca_avulsa"] = int(val) if val else None
        
        total_mes = sum(float(r.get("valor") or 0) for r in receitas)
        conn.close()
    except Exception:
        pass
    return render_template("financeiro/receitas/lista_receitas.html", receitas=receitas, mes=mes, ano=ano, total_mes=total_mes, ano_atual=date.today().year, academia_id=academia_id)


@bp_financeiro.route("/despesas")
@login_required
def lista_despesas():
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    mes = request.args.get("mes", date.today().month, type=int)
    ano = request.args.get("ano", date.today().year, type=int)

    despesas = []
    total_mes = 0.0
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, descricao, valor, data, categoria FROM despesas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s ORDER BY data DESC",
            (academia_id, mes, ano),
        )
        despesas = cur.fetchall()
        total_mes = sum(float(d.get("valor") or 0) for d in despesas)
        conn.close()
    except Exception:
        pass
    return render_template("financeiro/despesas/lista_despesas.html", despesas=despesas, mes=mes, ano=ano, total_mes=total_mes, ano_atual=date.today().year, academia_id=academia_id)


@bp_financeiro.route("/mensalidades/editar/<int:mensalidade_id>", methods=["GET", "POST"])
@login_required
def editar_mensalidade(mensalidade_id):
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(
            f"""SELECT id, nome, descricao, valor, id_academia, ativo,
               COALESCE(aplicar_juros_multas, 0) AS aplicar_juros_multas,
               COALESCE(percentual_multa_mes, 2) AS percentual_multa_mes,
               COALESCE(percentual_juros_dia, 0.0333) AS percentual_juros_dia
               FROM mensalidades WHERE id = %s AND id_academia IN ({ph})""",
            (mensalidade_id,) + tuple(ids),
        )
    except Exception:
        cur.execute(
            f"SELECT id, nome, descricao, valor, id_academia, ativo FROM mensalidades WHERE id = %s AND id_academia IN ({ph})",
            (mensalidade_id,) + tuple(ids),
        )
    mensalidade = cur.fetchone()
    conn.close()

    if not mensalidade:
        flash("Mensalidade não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_planos_mensalidades", academia_id=academia_id))

    if mensalidade and "aplicar_juros_multas" not in mensalidade:
        mensalidade["aplicar_juros_multas"] = 0

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        valor_str = request.form.get("valor") or ""
        id_acad = request.form.get("id_academia", type=int) or mensalidade.get("id_academia") or academia_id
        if id_acad not in ids:
            id_acad = academia_id
        aplicar_juros = 1 if "1" in request.form.getlist("aplicar_juros_multas") else 0
        ativo = 1 if "1" in request.form.getlist("ativo") else 0

        if not nome:
            flash("Informe o nome do plano.", "danger")
            mensalidade["nome"] = request.form.get("nome")
            mensalidade["descricao"] = request.form.get("descricao")
            mensalidade["valor"] = valor_str
            return render_template("financeiro/mensalidades/editar_mensalidade.html", mensalidade=mensalidade, academias=academias, academia_id=academia_id)
        valor = _parse_valor(valor_str)
        if valor is None or valor < 0:
            flash("Informe um valor válido.", "danger")
            mensalidade["nome"] = nome
            mensalidade["descricao"] = descricao
            mensalidade["valor"] = valor_str
            return render_template("financeiro/mensalidades/editar_mensalidade.html", mensalidade=mensalidade, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """UPDATE mensalidades SET nome=%s, descricao=%s, valor=%s, id_academia=%s, ativo=%s,
                       aplicar_juros_multas=%s, percentual_multa_mes=2, percentual_juros_dia=0.0333
                       WHERE id=%s""",
                    (nome, descricao, valor, id_acad, ativo, aplicar_juros, mensalidade_id),
                )
            except Exception as col_err:
                if "aplicar_juros_multas" in str(col_err) or "Unknown column" in str(col_err):
                    cur.execute(
                        "UPDATE mensalidades SET nome=%s, descricao=%s, valor=%s, id_academia=%s, ativo=%s WHERE id=%s",
                        (nome, descricao, valor, id_acad, ativo, mensalidade_id),
                    )
                else:
                    raise
            conn.commit()
            conn.close()
            flash("Mensalidade atualizada.", "success")
            return redirect(url_for("financeiro.lista_planos_mensalidades", academia_id=academia_id))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Erro ao atualizar: {e}", "danger")

    return render_template("financeiro/mensalidades/editar_mensalidade.html", mensalidade=mensalidade, academias=academias, academia_id=academia_id)


# ---------- RECEITAS: cadastrar, editar, excluir ----------
@bp_financeiro.route("/receitas/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar_receita():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in _get_academias_ids():
            id_acad = academia_id

        if not descricao:
            flash("Informe a descrição.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)
        if valor is None or valor <= 0:
            flash("Informe um valor válido.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)
        if not data_str:
            flash("Informe a data.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO receitas (descricao, valor, data, categoria, id_academia, observacoes, criado_por) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (descricao, valor, data_str, categoria, id_acad, observacoes, current_user.id),
            )
            conn.commit()
            conn.close()
            flash("Receita cadastrada com sucesso.", "success")
            return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id))
        except Exception:
            flash("Erro ao salvar receita.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)

    return render_template("financeiro/receitas/form_receita.html", receita=None, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/receitas/editar/<int:receita_id>", methods=["GET", "POST"])
@login_required
def editar_receita(receita_id):
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(ids))
    try:
        cur.execute(
            "SELECT id, descricao, valor, data, categoria, id_academia, observacoes, id_mensalidade_aluno, id_cobranca_avulsa FROM receitas WHERE id = %s AND id_academia IN (" + placeholders + ")",
            (receita_id,) + tuple(ids),
        )
    except Exception:
        cur.execute(
            "SELECT id, descricao, valor, data, categoria, id_academia, observacoes FROM receitas WHERE id = %s AND id_academia IN (" + placeholders + ")",
            (receita_id,) + tuple(ids),
        )
    receita = cur.fetchone()
    conn.close()
    if not receita:
        flash("Receita não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_receitas", academia_id=_get_academia_id()))
    receita.setdefault("id_mensalidade_aluno", None)
    receita.setdefault("id_cobranca_avulsa", None)
    if receita.get("id_mensalidade_aluno") or receita.get("id_cobranca_avulsa"):
        flash("Não é possível editar receitas geradas a partir de pagamento de mensalidade ou cobrança confirmada.", "danger")
        return redirect(url_for("financeiro.lista_receitas", academia_id=_get_academia_id()))

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or receita.get("id_academia") or academia_id
        if id_acad not in ids:
            id_acad = receita.get("id_academia") or academia_id

        if not descricao:
            flash("Informe a descrição.", "danger")
            receita["descricao"] = request.form.get("descricao")
            receita["valor"] = request.form.get("valor")
            receita["data"] = request.form.get("data")
            receita["categoria"] = request.form.get("categoria")
            receita["observacoes"] = request.form.get("observacoes")
            return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)
        if valor is None or valor <= 0:
            flash("Informe um valor válido.", "danger")
            receita["descricao"] = descricao
            receita["valor"] = request.form.get("valor")
            receita["data"] = data_str
            receita["categoria"] = categoria
            receita["observacoes"] = observacoes
            return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)
        if not data_str:
            flash("Informe a data.", "danger")
            return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE receitas SET descricao=%s, valor=%s, data=%s, categoria=%s, id_academia=%s, observacoes=%s WHERE id=%s",
                (descricao, valor, data_str, categoria, id_acad, observacoes, receita_id),
            )
            conn.commit()
            conn.close()
            flash("Receita atualizada.", "success")
            return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id))
        except Exception:
            flash("Erro ao atualizar receita.", "danger")

    return render_template("financeiro/receitas/form_receita.html", receita=receita, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/receitas/excluir/<int:receita_id>", methods=["POST"])
@login_required
def excluir_receita(receita_id):
    ids = _get_academias_ids()
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        ids = []
    if not ids:
        flash("Sem acesso a academias.", "warning")
        return redirect(url_for("painel.home"))
    academia_id = request.form.get("academia_id", type=int) or request.args.get("academia_id", type=int) or _get_academia_id()
    if academia_id not in ids:
        academia_id = ids[0]
    mes = request.form.get("mes", type=int) or request.args.get("mes", type=int) or date.today().month
    ano = request.form.get("ano", type=int) or request.args.get("ano", type=int) or date.today().year

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    rec = None
    for query, params in [
        ("SELECT id, id_mensalidade_aluno, id_cobranca_avulsa FROM receitas WHERE id = %s AND (id_academia = %s OR id_academia IS NULL)", (receita_id, academia_id)),
        ("SELECT id, id_mensalidade_aluno, id_cobranca_avulsa FROM receitas WHERE id = %s", (receita_id,)),
        ("SELECT id FROM receitas WHERE id = %s AND id_academia = %s", (receita_id, academia_id)),
    ]:
        try:
            cur.execute(query, params)
            rec = cur.fetchone()
            if rec:
                rec.setdefault("id_mensalidade_aluno", None)
                rec.setdefault("id_cobranca_avulsa", None)
                break
        except Exception:
            continue
    if not rec:
        conn.close()
        flash("Receita não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id, mes=mes, ano=ano))
    if rec.get("id_mensalidade_aluno") or rec.get("id_cobranca_avulsa"):
        conn.close()
        flash("Não é possível excluir receitas geradas a partir de pagamento de mensalidade ou cobrança confirmada.", "danger")
        return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id, mes=mes, ano=ano))
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM receitas WHERE id = %s", (receita_id,))
        conn.commit()
        flash("Receita excluída.", "success")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        flash("Erro ao excluir receita.", "danger")
    conn.close()
    return redirect(url_for("financeiro.lista_receitas", academia_id=academia_id, mes=mes, ano=ano))


# ---------- DESPESAS: cadastrar, editar, excluir ----------
@bp_financeiro.route("/despesas/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar_despesa():
    academia_id = _get_academia_id()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or academia_id
        if id_acad not in _get_academias_ids():
            id_acad = academia_id

        if not descricao:
            flash("Informe a descrição.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)
        if valor is None or valor <= 0:
            flash("Informe um valor válido.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)
        if not data_str:
            flash("Informe a data.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO despesas (descricao, valor, data, categoria, id_academia, observacoes, criado_por) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (descricao, valor, data_str, categoria, id_acad, observacoes, current_user.id),
            )
            conn.commit()
            conn.close()
            flash("Despesa cadastrada com sucesso.", "success")
            return redirect(url_for("financeiro.lista_despesas", academia_id=academia_id))
        except Exception:
            flash("Erro ao salvar despesa.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)

    return render_template("financeiro/despesas/form_despesa.html", despesa=None, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/despesas/editar/<int:despesa_id>", methods=["GET", "POST"])
@login_required
def editar_despesa(despesa_id):
    academia_id = _get_academia_id()
    if not academia_id:
        return redirect(url_for("painel.home"))

    academias = _get_academias_for_select()
    ids = _get_academias_ids()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(
        "SELECT id, descricao, valor, data, categoria, id_academia, observacoes FROM despesas WHERE id = %s AND id_academia IN (" + placeholders + ")",
        (despesa_id,) + tuple(ids),
    )
    despesa = cur.fetchone()
    conn.close()

    if not despesa:
        flash("Despesa não encontrada.", "warning")
        return redirect(url_for("financeiro.lista_despesas", academia_id=_get_academia_id()))

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        valor = _parse_valor(request.form.get("valor"))
        data_str = request.form.get("data", "").strip()
        categoria = (request.form.get("categoria") or "").strip() or None
        observacoes = (request.form.get("observacoes") or "").strip() or None
        id_acad = request.form.get("id_academia", type=int) or despesa.get("id_academia") or academia_id
        if id_acad not in ids:
            id_acad = despesa.get("id_academia") or academia_id

        if not descricao:
            flash("Informe a descrição.", "danger")
            despesa["descricao"] = request.form.get("descricao")
            despesa["valor"] = request.form.get("valor")
            despesa["data"] = request.form.get("data")
            despesa["categoria"] = request.form.get("categoria")
            despesa["observacoes"] = request.form.get("observacoes")
            return render_template("financeiro/despesas/form_despesa.html", despesa=despesa, academias=academias, academia_id=academia_id)
        if valor is None or valor <= 0:
            flash("Informe um valor válido.", "danger")
            despesa["descricao"] = descricao
            despesa["valor"] = request.form.get("valor")
            despesa["data"] = data_str
            despesa["categoria"] = categoria
            despesa["observacoes"] = observacoes
            return render_template("financeiro/despesas/form_despesa.html", despesa=despesa, academias=academias, academia_id=academia_id)
        if not data_str:
            flash("Informe a data.", "danger")
            return render_template("financeiro/despesas/form_despesa.html", despesa=despesa, academias=academias, academia_id=academia_id)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE despesas SET descricao=%s, valor=%s, data=%s, categoria=%s, id_academia=%s, observacoes=%s WHERE id=%s",
                (descricao, valor, data_str, categoria, id_acad, observacoes, despesa_id),
            )
            conn.commit()
            conn.close()
            flash("Despesa atualizada.", "success")
            return redirect(url_for("financeiro.lista_despesas", academia_id=academia_id))
        except Exception:
            flash("Erro ao atualizar despesa.", "danger")

    return render_template("financeiro/despesas/form_despesa.html", despesa=despesa, academias=academias, academia_id=academia_id)


@bp_financeiro.route("/despesas/excluir/<int:despesa_id>", methods=["POST"])
@login_required
def excluir_despesa(despesa_id):
    ids = _get_academias_ids()
    if not ids:
        return redirect(url_for("painel.home"))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ph = ",".join(["%s"] * len(ids))
        cur.execute("DELETE FROM despesas WHERE id = %s AND id_academia IN (" + ph + ")", (despesa_id,) + tuple(ids))
        conn.commit()
        conn.close()
        flash("Despesa excluída.", "success")
    except Exception:
        flash("Erro ao excluir despesa.", "danger")
    return redirect(url_for("financeiro.lista_despesas", academia_id=_get_academia_id()))
