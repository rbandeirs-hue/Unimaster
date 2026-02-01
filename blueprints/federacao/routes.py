# blueprints/federacao/routes.py
import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from config import get_db_connection

federacao_bp = Blueprint("federacao", __name__, url_prefix="/federacao")

LOGO_EXTENSOES = (".png", ".jpg", ".jpeg", ".gif")


def _pasta_logos():
    return os.path.join(current_app.root_path, "static", "uploads", "logos")


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
# 🔹 Painel da Federação
# =====================================================
@federacao_bp.route("/")
@login_required
def painel_federacao():

    # 🔥 RBAC – Apenas quem é gestor da federação ou admin
    if not (current_user.has_role("gestor_federacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("federacao.painel_federacao")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if current_user.has_role("admin"):
        cur.execute("""
            SELECT id, nome
            FROM associacoes
            ORDER BY nome
        """)
    else:
        cur.execute("""
            SELECT id, nome
            FROM associacoes
            WHERE id_federacao = %s
            ORDER BY nome
        """, (getattr(current_user, "id_federacao", None),))

    associacoes = cur.fetchall()

    # Dashboard: contagens
    stats = {"associacoes": 0, "academias": 0, "alunos": 0}
    try:
        stats["associacoes"] = len(associacoes)
        if current_user.has_role("admin"):
            cur.execute("SELECT COUNT(*) as c FROM academias")
            stats["academias"] = cur.fetchone().get("c") or 0
            cur.execute("SELECT COUNT(*) as c FROM alunos")
            stats["alunos"] = cur.fetchone().get("c") or 0
        else:
            fid = getattr(current_user, "id_federacao", None)
            if fid:
                cur.execute(
                    "SELECT COUNT(*) as c FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s",
                    (fid,),
                )
                stats["academias"] = cur.fetchone().get("c") or 0
                cur.execute(
                    "SELECT COUNT(*) as c FROM alunos a JOIN academias ac ON ac.id = a.id_academia JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s",
                    (fid,),
                )
                stats["alunos"] = cur.fetchone().get("c") or 0
    except Exception:
        pass

    cur.close()
    conn.close()

    return render_template(
        "painel/painel_federacao.html",
        usuario=current_user,
        associacoes=associacoes,
        stats=stats,
    )


# =====================================================
# 🔹 Gerenciamento da Federação (hub de módulos)
# =====================================================
@federacao_bp.route("/gerenciamento")
@login_required
def gerenciamento_federacao():
    if not (current_user.has_role("gestor_federacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    return render_template("painel/gerenciamento_federacao.html")


# =====================================================
# 🔹 Cadastro de Associação
# =====================================================
@federacao_bp.route("/associacoes/cadastro", methods=["GET", "POST"])
@login_required
def cadastro_associacao():

    if not (current_user.has_role("gestor_federacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    federacoes = []
    id_federacao_padrao = getattr(current_user, "id_federacao", None)

    if current_user.has_role("admin"):
        cur.execute("SELECT id, nome FROM federacoes ORDER BY nome")
        federacoes = cur.fetchall()
    elif id_federacao_padrao:
        cur.execute("SELECT id, nome FROM federacoes WHERE id = %s", (id_federacao_padrao,))
        federacoes = cur.fetchall()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        responsavel = request.form.get("responsavel", "").strip()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        logo_file = request.files.get("logo")

        if current_user.has_role("admin"):
            id_federacao = request.form.get("id_federacao")
        else:
            id_federacao = id_federacao_padrao

        if not nome:
            flash("Informe o nome da associação.", "danger")
        elif not id_federacao:
            flash("Selecione a federação da associação.", "danger")
        else:
            cur.execute("""
                INSERT INTO associacoes (nome, responsavel, email, telefone, id_federacao)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                nome,
                responsavel or None,
                email or None,
                telefone or None,
                id_federacao
            ))
            associacao_id = cur.lastrowid
            salvar_logo(logo_file, "associacao", associacao_id)
            conn.commit()
            cur.close()
            conn.close()
            flash("Associação cadastrada com sucesso!", "success")
            redirect_url = request.form.get("next") or back_url
            return redirect(redirect_url)

    cur.close()
    conn.close()

    return render_template(
        "associacoes/cadastro_associacao.html",
        federacoes=federacoes,
        id_federacao_selecionada=id_federacao_padrao,
        back_url=back_url
    )


# =====================================================
# 🔹 Cadastro de Federação
# =====================================================
@federacao_bp.route("/cadastro", methods=["GET", "POST"])
@login_required
def cadastro_federacao():

    if not current_user.has_role("admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("federacao.lista_federacoes")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        sigla = request.form.get("sigla", "").strip()
        cnpj = request.form.get("cnpj", "").strip()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        logo_file = request.files.get("logo")

        if not nome:
            flash("Informe o nome da federação.", "danger")
        else:
            cur.execute("""
                INSERT INTO federacoes (nome, sigla, cnpj, email, telefone)
                VALUES (%s, %s, %s, %s, %s)
            """, (nome, sigla or None, cnpj or None, email or None, telefone or None))
            federacao_id = cur.lastrowid
            salvar_logo(logo_file, "federacao", federacao_id)
            conn.commit()
            cur.close()
            conn.close()
            flash("Federação cadastrada com sucesso!", "success")
            redirect_url = request.form.get("next") or back_url
            return redirect(redirect_url)

    cur.close()
    conn.close()

    return render_template(
        "federacoes/cadastro_federacao.html",
        back_url=back_url
    )


# =====================================================
# 🔹 Lista de Federações
# =====================================================
@federacao_bp.route("/lista")
@login_required
def lista_federacoes():

    if not current_user.has_role("admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome, sigla, email, telefone FROM federacoes ORDER BY nome")
    federacoes = cur.fetchall()
    cur.close()
    conn.close()

    for fed in federacoes:
        fed["logo_url"] = buscar_logo_url("federacao", fed["id"])

    return render_template("federacoes/lista_federacoes.html", federacoes=federacoes)


# =====================================================
# 🔹 Editar Federação
# =====================================================
@federacao_bp.route("/editar/<int:federacao_id>", methods=["GET", "POST"])
@login_required
def editar_federacao(federacao_id):

    if not current_user.has_role("admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("federacao.lista_federacoes")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, sigla, cnpj, email, telefone FROM federacoes WHERE id = %s",
        (federacao_id,),
    )
    federacao = cur.fetchone()

    if not federacao:
        flash("Federação não encontrada.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("federacao.lista_federacoes"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        sigla = request.form.get("sigla", "").strip()
        cnpj = request.form.get("cnpj", "").strip()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        logo_file = request.files.get("logo")

        if not nome:
            flash("Informe o nome da federação.", "danger")
        else:
            cur.execute(
                """
                UPDATE federacoes
                SET nome=%s, sigla=%s, cnpj=%s, email=%s, telefone=%s
                WHERE id=%s
                """,
                (nome, sigla or None, cnpj or None, email or None, telefone or None, federacao_id),
            )
            salvar_logo(logo_file, "federacao", federacao_id)
            conn.commit()
            cur.close()
            conn.close()
            flash("Federação atualizada com sucesso!", "success")
            redirect_url = request.form.get("next") or back_url
            return redirect(redirect_url)

    cur.close()
    conn.close()

    logo_url = buscar_logo_url("federacao", federacao_id)
    return render_template(
        "federacoes/editar_federacao.html",
        federacao=federacao,
        logo_url=logo_url,
        back_url=back_url,
    )


# =====================================================
# 🔹 Lista de Associações
# =====================================================
@federacao_bp.route("/associacoes")
@login_required
def lista_associacoes():

    if not (current_user.has_role("admin") or current_user.has_role("gestor_federacao")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    federacao_id = request.args.get("federacao_id", type=int)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if current_user.has_role("admin"):
        if federacao_id:
            cur.execute("""
                SELECT ass.id, ass.nome, ass.email, ass.telefone, fed.nome AS federacao_nome
                FROM associacoes ass
                LEFT JOIN federacoes fed ON fed.id = ass.id_federacao
                WHERE ass.id_federacao = %s
                ORDER BY ass.nome
            """, (federacao_id,))
        else:
            cur.execute("""
                SELECT ass.id, ass.nome, ass.email, ass.telefone, fed.nome AS federacao_nome
                FROM associacoes ass
                LEFT JOIN federacoes fed ON fed.id = ass.id_federacao
                ORDER BY ass.nome
            """)
    else:
        cur.execute("""
            SELECT ass.id, ass.nome, ass.email, ass.telefone, fed.nome AS federacao_nome
            FROM associacoes ass
            LEFT JOIN federacoes fed ON fed.id = ass.id_federacao
            WHERE ass.id_federacao = %s
            ORDER BY ass.nome
        """, (getattr(current_user, "id_federacao", None),))

    associacoes = cur.fetchall()
    for assoc in associacoes:
        assoc["logo_url"] = buscar_logo_url("associacao", assoc["id"])
    cur.close()
    conn.close()

    return render_template("associacoes/lista_associacoes.html", associacoes=associacoes)
