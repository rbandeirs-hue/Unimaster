# blueprints/associacao/routes.py
import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from config import get_db_connection

associacao_bp = Blueprint("associacao", __name__, url_prefix="/associacao")

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

    cur.close()
    conn.close()

    return render_template(
        "painel/painel_associacao.html",
        usuario=current_user,
        academias=academias
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

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        responsavel = request.form.get("responsavel", "").strip()
        cidade = request.form.get("cidade", "").strip()
        uf = request.form.get("uf", "").strip().upper()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        logo_file = request.files.get("logo")

        if current_user.has_role("admin"):
            id_associacao = request.form.get("id_associacao")
        else:
            id_associacao = id_associacao_padrao

        if not nome:
            flash("Informe o nome da academia.", "danger")
        elif not id_associacao:
            flash("Selecione a associação da academia.", "danger")
        else:
            cur.execute("""
                INSERT INTO academias (nome, responsavel, cidade, uf, email, telefone, id_associacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                nome,
                responsavel or None,
                cidade or None,
                uf or None,
                email or None,
                telefone or None,
                id_associacao
            ))
            academia_id = cur.lastrowid
            salvar_logo(logo_file, "academia", academia_id)
            conn.commit()
            cur.close()
            conn.close()
            flash("Academia cadastrada com sucesso!", "success")
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
        associacao_nome=associacao_nome_cadastro
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

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    if escopo_associacao_usuario and id_assoc_user:
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

    if not (current_user.has_role("gestor_federacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("federacao.lista_associacoes")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id, nome, responsavel, email, telefone, id_federacao
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

    if current_user.has_role("gestor_federacao") and associacao.get("id_federacao") != getattr(current_user, "id_federacao", None):
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

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        responsavel = request.form.get("responsavel", "").strip()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        logo_file = request.files.get("logo")

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
                SET nome=%s, responsavel=%s, email=%s, telefone=%s, id_federacao=%s
                WHERE id=%s
                """,
                (
                    nome,
                    responsavel or None,
                    email or None,
                    telefone or None,
                    id_federacao,
                    associacao_id,
                ),
            )
            salvar_logo(logo_file, "associacao", associacao_id)
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
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    back_url = request.args.get("next") or request.referrer or url_for("associacao.lista_academias")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT ac.id, ac.nome, ac.responsavel, ac.cidade, ac.uf, ac.email, ac.telefone,
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

    if current_user.has_role("gestor_associacao") and academia.get("id_associacao") != getattr(current_user, "id_associacao", None):
        flash("Acesso negado.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("associacao.lista_academias"))

    if current_user.has_role("gestor_federacao") and academia.get("id_federacao") != getattr(current_user, "id_federacao", None):
        flash("Acesso negado.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("associacao.lista_academias"))

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

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        responsavel = request.form.get("responsavel", "").strip()
        cidade = request.form.get("cidade", "").strip()
        uf = request.form.get("uf", "").strip().upper()
        email = request.form.get("email", "").strip()
        telefone = request.form.get("telefone", "").strip()
        logo_file = request.files.get("logo")

        if current_user.has_role("admin") or current_user.has_role("gestor_federacao"):
            id_associacao = request.form.get("id_associacao")
        else:
            id_associacao = academia.get("id_associacao")

        if not nome:
            flash("Informe o nome da academia.", "danger")
        elif not id_associacao:
            flash("Selecione a associação da academia.", "danger")
        else:
            cur.execute(
                """
                UPDATE academias
                SET nome=%s, responsavel=%s, cidade=%s, uf=%s, email=%s, telefone=%s, id_associacao=%s
                WHERE id=%s
                """,
                (
                    nome,
                    responsavel or None,
                    cidade or None,
                    uf or None,
                    email or None,
                    telefone or None,
                    id_associacao,
                    academia_id,
                ),
            )
            salvar_logo(logo_file, "academia", academia_id)
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
    )
