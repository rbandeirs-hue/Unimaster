# ======================================================
# 🧩 Blueprint: Presenças
# ======================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_required, current_user
from config import get_db_connection
from utils.ranking_frequencia import SQL_MATRICULADO_NA_TURMA_DA_PRESENCA
from utils.alunos_academias import filtro_alunos_da_academia
from datetime import date, datetime, timedelta
from werkzeug.utils import secure_filename
import os
import uuid
import re # Necessário para o histórico/ajax se mantiver a lógica original

# ⚠️ O nome 'presencas' será usado para referenciar as rotas: url_for('presencas.registro_presenca')
bp_presencas = Blueprint("presencas", __name__)
ALLOWED_PLANO_AULA_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "jpg", "jpeg", "png", "gif", "txt", "zip", "rar"
}
ALLOWED_FOTO_PRESENCA_AVULSA = {"jpg", "jpeg", "png", "gif", "webp"}


def _normalizar_horario_aula(valor):
    """Normaliza horário para HH:MM:SS (uso em banco/consultas)."""
    v = (valor or "").strip()
    if re.match(r"^\d{2}:\d{2}:\d{2}$", v):
        return v
    if re.match(r"^\d{2}:\d{2}$", v):
        return f"{v}:00"
    return "00:00:00"


def _session_key_registro_chamada_extras(turma_id, data_aula, horario_aula):
    ha = horario_aula or "00:00:00"
    if isinstance(ha, str) and len(ha) == 5 and ha[2] == ":":
        ha = f"{ha}:00"
    return f"rpc_extras_v1_{turma_id}_{data_aula}_{ha}"


def _extras_chamada_ids_get(turma_id, data_aula, horario_aula):
    key = _session_key_registro_chamada_extras(turma_id, data_aula, horario_aula)
    raw = session.get(key)
    if not raw:
        return set()
    try:
        return {int(x) for x in raw}
    except (TypeError, ValueError):
        return set()


def _extras_chamada_ids_set(turma_id, data_aula, horario_aula, id_set):
    key = _session_key_registro_chamada_extras(turma_id, data_aula, horario_aula)
    if id_set:
        session[key] = sorted(id_set)
    else:
        session.pop(key, None)
    session.modified = True


def _extras_chamada_add_id(turma_id, data_aula, horario_aula, aluno_id):
    s = _extras_chamada_ids_get(turma_id, data_aula, horario_aula)
    s.add(int(aluno_id))
    _extras_chamada_ids_set(turma_id, data_aula, horario_aula, s)


def _extras_chamada_remove_id(turma_id, data_aula, horario_aula, aluno_id):
    s = _extras_chamada_ids_get(turma_id, data_aula, horario_aula)
    s.discard(int(aluno_id))
    _extras_chamada_ids_set(turma_id, data_aula, horario_aula, s)


def _extras_chamada_clear(turma_id, data_aula, horario_aula):
    key = _session_key_registro_chamada_extras(turma_id, data_aula, horario_aula)
    session.pop(key, None)
    session.modified = True


def _horario_padrao_turma(cursor, turma_id):
    """Horário da turma para presenças (TIME → HH:MM:SS)."""
    if not turma_id:
        return "00:00:00"
    try:
        cursor.execute(
            "SELECT hora_inicio FROM turmas WHERE TurmaID = %s LIMIT 1",
            (turma_id,),
        )
        row = cursor.fetchone()
        hi = row.get("hora_inicio") if row else None
        if hi is None:
            return "00:00:00"
        if hasattr(hi, "total_seconds"):
            total_sec = int(hi.total_seconds())
            return f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}:00"
        s = str(hi)
        if len(s) >= 5 and s[2] == ":":
            return _normalizar_horario_aula(s[:5])
        return "00:00:00"
    except Exception:
        return "00:00:00"


def _resolver_turma_origem_aluno_na_academia(cursor, aluno_id, academia_origem_id):
    """Turma principal do aluno na academia de origem (TurmaID ou aluno_turmas)."""
    if not aluno_id or not academia_origem_id:
        return None
    try:
        cursor.execute(
            """
            SELECT a.TurmaID FROM alunos a
            INNER JOIN turmas t ON t.TurmaID = a.TurmaID AND t.id_academia = %s
            WHERE a.id = %s
            LIMIT 1
            """,
            (academia_origem_id, aluno_id),
        )
        row = cursor.fetchone()
        if row and row.get("TurmaID"):
            return row["TurmaID"]
        cursor.execute(
            """
            SELECT at.TurmaID FROM aluno_turmas at
            INNER JOIN turmas t ON t.TurmaID = at.TurmaID AND t.id_academia = %s
            WHERE at.aluno_id = %s
            ORDER BY at.TurmaID
            LIMIT 1
            """,
            (academia_origem_id, aluno_id),
        )
        row2 = cursor.fetchone()
        return row2["TurmaID"] if row2 and row2.get("TurmaID") else None
    except Exception:
        return None


def _espelhar_presenca_visita_na_academia_origem(
    cursor,
    aluno_id,
    turma_destino_id,
    data_presenca,
    academia_destino_id,
    responsavel_id,
    responsavel_nome,
):
    """
    Aluno com visita aprovada: ao registrar presença na turma da academia destino,
    grava presença na turma de origem (academia do aluno) no mesmo dia — evita falta injusta na chamada local.
    """
    if not aluno_id or not turma_destino_id or not data_presenca or not academia_destino_id:
        return
    try:
        cursor.execute(
            """
            SELECT id, academia_origem_id
            FROM solicitacoes_aprovacao
            WHERE aluno_id = %s
              AND data_visita = %s
              AND turma_id = %s
              AND academia_destino_id = %s
              AND status = 'aprovado_destino'
              AND tipo = 'visita'
            LIMIT 1
            """,
            (aluno_id, data_presenca, turma_destino_id, academia_destino_id),
        )
        sol = cursor.fetchone()
        if not sol:
            return
        origem_aid = sol.get("academia_origem_id")
        turma_origem = _resolver_turma_origem_aluno_na_academia(cursor, aluno_id, origem_aid)
        if not turma_origem or turma_origem == turma_destino_id:
            return
        horario_origem = _horario_padrao_turma(cursor, turma_origem)
        nome_resp = ((responsavel_nome or "") + " · presença na visita")[:255]
        cursor.execute(
            """
            INSERT INTO presencas (aluno_id, turma_id, data_presenca, horario_aula, responsavel_id, responsavel_nome, presente)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                presente = 1,
                responsavel_id = VALUES(responsavel_id),
                responsavel_nome = VALUES(responsavel_nome),
                registrado_em = CURRENT_TIMESTAMP
            """,
            (
                aluno_id,
                turma_origem,
                data_presenca,
                horario_origem,
                responsavel_id,
                nome_resp,
            ),
        )
    except Exception:
        pass


def _merge_extras_sessao_registro_chamada(
    cursor,
    turma_selecionada,
    data_presenca,
    horario_aula,
    academia_id,
    excluir_aluno_tela_ids,
    alunos,
    ids_alunos_tela,
):
    """Reinclui na grade alunos adicionados por buscas anteriores (sessão), sem depender do termo atual."""
    extras = _extras_chamada_ids_get(turma_selecionada, data_presenca, horario_aula)
    kept = set()
    for aid in sorted(extras):
        if aid in excluir_aluno_tela_ids:
            continue
        if aid in ids_alunos_tela:
            continue
        params = [aid, turma_selecionada, turma_selecionada]
        q = """
            SELECT a.id, a.nome, a.foto, t_origem.Nome AS turma_origem_nome
            FROM alunos a
            LEFT JOIN turmas t_origem ON t_origem.TurmaID = a.TurmaID
            WHERE a.id = %s
              AND (a.ativo IS NULL OR a.ativo = 1)
              AND NOT (
                  EXISTS (
                      SELECT 1 FROM aluno_turmas at
                      WHERE at.aluno_id = a.id AND at.TurmaID = %s
                  )
                  OR a.TurmaID = %s
              )
        """
        if academia_id:
            # Inclui quem tem a academia como principal e quem está vinculado a ela.
            _t, _p = filtro_alunos_da_academia(academia_id)
            q += f" AND {_t}"
            params.extend(_p)
        q += " LIMIT 1"
        try:
            cursor.execute(q, tuple(params))
            row = cursor.fetchone()
            if not row:
                continue
            row["aluno_outra_turma"] = True
            alunos.append(row)
            ids_alunos_tela.add(aid)
            kept.add(aid)
        except Exception:
            continue
    _extras_chamada_ids_set(turma_selecionada, data_presenca, horario_aula, kept)


def _arquivo_plano_aula_permitido(filename):
    return "." in (filename or "") and filename.rsplit(".", 1)[1].lower() in ALLOWED_PLANO_AULA_EXTENSIONS


def _salvar_arquivo_plano_aula(file_storage, turma_id, data_presenca, horario_aula):
    if not file_storage or not file_storage.filename:
        return (None, None, None)

    if not _arquivo_plano_aula_permitido(file_storage.filename):
        return (
            None,
            None,
            "Formato de arquivo não permitido para plano de aula. Use: pdf, doc, docx, xls, xlsx, ppt, pptx, jpg, jpeg, png, gif, txt, zip ou rar.",
        )

    nome_original = secure_filename(file_storage.filename)
    ext = os.path.splitext(nome_original)[1].lower()
    horario_token = (horario_aula or "00:00:00").replace(":", "")
    nome_arquivo = f"plano_aula_t{turma_id}_{data_presenca}_{horario_token}_{uuid.uuid4().hex[:10]}{ext}"

    pasta = os.path.join(current_app.root_path, "static", "uploads", "planos_aula")
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, nome_arquivo)

    try:
        file_storage.save(caminho)
        return (nome_arquivo, nome_original, None)
    except Exception:
        return (None, None, "Não foi possível salvar o arquivo do plano de aula.")


def _garantir_tabela_presencas_avulsas(cursor):
    """Presenças avulsas: nome + foto opcional por aula (turma/data/horário), sem cadastro de aluno/visitante."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS presencas_avulsas (
            id INT(11) NOT NULL AUTO_INCREMENT,
            turma_id INT(11) NOT NULL,
            data_aula DATE NOT NULL,
            horario_aula TIME NOT NULL DEFAULT '00:00:00',
            academia_id INT(11) NULL DEFAULT NULL,
            nome VARCHAR(200) NOT NULL,
            foto VARCHAR(255) NULL DEFAULT NULL,
            presente TINYINT(1) NOT NULL DEFAULT 1,
            responsavel_id INT(11) NULL DEFAULT NULL,
            responsavel_nome VARCHAR(255) NULL DEFAULT NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_pa_turma_data_hora (turma_id, data_aula, horario_aula),
            KEY idx_pa_academia (academia_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
        """
    )


def _salvar_foto_presenca_avulsa(file_storage):
    """Salva imagem em static/uploads. Retorna (nome_arquivo, mensagem_erro)."""
    if not file_storage or not file_storage.filename:
        return (None, None)
    nome_original = secure_filename(file_storage.filename)
    if "." not in nome_original:
        return (None, "Envie uma imagem com extensão (jpg, png, etc.).")
    ext = nome_original.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_FOTO_PRESENCA_AVULSA:
        return (None, "Foto: use jpg, jpeg, png, gif ou webp.")
    nome_arquivo = f"pres_avulsa_{uuid.uuid4().hex[:12]}.{ext}"
    pasta = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, nome_arquivo)
    try:
        file_storage.save(caminho)
        return (nome_arquivo, None)
    except Exception:
        return (None, "Não foi possível salvar a foto.")


def _garantir_tabela_registros_aula_presenca(cursor):
    """Garante existência da tabela de observações/plano por aula."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS registros_aula_presenca (
            id INT(11) NOT NULL AUTO_INCREMENT,
            turma_id INT(11) NOT NULL,
            academia_id INT(11) NULL DEFAULT NULL,
            data_aula DATE NOT NULL,
            horario_aula TIME NOT NULL DEFAULT '00:00:00',
            observacao TEXT NULL DEFAULT NULL,
            plano_aula_texto LONGTEXT NULL DEFAULT NULL,
            plano_aula_arquivo VARCHAR(255) NULL DEFAULT NULL,
            plano_aula_arquivo_original VARCHAR(255) NULL DEFAULT NULL,
            responsavel_id INT(11) NULL DEFAULT NULL,
            responsavel_nome VARCHAR(255) NULL DEFAULT NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_registro_aula_turma_data_hora (turma_id, data_aula, horario_aula),
            KEY idx_registro_aula_data (data_aula),
            KEY idx_registro_aula_turma (turma_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
        """
    )


def _garantir_tabela_presencas_observacao_aluno(cursor):
    """Observação por aluno e por aula — visível apenas para o próprio aluno no painel."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS presencas_observacao_aluno (
            id INT(11) NOT NULL AUTO_INCREMENT,
            aluno_id INT(11) NOT NULL,
            turma_id INT(11) NOT NULL,
            data_aula DATE NOT NULL,
            horario_aula TIME NOT NULL DEFAULT '00:00:00',
            observacao TEXT NULL,
            responsavel_id INT(11) NULL DEFAULT NULL,
            responsavel_nome VARCHAR(255) NULL DEFAULT NULL,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_obs_aluno_aula (aluno_id, turma_id, data_aula, horario_aula),
            KEY idx_obs_turma_data (turma_id, data_aula),
            KEY idx_obs_aluno (aluno_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci
        """
    )


def _get_professor_id():
    """Retorna (primeiro professor_id, primeiro id_academia) do current_user."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, id_academia FROM professores WHERE usuario_id = %s AND ativo = 1 LIMIT 1",
            (current_user.id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return (row["id"], row.get("id_academia")) if row else (None, None)
    except Exception:
        return (None, None)


def _get_todos_professor_ids():
    """Retorna lista de professor_id do current_user (pode ter mais de um por academia)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id FROM professores WHERE usuario_id = %s AND ativo = 1 ORDER BY id",
            (current_user.id,),
        )
        ids = [r["id"] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return ids
    except Exception:
        return []


def _get_ids_turmas_professor(professor_id_or_ids):
    """Retorna set de TurmaID vinculadas ao(s) professor(es). Aceita int ou lista."""
    ids = [professor_id_or_ids] if isinstance(professor_id_or_ids, int) else (professor_id_or_ids or [])
    if not ids:
        return set()
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        ph = ",".join(["%s"] * len(ids))
        cur.execute("SELECT TurmaID FROM turma_professor WHERE professor_id IN (%s)" % ph, tuple(ids))
        result = {r["TurmaID"] for r in cur.fetchall()}
        cur.close()
        conn.close()
        return result
    except Exception:
        return set()


def _get_academias_presenca():
    """Retorna (academia_id, academias) para o painel de presenças."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        ids = []
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas:
            cur.close()
            conn.close()
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(vinculadas)), tuple(vinculadas))
            academias = cur.fetchall()
            cur.close()
            conn.close()
            if len(vinculadas) == 1:
                return vinculadas[0], academias
            aid = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
            if aid and aid in vinculadas:
                session["academia_gerenciamento_id"] = aid
                session["finance_academia_id"] = aid
            else:
                aid = vinculadas[0]
                session["academia_gerenciamento_id"] = aid
                session["finance_academia_id"] = aid
            return aid, academias
        if session.get("modo_painel") == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
            cur.close()
            conn.close()
            return None, []
        if current_user.has_role("admin"):
            cur.execute("SELECT id FROM academias ORDER BY nome")
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT ac.id FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s ORDER BY ac.nome",
                (getattr(current_user, "id_federacao", None),),
            )
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome", (getattr(current_user, "id_associacao", None),))
            ids = [r["id"] for r in cur.fetchall()]
        else:
            # Professor responsável ou auxiliar (em turma_professor)
            cur.execute("SELECT id_academia FROM professores WHERE usuario_id = %s AND ativo = 1 AND id_academia IS NOT NULL LIMIT 1", (current_user.id,))
            row = cur.fetchone()
            if row and row.get("id_academia"):
                ids = [row["id_academia"]]
        cur.close()
        conn.close()
        if not ids:
            return None, []
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids)), tuple(ids))
        academias = cur.fetchall()
        cur.close()
        conn.close()
        if len(ids) == 1:
            return ids[0], academias
        aid = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
        if aid and aid in ids:
            session["academia_gerenciamento_id"] = aid
            session["finance_academia_id"] = aid
        else:
            aid = ids[0]
            session["academia_gerenciamento_id"] = aid
            session["finance_academia_id"] = aid
        return aid, academias
    except Exception:
        return None, []


# ======================================================
# 🔹 Painel Presença (Módulo com 3 opções)
# ======================================================
@bp_presencas.route("/presencas", methods=["GET"])
@login_required
def painel_presenca():
    """Hub do módulo Presença: Registrar, Relatório, Histórico."""
    academia_id, academias = _get_academias_presenca()
    academias = academias or []
    modo = session.get("modo_painel")
    if modo == "professor":
        back_url = url_for("professor.painel_professor")
    elif modo == "academia":
        back_url = url_for("academia.painel_academia", academia_id=academia_id) if academia_id else url_for("academia.painel_academia")
    else:
        back_url = url_for("painel.home")
    return render_template(
        "presencas/painel_presenca.html",
        academias=academias,
        academia_id=academia_id,
        back_url=back_url,
    )


def _parse_ranking_frequencia_args():
    """Query string: mes, ano, turma_id, page, per_page, tipo_filtro."""
    hoje = date.today()
    mes = request.args.get("mes", type=int)
    if mes is None:
        mes = hoje.month
    ano = request.args.get("ano", type=int)
    if ano is None:
        ano = hoje.year
    mes = max(1, min(12, mes))
    ano = max(2000, min(2100, ano))
    turma_id = request.args.get("turma_id", type=int)
    page = request.args.get("page", type=int) or 1
    per_page = request.args.get("per_page", type=int) or 1
    if per_page not in (1, 3, 6, 12):
        per_page = 1
    page = max(1, page)
    tipo_filtro = request.args.get("tipo_filtro", "mes")
    if tipo_filtro not in ("mes", "ano", "periodo"):
        tipo_filtro = "mes"
    return mes, ano, turma_id, page, per_page, tipo_filtro


def _parse_intervalo_datas_ranking():
    """Opcional: data_inicio e data_fim (YYYY-MM-DD). Retorna (date, date) ou (None, None)."""
    di_s = (request.args.get("data_inicio") or "").strip()
    df_s = (request.args.get("data_fim") or "").strip()
    if len(di_s) < 10 or len(df_s) < 10:
        return None, None
    try:
        di = datetime.strptime(di_s[:10], "%Y-%m-%d").date()
        df = datetime.strptime(df_s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None, None
    if di > df:
        return None, None
    if (df - di).days > 400:
        df = di + timedelta(days=400)
    return di, df


def _turmas_com_presenca_ids(cursor, turma_ids, mes, ano, tipo_filtro, di=None, df=None):
    """Retorna set de turma_ids que têm ao menos uma presença no período selecionado."""
    if not turma_ids:
        return set()
    ph = ",".join(["%s"] * len(turma_ids))
    if tipo_filtro == "ano":
        where = f"YEAR(p.data_presenca) = %s AND COALESCE(p.turma_id, a.TurmaID) IN ({ph})"
        params = (ano,) + tuple(turma_ids)
    elif tipo_filtro == "periodo" and di and df:
        where = f"p.data_presenca BETWEEN %s AND %s AND COALESCE(p.turma_id, a.TurmaID) IN ({ph})"
        params = (di, df) + tuple(turma_ids)
    else:
        where = f"MONTH(p.data_presenca) = %s AND YEAR(p.data_presenca) = %s AND COALESCE(p.turma_id, a.TurmaID) IN ({ph})"
        params = (mes, ano) + tuple(turma_ids)
    cursor.execute(
        f"SELECT DISTINCT COALESCE(p.turma_id, a.TurmaID) AS tid "
        f"FROM presencas p INNER JOIN alunos a ON a.id = p.aluno_id "
        f"WHERE p.presente = 1 AND {where} AND {SQL_MATRICULADO_NA_TURMA_DA_PRESENCA}",
        params,
    )
    return {r["tid"] for r in cursor.fetchall()}


def _paginar_ranking_turmas(items, page, per_page):
    total = len(items)
    if total == 0:
        return [], 1, 0
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    return items[start : start + per_page], total_pages, total


def _ranking_frequencia_query_url(**updates):
    from urllib.parse import urlencode

    p = request.args.to_dict(flat=True)
    for k, v in updates.items():
        if v is None or v == "":
            p.pop(k, None)
        else:
            p[k] = str(v)
    q = urlencode(sorted(p.items()))
    base = url_for("presencas.ranking_frequencia_pagina")
    return f"{base}?{q}" if q else base


def _ranking_frequencia_detalhe_query_url(**updates):
    from urllib.parse import urlencode

    p = request.args.to_dict(flat=True)
    for k, v in updates.items():
        if v is None or v == "":
            p.pop(k, None)
        else:
            p[k] = str(v)
    q = urlencode(sorted(p.items()))
    base = url_for("presencas.ranking_frequencia_detalhe")
    return f"{base}?{q}" if q else base


@bp_presencas.route("/presencas/ranking-frequencia", methods=["GET"])
@login_required
def ranking_frequencia_pagina():
    """Pódio por turma com filtros (mês, ano, turma) e paginação entre turmas."""
    from urllib.parse import urlencode

    from utils.ranking_frequencia import ranking_frequencia_por_turmas

    mes_sel, ano_sel, turma_filtro, page, per_page, tipo_filtro = _parse_ranking_frequencia_args()
    di, df = _parse_intervalo_datas_ranking()
    modo = session.get("modo_painel") or ""
    destaque_aluno_id = None
    academia_id = None
    academias = []
    back_url = url_for("painel.home")

    def _filtrar_turmas_dd(cursor, turmas_info):
        """Retorna apenas turmas que têm presença no período atual."""
        all_ids = [t["TurmaID"] for t in turmas_info if t.get("TurmaID")]
        ids_com_presenca = _turmas_com_presenca_ids(cursor, all_ids, mes_sel, ano_sel, tipo_filtro, di, df)
        return [t for t in turmas_info if t.get("TurmaID") in ids_com_presenca]

    def _render(ranking_slice, total_pages, total_turmas, turmas_dd, turma_sel_val, completo_slice=None):
        from utils.ranking_frequencia import MES_COMPLETO

        pag = {
            "page": page,
            "total_pages": total_pages,
            "total_turmas": total_turmas,
            "per_page": per_page,
            "has_prev": page > 1 and total_pages > 1,
            "has_next": page < total_pages,
            "url_prev": _ranking_frequencia_query_url(page=page - 1) if page > 1 else None,
            "url_next": _ranking_frequencia_query_url(page=page + 1) if page < total_pages else None,
        }
        hoje = date.today()
        ano_min = hoje.year - 8
        ano_max = hoje.year + 1
        anos_opts = list(range(ano_min, ano_max + 1))
        meses_opts = [(i, MES_COMPLETO[i].capitalize()) for i in range(1, 13)]
        data_inicio_val = (request.args.get("data_inicio") or "").strip()[:10]
        data_fim_val = (request.args.get("data_fim") or "").strip()[:10]

        # Para cada turma, montar lista unificada com um único ranking/podio
        turmas_unificadas = []
        for i, bl in enumerate(ranking_slice or []):
            cb = (completo_slice or [])[i] if completo_slice and i < len(completo_slice) else None
            if tipo_filtro == "ano":
                top3 = bl.get("top3_ano", [])
                alunos = cb.get("alunos_ano", []) if cb else []
                rotulo = f"Ano {bl.get('ano_rotulo', ano_sel)}"
            else:
                top3 = bl.get("top3_mes", [])
                alunos = cb.get("alunos_periodo", []) if cb else []
                rotulo = bl.get("mes_rotulo", "")
            turmas_unificadas.append({
                "turma_id": bl.get("turma_id"),
                "turma_nome": bl.get("turma_nome"),
                "rotulo": rotulo,
                "top3": top3,
                "alunos": alunos,
            })

        return render_template(
            "presencas/ranking_frequencia.html",
            turmas_ranking=turmas_unificadas,
            destaque_aluno_id=destaque_aluno_id,
            academia_id=academia_id,
            academias=academias or [],
            back_url=back_url,
            mes_sel=mes_sel,
            ano_sel=ano_sel,
            turma_sel=turma_sel_val,
            turmas_opciones=turmas_dd or [],
            pagination=pag,
            ano_min=ano_min,
            ano_max=ano_max,
            anos_opts=anos_opts,
            meses_opts=meses_opts,
            per_page_sel=per_page,
            data_inicio_val=data_inicio_val,
            data_fim_val=data_fim_val,
            tipo_filtro=tipo_filtro,
            mes_atual=hoje.month,
            ano_atual=hoje.year,
        )

    # --- Aluno ---
    if modo == "aluno":
        if not (current_user.has_role("aluno") or current_user.has_role("admin")):
            flash("Acesso restrito.", "danger")
            return redirect(url_for("painel.home"))
        from blueprints.aluno.painel import _get_aluno

        aluno = _get_aluno()
        if not aluno:
            flash("Aluno não encontrado para este usuário.", "warning")
            return redirect(url_for("painel.home"))
        destaque_aluno_id = aluno.get("id")
        back_url = url_for("painel_aluno.meu_perfil")

        db = get_db_connection()
        cur = db.cursor(dictionary=True)
        try:
            ids = set()
            if aluno.get("TurmaID"):
                ids.add(aluno["TurmaID"])
            cur.execute("SELECT TurmaID FROM aluno_turmas WHERE aluno_id = %s", (aluno["id"],))
            for r in cur.fetchall():
                if r.get("TurmaID"):
                    ids.add(r["TurmaID"])
            if not ids:
                return _render([], 1, 0, [], None)
            ph = ",".join(["%s"] * len(ids))
            cur.execute(
                f"SELECT TurmaID, Nome FROM turmas WHERE TurmaID IN ({ph}) ORDER BY Nome",
                tuple(ids),
            )
            turmas_info_full = cur.fetchall()
            allowed_turma_ids = {t["TurmaID"] for t in turmas_info_full}
            turmas_query = list(turmas_info_full)
            turma_sel_val = turma_filtro
            if turma_filtro and turma_filtro in allowed_turma_ids:
                turmas_query = [t for t in turmas_query if t["TurmaID"] == turma_filtro]
            else:
                turma_sel_val = None

            from utils.ranking_frequencia import ranking_completo_por_turmas as _rcp
            full = ranking_frequencia_por_turmas(
                cur,
                turmas_query,
                mes=mes_sel,
                ano=ano_sel,
                data_inicio=di,
                data_fim=df,
            )
            completo = _rcp(cur, turmas_query, mes=mes_sel, ano=ano_sel, data_inicio=di, data_fim=df)
            turmas_dd = _filtrar_turmas_dd(cur, turmas_info_full)
            slice_, total_pages, total = _paginar_ranking_turmas(full, page, per_page)
            completo_slice, _, _ = _paginar_ranking_turmas(completo, page, per_page)
            return _render(slice_, total_pages, total, turmas_dd, turma_sel_val, completo_slice)
        finally:
            cur.close()
            db.close()

    # --- Professor ---
    if modo == "professor":
        from blueprints.professor.routes import (
            _get_todos_professor_ids,
            _get_turmas_professor,
            _usuario_e_professor_ou_auxiliar,
        )

        if not current_user.has_role("professor") and not _usuario_e_professor_ou_auxiliar():
            flash("Acesso negado.", "danger")
            return redirect(url_for("painel.home"))
        todos = _get_todos_professor_ids()
        if not todos:
            flash("Nenhuma turma vinculada ao professor.", "warning")
            return redirect(url_for("professor.painel_professor"))
        ids_prof = [p[0] for p in todos]
        turmas_info_full = _get_turmas_professor(ids_prof, None)
        allowed_turma_ids = {t["TurmaID"] for t in turmas_info_full}
        back_url = url_for("professor.painel_professor")

        turmas_query = list(turmas_info_full)
        turma_sel_val = turma_filtro
        if turma_filtro and turma_filtro in allowed_turma_ids:
            turmas_query = [t for t in turmas_query if t["TurmaID"] == turma_filtro]
        else:
            turma_sel_val = None

        db = get_db_connection()
        cur = db.cursor(dictionary=True)
        try:
            from utils.ranking_frequencia import ranking_completo_por_turmas as _rcp
            full = ranking_frequencia_por_turmas(
                cur,
                turmas_query,
                mes=mes_sel,
                ano=ano_sel,
                data_inicio=di,
                data_fim=df,
            )
            completo = _rcp(cur, turmas_query, mes=mes_sel, ano=ano_sel, data_inicio=di, data_fim=df)
            turmas_dd = _filtrar_turmas_dd(cur, turmas_info_full)
            slice_, total_pages, total = _paginar_ranking_turmas(full, page, per_page)
            completo_slice, _, _ = _paginar_ranking_turmas(completo, page, per_page)
            return _render(slice_, total_pages, total, turmas_dd, turma_sel_val, completo_slice)
        finally:
            cur.close()
            db.close()

    # --- Academia / gestores ---
    if not (
        current_user.has_role("gestor_academia")
        or current_user.has_role("professor")
        or current_user.has_role("admin")
        or current_user.has_role("gestor_federacao")
        or current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    academia_id, academias = _get_academias_presenca()
    academias = academias or []
    if not academia_id:
        flash("Nenhuma academia disponível para exibir o ranking.", "warning")
        return redirect(url_for("painel.home"))

    back_url = (
        url_for("academia.painel_academia", academia_id=academia_id)
        if academia_id
        else url_for("painel.home")
    )

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome",
            (academia_id,),
        )
        turmas_info_full = cur.fetchall()
        allowed_turma_ids = {t["TurmaID"] for t in turmas_info_full}

        turmas_query = list(turmas_info_full)
        turma_sel_val = turma_filtro
        if turma_filtro and turma_filtro in allowed_turma_ids:
            turmas_query = [t for t in turmas_query if t["TurmaID"] == turma_filtro]
        else:
            turma_sel_val = None

        from utils.ranking_frequencia import ranking_completo_por_turmas as _rcp
        full = ranking_frequencia_por_turmas(
            cur,
            turmas_query,
            mes=mes_sel,
            ano=ano_sel,
            data_inicio=di,
            data_fim=df,
        )
        completo = _rcp(cur, turmas_query, mes=mes_sel, ano=ano_sel, data_inicio=di, data_fim=df)
        turmas_dd = _filtrar_turmas_dd(cur, turmas_info_full)
        slice_, total_pages, total = _paginar_ranking_turmas(full, page, per_page)
        completo_slice, _, _ = _paginar_ranking_turmas(completo, page, per_page)
        return _render(slice_, total_pages, total, turmas_dd, turma_sel_val, completo_slice)
    finally:
        cur.close()
        db.close()


@bp_presencas.route("/presencas/ranking-frequencia/detalhe", methods=["GET"])
@login_required
def ranking_frequencia_detalhe():
    """Tabelas com todos os alunos por turma (mesmo período do pódio + total no ano)."""
    from utils.ranking_frequencia import MES_COMPLETO, ranking_completo_por_turmas

    mes_sel, ano_sel, turma_filtro, page, per_page, tipo_filtro = _parse_ranking_frequencia_args()
    di, df = _parse_intervalo_datas_ranking()
    modo = session.get("modo_painel") or ""
    destaque_aluno_id = None
    academia_id = None
    academias = []
    back_url = url_for("painel.home")

    def _render_detalhe(ranking_slice, total_pages, total_turmas, turmas_dd, turma_sel_val):
        pag = {
            "page": page,
            "total_pages": total_pages,
            "total_turmas": total_turmas,
            "per_page": per_page,
            "has_prev": page > 1 and total_pages > 1,
            "has_next": page < total_pages,
            "url_prev": _ranking_frequencia_detalhe_query_url(page=page - 1) if page > 1 else None,
            "url_next": _ranking_frequencia_detalhe_query_url(page=page + 1) if page < total_pages else None,
        }
        ano_min = date.today().year - 8
        ano_max = date.today().year + 1
        anos_opts = list(range(ano_min, ano_max + 1))
        meses_opts = [(i, MES_COMPLETO[i].capitalize()) for i in range(1, 13)]
        url_voltar_podium = _ranking_frequencia_query_url()
        return render_template(
            "presencas/ranking_frequencia_detalhe.html",
            ranking_completo_turmas=ranking_slice,
            destaque_aluno_id=destaque_aluno_id,
            academia_id=academia_id,
            academias=academias or [],
            back_url=back_url,
            mes_sel=mes_sel,
            ano_sel=ano_sel,
            turma_sel=turma_sel_val,
            turmas_opciones=turmas_dd or [],
            pagination=pag,
            ano_min=ano_min,
            ano_max=ano_max,
            anos_opts=anos_opts,
            meses_opts=meses_opts,
            per_page_sel=per_page,
            url_voltar_podium=url_voltar_podium,
            data_inicio_val=(request.args.get("data_inicio") or "").strip()[:10],
            data_fim_val=(request.args.get("data_fim") or "").strip()[:10],
            usa_intervalo_datas=bool(di and df),
        )

    if modo == "aluno":
        if not (current_user.has_role("aluno") or current_user.has_role("admin")):
            flash("Acesso restrito.", "danger")
            return redirect(url_for("painel.home"))
        from blueprints.aluno.painel import _get_aluno

        aluno = _get_aluno()
        if not aluno:
            flash("Aluno não encontrado para este usuário.", "warning")
            return redirect(url_for("painel.home"))
        destaque_aluno_id = aluno.get("id")
        back_url = url_for("painel_aluno.meu_perfil")

        db = get_db_connection()
        cur = db.cursor(dictionary=True)
        try:
            ids = set()
            if aluno.get("TurmaID"):
                ids.add(aluno["TurmaID"])
            cur.execute("SELECT TurmaID FROM aluno_turmas WHERE aluno_id = %s", (aluno["id"],))
            for r in cur.fetchall():
                if r.get("TurmaID"):
                    ids.add(r["TurmaID"])
            if not ids:
                return _render_detalhe([], 1, 0, [], None)
            ph = ",".join(["%s"] * len(ids))
            cur.execute(
                f"SELECT TurmaID, Nome FROM turmas WHERE TurmaID IN ({ph}) ORDER BY Nome",
                tuple(ids),
            )
            turmas_info_full = cur.fetchall()
            allowed_turma_ids = {t["TurmaID"] for t in turmas_info_full}
            turmas_query = list(turmas_info_full)
            turma_sel_val = turma_filtro
            if turma_filtro and turma_filtro in allowed_turma_ids:
                turmas_query = [t for t in turmas_query if t["TurmaID"] == turma_filtro]
            else:
                turma_sel_val = None

            full = ranking_completo_por_turmas(
                cur,
                turmas_query,
                mes=mes_sel,
                ano=ano_sel,
                data_inicio=di,
                data_fim=df,
            )
            slice_, total_pages, total = _paginar_ranking_turmas(full, page, per_page)
            return _render_detalhe(slice_, total_pages, total, turmas_info_full, turma_sel_val)
        finally:
            cur.close()
            db.close()

    if modo == "professor":
        from blueprints.professor.routes import (
            _get_todos_professor_ids,
            _get_turmas_professor,
            _usuario_e_professor_ou_auxiliar,
        )

        if not current_user.has_role("professor") and not _usuario_e_professor_ou_auxiliar():
            flash("Acesso negado.", "danger")
            return redirect(url_for("painel.home"))
        todos = _get_todos_professor_ids()
        if not todos:
            flash("Nenhuma turma vinculada ao professor.", "warning")
            return redirect(url_for("professor.painel_professor"))
        ids_prof = [p[0] for p in todos]
        turmas_info_full = _get_turmas_professor(ids_prof, None)
        allowed_turma_ids = {t["TurmaID"] for t in turmas_info_full}
        back_url = url_for("professor.painel_professor")

        turmas_query = list(turmas_info_full)
        turma_sel_val = turma_filtro
        if turma_filtro and turma_filtro in allowed_turma_ids:
            turmas_query = [t for t in turmas_query if t["TurmaID"] == turma_filtro]
        else:
            turma_sel_val = None

        db = get_db_connection()
        cur = db.cursor(dictionary=True)
        try:
            full = ranking_completo_por_turmas(
                cur,
                turmas_query,
                mes=mes_sel,
                ano=ano_sel,
                data_inicio=di,
                data_fim=df,
            )
            slice_, total_pages, total = _paginar_ranking_turmas(full, page, per_page)
            return _render_detalhe(slice_, total_pages, total, turmas_info_full, turma_sel_val)
        finally:
            cur.close()
            db.close()

    if not (
        current_user.has_role("gestor_academia")
        or current_user.has_role("professor")
        or current_user.has_role("admin")
        or current_user.has_role("gestor_federacao")
        or current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    academia_id, academias = _get_academias_presenca()
    academias = academias or []
    if not academia_id:
        flash("Nenhuma academia disponível para exibir o ranking.", "warning")
        return redirect(url_for("painel.home"))

    back_url = (
        url_for("academia.painel_academia", academia_id=academia_id)
        if academia_id
        else url_for("painel.home")
    )

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome",
            (academia_id,),
        )
        turmas_info_full = cur.fetchall()
        allowed_turma_ids = {t["TurmaID"] for t in turmas_info_full}

        turmas_query = list(turmas_info_full)
        turma_sel_val = turma_filtro
        if turma_filtro and turma_filtro in allowed_turma_ids:
            turmas_query = [t for t in turmas_query if t["TurmaID"] == turma_filtro]
        else:
            turma_sel_val = None

        full = ranking_completo_por_turmas(
            cur,
            turmas_query,
            mes=mes_sel,
            ano=ano_sel,
            data_inicio=di,
            data_fim=df,
        )
        slice_, total_pages, total = _paginar_ranking_turmas(full, page, per_page)
        return _render_detalhe(slice_, total_pages, total, turmas_info_full, turma_sel_val)
    finally:
        cur.close()
        db.close()


# ======================================================
# 🔹 Registro de Presença
# ======================================================
def _get_academia_filtro_presencas():
    """Retorna academia_id para filtrar (ata, historico, registro)."""
    aid = request.args.get("academia_id", type=int) or request.form.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    if not aid:
        aid, _ = _get_academias_presenca()
    if not aid:
        return None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas and aid in vinculadas:
            cur.close()
            conn.close()
            return aid
        if current_user.has_role("admin"):
            cur.execute("SELECT 1 FROM academias WHERE id = %s", (aid,))
        elif current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT 1 FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ac.id = %s AND ass.id_federacao = %s",
                (aid, getattr(current_user, "id_federacao", None)),
            )
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT 1 FROM academias WHERE id = %s AND id_associacao = %s", (aid, getattr(current_user, "id_associacao", None)))
        else:
            # Professor responsável ou auxiliar (qualquer um em turma_professor)
            cur.execute("SELECT 1 FROM professores WHERE usuario_id = %s AND id_academia = %s AND ativo = 1", (current_user.id, aid))
        if cur.fetchone():
            ok = True
        else:
            ok = False
        cur.close()
        conn.close()
        return aid if ok else None
    except Exception:
        return None


@bp_presencas.route('/registro_presenca', methods=['GET', 'POST'])
@login_required
def registro_presenca():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        _garantir_tabela_registros_aula_presenca(cursor)
        _garantir_tabela_presencas_avulsas(cursor)
        _garantir_tabela_presencas_observacao_aluno(cursor)
        db.commit()
    except Exception:
        db.rollback()
    academia_id = _get_academia_filtro_presencas()
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

    try:
        if academia_id:
            cursor.execute(
                "SELECT TurmaID, Nome, hora_inicio, hora_fim FROM turmas WHERE id_academia = %s ORDER BY Nome",
                (academia_id,),
            )
        else:
            cursor.execute("SELECT TurmaID, Nome, hora_inicio, hora_fim FROM turmas ORDER BY Nome")
        turmas = cursor.fetchall()
        if modo_professor and ids_turmas_professor:
            turmas = [t for t in turmas if t["TurmaID"] in ids_turmas_professor]
    except Exception:
        turmas = []

    # Seleção da turma e data
    turma_selecionada = request.form.get('turma_id') or request.args.get('turma_id')
    turma_selecionada = int(turma_selecionada) if turma_selecionada else None
    data_presenca = request.form.get('data_presenca') or request.args.get('data_presenca') or date.today().strftime('%Y-%m-%d')
    horario_raw = (request.form.get("horario_aula") or request.args.get("horario_aula") or "").strip()
    busca_aluno_nome = (request.args.get("busca_aluno") or request.form.get("busca_aluno") or "").strip()
    _excl_raw = (request.args.get("excluir_aluno_tela") or "").strip()
    excluir_aluno_tela_ids = {int(x) for x in _excl_raw.split(",") if x.strip().isdigit()}
    excluir_aluno_tela_param = ",".join(str(i) for i in sorted(excluir_aluno_tela_ids)) if excluir_aluno_tela_ids else ""

    if turma_selecionada and not horario_raw:
        turma_atual = next((t for t in turmas if t.get("TurmaID") == turma_selecionada), None)
        hora_inicio = turma_atual.get("hora_inicio") if turma_atual else None
        if hora_inicio:
            if hasattr(hora_inicio, 'total_seconds'):  # timedelta from MySQL TIME
                total_sec = int(hora_inicio.total_seconds())
                horario_raw = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
            else:
                horario_raw = str(hora_inicio)[:5]
    horario_aula = _normalizar_horario_aula(horario_raw)
    horario_aula_form = horario_aula[:5]
    registro_aula_atual = {}
    alunos_snapshot_ids = []
    if turma_selecionada:
        try:
            cursor.execute(
                """
                SELECT observacao, plano_aula_texto, plano_aula_arquivo, plano_aula_arquivo_original
                FROM registros_aula_presenca
                WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s
                LIMIT 1
                """,
                (turma_selecionada, data_presenca, horario_aula),
            )
            registro_aula_atual = cursor.fetchone() or {}
        except Exception:
            registro_aula_atual = {}
        try:
            cursor.execute(
                """
                SELECT aluno_id
                FROM presencas
                WHERE turma_id = %s AND data_presenca = %s AND horario_aula = %s
                ORDER BY aluno_id
                """,
                (turma_selecionada, data_presenca, horario_aula),
            )
            alunos_snapshot_ids = [row["aluno_id"] for row in (cursor.fetchall() or [])]
        except Exception:
            alunos_snapshot_ids = []

    # Remover aluno de outra turma da chamada (GET): apaga presença nesta turma/data/horário e oculta na busca
    if request.method == "GET" and turma_selecionada:
        rm = request.args.get("remover_aluno_outra_turma")
        if rm and str(rm).isdigit():
            rm_id = int(rm)
            if modo_professor and ids_turmas_professor and turma_selecionada not in ids_turmas_professor:
                flash("Sem permissão para alterar esta turma.", "danger")
                try:
                    db.commit()
                except Exception:
                    db.rollback()
            else:
                try:
                    if academia_id:
                        cursor.execute(
                            """SELECT a.id FROM alunos a
                               LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                               WHERE (at.TurmaID IS NOT NULL OR a.TurmaID = %s) AND {_filtro}""".format(
                                   _filtro=filtro_alunos_da_academia(academia_id)[0]),
                            (turma_selecionada, turma_selecionada,
                             *filtro_alunos_da_academia(academia_id)[1]),
                        )
                    else:
                        cursor.execute("SELECT id FROM alunos WHERE TurmaID=%s", (turma_selecionada,))
                    native_ids = {row["id"] for row in cursor.fetchall()}
                    if rm_id in native_ids:
                        flash("Este aluno pertence à turma. Desmarque a presença no cartão, se necessário.", "warning")
                    else:
                        if academia_id:
                            cursor.execute(
                                """DELETE p FROM presencas p
                                   INNER JOIN alunos a ON a.id = p.aluno_id
                                   WHERE p.aluno_id = %s AND p.turma_id = %s AND p.data_presenca = %s
                                     AND p.horario_aula = %s AND a.id_academia = %s""",
                                (rm_id, turma_selecionada, data_presenca, horario_aula, academia_id),
                            )
                        else:
                            cursor.execute(
                                """DELETE FROM presencas
                                   WHERE aluno_id = %s AND turma_id = %s AND data_presenca = %s AND horario_aula = %s""",
                                (rm_id, turma_selecionada, data_presenca, horario_aula),
                            )
                        excluir_aluno_tela_ids.add(rm_id)
                        excluir_aluno_tela_param = ",".join(str(i) for i in sorted(excluir_aluno_tela_ids))
                        _extras_chamada_remove_id(
                            turma_selecionada, data_presenca, horario_aula, rm_id
                        )
                        flash("Aluno de outra turma removido da chamada.", "success")
                    db.commit()
                except Exception as e:
                    db.rollback()
                    flash(f"Erro ao remover aluno da chamada: {e}", "danger")
            db.close()
            rp_kw = {
                "turma_id": turma_selecionada,
                "data_presenca": data_presenca,
                "horario_aula": horario_aula_form,
            }
            if academia_id:
                rp_kw["academia_id"] = academia_id
            if busca_aluno_nome:
                rp_kw["busca_aluno"] = busca_aluno_nome
            if excluir_aluno_tela_param:
                rp_kw["excluir_aluno_tela"] = excluir_aluno_tela_param
            return redirect(url_for("presencas.registro_presenca", **rp_kw))

    # Remover registro avulso (GET)
    if request.method == "GET" and turma_selecionada:
        rva = request.args.get("remover_presenca_avulsa")
        if rva and str(rva).isdigit():
            rva_id = int(rva)
            if modo_professor and ids_turmas_professor and turma_selecionada not in ids_turmas_professor:
                flash("Sem permissão para alterar esta turma.", "danger")
                try:
                    db.commit()
                except Exception:
                    db.rollback()
            else:
                try:
                    if academia_id:
                        cursor.execute(
                            """DELETE p FROM presencas_avulsas p
                               INNER JOIN turmas t ON t.TurmaID = p.turma_id
                               WHERE p.id = %s AND p.turma_id = %s AND p.data_aula = %s AND p.horario_aula = %s
                                 AND t.id_academia = %s""",
                            (rva_id, turma_selecionada, data_presenca, horario_aula, academia_id),
                        )
                    else:
                        cursor.execute(
                            """DELETE FROM presencas_avulsas
                               WHERE id = %s AND turma_id = %s AND data_aula = %s AND horario_aula = %s""",
                            (rva_id, turma_selecionada, data_presenca, horario_aula),
                        )
                    if cursor.rowcount:
                        flash("Registro avulso removido.", "success")
                    else:
                        flash("Registro não encontrado ou já removido.", "info")
                    db.commit()
                except Exception as e:
                    db.rollback()
                    flash(f"Erro ao remover registro avulso: {e}", "danger")
            db.close()
            rp_kw = {
                "turma_id": turma_selecionada,
                "data_presenca": data_presenca,
                "horario_aula": horario_aula_form,
            }
            if academia_id:
                rp_kw["academia_id"] = academia_id
            if busca_aluno_nome:
                rp_kw["busca_aluno"] = busca_aluno_nome
            if excluir_aluno_tela_param:
                rp_kw["excluir_aluno_tela"] = excluir_aluno_tela_param
            return redirect(url_for("presencas.registro_presenca", **rp_kw))

    if request.method == 'POST' and turma_selecionada:
        excluir_aluno_tela_form = (request.form.get("excluir_aluno_tela") or "").strip()
        if request.form.get("acao") == "presenca_avulsa":
            nome_av = (request.form.get("nome_presenca_avulsa") or "").strip()
            if len(nome_av) < 2:
                flash("Informe o nome (ao menos 2 caracteres).", "danger")
            elif len(nome_av) > 200:
                flash("Nome muito longo (máx. 200 caracteres).", "danger")
            elif modo_professor and ids_turmas_professor and turma_selecionada not in ids_turmas_professor:
                flash("Sem permissão para alterar esta turma.", "danger")
            else:
                try:
                    cursor.execute(
                        """
                        SELECT id FROM presencas_avulsas
                        WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s
                          AND LOWER(TRIM(nome)) = LOWER(TRIM(%s))
                          AND responsavel_id = %s
                          AND criado_em > (NOW() - INTERVAL 2 MINUTE)
                        LIMIT 1
                        """,
                        (turma_selecionada, data_presenca, horario_aula, nome_av, current_user.id),
                    )
                    if cursor.fetchone():
                        flash(
                            "Este nome já foi incluído há instantes nesta aula. Aguarde a lista atualizar ou confira se já consta.",
                            "warning",
                        )
                    else:
                        arquivo_foto = request.files.get("foto_presenca_avulsa")
                        foto_nome, err_foto = _salvar_foto_presenca_avulsa(arquivo_foto)
                        if err_foto:
                            flash(err_foto, "danger")
                        else:
                            cursor.execute(
                                """
                                INSERT INTO presencas_avulsas
                                (turma_id, data_aula, horario_aula, academia_id, nome, foto, presente, responsavel_id, responsavel_nome)
                                VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s)
                                """,
                                (
                                    turma_selecionada,
                                    data_presenca,
                                    horario_aula,
                                    academia_id,
                                    nome_av,
                                    foto_nome,
                                    current_user.id,
                                    current_user.nome,
                                ),
                            )
                            db.commit()
                            flash("Registro avulso incluído na chamada.", "success")
                except Exception as e:
                    db.rollback()
                    flash(f"Erro ao salvar registro avulso: {e}", "danger")
            db.close()
            rp_kw = {
                "turma_id": turma_selecionada,
                "data_presenca": data_presenca,
                "horario_aula": horario_aula_form,
            }
            if academia_id:
                rp_kw["academia_id"] = academia_id
            # Não repassar busca_aluno após avulso: o hidden do modal copiava o termo antigo e a página
            # reaplicava query_busca na volta, bloqueando/confundindo incluir outro aluno (outra turma).
            if excluir_aluno_tela_form:
                rp_kw["excluir_aluno_tela"] = excluir_aluno_tela_form
            return redirect(url_for("presencas.registro_presenca", **rp_kw))

        observacao_aula = (request.form.get("observacao_aula") or "").strip()
        plano_aula_texto = (request.form.get("plano_aula_texto") or "").strip()
        plano_arquivo_nome = registro_aula_atual.get("plano_aula_arquivo")
        plano_arquivo_nome_original = registro_aula_atual.get("plano_aula_arquivo_original")
        arquivo_plano = request.files.get("plano_aula_arquivo")
        if arquivo_plano and arquivo_plano.filename:
            arquivo_salvo, nome_original, erro_arquivo = _salvar_arquivo_plano_aula(
                arquivo_plano,
                turma_selecionada,
                data_presenca,
                horario_aula,
            )
            if erro_arquivo:
                flash(erro_arquivo, "warning")
            elif arquivo_salvo:
                plano_arquivo_nome = arquivo_salvo
                plano_arquivo_nome_original = nome_original

        alunos_selecionados_raw = request.form.getlist('aluno_id')
        alunos_selecionados = {
            int(a) for a in alunos_selecionados_raw
            if str(a).isdigit()
        }

        try:
            usar_base_snapshot_post = False
            try:
                cursor.execute(
                    """
                    SELECT DISTINCT aluno_id
                    FROM presencas
                    WHERE turma_id = %s AND data_presenca = %s AND horario_aula = %s
                    """,
                    (turma_selecionada, data_presenca, horario_aula),
                )
                snapshot_rows = cursor.fetchall() or []
                if snapshot_rows:
                    todos_alunos = [row["aluno_id"] for row in snapshot_rows]
                    usar_base_snapshot_post = True
                else:
                    todos_alunos = []
            except Exception:
                todos_alunos = []
            if not usar_base_snapshot_post and academia_id:
                # O aluno vinculado a esta academia entra na chamada da turma dela,
                # mesmo tendo outra academia como principal.
                _t, _p = filtro_alunos_da_academia(academia_id)
                cursor.execute(
                    f"""SELECT a.id FROM alunos a
                        LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                        WHERE (at.TurmaID IS NOT NULL OR a.TurmaID = %s) AND {_t}""",
                    (turma_selecionada, turma_selecionada, *_p),
                )
                todos_alunos = [row['id'] for row in cursor.fetchall()]
            elif not usar_base_snapshot_post:
                cursor.execute("SELECT id FROM alunos WHERE TurmaID=%s", (turma_selecionada,))
                todos_alunos = [row['id'] for row in cursor.fetchall()]
            # Buscar visitantes com aulas experimentais agendadas apenas quando não há snapshot consolidado.
            if not usar_base_snapshot_post:
                try:
                    cursor.execute("""
                        SELECT v.id FROM visitantes v
                        INNER JOIN aulas_experimentais ae ON ae.visitante_id = v.id
                        WHERE ae.turma_id = %s AND ae.data_aula = %s AND v.id_academia = %s AND v.ativo = 1
                    """, (turma_selecionada, data_presenca, academia_id))
                    for row in cursor.fetchall():
                        vid = f"visitante_{row.get('id')}"
                        if vid not in todos_alunos:
                            todos_alunos.append(vid)
                except Exception:
                    pass
            try:
                cursor.execute(
                    """SELECT id FROM presencas_avulsas
                       WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s""",
                    (turma_selecionada, data_presenca, horario_aula),
                )
                for row in cursor.fetchall():
                    aid = f"avulso_{row['id']}"
                    if aid not in todos_alunos:
                        todos_alunos.append(aid)
            except Exception:
                pass
        except Exception:
            try:
                cursor.execute("SELECT id FROM alunos WHERE TurmaID=%s", (turma_selecionada,))
                todos_alunos = [row['id'] for row in cursor.fetchall()]
            except Exception:
                todos_alunos = []

        try:
            # Separar alunos, visitantes e presenças avulsas
            alunos_ids = []
            visitantes_ids = []
            avulso_ids = []
            for aluno_id in todos_alunos:
                sid = str(aluno_id)
                if sid.startswith("visitante_"):
                    visitantes_ids.append(int(sid.replace("visitante_", "")))
                elif sid.startswith("avulso_"):
                    avulso_ids.append(int(sid.replace("avulso_", "")))
                else:
                    alunos_ids.append(aluno_id)

            # Permite marcar presença de alunos de outras turmas OU outras academias
            ids_turma_base = set(alunos_ids)
            ids_extras_selecionados = sorted(
                aluno_id for aluno_id in alunos_selecionados
                if aluno_id not in ids_turma_base
            )
            if ids_extras_selecionados:
                placeholders = ",".join(["%s"] * len(ids_extras_selecionados))
                # Aceita qualquer aluno válido (mesma ou outra academia)
                cursor.execute(
                    f"SELECT id FROM alunos WHERE id IN ({placeholders})",
                    tuple(ids_extras_selecionados),
                )
                ids_externos_validos = {row["id"] for row in cursor.fetchall()}
                for externo_id in ids_externos_validos:
                    if externo_id not in ids_turma_base:
                        alunos_ids.append(externo_id)

            # Sem ninguém marcado como presente => cancelar o registro desta turma/data/horário.
            if len(alunos_selecionados_raw) == 0:
                cursor.execute(
                    """
                    DELETE FROM presencas
                    WHERE turma_id = %s
                      AND data_presenca = %s
                      AND horario_aula = %s
                    """,
                    (turma_selecionada, data_presenca, horario_aula),
                )
                removidos = cursor.rowcount or 0

                try:
                    cursor.execute(
                        """
                        DELETE FROM presencas_avulsas
                        WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s
                        """,
                        (turma_selecionada, data_presenca, horario_aula),
                    )
                except Exception:
                    pass

                if visitantes_ids:
                    placeholders = ",".join(["%s"] * len(visitantes_ids))
                    cursor.execute(
                        f"""
                        UPDATE aulas_experimentais
                        SET presente = 0, registrado_por = %s
                        WHERE turma_id = %s
                          AND data_aula = %s
                          AND visitante_id IN ({placeholders})
                        """,
                        [current_user.id, turma_selecionada, data_presenca] + visitantes_ids,
                    )

                tem_dados_aula = bool(observacao_aula or plano_aula_texto or plano_arquivo_nome)
                if tem_dados_aula:
                    try:
                        cursor.execute(
                            """
                            INSERT INTO registros_aula_presenca
                            (
                                turma_id, academia_id, data_aula, horario_aula,
                                observacao, plano_aula_texto, plano_aula_arquivo, plano_aula_arquivo_original,
                                responsavel_id, responsavel_nome
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                observacao = VALUES(observacao),
                                plano_aula_texto = VALUES(plano_aula_texto),
                                plano_aula_arquivo = VALUES(plano_aula_arquivo),
                                plano_aula_arquivo_original = VALUES(plano_aula_arquivo_original),
                                responsavel_id = VALUES(responsavel_id),
                                responsavel_nome = VALUES(responsavel_nome),
                                atualizado_em = CURRENT_TIMESTAMP
                            """,
                            (
                                turma_selecionada,
                                academia_id,
                                data_presenca,
                                horario_aula,
                                observacao_aula if observacao_aula else None,
                                plano_aula_texto if plano_aula_texto else None,
                                plano_arquivo_nome,
                                plano_arquivo_nome_original,
                                current_user.id,
                                current_user.nome,
                            ),
                        )
                    except Exception as e:
                        flash(f"Observação/plano não puderam ser salvos: {e}", "warning")
                else:
                    try:
                        cursor.execute(
                            """
                            DELETE FROM registros_aula_presenca
                            WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s
                            """,
                            (turma_selecionada, data_presenca, horario_aula),
                        )
                    except Exception:
                        pass

                db.commit()
                _extras_chamada_clear(turma_selecionada, data_presenca, horario_aula)
                if removidos > 0:
                    flash("Registro de presença cancelado para esta turma/horário.", "warning")
                else:
                    flash("Nenhum aluno marcado: não há registro ativo para cancelar nessa turma/horário.", "info")
                if tem_dados_aula:
                    flash("Observação/plano de aula salvos para esta turma/horário.", "success")
                db.close()

                kwargs = {"turma_id": turma_selecionada, "data_presenca": data_presenca, "horario_aula": horario_aula_form}
                if academia_id:
                    kwargs["academia_id"] = academia_id
                if busca_aluno_nome:
                    kwargs["busca_aluno"] = busca_aluno_nome
                if excluir_aluno_tela_form:
                    kwargs["excluir_aluno_tela"] = excluir_aluno_tela_form
                return redirect(url_for("presencas.registro_presenca", **kwargs))
            
            # Identificar alunos visitando outra academia nesta data (para não marcar como ausente)
            ids_visitando_outra = set()
            if alunos_ids and academia_id:
                ph_v = ",".join(["%s"] * len(alunos_ids))
                try:
                    cursor.execute(f"""
                        SELECT DISTINCT aluno_id FROM solicitacoes_aprovacao
                        WHERE aluno_id IN ({ph_v}) AND data_visita = %s
                          AND status = 'aprovado_destino' AND tipo = 'visita' AND academia_origem_id = %s
                    """, tuple(alunos_ids) + (data_presenca, academia_id))
                    ids_visitando_outra = {row['aluno_id'] for row in cursor.fetchall()}
                except Exception:
                    pass

            # Registrar presenças de alunos
            for aluno_id in alunos_ids:
                # Não registrar ausência para alunos com visita aprovada em outra academia
                if aluno_id in ids_visitando_outra and aluno_id not in alunos_selecionados:
                    continue
                presente = 1 if aluno_id in alunos_selecionados else 0

                # Registrar presença na turma atual
                cursor.execute("""
                    INSERT INTO presencas (aluno_id, turma_id, data_presenca, horario_aula, responsavel_id, responsavel_nome, presente)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        presente = VALUES(presente),
                        responsavel_id = VALUES(responsavel_id),
                        responsavel_nome = VALUES(responsavel_nome),
                        registrado_em = CURRENT_TIMESTAMP
                """, (aluno_id, turma_selecionada, data_presenca, horario_aula, current_user.id, current_user.nome, presente))
                if presente == 1 and academia_id:
                    _espelhar_presenca_visita_na_academia_origem(
                        cursor,
                        aluno_id,
                        turma_selecionada,
                        data_presenca,
                        academia_id,
                        current_user.id,
                        current_user.nome,
                    )
            
            # Registrar presenças de visitantes (atualizar aulas_experimentais)
            for visitante_id in visitantes_ids:
                presente = 1 if f"visitante_{visitante_id}" in alunos_selecionados_raw else 0
                # Atualizar aula experimental
                cursor.execute("""
                    UPDATE aulas_experimentais 
                    SET presente = %s, registrado_por = %s
                    WHERE visitante_id = %s AND turma_id = %s AND data_aula = %s
                """, (presente, current_user.id, visitante_id, turma_selecionada, data_presenca))
                
                # Se presente, atualizar contador de aulas realizadas
                if presente:
                    cursor.execute("""
                        UPDATE visitantes
                        SET aulas_experimentais_realizadas = (
                            SELECT COUNT(*) FROM aulas_experimentais
                            WHERE visitante_id = %s AND presente = 1 AND data_aula <= CURDATE()
                        )
                        WHERE id = %s
                    """, (visitante_id, visitante_id))

            for avulso_id in avulso_ids:
                presente = 1 if f"avulso_{avulso_id}" in alunos_selecionados_raw else 0
                try:
                    cursor.execute(
                        """
                        UPDATE presencas_avulsas
                        SET presente = %s, responsavel_id = %s, responsavel_nome = %s
                        WHERE id = %s AND turma_id = %s AND data_aula = %s AND horario_aula = %s
                        """,
                        (
                            presente,
                            current_user.id,
                            current_user.nome,
                            avulso_id,
                            turma_selecionada,
                            data_presenca,
                            horario_aula,
                        ),
                    )
                except Exception:
                    pass

            try:
                cursor.execute(
                    """
                    INSERT INTO registros_aula_presenca
                    (
                        turma_id, academia_id, data_aula, horario_aula,
                        observacao, plano_aula_texto, plano_aula_arquivo, plano_aula_arquivo_original,
                        responsavel_id, responsavel_nome
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        observacao = VALUES(observacao),
                        plano_aula_texto = VALUES(plano_aula_texto),
                        plano_aula_arquivo = VALUES(plano_aula_arquivo),
                        plano_aula_arquivo_original = VALUES(plano_aula_arquivo_original),
                        responsavel_id = VALUES(responsavel_id),
                        responsavel_nome = VALUES(responsavel_nome),
                        atualizado_em = CURRENT_TIMESTAMP
                    """,
                    (
                        turma_selecionada,
                        academia_id,
                        data_presenca,
                        horario_aula,
                        observacao_aula if observacao_aula else None,
                        plano_aula_texto if plano_aula_texto else None,
                        plano_arquivo_nome,
                        plano_arquivo_nome_original,
                        current_user.id,
                        current_user.nome,
                    ),
                )
            except Exception as e:
                flash(f"Presenças salvas, mas houve erro ao salvar observação/plano: {e}", "warning")
            
            db.commit()
            flash("Presenças registradas com sucesso!", "success")
            _extras_chamada_clear(turma_selecionada, data_presenca, horario_aula)
        except Exception as e:
            db.rollback()
            flash(f"Erro ao registrar presenças: {e}", "danger")

        db.close()
        
        # ⚠️ CORREÇÃO/GARANTIA: Referenciando a rota com o prefixo do Blueprint
        kwargs = {"turma_id": turma_selecionada, "data_presenca": data_presenca, "horario_aula": horario_aula_form}
        if academia_id:
            kwargs["academia_id"] = academia_id
        if busca_aluno_nome:
            kwargs["busca_aluno"] = busca_aluno_nome
        if excluir_aluno_tela_form:
            kwargs["excluir_aluno_tela"] = excluir_aluno_tela_form
        return redirect(url_for("presencas.registro_presenca", **kwargs))

    alunos = []
    presencas_registradas = []
    if turma_selecionada and academia_id:
        try:
            cursor.execute("SELECT TurmaID FROM turmas WHERE TurmaID = %s AND id_academia = %s", (turma_selecionada, academia_id))
            if not cursor.fetchone():
                turma_selecionada = None
        except Exception:
            turma_selecionada = None
    alunos = []
    alunos_visitantes = []
    if turma_selecionada:
        try:
            if alunos_snapshot_ids:
                ph_snapshot = ",".join(["%s"] * len(alunos_snapshot_ids))
                cursor.execute(
                    f"""
                    SELECT a.id, a.nome, a.foto, a.TurmaID AS turma_origem_id, t_origem.Nome AS turma_origem_nome
                    FROM alunos a
                    LEFT JOIN turmas t_origem ON t_origem.TurmaID = a.TurmaID
                    WHERE a.id IN ({ph_snapshot})
                    ORDER BY a.nome
                    """,
                    tuple(alunos_snapshot_ids),
                )
                alunos = cursor.fetchall()
                for a in alunos:
                    try:
                        a["aluno_outra_turma"] = int(a.get("turma_origem_id") or 0) != int(turma_selecionada)
                    except (TypeError, ValueError):
                        a["aluno_outra_turma"] = False
                ids_alunos_turma = set()
            elif academia_id:
                cursor.execute(
                    """SELECT a.id, a.nome, a.foto FROM alunos a
                       LEFT JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
                       WHERE (at.TurmaID IS NOT NULL OR a.TurmaID = %s) AND a.id_academia = %s
                       ORDER BY a.nome""",
                    (turma_selecionada, turma_selecionada, academia_id),
                )
            else:
                cursor.execute("SELECT id, nome, foto FROM alunos WHERE TurmaID=%s ORDER BY nome", (turma_selecionada,))
            alunos = cursor.fetchall()
            ids_alunos_turma = {a["id"] for a in alunos}
            
            # Buscar alunos da turma que estão visitando outra academia nesta data
            alunos_visitando_outra_academia = []
            if ids_alunos_turma:
                try:
                    placeholders = ",".join(["%s"] * len(ids_alunos_turma))
                    cursor.execute(f"""
                        SELECT a.id, a.nome, a.foto, s.id AS solicitacao_id, ac_dest.nome AS academia_destino_nome, 
                               s.turma_id AS turma_destino_id, s.academia_destino_id
                        FROM alunos a
                        INNER JOIN solicitacoes_aprovacao s ON s.aluno_id = a.id
                        INNER JOIN academias ac_dest ON ac_dest.id = s.academia_destino_id
                        WHERE a.id IN ({placeholders}) AND s.data_visita = %s AND s.status = 'aprovado_destino' 
                          AND s.tipo = 'visita' AND s.academia_origem_id = %s
                        ORDER BY a.nome
                    """, tuple(ids_alunos_turma) + (data_presenca, academia_id))
                    alunos_visitando_raw = cursor.fetchall()
                    for a in alunos_visitando_raw:
                        a["visitando_outra_academia"] = True
                        a["bloqueado"] = True  # Card bloqueado na turma original
                        alunos_visitando_outra_academia.append(a)
                except Exception:
                    pass
            
            # Buscar visitantes com aulas experimentais agendadas e APROVADAS para esta turma e data
            try:
                cursor.execute("""
                    SELECT v.id, v.nome, v.foto, ae.id AS aula_experimental_id
                    FROM visitantes v
                    INNER JOIN aulas_experimentais ae ON ae.visitante_id = v.id
                    WHERE ae.turma_id = %s AND ae.data_aula = %s AND v.id_academia = %s 
                      AND v.ativo = 1 AND ae.aprovado = 1
                    ORDER BY v.nome
                """, (turma_selecionada, data_presenca, academia_id))
                visitantes_raw = cursor.fetchall()
                for v in visitantes_raw:
                    v["visitante"] = True
                    v["id"] = f"visitante_{v['id']}"  # Prefixo para diferenciar de alunos
                    alunos_visitantes.append(v)
            except Exception:
                pass
            
            # Buscar alunos com solicitações de visita APROVADAS para esta turma e data
            try:
                if ids_alunos_turma:
                    # Se há alunos da turma, excluir da busca de alunos em visita
                    placeholders = ",".join(["%s"] * len(ids_alunos_turma))
                    cursor.execute(f"""
                        SELECT a.id, a.nome, a.foto, s.id AS solicitacao_id, ac_orig.nome AS academia_origem_nome
                        FROM alunos a
                        INNER JOIN solicitacoes_aprovacao s ON s.aluno_id = a.id
                        INNER JOIN academias ac_orig ON ac_orig.id = s.academia_origem_id
                        WHERE s.turma_id = %s AND s.data_visita = %s AND s.academia_destino_id = %s
                          AND s.status = 'aprovado_destino' AND s.tipo = 'visita'
                          AND a.id NOT IN ({placeholders})
                        ORDER BY a.nome
                    """, (turma_selecionada, data_presenca, academia_id) + tuple(ids_alunos_turma))
                else:
                    # Se não há alunos da turma, buscar todos os alunos em visita
                    cursor.execute("""
                        SELECT a.id, a.nome, a.foto, s.id AS solicitacao_id, ac_orig.nome AS academia_origem_nome
                        FROM alunos a
                        INNER JOIN solicitacoes_aprovacao s ON s.aluno_id = a.id
                        INNER JOIN academias ac_orig ON ac_orig.id = s.academia_origem_id
                        WHERE s.turma_id = %s AND s.data_visita = %s AND s.academia_destino_id = %s
                          AND s.status = 'aprovado_destino' AND s.tipo = 'visita'
                        ORDER BY a.nome
                    """, (turma_selecionada, data_presenca, academia_id))
                alunos_visita_raw = cursor.fetchall()
                for a in alunos_visita_raw:
                    a["visitante"] = False  # É aluno, mas visitando outra academia
                    a["aluno_visita"] = True  # Marca como aluno em visita
                    alunos_visitantes.append(a)
            except Exception as e:
                # Se a tabela não existir ou houver erro, continua sem adicionar alunos em visita
                pass
            
            # Remover da lista principal os alunos que já aparecem como bloqueados (evitar duplicatas)
            ids_bloqueados = {a["id"] for a in alunos_visitando_outra_academia}
            alunos = [a for a in alunos if a["id"] not in ids_bloqueados]
            alunos = alunos + alunos_visitantes + alunos_visitando_outra_academia

            ids_alunos_tela = set()
            for a in alunos:
                aid = a.get("id")
                if isinstance(aid, str) and (
                    aid.startswith("visitante_") or aid.startswith("avulso_")
                ):
                    continue
                try:
                    ids_alunos_tela.add(int(aid))
                except (TypeError, ValueError):
                    pass

            # Garante que alunos externos já registrados na chamada continuem visíveis
            # Escopo pela turma da aula (t_aula.id_academia), não por a.id_academia — senão alunos de
            # outra academia somem após gravar presença (o registro está em presencas desta turma).
            params_externos_registrados = [turma_selecionada, data_presenca, horario_aula]
            query_externos_registrados = """
                SELECT DISTINCT a.id, a.nome, a.foto, a.id_academia,
                       t_origem.Nome AS turma_origem_nome,
                       ac_home.nome AS academia_origem_nome
                FROM presencas p
                INNER JOIN alunos a ON a.id = p.aluno_id
                INNER JOIN turmas t_aula ON t_aula.TurmaID = p.turma_id
                LEFT JOIN turmas t_origem ON t_origem.TurmaID = a.TurmaID
                LEFT JOIN academias ac_home ON ac_home.id = a.id_academia
                WHERE p.turma_id = %s
                  AND p.data_presenca = %s
                  AND p.horario_aula = %s
            """
            if academia_id:
                query_externos_registrados += " AND t_aula.id_academia = %s"
                params_externos_registrados.append(academia_id)
            cursor.execute(query_externos_registrados, tuple(params_externos_registrados))
            for a in cursor.fetchall():
                if a["id"] in excluir_aluno_tela_ids:
                    continue
                if a["id"] in ids_alunos_tela:
                    continue
                a["aluno_outra_turma"] = True
                if academia_id and a.get("id_academia") is not None:
                    try:
                        if int(a["id_academia"]) != int(academia_id):
                            a["aluno_visita"] = True
                    except (TypeError, ValueError):
                        pass
                alunos.append(a)
                ids_alunos_tela.add(a["id"])

            _merge_extras_sessao_registro_chamada(
                cursor,
                turma_selecionada,
                data_presenca,
                horario_aula,
                academia_id,
                excluir_aluno_tela_ids,
                alunos,
                ids_alunos_tela,
            )

            # Busca por nome para incluir aluno de outra turma na chamada
            if busca_aluno_nome:
                params_busca = [f"%{busca_aluno_nome}%", turma_selecionada, turma_selecionada]
                query_busca = """
                    SELECT a.id, a.nome, a.foto, t_origem.Nome AS turma_origem_nome
                    FROM alunos a
                    LEFT JOIN turmas t_origem ON t_origem.TurmaID = a.TurmaID
                    WHERE a.nome LIKE %s
                      AND (a.ativo IS NULL OR a.ativo = 1)
                      AND NOT (
                          EXISTS (
                              SELECT 1 FROM aluno_turmas at
                              WHERE at.aluno_id = a.id AND at.TurmaID = %s
                          )
                          OR a.TurmaID = %s
                      )
                """
                if academia_id:
                    query_busca += " AND a.id_academia = %s"
                    params_busca.append(academia_id)
                query_busca += " ORDER BY a.nome LIMIT 60"
                cursor.execute(query_busca, tuple(params_busca))
                for a in cursor.fetchall():
                    if a["id"] in excluir_aluno_tela_ids:
                        continue
                    if a["id"] in ids_alunos_tela:
                        continue
                    a["aluno_outra_turma"] = True
                    alunos.append(a)
                    ids_alunos_tela.add(a["id"])
                    _extras_chamada_add_id(
                        turma_selecionada, data_presenca, horario_aula, a["id"]
                    )

            try:
                cursor.execute(
                    """SELECT id, nome, foto FROM presencas_avulsas
                       WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s
                       ORDER BY nome""",
                    (turma_selecionada, data_presenca, horario_aula),
                )
                for av in cursor.fetchall():
                    alunos.append(
                        {
                            "id": f"avulso_{av['id']}",
                            "nome": av["nome"],
                            "foto": av["foto"],
                            "presenca_avulsa": True,
                            "avulso_db_id": av["id"],
                        }
                    )
            except Exception:
                pass

            alunos.sort(key=lambda x: (x.get("nome") or "").lower())
        except Exception:
            try:
                cursor.execute("SELECT id, nome, foto FROM alunos WHERE TurmaID=%s ORDER BY nome", (turma_selecionada,))
                alunos = cursor.fetchall()
            except Exception:
                alunos = []
            try:
                cursor.execute(
                    """SELECT id, nome, foto FROM presencas_avulsas
                       WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s
                       ORDER BY nome""",
                    (turma_selecionada, data_presenca, horario_aula),
                )
                for av in cursor.fetchall():
                    alunos.append(
                        {
                            "id": f"avulso_{av['id']}",
                            "nome": av["nome"],
                            "foto": av["foto"],
                            "presenca_avulsa": True,
                            "avulso_db_id": av["id"],
                        }
                    )
            except Exception:
                pass

        if alunos:
            try:
                # Separar IDs de alunos e visitantes
                visitante_ids_numericos = []
                for a in alunos:
                    if isinstance(a.get('id'), str) and a.get('id').startswith('visitante_'):
                        visitante_ids_numericos.append(int(a['id'].replace('visitante_', '')))
                
                presencas_registradas = []
                
                # Buscar presenças de alunos registradas para a chamada da turma/horário
                cursor.execute(
                    """SELECT aluno_id FROM presencas
                        WHERE data_presenca=%s
                          AND horario_aula=%s
                          AND presente=1
                          AND turma_id=%s""",
                    (data_presenca, horario_aula, turma_selecionada)
                )
                presencas_registradas.extend([row['aluno_id'] for row in cursor.fetchall()])
                
                # Buscar presenças de visitantes (aulas experimentais)
                if visitante_ids_numericos:
                    placeholders = ','.join(['%s'] * len(visitante_ids_numericos))
                    cursor.execute(
                        f"""SELECT visitante_id FROM aulas_experimentais 
                           WHERE data_aula=%s AND turma_id=%s AND presente=1 AND visitante_id IN ({placeholders})""",
                        [data_presenca, turma_selecionada] + visitante_ids_numericos
                    )
                    for row in cursor.fetchall():
                        presencas_registradas.append(f"visitante_{row['visitante_id']}")
                try:
                    cursor.execute(
                        """SELECT id FROM presencas_avulsas
                           WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s AND presente = 1""",
                        (turma_selecionada, data_presenca, horario_aula),
                    )
                    for row in cursor.fetchall():
                        presencas_registradas.append(f"avulso_{row['id']}")
                except Exception:
                    pass
            except Exception:
                presencas_registradas = []

    observacoes_privadas_map = {}
    if turma_selecionada and alunos:
        ids_obs = []
        for a in alunos:
            aid = a.get("id")
            if isinstance(aid, int):
                ids_obs.append(aid)
            elif isinstance(aid, str) and aid.isdigit():
                ids_obs.append(int(aid))
        ids_obs = list(dict.fromkeys(ids_obs))
        if ids_obs:
            try:
                ph = ",".join(["%s"] * len(ids_obs))
                cursor.execute(
                    f"""
                    SELECT aluno_id, observacao FROM presencas_observacao_aluno
                    WHERE turma_id = %s AND data_aula = %s AND horario_aula = %s
                      AND aluno_id IN ({ph})
                    """,
                    [turma_selecionada, data_presenca, horario_aula] + ids_obs,
                )
                for row in cursor.fetchall():
                    observacoes_privadas_map[row["aluno_id"]] = (row.get("observacao") or "").strip()
            except Exception:
                pass

    chamada_presenca_consolidada = False
    if turma_selecionada:
        try:
            cursor.execute(
                """SELECT 1 FROM presencas
                   WHERE turma_id = %s AND data_presenca = %s AND horario_aula = %s
                   LIMIT 1""",
                (turma_selecionada, data_presenca, horario_aula),
            )
            chamada_presenca_consolidada = cursor.fetchone() is not None
        except Exception:
            chamada_presenca_consolidada = False

    db.close()
    presencas_registradas_set = {str(v) for v in presencas_registradas}
    for a in alunos or []:
        a["marcado"] = str(a.get("id")) in presencas_registradas_set
        _pk = None
        _aid = a.get("id")
        if isinstance(_aid, int):
            _pk = _aid
        elif isinstance(_aid, str) and _aid.isdigit():
            _pk = int(_aid)
        a["observacao_privada_aluno"] = observacoes_privadas_map.get(_pk, "") if _pk is not None else ""

    _lista_chamada = alunos or []
    registro_chamada_total = len(_lista_chamada)
    registro_chamada_presentes = sum(1 for a in _lista_chamada if a.get("marcado"))
    if chamada_presenca_consolidada:
        registro_chamada_faltantes = registro_chamada_total - registro_chamada_presentes
    else:
        registro_chamada_faltantes = 0

    if modo_professor:
        back_url = url_for("professor.painel_professor")
    else:
        back_url = url_for("presencas.painel_presenca", academia_id=academia_id) if academia_id else url_for("presencas.painel_presenca")
    def url_registro_remover_aluno_outra_turma(aluno_id):
        """Jinja não aceita url_for(..., **dict); montamos a URL aqui."""
        if not turma_selecionada:
            return url_for("presencas.registro_presenca")
        kw = {
            "turma_id": turma_selecionada,
            "data_presenca": data_presenca,
            "horario_aula": horario_aula_form,
            "remover_aluno_outra_turma": aluno_id,
        }
        if academia_id:
            kw["academia_id"] = academia_id
        if busca_aluno_nome:
            kw["busca_aluno"] = busca_aluno_nome
        if excluir_aluno_tela_param:
            kw["excluir_aluno_tela"] = excluir_aluno_tela_param
        return url_for("presencas.registro_presenca", **kw)

    def url_registro_remover_presenca_avulsa(avulso_row_id):
        if not turma_selecionada:
            return url_for("presencas.registro_presenca")
        kw = {
            "turma_id": turma_selecionada,
            "data_presenca": data_presenca,
            "horario_aula": horario_aula_form,
            "remover_presenca_avulsa": avulso_row_id,
        }
        if academia_id:
            kw["academia_id"] = academia_id
        if busca_aluno_nome:
            kw["busca_aluno"] = busca_aluno_nome
        if excluir_aluno_tela_param:
            kw["excluir_aluno_tela"] = excluir_aluno_tela_param
        return url_for("presencas.registro_presenca", **kw)

    return render_template(
        'registro_presenca.html',
        turmas=turmas,
        alunos=alunos,
        turma_selecionada=turma_selecionada,
        data_presenca=data_presenca,
        horario_aula=horario_aula_form,
        presencas_registradas=presencas_registradas,
        presencas_registradas_set=presencas_registradas_set,
        academia_id=academia_id,
        back_url=back_url,
        busca_aluno_nome=busca_aluno_nome,
        observacao_aula=registro_aula_atual.get("observacao") or "",
        plano_aula_texto=registro_aula_atual.get("plano_aula_texto") or "",
        plano_aula_arquivo=registro_aula_atual.get("plano_aula_arquivo"),
        plano_aula_arquivo_original=registro_aula_atual.get("plano_aula_arquivo_original"),
        url_registro_remover_aluno_outra_turma=url_registro_remover_aluno_outra_turma,
        url_registro_remover_presenca_avulsa=url_registro_remover_presenca_avulsa,
        excluir_aluno_tela_param=excluir_aluno_tela_param,
        registro_chamada_total=registro_chamada_total,
        registro_chamada_presentes=registro_chamada_presentes,
        registro_chamada_faltantes=registro_chamada_faltantes,
        chamada_presenca_consolidada=chamada_presenca_consolidada,
    )


@bp_presencas.route("/registro_presenca/observacao_aluno", methods=["POST"])
@login_required
def salvar_observacao_aluno_presenca():
    """Salva observação individual visível apenas para o aluno em Minhas presenças."""
    academia_id = _get_academia_filtro_presencas()
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

    turma_id = request.form.get("turma_id", type=int)
    data_aula = (request.form.get("data_presenca") or "").strip()
    horario_raw = (request.form.get("horario_aula") or "").strip()
    aluno_id = request.form.get("aluno_id", type=int)
    obs = (request.form.get("observacao_aluno") or "").strip()
    busca_aluno_nome = (request.form.get("busca_aluno") or "").strip()
    excluir_aluno_tela_form = (request.form.get("excluir_aluno_tela") or "").strip()

    def _redirect_kw():
        kw = {}
        if turma_id:
            kw["turma_id"] = turma_id
        if data_aula:
            kw["data_presenca"] = data_aula
        if horario_raw:
            kw["horario_aula"] = horario_raw
        if academia_id:
            kw["academia_id"] = academia_id
        if busca_aluno_nome:
            kw["busca_aluno"] = busca_aluno_nome
        if excluir_aluno_tela_form:
            kw["excluir_aluno_tela"] = excluir_aluno_tela_form
        return kw

    if not turma_id or not data_aula or not aluno_id:
        flash("Dados incompletos para salvar a observação.", "danger")
        return redirect(url_for("presencas.registro_presenca", **_redirect_kw()))

    if modo_professor and ids_turmas_professor and turma_id not in ids_turmas_professor:
        flash("Sem permissão para esta turma.", "danger")
        return redirect(url_for("presencas.registro_presenca", **_redirect_kw()))

    horario_aula = _normalizar_horario_aula(horario_raw)

    if len(obs) > 2000:
        flash("Observação muito longa (máximo 2000 caracteres).", "danger")
        return redirect(url_for("presencas.registro_presenca", **_redirect_kw()))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        _garantir_tabela_presencas_observacao_aluno(cursor)
        db.commit()
    except Exception:
        db.rollback()

    try:
        cursor.execute("SELECT id, id_academia, usuario_id FROM alunos WHERE id = %s", (aluno_id,))
        aluno_row = cursor.fetchone()
        if not aluno_row:
            flash("Aluno não encontrado.", "danger")
            db.close()
            return redirect(url_for("presencas.registro_presenca", **_redirect_kw()))
        if academia_id and aluno_row.get("id_academia") != academia_id:
            flash("Aluno não pertence a esta academia.", "danger")
            db.close()
            return redirect(url_for("presencas.registro_presenca", **_redirect_kw()))

        if academia_id:
            cursor.execute(
                "SELECT TurmaID FROM turmas WHERE TurmaID = %s AND id_academia = %s LIMIT 1",
                (turma_id, academia_id),
            )
            if not cursor.fetchone():
                flash("Turma inválida para esta academia.", "danger")
                db.close()
                return redirect(url_for("presencas.registro_presenca", **_redirect_kw()))

        nome_resp = getattr(current_user, "nome", None) or ""
        if not obs:
            cursor.execute(
                """DELETE FROM presencas_observacao_aluno
                   WHERE aluno_id = %s AND turma_id = %s AND data_aula = %s AND horario_aula = %s""",
                (aluno_id, turma_id, data_aula, horario_aula),
            )
            flash("Observação individual removida.", "info")
        else:
            cursor.execute(
                """
                INSERT INTO presencas_observacao_aluno
                    (aluno_id, turma_id, data_aula, horario_aula, observacao, responsavel_id, responsavel_nome)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    observacao = VALUES(observacao),
                    responsavel_id = VALUES(responsavel_id),
                    responsavel_nome = VALUES(responsavel_nome),
                    atualizado_em = CURRENT_TIMESTAMP
                """,
                (
                    aluno_id,
                    turma_id,
                    data_aula,
                    horario_aula,
                    obs,
                    current_user.id,
                    nome_resp,
                ),
            )
            flash("Observação salva. Somente este aluno verá no painel dele.", "success")
            aluno_usuario_id = aluno_row.get("usuario_id")
            if aluno_usuario_id and obs:
                try:
                    from utils.push_notifications import enviar_push_usuario
                    nome_prof = getattr(current_user, "nome", "Professor") or "Professor"
                    enviar_push_usuario(
                        aluno_usuario_id,
                        title="Nova observação do professor",
                        body=f"{nome_prof}: {obs[:100]}{'...' if len(obs) > 100 else ''}",
                        url="/aluno/minhas-presencas",
                        tag="observacao",
                    )
                except Exception:
                    pass
        db.commit()
    except Exception as e:
        db.rollback()
        flash(f"Erro ao salvar observação: {e}", "danger")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()

    return redirect(url_for("presencas.registro_presenca", **_redirect_kw()))


# ======================================================
# 🔹 Ata de Presença
# ======================================================
@bp_presencas.route('/ata_presenca', methods=['GET'])
@login_required
def ata_presenca():
    academia_id = _get_academia_filtro_presencas()
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    hoje = datetime.today()
    mes_selecionado = int(request.args.get('mes', hoje.month))
    ano_selecionado = int(request.args.get('ano', hoje.year))
    turma_selecionada = int(request.args.get('turma', 0))

    try:
        if academia_id:
            try:
                cursor.execute("SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome", (academia_id,))
            except Exception:
                cursor.execute("SELECT TurmaID, Nome FROM turmas ORDER BY Nome")
        else:
            cursor.execute("SELECT TurmaID, Nome FROM turmas ORDER BY Nome")
        turmas_raw = cursor.fetchall()
        if modo_professor and ids_turmas_professor:
            turmas_raw = [t for t in turmas_raw if t['TurmaID'] in ids_turmas_professor]
        turmas = {t['TurmaID']: t['Nome'] for t in turmas_raw}
    except Exception:
        turmas = {}

    try:
        if academia_id:
            cursor.execute("SELECT id, nome, TurmaID FROM alunos WHERE id_academia = %s ORDER BY nome", (academia_id,))
        else:
            cursor.execute("SELECT id, nome, TurmaID FROM alunos ORDER BY nome")
        alunos = cursor.fetchall()
        if modo_professor and ids_turmas_professor:
            ph = ",".join(["%s"] * len(ids_turmas_professor))
            ids_list = list(ids_turmas_professor)
            cursor.execute(
                f"""SELECT DISTINCT a.id FROM alunos a
                   WHERE a.TurmaID IN ({ph}) OR a.id IN (SELECT aluno_id FROM aluno_turmas WHERE TurmaID IN ({ph}))""",
                ids_list + ids_list,
            )
            ids_ok = {r["id"] for r in cursor.fetchall()}
            alunos = [a for a in alunos if a["id"] in ids_ok]
    except Exception:
        alunos = []
    alunos_por_turma = {}
    for a in alunos:
        alunos_por_turma.setdefault(a.get('TurmaID'), []).append(a)

    presencas = []
    registros_aula_meta = []
    try:
        query = """
            SELECT p.data_presenca, p.horario_aula, p.aluno_id, p.presente,
                   COALESCE(u.nome, p.responsavel_nome, '-') AS responsavel,
                   COALESCE(p.turma_id, a.TurmaID) AS TurmaID,
                   a.nome AS aluno_nome,
                   a.TurmaID AS turma_origem_id,
                   t_origem.Nome AS turma_origem_nome,
                   p.registrado_em
            FROM presencas p
            JOIN alunos a ON a.id = p.aluno_id
            LEFT JOIN usuarios u ON u.id = p.responsavel_id
            LEFT JOIN turmas t_origem ON t_origem.TurmaID = a.TurmaID
            WHERE YEAR(p.data_presenca) = %s
        """
        params = [ano_selecionado]
        if mes_selecionado != 0:
            query += " AND MONTH(p.data_presenca) = %s"
            params.append(mes_selecionado)
        if turma_selecionada != 0:
            query += " AND COALESCE(p.turma_id, a.TurmaID) = %s"
            params.append(turma_selecionada)
        if modo_professor and ids_turmas_professor:
            ph = ",".join(["%s"] * len(ids_turmas_professor))
            ids_list = list(ids_turmas_professor)
            query += f" AND COALESCE(p.turma_id, a.TurmaID) IN ({ph})"
            params.extend(ids_list)
        if academia_id:
            query += " AND a.id_academia = %s"
            params.append(academia_id)
        query += " ORDER BY p.data_presenca, TurmaID, p.horario_aula"
        cursor.execute(query, tuple(params))
        presencas = cursor.fetchall()
    except Exception as e:
        flash(f"Erro ao carregar presenças: {e}", "danger")

    try:
        query_meta = """
            SELECT turma_id, data_aula, horario_aula, observacao, plano_aula_texto,
                   plano_aula_arquivo, plano_aula_arquivo_original
            FROM registros_aula_presenca
            WHERE YEAR(data_aula) = %s
        """
        params_meta = [ano_selecionado]
        if mes_selecionado != 0:
            query_meta += " AND MONTH(data_aula) = %s"
            params_meta.append(mes_selecionado)
        if turma_selecionada != 0:
            query_meta += " AND turma_id = %s"
            params_meta.append(turma_selecionada)
        if modo_professor and ids_turmas_professor:
            ph = ",".join(["%s"] * len(ids_turmas_professor))
            ids_list = list(ids_turmas_professor)
            query_meta += f" AND turma_id IN ({ph})"
            params_meta.extend(ids_list)
        if academia_id:
            query_meta += " AND academia_id = %s"
            params_meta.append(academia_id)
        query_meta += " ORDER BY data_aula, turma_id, horario_aula"
        cursor.execute(query_meta, tuple(params_meta))
        registros_aula_meta = cursor.fetchall() or []
    except Exception:
        registros_aula_meta = []

    presencas_avulsas_rows = []
    try:
        _garantir_tabela_presencas_avulsas(cursor)
        db.commit()
    except Exception:
        db.rollback()
    try:
        query_av = """
            SELECT id, turma_id, data_aula, horario_aula, nome, foto, presente,
                   COALESCE(responsavel_nome, '-') AS responsavel, criado_em
            FROM presencas_avulsas
            WHERE YEAR(data_aula) = %s
        """
        params_av = [ano_selecionado]
        if mes_selecionado != 0:
            query_av += " AND MONTH(data_aula) = %s"
            params_av.append(mes_selecionado)
        if turma_selecionada != 0:
            query_av += " AND turma_id = %s"
            params_av.append(turma_selecionada)
        if modo_professor and ids_turmas_professor:
            ph = ",".join(["%s"] * len(ids_turmas_professor))
            ids_list = list(ids_turmas_professor)
            query_av += f" AND turma_id IN ({ph})"
            params_av.extend(ids_list)
        if academia_id:
            query_av += " AND academia_id = %s"
            params_av.append(academia_id)
        query_av += " ORDER BY data_aula, turma_id, horario_aula, nome"
        cursor.execute(query_av, tuple(params_av))
        presencas_avulsas_rows = cursor.fetchall() or []
    except Exception:
        presencas_avulsas_rows = []

    db.close()

    presencas_por_data = {}
    for p in presencas:
        dp = p.get('data_presenca')
        if not dp:
            continue
        data_str = dp.strftime("%d/%m/%Y") if hasattr(dp, 'strftime') else str(dp)
        turma_id = p.get('TurmaID')
        horario_valor = p.get("horario_aula")
        horario_str = (
            horario_valor.strftime("%H:%M")
            if hasattr(horario_valor, "strftime")
            else str(horario_valor or "00:00:00")[:5]
        )
        horario_token = horario_str.replace(":", "")
        registro_key = f"{turma_id}_{horario_token}"
        if data_str not in presencas_por_data:
            presencas_por_data[data_str] = {}
        if registro_key not in presencas_por_data[data_str]:
            presencas_por_data[data_str][registro_key] = {
                'turma_id': turma_id,
                'horario_aula': horario_str,
                'presentes': [],
                'responsavel': p.get('responsavel', '-'),
                'registros_em': [],
                'alunos': [],
                'observacao': None,
                'plano_aula_texto': None,
                'plano_aula_arquivo': None,
                'plano_aula_arquivo_original': None,
            }
        # Garante presença de alunos registrados na chamada,
        # inclusive alunos de outras turmas.
        alunos_registro = presencas_por_data[data_str][registro_key]['alunos']
        ids_no_registro = {a.get("id") for a in alunos_registro}
        aluno_id = p.get('aluno_id')
        if aluno_id and aluno_id not in ids_no_registro:
            turma_origem_id = p.get("turma_origem_id")
            turma_ata_id = turma_id
            alunos_registro.append({
                "id": aluno_id,
                "nome": p.get("aluno_nome"),
                "aluno_outra_turma": bool(
                    turma_origem_id and turma_ata_id and int(turma_origem_id) != int(turma_ata_id)
                ),
                "turma_origem_nome": p.get("turma_origem_nome"),
            })
        if p.get('presente') == 1:
            presencas_por_data[data_str][registro_key]['presentes'].append(p.get('aluno_id'))
        reg_em = p.get('registrado_em')
        if reg_em:
            presencas_por_data[data_str][registro_key]['registros_em'].append(reg_em)

    for av in presencas_avulsas_rows:
        dp = av.get("data_aula")
        if not dp:
            continue
        data_str = dp.strftime("%d/%m/%Y") if hasattr(dp, "strftime") else str(dp)
        turma_id = av.get("turma_id")
        horario_valor = av.get("horario_aula")
        horario_str = (
            horario_valor.strftime("%H:%M")
            if hasattr(horario_valor, "strftime")
            else str(horario_valor or "00:00:00")[:5]
        )
        horario_token = horario_str.replace(":", "")
        registro_key = f"{turma_id}_{horario_token}"
        if data_str not in presencas_por_data:
            presencas_por_data[data_str] = {}
        if registro_key not in presencas_por_data[data_str]:
            presencas_por_data[data_str][registro_key] = {
                "turma_id": turma_id,
                "horario_aula": horario_str,
                "presentes": [],
                "responsavel": av.get("responsavel", "-"),
                "registros_em": [],
                "alunos": [],
                "observacao": None,
                "plano_aula_texto": None,
                "plano_aula_arquivo": None,
                "plano_aula_arquivo_original": None,
            }
        reg = presencas_por_data[data_str][registro_key]
        if av.get("criado_em"):
            reg.setdefault("registros_em", [])
            reg["registros_em"].append(av["criado_em"])
        av_key = f"avulso_{av['id']}"
        alunos_registro = reg["alunos"]
        ids_no_registro = {a.get("id") for a in alunos_registro}
        if av_key not in ids_no_registro:
            alunos_registro.append(
                {
                    "id": av_key,
                    "nome": av.get("nome") or "",
                    "foto": av.get("foto"),
                    "presenca_avulsa": True,
                    "aluno_outra_turma": False,
                }
            )
        if av.get("presente") == 1 and av_key not in reg["presentes"]:
            reg["presentes"].append(av_key)

    # Enriquecer registros com observação/plano da aula
    for meta in registros_aula_meta:
        data_meta = meta.get("data_aula")
        if not data_meta:
            continue
        data_str = data_meta.strftime("%d/%m/%Y") if hasattr(data_meta, "strftime") else str(data_meta)
        turma_id = meta.get("turma_id")
        horario_valor = meta.get("horario_aula")
        horario_str = (
            horario_valor.strftime("%H:%M")
            if hasattr(horario_valor, "strftime")
            else str(horario_valor or "00:00:00")[:5]
        )
        horario_token = horario_str.replace(":", "")
        registro_key = f"{turma_id}_{horario_token}"
        if data_str not in presencas_por_data:
            presencas_por_data[data_str] = {}
        if registro_key not in presencas_por_data[data_str]:
            presencas_por_data[data_str][registro_key] = {
                'turma_id': turma_id,
                'horario_aula': horario_str,
                'presentes': [],
                'responsavel': '-',
                'registros_em': [],
                'alunos': [],
                'observacao': None,
                'plano_aula_texto': None,
                'plano_aula_arquivo': None,
                'plano_aula_arquivo_original': None,
            }
        reg = presencas_por_data[data_str][registro_key]
        reg['observacao'] = meta.get("observacao")
        reg['plano_aula_texto'] = meta.get("plano_aula_texto")
        reg['plano_aula_arquivo'] = meta.get("plano_aula_arquivo")
        reg['plano_aula_arquivo_original'] = meta.get("plano_aula_arquivo_original")
    for data_str, turmas_d in presencas_por_data.items():
        for tid, reg in turmas_d.items():
            reg["abertura_registro"] = min(reg["registros_em"]) if reg.get("registros_em") else None
            reg.pop("registros_em", None)
            try:
                reg["alunos"].sort(key=lambda x: ((x.get("nome") or "").lower(), str(x.get("id"))))
            except (TypeError, AttributeError):
                pass

    presencas_por_mes = {}
    for data, turmas_dict in presencas_por_data.items():
        mes_ano = data[-7:] if len(data) >= 7 else data
        if mes_ano not in presencas_por_mes:
            presencas_por_mes[mes_ano] = {}
        presencas_por_mes[mes_ano][data] = turmas_dict

    try:
        def _parse_mes_ano(s):
            partes = s.split('/')
            if len(partes) >= 2:
                m, a = int(partes[0]) if partes[0].isdigit() else 1, int(partes[-1]) if partes[-1].isdigit() else 2025
                return (a, m)
            return (2025, 1)
        presencas_por_mes = dict(sorted(presencas_por_mes.items(), key=lambda x: _parse_mes_ano(x[0])))
    except (ValueError, TypeError, IndexError):
        pass

    if modo_professor:
        back_url = url_for("professor.painel_professor")
    else:
        back_url = url_for("presencas.painel_presenca", academia_id=academia_id) if academia_id else url_for("presencas.painel_presenca")
    return render_template('ata_presenca.html',
                            presencas_por_mes=presencas_por_mes,
                            turmas=turmas,
                            mes=mes_selecionado,
                            ano=ano_selecionado,
                            turma_id=turma_selecionada,
                            hoje=hoje,
                            back_url=back_url,
                            academia_id=academia_id)

# ======================================================
# 🔹 Histórico de Presença (Lista de Cards)
# ======================================================
@bp_presencas.route('/historico_presenca_lista')
@login_required
def historico_presenca_lista():
    academia_id = _get_academia_filtro_presencas()
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        if academia_id:
            cursor.execute("SELECT id, nome FROM alunos WHERE id_academia = %s ORDER BY nome", (academia_id,))
        else:
            cursor.execute("SELECT id, nome FROM alunos ORDER BY nome")
        alunos = cursor.fetchall()
        if modo_professor and ids_turmas_professor:
            ph = ",".join(["%s"] * len(ids_turmas_professor))
            ids_list = list(ids_turmas_professor)
            cursor.execute(
                f"""SELECT DISTINCT a.id FROM alunos a
                   WHERE a.TurmaID IN ({ph}) OR a.id IN (SELECT aluno_id FROM aluno_turmas WHERE TurmaID IN ({ph}))""",
                ids_list + ids_list,
            )
            ids_ok = {r["id"] for r in cursor.fetchall()}
            alunos = [a for a in alunos if a["id"] in ids_ok]
    except Exception:
        alunos = []
    db.close()

    hoje = datetime.today()
    if modo_professor:
        back_url = url_for("professor.painel_professor")
    else:
        back_url = url_for("presencas.painel_presenca", academia_id=academia_id) if academia_id else url_for("presencas.painel_presenca")
    return render_template('historico_presenca_lista.html', alunos=alunos, hoje=hoje, back_url=back_url, academia_id=academia_id)

# ======================================================
# 🔹 Histórico de Presença (Endpoint AJAX)
# ======================================================
@bp_presencas.route('/historico_presenca_ajax/<int:aluno_id>')
@login_required
def historico_presenca_ajax(aluno_id):
    academia_id = _get_academia_filtro_presencas()
    modo_professor = session.get("modo_painel") == "professor"
    ids_turmas_professor = set()
    if modo_professor:
        ids_prof = _get_todos_professor_ids()
        ids_turmas_professor = _get_ids_turmas_professor(ids_prof)

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id, id_academia, TurmaID FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()
    if not aluno:
        db.close()
        return "<p class='alert alert-warning p-2 small'>Aluno não encontrado.</p>"
    if academia_id and aluno.get("id_academia") != academia_id:
        db.close()
        return "<p class='alert alert-warning p-2 small'>Acesso negado.</p>"
    if modo_professor and ids_turmas_professor:
        aluno_turma_ok = aluno.get("TurmaID") in ids_turmas_professor
        if not aluno_turma_ok:
            cursor.execute(
                "SELECT 1 FROM aluno_turmas WHERE aluno_id = %s AND TurmaID IN (%s)" % (aluno_id, ",".join(["%s"] * len(ids_turmas_professor))),
                tuple(ids_turmas_professor),
            )
            aluno_turma_ok = cursor.fetchone() is not None
        if not aluno_turma_ok:
            db.close()
            return "<p class='alert alert-warning p-2 small'>Acesso negado.</p>"

    mes = int(request.args.get('mes', 0))
    ano = int(request.args.get('ano', datetime.today().year))

    # Seleciona presenças do aluno filtrando mês/ano
    if mes == 0:
        cursor.execute("""
            SELECT data_presenca, presente
            FROM presencas
            WHERE aluno_id=%s AND YEAR(data_presenca)=%s
            ORDER BY data_presenca
        """, (aluno_id, ano))
    else:
        cursor.execute("""
            SELECT data_presenca, presente
            FROM presencas
            WHERE aluno_id=%s AND MONTH(data_presenca)=%s AND YEAR(data_presenca)=%s
            ORDER BY data_presenca
        """, (aluno_id, mes, ano))

    registros = cursor.fetchall()
    db.close()

    total = len(registros)
    total_presenca = sum(1 for r in registros if r.get('presente') == 1)
    total_falta = total - total_presenca
    percentual_presenca = round((total_presenca / total * 100), 1) if total > 0 else 0

    # Monta HTML do resumo (será inserido no card)
    html = f"""
    <div class="historico-aluno p-3 border rounded bg-light">
      <ul class="list-group list-group-flush">
        <li class="list-group-item"><strong>Total de Aulas:</strong> {total}</li>
        <li class="list-group-item"><strong>Total de Presenças:</strong> {total_presenca}</li>
        <li class="list-group-item"><strong>Total de Faltas:</strong> {total_falta}</li>
        <li class="list-group-item"><strong>Porcentagem de Presença:</strong> {percentual_presenca}%</li>
      </ul>
    </div>
    """

    return html


@bp_presencas.route('/buscar_alunos_outra_turma_ajax', methods=['GET'])
@login_required
def buscar_alunos_outra_turma_ajax():
    turma_id = request.args.get("turma_id", type=int)
    termo = (request.args.get("q") or "").strip()
    if not turma_id or len(termo) < 2:
        return jsonify([])

    academia_id = _get_academia_filtro_presencas()

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        params = [f"%{termo}%", turma_id, turma_id]
        query = """
            SELECT a.id, a.nome, t_origem.Nome AS turma_origem_nome
            FROM alunos a
            LEFT JOIN turmas t_origem ON t_origem.TurmaID = a.TurmaID
            WHERE a.nome LIKE %s
              AND (a.ativo IS NULL OR a.ativo = 1)
              AND NOT (
                  EXISTS (
                      SELECT 1 FROM aluno_turmas at
                      WHERE at.aluno_id = a.id AND at.TurmaID = %s
                  )
                  OR a.TurmaID = %s
              )
        """
        if academia_id:
            query += " AND a.id_academia = %s"
            params.append(academia_id)
        query += " ORDER BY a.nome LIMIT 40"

        cursor.execute(query, tuple(params))
        resultados = cursor.fetchall() or []
        payload = [
            {
                "id": r.get("id"),
                "nome": r.get("nome"),
                "turma_origem_nome": r.get("turma_origem_nome") or "",
            }
            for r in resultados
        ]
        return jsonify(payload)
    except Exception:
        return jsonify([])
    finally:
        db.close()


@bp_presencas.route('/buscar_alunos_outra_academia_ajax', methods=['GET'])
@login_required
def buscar_alunos_outra_academia_ajax():
    """Busca alunos para incluir na chamada (outra turma e/ou outra academia), exceto quem já é da turma desta aula."""
    turma_id = request.args.get("turma_id", type=int)
    termo = (request.args.get("q") or "").strip()
    if not turma_id or len(termo) < 2:
        return jsonify([])

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # Não excluir por id_academia: alunos da mesma academia em outra turma devem aparecer.
        # Excluir só quem já está matriculado nesta turma (aluno_turmas ou TurmaID legado).
        # ativo: mesmo critério da lista de alunos (NULL = ativo).
        params = [f"%{termo}%", turma_id, turma_id]
        query = """
            SELECT a.id, a.nome, a.foto,
                   ac.nome AS academia_nome,
                   t.Nome  AS turma_nome
            FROM alunos a
            LEFT JOIN academias ac ON ac.id = a.id_academia
            LEFT JOIN turmas t     ON t.TurmaID = a.TurmaID
            WHERE a.nome LIKE %s
              AND (a.ativo IS NULL OR a.ativo = 1)
              AND NOT (
                  EXISTS (
                      SELECT 1 FROM aluno_turmas at
                      WHERE at.aluno_id = a.id AND at.TurmaID = %s
                  )
                  OR a.TurmaID = %s
              )
            ORDER BY ac.nome, a.nome
            LIMIT 20
        """
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall() or []
        return jsonify([
            {
                "id": r["id"],
                "nome": r["nome"],
                "foto": r["foto"] or "",
                "academia_nome": r["academia_nome"] or "",
                "turma_nome": r["turma_nome"] or "",
            }
            for r in rows
        ])
    except Exception:
        return jsonify([])
    finally:
        cursor.close()
        db.close()