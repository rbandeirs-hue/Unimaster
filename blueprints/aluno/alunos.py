# ======================================================
# 🧩 Blueprint: Alunos (CRUD) - Versão RBAC + Modalidades N:N
# ======================================================

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    Blueprint,
    current_app,
    session,
    jsonify,
)
from flask_login import login_required, current_user
from config import get_db_connection
from utils.modalidades import filtro_visibilidade_sql
from utils.upload_seguro import validar_upload, nome_seguro, UploadInvalido
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import os
import base64
import unicodedata
from urllib.parse import urlparse

bp_alunos = Blueprint("alunos", __name__, url_prefix="/alunos")


def _get_academias_ids():
    """IDs de academias acessíveis (prioridade: usuarios_academias, alinhado ao gerenciamento)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        # Modo painel Associação: gestor vê todas as academias (lista global de alunos + filtro)
        if session.get("modo_painel") == "associacao" and current_user.has_role(
            "gestor_associacao"
        ):
            cur.execute("SELECT id FROM academias ORDER BY nome")
            ids = [r["id"] for r in cur.fetchall()]
            cur.close()
            conn.close()
            return ids
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas:
            cur.close()
            conn.close()
            return vinculadas
        # Modo academia: gestor_academia/professor só veem academias de usuarios_academias (não id_academia)
        if session.get("modo_painel") == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
            cur.close()
            conn.close()
            return []
        ids = []
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
            ids = []
        cur.close()
        conn.close()
        return ids
    except Exception:
        return []


def _idade_anos_completa(data_nascimento):
    """Idade em anos completos (mesma regra da matrícula em turmas)."""
    if not data_nascimento:
        return None
    if isinstance(data_nascimento, str):
        try:
            data_nascimento = datetime.strptime(str(data_nascimento)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
    if isinstance(data_nascimento, datetime):
        data_nascimento = data_nascimento.date()
    if not isinstance(data_nascimento, date):
        return None
    hoje = date.today()
    idade = hoje.year - data_nascimento.year
    if (hoje.month, hoje.day) < (data_nascimento.month, data_nascimento.day):
        idade -= 1
    return idade if idade >= 0 else None


def _pode_gerenciar_aluno_academia(id_academia):
    if not id_academia:
        return False
    if current_user.has_role("admin"):
        return True
    ids = set(_get_academias_ids() or [])
    try:
        iac = int(id_academia)
    except (TypeError, ValueError):
        return False
    if iac in ids:
        return True
    if session.get("modo_painel") == "academia":
        try:
            uid_acad = int(getattr(current_user, "id_academia", None) or 0)
        except (TypeError, ValueError):
            uid_acad = 0
        if uid_acad == iac and (
            current_user.has_role("gestor_academia") or current_user.has_role("professor")
        ):
            return True
    return False


def _permite_modal_matricula_turma():
    """Lista de alunos: modal de matrícula só no modo academia (gestor/professor) ou admin."""
    if current_user.has_role("admin"):
        return True
    return session.get("modo_painel") == "academia" and (
        current_user.has_role("gestor_academia") or current_user.has_role("professor")
    )


def _pode_transferir_aluno_academia_modo_associacao():
    """Transferência entre academias da mesma associação: só no painel modo associação."""
    if session.get("modo_painel") != "associacao":
        return False
    return current_user.has_role("gestor_associacao") or current_user.has_role("admin")


def _mensalidade_quitada_por_desconto_integral(ma_sim, status_pagamento):
    """True quando o desconto cobre o valor integral da parcela (nada a cobrar da mensalidade)."""
    if (status_pagamento or "").lower() == "pendente_aprovacao":
        return False
    if not ma_sim.get("tem_desconto"):
        return False
    try:
        vf = round(float(ma_sim.get("valor_final") or 0), 2)
        vi = round(float(ma_sim.get("valor_integral") or 0), 2)
        vd = round(float(ma_sim.get("valor_desconto") or 0), 2)
    except (TypeError, ValueError):
        return False
    if vf <= 0:
        return True
    if vi > 0 and vd + 0.009 >= vi:
        return True
    return False


def _formatar_data_pg_br(val):
    """Normaliza data vinda do MySQL (date/datetime/str) para dd/mm/aaaa."""
    if val is None:
        return "—"
    fn = getattr(val, "strftime", None)
    if callable(fn):
        try:
            return val.strftime("%d/%m/%Y")
        except Exception:
            pass
    s = str(val).strip()
    if len(s) >= 10 and s[4:5] == "-":
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            pass
    return s[:10] if len(s) >= 10 else (s or "—")


def _receitas_linhas_por_mensalidade_ids(db, ma_ids):
    """
    Monta dict mensalidade_aluno.id -> [{forma, valor, data}, ...] a partir de receitas.
    Tenta SELECTs em cascata se colunas opcionais não existirem no banco.
    """
    out = {}
    if not ma_ids:
        return out
    try:
        ma_ids = [int(x) for x in ma_ids]
    except (TypeError, ValueError):
        return out
    ma_ids = list(dict.fromkeys(ma_ids))
    ph = ", ".join(["%s"] * len(ma_ids))
    tpl = tuple(ma_ids)
    sql_attempts = [
        f"""
        SELECT r.id_mensalidade_aluno, r.valor, r.data,
               r.id_forma_pagamento, r.descricao
        FROM receitas r
        WHERE r.id_mensalidade_aluno IN ({ph})
        ORDER BY r.id_mensalidade_aluno, r.id
        """,
        f"""
        SELECT r.id_mensalidade_aluno, r.valor, r.data, r.descricao
        FROM receitas r
        WHERE r.id_mensalidade_aluno IN ({ph})
        ORDER BY r.id_mensalidade_aluno, r.id
        """,
        f"""
        SELECT r.id_mensalidade_aluno, r.valor, r.data
        FROM receitas r
        WHERE r.id_mensalidade_aluno IN ({ph})
        ORDER BY r.id_mensalidade_aluno, r.id
        """,
    ]
    _rec_rows = []
    cur = db.cursor(dictionary=True)
    try:
        for sql in sql_attempts:
            try:
                cur.execute(sql, tpl)
                _rec_rows = cur.fetchall()
                break
            except Exception:
                continue
    finally:
        cur.close()
    _fp_ids = set()
    for _rw in _rec_rows:
        _fid = _rw.get("id_forma_pagamento")
        if _fid is not None:
            try:
                _fp_ids.add(int(_fid))
            except (TypeError, ValueError):
                pass
    _nome_fp = {}
    if _fp_ids:
        _fp_ph = ", ".join(["%s"] * len(_fp_ids))
        cur2 = db.cursor(dictionary=True)
        try:
            cur2.execute(
                f"SELECT id, nome FROM formas_pagamento WHERE id IN ({_fp_ph})",
                tuple(_fp_ids),
            )
            for _fr in cur2.fetchall():
                try:
                    _iid = int(_fr.get("id"))
                    _nome_fp[_iid] = (_fr.get("nome") or "").strip()
                except (TypeError, ValueError):
                    pass
        finally:
            cur2.close()
    for _r in _rec_rows:
        _mid_raw = _r.get("id_mensalidade_aluno")
        if _mid_raw is None:
            continue
        try:
            _mid = int(_mid_raw)
        except (TypeError, ValueError):
            continue
        dr = _r.get("data")
        ds = _formatar_data_pg_br(dr)
        vl = float(_r.get("valor") or 0)
        _fid = _r.get("id_forma_pagamento")
        try:
            _fi = int(_fid) if _fid is not None else None
        except (TypeError, ValueError):
            _fi = None
        fn = ""
        if _fi is not None:
            fn = (_nome_fp.get(_fi) or "").strip()
        if not fn:
            dsc = (_r.get("descricao") or "").strip()
            if dsc and len(dsc) > 80:
                dsc = dsc[:77] + "…"
            fn = dsc if dsc else "—"
        out.setdefault(_mid, []).append({"forma": fn, "valor": vl, "data": ds})
    return out


def _agrupar_abertos_por_plano(abertos):
    """Agrupa mensalidades em aberto por plano (mensalidade_id), preservando ordem do vencimento."""
    if not abertos:
        return []
    from collections import OrderedDict

    grupos = OrderedDict()
    for it in abertos:
        mid = it.get("mensalidade_id")
        key = str(mid) if mid is not None else f"_:{(it.get('tipo') or '').strip()}"
        if key not in grupos:
            grupos[key] = {
                "mensalidade_id": mid,
                "plano_nome": it.get("tipo") or "Mensalidade",
                "itens": [],
            }
        grupos[key]["itens"].append(it)
    return list(grupos.values())


# ======================================================
# FUNÇÕES UTILITÁRIAS
# ======================================================

def _eh_responsavel_aluno(cursor, usuario_id, aluno_id):
    """Verifica se o usuário é responsável pelo aluno (via responsavel_alunos)."""
    if not usuario_id or not aluno_id:
        return False
    try:
        cursor.execute(
            "SELECT 1 FROM responsavel_alunos WHERE usuario_id = %s AND aluno_id = %s LIMIT 1",
            (usuario_id, aluno_id),
        )
        return cursor.fetchone() is not None
    except Exception:
        return False


def allowed_file(filename):
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extrair_numero(valor):
    return int("".join(filter(str.isdigit, str(valor)))) if valor else 0


def validar_cpf(cpf):
    """
    Validação de CPF (apenas dígitos).
    """
    if not cpf:
        return False
    cpf = "".join(filter(str.isdigit, str(cpf)))
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    soma = 0
    for i in range(9):
        soma += int(cpf[i]) * (10 - i)
    dig1 = 0 if (soma % 11) < 2 else 11 - (soma % 11)
    if dig1 != int(cpf[9]):
        return False

    soma = 0
    for i in range(10):
        soma += int(cpf[i]) * (11 - i)
    dig2 = 0 if (soma % 11) < 2 else 11 - (soma % 11)
    return dig2 == int(cpf[10])


def parse_carencia(valor):
    if not valor:
        return 0, 0, 0
    texto = str(valor).lower()
    numero = extrair_numero(texto)
    if numero == 0:
        return 0, 0, 0
    if "ano" in texto:
        return numero, 0, 0
    if "mes" in texto:
        return 0, numero, 0
    if "dia" in texto:
        return 0, 0, numero
    return 0, numero, 0


def parse_date(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(valor, fmt).date()
            except Exception:
                continue
    return None


def _clean_str(valor):
    """Retorna None se vazio, 'None', 'null' ou só espaços, senão strip do valor."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s or s.lower() in ("none", "null", "undefined"):
        return None
    return s


def normalizar_cpf(valor):
    if not valor:
        return None
    digits = "".join(filter(str.isdigit, str(valor)))
    if not digits:
        return None
    if len(digits) == 11:
        return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}"
    return str(valor).strip()


def salvar_imagem_base64(data_url, prefix):
    """
    Recebe dataURL (data:image/png;base64,...) e salva em static/uploads.
    Retorna apenas o nome do arquivo (para gravar no banco).
    """
    if not data_url:
        return None

    try:
        if "," in data_url:
            header, encoded = data_url.split(",", 1)
        else:
            encoded = data_url
        img_data = base64.b64decode(encoded)
    except Exception:
        return None

    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
    upload_folder = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(upload_folder, exist_ok=True)
    filepath = os.path.join(upload_folder, filename)

    with open(filepath, "wb") as f:
        f.write(img_data)

    return filename


def salvar_arquivo_upload(file_storage, prefix):
    """Salva foto enviada via input[type=file] — valida extensão + magic bytes."""
    if not file_storage or not file_storage.filename:
        return None
    try:
        ext = validar_upload(file_storage, categorias=["imagem"])
    except UploadInvalido:
        return None
    filename = nome_seguro(prefix, ext)
    upload_folder = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(upload_folder, exist_ok=True)
    file_storage.save(os.path.join(upload_folder, filename))
    return filename


# ======================================================
# 🔹 1. LISTA DE ALUNOS (com RBAC)
# ======================================================


@bp_alunos.route("/mensalidade/<int:ma_id>/pagamento-detalhes", methods=["GET"])
@login_required
def pagamento_detalhes_mensalidade(ma_id):
    """JSON com linhas de receita (modal detalhe pagamento); usa o mesmo critério de acesso da lista."""
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT ma.id, ma.data_pagamento, ma.valor_pago, ma.id_forma_pagamento,
                   m.id_academia AS id_academia_plano, a.id_academia AS id_academia_aluno,
                   ma.data_vencimento
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE ma.id = %s AND ma.status = 'pago'
            """,
            (ma_id,),
        )
        ma = cur.fetchone()
        if not ma:
            return jsonify({"ok": False, "erro": "Não encontrado."}), 404
        idp = ma.get("id_academia_plano")
        ida = ma.get("id_academia_aluno")
        if not (
            _pode_gerenciar_aluno_academia(idp)
            or _pode_gerenciar_aluno_academia(ida)
        ):
            return jsonify({"ok": False, "erro": "Sem permissão."}), 403
        dv = ma.get("data_vencimento")
        competencia = (
            dv.strftime("%m/%Y") if hasattr(dv, "strftime") and dv else ""
        )
        dp = ma.get("data_pagamento")
        data_pagamento_fmt = (
            dp.strftime("%d/%m/%Y") if hasattr(dp, "strftime") and dp else None
        )
        valor_pago = float(ma.get("valor_pago") or 0)
        id_fp = ma.get("id_forma_pagamento")
        forma_resumo = "Várias formas"
        if id_fp is not None:
            try:
                cur.execute(
                    "SELECT nome FROM formas_pagamento WHERE id = %s LIMIT 1",
                    (int(id_fp),),
                )
                nr = cur.fetchone()
                nn = (nr.get("nome") if nr else None) or ""
                forma_resumo = nn.strip() if nn.strip() else "—"
            except Exception:
                forma_resumo = "—"
        det = _receitas_linhas_por_mensalidade_ids(db, [ma_id])
        linhas = det.get(int(ma_id)) or []
        return jsonify(
            {
                "ok": True,
                "linhas": linhas,
                "competencia": competencia,
                "data_pagamento": data_pagamento_fmt,
                "valor_pago": round(valor_pago, 2),
                "forma_resumo": forma_resumo,
            }
        )
    finally:
        cur.close()
        db.close()


@bp_alunos.route("/lista_alunos", methods=["GET"])
@login_required
def lista_alunos():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    busca = request.args.get("busca", "").strip()
    graduacao_id = request.args.get("graduacao_id", type=int)
    peso_min = request.args.get("peso_min", type=float)
    peso_max = request.args.get("peso_max", type=float)
    filtro_ativo = (request.args.get("filtro_ativo") or "ativo").strip().lower()
    if filtro_ativo not in ("todos", "ativo", "inativo"):
        filtro_ativo = "ativo"
    # Filtros adicionais (modo academia): ano de nascimento (ou período), turma e sexo
    ano_nasc_min = request.args.get("ano_nasc_min", type=int)
    ano_nasc_max = request.args.get("ano_nasc_max", type=int)
    turma_filtro = request.args.get("turma_id", type=int)
    sexo_filtro = (request.args.get("sexo") or "").strip().upper()
    if sexo_filtro not in ("M", "F", "O"):
        sexo_filtro = ""
    # Filtro por modalidade: id da modalidade, ou -1 para "Sem modalidade"
    modalidade_filtro = request.args.get("modalidade_id", type=int)
    hoje = date.today()

    # Base
    query = """
        SELECT a.*,
               ac.nome  AS academia_nome,
               ass.nome AS associacao_nome,
               fed.nome AS federacao_nome,
               g.faixa  AS faixa,
               g.graduacao AS graduacao,
               t.Nome   AS turma_nome
        FROM alunos a
        LEFT JOIN academias ac   ON a.id_academia   = ac.id
        LEFT JOIN associacoes ass ON a.id_associacao = ass.id
        LEFT JOIN federacoes fed ON a.id_federacao = fed.id
        LEFT JOIN graduacao g    ON a.graduacao_id = g.id
        LEFT JOIN turmas t       ON a.TurmaID      = t.TurmaID
        WHERE 1=1
    """
    params = []

    # ======================================================
    # 🔐 RBAC — CONTROLE DE ACESSO POR ROLE
    # ======================================================
    ids_acessiveis = _get_academias_ids()
    modo = session.get("modo_painel") or ""
    # academia_id na URL: "" ou ausente = Todas; número = filtrar
    raw_academia = request.args.get("academia_id")
    academia_filtro = None
    if raw_academia is not None and str(raw_academia).strip():
        try:
            academia_filtro = int(raw_academia)
        except (ValueError, TypeError):
            academia_filtro = None
    elif raw_academia is None:
        academia_filtro = session.get("academia_gerenciamento_id")
    if raw_academia is not None and not str(raw_academia).strip():
        session.pop("academia_gerenciamento_id", None)
        session.pop("finance_academia_id", None)
    # Se academia selecionada e válida, filtra por ela
    if academia_filtro and academia_filtro in ids_acessiveis:
        session["academia_gerenciamento_id"] = academia_filtro
        session["finance_academia_id"] = academia_filtro
        query += " AND a.id_academia = %s"
        params.append(academia_filtro)
    # SUPERUSER (admin) → vê tudo (só quando não tem filtro de academia)
    elif current_user.has_role("admin"):
        pass

    # Painel Associação (gestor): mesma visão global — todos os alunos do sistema
    elif modo == "associacao" and current_user.has_role("gestor_associacao"):
        pass

    # FEDERAÇÃO → vê alunos das academias da federação; só alunos com modalidade ofertada pela fed E associação
    elif current_user.has_role("gestor_federacao"):
        fid = getattr(current_user, "id_federacao", 0)
        query += """
            AND a.id_academia IN (
                SELECT ac2.id FROM academias ac2
                JOIN associacoes ass2 ON ass2.id = ac2.id_associacao
                WHERE ass2.id_federacao = %s
            )
            AND EXISTS (
                SELECT 1 FROM aluno_modalidades am
                INNER JOIN federacao_modalidades fm ON fm.modalidade_id = am.modalidade_id AND fm.federacao_id = %s
                INNER JOIN associacao_modalidades asm ON asm.modalidade_id = am.modalidade_id
                    AND asm.associacao_id = (SELECT id_associacao FROM academias WHERE id = a.id_academia LIMIT 1)
                WHERE am.aluno_id = a.id
            )
        """
        params.append(fid)
        params.append(fid)

    # ASSOCIAÇÃO → só alunos com pelo menos uma modalidade que a associação oferta (exclui sem modalidade)
    elif current_user.has_role("gestor_associacao"):
        aid = getattr(current_user, "id_associacao", 0)
        query += """
            AND a.id_academia IN (
                SELECT id FROM academias WHERE id_associacao = %s
            )
            AND EXISTS (SELECT 1 FROM aluno_modalidades WHERE aluno_id = a.id)
            AND EXISTS (
                SELECT 1 FROM aluno_modalidades am
                INNER JOIN associacao_modalidades asm ON asm.modalidade_id = am.modalidade_id AND asm.associacao_id = %s
                WHERE am.aluno_id = a.id
            )
        """
        params.append(aid)
        params.append(aid)

    # ACADEMIA / PROFESSOR → vê alunos da própria academia
    elif current_user.has_role("gestor_academia") or current_user.has_role("professor"):
        query += " AND a.id_academia = %s"
        params.append(getattr(current_user, "id_academia", 0))

    # ALUNO → vê apenas ele mesmo (assumindo que current_user.id == alunos.id ou há um vínculo)
    elif current_user.has_role("aluno"):
        query += " AND a.id = %s"
        params.append(current_user.id)

    # Filtro de busca por nome
    if busca:
        query += " AND a.nome LIKE %s"
        params.append(f"%{busca}%")

    # Filtros dinâmicos (ano de nascimento, graduação, peso)
    if graduacao_id is not None:
        query += " AND a.graduacao_id = %s"
        params.append(graduacao_id)

    # Filtro por ano de nascimento (único ou período: de X a Y)
    if ano_nasc_min is not None and ano_nasc_max is not None:
        if ano_nasc_min > ano_nasc_max:
            ano_nasc_min, ano_nasc_max = ano_nasc_max, ano_nasc_min
        query += " AND YEAR(a.data_nascimento) BETWEEN %s AND %s"
        params.extend([ano_nasc_min, ano_nasc_max])
    elif ano_nasc_min is not None:
        query += " AND YEAR(a.data_nascimento) >= %s"
        params.append(ano_nasc_min)
    elif ano_nasc_max is not None:
        query += " AND YEAR(a.data_nascimento) <= %s"
        params.append(ano_nasc_max)

    # Filtro por turma
    if turma_filtro is not None:
        query += " AND a.TurmaID = %s"
        params.append(turma_filtro)

    # Filtro por sexo
    if sexo_filtro:
        query += " AND a.sexo = %s"
        params.append(sexo_filtro)

    if peso_min is not None and peso_max is not None:
        query += " AND a.peso IS NOT NULL AND a.peso BETWEEN %s AND %s"
        params.extend([peso_min, peso_max])
    elif peso_min is not None:
        query += " AND a.peso IS NOT NULL AND a.peso >= %s"
        params.append(peso_min)
    elif peso_max is not None:
        query += " AND a.peso IS NOT NULL AND a.peso <= %s"
        params.append(peso_max)

    # Filtro de status (padrão: ativos)
    if filtro_ativo == "ativo":
        query += " AND COALESCE(a.ativo, 1) = 1"
    elif filtro_ativo == "inativo":
        query += " AND COALESCE(a.ativo, 1) = 0"

    query += " ORDER BY a.nome"

    cursor.execute(query, tuple(params))
    alunos = cursor.fetchall()

    # Carrega faixas
    cursor.execute("SELECT * FROM graduacao ORDER BY COALESCE(NULLIF(ordem,0), id), id")
    faixas = cursor.fetchall()

    # Carrega turmas para o filtro (modo academia: turmas da academia selecionada/própria)
    turmas_filtro = []
    try:
        _acad_turmas_id = None
        if academia_filtro and academia_filtro in ids_acessiveis:
            _acad_turmas_id = academia_filtro
        elif modo == "academia":
            _acad_turmas_id = getattr(current_user, "id_academia", None)
        if _acad_turmas_id:
            cursor.execute(
                "SELECT TurmaID AS turma_id, Nome AS turma_nome FROM turmas WHERE id_academia = %s ORDER BY Nome",
                (_acad_turmas_id,),
            )
            turmas_filtro = cursor.fetchall()
    except Exception:
        turmas_filtro = []

    # Carrega categorias da tabela categorias
    cursor.execute(
        """
        SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max
        FROM categorias
        ORDER BY id
        """
    )
    categorias = cursor.fetchall()

    # Aprovação especial por professor
    cursor.execute(
        """
        SELECT aluno_id, faixa_aprovada, aprovado_por, data_aprovacao
        FROM aprovacoes_faixa_professor
        """
    )
    aprovacoes = {a["aluno_id"]: a for a in cursor.fetchall()}

    # Turmas de Judô (modalidade_id=1) para cálculo de frequência
    try:
        cursor.execute(
            "SELECT turma_id FROM turma_modalidades WHERE modalidade_id = 1"
        )
        turmas_judo_ids = [r["turma_id"] for r in cursor.fetchall()]
    except Exception:
        turmas_judo_ids = []

    # Carrega modalidades de todos os alunos (N:N)
    aluno_ids = [a["id"] for a in alunos]
    modalidades_por_aluno = {}
    modalidades_filtro = []
    tem_sem_modalidade = False
    mensalidade_status_por_aluno = {}
    mensalidade_detalhes_por_aluno = {}
    pacotes_ativos_por_aluno = {}
    turmas_nn_por_aluno = {}
    if aluno_ids:
        placeholders = ", ".join(["%s"] * len(aluno_ids))
        cursor.execute(
            f"""
            SELECT am.aluno_id, m.id, m.nome
            FROM aluno_modalidades am
            JOIN modalidade m ON m.id = am.modalidade_id
            WHERE am.aluno_id IN ({placeholders})
            ORDER BY m.nome
            """,
            tuple(aluno_ids),
        )
        for row in cursor.fetchall():
            modalidades_por_aluno.setdefault(row["aluno_id"], []).append(
                {"id": row["id"], "nome": row["nome"]}
            )

        # Modalidades presentes nos alunos carregados (opções do filtro de modalidade)
        _mods_vistas = {}
        for _lst in modalidades_por_aluno.values():
            for _m in _lst:
                _mods_vistas.setdefault(_m["id"], _m["nome"])
        modalidades_filtro = sorted(
            ({"id": mid, "nome": nome} for mid, nome in _mods_vistas.items()),
            key=lambda x: (x["nome"] or "").lower(),
        )
        tem_sem_modalidade = any(not modalidades_por_aluno.get(aid) for aid in aluno_ids)

        # Status financeiro por aluno (lista de alunos no modo academia)
        # Regra:
        # - possui_mensalidade: há ao menos uma cobrança (exceto cancelada)
        # - atrasada: existe cobrança atrasada/pendente vencida
        try:
            cursor.execute(
                f"""
                SELECT
                    ma.aluno_id,
                    COUNT(*) AS total_cobrancas,
                    SUM(
                        CASE
                            WHEN ma.status = 'atrasado'
                              OR (ma.status = 'pendente' AND ma.data_vencimento < CURDATE())
                            THEN 1 ELSE 0
                        END
                    ) AS total_atrasadas
                FROM mensalidade_aluno ma
                WHERE ma.aluno_id IN ({placeholders})
                  AND ma.status <> 'cancelado'
                GROUP BY ma.aluno_id
                """,
                tuple(aluno_ids),
            )
            for row in cursor.fetchall():
                total_cobrancas = int(row.get("total_cobrancas") or 0)
                total_atrasadas = int(row.get("total_atrasadas") or 0)
                mensalidade_status_por_aluno[row["aluno_id"]] = {
                    "tem_mensalidade": total_cobrancas > 0,
                    "atrasada": total_atrasadas > 0,
                }

            _sql_ma_fin = f"""
                SELECT
                    ma.aluno_id,
                    ma.id AS mensalidade_aluno_id,
                    ma.mensalidade_id,
                    ma.valor,
                    ma.data_vencimento,
                    ma.status,
                    ma.status_pagamento,
                    ma.valor_original,
                    ma.desconto_aplicado,
                    ma.id_desconto,
                    COALESCE(ma.remover_juros, 0) AS remover_juros,
                    COALESCE(m.nome, 'Mensalidade') AS tipo_mensalidade,
                    m.id_academia AS id_academia_plano,
                    COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
                    COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
                    COALESCE(m.percentual_juros_dia, 0.033) AS percentual_juros_dia,
                    ma.data_pagamento,
                    ma.valor_pago,
                    ma.id_forma_pagamento,
                    fp.nome AS forma_pagamento_nome
                FROM mensalidade_aluno ma
                LEFT JOIN mensalidades m ON m.id = ma.mensalidade_id
                LEFT JOIN formas_pagamento fp ON fp.id = ma.id_forma_pagamento
                WHERE ma.aluno_id IN ({placeholders})
                  AND ma.status <> 'cancelado'
                ORDER BY ma.aluno_id, ma.data_vencimento
                """
            _sql_ma_fin_basic = f"""
                SELECT
                    ma.aluno_id,
                    ma.id AS mensalidade_aluno_id,
                    ma.mensalidade_id,
                    ma.valor,
                    ma.data_vencimento,
                    ma.status,
                    ma.status_pagamento,
                    ma.valor_original,
                    ma.desconto_aplicado,
                    ma.id_desconto,
                    COALESCE(ma.remover_juros, 0) AS remover_juros,
                    COALESCE(m.nome, 'Mensalidade') AS tipo_mensalidade,
                    m.id_academia AS id_academia_plano,
                    COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
                    COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
                    COALESCE(m.percentual_juros_dia, 0.033) AS percentual_juros_dia
                FROM mensalidade_aluno ma
                LEFT JOIN mensalidades m ON m.id = ma.mensalidade_id
                WHERE ma.aluno_id IN ({placeholders})
                  AND ma.status <> 'cancelado'
                ORDER BY ma.aluno_id, ma.data_vencimento
                """
            try:
                cursor.execute(_sql_ma_fin, tuple(aluno_ids))
                ma_rows = cursor.fetchall()
                _ma_fin_cols = "full"
            except Exception:
                try:
                    cursor.execute(_sql_ma_fin_basic, tuple(aluno_ids))
                    ma_rows = cursor.fetchall()
                    _ma_fin_cols = "basic"
                except Exception:
                    ma_rows = []
                    _ma_fin_cols = "none"

            for row in ma_rows:
                aluno_id = row.get("aluno_id")
                if not aluno_id:
                    continue
                info = mensalidade_detalhes_por_aluno.setdefault(
                    aluno_id,
                    {"abertos": [], "proximo_vencimento": None},
                )
                status = (row.get("status") or "").lower()
                status_pagamento = (row.get("status_pagamento") or "").lower()
                venc = row.get("data_vencimento")
                em_aberto = status in ("pendente", "atrasado") or status_pagamento == "pendente_aprovacao"
                if em_aberto:
                    if status_pagamento == "pendente_aprovacao":
                        status_label = "Aguardando confirmação"
                    elif status == "atrasado" or (status == "pendente" and venc and venc < hoje):
                        status_label = "Atrasada"
                    else:
                        status_label = "Pendente"

                    competencia = (
                        venc.strftime("%m/%Y") if hasattr(venc, "strftime") and venc else "-"
                    )
                    mid = row.get("mensalidade_aluno_id")
                    acao_pagamento = (
                        "confirmar"
                        if status_pagamento == "pendente_aprovacao"
                        else "registrar"
                    )
                    ma_sim = {
                        "valor": float(row.get("valor") or 0),
                        "data_vencimento": venc,
                        "status": row.get("status"),
                        "status_pagamento": row.get("status_pagamento"),
                        "valor_original": row.get("valor_original"),
                        "desconto_aplicado": row.get("desconto_aplicado"),
                        "id_desconto": row.get("id_desconto"),
                        "mensalidade_id": row.get("mensalidade_id"),
                        "remover_juros": int(row.get("remover_juros") or 0),
                        "aplicar_juros_multas": int(row.get("aplicar_juros_multas") or 0),
                        "percentual_multa_mes": row.get("percentual_multa_mes"),
                        "percentual_juros_dia": row.get("percentual_juros_dia"),
                        "id_academia": row.get("id_academia_plano"),
                    }
                    try:
                        from blueprints.financeiro.routes import (
                            _ma_enriquecer_exibicao,
                        )

                        _ma_enriquecer_exibicao(
                            ma_sim, aluno_id, ma_sim.get("id_academia"), hoje
                        )
                    except Exception:
                        ma_sim["valor_final"] = ma_sim["valor"]
                        ma_sim["valor_integral"] = ma_sim["valor"]
                        ma_sim["valor_desconto"] = 0
                        ma_sim["tem_desconto"] = False
                        ma_sim["tem_juros"] = False
                        ma_sim["multa_val"] = None
                        ma_sim["juros_val"] = None
                        ma_sim["desconto_nome"] = ""
                    if _mensalidade_quitada_por_desconto_integral(
                        ma_sim, status_pagamento
                    ):
                        competencia_q = (
                            venc.strftime("%m/%Y")
                            if hasattr(venc, "strftime") and venc
                            else "-"
                        )
                        mid_q = row.get("mensalidade_aluno_id")
                        data_vencimento_fmt = (
                            venc.strftime("%d/%m/%Y")
                            if hasattr(venc, "strftime") and venc
                            else None
                        )
                        info["abertos"].append(
                            {
                                "id": mid_q,
                                "mensalidade_id": row.get("mensalidade_id"),
                                "tipo": row.get("tipo_mensalidade"),
                                "competencia": competencia_q,
                                "data_vencimento": data_vencimento_fmt,
                                "status": "Pago",
                                "is_pago": True,
                                "pago_por_desconto_integral": True,
                                "acao_pagamento": None,
                                "valor_pago": 0.0,
                                "data_pagamento": None,
                                "forma_pagamento": "Desconto integral",
                            }
                        )
                        continue
                    dias_atraso = None
                    if status_label == "Atrasada" and venc:
                        try:
                            vd = (
                                venc
                                if isinstance(venc, date)
                                else date.fromisoformat(str(venc)[:10])
                            )
                            dias_atraso = max(0, (hoje - vd).days)
                        except Exception:
                            pass
                    _vf_calc = float(ma_sim.get("valor_final") or row.get("valor") or 0)
                    _multa_sim = float(ma_sim.get("multa_val") or 0)
                    _juros_sim = float(ma_sim.get("juros_val") or 0)
                    if bool(ma_sim.get("tem_juros")) and (_multa_sim + _juros_sim) > 0.001:
                        _vsem_jm = round(max(0.0, _vf_calc - _multa_sim - _juros_sim), 2)
                    else:
                        _vsem_jm = round(_vf_calc, 2)
                    info["abertos"].append(
                        {
                            "id": mid,
                            "mensalidade_id": row.get("mensalidade_id"),
                            "tipo": row.get("tipo_mensalidade"),
                            "id_academia_plano": row.get("id_academia_plano"),
                            "competencia": competencia,
                            "data_vencimento": (
                                venc.strftime("%d/%m/%Y")
                                if hasattr(venc, "strftime") and venc
                                else None
                            ),
                            "data_vencimento_iso": (
                                venc.strftime("%Y-%m-%d")
                                if hasattr(venc, "strftime") and venc
                                else ""
                            ),
                            "id_desconto": row.get("id_desconto"),
                            "valor_sem_juros_multa": _vsem_jm,
                            "valor": float(row.get("valor") or 0),
                            "valor_integral": ma_sim.get("valor_integral"),
                            "valor_desconto": ma_sim.get("valor_desconto"),
                            "valor_final": ma_sim.get("valor_final"),
                            "tem_desconto": bool(ma_sim.get("tem_desconto")),
                            "tem_juros": bool(ma_sim.get("tem_juros")),
                            "multa_val": ma_sim.get("multa_val"),
                            "juros_val": ma_sim.get("juros_val"),
                            "desconto_nome": ma_sim.get("desconto_nome") or "",
                            "status": status_label,
                            "acao_pagamento": acao_pagamento,
                            "is_pago": False,
                            "dias_atraso": dias_atraso,
                        }
                    )
                    if venc and venc >= hoje:
                        prox = info.get("proximo_vencimento")
                        if prox is None or venc < prox:
                            info["proximo_vencimento"] = venc

                elif status == "pago":
                    mid = row.get("mensalidade_aluno_id")
                    competencia = (
                        venc.strftime("%m/%Y") if hasattr(venc, "strftime") and venc else "-"
                    )
                    dp = row.get("data_pagamento")
                    data_pagamento_fmt = (
                        dp.strftime("%d/%m/%Y")
                        if hasattr(dp, "strftime") and dp
                        else None
                    )
                    valor_pago = float(row.get("valor_pago") or row.get("valor") or 0)
                    if _ma_fin_cols != "full":
                        forma = "—"
                    else:
                        nome_fp = (row.get("forma_pagamento_nome") or "").strip()
                        id_fp = row.get("id_forma_pagamento")
                        if nome_fp:
                            forma = nome_fp
                        elif id_fp is not None:
                            forma = "—"
                        else:
                            forma = "Várias formas"
                            ma_pago = {
                                "valor": float(row.get("valor") or 0),
                                "data_vencimento": venc,
                                "status": row.get("status"),
                                "status_pagamento": row.get("status_pagamento"),
                                "valor_original": row.get("valor_original"),
                                "desconto_aplicado": row.get("desconto_aplicado"),
                                "id_desconto": row.get("id_desconto"),
                                "mensalidade_id": row.get("mensalidade_id"),
                                "remover_juros": int(row.get("remover_juros") or 0),
                                "aplicar_juros_multas": int(row.get("aplicar_juros_multas") or 0),
                                "percentual_multa_mes": row.get("percentual_multa_mes"),
                                "percentual_juros_dia": row.get("percentual_juros_dia"),
                                "id_academia": row.get("id_academia_plano"),
                            }
                            try:
                                from blueprints.financeiro.routes import (
                                    _ma_enriquecer_exibicao,
                                )

                                _ma_enriquecer_exibicao(
                                    ma_pago, aluno_id, ma_pago.get("id_academia"), hoje
                                )
                                if _mensalidade_quitada_por_desconto_integral(
                                    ma_pago, row.get("status_pagamento")
                                ):
                                    forma = "Desconto integral"
                            except Exception:
                                pass
                    info["abertos"].append(
                        {
                            "id": mid,
                            "mensalidade_id": row.get("mensalidade_id"),
                            "tipo": row.get("tipo_mensalidade"),
                            "competencia": competencia,
                            "data_vencimento": (
                                venc.strftime("%d/%m/%Y")
                                if hasattr(venc, "strftime") and venc
                                else None
                            ),
                            "status": "Pago",
                            "is_pago": True,
                            "acao_pagamento": "estornar",
                            "data_pagamento": data_pagamento_fmt,
                            "forma_pagamento": forma,
                            "valor_pago": valor_pago,
                            "pagamento_linhas": [],
                        }
                    )

            # Detalhe por receita (várias formas ou conferência) para parcelas pagas
            try:
                _mids_det = []
                for _info in mensalidade_detalhes_por_aluno.values():
                    for _it in _info.get("abertos") or []:
                        if (
                            _it.get("is_pago")
                            and _it.get("id")
                            and not _it.get("pago_por_desconto_integral")
                        ):
                            try:
                                _mids_det.append(int(_it["id"]))
                            except (TypeError, ValueError):
                                pass
                _mids_det = list(dict.fromkeys(_mids_det))
                _det_por_mid = (
                    _receitas_linhas_por_mensalidade_ids(db, _mids_det)
                    if _mids_det
                    else {}
                )
                for _info in mensalidade_detalhes_por_aluno.values():
                    for _it in _info.get("abertos") or []:
                        if not (
                            _it.get("is_pago")
                            and _it.get("id")
                            and not _it.get("pago_por_desconto_integral")
                        ):
                            continue
                        try:
                            _mid = int(_it["id"])
                        except (TypeError, ValueError):
                            continue
                        rows = _det_por_mid.get(_mid) or []
                        _it["pagamento_linhas"] = rows
            except Exception:
                pass

            try:
                _acad_por_aluno = {}
                for _a in alunos:
                    try:
                        _acad_por_aluno[int(_a["id"])] = _a.get("id_academia")
                    except (TypeError, ValueError, KeyError):
                        pass

                cursor.execute(
                    f"""
                    SELECT ad.aluno_id, d.id, d.nome, d.tipo, d.valor, d.id_academia
                    FROM aluno_desconto ad
                    JOIN descontos d ON d.id = ad.desconto_id AND d.ativo = 1
                    WHERE ad.aluno_id IN ({placeholders})
                      AND ad.ativo = 1
                    """,
                    tuple(aluno_ids),
                )
                _desc_por_aluno = {}
                for _dr in cursor.fetchall():
                    _desc_por_aluno.setdefault(_dr["aluno_id"], []).append(
                        {
                            "id": _dr["id"],
                            "nome": _dr["nome"],
                            "tipo": (_dr.get("tipo") or "percentual"),
                            "valor": float(_dr.get("valor") or 0),
                            "id_academia": _dr.get("id_academia"),
                        }
                    )

                _acads_desc = set()
                for _aid_x, _info_x in mensalidade_detalhes_por_aluno.items():
                    _ac_al = _acad_por_aluno.get(_aid_x)
                    if _ac_al is not None:
                        try:
                            _acads_desc.add(int(_ac_al))
                        except (TypeError, ValueError):
                            pass
                    for _mx in _info_x.get("abertos") or []:
                        if _mx.get("is_pago") or not _mx.get("id"):
                            continue
                        _pal = _mx.get("id_academia_plano")
                        if _pal is not None:
                            try:
                                _acads_desc.add(int(_pal))
                            except (TypeError, ValueError):
                                pass

                _desc_cat_por_acad = {}
                if _acads_desc:
                    _pla2 = ", ".join(["%s"] * len(_acads_desc))
                    cursor.execute(
                        f"""
                        SELECT id, nome, tipo, valor, id_academia
                        FROM descontos
                        WHERE ativo = 1 AND id_academia IN ({_pla2})
                        """,
                        tuple(_acads_desc),
                    )
                    for _cr in cursor.fetchall():
                        _ida = _cr.get("id_academia")
                        if _ida is None:
                            continue
                        try:
                            _ik = int(_ida)
                        except (TypeError, ValueError):
                            continue
                        _desc_cat_por_acad.setdefault(_ik, []).append(
                            {
                                "id": _cr["id"],
                                "nome": _cr["nome"],
                                "tipo": (_cr.get("tipo") or "percentual"),
                                "valor": float(_cr.get("valor") or 0),
                                "id_academia": _ida,
                            }
                        )

                for _aid_k, _info_d in mensalidade_detalhes_por_aluno.items():
                    for _ma in _info_d.get("abertos") or []:
                        if _ma.get("is_pago") or not _ma.get("id"):
                            continue
                        if _ma.get("id_desconto") or _ma.get("tem_desconto"):
                            _ma["descontos_opcao"] = []
                            continue
                        _pl = _ma.get("id_academia_plano")
                        if _pl is None:
                            _pl = _acad_por_aluno.get(_aid_k)
                        opts = []
                        seen = set()
                        for dd in _desc_por_aluno.get(_aid_k, []):
                            _dac = dd.get("id_academia")
                            if _pl is not None and _dac is not None:
                                try:
                                    if int(_dac) != int(_pl):
                                        continue
                                except (TypeError, ValueError):
                                    continue
                            try:
                                _iid = int(dd["id"])
                            except (TypeError, ValueError, KeyError):
                                continue
                            if _iid in seen:
                                continue
                            seen.add(_iid)
                            opts.append(
                                {
                                    "id": dd["id"],
                                    "nome": dd["nome"],
                                    "tipo": dd["tipo"],
                                    "valor": dd["valor"],
                                }
                            )
                        try:
                            _pint = int(_pl) if _pl is not None else None
                        except (TypeError, ValueError):
                            _pint = None
                        if _pint is not None:
                            for dd in _desc_cat_por_acad.get(_pint, []):
                                try:
                                    _iid = int(dd["id"])
                                except (TypeError, ValueError, KeyError):
                                    continue
                                if _iid in seen:
                                    continue
                                seen.add(_iid)
                                opts.append(
                                    {
                                        "id": dd["id"],
                                        "nome": dd["nome"],
                                        "tipo": dd["tipo"],
                                        "valor": dd["valor"],
                                    }
                                )
                        _ma["descontos_opcao"] = sorted(
                            opts,
                            key=lambda z: ((z.get("nome") or "") + "").lower(),
                        )
            except Exception:
                for _info_d in mensalidade_detalhes_por_aluno.values():
                    for _ma in _info_d.get("abertos") or []:
                        if not _ma.get("is_pago") and _ma.get("id"):
                            _ma.setdefault("descontos_opcao", [])

            for _aid_fin, info_fin in mensalidade_detalhes_por_aluno.items():
                info_fin["abertos_grupos"] = _agrupar_abertos_por_plano(
                    info_fin.get("abertos") or []
                )
            for aid_ui in list(mensalidade_detalhes_por_aluno.keys()):
                info_ui = mensalidade_detalhes_por_aluno[aid_ui]
                ab_ui = info_ui.get("abertos") or []
                atrasada_ui = any(
                    (not x.get("is_pago")) and x.get("status") == "Atrasada"
                    for x in ab_ui
                )
                st_ui = dict(mensalidade_status_por_aluno.get(aid_ui) or {})
                st_ui["atrasada"] = atrasada_ui
                mensalidade_status_por_aluno[aid_ui] = st_ui
        except Exception:
            mensalidade_status_por_aluno = {}
            mensalidade_detalhes_por_aluno = {}

        # Pacotes (planos de mensalidade) com cobrança ativa no aluno
        try:
            _ph_pac = ", ".join(["%s"] * len(aluno_ids))
            cursor.execute(
                f"""
                SELECT DISTINCT ma.aluno_id, m.id AS mensalidade_id,
                       COALESCE(m.nome, 'Mensalidade') AS nome, m.valor
                FROM mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                WHERE ma.aluno_id IN ({_ph_pac})
                  AND ma.status <> 'cancelado'
                  AND COALESCE(m.ativo, 1) = 1
                ORDER BY ma.aluno_id, nome
                """,
                tuple(aluno_ids),
            )
            for _pr in cursor.fetchall():
                _aid = _pr.get("aluno_id")
                if not _aid:
                    continue
                try:
                    _mid = int(_pr.get("mensalidade_id"))
                except (TypeError, ValueError):
                    _mid = None
                _nome = (_pr.get("nome") or "Mensalidade").strip()
                _vl = float(_pr.get("valor") or 0)
                _lista = pacotes_ativos_por_aluno.setdefault(_aid, [])
                if not any(
                    x.get("id") == _mid for x in _lista if _mid is not None
                ):
                    _lista.append({"id": _mid, "nome": _nome, "valor": _vl})
        except Exception:
            pacotes_ativos_por_aluno = {}

        try:
            cursor.execute(
                f"""
                SELECT aluno_id, COUNT(*) AS n
                FROM aluno_turmas
                WHERE aluno_id IN ({placeholders})
                GROUP BY aluno_id
                """,
                tuple(aluno_ids),
            )
            for row in cursor.fetchall():
                aid = row.get("aluno_id")
                if aid is not None:
                    turmas_nn_por_aluno[aid] = int(row.get("n") or 0)
        except Exception:
            pass

    # ======================================================
    # 🔹 CÁLCULO DE FAIXAS + MODALIDADES
    # ======================================================

    for aluno in alunos:
        n_nn = turmas_nn_por_aluno.get(aluno["id"], 0)
        aluno["tem_matricula_em_turma"] = bool(aluno.get("TurmaID")) or n_nn > 0
        # Mapear rua -> endereco (para templates que usam "endereco")
        aluno["endereco"] = aluno.get("rua")

        # Modalidades do aluno (lista global no painel associação — sem recorte por associação)
        mods = modalidades_por_aluno.get(aluno["id"], [])
        aluno["modalidades"] = mods
        aluno["modalidades_ids"] = [m["id"] for m in mods]
        aluno["modalidades_nomes"] = ", ".join(m["nome"] for m in mods) if mods else "-"
        status_fin = mensalidade_status_por_aluno.get(aluno["id"]) or {}
        detalhes_fin = mensalidade_detalhes_por_aluno.get(aluno["id"]) or {}
        aluno["mensalidade_tem"] = bool(status_fin.get("tem_mensalidade"))
        aluno["mensalidade_atrasada"] = bool(status_fin.get("atrasada"))
        # Conta mensalidades em atraso (dias_atraso > 0) para o badge
        _grupos = detalhes_fin.get("abertos_grupos") or []
        aluno["n_mensalidades_atraso"] = sum(
            1 for grp in _grupos
            for m in (grp.get("itens") or [])
            if not m.get("is_pago") and m.get("dias_atraso")
        )
        aluno["mensalidades_em_aberto"] = detalhes_fin.get("abertos") or []
        aluno["mensalidades_abertos_grupos"] = detalhes_fin.get("abertos_grupos") or []
        prox_venc = detalhes_fin.get("proximo_vencimento")
        aluno["mensalidade_proximo_vencimento"] = (
            prox_venc.strftime("%d/%m/%Y")
            if hasattr(prox_venc, "strftime")
            else None
        )
        aluno["pacotes_mensalidade_ativos"] = pacotes_ativos_por_aluno.get(
            aluno["id"]
        ) or []

        nasc = parse_date(aluno.get("data_nascimento"))
        exame = parse_date(aluno.get("ultimo_exame_faixa"))

        # Frequência Judô (ano, mês, desde último exame)
        freq_ano, freq_mes, freq_desde_exame = None, None, None
        total_desde, presentes_desde = 0, 0
        data_inicio_freq = exame or parse_date(aluno.get("data_matricula")) or hoje
        if turmas_judo_ids:
            ph = ",".join(["%s"] * len(turmas_judo_ids))
            params_j = [aluno["id"]] + turmas_judo_ids
            for label, extra_sql, extra_params in [
                ("ano", "AND YEAR(data_presenca)=%s", [hoje.year]),
                ("mes", "AND YEAR(data_presenca)=%s AND MONTH(data_presenca)=%s", [hoje.year, hoje.month]),
                ("desde", "AND data_presenca >= %s AND data_presenca <= %s", [data_inicio_freq, hoje]),
            ]:
                cursor.execute(
                    f"""SELECT COUNT(*) AS tot, SUM(CASE WHEN presente=1 THEN 1 ELSE 0 END) AS pres
                        FROM presencas WHERE aluno_id=%s AND turma_id IN ({ph}) {extra_sql}""",
                    params_j + extra_params,
                )
                r = cursor.fetchone()
                if r and r.get("tot", 0) and r["tot"] > 0:
                    pct = round((r["pres"] or 0) / r["tot"] * 100, 1)
                    if label == "ano":
                        freq_ano = pct
                    elif label == "mes":
                        freq_mes = pct
                    else:
                        freq_desde_exame = pct
                        total_desde = r["tot"]
                        presentes_desde = r["pres"] or 0
        aluno["frequencia_ano"] = freq_ano
        aluno["frequencia_mes"] = freq_mes
        aluno["frequencia_desde_exame"] = freq_desde_exame
        aluno["frequencia_desde_inicio"] = data_inicio_freq.strftime("%d/%m/%Y")
        aluno["total_aulas_desde"] = total_desde
        aluno["presentes_desde"] = presentes_desde

        # Idade real e em ano civil
        aluno["idade_real"] = (
            hoje.year
            - nasc.year
            - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
        ) if nasc else None

        aluno["idade_ano_civil"] = hoje.year - nasc.year if nasc else None
        idade_civil = aluno["idade_ano_civil"] or 0
        faixa_atual = (aluno.get("faixa") or "").lower()

        aluno["data_nascimento_formatada"] = (
            nasc.strftime("%d/%m/%Y") if nasc else "-"
        )
        aluno["ultimo_exame_faixa_formatada"] = (
            exame.strftime("%d/%m/%Y") if exame else "-"
        )

        faixa_sugerida = "-"
        regra_especial = "-"

        # Regras automáticas
        if idade_civil <= 6:
            faixa_sugerida = "Branca / Cinza"
        elif idade_civil == 7:
            faixa_sugerida = "Cinza"
        elif idade_civil == 11:
            faixa_sugerida = "Azul"
        elif idade_civil == 15:
            faixa_sugerida = "Amarela"
        elif "azul" in faixa_atual and idade_civil <= 12:
            faixa_sugerida = "Azul / Amarela"
        elif "amarela" in faixa_atual and idade_civil <= 13:
            faixa_sugerida = "Amarela / Laranja"

        # Aprovação manual do professor
        aprov = aprovacoes.get(aluno["id"])
        if idade_civil >= 11 and aprov:
            faixa_sugerida = aprov["faixa_aprovada"]
            regra_especial = (
                f"Aprovado por {aprov['aprovado_por']} em "
                f"{aprov['data_aprovacao'].strftime('%d/%m/%Y')}"
            )

        aluno["faixa_sugerida"] = faixa_sugerida
        aluno["regra_especial"] = regra_especial

        # Próxima faixa
        faixa_atual_id = aluno.get("graduacao_id")
        proxima = None

        for i, f in enumerate(faixas):
            if f["id"] == faixa_atual_id and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                break

        if not proxima:
            aluno.update(
                {
                    "proxima_faixa": "Última faixa",
                    "aptidao_status": "-",
                    "aptidao": "Sem próxima faixa",
                    "motivo": "",
                    "data_elegivel": "-",
                    "faltam_dias": 0,
                    "frequencia_aptidao_ok": True,
                }
            )
            continue

        idade_minima = extrair_numero(proxima.get("idade_minima"))
        carencia_meses = extrair_numero(proxima.get("carencia_meses"))
        carencia_dias = extrair_numero(proxima.get("carencia_dias"))
        carencia_minima_raw = proxima.get("carencia_minima") or proxima.get("carencia")

        anos_c, meses_c, dias_c = 0, 0, 0
        if carencia_meses:
            meses_c = carencia_meses
        elif carencia_dias:
            dias_c = carencia_dias
        else:
            anos_c, meses_c, dias_c = parse_carencia(carencia_minima_raw)

        carencia_required = any([anos_c, meses_c, dias_c])
        if carencia_required and exame:
            delta = relativedelta(years=anos_c, months=meses_c, days=dias_c)
            data_carencia = exame + delta
        else:
            data_carencia = None

        data_idade_minima = (
            nasc + relativedelta(years=idade_minima) if (nasc and idade_minima) else None
        )

        data_elegivel = (
            max(data_carencia, data_idade_minima)
            if (data_carencia and data_idade_minima)
            else (data_carencia or data_idade_minima)
        )
        faltam = max(0, (data_elegivel - hoje).days) if data_elegivel else 0

        if idade_minima == 0:
            idade_ok = True
            idade_data_ok = True
        else:
            idade_ok = aluno["idade_real"] is not None and aluno["idade_real"] >= idade_minima
            idade_data_ok = data_idade_minima is not None and hoje >= data_idade_minima

        if not carencia_required:
            carencia_ok = True
        else:
            carencia_ok = data_carencia is not None and hoje >= data_carencia

        aluno["proxima_faixa"] = f"{proxima['faixa']} {proxima['graduacao']}"
        aluno["data_elegivel"] = (
            data_elegivel.strftime("%d/%m/%Y") if data_elegivel else "-"
        )
        aluno["faltam_dias"] = faltam

        # Exige 70% de frequência em Judô desde o último exame
        freq_val = aluno.get("frequencia_desde_exame")
        frequencia_ok = True if freq_val is None else freq_val >= 70
        aluno["frequencia_aptidao_ok"] = frequencia_ok

        if idade_ok and idade_data_ok and carencia_ok and frequencia_ok:
            aluno["aptidao_status"] = "Apto"
            aluno["aptidao"] = (
                f"Apto para exame de faixa {aluno['proxima_faixa']}"
            )
            aluno["motivo"] = ""
        else:
            motivos = []
            if idade_minima > 0:
                if aluno["idade_real"] is None:
                    motivos.append("Informe data de nascimento")
                elif not idade_ok:
                    motivos.append(f"Idade mínima: {idade_minima} anos")
            if carencia_required:
                if not exame:
                    motivos.append("Informe data do último exame")
                elif not carencia_ok:
                    data_carencia_fmt = (
                        data_carencia.strftime("%d/%m/%Y") if data_carencia else "-"
                    )
                    motivos.append(
                        f"Carência até {data_carencia_fmt} (faltam {faltam} dias)"
                    )
            if not idade_data_ok and data_idade_minima:
                motivos.append(
                    f"Idade mínima em {data_idade_minima.strftime('%d/%m/%Y')}"
                )
            if not frequencia_ok and freq_val is not None:
                motivos.append(
                    f"Frequência Judô: {freq_val}% (mínimo 70% desde {aluno.get('frequencia_desde_inicio', 'último exame')})"
                )
            elif not frequencia_ok and total_desde == 0:
                motivos.append("Sem registro de frequência em Judô desde o último exame")
            aluno["aptidao_status"] = "Inapto"
            aluno["aptidao"] = "Inapto"
            aluno["motivo"] = "; ".join(motivos)

        # ======================================================
        # 🔹 Categorias baseadas na tabela categorias
        # ======================================================
        # Busca categoria na tabela categorias
        categorias_match = []
        sexo = (aluno.get("sexo") or "").upper()
        peso = aluno.get("peso")
        idade_ano_civil = aluno.get("idade_ano_civil")
        
        if sexo in ("M", "F") and peso is not None and idade_ano_civil is not None:
            for cat in categorias:
                # Verifica gênero
                if (cat.get("genero") or "").upper() != sexo:
                    continue
                
                # Verifica idade
                idade_min = cat.get("idade_min")
                idade_max = cat.get("idade_max")
                if idade_min is not None and idade_ano_civil < idade_min:
                    continue
                if idade_max is not None and idade_ano_civil > idade_max:
                    continue
                
                # Verifica peso
                peso_min = cat.get("peso_min")
                peso_max = cat.get("peso_max")
                if peso_min is not None and peso < float(peso_min):
                    continue
                if peso_max is not None and peso > float(peso_max):
                    continue
                
                categorias_match.append(cat)

        partes = []
        # Exibir classe se disponível na categoria
        if categorias_match:
            cat = categorias_match[0]
            id_classe = cat.get('id_classe')
            if id_classe:
                partes.append(f"Classe: {id_classe}")
            
            nome_categoria_txt = cat.get('nome_categoria') or ''
            if nome_categoria_txt:
                partes.append(f"Categoria: {nome_categoria_txt}")
            else:
                partes.append("Categoria: -")
        else:
            if peso is None:
                partes.append("Categoria: informe o peso")
            elif sexo not in ("M", "F"):
                partes.append("Categoria: informe o sexo")
            elif idade_ano_civil is None:
                partes.append("Categoria: informe data de nascimento")
            else:
                partes.append("Categoria: não encontrada")

        aluno["classes_e_pesos"] = " | ".join(partes)

    # Carregar academias para seletor (admin, federação, associação: sempre; academia: se > 1)
    academias = []
    academia_id_sel = None
    mostrar_filtro_academia = (
        len(ids_acessiveis) >= 1
        and (modo in ("academia", "associacao", "federacao") or current_user.has_role("admin"))
    )
    if mostrar_filtro_academia:
        try:
            cursor.execute(
                "SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids_acessiveis)),
                tuple(ids_acessiveis),
            )
            academias = cursor.fetchall()
            academia_id_sel = academia_filtro if (academia_filtro and academia_filtro in ids_acessiveis) else None
        except Exception:
            pass

    # Filtro por modalidade (afeta lista, agrupamento e estatísticas)
    if modalidade_filtro:
        if modalidade_filtro == -1:
            alunos = [a for a in alunos if not (a.get("modalidades_ids"))]
        else:
            alunos = [a for a in alunos if modalidade_filtro in (a.get("modalidades_ids") or [])]

    # Verificar modo de agrupamento (apenas para modo associação)
    agrupar_por_academia = False
    if modo == "associacao":
        agrupar_por_academia = request.args.get("agrupar_por") == "academia"
    
    # Agrupar alunos por modalidade ou por academia (modo associação)
    alunos_agrupados = []
    
    if modo == "associacao" and agrupar_por_academia:
        # Agrupar por academia no modo associação
        acad_nome_to_alunos = {}
        for aluno in alunos:
            acad_nome = aluno.get("academia_nome") or "Sem academia"
            acad_nome_to_alunos.setdefault(acad_nome, []).append(aluno)
        
        # Ordenar academias A-Z e alunos dentro de cada academia A-Z
        for acad_nome in sorted(acad_nome_to_alunos.keys()):
            lista = sorted(acad_nome_to_alunos[acad_nome], key=lambda a: (a.get("nome") or ""))
            alunos_agrupados.append((acad_nome, lista))
    else:
        # Agrupar por modalidade (comportamento padrão)
        mod_nome_to_alunos = {}
        for aluno in alunos:
            mods = aluno.get("modalidades") or []
            if not mods:
                mod_nome_to_alunos.setdefault("Sem modalidade", []).append(aluno)
            else:
                for m in mods:
                    if modalidade_filtro and modalidade_filtro != -1 and m.get("id") != modalidade_filtro:
                        continue
                    nome_mod = m.get("nome") or "Outras"
                    mod_nome_to_alunos.setdefault(nome_mod, []).append(aluno)
        # Ordenar: "Sem modalidade" por último
        def _ord_modalidade(k):
            return (1, k) if k == "Sem modalidade" else (0, k)
        mod_keys = list(mod_nome_to_alunos.keys())
        for nome_mod in sorted(mod_keys, key=_ord_modalidade):
            lista = mod_nome_to_alunos[nome_mod]
            alunos_agrupados.append((nome_mod, sorted(lista, key=lambda a: (a.get("nome") or ""))))

    # Estatísticas: total = alunos que realmente aparecem na página (após filtro de modalidade, etc.)
    ids_na_pagina = set()
    for _, grupo in alunos_agrupados:
        for a in grupo:
            ids_na_pagina.add(a.get("id"))
    alunos_exibidos = [a for a in alunos if a.get("id") in ids_na_pagina]

    stats = {
        "total": len(alunos_exibidos),
        "ativos": 0,
        "inativos": 0,
        "por_academia": {},
        "por_graduacao": {},
        "por_turma": {},
    }
    for aluno in alunos_exibidos:
        av = aluno.get("ativo")
        if av is None:
            stats["ativos"] += 1
        else:
            try:
                if int(av) == 1:
                    stats["ativos"] += 1
                else:
                    stats["inativos"] += 1
            except (TypeError, ValueError):
                if av:
                    stats["ativos"] += 1
                else:
                    stats["inativos"] += 1
        acad_nome = aluno.get("academia_nome") or "Sem academia"
        stats["por_academia"][acad_nome] = stats["por_academia"].get(acad_nome, 0) + 1
        grad_nome = aluno.get("faixa") or "Sem faixa"
        if aluno.get("graduacao"):
            grad_nome = f"{grad_nome} {aluno['graduacao']}".strip()
        stats["por_graduacao"][grad_nome] = stats["por_graduacao"].get(grad_nome, 0) + 1
        turma_nome_st = aluno.get("turma_nome")
        if turma_nome_st:
            stats["por_turma"][turma_nome_st] = stats["por_turma"].get(turma_nome_st, 0) + 1

    # Mostrar filtros avançados em modo associação/federação ou quando há múltiplas academias
    mostrar_filtros_avancados = modo in ("associacao", "federacao") or len(ids_acessiveis) > 1

    # Enriquecer alunos para o modal (adicionar categorias, frequência, etc.)
    # IMPORTANTE: fazer antes de fechar a conexão do banco
    for _, grupo_alunos in alunos_agrupados:
        for aluno in grupo_alunos:
            enriquecer_aluno_para_modal(aluno)

    # Planos de mensalidade da academia (para modal financeiro no modo academia)
    planos_mensalidades = []
    try:
        academia_planos_id = academia_id_sel or getattr(current_user, "id_academia", None)
        if academia_planos_id:
            conn2 = get_db_connection()
            cur2 = conn2.cursor(dictionary=True)
            cur2.execute(
                "SELECT id, nome, valor FROM mensalidades WHERE id_academia = %s AND ativo = 1 ORDER BY nome",
                (academia_planos_id,),
            )
            planos_mensalidades = cur2.fetchall()
            cur2.close()
            conn2.close()
    except Exception:
        planos_mensalidades = []

    # Turmas, planos e formas de pagamento por academia (reativação / modal financeiro)
    turmas_por_academia = {}
    planos_por_academia = {}
    formas_por_academia = {}
    try:
        ids_acads_presentes = {a.get("id_academia") for a in alunos if a.get("id_academia")}
        for _info in (mensalidade_detalhes_por_aluno or {}).values():
            for _it in _info.get("abertos") or []:
                _ap = _it.get("id_academia_plano")
                if _ap is not None:
                    ids_acads_presentes.add(_ap)
        for acad_id in ids_acads_presentes:
            if not acad_id:
                continue
            cursor.execute(
                """
                SELECT TurmaID AS turma_id, Nome AS turma_nome
                FROM turmas WHERE id_academia = %s ORDER BY Nome
                """,
                (acad_id,),
            )
            turmas_por_academia[acad_id] = cursor.fetchall()
            cursor.execute(
                """
                SELECT id, nome, valor FROM mensalidades
                WHERE id_academia = %s AND ativo = 1 ORDER BY nome
                """,
                (acad_id,),
            )
            planos_por_academia[acad_id] = cursor.fetchall()
            try:
                from blueprints.financeiro.routes import _ensure_formas_padrao

                _ensure_formas_padrao(cursor, acad_id)
                cursor.execute(
                    """
                    SELECT id, nome FROM formas_pagamento
                    WHERE id_academia = %s AND ativo = 1 ORDER BY ordem, nome
                    """,
                    (acad_id,),
                )
                _fp_rows = cursor.fetchall()
                for _fp in _fp_rows:
                    try:
                        _fp["id"] = int(_fp["id"])
                    except (TypeError, ValueError, KeyError):
                        pass
                formas_por_academia[acad_id] = _fp_rows
            except Exception:
                formas_por_academia[acad_id] = []
    except Exception:
        turmas_por_academia = {}
        planos_por_academia = {}
        formas_por_academia = {}

    academias_por_associacao = {}
    if modo == "associacao" and _pode_transferir_aluno_academia_modo_associacao():
        try:
            if current_user.has_role("gestor_associacao"):
                assoc_id = getattr(current_user, "id_associacao", None)
                if assoc_id is not None:
                    cursor.execute(
                        "SELECT id, nome FROM academias WHERE id_associacao = %s ORDER BY nome",
                        (assoc_id,),
                    )
                    academias_por_associacao[int(assoc_id)] = cursor.fetchall()
            elif current_user.has_role("admin"):
                assoc_ids = set()
                for a in alunos:
                    ias = a.get("id_associacao")
                    if ias is not None:
                        try:
                            assoc_ids.add(int(ias))
                        except (TypeError, ValueError):
                            pass
                for aid in assoc_ids:
                    cursor.execute(
                        "SELECT id, nome FROM academias WHERE id_associacao = %s ORDER BY nome",
                        (aid,),
                    )
                    academias_por_associacao[aid] = cursor.fetchall()
        except Exception:
            academias_por_associacao = {}

    db.close()
    
    # Modo associação/federação: voltar sempre para o gerenciamento
    if modo == "associacao":
        back_url = url_for("associacao.gerenciamento_associacao")
    elif modo == "federacao":
        back_url = url_for("federacao.gerenciamento_federacao")
    else:
        lista_alunos_path_norm = url_for("alunos.lista_alunos").rstrip("/") or "/"

        def _path_norm(url_or_path):
            if not url_or_path:
                return ""
            s = str(url_or_path).strip()
            if not s:
                return ""
            if s.startswith("/") and not s.startswith("//"):
                path = urlparse(s).path
            elif "://" in s:
                path = urlparse(s).path
            else:
                path = urlparse(s).path
            return (path.rstrip("/") or "/")

        def _voltar_aponta_para_lista_alunos(candidate):
            return _path_norm(candidate) == lista_alunos_path_norm

        back_url = (request.args.get("next") or "").strip()
        if back_url:
            if not back_url.startswith("/") or back_url.startswith("//"):
                back_url = ""
            elif _voltar_aponta_para_lista_alunos(back_url):
                back_url = ""

        # O botão Voltar deve levar à ÁREA PRINCIPAL do modo atual, e não
        # apenas desfazer a última navegação (request.referrer), que fazia o
        # botão "voltar só uma ação". O parâmetro explícito ?next= ainda é honrado acima.
        if not back_url:
            if modo == "admin":
                back_url = url_for("painel.gerenciamento_admin")
            elif modo == "professor":
                back_url = url_for("professor.painel_professor")
            elif modo == "academia" and academia_id_sel:
                back_url = url_for("academia.painel_academia", academia_id=academia_id_sel)
            elif modo == "academia":
                back_url = url_for("academia.painel_academia")
            else:
                back_url = url_for("painel.home")
    modo_associacao = modo == "associacao"
    # Academias com cobrança online (Asaas) ativa — habilita o seletor PIX/Boleto no modal.
    asaas_academias = set()
    try:
        _c = get_db_connection()
        _cur = _c.cursor()
        _cur.execute("SELECT id FROM academias WHERE asaas_habilitado = 1 AND asaas_api_key IS NOT NULL AND asaas_api_key <> ''")
        asaas_academias = {row[0] for row in _cur.fetchall()}
        _c.close()
    except Exception:
        asaas_academias = set()
    # Modo associação: filtros sempre vazios (só placeholders)
    return render_template(
        "alunos/lista_alunos.html",
        alunos=alunos,
        asaas_academias=asaas_academias,
        alunos_agrupados=alunos_agrupados,
        busca="" if modo_associacao else busca,
        back_url=back_url,
        academias=academias,
        academia_id=academia_id_sel,
        faixas=faixas,
        graduacao_id=None if modo_associacao else graduacao_id,
        peso_min=None if modo_associacao else peso_min,
        peso_max=None if modo_associacao else peso_max,
        ano_nasc_min=None if modo_associacao else ano_nasc_min,
        ano_nasc_max=None if modo_associacao else ano_nasc_max,
        turma_id=None if modo_associacao else turma_filtro,
        sexo=("" if modo_associacao else sexo_filtro),
        turmas_filtro=turmas_filtro,
        modalidades_filtro=modalidades_filtro,
        modalidade_id=modalidade_filtro,
        tem_sem_modalidade=tem_sem_modalidade,
        filtro_ativo=("todos" if modo_associacao else filtro_ativo),
        stats=stats,
        mostrar_filtros_avancados=mostrar_filtros_avancados,
        agrupar_por_academia=agrupar_por_academia if modo_associacao else False,
        modo_associacao=modo_associacao,
        planos_mensalidades=planos_mensalidades,
        turmas_por_academia=turmas_por_academia,
        planos_por_academia=planos_por_academia,
        formas_por_academia=formas_por_academia,
        hoje=hoje,
        academias_por_associacao=academias_por_associacao,
    )


def enriquecer_aluno_para_modal(aluno):
    """Enriquece um único aluno com classes_e_pesos, aptidão, frequência etc. para o modal 'Ver dados'."""
    if not aluno or not aluno.get("id"):
        return
    # Inicializar valores padrão para aptidão
    aluno.setdefault("aptidao_status", "Não calculado")
    aluno.setdefault("motivo", "")
    aluno.setdefault("data_elegivel", "-")
    aluno.setdefault("proxima_faixa", "-")
    aluno.setdefault("frequencia_ano", None)
    aluno.setdefault("frequencia_mes", None)
    aluno.setdefault("frequencia_desde_exame", None)
    aluno.setdefault("total_aulas_desde", 0)
    aluno.setdefault("presentes_desde", 0)
    aluno.setdefault("turma_nome", None)
    aluno.setdefault("academia_nome", None)
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    hoje = date.today()
    try:
        # Buscar turma e academia se não estiverem definidas
        if not aluno.get("turma_nome") or not aluno.get("academia_nome"):
            cursor.execute(
                """SELECT ac.nome AS academia_nome, t.Nome AS turma_nome
                   FROM alunos a
                   LEFT JOIN academias ac ON ac.id = a.id_academia
                   LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                   WHERE a.id = %s""",
                (aluno["id"],),
            )
            row = cursor.fetchone()
            if row:
                if not aluno.get("academia_nome"):
                    aluno["academia_nome"] = row.get("academia_nome")
                if not aluno.get("turma_nome"):
                    aluno["turma_nome"] = row.get("turma_nome")
        
        # Se ainda não encontrou turma, tentar buscar diretamente pelo TurmaID
        if not aluno.get("turma_nome") and aluno.get("TurmaID"):
            cursor.execute("SELECT Nome FROM turmas WHERE TurmaID = %s", (aluno.get("TurmaID"),))
            turma_row = cursor.fetchone()
            if turma_row:
                aluno["turma_nome"] = turma_row.get("Nome")
        
        # Se ainda não encontrou, tentar buscar via aluno_turmas
        if not aluno.get("turma_nome"):
            cursor.execute(
                """SELECT t.Nome FROM aluno_turmas at
                   INNER JOIN turmas t ON t.TurmaID = at.TurmaID
                   WHERE at.aluno_id = %s
                   ORDER BY at.TurmaID LIMIT 1""",
                (aluno["id"],),
            )
            turma_row = cursor.fetchone()
            if turma_row:
                aluno["turma_nome"] = turma_row.get("Nome")
        cursor.execute("SELECT * FROM graduacao ORDER BY id")
        faixas = cursor.fetchall()
        # Carrega categorias da tabela categorias
        cursor.execute(
            """
            SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max
            FROM categorias
            ORDER BY id
            """
        )
        categorias = cursor.fetchall()
        cursor.execute("SELECT aluno_id, faixa_aprovada, aprovado_por, data_aprovacao FROM aprovacoes_faixa_professor")
        aprovacoes = {a["aluno_id"]: a for a in cursor.fetchall()}
        try:
            cursor.execute("SELECT turma_id FROM turma_modalidades WHERE modalidade_id = 1")
            turmas_judo_ids = [r["turma_id"] for r in cursor.fetchall()]
        except Exception:
            turmas_judo_ids = []

        cursor.execute(
            """SELECT m.id, m.nome FROM modalidade m
               INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id
               WHERE am.aluno_id = %s ORDER BY m.nome""",
            (aluno["id"],),
        )
        mods = cursor.fetchall()
        aluno["modalidades"] = mods
        aluno["modalidades_nomes"] = ", ".join(m["nome"] for m in mods) if mods else "-"

        nasc = parse_date(aluno.get("data_nascimento"))
        exame = parse_date(aluno.get("ultimo_exame_faixa"))

        freq_ano, freq_mes, freq_desde_exame = None, None, None
        total_desde, presentes_desde = 0, 0
        data_inicio_freq = exame or parse_date(aluno.get("data_matricula")) or hoje
        if turmas_judo_ids:
            ph = ",".join(["%s"] * len(turmas_judo_ids))
            for label, extra_sql, extra_params in [
                ("ano", "AND YEAR(data_presenca)=%s", [hoje.year]),
                ("mes", "AND YEAR(data_presenca)=%s AND MONTH(data_presenca)=%s", [hoje.year, hoje.month]),
                ("desde", "AND data_presenca >= %s AND data_presenca <= %s", [data_inicio_freq, hoje]),
            ]:
                cursor.execute(
                    f"""SELECT COUNT(*) AS tot, SUM(CASE WHEN presente=1 THEN 1 ELSE 0 END) AS pres
                        FROM presencas WHERE aluno_id=%s AND turma_id IN ({ph}) {extra_sql}""",
                    [aluno["id"]] + turmas_judo_ids + extra_params,
                )
                r = cursor.fetchone()
                if r and r.get("tot", 0) and r["tot"] > 0:
                    pct = round((r["pres"] or 0) / r["tot"] * 100, 1)
                    if label == "ano":
                        freq_ano = pct
                    elif label == "mes":
                        freq_mes = pct
                    else:
                        freq_desde_exame = pct
                        total_desde = r["tot"]
                        presentes_desde = r["pres"] or 0
        aluno["frequencia_ano"] = freq_ano
        aluno["frequencia_mes"] = freq_mes
        aluno["frequencia_desde_exame"] = freq_desde_exame
        aluno["total_aulas_desde"] = total_desde
        aluno["presentes_desde"] = presentes_desde

        aluno["idade_real"] = (
            hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
        ) if nasc else None
        aluno["idade_ano_civil"] = hoje.year - nasc.year if nasc else None
        idade_civil = aluno["idade_ano_civil"] or 0
        faixa_atual = (aluno.get("faixa") or aluno.get("faixa_nome") or "").lower()

        aluno["data_nascimento_formatada"] = nasc.strftime("%d/%m/%Y") if nasc else "-"
        aluno["ultimo_exame_faixa_formatada"] = exame.strftime("%d/%m/%Y") if exame else "-"

        gid = aluno.get("graduacao_id")
        proxima = None
        for i, f in enumerate(faixas):
            if f["id"] == gid and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                break

        if not proxima:
            aluno["aptidao_status"] = "Sem próxima faixa"
            aluno["motivo"] = "Não há próxima faixa cadastrada no sistema"
            aluno["data_elegivel"] = "-"
            aluno["proxima_faixa"] = "-"
        else:
            aluno["proxima_faixa"] = f"{proxima['faixa']} {proxima['graduacao']}"
            idade_minima = extrair_numero(proxima.get("idade_minima"))
            carencia_meses = extrair_numero(proxima.get("carencia_meses"))
            carencia_dias = extrair_numero(proxima.get("carencia_dias"))
            carencia_minima_raw = proxima.get("carencia_minima") or proxima.get("carencia")
            anos_c, meses_c, dias_c = 0, 0, 0
            if carencia_meses:
                meses_c = carencia_meses
            elif carencia_dias:
                dias_c = carencia_dias
            else:
                anos_c, meses_c, dias_c = parse_carencia(carencia_minima_raw)
            carencia_required = any([anos_c, meses_c, dias_c])
            if carencia_required and exame:
                delta = relativedelta(years=anos_c, months=meses_c, days=dias_c)
                data_carencia = exame + delta
            else:
                data_carencia = None
            data_idade_minima = (
                nasc + relativedelta(years=idade_minima) if (nasc and idade_minima) else None
            )
            data_elegivel = (
                max(data_carencia, data_idade_minima)
                if (data_carencia and data_idade_minima)
                else (data_carencia or data_idade_minima)
            )
            aluno["data_elegivel"] = (
                data_elegivel.strftime("%d/%m/%Y") if data_elegivel else "-"
            )
            idade_ok = True if idade_minima == 0 else (
                aluno["idade_real"] is not None and aluno["idade_real"] >= idade_minima
            )
            idade_data_ok = True if idade_minima == 0 else (
                data_idade_minima is not None and hoje >= data_idade_minima
            )
            carencia_ok = True if not carencia_required else (
                data_carencia is not None and hoje >= data_carencia
            )
            freq_val = aluno.get("frequencia_desde_exame")
            frequencia_ok = True if freq_val is None else freq_val >= 70

            if idade_ok and idade_data_ok and carencia_ok and frequencia_ok:
                aluno["aptidao_status"] = "Apto"
                aluno["motivo"] = ""
            else:
                motivos = []
                if not idade_ok and idade_minima > 0:
                    motivos.append(f"Idade mínima: {idade_minima} anos")
                if not idade_data_ok and data_idade_minima:
                    motivos.append(f"Idade mínima em {data_idade_minima.strftime('%d/%m/%Y')}")
                if not carencia_ok and data_carencia:
                    motivos.append(f"Carencia até {data_carencia.strftime('%d/%m/%Y')}")
                if not frequencia_ok and freq_val is not None:
                    motivos.append(f"Frequência desde exame: {freq_val}% (mín. 70%)")
                if not frequencia_ok and total_desde == 0:
                    motivos.append("Sem registro de frequência em Judô desde o último exame")
                aluno["aptidao_status"] = "Inapto"
                aluno["motivo"] = "; ".join(motivos)

        # Busca categoria na tabela categorias usando a mesma lógica de simular_categorias
        categorias_match = []
        sexo = (aluno.get("sexo") or "").upper()
        peso = aluno.get("peso")
        idade_ano_civil = aluno.get("idade_ano_civil")
        
        if sexo in ("M", "F") and peso is not None and peso > 0 and idade_ano_civil is not None:
            # Mapear M/F para MASCULINO/FEMININO
            genero_db = "MASCULINO" if sexo == "M" else "FEMININO" if sexo == "F" else sexo
            
            cursor.execute("""
                SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max, descricao
                FROM categorias
                WHERE UPPER(genero) = UPPER(%s)
                AND ativo = 1
                AND (
                    (idade_min IS NULL OR %s >= idade_min)
                    AND (idade_max IS NULL OR %s <= idade_max)
                )
                AND (
                    (peso_min IS NULL OR %s >= peso_min)
                    AND (peso_max IS NULL OR %s <= peso_max)
                )
                ORDER BY nome_categoria
            """, (genero_db, idade_ano_civil, idade_ano_civil, peso, peso))
            categorias_match = cursor.fetchall()

        # Preparar lista de categorias para exibição
        categorias_lista = []
        if categorias_match:
            for cat in categorias_match:
                nome_cat = cat.get("nome_categoria") or cat.get("categoria") or "-"
                id_classe = cat.get("id_classe")
                if id_classe:
                    categorias_lista.append(f"{id_classe} - {nome_cat}")
                else:
                    categorias_lista.append(nome_cat)
        
        # Garantir que categorias_disponiveis seja sempre uma lista
        aluno["categorias_disponiveis"] = categorias_match if categorias_match else []
        
        # Mensagem de erro se não encontrou categorias
        if not categorias_match:
            if peso is None or peso == 0:
                aluno["categorias_texto"] = "Informe o peso"
            elif sexo not in ("M", "F"):
                aluno["categorias_texto"] = "Informe o sexo"
            elif idade_ano_civil is None:
                aluno["categorias_texto"] = "Informe data de nascimento"
            else:
                aluno["categorias_texto"] = "Nenhuma categoria encontrada"
        else:
            aluno["categorias_texto"] = ", ".join(categorias_lista) if categorias_lista else "Nenhuma categoria encontrada"
        
        aluno["classes_e_pesos"] = aluno.get("categorias_texto") or "-"

        if not aluno.get("responsavel") and aluno.get("responsavel_nome"):
            aluno["responsavel"] = aluno["responsavel_nome"]
    except Exception as e:
        # Em caso de erro, manter valores padrão já definidos
        import logging
        logging.error(f"Erro ao enriquecer aluno {aluno.get('id')}: {e}", exc_info=True)
        # Garantir que pelo menos os valores padrão estejam definidos
        aluno.setdefault("aptidao_status", "Erro ao calcular")
        aluno.setdefault("motivo", "Erro ao processar dados de aptidão")
        aluno.setdefault("data_elegivel", "-")
        aluno.setdefault("proxima_faixa", "-")
    finally:
        cursor.close()
        conn.close()


# ======================================================
# 🔹 2. CADASTRAR ALUNO
# ======================================================

@bp_alunos.route("/cadastrar_aluno", methods=["GET", "POST"])
@login_required
def cadastrar_aluno():
    # Permissões: apenas gestores / admin
    if not (
        current_user.has_role("gestor_academia")
        or current_user.has_role("gestor_associacao")
        or current_user.has_role("gestor_federacao")
        or current_user.has_role("admin")
    ):
        flash("Você não tem permissão para cadastrar alunos.", "danger")
        return redirect(url_for("alunos.lista_alunos"))

    back_url = request.args.get("next") or request.referrer or url_for("alunos.lista_alunos")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Carregar combos (graduacoes, turmas, modalidades)
    try:
        cursor.execute(
            """
            SELECT g.*, g.modalidade_id
            FROM graduacao g
            WHERE COALESCE(g.ativo, 1) = 1
            ORDER BY COALESCE(NULLIF(g.ordem,0), g.id), g.id
            """
        )
        graduacoes = cursor.fetchall()
    except Exception:
        cursor.execute("SELECT * FROM graduacao ORDER BY id")
        graduacoes = cursor.fetchall()

    acad_filtro = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    ids_acad = _get_academias_ids()
    if acad_filtro and acad_filtro in ids_acad:
        session["academia_gerenciamento_id"] = acad_filtro
        session["finance_academia_id"] = acad_filtro
    turmas = []
    try:
        if acad_filtro and acad_filtro in ids_acad:
            # Filtrar por academia específica selecionada
            cursor.execute("SELECT * FROM turmas WHERE id_academia = %s ORDER BY Nome", (acad_filtro,))
            turmas = cursor.fetchall()
        elif ids_acad:
            # Filtrar por todas as academias acessíveis ao usuário
            placeholders = ",".join(["%s"] * len(ids_acad))
            cursor.execute(f"SELECT * FROM turmas WHERE id_academia IN ({placeholders}) ORDER BY Nome", tuple(ids_acad))
            turmas = cursor.fetchall()
        # Se não houver academias acessíveis, turmas já está como lista vazia
    except Exception:
        # Em caso de erro, tentar filtrar pelas academias acessíveis
        if ids_acad:
            try:
                placeholders = ",".join(["%s"] * len(ids_acad))
                cursor.execute(f"SELECT * FROM turmas WHERE id_academia IN ({placeholders}) ORDER BY Nome", tuple(ids_acad))
                turmas = cursor.fetchall()
            except Exception:
                turmas = []

    id_acad_modalidade = acad_filtro or (ids_acad[0] if ids_acad else None) or getattr(current_user, "id_academia", None)
    modalidades = []
    id_assoc_modalidade = None
    try:
        if id_acad_modalidade:
            cursor.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_acad_modalidade,))
            r = cursor.fetchone()
            id_assoc_modalidade = r.get("id_associacao") if r else None
            extra, extra_params = filtro_visibilidade_sql(id_academia=id_acad_modalidade, id_associacao=id_assoc_modalidade)
            cursor.execute(
                """
                SELECT m.id, m.nome, m.descricao, m.ativo
                FROM modalidade m
                INNER JOIN academia_modalidades am ON am.modalidade_id = m.id
                WHERE am.academia_id = %s AND m.ativo = 1
                """ + extra + """
                ORDER BY m.nome
                """,
                (id_acad_modalidade,) + extra_params,
            )
            modalidades = cursor.fetchall()
        else:
            cursor.execute("SELECT id, nome, descricao, ativo FROM modalidade WHERE ativo = 1 ORDER BY nome")
            modalidades = cursor.fetchall()
    except Exception:
        cursor.execute("SELECT id, nome, descricao, ativo FROM modalidade WHERE ativo = 1 ORDER BY nome")
        modalidades = cursor.fetchall()

    # Academias disponíveis (com associação)
    academias = []
    try:
        if current_user.has_role("admin"):
            cursor.execute(
                """
                SELECT ac.id, ac.nome AS academia_nome, ass.nome AS associacao_nome,
                       ass.id AS associacao_id, ass.id_federacao
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                ORDER BY ac.nome
                """
            )
        elif current_user.has_role("gestor_federacao"):
            cursor.execute(
                """
                SELECT ac.id, ac.nome AS academia_nome, ass.nome AS associacao_nome,
                       ass.id AS associacao_id, ass.id_federacao
                FROM academias ac
                JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ass.id_federacao = %s
                ORDER BY ac.nome
                """,
                (getattr(current_user, "id_federacao", 0),),
            )
        elif current_user.has_role("gestor_associacao"):
            cursor.execute(
                """
                SELECT ac.id, ac.nome AS academia_nome, ass.nome AS associacao_nome,
                       ass.id AS associacao_id, ass.id_federacao
                FROM academias ac
                JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ass.id = %s
                ORDER BY ac.nome
                """,
                (getattr(current_user, "id_associacao", 0),),
            )
        elif current_user.has_role("gestor_academia") and ids_acad:
            # Gestor: academias de usuarios_academias ou id_academia
            ph = ",".join(["%s"] * len(ids_acad))
            cursor.execute(
                f"""
                SELECT ac.id, ac.nome AS academia_nome, ass.nome AS associacao_nome,
                       ass.id AS associacao_id, ass.id_federacao
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ac.id IN ({ph})
                ORDER BY ac.nome
                """,
                tuple(ids_acad),
            )
        else:
            cursor.execute(
                """
                SELECT ac.id, ac.nome AS academia_nome, ass.nome AS associacao_nome,
                       ass.id AS associacao_id, ass.id_federacao
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ac.id = %s
                """,
                (getattr(current_user, "id_academia", 0),),
            )
        academias = cursor.fetchall()
    except Exception:
        academias = []

    if request.method == "POST":
        form = request.form

        # Garantir que valores vazios sejam None (NULL no banco)
        nome = (form.get("nome", "") or "").strip() or None
        data_nascimento = form.get("data_nascimento") or None
        if data_nascimento == "":
            data_nascimento = None
        sexo = form.get("sexo") or None
        if sexo == "":
            sexo = None
        status = "ativo"
        # Campo ativo: se não informado, usa 1 (padrão da coluna não permite NULL)
        ativo_val = form.get("ativo")
        if ativo_val == "" or ativo_val is None:
            ativo = 1  # Valor padrão quando não informado
        elif ativo_val == "1" or ativo_val == "on":
            ativo = 1
        elif ativo_val == "0" or ativo_val == "off":
            ativo = 0
        else:
            ativo = 1  # Valor padrão quando não informado
        data_matricula = date.today().strftime("%Y-%m-%d")
        graduacao_id_raw = form.get("graduacao_id") or None
        if graduacao_id_raw == "":
            graduacao_id_raw = None
        graduacao_id = int(graduacao_id_raw) if (graduacao_id_raw and str(graduacao_id_raw).isdigit()) else None
        TurmaID = form.get("TurmaID") or None
        if TurmaID == "":
            TurmaID = None

        # _clean_str já retorna None para valores vazios
        nacionalidade = _clean_str(form.get("nacionalidade"))
        nome_pai = _clean_str(form.get("nome_pai"))
        nome_mae = _clean_str(form.get("nome_mae"))

        cpf = normalizar_cpf(form.get("cpf"))
        rg = _clean_str(form.get("rg"))
        orgao_emissor = _clean_str(form.get("orgao_emissor"))
        rg_data_emissao = form.get("rg_data_emissao") or None
        if rg_data_emissao == "":
            rg_data_emissao = None

        cep = _clean_str(form.get("cep"))
        endereco = _clean_str(form.get("endereco"))  # mapeado para 'rua'
        numero = _clean_str(form.get("numero"))
        complemento = _clean_str(form.get("complemento"))
        bairro = _clean_str(form.get("bairro"))
        cidade = _clean_str(form.get("cidade"))
        estado = _clean_str(form.get("estado"))

        responsavel_nome = _clean_str(form.get("responsavel_nome"))
        responsavel_parentesco = _clean_str(
            form.get("responsavel_parentesco") or form.get("responsavel_grau_parentesco")
        )

        email = _clean_str(form.get("email"))
        telefone_celular = _clean_str(form.get("telefone_celular"))
        telefone_residencial = _clean_str(form.get("telefone_residencial"))
        telefone_comercial = _clean_str(form.get("telefone_comercial"))
        telefone_outro = _clean_str(form.get("telefone_outro"))

        peso_str = form.get("peso") or None
        peso = None
        if peso_str and peso_str != "":
            try:
                peso = float(str(peso_str).replace(",", "."))
            except (ValueError, TypeError):
                peso = None

        ultimo_exame_faixa = form.get("ultimo_exame_faixa") or None
        if ultimo_exame_faixa == "":
            ultimo_exame_faixa = None

        zempo = _clean_str(form.get("zempo"))
        data_cadastro_zempo = form.get("data_cadastro_zempo") or None
        if data_cadastro_zempo == "":
            data_cadastro_zempo = None
        cadastro_zempo = form.get("cadastro_zempo") == "1"

        responsavel_financeiro_nome = _clean_str(form.get("responsavel_financeiro_nome"))
        responsavel_financeiro_cpf = normalizar_cpf(form.get("responsavel_financeiro_cpf"))

        observacoes = _clean_str(form.get("observacoes"))

        id_academia = form.get("id_academia") or getattr(current_user, "id_academia", None)
        modalidades_ids_raw = request.form.getlist("aluno_modalidade_ids")
        # Validar: só aceitar modalidades ofertadas pela academia
        modalidades_ids = []
        if id_academia and modalidades_ids_raw:
            cursor.execute(
                "SELECT modalidade_id FROM academia_modalidades WHERE academia_id = %s",
                (id_academia,),
            )
            ids_validos = {r["modalidade_id"] for r in cursor.fetchall()}
            modalidades_ids = [int(x) for x in modalidades_ids_raw if str(x).strip().isdigit() and int(x) in ids_validos]
        else:
            modalidades_ids = [int(x) for x in modalidades_ids_raw if str(x).strip().isdigit()]

        # Graduação só pode ser genérica (modalidade_id NULL) ou da modalidade selecionada.
        if graduacao_id:
            try:
                cursor.execute("SELECT modalidade_id FROM graduacao WHERE id = %s", (graduacao_id,))
                g_sel = cursor.fetchone()
                if not g_sel:
                    graduacao_id = None
                else:
                    mod_grad = g_sel.get("modalidade_id")
                    if mod_grad is not None and int(mod_grad) not in modalidades_ids:
                        graduacao_id = None
            except Exception:
                pass

        # Foto
        foto_dataurl = form.get("foto")  # base64
        foto_arquivo = request.files.get("foto_arquivo")
        id_associacao = getattr(current_user, "id_associacao", None)
        id_federacao = getattr(current_user, "id_federacao", None)
        if id_academia:
            cursor.execute(
                """
                SELECT ac.id_associacao, ass.id_federacao
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ac.id = %s
                """,
                (id_academia,),
            )
            row = cursor.fetchone()
            if row:
                id_associacao = row.get("id_associacao")
                id_federacao = row.get("id_federacao")

        cursor.execute("SHOW COLUMNS FROM alunos")
        colunas_alunos = {row["Field"] for row in cursor.fetchall()}

        # Regra: CPF obrigatório (aluno ou responsável financeiro)
        cpf_aluno_valido = validar_cpf(cpf)
        cpf_resp_valido = validar_cpf(responsavel_financeiro_cpf)

        if not (cpf_aluno_valido or cpf_resp_valido):
            flash(
                "Informe CPF válido do aluno ou do responsável financeiro.",
                "danger",
            )
            db.close()
            return render_template(
                "alunos/cadastro_aluno.html",
                graduacoes=graduacoes,
                turmas=turmas,
                modalidades=modalidades,
                academias=academias,
                back_url=back_url,
                form_data=form,
                academia_selecionada=form.get("id_academia") or request.args.get("academia_id"),
                aluno=None,
            )

        if cpf_aluno_valido:
            cpf_digits = "".join(filter(str.isdigit, str(cpf)))
            cursor.execute(
                """
                SELECT id, nome, cpf
                FROM alunos
                WHERE REPLACE(REPLACE(REPLACE(cpf, '.', ''), '-', ''), ' ', '') = %s
                """,
                (cpf_digits,),
            )
            existente = cursor.fetchone()
            if existente:
                flash(
                    f"CPF já cadastrado para o aluno \"{existente['nome']}\" (ID {existente['id']}).",
                    "danger",
                )
                db.close()
                return render_template(
                    "alunos/cadastro_aluno.html",
                    graduacoes=graduacoes,
                    turmas=turmas,
                    modalidades=modalidades,
                    academias=academias,
                    back_url=back_url,
                    form_data=form,
                    academia_selecionada=form.get("id_academia") or request.args.get("academia_id"),
                    aluno=None,
                )

        # Regra: aluno menor precisa CPF válido do responsável financeiro
        try:
            nasc_data = (
                datetime.strptime(data_nascimento, "%Y-%m-%d").date()
                if data_nascimento
                else None
            )
        except Exception:
            nasc_data = None

        if nasc_data:
            hoje = date.today()
            idade = hoje.year - nasc_data.year - (
                (hoje.month, hoje.day) < (nasc_data.month, nasc_data.day)
            )
            if idade < 18 and not cpf_resp_valido:
                flash(
                    "Aluno menor: informe CPF válido do responsável financeiro.",
                    "danger",
                )
                db.close()
                return render_template(
                    "alunos/cadastro_aluno.html",
                    graduacoes=graduacoes,
                    turmas=turmas,
                    modalidades=modalidades,
                    academias=academias,
                    back_url=back_url,
                    form_data=form,
                    academia_selecionada=form.get("id_academia") or request.args.get("academia_id"),
                    aluno=None,
                )

        if not cadastro_zempo:
            zempo = None
            data_cadastro_zempo = None

        try:
            # 1) Inserir aluno sem foto (para pegar o ID)
            cursor_insert = db.cursor()
            cursor_insert.execute(
                """
                INSERT INTO alunos (
                    nome, data_nascimento, sexo,
                    status, ativo, data_matricula,
                    graduacao_id, peso, zempo,
                    telefone, email, observacoes, ultimo_exame_faixa,
                    TurmaID, cpf, id_academia, id_associacao, id_federacao,
                    nome_pai, nome_mae, responsavel_nome, responsavel_parentesco,
                    nacionalidade, rg, orgao_emissor, rg_data_emissao,
                    cep, rua, numero, complemento, bairro, cidade, estado,
                    tel_residencial, tel_comercial, tel_celular, tel_outro,
                    responsavel_financeiro_nome, responsavel_financeiro_cpf
                )
                VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s
                )
                """,
                (
                    nome,
                    data_nascimento,
                    sexo,
                    status,
                    ativo,
                    data_matricula,
                    graduacao_id,
                    peso,
                    zempo,
                    telefone_celular,  # telefone principal
                    email,
                    observacoes,
                    ultimo_exame_faixa,
                    TurmaID,
                    cpf,
                    id_academia,
                    id_associacao,
                    id_federacao,
                    nome_pai,
                    nome_mae,
                    responsavel_nome,
                    responsavel_parentesco,
                    nacionalidade,
                    rg,
                    orgao_emissor,
                    rg_data_emissao,
                    cep,
                    endereco,
                    numero,
                    complemento,
                    bairro,
                    cidade,
                    estado,
                    telefone_residencial,
                    telefone_comercial,
                    telefone_celular,
                    telefone_outro,
                    responsavel_financeiro_nome,
                    responsavel_financeiro_cpf,
                ),
            )
            aluno_id = cursor_insert.lastrowid

            # 2) Modalidades (N:N)
            if modalidades_ids:
                for mid in modalidades_ids:
                    if mid:
                        cursor_insert.execute(
                            """
                            INSERT INTO aluno_modalidades (aluno_id, modalidade_id)
                            VALUES (%s, %s)
                            """,
                            (aluno_id, mid),
                        )

            # 3) Foto (se enviada)
            foto_filename = None
            if foto_dataurl:
                foto_filename = salvar_imagem_base64(foto_dataurl, f"aluno_{aluno_id}")
            elif foto_arquivo:
                foto_filename = salvar_arquivo_upload(
                    foto_arquivo, f"aluno_{aluno_id}"
                )

            if foto_filename:
                cursor_insert.execute(
                    "UPDATE alunos SET foto=%s WHERE id=%s",
                    (foto_filename, aluno_id),
                )

            if "data_cadastro_zempo" in colunas_alunos:
                cursor_insert.execute(
                    "UPDATE alunos SET data_cadastro_zempo=%s WHERE id=%s",
                    (data_cadastro_zempo, aluno_id),
                )

            db.commit()
            flash(f'Aluno "{nome}" cadastrado com sucesso!', "success")
            redirect_url = request.form.get("next") or back_url
            return redirect(redirect_url)

        except Exception as e:
            db.rollback()
            msg = str(e)
            if "Duplicate entry" in msg and (
                "responsavel_financeiro" in msg.lower() or "financeiro_cpf" in msg.lower()
            ):
                flash(
                    "O banco ainda impede usar o mesmo CPF de responsável financeiro em mais de um aluno. "
                    "Execute no servidor: .venv/bin/python migrations/executar_drop_unique_responsavel_financeiro_cpf.py",
                    "danger",
                )
            elif "Duplicate entry" in msg and "unq_cpf" in msg:
                flash(
                    "CPF do aluno já está cadastrado para outro aluno. Cada aluno deve ter CPF próprio; "
                    "o CPF do pai/mãe vai apenas no campo do responsável financeiro.",
                    "danger",
                )
            else:
                flash(f"Erro ao cadastrar aluno: {e}", "danger")
            academia_selecionada = form.get("id_academia") or request.args.get("academia_id")
            db.close()
            return render_template(
                "alunos/cadastro_aluno.html",
                graduacoes=graduacoes,
                turmas=turmas,
                modalidades=modalidades,
                academias=academias,
                back_url=back_url,
                form_data=form,
                academia_selecionada=academia_selecionada,
                aluno=None,
            )

    academia_selecionada = (
        request.args.get("academia_id")
        or session.get("academia_gerenciamento_id")
        or (ids_acad[0] if ids_acad else None)
        or getattr(current_user, "id_academia", None)
    )

    db.close()
    return render_template(
        "alunos/cadastro_aluno.html",
        graduacoes=graduacoes,
        turmas=turmas,
        modalidades=modalidades,
        academias=academias,
        back_url=back_url,
        academia_selecionada=academia_selecionada,
        aluno=None,
    )


# ======================================================
# 🔹 3. EDITAR ALUNO
# ======================================================

@bp_alunos.route("/editar_aluno/<int:aluno_id>", methods=["GET", "POST"])
@login_required
def editar_aluno(aluno_id):
    back_url = (
        request.args.get("next")
        or request.referrer
        or (url_for("painel_aluno.painel") if current_user.has_role("aluno") else url_for("alunos.lista_alunos"))
    )

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT a.*,
                   ac.nome  AS academia_nome,
                   ass.nome AS associacao_nome,
                   fed.nome AS federacao_nome
            FROM alunos a
            LEFT JOIN academias ac   ON a.id_academia = ac.id
            LEFT JOIN associacoes ass ON a.id_associacao = ass.id
            LEFT JOIN federacoes fed ON a.id_federacao = fed.id
            WHERE a.id = %s
            """,
            (aluno_id,),
        )
        aluno = cursor.fetchone()
    except Exception as e:
        if db:
            db.close()
        flash("Erro ao carregar aluno. Tente novamente.", "danger")
        if current_user.has_role("aluno"):
            return redirect(url_for("painel_aluno.painel"))
        return redirect(url_for("alunos.lista_alunos"))

    if not aluno:
        flash("Aluno não encontrado.", "danger")
        db.close()
        return redirect(url_for("alunos.lista_alunos"))

    # Permissões para editar
    pode_editar = (
        current_user.has_role("admin")
        or (
            current_user.has_role("gestor_academia")
            and aluno.get("id_academia") == getattr(current_user, "id_academia", None)
        )
        or (
            current_user.has_role("aluno")
            and aluno.get("usuario_id") == current_user.id
        )
        or (
            current_user.has_role("responsavel")
            and _eh_responsavel_aluno(cursor, current_user.id, aluno_id)
        )
    )

    if not pode_editar:
        flash("Você não tem permissão para editar este aluno.", "danger")
        db.close()
        if current_user.has_role("aluno"):
            return redirect(url_for("painel_aluno.painel"))
        if current_user.has_role("responsavel"):
            return redirect(url_for("painel_responsavel.meu_perfil"))
        return redirect(url_for("alunos.lista_alunos"))

    graduacoes = []
    turmas = []
    modalidades = []
    aluno["modalidades_ids"] = []

    try:
        try:
            # Filtra inativas, mas mantém a graduação atual do aluno mesmo inativa.
            grad_atual_id = aluno.get("graduacao_id")
            if grad_atual_id:
                cursor.execute(
                    """
                    SELECT g.*, g.modalidade_id
                    FROM graduacao g
                    WHERE COALESCE(g.ativo, 1) = 1 OR g.id = %s
                    ORDER BY COALESCE(NULLIF(g.ordem,0), g.id), g.id
                    """,
                    (grad_atual_id,),
                )
            else:
                cursor.execute(
                    """
                    SELECT g.*, g.modalidade_id
                    FROM graduacao g
                    WHERE COALESCE(g.ativo, 1) = 1
                    ORDER BY COALESCE(NULLIF(g.ordem,0), g.id), g.id
                    """
                )
            graduacoes = cursor.fetchall()
        except Exception:
            cursor.execute("SELECT * FROM graduacao ORDER BY id")
            graduacoes = cursor.fetchall()
    except Exception:
        pass

    try:
        # Filtrar turmas apenas das academias acessíveis ao usuário
        ids_acad = _get_academias_ids()
        if ids_acad:
            # Se o aluno já tem uma academia, usar ela se estiver acessível
            aluno_academia_id = aluno.get("id_academia")
            if aluno_academia_id and aluno_academia_id in ids_acad:
                cursor.execute("SELECT * FROM turmas WHERE id_academia = %s ORDER BY Nome", (aluno_academia_id,))
            else:
                # Filtrar por todas as academias acessíveis
                placeholders = ",".join(["%s"] * len(ids_acad))
                cursor.execute(f"SELECT * FROM turmas WHERE id_academia IN ({placeholders}) ORDER BY Nome", tuple(ids_acad))
            turmas = cursor.fetchall()
        else:
            # Sem academias acessíveis, retornar lista vazia
            turmas = []
    except Exception:
        turmas = []

    try:
        id_acad = aluno.get("id_academia")
        if id_acad:
            cursor.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_acad,))
            r = cursor.fetchone()
            id_assoc = r.get("id_associacao") if r else None
            extra, extra_params = filtro_visibilidade_sql(id_academia=id_acad, id_associacao=id_assoc)
            cursor.execute(
                """
                SELECT m.id, m.nome, m.descricao, m.ativo
                FROM modalidade m
                INNER JOIN academia_modalidades am ON am.modalidade_id = m.id
                WHERE am.academia_id = %s AND m.ativo = 1
                """ + extra + """
                ORDER BY m.nome
                """,
                (id_acad,) + extra_params,
            )
            modalidades = cursor.fetchall()
        else:
            cursor.execute("SELECT id, nome, descricao, ativo FROM modalidade WHERE ativo = 1 ORDER BY nome")
            modalidades = cursor.fetchall()
    except Exception:
        modalidades = []

    try:
        cursor.execute(
            "SELECT modalidade_id FROM aluno_modalidades WHERE aluno_id = %s",
            (aluno_id,),
        )
        aluno["modalidades_ids"] = [row["modalidade_id"] for row in cursor.fetchall()]
    except Exception:
        pass

    aluno["turmas_ids"] = []
    try:
        cursor.execute(
            "SELECT TurmaID FROM aluno_turmas WHERE aluno_id = %s",
            (aluno_id,),
        )
        aluno["turmas_ids"] = [row["TurmaID"] for row in cursor.fetchall()]
    except Exception:
        pass
    if not aluno["turmas_ids"] and aluno.get("TurmaID"):
        aluno["turmas_ids"] = [aluno["TurmaID"]]

    # Mapear rua -> endereco (para o template)
    aluno["endereco"] = aluno.get("rua")

    if request.method == "POST":
        form = request.form

        nome = form.get("nome", "").strip()
        data_nascimento = form.get("data_nascimento") or None
        sexo = form.get("sexo") or None
        data_matricula = aluno.get("data_matricula")
        graduacao_id_raw = form.get("graduacao_id") or None
        graduacao_id = int(graduacao_id_raw) if (graduacao_id_raw and str(graduacao_id_raw).isdigit()) else None
        # Turma e modalidade: só gestor/academy pode alterar; aluno/responsavel mantêm os atuais
        pode_alterar_turma_mod = current_user.has_role("admin") or current_user.has_role("gestor_academia")
        if pode_alterar_turma_mod:
            turmas_ids = [int(x) for x in form.getlist("turmas_ids") if x and str(x).isdigit()]
        else:
            turmas_ids = aluno.get("turmas_ids") or []
            if not turmas_ids and aluno.get("TurmaID"):
                turmas_ids = [aluno["TurmaID"]]
        TurmaID = turmas_ids[0] if turmas_ids else form.get("TurmaID") or None

        nacionalidade = _clean_str(form.get("nacionalidade"))
        nome_pai = _clean_str(form.get("nome_pai"))
        nome_mae = _clean_str(form.get("nome_mae"))

        cpf = normalizar_cpf(form.get("cpf"))
        rg = _clean_str(form.get("rg"))
        orgao_emissor = _clean_str(form.get("orgao_emissor"))
        rg_data_emissao = form.get("rg_data_emissao") or None

        cep = _clean_str(form.get("cep"))
        endereco = _clean_str(form.get("endereco"))  # rua
        numero = _clean_str(form.get("numero"))
        complemento = _clean_str(form.get("complemento"))
        bairro = _clean_str(form.get("bairro"))
        cidade = _clean_str(form.get("cidade"))
        estado = _clean_str(form.get("estado"))

        responsavel_nome = _clean_str(form.get("responsavel_nome"))
        responsavel_parentesco = _clean_str(
            form.get("responsavel_parentesco") or form.get("responsavel_grau_parentesco")
        )

        email = _clean_str(form.get("email"))
        telefone_celular = _clean_str(form.get("telefone_celular"))
        telefone_residencial = _clean_str(form.get("telefone_residencial"))
        telefone_comercial = _clean_str(form.get("telefone_comercial"))
        telefone_outro = _clean_str(form.get("telefone_outro"))

        peso_str = form.get("peso") or None
        peso = None
        if peso_str:
            peso = float(str(peso_str).replace(",", "."))

        ultimo_exame_faixa = form.get("ultimo_exame_faixa") or None

        zempo = _clean_str(form.get("zempo"))
        data_cadastro_zempo = form.get("data_cadastro_zempo") or None
        cadastro_zempo = form.get("cadastro_zempo") == "1"
        if not cadastro_zempo:
            zempo = None
            data_cadastro_zempo = None

        responsavel_financeiro_nome = _clean_str(form.get("responsavel_financeiro_nome"))
        responsavel_financeiro_cpf = normalizar_cpf(form.get("responsavel_financeiro_cpf"))

        observacoes = _clean_str(form.get("observacoes"))
        
        # Campo ativo: se não informado, usa 1 (padrão da coluna não permite NULL)
        ativo_val = form.get("ativo")
        if ativo_val == "" or ativo_val is None:
            ativo = 1  # Valor padrão quando não informado
        elif ativo_val == "1" or ativo_val == "on":
            ativo = 1
        elif ativo_val == "0" or ativo_val == "off":
            ativo = 0
        else:
            ativo = 1  # Valor padrão quando não informado

        if pode_alterar_turma_mod:
            modalidades_ids_raw = request.form.getlist("aluno_modalidade_ids")
            id_acad = aluno.get("id_academia")
            if id_acad:
                cursor.execute(
                    "SELECT modalidade_id FROM academia_modalidades WHERE academia_id = %s",
                    (id_acad,),
                )
                ids_validos = {r["modalidade_id"] for r in cursor.fetchall()}
                modalidades_ids = [str(x) for x in modalidades_ids_raw if str(x).strip().isdigit() and int(x) in ids_validos]
            else:
                modalidades_ids = [x for x in modalidades_ids_raw if str(x).strip()]
        else:
            modalidades_ids = [str(x) for x in (aluno.get("modalidades_ids") or [])]

        if graduacao_id:
            try:
                cursor.execute("SELECT modalidade_id FROM graduacao WHERE id = %s", (graduacao_id,))
                g_sel = cursor.fetchone()
                if not g_sel:
                    graduacao_id = None
                else:
                    mod_grad = g_sel.get("modalidade_id")
                    if mod_grad is not None and int(mod_grad) not in [int(x) for x in modalidades_ids]:
                        graduacao_id = None
            except Exception:
                pass

        # Foto
        foto_dataurl = form.get("foto")
        foto_arquivo = request.files.get("foto_arquivo")
        foto_atual = aluno.get("foto")

        foto_filename = foto_atual
        if foto_dataurl:
            foto_filename = salvar_imagem_base64(foto_dataurl, f"aluno_{aluno_id}")
        elif foto_arquivo:
            foto_filename = salvar_arquivo_upload(foto_arquivo, f"aluno_{aluno_id}")

        cursor.execute("SHOW COLUMNS FROM alunos")
        colunas_alunos = {row["Field"] for row in cursor.fetchall()}

        try:
            # Atualizar aluno
            cursor_update = db.cursor()
            cursor_update.execute(
                """
                UPDATE alunos SET
                    nome=%s,
                    data_nascimento=%s,
                    sexo=%s,
                    graduacao_id=%s,
                    peso=%s,
                    zempo=%s,
                    telefone=%s,
                    email=%s,
                    observacoes=%s,
                    ultimo_exame_faixa=%s,
                    TurmaID=%s,
                    cpf=%s,
                    nome_pai=%s,
                    nome_mae=%s,
                    responsavel_nome=%s,
                    responsavel_parentesco=%s,
                    nacionalidade=%s,
                    rg=%s,
                    orgao_emissor=%s,
                    rg_data_emissao=%s,
                    cep=%s,
                    rua=%s,
                    numero=%s,
                    complemento=%s,
                    bairro=%s,
                    cidade=%s,
                    estado=%s,
                    tel_residencial=%s,
                    tel_comercial=%s,
                    tel_celular=%s,
                    tel_outro=%s,
                    responsavel_financeiro_nome=%s,
                    responsavel_financeiro_cpf=%s,
                    foto=%s,
                    ativo=%s
                WHERE id=%s
                """,
                (
                    nome,
                    data_nascimento,
                    sexo,
                    graduacao_id,
                    peso,
                    zempo,
                    telefone_celular,
                    email,
                    observacoes,
                    ultimo_exame_faixa,
                    TurmaID,
                    cpf,
                    nome_pai,
                    nome_mae,
                    responsavel_nome,
                    responsavel_parentesco,
                    nacionalidade,
                    rg,
                    orgao_emissor,
                    rg_data_emissao,
                    cep,
                    endereco,
                    numero,
                    complemento,
                    bairro,
                    cidade,
                    estado,
                    telefone_residencial,
                    telefone_comercial,
                    telefone_celular,
                    telefone_outro,
                    responsavel_financeiro_nome,
                    responsavel_financeiro_cpf,
                    foto_filename,
                    ativo,
                    aluno_id,
                ),
            )

            if "data_cadastro_zempo" in colunas_alunos:
                cursor_update.execute(
                    "UPDATE alunos SET data_cadastro_zempo=%s WHERE id=%s",
                    (data_cadastro_zempo, aluno_id),
                )

            # Sincronizar foto com o usuário vinculado (se houver)
            if foto_filename and foto_filename != foto_atual:
                try:
                    cursor_update.execute(
                        "UPDATE usuarios u "
                        "JOIN alunos a ON a.usuario_id = u.id "
                        "SET u.foto = %s "
                        "WHERE a.id = %s AND a.usuario_id IS NOT NULL",
                        (foto_filename, aluno_id),
                    )
                except Exception:
                    pass

            # Atualizar modalidades N:N
            cursor_update.execute(
                "DELETE FROM aluno_modalidades WHERE aluno_id = %s", (aluno_id,)
            )
            if modalidades_ids:
                for mid in modalidades_ids:
                    if mid:
                        cursor_update.execute(
                            """
                            INSERT INTO aluno_modalidades (aluno_id, modalidade_id)
                            VALUES (%s, %s)
                            """,
                            (aluno_id, mid),
                        )

            # Atualizar aluno_turmas N:N (múltiplas turmas)
            try:
                cursor_update.execute(
                    "DELETE FROM aluno_turmas WHERE aluno_id = %s", (aluno_id,)
                )
                for tid in turmas_ids:
                    if tid:
                        cursor_update.execute(
                            "INSERT IGNORE INTO aluno_turmas (aluno_id, TurmaID) VALUES (%s, %s)",
                            (aluno_id, tid),
                        )
            except Exception:
                pass

            db.commit()
            flash(f'Dados do aluno "{nome}" atualizados com sucesso!', "success")
            db.close()
            redirect_url = request.form.get("next") or back_url
            return redirect(redirect_url)

        except Exception as e:
            db.rollback()
            msg = str(e)
            if "Duplicate entry" in msg and (
                "responsavel_financeiro" in msg.lower() or "financeiro_cpf" in msg.lower()
            ):
                flash(
                    "O banco ainda impede repetir o CPF do responsável financeiro. "
                    "Execute: .venv/bin/python migrations/executar_drop_unique_responsavel_financeiro_cpf.py",
                    "danger",
                )
            elif "Duplicate entry" in msg and "unq_cpf" in msg:
                flash(
                    "CPF do aluno já está cadastrado para outro aluno.",
                    "danger",
                )
            else:
                flash(f"Erro ao atualizar aluno: {e}", "danger")

    # Para aluno/responsável: exibir turmas e modalidades em texto (somente leitura)
    turmas_ids = aluno.get("turmas_ids") or []
    if not turmas_ids and aluno.get("TurmaID"):
        turmas_ids = [aluno["TurmaID"]]
    turmas_display = ", ".join(
        t.get("Nome", "") or "" for t in turmas if t.get("TurmaID") in turmas_ids
    ) if turmas else "—"
    modalidades_ids = aluno.get("modalidades_ids") or []
    modalidades_display = ", ".join(
        m.get("nome", "") or "" for m in modalidades if m.get("id") in modalidades_ids
    ) if modalidades else "—"

    db.close()
    return render_template(
        "alunos/editar_aluno.html",
        aluno=aluno,
        graduacoes=graduacoes,
        turmas=turmas,
        modalidades=modalidades,
        turmas_display=turmas_display,
        modalidades_display=modalidades_display,
        back_url=back_url,
    )


# ======================================================
# 🔹 4. EXCLUIR ALUNO
# ======================================================

@bp_alunos.route("/excluir_aluno/<int:aluno_id>", methods=["POST"])
@login_required
def excluir_aluno(aluno_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, nome, id_academia FROM alunos WHERE id = %s", (aluno_id,)
    )
    aluno = cursor.fetchone()

    if not aluno:
        flash("Aluno não encontrado.", "danger")
        db.close()
        return redirect(url_for("alunos.lista_alunos"))

    pode_excluir = current_user.has_role("admin") or (
        current_user.has_role("gestor_academia")
        and aluno["id_academia"] == getattr(current_user, "id_academia", None)
    )

    if not pode_excluir:
        flash("Você não tem permissão para excluir este aluno.", "danger")
        db.close()
        return redirect(url_for("alunos.lista_alunos"))

    try:
        # aluno_modalidades tem ON DELETE CASCADE, mas não custa garantir:
        cursor.execute("DELETE FROM aluno_modalidades WHERE aluno_id = %s", (aluno_id,))
        cursor.execute("DELETE FROM alunos WHERE id = %s", (aluno_id,))
        db.commit()
        flash(f'Aluno "{aluno["nome"]}" excluído com sucesso!', "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao excluir aluno: {e}", "danger")

    db.close()
    return redirect(url_for("alunos.lista_alunos"))


@bp_alunos.route("/alterar_status_aluno/<int:aluno_id>", methods=["POST"])
@login_required
def alterar_status_aluno(aluno_id):
    destino_ativo = 1 if str(request.form.get("ativo_destino") or "1") == "1" else 0
    next_url = (request.form.get("next") or "").strip()

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nome, id_academia, COALESCE(ativo,1) AS ativo FROM alunos WHERE id = %s", (aluno_id,))
        aluno = cursor.fetchone()
        if not aluno:
            flash("Aluno não encontrado.", "danger")
            return redirect(next_url) if (next_url.startswith("/") and "//" not in next_url) else redirect(url_for("alunos.lista_alunos"))

        ids_acessiveis = set(_get_academias_ids() or [])
        pode_gerenciar = current_user.has_role("admin") or (aluno.get("id_academia") in ids_acessiveis)
        if not pode_gerenciar:
            flash("Você não tem permissão para alterar este aluno.", "danger")
            return redirect(next_url) if (next_url.startswith("/") and "//" not in next_url) else redirect(url_for("alunos.lista_alunos"))

        status_txt = "ativo" if destino_ativo == 1 else "inativo"
        cursor.execute(
            "UPDATE alunos SET ativo = %s, status = %s, "
            "data_inativacao = CASE WHEN %s = 0 THEN CURDATE() ELSE NULL END WHERE id = %s",
            (destino_ativo, status_txt, destino_ativo, aluno_id),
        )

        if destino_ativo == 0:
            cancelar = str(request.form.get("cancelar_mensalidades") or "").strip() in ("1", "on", "true")
            if cancelar:
                hoje = date.today()
                mes_cancel = request.form.get("mes_cancelamento", type=int) or hoje.month
                ano_cancel = request.form.get("ano_cancelamento", type=int) or hoje.year
                if not (1 <= mes_cancel <= 12):
                    mes_cancel = hoje.month
                if ano_cancel < 2000 or ano_cancel > 2100:
                    ano_cancel = hoje.year
                data_inicio = date(ano_cancel, mes_cancel, 1)
                cursor.execute(
                    """
                    UPDATE mensalidade_aluno ma
                    JOIN mensalidades m ON m.id = ma.mensalidade_id
                    SET ma.status = 'cancelado'
                    WHERE ma.aluno_id = %s
                      AND ma.status != 'cancelado'
                      AND ma.data_vencimento >= %s
                      AND m.id_academia = %s
                    """,
                    (aluno_id, data_inicio, aluno.get("id_academia")),
                )
                canceladas = cursor.rowcount or 0
                flash(
                    f'Aluno "{aluno.get("nome")}" inativado. {canceladas} mensalidade(s) cancelada(s) a partir de {mes_cancel:02d}/{ano_cancel}.',
                    "warning",
                )
            else:
                flash(f'Aluno "{aluno.get("nome")}" inativado com sucesso.', "warning")
        else:
            hoje = date.today()
            turma_id = request.form.get("turma_id", type=int)
            if not turma_id:
                flash("Selecione a turma para reativar o aluno.", "danger")
                return redirect(next_url) if (next_url.startswith("/") and "//" not in next_url) else redirect(url_for("alunos.lista_alunos"))

            if not aluno.get("id_academia"):
                flash("Aluno sem academia vinculada; não é possível definir turma.", "danger")
                return redirect(next_url) if (next_url.startswith("/") and "//" not in next_url) else redirect(url_for("alunos.lista_alunos"))

            cursor.execute(
                "SELECT TurmaID FROM turmas WHERE TurmaID = %s AND id_academia = %s",
                (turma_id, aluno.get("id_academia")),
            )
            if not cursor.fetchone():
                flash("Turma inválida para a academia deste aluno.", "danger")
                return redirect(next_url) if (next_url.startswith("/") and "//" not in next_url) else redirect(url_for("alunos.lista_alunos"))

            gerar_mens = str(request.form.get("gerar_mensalidade") or "").strip() in ("1", "on", "true")
            plano_id = None
            valor_plano = 0.0
            mes_ini = hoje.month
            ano_ref = hoje.year
            dia_venc = 10
            if gerar_mens:
                plano_id = request.form.get("mensalidade_id", type=int)
                if not plano_id:
                    flash("Selecione o plano para gerar a mensalidade ou desmarque a opção.", "danger")
                    return redirect(next_url) if (next_url.startswith("/") and "//" not in next_url) else redirect(url_for("alunos.lista_alunos"))
                cursor.execute(
                    "SELECT id, nome, valor FROM mensalidades WHERE id = %s AND id_academia = %s",
                    (plano_id, aluno.get("id_academia")),
                )
                plano_row = cursor.fetchone()
                if not plano_row:
                    flash("Plano de mensalidade não encontrado para esta academia.", "danger")
                    return redirect(next_url) if (next_url.startswith("/") and "//" not in next_url) else redirect(url_for("alunos.lista_alunos"))
                valor_plano = float(plano_row.get("valor", 0) or 0)
                ano_ref = request.form.get("ano_ref", type=int) or hoje.year
                mes_ini = request.form.get("mes_inicial", type=int) or hoje.month
                if mes_ini < 1 or mes_ini > 12:
                    mes_ini = hoje.month
                if ano_ref < 2000 or ano_ref > 2100:
                    ano_ref = hoje.year
                dia_venc = min(28, max(1, request.form.get("dia_vencimento", type=int) or 10))

            cursor.execute(
                "UPDATE alunos SET ativo = %s, status = %s, TurmaID = %s WHERE id = %s",
                (destino_ativo, status_txt, turma_id, aluno_id),
            )
            try:
                cursor.execute(
                    "INSERT IGNORE INTO aluno_turmas (aluno_id, TurmaID) VALUES (%s, %s)",
                    (aluno_id, turma_id),
                )
            except Exception:
                pass

            msg_extra = []
            if gerar_mens and plano_id:
                dias_por_mes = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 31, 12: 31}
                dia = min(dia_venc, dias_por_mes.get(mes_ini, 28))
                data_venc = date(ano_ref, mes_ini, dia)
                data_venc_s = data_venc.strftime("%Y-%m-%d")
                cursor.execute(
                    """SELECT 1 FROM mensalidade_aluno
                       WHERE aluno_id = %s AND mensalidade_id = %s
                       AND data_vencimento = %s AND status != 'cancelado'""",
                    (aluno_id, plano_id, data_venc_s),
                )
                if cursor.fetchone():
                    msg_extra.append(
                        f"Já existia mensalidade em {mes_ini:02d}/{ano_ref}; nenhuma nova cobrança criada."
                    )
                else:
                    cursor.execute(
                        """INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, turma_id, data_vencimento, valor, status)
                           VALUES (%s, %s, %s, %s, %s, 'pendente')""",
                        (plano_id, aluno_id, turma_id, data_venc_s, valor_plano),
                    )
                    msg_extra.append(f"Mensalidade gerada ({mes_ini:02d}/{ano_ref}).")

            flash(
                f'Aluno "{aluno.get("nome")}" reativado com turma definida.'
                + (" " + " ".join(msg_extra) if msg_extra else ""),
                "success",
            )

        db.commit()
    except Exception as e:
        db.rollback()
        flash(f"Erro ao alterar status do aluno: {e}", "danger")
    finally:
        db.close()

    if next_url.startswith("/") and "//" not in next_url:
        return redirect(next_url)
    return redirect(url_for("alunos.lista_alunos"))


@bp_alunos.route("/turmas-matricula/<int:aluno_id>", methods=["GET"])
@login_required
def turmas_matricula_json(aluno_id):
    """JSON: turmas matriculadas, disponíveis na academia e planos (modal matrícula — modo academia)."""
    if not _permite_modal_matricula_turma():
        return (
            jsonify({"ok": False, "msg": "Disponível apenas no modo academia."}),
            403,
        )
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, nome, id_academia, data_nascimento, TurmaID
            FROM alunos WHERE id = %s
            """,
            (aluno_id,),
        )
        aluno = cursor.fetchone()
        if not aluno:
            return jsonify({"ok": False, "msg": "Aluno não encontrado"}), 404
        if not _pode_gerenciar_aluno_academia(aluno.get("id_academia")):
            return jsonify({"ok": False, "msg": "Sem permissão"}), 403
        id_acad = aluno.get("id_academia")

        matriculadas = []
        try:
            cursor.execute(
                """
                SELECT t.TurmaID AS turma_id, t.Nome AS nome
                FROM aluno_turmas at
                JOIN turmas t ON t.TurmaID = at.TurmaID
                WHERE at.aluno_id = %s
                ORDER BY t.Nome
                """,
                (aluno_id,),
            )
            matriculadas = cursor.fetchall() or []
        except Exception:
            matriculadas = []

        mat_ids = {m["turma_id"] for m in matriculadas}
        tid_leg = aluno.get("TurmaID")
        if tid_leg and tid_leg not in mat_ids:
            try:
                cursor.execute(
                    """
                    SELECT TurmaID AS turma_id, Nome AS nome FROM turmas
                    WHERE TurmaID = %s AND id_academia = %s
                    """,
                    (tid_leg, id_acad),
                )
                row_leg = cursor.fetchone()
                if row_leg:
                    matriculadas.append(row_leg)
                    mat_ids.add(tid_leg)
            except Exception:
                pass

        idade_aluno = _idade_anos_completa(aluno.get("data_nascimento"))
        todas = []
        try:
            cursor.execute(
                """
                SELECT TurmaID AS turma_id, Nome AS nome,
                       IdadeMin AS idade_min, IdadeMax AS idade_max
                FROM turmas WHERE id_academia = %s ORDER BY Nome
                """,
                (id_acad,),
            )
            todas = cursor.fetchall() or []
        except Exception:
            try:
                cursor.execute(
                    """
                    SELECT TurmaID AS turma_id, Nome AS nome
                    FROM turmas WHERE id_academia = %s ORDER BY Nome
                    """,
                    (id_acad,),
                )
                todas = cursor.fetchall() or []
                for row in todas:
                    row.setdefault("idade_min", None)
                    row.setdefault("idade_max", None)
            except Exception:
                todas = []

        disponiveis = []
        for t in todas:
            tid = t["turma_id"]
            if tid in mat_ids:
                continue
            imin, imax = t.get("idade_min"), t.get("idade_max")
            idade_ok = True
            if imin is not None or imax is not None:
                if idade_aluno is None:
                    idade_ok = False
                else:
                    lo = int(imin) if imin is not None else 0
                    hi = int(imax) if imax is not None else 999
                    idade_ok = lo <= idade_aluno <= hi
            disponiveis.append(
                {
                    "turma_id": int(tid) if tid is not None else None,
                    "nome": t["nome"],
                    "idade_min": imin,
                    "idade_max": imax,
                    "idade_ok": idade_ok,
                }
            )

        planos = []
        try:
            cursor.execute(
                """
                SELECT id, nome, valor FROM mensalidades
                WHERE id_academia = %s AND ativo = 1 ORDER BY nome
                """,
                (id_acad,),
            )
            rows_pl = cursor.fetchall() or []
        except Exception:
            try:
                cursor.execute(
                    """
                    SELECT id, nome, valor FROM mensalidades
                    WHERE id_academia = %s ORDER BY nome
                    """,
                    (id_acad,),
                )
                rows_pl = cursor.fetchall() or []
            except Exception:
                rows_pl = []
        for p in rows_pl:
            try:
                val = float(p.get("valor") or 0)
            except (TypeError, ValueError):
                val = 0.0
            planos.append(
                {
                    "id": p["id"],
                    "nome": p["nome"],
                    "valor": val,
                }
            )

        hoje = date.today()
        return jsonify(
            {
                "ok": True,
                "aluno": {"id": aluno["id"], "nome": aluno["nome"]},
                "matriculadas": [
                    {"turma_id": m["turma_id"], "nome": m["nome"]} for m in matriculadas
                ],
                "disponiveis": disponiveis,
                "planos": planos,
                "idade_aluno": idade_aluno,
                "hoje": {"mes": hoje.month, "ano": hoje.year},
            }
        )
    except Exception as e:
        try:
            current_app.logger.exception("turmas_matricula_json aluno_id=%s", aluno_id)
        except Exception:
            pass
        return (
            jsonify(
                {
                    "ok": False,
                    "msg": "Erro ao carregar dados da matrícula. Verifique se as tabelas turmas, aluno_turmas e mensalidades estão atualizadas.",
                }
            ),
            500,
        )
    finally:
        try:
            cursor.close()
            db.close()
        except Exception:
            pass


@bp_alunos.route(
    "/transferir-academia-associacao/<int:aluno_id>",
    methods=["POST"],
)
@login_required
def transferir_aluno_academia_associacao(aluno_id):
    """Modo associação: move aluno para outra academia da mesma associação; remove turmas e cancela mensalidades futuras na origem."""
    if not _pode_transferir_aluno_academia_modo_associacao():
        flash("Transferência disponível apenas no modo associação.", "danger")
        return redirect(url_for("alunos.lista_alunos"))

    destino_id = request.form.get("id_academia_destino", type=int)
    next_url = (request.form.get("next") or "").strip()
    if not destino_id:
        flash("Selecione a academia de destino.", "danger")
        return (
            redirect(next_url)
            if (next_url.startswith("/") and "//" not in next_url)
            else redirect(url_for("alunos.lista_alunos"))
        )

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT a.id, a.nome, a.id_academia, a.id_associacao, a.TurmaID
            FROM alunos a
            WHERE a.id = %s
            """,
            (aluno_id,),
        )
        aluno = cursor.fetchone()
        if not aluno:
            flash("Aluno não encontrado.", "danger")
            return redirect(url_for("alunos.lista_alunos"))

        origem_id = aluno.get("id_academia")
        if not origem_id:
            flash("Aluno sem academia de origem.", "danger")
            return redirect(url_for("alunos.lista_alunos"))

        if int(destino_id) == int(origem_id):
            flash("Selecione uma academia diferente da atual.", "warning")
            return (
                redirect(next_url)
                if (next_url.startswith("/") and "//" not in next_url)
                else redirect(url_for("alunos.lista_alunos"))
            )

        cursor.execute(
            "SELECT id, id_associacao FROM academias WHERE id IN (%s, %s)",
            (origem_id, destino_id),
        )
        rows_ac = cursor.fetchall()
        by_id = {int(r["id"]): r for r in rows_ac}
        if int(origem_id) not in by_id or int(destino_id) not in by_id:
            flash("Academia de origem ou destino inválida.", "danger")
            return redirect(url_for("alunos.lista_alunos"))

        assoc_orig = by_id[int(origem_id)].get("id_associacao")
        assoc_dest = by_id[int(destino_id)].get("id_associacao")
        if assoc_orig is None or assoc_dest is None or int(assoc_orig) != int(assoc_dest):
            flash("As duas academias precisam pertencer à mesma associação.", "danger")
            return redirect(url_for("alunos.lista_alunos"))

        if current_user.has_role("gestor_associacao"):
            uid_assoc = getattr(current_user, "id_associacao", None)
            if uid_assoc is None or int(uid_assoc) != int(assoc_orig):
                flash("Sem permissão para transferir este aluno.", "danger")
                return redirect(url_for("alunos.lista_alunos"))

        cursor.execute(
            """
            SELECT ac.id AS id_academia, ac.id_associacao, ass.id_federacao
            FROM academias ac
            LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
            WHERE ac.id = %s
            """,
            (destino_id,),
        )
        dest_meta = cursor.fetchone()
        if not dest_meta:
            flash("Academia de destino não encontrada.", "danger")
            return redirect(url_for("alunos.lista_alunos"))

        id_assoc_new = dest_meta.get("id_associacao")
        id_fed_new = dest_meta.get("id_federacao")

        cursor.execute("DELETE FROM aluno_turmas WHERE aluno_id = %s", (aluno_id,))

        cursor.execute(
            """
            UPDATE mensalidade_aluno ma
            INNER JOIN mensalidades m ON m.id = ma.mensalidade_id
            SET ma.status = 'cancelado'
            WHERE ma.aluno_id = %s
              AND m.id_academia = %s
              AND ma.status NOT IN ('cancelado', 'pago')
              AND ma.data_vencimento >= CURDATE()
            """,
            (aluno_id, origem_id),
        )
        n_cancel = cursor.rowcount or 0

        cursor.execute(
            """
            UPDATE alunos
            SET id_academia = %s,
                id_associacao = %s,
                id_federacao = %s,
                TurmaID = NULL
            WHERE id = %s
            """,
            (
                destino_id,
                id_assoc_new,
                id_fed_new,
                aluno_id,
            ),
        )

        db.commit()
        flash(
            f'Aluno "{aluno.get("nome")}" transferido. Turmas da academia anterior foram removidas. '
            f"{n_cancel} cobrança(s) de mensalidade com vencimento futuro na academia de origem foram canceladas. "
            "Na nova academia, conclua matrícula em turma e mensalidade.",
            "success",
        )
    except Exception as e:
        db.rollback()
        flash(f"Erro ao transferir aluno: {e}", "danger")
    finally:
        cursor.close()
        db.close()

    if next_url.startswith("/") and "//" not in next_url:
        return redirect(next_url)
    return redirect(url_for("alunos.lista_alunos"))


@bp_alunos.route("/matricular-turma/<int:aluno_id>", methods=["POST"])
@login_required
def matricular_turma_post(aluno_id):
    """Matricula o aluno em uma turma da própria academia; opcionalmente gera mensalidade."""
    if not _permite_modal_matricula_turma():
        return (
            jsonify({"ok": False, "msg": "Disponível apenas no modo academia."}),
            403,
        )
    data = request.get_json(silent=True) or {}
    try:
        turma_id = int(data.get("turma_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Selecione uma turma."}), 400
    excecao = bool(data.get("excecao_idade"))
    gerar_mens = bool(data.get("gerar_mensalidade"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, nome, id_academia, data_nascimento, TurmaID FROM alunos WHERE id = %s",
            (aluno_id,),
        )
        aluno = cursor.fetchone()
        if not aluno:
            return jsonify({"ok": False, "msg": "Aluno não encontrado"}), 404
        if not _pode_gerenciar_aluno_academia(aluno.get("id_academia")):
            return jsonify({"ok": False, "msg": "Sem permissão"}), 403

        cursor.execute(
            "SELECT id_academia, IdadeMin, IdadeMax, Nome FROM turmas WHERE TurmaID = %s",
            (turma_id,),
        )
        turma = cursor.fetchone()
        if not turma or str(turma.get("id_academia")) != str(aluno.get("id_academia")):
            return jsonify({"ok": False, "msg": "Turma inválida para este aluno."}), 400

        cursor.execute(
            "SELECT 1 FROM aluno_turmas WHERE aluno_id = %s AND TurmaID = %s",
            (aluno_id, turma_id),
        )
        if cursor.fetchone():
            return jsonify({"ok": False, "msg": "Aluno já matriculado nesta turma."}), 400
        if aluno.get("TurmaID") and int(aluno.get("TurmaID")) == int(turma_id):
            return jsonify({"ok": False, "msg": "Aluno já matriculado nesta turma."}), 400

        idade_min = turma.get("IdadeMin")
        idade_max = turma.get("IdadeMax")
        if not excecao and (idade_min is not None or idade_max is not None):
            idade_aluno = _idade_anos_completa(aluno.get("data_nascimento"))
            if idade_aluno is None:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "msg": "Aluno sem data de nascimento. Informe a data ou use exceção de idade.",
                        }
                    ),
                    400,
                )
            imin = int(idade_min) if idade_min is not None else 0
            imax = int(idade_max) if idade_max is not None else 999
            if idade_aluno < imin or idade_aluno > imax:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "msg": f"Idade fora da faixa da turma ({imin}–{imax} anos). Marque exceção se aplicável.",
                        }
                    ),
                    400,
                )

        hoje = date.today()
        plano_id = None
        valor_plano = 0.0
        mes_ini = hoje.month
        ano_ref = hoje.year
        dia_venc = 10
        if gerar_mens:
            try:
                plano_id = int(data.get("mensalidade_id"))
            except (TypeError, ValueError):
                return (
                    jsonify(
                        {
                            "ok": False,
                            "msg": "Selecione o plano de mensalidade ou desmarque a opção.",
                        }
                    ),
                    400,
                )
            cursor.execute(
                "SELECT id, nome, valor FROM mensalidades WHERE id = %s AND id_academia = %s",
                (plano_id, aluno.get("id_academia")),
            )
            plano_row = cursor.fetchone()
            if not plano_row:
                return jsonify({"ok": False, "msg": "Plano não encontrado."}), 400
            valor_plano = float(plano_row.get("valor", 0) or 0)
            ano_ref = int(data.get("ano_ref") or hoje.year)
            mes_ini = int(data.get("mes_inicial") or hoje.month)
            if mes_ini < 1 or mes_ini > 12:
                mes_ini = hoje.month
            if ano_ref < 2000 or ano_ref > 2100:
                ano_ref = hoje.year
            dia_venc = min(28, max(1, int(data.get("dia_vencimento") or 10)))

        cursor.execute(
            "INSERT INTO aluno_turmas (aluno_id, TurmaID) VALUES (%s, %s)",
            (aluno_id, turma_id),
        )
        if not aluno.get("TurmaID"):
            cursor.execute(
                "UPDATE alunos SET TurmaID = %s WHERE id = %s",
                (turma_id, aluno_id),
            )

        msg_extra = []
        if gerar_mens and plano_id:
            dias_por_mes = {
                1: 31,
                2: 28,
                3: 31,
                4: 30,
                5: 31,
                6: 30,
                7: 31,
                8: 31,
                9: 30,
                10: 31,
                11: 31,
                12: 31,
            }
            dia = min(dia_venc, dias_por_mes.get(mes_ini, 28))
            data_venc = date(ano_ref, mes_ini, dia)
            data_venc_s = data_venc.strftime("%Y-%m-%d")
            cursor.execute(
                """
                SELECT 1 FROM mensalidade_aluno
                WHERE aluno_id = %s AND mensalidade_id = %s
                AND data_vencimento = %s AND status != 'cancelado'
                """,
                (aluno_id, plano_id, data_venc_s),
            )
            if cursor.fetchone():
                msg_extra.append(
                    f"Já existia cobrança em {mes_ini:02d}/{ano_ref}; nenhuma mensalidade nova."
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO mensalidade_aluno (mensalidade_id, aluno_id, turma_id, data_vencimento, valor, status)
                    VALUES (%s, %s, %s, %s, %s, 'pendente')
                    """,
                    (plano_id, aluno_id, turma_id, data_venc_s, valor_plano),
                )
                msg_extra.append(f"Mensalidade gerada ({mes_ini:02d}/{ano_ref}).")

        db.commit()
        out = f'Matriculado em "{turma.get("Nome") or "turma"}".'
        if msg_extra:
            out += " " + " ".join(msg_extra)
        return jsonify({"ok": True, "msg": out})
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "msg": str(e)}), 500
    finally:
        cursor.close()
        db.close()


@bp_alunos.route("/historico_aulas/<int:aluno_id>", methods=["GET"])
@login_required
def historico_aulas(aluno_id):
    mes = request.args.get("mes", type=int) or date.today().month
    ano = request.args.get("ano", type=int) or date.today().year
    periodo = (request.args.get("periodo") or "mes").strip().lower()
    if periodo not in ("mes", "ano"):
        periodo = "mes"
    if not (1 <= mes <= 12):
        mes = date.today().month
    if ano < 2000 or ano > 2100:
        ano = date.today().year

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, id_academia FROM alunos WHERE id = %s", (aluno_id,))
        aluno = cursor.fetchone()
        if not aluno:
            return jsonify({"erro": "Aluno não encontrado"}), 404
        ids_acessiveis = set(_get_academias_ids() or [])
        if not current_user.has_role("admin") and aluno.get("id_academia") not in ids_acessiveis:
            return jsonify({"erro": "Sem permissão"}), 403

        base_sql = """
            SELECT p.data_presenca, p.presente, p.horario_aula,
                   COALESCE(t.Nome, '') AS turma_nome,
                   ra.observacao AS obs_aula,
                   po.observacao AS obs_aluno
            FROM presencas p
            LEFT JOIN turmas t ON t.TurmaID = p.turma_id
            LEFT JOIN registros_aula_presenca ra
                   ON ra.turma_id = p.turma_id
                  AND ra.data_aula = p.data_presenca
                  AND ra.horario_aula = p.horario_aula
            LEFT JOIN presencas_observacao_aluno po
                   ON po.aluno_id = p.aluno_id
                  AND po.turma_id = p.turma_id
                  AND po.data_aula = p.data_presenca
                  AND po.horario_aula = p.horario_aula
        """
        if periodo == "ano":
            cursor.execute(base_sql + """
                WHERE p.aluno_id = %s AND YEAR(p.data_presenca) = %s
                ORDER BY p.data_presenca, p.horario_aula
            """, (aluno_id, ano))
        else:
            cursor.execute(base_sql + """
                WHERE p.aluno_id = %s AND YEAR(p.data_presenca) = %s AND MONTH(p.data_presenca) = %s
                ORDER BY p.data_presenca, p.horario_aula
            """, (aluno_id, ano, mes))
        rows = cursor.fetchall()

        dias = []
        for r in rows:
            horario = ""
            if r["horario_aula"]:
                try:
                    h = r["horario_aula"]
                    if hasattr(h, "seconds"):
                        total_s = h.seconds
                        horario = f"{total_s//3600:02d}:{(total_s%3600)//60:02d}"
                    else:
                        horario = str(h)[:5]
                except Exception:
                    horario = str(r["horario_aula"])[:5]
            dias.append({
                "data": str(r["data_presenca"]),
                "presente": bool(r["presente"]),
                "horario": horario,
                "turma_nome": r["turma_nome"],
                "obs_aula": r["obs_aula"] or "",
                "obs_aluno": r["obs_aluno"] or "",
            })

        total = len(dias)
        presentes = sum(1 for d in dias if d["presente"])
        faltas = total - presentes
        pct = round(presentes / total * 100, 1) if total > 0 else None

        return jsonify({
            "periodo": periodo,
            "mes": mes if periodo == "mes" else None,
            "ano": ano,
            "dias": dias,
            "total": total,
            "presentes": presentes,
            "faltas": faltas,
            "percentual": pct,
        })
    finally:
        cursor.close()
        db.close()


@bp_alunos.route("/desistencia_dados/<int:aluno_id>", methods=["GET"])
@login_required
def desistencia_dados(aluno_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, nome, id_academia, COALESCE(ativo,1) AS ativo, TurmaID FROM alunos WHERE id = %s",
            (aluno_id,),
        )
        aluno = cursor.fetchone()
        if not aluno:
            return jsonify({"erro": "Aluno não encontrado"}), 404

        ids_acessiveis = set(_get_academias_ids() or [])
        if not current_user.has_role("admin") and aluno.get("id_academia") not in ids_acessiveis:
            return jsonify({"erro": "Sem permissão"}), 403

        # Turmas do aluno via aluno_turmas (N:N)
        cursor.execute("""
            SELECT t.TurmaID AS turma_id, t.Nome AS turma_nome
            FROM aluno_turmas at2
            JOIN turmas t ON t.TurmaID = at2.TurmaID
            WHERE at2.aluno_id = %s
            ORDER BY t.Nome
        """, (aluno_id,))
        turmas = list(cursor.fetchall())

        # Matrícula legada em alunos.TurmaID: incluir se ainda não está em aluno_turmas
        legacy_tid = aluno.get("TurmaID")
        ids_nn = {t["turma_id"] for t in turmas}
        if legacy_tid and legacy_tid not in ids_nn:
            cursor.execute(
                """
                SELECT t.TurmaID AS turma_id, t.Nome AS turma_nome
                FROM turmas t
                WHERE t.TurmaID = %s
                """,
                (legacy_tid,),
            )
            row_legacy = cursor.fetchone()
            if row_legacy:
                turmas.append(row_legacy)
                turmas.sort(key=lambda x: (x.get("turma_nome") or ""))

        # Se não houver N:N nem TurmaID preenchido, lista vazia (comportamento anterior quando só legacy existia)
        if not turmas and aluno.get("id_academia"):
            cursor.execute("""
                SELECT t.TurmaID AS turma_id, t.Nome AS turma_nome
                FROM alunos a
                JOIN turmas t ON t.TurmaID = a.TurmaID
                WHERE a.id = %s AND a.TurmaID IS NOT NULL
            """, (aluno_id,))
            turmas = cursor.fetchall()

        hoje = date.today()

        return jsonify({
            "turmas": [{"turma_id": t["turma_id"], "turma_nome": t["turma_nome"]} for t in turmas],
            "hoje_mes": hoje.month,
            "hoje_ano": hoje.year,
        })
    finally:
        cursor.close()
        db.close()


@bp_alunos.route("/registrar_desistencia/<int:aluno_id>", methods=["POST"])
@login_required
def registrar_desistencia(aluno_id):
    next_url = (request.form.get("next") or "").strip()

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, nome, id_academia, COALESCE(ativo,1) AS ativo, TurmaID FROM alunos WHERE id = %s",
            (aluno_id,),
        )
        aluno = cursor.fetchone()
        if not aluno:
            flash("Aluno não encontrado.", "danger")
            return redirect(next_url if (next_url.startswith("/") and "//" not in next_url) else url_for("alunos.lista_alunos"))

        ids_acessiveis = set(_get_academias_ids() or [])
        if not current_user.has_role("admin") and aluno.get("id_academia") not in ids_acessiveis:
            flash("Sem permissão.", "danger")
            return redirect(next_url if (next_url.startswith("/") and "//" not in next_url) else url_for("alunos.lista_alunos"))

        legacy_tid = aluno.get("TurmaID")

        # Turmas a remover (linhas em aluno_turmas + eventual matrícula só em alunos.TurmaID)
        turmas_desativar = request.form.getlist("turmas_desativar")
        removidas = 0
        ids_remover = []
        for tid in turmas_desativar:
            try:
                tid_int = int(tid)
            except (ValueError, TypeError):
                continue
            ids_remover.append(tid_int)
            cursor.execute("DELETE FROM aluno_turmas WHERE aluno_id = %s AND TurmaID = %s", (aluno_id, tid_int))
            removidas += cursor.rowcount

        # Se a turma legada (campo TurmaID) foi desistida, atualizar para outra turma restante em N:N ou NULL
        if legacy_tid and ids_remover and legacy_tid in ids_remover:
            cursor.execute(
                "SELECT TurmaID FROM aluno_turmas WHERE aluno_id = %s ORDER BY TurmaID LIMIT 1",
                (aluno_id,),
            )
            subst = cursor.fetchone()
            novo_tid = subst["TurmaID"] if subst else None
            cursor.execute("UPDATE alunos SET TurmaID = %s WHERE id = %s", (novo_tid, aluno_id))

        # Cancelar mensalidades selecionadas
        mens_cancelar = request.form.getlist("mensalidades_cancelar")
        canceladas_ids = 0
        if mens_cancelar:
            ids_validos = []
            for mid in mens_cancelar:
                try:
                    ids_validos.append(int(mid))
                except (ValueError, TypeError):
                    pass
            if ids_validos:
                placeholders = ",".join(["%s"] * len(ids_validos))
                cursor.execute(
                    f"UPDATE mensalidade_aluno SET status='cancelado' WHERE id IN ({placeholders}) AND aluno_id=%s",
                    ids_validos + [aluno_id],
                )
                canceladas_ids = cursor.rowcount

        # Cancelar mensalidades a partir de mês/ano
        canceladas_periodo = 0
        cancelar_periodo = str(request.form.get("cancelar_mensalidades_periodo") or "").strip() in ("1", "on", "true")
        if cancelar_periodo:
            hoje = date.today()
            mes_cancel = request.form.get("mes_cancelamento", type=int) or hoje.month
            ano_cancel = request.form.get("ano_cancelamento", type=int) or hoje.year
            if not (1 <= mes_cancel <= 12):
                mes_cancel = hoje.month
            if ano_cancel < 2000 or ano_cancel > 2100:
                ano_cancel = hoje.year
            data_inicio = date(ano_cancel, mes_cancel, 1)
            cursor.execute(
                """
                UPDATE mensalidade_aluno ma
                JOIN mensalidades m ON m.id = ma.mensalidade_id
                SET ma.status = 'cancelado'
                WHERE ma.aluno_id = %s
                  AND ma.status != 'cancelado'
                  AND ma.data_vencimento >= %s
                  AND m.id_academia = %s
                """,
                (aluno_id, data_inicio, aluno.get("id_academia")),
            )
            canceladas_periodo = cursor.rowcount or 0

        # Inativar só se não restar matrícula nem em aluno_turmas nem em TurmaID (legado)
        cursor.execute("SELECT COUNT(*) AS total FROM aluno_turmas WHERE aluno_id = %s", (aluno_id,))
        restantes_nn = (cursor.fetchone() or {}).get("total", 0)
        cursor.execute("SELECT TurmaID FROM alunos WHERE id = %s", (aluno_id,))
        turma_id_depois = (cursor.fetchone() or {}).get("TurmaID")
        inativar = restantes_nn == 0 and turma_id_depois is None
        if inativar:
            cursor.execute("UPDATE alunos SET ativo=0, status='inativo', data_inativacao=CURDATE() WHERE id=%s", (aluno_id,))

        db.commit()

        partes = []
        if removidas:
            partes.append(f"{removidas} matrícula(s) removida(s)")
        canceladas_total = canceladas_ids + canceladas_periodo
        if canceladas_total:
            partes.append(f"{canceladas_total} mensalidade(s) cancelada(s)")
        if inativar:
            partes.append("aluno inativado automaticamente")

        msg = f'Desistência de "{aluno.get("nome")}" registrada'
        if partes:
            msg += ": " + ", ".join(partes) + "."
        flash(msg, "warning")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao registrar desistência: {e}", "danger")
    finally:
        cursor.close()
        db.close()

    if next_url.startswith("/") and "//" not in next_url:
        return redirect(next_url)
    return redirect(url_for("alunos.lista_alunos"))
