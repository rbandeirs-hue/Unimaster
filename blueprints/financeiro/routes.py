# ======================================================
# Blueprint: Financeiro (mensalidades, receitas, despesas, descontos)
# ======================================================
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from utils.upload_seguro import validar_upload, nome_seguro, UploadInvalido
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from config import get_db_connection
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
        cur.execute(
            """
            SELECT ma.aluno_id, ma.mensalidade_id, ma.turma_id, ma.valor, DAY(ma.data_vencimento) AS dia
            FROM mensalidade_aluno ma
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE a.id_academia = %s AND a.status = 'ativo'
              AND ma.status <> 'cancelado' AND ma.mensalidade_id IS NOT NULL
              AND ma.id = (SELECT ma2.id FROM mensalidade_aluno ma2
                           WHERE ma2.aluno_id = ma.aluno_id AND ma2.status <> 'cancelado'
                                 AND ma2.mensalidade_id IS NOT NULL
                           ORDER BY ma2.data_vencimento DESC, ma2.id DESC LIMIT 1)
            """,
            (academia_id,),
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
            if t.get("turma_id"):
                cur.execute(
                    "INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, turma_id, data_vencimento, valor, status) VALUES (%s,%s,%s,%s,%s,'pendente')",
                    (t["mensalidade_id"], t["aluno_id"], t["turma_id"], venc, t["valor"]),
                )
            else:
                cur.execute(
                    "INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, data_vencimento, valor, status) VALUES (%s,%s,%s,%s,'pendente')",
                    (t["mensalidade_id"], t["aluno_id"], venc, t["valor"]),
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
    return jsonify({
        "ok": True,
        "atrasadas_marcadas": atrasadas,
        "mensalidades_geradas": geradas,
        "academias_processadas": academias_processadas,
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


def _asaas_habilitado_academia(academia_id):
    """True se a cobrança digital (Asaas) está disponível para a academia.

    Exige o flag asaas_habilitado ligado E a chave de API da própria academia.
    """
    cfg = _asaas_config_academia(academia_id)
    return bool(cfg and cfg.get("asaas_habilitado") and (cfg.get("asaas_api_key") or "").strip())


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
            """SELECT ma.id, ma.valor, ma.data_vencimento,
                      a.nome, a.cpf, a.email, a.telefone, a.id_academia,
                      ac.asaas_habilitado, ac.asaas_api_key, ac.asaas_ambiente
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               JOIN academias ac ON ac.id = a.id_academia
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
        if not ma.get("asaas_habilitado"):
            flash("Cobrança digital (Asaas) não está habilitada para esta academia. "
                  "Ative em Configurações da academia → Financeiro.", "warning")
            return redirect(destino)

        r = _emitir_cobranca_asaas(ma, tipo, descricao=f"Mensalidade - {ma['nome']}")
        cur.execute(
            """UPDATE mensalidade_aluno
               SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                   asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s
               WHERE id=%s""",
            (r["payment_id"], r["tipo"], r["boleto_url"], r["pix_qrcode"], r["pix_copia_cola"], ma_id),
        )
        conn.commit()
        flash(f"Cobrança {tipo} gerada no Asaas com sucesso.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao gerar cobrança Asaas (ma {ma_id}): {e}", exc_info=True)
        flash(f"Erro ao gerar cobrança no Asaas: {e}", "danger")
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
            """SELECT ca.id, ca.valor, ca.data_vencimento, ca.descricao,
                      a.nome, a.cpf, a.email, a.telefone, ca.id_academia,
                      ac.asaas_habilitado, ac.asaas_api_key, ac.asaas_ambiente
               FROM cobranca_avulsa ca
               JOIN alunos a ON a.id = ca.aluno_id
               JOIN academias ac ON ac.id = ca.id_academia
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
        if not ca.get("asaas_habilitado"):
            flash("Cobrança digital (Asaas) não está habilitada para esta academia. "
                  "Ative em Configurações da academia → Financeiro.", "warning")
            return redirect(destino)

        descricao = (ca.get("descricao") or "Cobrança avulsa") + f" - {ca['nome']}"
        r = _emitir_cobranca_asaas(ca, tipo, descricao=descricao)
        cur.execute(
            """UPDATE cobranca_avulsa
               SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                   asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s
               WHERE id=%s""",
            (r["payment_id"], r["tipo"], r["boleto_url"], r["pix_qrcode"], r["pix_copia_cola"], av_id),
        )
        conn.commit()
        flash(f"Cobrança {tipo} gerada no Asaas com sucesso.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao gerar cobrança Asaas (avulsa {av_id}): {e}", exc_info=True)
        flash(f"Erro ao gerar cobrança no Asaas: {e}", "danger")
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
                   ma.asaas_boleto_url, ma.asaas_pix_copia_cola, ma.asaas_tipo,
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
                   asaas_payment_id, asaas_tipo, asaas_boleto_url, asaas_pix_copia_cola
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

    conn.close()

    return render_template(
        "financeiro/mensalidades/mensalidades_alunos.html",
        academia_id=academia_id,
        academias=academias,
        mensalidades=mensalidades,
        avulsas=avulsas,
        contagens=contagens,
        mes=mes,
        ano=ano,
        busca=busca,
        filtro_status=filtro_status,
        ano_atual=date.today().year,
        formas_lista=formas_lista,
        asaas_on=_asaas_habilitado_academia(academia_id),
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
        cur.execute(
            "SELECT id, nome FROM alunos WHERE id = %s AND id_academia = %s",
            (aluno_id, academia_id),
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
        if busca:
            cur.execute(
                "SELECT id, nome, foto FROM alunos WHERE id_academia = %s AND ativo = 1 AND nome LIKE %s ORDER BY nome LIMIT 50",
                (acad_id, f"%{busca}%"),
            )
        else:
            cur.execute(
                "SELECT id, nome, foto FROM alunos WHERE id_academia = %s AND ativo = 1 ORDER BY nome LIMIT 30",
                (acad_id,),
            )
        rows = cur.fetchall()
        for r in rows:
            r["foto_url"] = url_for("static", filename="uploads/" + r["foto"]) if r.get("foto") else None
    except Exception:
        try:
            cur.execute(
                "SELECT a.id, a.nome, a.foto FROM alunos a WHERE a.id_academia = %s AND a.ativo = 1 ORDER BY a.nome LIMIT 30",
                (acad_id,),
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
                       WHERE a.id_academia = %s AND (at.TurmaID IS NOT NULL OR a.TurmaID = %s)
                       ORDER BY a.nome""",
                    (turma_id, acad_id, turma_id),
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
    if metodo not in ("PIX", "BOLETO") or not registros:
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
                cur.execute(
                    "SELECT asaas_habilitado, asaas_api_key, asaas_ambiente FROM academias WHERE id=%s",
                    (acad,),
                )
                cred_cache[acad] = cur.fetchone() or {}
            cred = cred_cache[acad]
            if not (cred.get("asaas_habilitado") and (cred.get("asaas_api_key") or "").strip()):
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
                cur.execute("SELECT nome, cpf, email, telefone FROM alunos WHERE id=%s", (aid,))
                aluno_cache[aid] = cur.fetchone() or {}
            al = aluno_cache[aid]
            row = {
                "id": reg["id"], "nome": al.get("nome"), "cpf": al.get("cpf"),
                "email": al.get("email"), "telefone": al.get("telefone"),
                "valor": valor, "data_vencimento": reg.get("data_vencimento"),
                "asaas_api_key": cred.get("asaas_api_key"), "asaas_ambiente": cred.get("asaas_ambiente"),
            }
            try:
                r = _emitir_cobranca_asaas(row, metodo, descricao=reg.get("descricao") or "Cobrança")
                tabela = "mensalidade_aluno" if reg.get("origem") == "mensalidade" else "cobranca_avulsa"
                cur.execute(
                    f"""UPDATE {tabela}
                        SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                            asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s
                        WHERE id=%s""",
                    (r["payment_id"], r["tipo"], r["boleto_url"], r["pix_qrcode"], r["pix_copia_cola"], reg["id"]),
                )
                conn.commit()
                geradas += 1
            except Exception as e:
                conn.rollback()
                current_app.logger.error(f"Auto Asaas falhou ({reg.get('origem')} {reg.get('id')}): {e}")
                falhas += 1
    finally:
        conn.close()
    return (geradas, ignoradas, falhas)


def _flash_resumo_asaas(geradas, ignoradas, falhas, metodo):
    if geradas:
        flash(f"Cobrança online ({metodo}) gerada para {geradas} cobrança(s). O aluno já pode pagar.", "success")
    if ignoradas:
        flash(f"{ignoradas} cobrança(s) sem cobrança online (valor abaixo de R$ 5,00 ou Asaas indisponível).", "warning")
    if falhas:
        flash(f"{falhas} cobrança(s) não puderam gerar a cobrança online no Asaas (verifique CPF/dados do aluno).", "warning")


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
                try:
                    cur.execute(
                        """INSERT INTO cobranca_avulsa (aluno_id, id_academia, descricao, valor, data_vencimento, status, criado_por)
                           VALUES (%s, %s, %s, %s, %s, 'pendente', %s)""",
                        (aluno_ids[0], id_acad, descricao, valor, data_venc, current_user.id),
                    )
                except Exception:
                    cur.execute(
                        "INSERT INTO cobranca_avulsa (aluno_id, id_academia, descricao, valor, data_vencimento, status) VALUES (%s, %s, %s, %s, %s, 'pendente')",
                        (aluno_ids[0], id_acad, descricao, valor, data_venc),
                    )
                av_id = cur.lastrowid
                conn.commit()
                conn.close()
                flash("Cobrança avulsa gerada.", "success")
                metodo = (request.form.get("asaas_metodo") or "").upper()
                if metodo in ("PIX", "BOLETO") and av_id:
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
                            if tid:
                                cur.execute(
                                    """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, turma_id, data_vencimento, valor, status)
                                       VALUES (%s, %s, %s, %s, %s, 'pendente')""",
                                    (plano_id, aid, tid, data_venc, valor_plano),
                                )
                            else:
                                cur.execute(
                                    """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, data_vencimento, valor, status)
                                       VALUES (%s, %s, %s, %s, 'pendente')""",
                                    (plano_id, aid, data_venc, valor_plano),
                                )
                            criadas_mens.append({
                                "origem": "mensalidade", "id": cur.lastrowid, "aluno_id": aid,
                                "id_academia": id_acad, "valor": valor_plano, "data_vencimento": data_venc,
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
                if metodo in ("PIX", "BOLETO") and criadas_mens:
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
                        """UPDATE mensalidade_aluno SET valor_original = %s, desconto_aplicado = %s, valor = 0, id_desconto = %s, status = 'pago', data_pagamento = %s WHERE id = %s""",
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
