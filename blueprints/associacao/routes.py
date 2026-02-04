# blueprints/associacao/routes.py
import os
import base64
import re
import unicodedata
from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from config import get_db_connection
from utils.modalidades import filtro_visibilidade_sql

associacao_bp = Blueprint("associacao", __name__, url_prefix="/associacao")

LOGO_EXTENSOES = (".png", ".jpg", ".jpeg", ".gif")


def _pasta_logos():
    return os.path.join(current_app.root_path, "static", "uploads", "logos")


def _slugify(nome):
    """Converte nome em slug URL-amigável: 'Academia Judô Centro' -> 'academia-judo-centro'."""
    if not nome:
        return ""
    s = unicodedata.normalize("NFD", str(nome))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-") or "academia"


def salvar_logo_base64(data_url, prefixo, entidade_id):
    """Salva logo a partir de dataURL (base64) em static/uploads/logos."""
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        if "," in data_url:
            _, encoded = data_url.split(",", 1)
        else:
            encoded = data_url
        img_data = base64.b64decode(encoded)
    except Exception:
        return None
    pasta = _pasta_logos()
    os.makedirs(pasta, exist_ok=True)
    for ext in LOGO_EXTENSOES:
        existente = os.path.join(pasta, f"{prefixo}_{entidade_id}{ext}")
        if os.path.exists(existente):
            try:
                os.remove(existente)
            except OSError:
                pass
    filename = f"{prefixo}_{entidade_id}.png"
    filepath = os.path.join(pasta, filename)
    with open(filepath, "wb") as f:
        f.write(img_data)
    return filename


def salvar_logo(file_storage, prefixo, entidade_id):
    if not file_storage or file_storage.filename == "":
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in LOGO_EXTENSOES:
        return None
    pasta = _pasta_logos()
    os.makedirs(pasta, exist_ok=True)
    for ext_item in LOGO_EXTENSOES:
        existente = os.path.join(pasta, f"{prefixo}_{entidade_id}{ext_item}")
        if os.path.exists(existente):
            try:
                os.remove(existente)
            except OSError:
                pass
    filename = f"{prefixo}_{entidade_id}{ext}"
    file_storage.save(os.path.join(pasta, filename))
    return filename


def buscar_logo_url(prefixo, entidade_id):
    pasta = _pasta_logos()
    for ext in LOGO_EXTENSOES:
        filename = f"{prefixo}_{entidade_id}{ext}"
        if os.path.isfile(os.path.join(pasta, filename)):
            return url_for("static", filename=f"uploads/logos/{filename}")
    return None

# =====================================================
# 🔹 Painel da Associação
# =====================================================
@associacao_bp.route("/")
@login_required
def painel_associacao():

    # 🔥 RBAC – Apenas quem tem papel adequado pode acessar
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("associacao.painel_associacao")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if current_user.has_role("admin"):
        cur.execute("""
            SELECT id, nome
            FROM academias
            ORDER BY nome
        """)
    else:
        cur.execute("""
            SELECT id, nome
            FROM academias
            WHERE id_associacao = %s
            ORDER BY nome
        """, (getattr(current_user, "id_associacao", None),))

    academias = cur.fetchall()

    # Dashboard: contagens (alunos via id_academia das academias da associação)
    stats = {"academias": 0, "alunos": 0}
    try:
        stats["academias"] = len(academias)
        if academias:
            ids_acad = tuple(a["id"] for a in academias)
            if len(ids_acad) == 1:
                cur.execute("SELECT COUNT(*) as c FROM alunos WHERE id_academia = %s", (ids_acad[0],))
            else:
                ph = ",".join(["%s"] * len(ids_acad))
                cur.execute(f"SELECT COUNT(*) as c FROM alunos WHERE id_academia IN ({ph})", ids_acad)
            stats["alunos"] = cur.fetchone().get("c") or 0
    except Exception:
        pass

    cur.close()
    conn.close()

    return render_template(
        "painel/painel_associacao.html",
        usuario=current_user,
        academias=academias,
        stats=stats,
    )


# =====================================================
# 🔹 Gerenciamento da Associação (hub de módulos)
# =====================================================
@associacao_bp.route("/gerenciamento")
@login_required
def gerenciamento_associacao():
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    return render_template("painel/gerenciamento_associacao.html")


# =====================================================
# 🔹 Lista de Professores da Associação
# =====================================================
@associacao_bp.route("/professores")
@login_required
def lista_professores():
    """Lista todos os professores vinculados às academias da associação."""
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    associacao_id = getattr(current_user, "id_associacao", None)
    if not associacao_id and not current_user.has_role("admin"):
        flash("Associação não encontrada.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar professores de todas as academias da associação
        if current_user.has_role("admin"):
            query = """
                SELECT 
                    p.id,
                    p.nome,
                    p.email,
                    p.telefone,
                    p.ativo,
                    p.id_academia,
                    p.usuario_id,
                    ac.nome AS academia_nome,
                    COALESCE(u.foto, (SELECT a.foto FROM alunos a WHERE a.usuario_id = p.usuario_id AND a.ativo = 1 LIMIT 1)) AS foto
                FROM professores p
                INNER JOIN academias ac ON ac.id = p.id_academia
                LEFT JOIN usuarios u ON u.id = p.usuario_id
                WHERE p.ativo = 1
                ORDER BY ac.nome, p.nome
            """
            cur.execute(query)
        else:
            query = """
                SELECT 
                    p.id,
                    p.nome,
                    p.email,
                    p.telefone,
                    p.ativo,
                    p.id_academia,
                    p.usuario_id,
                    ac.nome AS academia_nome,
                    COALESCE(u.foto, (SELECT a.foto FROM alunos a WHERE a.usuario_id = p.usuario_id AND a.ativo = 1 LIMIT 1)) AS foto
                FROM professores p
                INNER JOIN academias ac ON ac.id = p.id_academia
                LEFT JOIN usuarios u ON u.id = p.usuario_id
                WHERE ac.id_associacao = %s AND p.ativo = 1
                ORDER BY ac.nome, p.nome
            """
            cur.execute(query, (associacao_id,))
        
        professores = cur.fetchall()
        
        # Processar fotos e URLs
        for prof in professores:
            if prof.get("foto"):
                prof["foto_url"] = url_for("static", filename="uploads/" + prof["foto"])
            else:
                prof["foto_url"] = None
        
        # Agrupar professores por academia
        professores_por_academia = {}
        for prof in professores:
            academia_nome = prof.get("academia_nome", "Sem Academia")
            if academia_nome not in professores_por_academia:
                professores_por_academia[academia_nome] = []
            professores_por_academia[academia_nome].append(prof)
        
        # Calcular estatísticas
        total_professores = len(professores)
        total_ativos = sum(1 for prof in professores if prof.get("ativo"))
        
        # Contar academias únicas
        academias_unicas = set(prof.get("academia_nome") for prof in professores if prof.get("academia_nome"))
        total_academias = len(academias_unicas)
        
        # Buscar nome da associação
        if associacao_id:
            cur.execute("SELECT nome FROM associacoes WHERE id = %s", (associacao_id,))
            associacao = cur.fetchone()
            associacao_nome = associacao.get("nome") if associacao else None
        else:
            associacao_nome = None
            
    except Exception as e:
        flash(f"Erro ao buscar professores: {e}", "danger")
        professores = []
        professores_por_academia = {}
        associacao_nome = None
        total_professores = 0
        total_ativos = 0
        total_academias = 0
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "associacao/professores.html",
        professores=professores,
        professores_por_academia=professores_por_academia,
        associacao_nome=associacao_nome,
        associacao_id=associacao_id,
        total_professores=total_professores,
        total_ativos=total_ativos,
        total_academias=total_academias,
    )


# =====================================================
# 🔹 Configurações da Associação
# =====================================================
@associacao_bp.route("/configuracoes")
@login_required
def configuracoes_associacao():
    if not (current_user.has_role("gestor_federacao") or current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    associacao_id = request.args.get("associacao_id", type=int)
    id_assoc_user = getattr(current_user, "id_associacao", None)

    if (current_user.has_role("admin") or current_user.has_role("gestor_federacao")) and not associacao_id:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        if current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT id, nome FROM associacoes WHERE id_federacao = %s ORDER BY nome",
                (getattr(current_user, "id_federacao", 0),),
            )
        else:
            cur.execute("SELECT id, nome FROM associacoes ORDER BY nome")
        associacoes = cur.fetchall()
        cur.close()
        conn.close()
        return render_template(
            "painel/configuracoes_associacao.html",
            associacao=None,
            associacoes=associacoes,
        )

    aid = associacao_id or id_assoc_user
    if not aid:
        flash("Selecione uma associação.", "warning")
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM associacoes WHERE id = %s", (aid,))
    associacao = cur.fetchone()
    cur.close()
    conn.close()

    if not associacao:
        flash("Associação não encontrada.", "danger")
        return redirect(url_for("associacao.gerenciamento_associacao"))

    associacao["logo_url"] = buscar_logo_url("associacao", associacao["id"])
    return render_template(
        "painel/configuracoes_associacao.html",
        associacao=associacao,
        associacoes=None,
    )


# =====================================================
# 🔹 Cadastro de Academia
# =====================================================
@associacao_bp.route("/academias/cadastro", methods=["GET", "POST"])
@login_required
def cadastro_academia():

    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("associacao.lista_academias")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    associacoes = []
    id_associacao_padrao = getattr(current_user, "id_associacao", None)

    if current_user.has_role("admin"):
        cur.execute("SELECT id, nome FROM associacoes ORDER BY nome")
        associacoes = cur.fetchall()
    elif id_associacao_padrao:
        cur.execute("SELECT id, nome FROM associacoes WHERE id = %s", (id_associacao_padrao,))
        associacoes = cur.fetchall()

    # Modo associação: só modalidades vinculadas à associação (associacao_modalidades)
    modo_associacao_modalidades = (
        current_user.has_role("gestor_associacao")
        and not current_user.has_role("admin")
        and id_associacao_padrao
    )
    if modo_associacao_modalidades:
        extra, extra_params = filtro_visibilidade_sql(id_associacao=id_associacao_padrao)
        cur.execute(
            """
            SELECT m.id, m.nome FROM modalidade m
            INNER JOIN associacao_modalidades am ON am.modalidade_id = m.id AND am.associacao_id = %s
            WHERE m.ativo = 1 """ + extra + """ ORDER BY m.nome
            """,
            (id_associacao_padrao,) + extra_params,
        )
        modalidades = cur.fetchall()
        if not modalidades:
            extra2, extra_params2 = filtro_visibilidade_sql(id_associacao=id_associacao_padrao)
            cur.execute("SELECT id, nome FROM modalidade m WHERE m.ativo = 1" + extra2 + " ORDER BY m.nome", extra_params2)
            modalidades = cur.fetchall()
    else:
        cur.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY nome")
        modalidades = cur.fetchall()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        responsavel = request.form.get("responsavel", "").strip()
        cidade = request.form.get("cidade", "").strip()
        uf = request.form.get("uf", "").strip().upper()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        cep = request.form.get("cep", "").strip()
        rua = request.form.get("rua", "").strip()
        numero = request.form.get("numero", "").strip()
        complemento = request.form.get("complemento", "").strip()
        bairro = request.form.get("bairro", "").strip()
        logo_file = request.files.get("logo")
        logo_base64 = request.form.get("logo_base64")
        modalidade_ids = [int(x) for x in request.form.getlist("modalidade_ids") if str(x).strip().isdigit()]
        
        # Dados do gestor
        gestor_nome = request.form.get("gestor_nome", "").strip()
        gestor_email = request.form.get("gestor_email", "").strip()
        gestor_senha = request.form.get("gestor_senha", "").strip()

        if current_user.has_role("admin"):
            id_associacao = request.form.get("id_associacao")
        else:
            id_associacao = id_associacao_padrao

        if not nome:
            flash("Informe o nome da academia.", "danger")
        elif not id_associacao:
            flash("Selecione a associação da academia.", "danger")
        elif not gestor_nome or not gestor_email or not gestor_senha:
            flash("Preencha todos os dados do gestor (nome, e-mail e senha).", "danger")
        elif len(gestor_senha) < 6:
            flash("A senha do gestor deve ter no mínimo 6 caracteres.", "danger")
        else:
            # Modo associação: validar modalidades apenas as vinculadas à associação
            if modo_associacao_modalidades:
                cur.execute(
                    "SELECT modalidade_id FROM associacao_modalidades WHERE associacao_id = %s",
                    (id_associacao,),
                )
                ids_validos = {r["modalidade_id"] for r in cur.fetchall()}
                modalidade_ids = [mid for mid in modalidade_ids if mid in ids_validos]

            # Verificar se email do gestor já existe
            cur.execute("SELECT id FROM usuarios WHERE email = %s", (gestor_email,))
            if cur.fetchone():
                flash("Já existe um usuário com este e-mail. Use outro e-mail para o gestor.", "danger")
                cur.close()
                conn.close()
                return render_template(
                    "academias/cadastro_academia.html",
                    associacoes=associacoes,
                    id_associacao_selecionada=id_associacao_padrao,
                    back_url=back_url,
                    modo_associacao=modo_associacao,
                    associacao_nome=associacao_nome_cadastro,
                    modalidades=modalidades,
                )
            
            # Criar academia
            cur.execute("""
                INSERT INTO academias (nome, responsavel, cidade, uf, email, telefone, cep, rua, numero, complemento, bairro, id_associacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                nome,
                responsavel or None,
                cidade or None,
                uf or None,
                email or None,
                telefone or None,
                cep or None,
                rua or None,
                numero or None,
                complemento or None,
                bairro or None,
                id_associacao
            ))
            academia_id = cur.lastrowid
            
            # Salvar logo
            if logo_base64 and logo_base64.startswith("data:"):
                salvar_logo_base64(logo_base64, "academia", academia_id)
            else:
                salvar_logo(logo_file, "academia", academia_id)
            
            # Vincular modalidades
            for mid in modalidade_ids:
                cur.execute(
                    "INSERT IGNORE INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                    (academia_id, mid),
                )
            
            # Buscar id_associacao e id_federacao da academia criada
            cur.execute("""
                SELECT a.id_associacao, 
                       ass.id_federacao
                FROM academias a
                LEFT JOIN associacoes ass ON ass.id = a.id_associacao
                WHERE a.id = %s
            """, (academia_id,))
            acad_info = cur.fetchone()
            id_associacao_usuario = acad_info["id_associacao"] if acad_info else None
            id_federacao_usuario = acad_info["id_federacao"] if acad_info else None
            
            # Criar usuário gestor
            senha_hash = generate_password_hash(gestor_senha)
            cur.execute("""
                INSERT INTO usuarios (nome, email, senha, id_academia, id_associacao, id_federacao)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (gestor_nome, gestor_email, senha_hash, academia_id, id_associacao_usuario, id_federacao_usuario))
            gestor_user_id = cur.lastrowid
            
            # Buscar IDs das roles gestor_academia e aluno
            cur.execute("""
                SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) as chave 
                FROM roles 
                WHERE chave IN ('gestor_academia', 'aluno')
                   OR nome IN ('Gestor Academia', 'Aluno')
                ORDER BY 
                    CASE chave
                        WHEN 'gestor_academia' THEN 1
                        WHEN 'aluno' THEN 2
                        ELSE 3
                    END
            """)
            roles_encontradas = cur.fetchall()
            role_gestor = None
            role_aluno = None
            for r in roles_encontradas:
                if r.get("chave") == "gestor_academia" or "gestor" in r.get("nome", "").lower() and "academia" in r.get("nome", "").lower():
                    role_gestor = r
                elif r.get("chave") == "aluno" or r.get("nome", "").lower() == "aluno":
                    role_aluno = r
            
            # Vincular role gestor_academia
            if role_gestor:
                cur.execute("""
                    INSERT INTO roles_usuario (usuario_id, role_id)
                    VALUES (%s, %s)
                """, (gestor_user_id, role_gestor["id"]))
            
            # Vincular role aluno
            if role_aluno:
                cur.execute("""
                    INSERT INTO roles_usuario (usuario_id, role_id)
                    VALUES (%s, %s)
                """, (gestor_user_id, role_aluno["id"]))
            
            # Vincular usuário à academia
            cur.execute("""
                INSERT INTO usuarios_academias (usuario_id, academia_id)
                VALUES (%s, %s)
            """, (gestor_user_id, academia_id))
            
            # Criar perfil de aluno automaticamente
            if role_aluno:
                try:
                    # Buscar id_associacao e id_federacao da academia
                    cur.execute("""
                        SELECT a.id_associacao, 
                               ass.id_federacao
                        FROM academias a
                        LEFT JOIN associacoes ass ON ass.id = a.id_associacao
                        WHERE a.id = %s
                    """, (academia_id,))
                    acad_info = cur.fetchone()
                    id_associacao_aluno = acad_info["id_associacao"] if acad_info else None
                    id_federacao_aluno = acad_info["id_federacao"] if acad_info else None
                    
                    cur.execute("""
                        INSERT INTO alunos (
                            nome, usuario_id, id_academia, id_associacao, id_federacao,
                            status, ativo, data_matricula
                        )
                        VALUES (%s, %s, %s, %s, %s, 'ativo', 1, %s)
                    """, (gestor_nome, gestor_user_id, academia_id, id_associacao_aluno, id_federacao_aluno, date.today()))
                    current_app.logger.info(f"Perfil de aluno criado automaticamente para gestor {gestor_nome} (ID: {gestor_user_id})")
                except Exception as e:
                    # Se falhar, não impede a criação da academia, mas registra o erro
                    current_app.logger.error(f"Erro ao criar perfil de aluno para gestor {gestor_nome} (ID: {gestor_user_id}): {e}", exc_info=True)
            
            conn.commit()
            cur.close()
            conn.close()
            flash(f"Academia cadastrada com sucesso! Usuário gestor '{gestor_nome}' criado e vinculado.", "success")
            redirect_url = request.form.get("next") or back_url
            return redirect(redirect_url)

    # Modo associação: não mostrar seletor de associação (usar apenas a do usuário)
    modo_associacao = (
        current_user.has_role("gestor_associacao")
        and not current_user.has_role("admin")
        and id_associacao_padrao
    )
    associacao_nome_cadastro = None
    if modo_associacao:
        cur.execute("SELECT nome FROM associacoes WHERE id = %s", (id_associacao_padrao,))
        row = cur.fetchone()
        associacao_nome_cadastro = row["nome"] if row else None

    cur.close()
    conn.close()

    return render_template(
        "academias/cadastro_academia.html",
        associacoes=associacoes,
        id_associacao_selecionada=id_associacao_padrao,
        back_url=back_url,
        modo_associacao=modo_associacao,
        associacao_nome=associacao_nome_cadastro,
        modalidades=modalidades,
    )


# =====================================================
# 🔹 Lista de Academias
# =====================================================
@associacao_bp.route("/academias")
@login_required
def lista_academias():
    from flask import session

    if not (current_user.has_role("admin") or current_user.has_role("gestor_federacao")
            or current_user.has_role("gestor_associacao")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    associacao_id = request.args.get("associacao_id", type=int)
    id_assoc_user = getattr(current_user, "id_associacao", None)
    modo_ativo = session.get("modo_painel")

    # Quando em modo associação, filtrar SEMPRE pela associação do usuário
    escopo_associacao_usuario = (
        modo_ativo == "associacao"
        or (current_user.has_role("gestor_associacao")
            and not current_user.has_role("admin")
            and not current_user.has_role("gestor_federacao"))
    )
    # Modo academia: gestor_academia/professor só veem academias vinculadas
    escopo_academia_vinculada = (
        modo_ativo == "academia"
        and (current_user.has_role("gestor_academia") or current_user.has_role("professor"))
    )

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if escopo_academia_vinculada:
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s", (current_user.id,))
        ids_acad = [r["academia_id"] for r in cur.fetchall()]
        if ids_acad:
            ph = ",".join(["%s"] * len(ids_acad))
            cur.execute(
                f"""SELECT ac.id, ac.nome, ac.cidade, ac.uf, ass.nome AS associacao_nome
                    FROM academias ac
                    LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                    WHERE ac.id IN ({ph})
                    ORDER BY ac.nome""",
                tuple(ids_acad),
            )
        else:
            cur.execute("SELECT 1 LIMIT 0")
    elif escopo_associacao_usuario and id_assoc_user:
        cur.execute("""
            SELECT ac.id, ac.nome, ac.cidade, ac.uf, ass.nome AS associacao_nome
            FROM academias ac
            LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
            WHERE ac.id_associacao = %s
            ORDER BY ac.nome
        """, (id_assoc_user,))
    elif current_user.has_role("admin") and not escopo_associacao_usuario:
        if associacao_id:
            cur.execute("""
                SELECT ac.id, ac.nome, ac.cidade, ac.uf, ass.nome AS associacao_nome
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ac.id_associacao = %s
                ORDER BY ac.nome
            """, (associacao_id,))
        else:
            cur.execute("""
                SELECT ac.id, ac.nome, ac.cidade, ac.uf, ass.nome AS associacao_nome
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                ORDER BY ac.nome
            """)
    elif current_user.has_role("gestor_federacao"):
        if associacao_id:
            cur.execute("""
                SELECT ac.id, ac.nome, ac.cidade, ac.uf, ass.nome AS associacao_nome
                FROM academias ac
                JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ass.id_federacao = %s AND ass.id = %s
                ORDER BY ac.nome
            """, (getattr(current_user, "id_federacao", None), associacao_id))
        else:
            cur.execute("""
                SELECT ac.id, ac.nome, ac.cidade, ac.uf, ass.nome AS associacao_nome
                FROM academias ac
                JOIN associacoes ass ON ass.id = ac.id_associacao
                WHERE ass.id_federacao = %s
                ORDER BY ac.nome
            """, (getattr(current_user, "id_federacao", None),))
    else:
        cur.execute("""
            SELECT ac.id, ac.nome, ac.cidade, ac.uf, ass.nome AS associacao_nome
            FROM academias ac
            LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
            WHERE ac.id_associacao = %s
            ORDER BY ac.nome
        """, (getattr(current_user, "id_associacao", None),))

    academias = cur.fetchall()
    for acad in academias:
        acad["logo_url"] = buscar_logo_url("academia", acad["id"])

    # Modo associação: título específico quando gestor_associacao (sem admin/gestor_fed)
    escopo_associacao = (
        current_user.has_role("gestor_associacao")
        and not current_user.has_role("admin")
        and not current_user.has_role("gestor_federacao")
    )
    associacao_nome = None
    if escopo_associacao and id_assoc_user:
        cur.execute("SELECT nome FROM associacoes WHERE id = %s", (id_assoc_user,))
        row = cur.fetchone()
        associacao_nome = row["nome"] if row else None

    cur.close()
    conn.close()

    return render_template(
        "academias/lista_academias.html",
        academias=academias,
        escopo_associacao=escopo_associacao,
        associacao_nome=associacao_nome
    )


# =====================================================
# 🔹 Editar Associação
# =====================================================
@associacao_bp.route("/associacoes/editar/<int:associacao_id>", methods=["GET", "POST"])
@login_required
def editar_associacao(associacao_id):

    if not (current_user.has_role("gestor_federacao") or current_user.has_role("admin") or current_user.has_role("gestor_associacao")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer
    if current_user.has_role("gestor_associacao"):
        back_url = back_url or url_for("associacao.configuracoes_associacao", associacao_id=associacao_id)
    else:
        back_url = back_url or url_for("federacao.lista_associacoes")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id, nome, responsavel, email, telefone, cep, rua, numero, complemento, bairro, cidade, uf, id_federacao
        FROM associacoes
        WHERE id = %s
        """,
        (associacao_id,),
    )
    associacao = cur.fetchone()

    if not associacao:
        flash("Associação não encontrada.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("federacao.lista_associacoes"))

    # Gestor associação só pode editar a própria associação
    if current_user.has_role("gestor_associacao"):
        if associacao_id != getattr(current_user, "id_associacao", None):
            flash("Acesso negado.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("associacao.configuracoes_associacao", associacao_id=getattr(current_user, "id_associacao")))
    elif current_user.has_role("gestor_federacao") and associacao.get("id_federacao") != getattr(current_user, "id_federacao", None):
        flash("Acesso negado.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("federacao.lista_associacoes"))

    federacoes = []
    if current_user.has_role("admin"):
        cur.execute("SELECT id, nome FROM federacoes ORDER BY nome")
        federacoes = cur.fetchall()
    elif getattr(current_user, "id_federacao", None):
        cur.execute("SELECT id, nome FROM federacoes WHERE id = %s", (current_user.id_federacao,))
        federacoes = cur.fetchall()
    elif current_user.has_role("gestor_associacao") and associacao.get("id_federacao"):
        cur.execute("SELECT id, nome FROM federacoes WHERE id = %s", (associacao["id_federacao"],))
        federacoes = cur.fetchall()

    if current_user.has_role("gestor_associacao"):
        extra, extra_params = filtro_visibilidade_sql(id_associacao=associacao_id)
        cur.execute("SELECT id, nome FROM modalidade m WHERE m.ativo = 1" + extra + " ORDER BY m.nome", extra_params)
    else:
        cur.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY nome")
    modalidades = cur.fetchall()
    cur.execute("SELECT modalidade_id FROM associacao_modalidades WHERE associacao_id = %s", (associacao_id,))
    associacao_modalidades_ids = {r["modalidade_id"] for r in cur.fetchall()}

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        responsavel = request.form.get("responsavel", "").strip()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        cep = request.form.get("cep", "").strip()
        rua = request.form.get("rua", "").strip()
        numero = request.form.get("numero", "").strip()
        complemento = request.form.get("complemento", "").strip()
        bairro = request.form.get("bairro", "").strip()
        cidade = request.form.get("cidade", "").strip()
        uf = request.form.get("uf", "").strip().upper()
        logo_file = request.files.get("logo")
        modalidade_ids = [int(x) for x in request.form.getlist("modalidade_ids") if str(x).strip().isdigit()]

        if current_user.has_role("admin"):
            id_federacao = request.form.get("id_federacao")
        else:
            id_federacao = associacao.get("id_federacao")

        if not nome:
            flash("Informe o nome da associação.", "danger")
        elif not id_federacao:
            flash("Selecione a federação da associação.", "danger")
        else:
            cur.execute(
                """
                UPDATE associacoes
                SET nome=%s, responsavel=%s, email=%s, telefone=%s, 
                    cep=%s, rua=%s, numero=%s, complemento=%s, bairro=%s, cidade=%s, uf=%s, id_federacao=%s
                WHERE id=%s
                """,
                (
                    nome,
                    responsavel or None,
                    email or None,
                    telefone or None,
                    cep or None,
                    rua or None,
                    numero or None,
                    complemento or None,
                    bairro or None,
                    cidade or None,
                    uf or None,
                    id_federacao,
                    associacao_id,
                ),
            )
            salvar_logo(logo_file, "associacao", associacao_id)
            cur.execute("DELETE FROM associacao_modalidades WHERE associacao_id = %s", (associacao_id,))
            for mid in modalidade_ids:
                cur.execute(
                    "INSERT INTO associacao_modalidades (associacao_id, modalidade_id) VALUES (%s, %s)",
                    (associacao_id, mid),
                )
            conn.commit()
            cur.close()
            conn.close()
            flash("Associação atualizada com sucesso!", "success")
            redirect_url = request.form.get("next") or back_url
            return redirect(redirect_url)

    cur.close()
    conn.close()

    logo_url = buscar_logo_url("associacao", associacao_id)
    return render_template(
        "associacoes/editar_associacao.html",
        associacao=associacao,
        federacoes=federacoes,
        logo_url=logo_url,
        back_url=back_url,
        modalidades=modalidades,
        associacao_modalidades_ids=associacao_modalidades_ids,
    )


# =====================================================
# 🔹 Editar Academia
# =====================================================
@associacao_bp.route("/academias/editar/<int:academia_id>", methods=["GET", "POST"])
@login_required
def editar_academia(academia_id):

    if not (
        current_user.has_role("admin")
        or current_user.has_role("gestor_federacao")
        or current_user.has_role("gestor_associacao")
        or current_user.has_role("gestor_academia")
        or current_user.has_role("professor")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer
    if current_user.has_role("gestor_academia") or current_user.has_role("professor"):
        back_url = back_url or url_for("academia.configuracoes_academia", academia_id=academia_id)
    else:
        back_url = back_url or url_for("associacao.lista_academias")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT ac.id, ac.nome, ac.responsavel, ac.cidade, ac.uf, ac.email, ac.telefone,
               ac.cep, ac.rua, ac.numero, ac.complemento, ac.bairro,
               ac.id_associacao, ass.id_federacao
        FROM academias ac
        LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
        WHERE ac.id = %s
        """,
        (academia_id,),
    )
    academia = cur.fetchone()

    if not academia:
        flash("Academia não encontrada.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("associacao.lista_academias"))

    # Gestor associação: pode editar academias vinculadas à sua associação
    if current_user.has_role("gestor_associacao") and not current_user.has_role("admin"):
        id_assoc_user = getattr(current_user, "id_associacao", None)
        # Fallback: se id_associacao não está em usuarios, buscar via usuarios_academias
        if id_assoc_user is None:
            cur.execute(
                """SELECT ac.id_associacao FROM academias ac
                   INNER JOIN usuarios_academias ua ON ua.academia_id = ac.id
                   WHERE ua.usuario_id = %s AND ac.id_associacao IS NOT NULL LIMIT 1""",
                (current_user.id,),
            )
            row = cur.fetchone()
            if row and row.get("id_associacao"):
                id_assoc_user = row["id_associacao"]
        id_assoc_acad = academia.get("id_associacao")
        # Permite se: academia vinculada à associação do gestor OU gestor vinculado à academia
        vincula_associacao = (
            id_assoc_user is not None
            and id_assoc_acad is not None
            and int(id_assoc_user) == int(id_assoc_acad)
        )
        cur.execute(
            "SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id = %s",
            (current_user.id, academia_id),
        )
        vincula_academia = cur.fetchone() is not None
        if not vincula_associacao and not vincula_academia:
            flash("Acesso negado.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("associacao.lista_academias"))

    if current_user.has_role("gestor_federacao") and academia.get("id_federacao") != getattr(current_user, "id_federacao", None):
        flash("Acesso negado.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("associacao.lista_academias"))

    # Gestor academia/professor: só academias em usuarios_academias — exceto se gestor_associacao no modo associação
    em_modo_associacao = session.get("modo_painel") == "associacao"
    if (current_user.has_role("gestor_academia") or current_user.has_role("professor")) and not (current_user.has_role("gestor_associacao") and em_modo_associacao):
        cur.execute("SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id = %s", (current_user.id, academia_id))
        if cur.fetchone() is None:
            flash("Acesso negado.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("academia.painel_academia"))

    associacoes = []
    if current_user.has_role("admin"):
        cur.execute("SELECT id, nome FROM associacoes ORDER BY nome")
        associacoes = cur.fetchall()
    elif current_user.has_role("gestor_federacao"):
        cur.execute(
            "SELECT id, nome FROM associacoes WHERE id_federacao = %s ORDER BY nome",
            (getattr(current_user, "id_federacao", None),),
        )
        associacoes = cur.fetchall()
    elif getattr(current_user, "id_associacao", None):
        cur.execute("SELECT id, nome FROM associacoes WHERE id = %s", (current_user.id_associacao,))
        associacoes = cur.fetchall()
    elif current_user.has_role("gestor_academia") or current_user.has_role("professor"):
        cur.execute(
            "SELECT id, nome FROM associacoes WHERE id = %s",
            (academia.get("id_associacao"),),
        )
        associacoes = cur.fetchall()

    # Modo associação: só modalidades vinculadas à associação com filtro de visibilidade.
    # Quando modo_painel=associacao, usa filtro mesmo com gestor_academia (evita privadas de academia).
    modo_associacao_edit = (
        current_user.has_role("gestor_associacao")
        and not current_user.has_role("admin")
        and not current_user.has_role("professor")
        and academia.get("id_associacao") is not None
        and (session.get("modo_painel") == "associacao" or not current_user.has_role("gestor_academia"))
    )
    id_assoc = academia.get("id_associacao")
    if modo_associacao_edit:
        extra, extra_params = filtro_visibilidade_sql(id_associacao=id_assoc)
        cur.execute(
            """
            SELECT m.id, m.nome FROM modalidade m
            INNER JOIN associacao_modalidades am ON am.modalidade_id = m.id AND am.associacao_id = %s
            WHERE m.ativo = 1 """ + extra + """ ORDER BY m.nome
            """,
            (id_assoc,) + extra_params,
        )
        modalidades = cur.fetchall()
        if not modalidades:
            extra2, extra_params2 = filtro_visibilidade_sql(id_associacao=id_assoc)
            cur.execute("SELECT id, nome FROM modalidade m WHERE m.ativo = 1" + extra2 + " ORDER BY m.nome", extra_params2)
            modalidades = cur.fetchall()
    else:
        # Modo academia/admin/federação: filtrar por visibilidade (públicas + privadas desta academia/associação)
        extra, extra_params = filtro_visibilidade_sql(
            id_associacao=id_assoc, id_academia=academia_id
        )
        cur.execute(
            "SELECT id, nome FROM modalidade m WHERE m.ativo = 1" + extra + " ORDER BY m.nome",
            extra_params,
        )
        modalidades = cur.fetchall()

    cur.execute("SELECT modalidade_id FROM academia_modalidades WHERE academia_id = %s", (academia_id,))
    academia_modalidades_ids = {r["modalidade_id"] for r in cur.fetchall()}

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        responsavel = request.form.get("responsavel", "").strip()
        cidade = request.form.get("cidade", "").strip()
        uf = request.form.get("uf", "").strip().upper()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        cep = request.form.get("cep", "").strip()
        rua = request.form.get("rua", "").strip()
        numero = request.form.get("numero", "").strip()
        complemento = request.form.get("complemento", "").strip()
        bairro = request.form.get("bairro", "").strip()
        logo_file = request.files.get("logo")
        logo_base64 = request.form.get("logo_base64")
        modalidade_ids = [int(x) for x in request.form.getlist("modalidade_ids") if str(x).strip().isdigit()]

        if current_user.has_role("admin") or current_user.has_role("gestor_federacao"):
            id_associacao = request.form.get("id_associacao")
        else:
            id_associacao = academia.get("id_associacao")

        if not nome:
            flash("Informe o nome da academia.", "danger")
        elif not id_associacao:
            flash("Selecione a associação da academia.", "danger")
        else:
            # Modo associação: validar modalidades apenas as vinculadas à associação
            if modo_associacao_edit:
                cur.execute(
                    "SELECT modalidade_id FROM associacao_modalidades WHERE associacao_id = %s",
                    (id_associacao,),
                )
                ids_validos = {r["modalidade_id"] for r in cur.fetchall()}
                modalidade_ids = [mid for mid in modalidade_ids if mid in ids_validos]

            cur.execute(
                """
                UPDATE academias
                SET nome=%s, responsavel=%s, cidade=%s, uf=%s, email=%s, telefone=%s, 
                    cep=%s, rua=%s, numero=%s, complemento=%s, bairro=%s, id_associacao=%s
                WHERE id=%s
                """,
                (
                    nome,
                    responsavel or None,
                    cidade or None,
                    uf or None,
                    email or None,
                    telefone or None,
                    cep or None,
                    rua or None,
                    numero or None,
                    complemento or None,
                    bairro or None,
                    id_associacao,
                    academia_id,
                ),
            )
            if logo_base64 and logo_base64.startswith("data:"):
                salvar_logo_base64(logo_base64, "academia", academia_id)
            else:
                salvar_logo(logo_file, "academia", academia_id)
            cur.execute("DELETE FROM academia_modalidades WHERE academia_id = %s", (academia_id,))
            for mid in modalidade_ids:
                cur.execute(
                    "INSERT INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                    (academia_id, mid),
                )
            conn.commit()
            cur.close()
            conn.close()
            flash("Academia atualizada com sucesso!", "success")
            redirect_url = request.form.get("next") or back_url
            return redirect(redirect_url)

    cur.close()
    conn.close()

    logo_url = buscar_logo_url("academia", academia_id)
    return render_template(
        "academias/editar_academia.html",
        academia=academia,
        associacoes=associacoes,
        logo_url=logo_url,
        back_url=back_url,
        modalidades=modalidades,
        academia_modalidades_ids=academia_modalidades_ids,
        modo_associacao=modo_associacao_edit,
        modo_academia=current_user.has_role("gestor_academia") or current_user.has_role("professor"),
    )


# =====================================================
# 🔹 Gerenciar Categorias
# =====================================================
@associacao_bp.route("/categorias", methods=["GET", "POST"])
@login_required
def gerenciar_categorias():
    """Gerenciar categorias de competição."""
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin") or current_user.has_role("gestor_federacao")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("associacao.gerenciamento_associacao"))
    
    # Determinar associacao_id para o back_url
    associacao_id = request.args.get("associacao_id", type=int)
    id_assoc_user = getattr(current_user, "id_associacao", None)
    modo_ativo = session.get("modo_painel")
    
    import unicodedata
    
    def parse_int(valor):
        valor = (valor or "").strip()
        if not valor:
            return None
        try:
            return int(valor)
        except ValueError:
            return None

    def parse_float(valor):
        valor = (valor or "").strip().replace(",", ".")
        if not valor:
            return None
        try:
            return float(valor)
        except ValueError:
            return None

    def carregar_colunas(cursor, tabela):
        try:
            cursor.execute(f"SHOW COLUMNS FROM {tabela}")
            cols = cursor.fetchall()
            col_map = {}
            for c in cols:
                key = c["Field"].lower()
                col_map[key] = c["Field"]
                key_norm = "".join(
                    ch for ch in unicodedata.normalize("NFKD", key) if not unicodedata.combining(ch)
                )
                col_map.setdefault(key_norm, c["Field"])
            return col_map
        except Exception:
            return {}

    def resolver_colunas(col_map, aliases):
        resolved = {}
        missing = []
        for key, options in aliases.items():
            found = None
            for opt in options:
                if opt in col_map:
                    found = col_map[opt]
                    break
            if not found:
                missing.append(key)
            resolved[key] = found
        return resolved, missing

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
    except Exception as e:
        flash(f"Erro ao conectar no banco: {e}", "danger")
        return render_template("categorias/gerenciar_categorias.html", categorias=[], back_url=url_for("associacao.configuracoes_associacao"))

    tabela_categorias = "categorias"
    col_map = carregar_colunas(cursor, tabela_categorias)

    cols, missing = resolver_colunas(
        col_map,
        {
            "id": ["id"],
            "genero": ["genero", "sexo", "gender"],
            "id_classe": ["id_classe", "classe"],
            "categoria": ["categoria"],
            "nome_categoria": ["nome_categoria", "nome"],
            "peso_min": ["peso_min", "peso_minimo", "min_peso"],
            "peso_max": ["peso_max", "peso_maximo", "max_peso"],
            "idade_min": ["idade_min", "idade_minima", "min_idade"],
            "idade_max": ["idade_max", "idade_maxima", "max_idade"],
            "descricao": ["descricao", "notas", "observacao", "obs"],
            "ativo": ["ativo", "status", "ativo_flag"],
        },
    )

    if request.method == "POST":
        form_tipo = request.form.get("form_tipo")
        try:
            # Adicionar nova categoria
            if form_tipo == "nova_categoria":
                genero = request.form.get("genero", "").strip()
                id_classe = request.form.get("id_classe", "").strip()
                categoria = request.form.get("categoria", "").strip()
                nome_categoria = request.form.get("nome_categoria", "").strip()
                peso_min = parse_float(request.form.get("peso_min"))
                peso_max = parse_float(request.form.get("peso_max"))
                idade_min = parse_int(request.form.get("idade_min"))
                idade_max = parse_int(request.form.get("idade_max"))
                descricao = request.form.get("descricao", "").strip()
                ativo = 1 if request.form.get("ativo") == "1" else 0
                
                if not nome_categoria:
                    flash("Nome da categoria é obrigatório.", "danger")
                else:
                    campos_insert = []
                    valores_insert = []
                    placeholders = []
                    
                    if cols.get("genero"):
                        campos_insert.append(cols["genero"])
                        valores_insert.append(genero if genero else None)
                        placeholders.append("%s")
                    if cols.get("id_classe"):
                        campos_insert.append(cols["id_classe"])
                        valores_insert.append(id_classe if id_classe else None)
                        placeholders.append("%s")
                    if cols.get("categoria"):
                        campos_insert.append(cols["categoria"])
                        valores_insert.append(categoria if categoria else None)
                        placeholders.append("%s")
                    if cols.get("nome_categoria"):
                        campos_insert.append(cols["nome_categoria"])
                        valores_insert.append(nome_categoria)
                        placeholders.append("%s")
                    if cols.get("peso_min"):
                        campos_insert.append(cols["peso_min"])
                        valores_insert.append(peso_min)
                        placeholders.append("%s")
                    if cols.get("peso_max"):
                        campos_insert.append(cols["peso_max"])
                        valores_insert.append(peso_max)
                        placeholders.append("%s")
                    if cols.get("idade_min"):
                        campos_insert.append(cols["idade_min"])
                        valores_insert.append(idade_min)
                        placeholders.append("%s")
                    if cols.get("idade_max"):
                        campos_insert.append(cols["idade_max"])
                        valores_insert.append(idade_max)
                        placeholders.append("%s")
                    if cols.get("descricao"):
                        campos_insert.append(cols["descricao"])
                        valores_insert.append(descricao if descricao else None)
                        placeholders.append("%s")
                    if cols.get("ativo"):
                        campos_insert.append(cols["ativo"])
                        valores_insert.append(ativo)
                        placeholders.append("%s")
                    
                    cursor.execute(
                        f"""
                        INSERT INTO {tabela_categorias} ({", ".join(campos_insert)})
                        VALUES ({", ".join(placeholders)})
                        """,
                        tuple(valores_insert)
                    )
                    db.commit()
                    flash("Categoria adicionada com sucesso.", "success")
                    # Manter associacao_id na URL ao redirecionar
                    redirect_url = url_for("associacao.gerenciar_categorias")
                    if associacao_id or id_assoc_user:
                        redirect_url = url_for("associacao.gerenciar_categorias", associacao_id=associacao_id or id_assoc_user)
                    return redirect(redirect_url)
            
            # Atualizar categorias existentes
            elif form_tipo == "categorias" and not missing:
                ids = request.form.getlist("id")
                generos = request.form.getlist("genero")
                id_classes = request.form.getlist("id_classe")
                categorias = request.form.getlist("categoria")
                nomes = request.form.getlist("nome_categoria")
                pesos_min = request.form.getlist("peso_min")
                pesos_max = request.form.getlist("peso_max")
                idades_min = request.form.getlist("idade_min")
                idades_max = request.form.getlist("idade_max")
                descricoes = request.form.getlist("descricao")
                ativos = request.form.getlist("ativo")
                
                # Garantir que ativos tenha o mesmo tamanho de ids
                if cols.get("ativo") and len(ativos) < len(ids):
                    # Preencher com valores padrão (1 = ativo) para os que faltam
                    while len(ativos) < len(ids):
                        ativos.append("1")

                total = len(ids)
                # Verificar tamanhos dos arrays
                listas_verificar = [generos, id_classes, categorias, nomes, pesos_min, pesos_max, idades_min, idades_max, descricoes]
                if ativos:
                    listas_verificar.append(ativos)
                
                tamanhos = {
                    "ids": len(ids),
                    "generos": len(generos),
                    "id_classes": len(id_classes),
                    "categorias": len(categorias),
                    "nomes": len(nomes),
                    "pesos_min": len(pesos_min),
                    "pesos_max": len(pesos_max),
                    "idades_min": len(idades_min),
                    "idades_max": len(idades_max),
                    "descricoes": len(descricoes),
                }
                if ativos:
                    tamanhos["ativos"] = len(ativos)
                
                if not all(len(lst) == total for lst in listas_verificar):
                    mensagem_erro = f"Erro ao salvar categorias: dados inconsistentes. Tamanhos: {tamanhos}"
                    current_app.logger.error(mensagem_erro)
                    flash("Erro ao salvar categorias: dados inconsistentes. Verifique se todos os campos estão preenchidos.", "danger")
                else:
                    for i in range(total):
                        set_clauses = []
                        valores_update = []
                        
                        if cols.get("genero"):
                            set_clauses.append(f"{cols['genero']}=%s")
                            valores_update.append(generos[i].strip() if generos[i] and generos[i].strip() else None)
                        if cols.get("id_classe"):
                            set_clauses.append(f"{cols['id_classe']}=%s")
                            valores_update.append(id_classes[i].strip() if id_classes[i] and id_classes[i].strip() else None)
                        if cols.get("categoria"):
                            set_clauses.append(f"{cols['categoria']}=%s")
                            valores_update.append(categorias[i].strip() if categorias[i] and categorias[i].strip() else None)
                        if cols.get("nome_categoria"):
                            set_clauses.append(f"{cols['nome_categoria']}=%s")
                            valores_update.append(nomes[i].strip() if nomes[i] and nomes[i].strip() else None)
                        if cols.get("peso_min"):
                            set_clauses.append(f"{cols['peso_min']}=%s")
                            valores_update.append(parse_float(pesos_min[i]) if pesos_min[i] else None)
                        if cols.get("peso_max"):
                            set_clauses.append(f"{cols['peso_max']}=%s")
                            valores_update.append(parse_float(pesos_max[i]) if pesos_max[i] else None)
                        if cols.get("idade_min"):
                            set_clauses.append(f"{cols['idade_min']}=%s")
                            valores_update.append(parse_int(idades_min[i]) if idades_min[i] else None)
                        if cols.get("idade_max"):
                            set_clauses.append(f"{cols['idade_max']}=%s")
                            valores_update.append(parse_int(idades_max[i]) if idades_max[i] else None)
                        if cols.get("descricao"):
                            set_clauses.append(f"{cols['descricao']}=%s")
                            valores_update.append(descricoes[i].strip() if descricoes[i] and descricoes[i].strip() else None)
                        if cols.get("ativo"):
                            # Sempre incluir campo ativo, mesmo se não vier na lista (manter valor atual)
                            if ativos and i < len(ativos):
                                set_clauses.append(f"{cols['ativo']}=%s")
                                valores_update.append(1 if ativos[i] == "1" else 0)
                            else:
                                # Se não veio na lista, buscar valor atual do banco
                                cursor.execute(f"SELECT {cols['ativo']} FROM {tabela_categorias} WHERE {cols['id']} = %s", (ids[i],))
                                valor_atual = cursor.fetchone()
                                if valor_atual:
                                    set_clauses.append(f"{cols['ativo']}=%s")
                                    valores_update.append(valor_atual.get(cols['ativo'], 1))
                        
                        valores_update.append(ids[i])
                        
                        cursor.execute(
                            f"""
                            UPDATE {tabela_categorias}
                            SET {", ".join(set_clauses)}
                            WHERE {cols['id']}=%s
                            """,
                            tuple(valores_update)
                        )
                    db.commit()
                    flash("Categorias atualizadas com sucesso.", "success")
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar categorias: {e}", "danger")

    categorias_lista = []
    try:
        if not missing:
            campos_select = [
                f"{cols['id']} AS id",
                f"{cols['genero']} AS genero",
                f"{cols['id_classe']} AS id_classe",
                f"{cols['categoria']} AS categoria",
                f"{cols['nome_categoria']} AS nome_categoria",
                f"{cols['peso_min']} AS peso_min",
                f"{cols['peso_max']} AS peso_max",
                f"{cols['idade_min']} AS idade_min",
                f"{cols['idade_max']} AS idade_max",
                f"{cols['descricao']} AS descricao"
            ]
            if cols.get("ativo"):
                campos_select.append(f"{cols['ativo']} AS ativo")
            
            cursor.execute(
                f"""
                SELECT {", ".join(campos_select)}
                FROM {tabela_categorias}
                ORDER BY {cols['id']}
                """
            )
            categorias_lista = cursor.fetchall()
        else:
            flash(
                "Tabela de categorias não encontrada ou colunas ausentes: "
                + ", ".join(missing),
                "danger",
            )
    except Exception as e:
        flash(f"Erro ao carregar categorias: {e}", "danger")
    finally:
        cursor.close()
        db.close()

    # Determinar a URL de volta correta
    aid = associacao_id or id_assoc_user
    
    # Se tiver uma associação definida, voltar para configurações com o ID
    if aid:
        back_url = url_for("associacao.configuracoes_associacao", associacao_id=aid)
    else:
        # Caso contrário, voltar para gerenciamento (que pode pedir seleção)
        back_url = url_for("associacao.gerenciamento_associacao")
    
    return render_template(
        "categorias/gerenciar_categorias.html",
        categorias=categorias_lista,
        back_url=back_url,
    )


# =====================================================
# 🔹 Pré-cadastro — Gerar Links por Academia
# =====================================================
@associacao_bp.route("/precadastro")
@login_required
def precadastro():
    """Lista academias da associação e permite gerar links de pré-cadastro."""
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    associacao_id = getattr(current_user, "id_associacao", None)
    academia_selecionada_id = request.args.get("academia_id", type=int)
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar academias da associação
        if current_user.has_role("admin"):
            cur.execute("SELECT id, nome, slug FROM academias ORDER BY nome")
        else:
            cur.execute("""
                SELECT id, nome, slug 
                FROM academias 
                WHERE id_associacao = %s 
                ORDER BY nome
            """, (associacao_id,))
        
        academias = cur.fetchall()
        
        # Se uma academia foi selecionada, gerar o link
        link_publico = None
        academia_selecionada = None
        if academia_selecionada_id:
            # Verificar se a academia pertence à associação
            academia_encontrada = None
            for ac in academias:
                if ac["id"] == academia_selecionada_id:
                    academia_encontrada = ac
                    break
            
            if academia_encontrada:
                academia_selecionada = academia_encontrada
                academia_slug = academia_encontrada.get("slug")
                
                # Se não tem slug, criar um
                if not academia_slug:
                    academia_slug = _slugify(academia_encontrada["nome"])
                    base_slug = academia_slug
                    n = 1
                    while True:
                        cur.execute("SELECT id FROM academias WHERE slug = %s AND id != %s", (academia_slug, academia_selecionada_id))
                        if cur.fetchone() is None:
                            break
                        academia_slug = f"{base_slug}-{n}"
                        n += 1
                    cur.execute("UPDATE academias SET slug = %s WHERE id = %s", (academia_slug, academia_selecionada_id))
                    conn.commit()
                
                # Gerar link público
                from flask import url_for
                link_publico = url_for("precadastro.form_publico", academia_slug=academia_slug or academia_selecionada_id, _external=True)
        
    except Exception as e:
        flash(f"Erro ao carregar academias: {e}", "danger")
        academias = []
        link_publico = None
        academia_selecionada = None
    finally:
        cur.close()
        conn.close()
    
    return render_template(
        "associacao/precadastro.html",
        academias=academias,
        academia_selecionada=academia_selecionada,
        academia_selecionada_id=academia_selecionada_id,
        link_publico=link_publico,
    )
