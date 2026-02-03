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
)
from flask_login import login_required, current_user
from config import get_db_connection
from utils.modalidades import filtro_visibilidade_sql
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import os
import base64
import unicodedata

bp_alunos = Blueprint("alunos", __name__, url_prefix="/alunos")


def _get_academias_ids():
    """IDs de academias acessíveis (prioridade: usuarios_academias, alinhado ao gerenciamento)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
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
    """
    Salva um arquivo enviado pelo input type=file em static/uploads.
    """
    if not file_storage or file_storage.filename == "":
        return None

    if not allowed_file(file_storage.filename):
        return None

    _, ext = os.path.splitext(file_storage.filename)
    if not ext:
        ext = ".png"

    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext.lower()}"
    upload_folder = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(upload_folder, exist_ok=True)
    filepath = os.path.join(upload_folder, filename)
    file_storage.save(filepath)
    return filename


# ======================================================
# 🔹 1. LISTA DE ALUNOS (com RBAC)
# ======================================================

@bp_alunos.route("/lista_alunos", methods=["GET"])
@login_required
def lista_alunos():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    busca = request.args.get("busca", "").strip()
    idade_min = request.args.get("idade_min", type=int)
    idade_max = request.args.get("idade_max", type=int)
    graduacao_id = request.args.get("graduacao_id", type=int)
    peso_min = request.args.get("peso_min", type=float)
    peso_max = request.args.get("peso_max", type=float)
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

    # Filtros dinâmicos (idade, graduação, peso)
    if idade_min is not None and idade_max is not None:
        query += " AND TIMESTAMPDIFF(YEAR, a.data_nascimento, CURDATE()) BETWEEN %s AND %s"
        params.extend([idade_min, idade_max])
    elif idade_min is not None:
        query += " AND TIMESTAMPDIFF(YEAR, a.data_nascimento, CURDATE()) >= %s"
        params.append(idade_min)
    elif idade_max is not None:
        query += " AND TIMESTAMPDIFF(YEAR, a.data_nascimento, CURDATE()) <= %s"
        params.append(idade_max)

    if graduacao_id is not None:
        query += " AND a.graduacao_id = %s"
        params.append(graduacao_id)

    if peso_min is not None and peso_max is not None:
        query += " AND a.peso IS NOT NULL AND a.peso BETWEEN %s AND %s"
        params.extend([peso_min, peso_max])
    elif peso_min is not None:
        query += " AND a.peso IS NOT NULL AND a.peso >= %s"
        params.append(peso_min)
    elif peso_max is not None:
        query += " AND a.peso IS NOT NULL AND a.peso <= %s"
        params.append(peso_max)

    query += " ORDER BY a.nome"

    cursor.execute(query, tuple(params))
    alunos = cursor.fetchall()

    # Carrega faixas
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

    # Modo associação: só modalidades que a associação oferta (para filtro e exibição)
    associacao_modalidades_ids = set()
    if modo == "associacao":
        id_assoc = getattr(current_user, "id_associacao", None)
        if id_assoc:
            cursor.execute(
                "SELECT modalidade_id FROM associacao_modalidades WHERE associacao_id = %s",
                (id_assoc,),
            )
            associacao_modalidades_ids = {r["modalidade_id"] for r in cursor.fetchall()}

    # ======================================================
    # 🔹 CÁLCULO DE FAIXAS + MODALIDADES
    # ======================================================

    for aluno in alunos:
        # Mapear rua -> endereco (para templates que usam "endereco")
        aluno["endereco"] = aluno.get("rua")

        # Modalidades (modo associação: só as que a associação oferta)
        mods = modalidades_por_aluno.get(aluno["id"], [])
        if modo == "associacao" and associacao_modalidades_ids:
            mods = [m for m in mods if m["id"] in associacao_modalidades_ids]
        aluno["modalidades"] = mods
        aluno["modalidades_ids"] = [m["id"] for m in mods]
        aluno["modalidades_nomes"] = ", ".join(m["nome"] for m in mods) if mods else "-"

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
                    nome_mod = m.get("nome") or "Outras"
                    mod_nome_to_alunos.setdefault(nome_mod, []).append(aluno)
        # Ordenar: "Sem modalidade" por último
        def _ord_modalidade(k):
            return (1, k) if k == "Sem modalidade" else (0, k)
        mod_keys = list(mod_nome_to_alunos.keys())
        # Modo associação: não exibir grupo "Sem modalidade" (alunos sem modalidade já excluídos na query)
        if modo == "associacao" and "Sem modalidade" in mod_keys:
            mod_keys = [k for k in mod_keys if k != "Sem modalidade"]
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
        "por_academia": {},
        "por_graduacao": {},
    }
    for aluno in alunos_exibidos:
        acad_nome = aluno.get("academia_nome") or "Sem academia"
        stats["por_academia"][acad_nome] = stats["por_academia"].get(acad_nome, 0) + 1
        grad_nome = aluno.get("faixa") or "Sem faixa"
        if aluno.get("graduacao"):
            grad_nome = f"{grad_nome} {aluno['graduacao']}".strip()
        stats["por_graduacao"][grad_nome] = stats["por_graduacao"].get(grad_nome, 0) + 1

    # Mostrar filtros avançados em modo associação/federação ou quando há múltiplas academias
    mostrar_filtros_avancados = modo in ("associacao", "federacao") or len(ids_acessiveis) > 1

    # Enriquecer alunos para o modal (adicionar categorias, frequência, etc.)
    # IMPORTANTE: fazer antes de fechar a conexão do banco
    for _, grupo_alunos in alunos_agrupados:
        for aluno in grupo_alunos:
            enriquecer_aluno_para_modal(aluno)

    db.close()
    
    # Modo associação/federação: voltar sempre para o gerenciamento
    if modo == "associacao":
        back_url = url_for("associacao.gerenciamento_associacao")
    elif modo == "federacao":
        back_url = url_for("federacao.gerenciamento_federacao")
    else:
        back_url = request.args.get("next")
        if not back_url:
            ref = request.referrer or ""
            if ref and "cadastrar_aluno" not in ref:
                back_url = ref
        if not back_url:
            if academia_id_sel and modo == "academia":
                back_url = url_for("academia.painel_academia", academia_id=academia_id_sel)
            else:
                back_url = url_for("painel.home")
    modo_associacao = modo == "associacao"
    # Modo associação: filtros sempre vazios (só placeholders)
    return render_template(
        "alunos/lista_alunos.html",
        alunos=alunos,
        alunos_agrupados=alunos_agrupados,
        busca="" if modo_associacao else busca,
        back_url=back_url,
        academias=academias,
        academia_id=academia_id_sel,
        faixas=faixas,
        idade_min=None if modo_associacao else idade_min,
        idade_max=None if modo_associacao else idade_max,
        graduacao_id=None if modo_associacao else graduacao_id,
        peso_min=None if modo_associacao else peso_min,
        peso_max=None if modo_associacao else peso_max,
        stats=stats,
        mostrar_filtros_avancados=mostrar_filtros_avancados,
        agrupar_por_academia=agrupar_por_academia if modo_associacao else False,
        modo_associacao=modo_associacao,
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
        graduacao_id = form.get("graduacao_id") or None
        if graduacao_id == "":
            graduacao_id = None
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
            if "Duplicate entry" in msg and "unq_cpf" in msg:
                flash("CPF já cadastrado. Verifique e tente novamente.", "danger")
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
        graduacao_id = form.get("graduacao_id") or None
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
