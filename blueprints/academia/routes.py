# blueprints/academia/routes.py
from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, session, request, jsonify
from flask_login import login_required, current_user
from config import get_db_connection
from werkzeug.security import generate_password_hash
from math import ceil
from blueprints.auth.user_model import Usuario

academia_bp = Blueprint("academia", __name__, url_prefix="/academia")


def _get_academias_ids():
    """Retorna IDs de academias acessíveis pelo usuário."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ids = []
    try:
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
    except Exception:
        pass
    cur.close()
    conn.close()
    return ids


def _get_academia_filtro():
    """Retorna academia_id ativa (session ou primeira) e lista de academias para seleção."""
    ids = _get_academias_ids()
    if not ids:
        return None, []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    if len(ids) == 1:
        cur.execute("SELECT id, nome FROM academias WHERE id = %s", (ids[0],))
        ac = cur.fetchone()
        cur.close()
        conn.close()
        return ids[0], [ac] if ac else []
    aid = (
        request.args.get("academia_id", type=int)
        or (session.get("academia_gerenciamento_id") if session.get("modo_painel") == "academia" else None)
        or session.get("academia_usuarios_id")
    )
    if aid and aid in ids:
        session["academia_usuarios_id"] = aid
    else:
        session["academia_usuarios_id"] = ids[0]
        aid = ids[0]
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids)), tuple(ids))
    academias = cur.fetchall()
    cur.close()
    conn.close()
    return aid, academias


def _get_academia_gerenciamento():
    """Retorna academia_id ativa para gerenciamento e lista de academias para seleção."""
    ids = _get_academias_ids()
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
    else:
        session["academia_gerenciamento_id"] = ids[0]
        aid = ids[0]
    return aid, academias


def _get_academia_stats(academia_id=None):
    """Retorna stats da academia. Usa academia_id passado ou current_user.id_academia."""
    stats = {"alunos": 0, "turmas": 0, "professores": 0, "receitas_mes": 0.0, "despesas_mes": 0.0}
    aid = academia_id or getattr(current_user, "id_academia", None)
    if not aid:
        return stats
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) as c FROM alunos WHERE id_academia = %s", (aid,))
        stats["alunos"] = cur.fetchone().get("c") or 0
        cur.execute("SELECT COUNT(*) as c FROM turmas WHERE id_academia = %s", (aid,))
        stats["turmas"] = cur.fetchone().get("c") or 0
        cur.execute("SELECT COUNT(*) as c FROM professores WHERE id_academia = %s", (aid,))
        stats["professores"] = cur.fetchone().get("c") or 0
        mes, ano = date.today().month, date.today().year
        cur.execute(
            "SELECT COALESCE(SUM(valor), 0) as total FROM receitas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
            (aid, mes, ano),
        )
        stats["receitas_mes"] = float(cur.fetchone().get("total") or 0)
        cur.execute(
            "SELECT COALESCE(SUM(valor), 0) as total FROM despesas WHERE id_academia = %s AND MONTH(data) = %s AND YEAR(data) = %s",
            (aid, mes, ano),
        )
        stats["despesas_mes"] = float(cur.fetchone().get("total") or 0)
        cur.close()
        conn.close()
    except Exception:
        pass
    return stats


# =====================================================
# 🔹 Dash da Academia (apenas estatísticas)
# =====================================================
@academia_bp.route("/dash")
@login_required
def dash():
    if not (current_user.has_role("gestor_academia") or current_user.has_role("professor") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))
    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id
    stats = _get_academia_stats(academia_id)
    return render_template("painel/academia_dash.html", stats=stats, academias=academias, academia_id=academia_id)


# =====================================================
# 🔹 Painel da Academia (Gerenciamento - cards)
# =====================================================
@academia_bp.route("/")
@login_required
def painel_academia():

    # =====================================================
    # 🔥 RBAC — Perfis permitidos:
    #  - gestor_academia
    #  - professor
    #  - admin
    #  - gestor_federacao / gestor_associacao (com academias)
    # =====================================================
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin") or
        current_user.has_role("gestor_federacao") or
        current_user.has_role("gestor_associacao")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    academia_id, academias = _get_academia_gerenciamento()
    if not academia_id:
        flash("Nenhuma academia disponível.", "warning")
        return redirect(url_for("painel.home"))

    session["modo_painel"] = "academia"
    session["academia_gerenciamento_id"] = academia_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
    academia = cur.fetchone()
    cur.close()
    conn.close()

    return render_template(
        "painel/painel_academia.html",
        usuario=current_user,
        academia=academia,
        academias=academias,
        academia_id=academia_id,
    )


# =====================================================
# 🔹 Usuários da Academia (lista e cadastro)
# =====================================================
def _academia_usuarios_required():
    """Verifica se pode acessar gestão de usuários por academia."""
    if not (
        current_user.has_role("gestor_academia") or
        current_user.has_role("professor") or
        current_user.has_role("admin")
    ):
        flash("Acesso restrito.", "danger")
        return False
    ids = _get_academias_ids()
    if not ids:
        flash("Nenhuma academia disponível.", "warning")
        return False
    return True


@academia_bp.route("/usuarios")
@login_required
def lista_usuarios():
    if not _academia_usuarios_required():
        return redirect(url_for("academia.painel_academia"))

    academia_id, academias = _get_academia_filtro()
    busca = request.args.get("busca", "").strip()
    page = int(request.args.get("page", 1))
    por_pagina = 15
    offset = (page - 1) * por_pagina

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    where = "u.id_academia = %s"
    params = [academia_id]
    if busca:
        where += " AND (u.nome LIKE %s OR u.email LIKE %s)"
        params.extend([f"%{busca}%", f"%{busca}%"])

    cur.execute(f"SELECT COUNT(*) AS total FROM usuarios u WHERE {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(f"""
        SELECT u.id, u.nome, u.email, u.criado_em, COALESCE(u.ativo, 1) AS ativo
        FROM usuarios u
        WHERE {where}
        ORDER BY u.nome
        LIMIT %s OFFSET %s
    """, params + [por_pagina, offset])
    usuarios = cur.fetchall()

    for u in usuarios:
        cur.execute("""
            SELECT r.nome FROM roles r
            JOIN roles_usuario ru ON ru.role_id = r.id
            WHERE ru.usuario_id = %s
        """, (u["id"],))
        roles_nomes = [r["nome"] for r in cur.fetchall()]
        u["roles"] = ", ".join(roles_nomes) or "—"
        u["niveis_acesso"] = Usuario.niveis_acesso_por_roles(roles_nomes) if roles_nomes else ["—"]

    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    row = cur.fetchone()
    academia_nome = row.get("nome", "") if row else ""

    cur.close()
    conn.close()

    total_paginas = ceil(total / por_pagina) if total > 0 else 1

    return render_template(
        "academia/lista_usuarios.html",
        usuarios=usuarios,
        busca=busca,
        pagina_atual=page,
        total_paginas=total_paginas,
        academias=academias,
        academia_id=academia_id,
        academia_nome=academia_nome,
    )


@academia_bp.route("/usuarios/cadastro", methods=["GET", "POST"])
@login_required
def cadastro_usuario():
    if not _academia_usuarios_required():
        return redirect(url_for("academia.painel_academia"))

    academia_id, academias = _get_academia_filtro()
    back_url = request.args.get("next") or url_for("academia.lista_usuarios", academia_id=academia_id)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) as chave FROM roles WHERE chave IN ('aluno', 'professor', 'gestor_academia', 'responsavel') ORDER BY nome")
    roles_academia = cur.fetchall()
    cur.execute("SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) as chave FROM roles ORDER BY nome")
    roles_todas = cur.fetchall()

    # Alunos da academia: para Aluno (sem usuario_id), para Responsável (todos)
    cur.execute(
        """SELECT id, nome, usuario_id FROM alunos WHERE id_academia = %s AND ativo = 1 AND status = 'ativo'
           ORDER BY nome""",
        (academia_id,),
    )
    todos_alunos = cur.fetchall()
    alunos_para_aluno = [a for a in todos_alunos if not a.get("usuario_id")]
    alunos_para_responsavel = todos_alunos
    cur.close()
    conn.close()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip()
        senha = (request.form.get("senha") or "").strip()
        roles_escolhidas = request.form.getlist("roles")
        id_academia_sel = request.form.get("id_academia", type=int)
        ids = _get_academias_ids()
        if id_academia_sel and id_academia_sel in ids:
            academia_id = id_academia_sel
        elif ids:
            academia_id = ids[0]

        if not nome or not email or not senha or not roles_escolhidas:
            flash("Preencha nome, e-mail, senha e selecione ao menos uma role.", "danger")
            return redirect(url_for("academia.cadastro_usuario"))

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
        if cur.fetchone():
            flash("Já existe usuário com este e-mail.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for("academia.cadastro_usuario"))

        cur.execute(
            """INSERT INTO usuarios (nome, email, senha, id_academia) VALUES (%s, %s, %s, %s)""",
            (nome, email, generate_password_hash(senha), academia_id),
        )
        user_id = cur.lastrowid
        for rid in roles_escolhidas:
            cur.execute("INSERT INTO roles_usuario (usuario_id, role_id) VALUES (%s, %s)", (user_id, rid))

        # Vínculo academia
        cur.execute("INSERT INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)", (user_id, academia_id))

        # Role aluno: vincular usuário a um aluno (alunos.usuario_id)
        cur.execute("SELECT id FROM roles WHERE chave = 'aluno'")
        r_aluno = cur.fetchone()
        if r_aluno and str(r_aluno["id"]) in roles_escolhidas:
            aluno_id = request.form.get("aluno_id", type=int)
            if aluno_id:
                cur.execute(
                    "UPDATE alunos SET usuario_id = %s WHERE id = %s AND id_academia = %s AND usuario_id IS NULL",
                    (user_id, aluno_id, academia_id),
                )

        # Role responsavel: vincular a vários alunos (responsavel_alunos)
        cur.execute("SELECT id FROM roles WHERE chave = 'responsavel'")
        r_resp = cur.fetchone()
        if r_resp and str(r_resp["id"]) in roles_escolhidas:
            for x in request.form.getlist("aluno_ids"):
                try:
                    aid = int(x)
                    cur.execute(
                        "SELECT 1 FROM alunos WHERE id = %s AND id_academia = %s",
                        (aid, academia_id),
                    )
                    if cur.fetchone():
                        cur.execute(
                            "INSERT IGNORE INTO responsavel_alunos (usuario_id, aluno_id) VALUES (%s, %s)",
                            (user_id, aid),
                        )
                except (ValueError, TypeError):
                    pass

        conn.commit()
        cur.close()
        conn.close()
        flash("Usuário cadastrado com sucesso!", "success")
        return redirect(back_url)

    return render_template(
        "academia/cadastro_usuario.html",
        roles=roles_academia if len(roles_academia) >= 2 else roles_todas,
        academias=academias,
        academia_id=academia_id,
        alunos_para_aluno=alunos_para_aluno,
        alunos_para_responsavel=alunos_para_responsavel,
        back_url=back_url,
    )


@academia_bp.route("/<int:academia_id>/alunos-para-vinculo")
@login_required
def api_alunos_para_vinculo(academia_id):
    """Retorna alunos da academia para vincular em usuário (aluno ou responsável)."""
    ids = _get_academias_ids()
    if academia_id not in ids:
        return jsonify({"alunos": [], "disponiveis_aluno": []})
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT id, nome, usuario_id FROM alunos WHERE id_academia = %s AND ativo = 1 AND status = 'ativo'
           ORDER BY nome""",
        (academia_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    disponiveis_aluno = [{"id": r["id"], "nome": r["nome"]} for r in rows if not r.get("usuario_id")]
    return jsonify({"alunos": rows, "disponiveis_aluno": disponiveis_aluno})


@academia_bp.route("/usuarios/<int:user_id>/toggle-ativo", methods=["POST"])
@login_required
def toggle_usuario_ativo(user_id):
    """Alterna status ativo/inativo do usuário."""
    if not _academia_usuarios_required():
        return redirect(url_for("academia.painel_academia"))

    if user_id == current_user.id:
        flash("Você não pode inativar a si mesmo.", "warning")
        return redirect(request.referrer or url_for("academia.lista_usuarios"))

    ids = _get_academias_ids()
    if not ids:
        flash("Nenhuma academia acessível.", "danger")
        return redirect(url_for("academia.painel_academia"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    # Admin pode alterar qualquer usuário; demais apenas usuários das academias em escopo
    if current_user.has_role("admin"):
        cur.execute("SELECT id, ativo FROM usuarios WHERE id = %s", (user_id,))
    else:
        cur.execute(
            "SELECT id, ativo FROM usuarios WHERE id = %s AND id_academia IN ({})".format(
                ",".join(["%s"] * len(ids))
            ),
            (user_id,) + tuple(ids),
        )
    u = cur.fetchone()
    if not u:
        cur.close()
        conn.close()
        flash("Usuário não encontrado ou fora do seu escopo.", "danger")
        return redirect(request.referrer or url_for("academia.lista_usuarios"))

    novo = 0 if u.get("ativo", 1) else 1
    cur.execute("UPDATE usuarios SET ativo = %s WHERE id = %s", (novo, user_id))
    conn.commit()
    cur.close()
    conn.close()

    flash("Usuário {} com sucesso.".format("ativado" if novo else "inativado"), "success")
    return redirect(request.referrer or url_for("academia.lista_usuarios"))
