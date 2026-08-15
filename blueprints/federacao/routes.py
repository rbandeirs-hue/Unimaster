# blueprints/federacao/routes.py
import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from config import get_db_connection
from utils.upload_seguro import validar_upload, UploadInvalido

federacao_bp = Blueprint("federacao", __name__, url_prefix="/federacao")

LOGO_EXTENSOES = (".png", ".jpg", ".jpeg", ".gif")


def _pasta_logos():
    return os.path.join(current_app.root_path, "static", "uploads", "logos")


def salvar_logo(file_storage, prefixo, entidade_id):
    if not file_storage or not file_storage.filename:
        return None
    try:
        ext = validar_upload(file_storage, categorias=["imagem"])
    except UploadInvalido:
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
    filename = f"{prefixo}_{entidade_id}.{ext}"
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
# 🔹 Painel da Federação (redirecionado para gerenciamento)
# =====================================================
@federacao_bp.route("/")
@login_required
def painel_federacao():
    # Redireciona direto para o gerenciamento da federação
    return redirect(url_for("federacao.gerenciamento_federacao"))


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
# 🔹 Configurações da Federação
# =====================================================
@federacao_bp.route("/configuracoes")
@login_required
def configuracoes_federacao():
    if not (current_user.has_role("gestor_federacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    federacao_id = request.args.get("federacao_id", type=int)
    id_fed_user = getattr(current_user, "id_federacao", None)

    if current_user.has_role("admin") and not federacao_id:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, nome FROM federacoes ORDER BY nome")
        federacoes = cur.fetchall()
        cur.close()
        conn.close()
        return render_template(
            "painel/configuracoes_federacao.html",
            federacao=None,
            federacoes=federacoes,
        )

    fid = federacao_id or id_fed_user
    if not fid:
        flash("Selecione uma federação.", "warning")
        return redirect(url_for("federacao.gerenciamento_federacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM federacoes WHERE id = %s", (fid,))
    federacao = cur.fetchone()
    cur.close()
    conn.close()

    if not federacao:
        flash("Federação não encontrada.", "danger")
        return redirect(url_for("federacao.gerenciamento_federacao"))

    return render_template(
        "painel/configuracoes_federacao.html",
        federacao=federacao,
        federacoes=None,
    )


# =====================================================
# 🔹 Cadastro de Associação
# =====================================================
@federacao_bp.route("/associacoes/cadastro", methods=["GET", "POST"])
@login_required
def cadastro_associacao():

    if not (current_user.has_role("gestor_federacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("federacao.lista_associacoes")
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

    cur.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY nome")
    modalidades = cur.fetchall()

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
            id_federacao = id_federacao_padrao

        if not nome:
            flash("Informe o nome da associação.", "danger")
        elif not id_federacao:
            flash("Selecione a federação da associação.", "danger")
        else:
            cur.execute("""
                INSERT INTO associacoes (nome, responsavel, email, telefone, cep, rua, numero, complemento, bairro, cidade, uf, id_federacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
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
                id_federacao
            ))
            associacao_id = cur.lastrowid
            salvar_logo(logo_file, "associacao", associacao_id)
            for mid in modalidade_ids:
                cur.execute(
                    "INSERT IGNORE INTO associacao_modalidades (associacao_id, modalidade_id) VALUES (%s, %s)",
                    (associacao_id, mid),
                )
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
        back_url=back_url,
        modalidades=modalidades,
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

    cur.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY nome")
    modalidades = cur.fetchall()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        sigla = request.form.get("sigla", "").strip()
        cnpj = request.form.get("cnpj", "").strip()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        logo_file = request.files.get("logo")
        modalidade_ids = [int(x) for x in request.form.getlist("modalidade_ids") if str(x).strip().isdigit()]

        if not nome:
            flash("Informe o nome da federação.", "danger")
        else:
            cur.execute("""
                INSERT INTO federacoes (nome, sigla, cnpj, email, telefone)
                VALUES (%s, %s, %s, %s, %s)
            """, (nome, sigla or None, cnpj or None, email or None, telefone or None))
            federacao_id = cur.lastrowid
            salvar_logo(logo_file, "federacao", federacao_id)
            for mid in modalidade_ids:
                cur.execute(
                    "INSERT IGNORE INTO federacao_modalidades (federacao_id, modalidade_id) VALUES (%s, %s)",
                    (federacao_id, mid),
                )
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
        back_url=back_url,
        modalidades=modalidades,
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

    cur.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY nome")
    modalidades = cur.fetchall()
    cur.execute("SELECT modalidade_id FROM federacao_modalidades WHERE federacao_id = %s", (federacao_id,))
    federacao_modalidades_ids = {r["modalidade_id"] for r in cur.fetchall()}

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        sigla = request.form.get("sigla", "").strip()
        cnpj = request.form.get("cnpj", "").strip()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        logo_file = request.files.get("logo")
        modalidade_ids = [int(x) for x in request.form.getlist("modalidade_ids") if str(x).strip().isdigit()]

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
            cur.execute("DELETE FROM federacao_modalidades WHERE federacao_id = %s", (federacao_id,))
            for mid in modalidade_ids:
                cur.execute(
                    "INSERT INTO federacao_modalidades (federacao_id, modalidade_id) VALUES (%s, %s)",
                    (federacao_id, mid),
                )
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
        modalidades=modalidades,
        federacao_modalidades_ids=federacao_modalidades_ids,
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
