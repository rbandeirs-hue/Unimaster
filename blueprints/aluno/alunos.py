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
        elif getattr(current_user, "id_academia", None):
            ids = [current_user.id_academia]
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
    # Se em modo academia com academia_id selecionada, filtra por ela
    academia_filtro = request.args.get("academia_id", type=int) or session.get("academia_gerenciamento_id")
    ids_acessiveis = _get_academias_ids()
    if academia_filtro and academia_filtro in ids_acessiveis:
        session["academia_gerenciamento_id"] = academia_filtro
        session["finance_academia_id"] = academia_filtro
        query += " AND a.id_academia = %s"
        params.append(academia_filtro)
    # SUPERUSER (admin) → vê tudo (só quando não tem filtro de academia)
    elif current_user.has_role("admin"):
        pass

    # FEDERAÇÃO → vê alunos das academias da federação
    elif current_user.has_role("gestor_federacao"):
        query += """
            AND a.id_academia IN (
                SELECT ac.id
                FROM academias ac
                JOIN associacoes ass2 ON ass2.id = ac.id_associacao
                WHERE ass2.id_federacao = %s
            )
        """
        params.append(getattr(current_user, "id_federacao", 0))

    # ASSOCIAÇÃO → vê alunos das academias da associação
    elif current_user.has_role("gestor_associacao"):
        query += """
            AND a.id_academia IN (
                SELECT id FROM academias WHERE id_associacao = %s
            )
        """
        params.append(getattr(current_user, "id_associacao", 0))

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

    query += " ORDER BY a.nome"

    cursor.execute(query, tuple(params))
    alunos = cursor.fetchall()

    # Carrega faixas
    cursor.execute("SELECT * FROM graduacao ORDER BY id")
    faixas = cursor.fetchall()

    # Carrega classes (idade) e categorias de peso
    cursor.execute(
        """
        SELECT id_classe, classe, idade_min, idade_max, notas
        FROM classes_judo
        ORDER BY id_classe
        """
    )
    classes_judo = cursor.fetchall()

    cursor.execute("SHOW COLUMNS FROM categorias_peso")
    cols_peso_raw = cursor.fetchall()
    cols_peso_map = {}
    for c in cols_peso_raw:
        key = c["Field"].lower()
        cols_peso_map[key] = c["Field"]
        key_norm = "".join(
            ch for ch in unicodedata.normalize("NFKD", key) if not unicodedata.combining(ch)
        )
        cols_peso_map.setdefault(key_norm, c["Field"])

    def col_peso(nome):
        return cols_peso_map.get(nome, nome)

    cursor.execute(
        f"""
        SELECT {col_peso('id_peso')} AS id_peso,
               {col_peso('genero')} AS genero,
               {col_peso('id_classe_fk')} AS id_classe_fk,
               {col_peso('categoria')} AS categoria,
               {col_peso('nome_categoria')} AS nome_categoria,
               {col_peso('peso_min')} AS peso_min,
               {col_peso('peso_max')} AS peso_max
        FROM categorias_peso
        ORDER BY {col_peso('id_peso')}
        """
    )
    categorias_peso = cursor.fetchall()

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

    # ======================================================
    # 🔹 CÁLCULO DE FAIXAS + MODALIDADES
    # ======================================================

    for aluno in alunos:
        # Mapear rua -> endereco (para templates que usam "endereco")
        aluno["endereco"] = aluno.get("rua")

        # Modalidades
        mods = modalidades_por_aluno.get(aluno["id"], [])
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
        # 🔹 Classes por idade + categorias de peso
        # ======================================================
        classes_aptas = []
        if aluno["idade_ano_civil"] is not None:
            for c in classes_judo:
                idade_min = c.get("idade_min")
                idade_max = c.get("idade_max")
                if idade_min is None:
                    continue
                if aluno["idade_ano_civil"] < idade_min:
                    continue
                if idade_max is not None and aluno["idade_ano_civil"] > idade_max:
                    continue
                classes_aptas.append(c)

        def classe_fk_match(valor, ids_classes):
            if not valor or not ids_classes:
                return False
            texto = str(valor).strip()
            if not texto:
                return False
            if "-" in texto:
                partes = [p.strip() for p in texto.split("-", 1)]
                try:
                    ini = int("".join(filter(str.isdigit, partes[0])))
                    fim = int("".join(filter(str.isdigit, partes[1])))
                    return any(ini <= cid <= fim for cid in ids_classes)
                except Exception:
                    return False
            ids = []
            for token in texto.replace(";", ",").replace(" ", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    ids.append(int("".join(filter(str.isdigit, token))))
                except Exception:
                    continue
            if ids:
                return any(cid in ids for cid in ids_classes)
            try:
                return int("".join(filter(str.isdigit, texto))) in ids_classes
            except Exception:
                return False

        categorias_match = []
        sexo = (aluno.get("sexo") or "").upper()
        peso = aluno.get("peso")
        ids_classes = [c["id_classe"] for c in classes_aptas if c.get("id_classe") is not None]
        if sexo in ("M", "F") and peso is not None and ids_classes:
            for cat in categorias_peso:
                if (cat.get("genero") or "").upper() != sexo:
                    continue
                if not classe_fk_match(cat.get("id_classe_fk"), ids_classes):
                    continue
                peso_min = cat.get("peso_min")
                peso_max = cat.get("peso_max")
                if peso_min is not None and peso < float(peso_min):
                    continue
                if peso_max is not None and peso > float(peso_max):
                    continue
                categorias_match.append(cat)

        partes = []
        if classes_aptas:
            classes_txt_list = []
            for c in classes_aptas:
                classe_nome = c.get("classe") or "-"
                classe_upper = str(classe_nome).upper()
                if "/" in classe_upper:
                    partes_classe = [p.strip() for p in classe_upper.split("/") if p.strip()]
                    if sexo == "M":
                        for p in partes_classe:
                            if p.startswith("M"):
                                classe_nome = p
                                break
                    elif sexo == "F":
                        for p in partes_classe:
                            if p.startswith("F"):
                                classe_nome = p
                                break
                classes_txt_list.append(classe_nome)
            classes_txt = ", ".join(classes_txt_list)
            partes.append(f"Classe: {classes_txt}")
        else:
            if aluno["idade_ano_civil"] is None:
                partes.append("Classe: informe data de nascimento")
            else:
                partes.append("Classe: não encontrada")

        if categorias_match:
            cat = categorias_match[0]
            categoria_txt = cat.get('categoria') or ''
            nome_categoria_txt = cat.get('nome_categoria') or ''
            if categoria_txt and nome_categoria_txt:
                partes.append(f"Categoria: {categoria_txt} - {nome_categoria_txt}")
            elif nome_categoria_txt:
                partes.append(f"Categoria: {nome_categoria_txt}")
            elif categoria_txt:
                partes.append(f"Categoria: {categoria_txt}")
            else:
                partes.append("Categoria: -")
        else:
            if peso is None:
                partes.append("Categoria: informe o peso")
            elif sexo not in ("M", "F"):
                partes.append("Categoria: informe o sexo")
            else:
                partes.append("Categoria: não encontrada")

        aluno["classes_e_pesos"] = " | ".join(partes)

    # Carregar academias para seletor (quando usuário tem acesso a mais de uma)
    academias = []
    academia_id_sel = None
    if len(ids_acessiveis) > 1 and (
        session.get("modo_painel") == "academia" or request.args.get("academia_id")
    ):
        try:
            cursor.execute(
                "SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids_acessiveis)),
                tuple(ids_acessiveis),
            )
            academias = cursor.fetchall()
            academia_id_sel = academia_filtro or ids_acessiveis[0]
        except Exception:
            pass

    db.close()

    back_url = request.args.get("next")
    if not back_url:
        ref = request.referrer or ""
        if ref and "cadastrar_aluno" not in ref:
            back_url = ref
    if not back_url:
        back_url = (
            url_for("academia.painel_academia", academia_id=academia_id_sel)
            if academia_id_sel and session.get("modo_painel") == "academia"
            else url_for("painel.home")
        )
    return render_template(
        "alunos/lista_alunos.html",
        alunos=alunos,
        busca=busca,
        back_url=back_url,
        academias=academias,
        academia_id=academia_id_sel,
    )


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
    try:
        if acad_filtro and acad_filtro in ids_acad:
            cursor.execute("SELECT * FROM turmas WHERE id_academia = %s ORDER BY Nome", (acad_filtro,))
        else:
            cursor.execute("SELECT * FROM turmas ORDER BY Nome")
    except Exception:
        cursor.execute("SELECT * FROM turmas ORDER BY Nome")
    turmas = cursor.fetchall()

    id_acad_modalidade = acad_filtro or (ids_acad[0] if ids_acad else None) or getattr(current_user, "id_academia", None)
    try:
        cursor.execute(
            """
            SELECT * FROM modalidade
            WHERE (id_academia IS NULL OR id_academia = %s) AND ativo = 1
            ORDER BY nome
            """,
            (id_acad_modalidade,),
        )
    except Exception:
        cursor.execute("SELECT * FROM modalidade WHERE ativo = 1 ORDER BY nome")
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

        nome = form.get("nome", "").strip()
        data_nascimento = form.get("data_nascimento") or None
        sexo = form.get("sexo") or None
        status = "ativo"
        ativo = 1
        data_matricula = date.today().strftime("%Y-%m-%d")
        graduacao_id = form.get("graduacao_id") or None
        TurmaID = form.get("TurmaID") or None

        nacionalidade = form.get("nacionalidade") or None
        nome_pai = form.get("nome_pai") or None
        nome_mae = form.get("nome_mae") or None

        cpf = normalizar_cpf(form.get("cpf"))
        rg = form.get("rg") or None
        orgao_emissor = form.get("orgao_emissor") or None
        rg_data_emissao = form.get("rg_data_emissao") or None

        cep = form.get("cep") or None
        endereco = form.get("endereco") or None  # mapeado para 'rua'
        numero = form.get("numero") or None
        complemento = form.get("complemento") or None
        bairro = form.get("bairro") or None
        cidade = form.get("cidade") or None
        estado = form.get("estado") or None

        responsavel_nome = form.get("responsavel_nome") or None
        responsavel_parentesco = (
            form.get("responsavel_parentesco")
            or form.get("responsavel_grau_parentesco")
            or None
        )

        email = form.get("email") or None
        telefone_celular = form.get("telefone_celular") or None
        telefone_residencial = form.get("telefone_residencial") or None
        telefone_comercial = form.get("telefone_comercial") or None
        telefone_outro = form.get("telefone_outro") or None

        peso_str = form.get("peso") or None
        peso = None
        if peso_str:
            peso = float(str(peso_str).replace(",", "."))

        ultimo_exame_faixa = form.get("ultimo_exame_faixa") or None

        zempo = form.get("zempo") or None
        data_cadastro_zempo = form.get("data_cadastro_zempo") or None
        registro_fpju = form.get("registro_fpju") or None
        cadastro_zempo = form.get("cadastro_zempo") == "1"

        responsavel_financeiro_nome = form.get("responsavel_financeiro_nome") or None
        responsavel_financeiro_cpf = normalizar_cpf(form.get("responsavel_financeiro_cpf"))

        observacoes = form.get("observacoes") or None

        modalidades_ids = request.form.getlist("aluno_modalidade_ids")

        # Foto
        foto_dataurl = form.get("foto")  # base64
        foto_arquivo = request.files.get("foto_arquivo")

        id_academia = form.get("id_academia") or getattr(current_user, "id_academia", None)
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

            if "registro_fpju" in colunas_alunos:
                cursor_insert.execute(
                    "UPDATE alunos SET registro_fpju=%s WHERE id=%s",
                    (registro_fpju, aluno_id),
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
        cursor.execute("SELECT * FROM turmas ORDER BY Nome")
        turmas = cursor.fetchall()
    except Exception:
        pass

    try:
        cursor.execute(
            """
            SELECT * FROM modalidade
            WHERE (id_academia IS NULL OR id_academia = %s) AND ativo = 1
            ORDER BY nome
            """,
            (aluno.get("id_academia"),),
        )
        modalidades = cursor.fetchall()
    except Exception:
        pass

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

        nacionalidade = form.get("nacionalidade") or None
        nome_pai = form.get("nome_pai") or None
        nome_mae = form.get("nome_mae") or None

        cpf = normalizar_cpf(form.get("cpf"))
        rg = form.get("rg") or None
        orgao_emissor = form.get("orgao_emissor") or None
        rg_data_emissao = form.get("rg_data_emissao") or None

        cep = form.get("cep") or None
        endereco = form.get("endereco") or None  # rua
        numero = form.get("numero") or None
        complemento = form.get("complemento") or None
        bairro = form.get("bairro") or None
        cidade = form.get("cidade") or None
        estado = form.get("estado") or None

        responsavel_nome = form.get("responsavel_nome") or None
        responsavel_parentesco = (
            form.get("responsavel_parentesco")
            or form.get("responsavel_grau_parentesco")
            or None
        )

        email = form.get("email") or None
        telefone_celular = form.get("telefone_celular") or None
        telefone_residencial = form.get("telefone_residencial") or None
        telefone_comercial = form.get("telefone_comercial") or None
        telefone_outro = form.get("telefone_outro") or None

        peso_str = form.get("peso") or None
        peso = None
        if peso_str:
            peso = float(str(peso_str).replace(",", "."))

        ultimo_exame_faixa = form.get("ultimo_exame_faixa") or None

        zempo = form.get("zempo") or None
        data_cadastro_zempo = form.get("data_cadastro_zempo") or None
        registro_fpju = form.get("registro_fpju") or None

        responsavel_financeiro_nome = form.get("responsavel_financeiro_nome") or None
        responsavel_financeiro_cpf = normalizar_cpf(form.get("responsavel_financeiro_cpf"))

        observacoes = form.get("observacoes") or None

        if pode_alterar_turma_mod:
            modalidades_ids = request.form.getlist("aluno_modalidade_ids")
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
                    foto=%s
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
                    aluno_id,
                ),
            )

            if "data_cadastro_zempo" in colunas_alunos:
                cursor_update.execute(
                    "UPDATE alunos SET data_cadastro_zempo=%s WHERE id=%s",
                    (data_cadastro_zempo, aluno_id),
                )

            if "registro_fpju" in colunas_alunos:
                cursor_update.execute(
                    "UPDATE alunos SET registro_fpju=%s WHERE id=%s",
                    (registro_fpju, aluno_id),
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
