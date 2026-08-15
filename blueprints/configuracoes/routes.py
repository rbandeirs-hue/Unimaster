# ======================================================
# Configurações (somente admin): Modalidades globais,
# vincular a uma ou mais academias.
# ======================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from functools import wraps
from config import get_db_connection
from utils.modalidades import filtro_visibilidade_sql

bp_configuracoes = Blueprint("configuracoes", __name__, url_prefix="/configuracoes")


def admin_required(f):
    @wraps(f)
    def _view(*a, **kw):
        if not current_user.is_authenticated or not current_user.has_role("admin"):
            flash("Acesso restrito a administradores.", "danger")
            return redirect(url_for("painel.home"))
        return f(*a, **kw)
    return _view


def modalidades_access_required(f):
    @wraps(f)
    def _view(*a, **kw):
        if not current_user.is_authenticated:
            flash("Faça login para continuar.", "danger")
            return redirect(url_for("painel.home"))
        if current_user.has_role("admin") or current_user.has_role("gestor_academia"):
            return f(*a, **kw)
        flash("Acesso restrito a administradores e gestores de academia.", "danger")
        return redirect(url_for("painel.home"))
    return _view


def _academias_do_usuario():
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    academias = []
    try:
        if current_user.has_role("admin"):
            cur.execute(
                """
                SELECT ac.id, ac.nome, ac.id_associacao, ass.nome AS associacao_nome
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                ORDER BY ac.nome
                """
            )
            academias = cur.fetchall()
        else:
            cur.execute(
                """
                SELECT ac.id, ac.nome, ac.id_associacao, ass.nome AS associacao_nome
                FROM academias ac
                LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
                JOIN usuarios_academias ua ON ua.academia_id = ac.id
                WHERE ua.usuario_id = %s
                ORDER BY ac.nome
                """,
                (current_user.id,),
            )
            academias = cur.fetchall()
    finally:
        cur.close()
        db.close()
    return academias


def _contexto_modalidades():
    academias = _academias_do_usuario()
    modo = session.get("modo_painel")

    # Operando como ASSOCIAÇÃO: escopo da associação, mesmo para quem acumula admin.
    # Sem isso, o admin veria as modalidades PRIVADAS de qualquer academia.
    if modo == "associacao":
        id_assoc = (getattr(current_user, "id_associacao", None)
                    or session.get("associacao_gerenciamento_id"))
        if not id_assoc and academias:
            id_assoc = academias[0].get("id_associacao")
        return {
            "is_admin": False,
            "academias_permitidas": academias,
            "academia_contexto": None,
            "academia_contexto_id": None,
            "id_associacao_contexto": id_assoc,
        }

    # Operando como ACADEMIA: escopo da academia selecionada, mesmo para admin.
    if modo == "academia" and academias:
        ids = [a["id"] for a in academias]
        academia_id = (
            request.args.get("academia_id", type=int)
            or session.get("academia_gerenciamento_id")
            or session.get("academia_usuarios_id")
            or ids[0]
        )
        if academia_id not in ids:
            academia_id = ids[0]
        session["academia_gerenciamento_id"] = academia_id
        session["academia_usuarios_id"] = academia_id
        ac = next((a for a in academias if a["id"] == academia_id), academias[0])
        return {
            "is_admin": False,
            "academias_permitidas": academias,
            "academia_contexto": ac,
            "academia_contexto_id": ac["id"],
            "id_associacao_contexto": ac.get("id_associacao"),
        }

    # Fora de um modo escopado (painel admin global): admin vê tudo.
    if current_user.has_role("admin"):
        return {
            "is_admin": True,
            "academias_permitidas": academias,
            "academia_contexto": None,
            "academia_contexto_id": None,
            "id_associacao_contexto": None,
        }
    if not academias:
        return None

    ids = [a["id"] for a in academias]
    academia_id = (
        request.args.get("academia_id", type=int)
        or session.get("academia_gerenciamento_id")
        or session.get("academia_usuarios_id")
        or ids[0]
    )
    if academia_id not in ids:
        academia_id = ids[0]
    session["academia_gerenciamento_id"] = academia_id
    session["academia_usuarios_id"] = academia_id

    academia_contexto = next((a for a in academias if a["id"] == academia_id), academias[0])
    return {
        "is_admin": False,
        "academias_permitidas": academias,
        "academia_contexto": academia_contexto,
        "academia_contexto_id": academia_contexto["id"],
        "id_associacao_contexto": academia_contexto.get("id_associacao"),
    }


@bp_configuracoes.route("")
@login_required
@admin_required
def hub():
    return render_template("configuracoes/hub.html")


@bp_configuracoes.route("/modalidades")
@login_required
@modalidades_access_required
def modalidades_lista():
    contexto = _contexto_modalidades()
    if not contexto:
        flash("Nenhuma academia vinculada ao seu usuário.", "warning")
        return redirect(url_for("painel.home"))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        try:
            where = ""
            params = ()
            if not contexto["is_admin"]:
                where, params = filtro_visibilidade_sql(
                    id_associacao=contexto["id_associacao_contexto"],
                    id_academia=contexto["academia_contexto_id"],
                )
            cur.execute(
                f"""
                SELECT m.id, m.nome, m.descricao, m.ativo,
                       COALESCE(m.visibilidade, 'publica') as visibilidade
                FROM modalidade m
                WHERE 1=1 {where}
                ORDER BY m.nome
                """,
                params,
            )
            modalidades = cur.fetchall()
        except Exception:
            cur.execute("SELECT id, nome, descricao, ativo FROM modalidade ORDER BY nome")
            modalidades = cur.fetchall()
            for m in modalidades:
                m["visibilidade"] = "publica"
    except Exception:
        db.close()
        flash("Tabela modalidade não encontrada. Execute a migration add_modalidade_academia_modalidades.sql", "danger")
        return redirect(url_for("configuracoes.hub"))
    mod_academias = {}
    try:
        cur.execute(
            """
            SELECT am.modalidade_id, ac.id AS academia_id, ac.nome AS academia_nome
            FROM academia_modalidades am
            JOIN academias ac ON ac.id = am.academia_id
            ORDER BY ac.nome
            """
        )
        for r in cur.fetchall():
            mid = r["modalidade_id"]
            mod_academias.setdefault(mid, []).append({"id": r["academia_id"], "nome": r["academia_nome"]})
    except Exception:
        pass
    for m in modalidades:
        m["academias"] = mod_academias.get(m["id"], [])
    db.close()
    return render_template(
        "configuracoes/modalidades_lista.html",
        modalidades=modalidades,
        academias_contexto=contexto["academias_permitidas"],
        academia_contexto_id=contexto["academia_contexto_id"],
        is_admin=contexto["is_admin"],
    )


@bp_configuracoes.route("/modalidades/cadastro", methods=["GET", "POST"])
@login_required
@modalidades_access_required
def modalidades_cadastro():
    contexto = _contexto_modalidades()
    if not contexto:
        flash("Nenhuma academia vinculada ao seu usuário.", "warning")
        return redirect(url_for("painel.home"))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    if contexto["is_admin"]:
        cur.execute("SELECT id, nome FROM academias ORDER BY nome")
        academias = cur.fetchall()
        cur.execute("SELECT id, nome FROM associacoes ORDER BY nome")
        associacoes = cur.fetchall()
    else:
        academias = [{"id": a["id"], "nome": a["nome"]} for a in contexto["academias_permitidas"]]
        associacoes = []

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        ativo = 1 if request.form.get("ativo") == "1" else 0
        visibilidade = request.form.get("visibilidade") or "publica"
        id_associacao = request.form.get("id_associacao", type=int) or None
        id_academia = request.form.get("id_academia", type=int) or None
        if not contexto["is_admin"]:
            id_academia = contexto["academia_contexto_id"]
            id_associacao = None
        if visibilidade == "privada" and id_associacao and id_academia:
            id_academia = None  # Só um dono
        elif visibilidade == "publica":
            id_associacao = id_academia = None
        if contexto["is_admin"]:
            academia_ids = [int(x) for x in request.form.getlist("academia_ids") if str(x).strip()]
        else:
            academia_ids = [contexto["academia_contexto_id"]]
        if not nome:
            flash("Nome da modalidade é obrigatório.", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_cadastro"))
        try:
            cur.execute("SELECT id FROM modalidade WHERE nome = %s", (nome,))
            row = cur.fetchone()
            if row:
                modalidade_id = row["id"]
                for aid in academia_ids:
                    cur.execute(
                        "SELECT 1 FROM academia_modalidades WHERE academia_id = %s AND modalidade_id = %s",
                        (aid, modalidade_id),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT IGNORE INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                            (aid, modalidade_id),
                        )
                db.commit()
                flash("Modalidade existente vinculada às academias selecionadas.", "success")
            else:
                try:
                    cur.execute(
                        "INSERT INTO modalidade (nome, descricao, ativo, visibilidade, id_associacao, id_academia) VALUES (%s, %s, %s, %s, %s, %s)",
                        (nome, descricao, ativo, visibilidade, id_associacao, id_academia),
                    )
                except Exception:
                    cur.execute(
                        "INSERT INTO modalidade (nome, ativo, visibilidade, id_associacao, id_academia) VALUES (%s, %s, %s, %s, %s)",
                        (nome, ativo, visibilidade, id_associacao, id_academia),
                    )
                modalidade_id = cur.lastrowid
                for aid in academia_ids:
                    cur.execute(
                        "INSERT IGNORE INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                        (aid, modalidade_id),
                    )
                db.commit()
                flash("Modalidade cadastrada e vinculada às academias com sucesso.", "success")
            db.close()
            return redirect(url_for("configuracoes.modalidades_lista"))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao salvar: {e}", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_cadastro"))

    db.close()
    return render_template(
        "configuracoes/modalidades_cadastro.html",
        academias=academias,
        associacoes=associacoes,
        is_admin=contexto["is_admin"],
        academia_contexto=contexto["academia_contexto"],
        academias_contexto=contexto["academias_permitidas"],
        academia_contexto_id=contexto["academia_contexto_id"],
    )


@bp_configuracoes.route("/modalidades/<int:modalidade_id>/editar", methods=["GET", "POST"])
@login_required
@modalidades_access_required
def modalidades_editar(modalidade_id):
    contexto = _contexto_modalidades()
    if not contexto:
        flash("Nenhuma academia vinculada ao seu usuário.", "warning")
        return redirect(url_for("painel.home"))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome, descricao, ativo, visibilidade, id_associacao, id_academia FROM modalidade WHERE id = %s", (modalidade_id,))
    except Exception:
        cur.execute("SELECT id, nome, descricao, ativo FROM modalidade WHERE id = %s", (modalidade_id,))
    modalidade = cur.fetchone()
    if not modalidade:
        db.close()
        flash("Modalidade não encontrada.", "danger")
        return redirect(url_for("configuracoes.modalidades_lista"))
    if not contexto["is_admin"]:
        visivel = (modalidade.get("visibilidade") or "publica") == "publica" or (
            modalidade.get("visibilidade") == "privada"
            and modalidade.get("id_academia") == contexto["academia_contexto_id"]
        )
        if not visivel:
            db.close()
            flash("Você não pode editar esta modalidade.", "danger")
            return redirect(url_for("configuracoes.modalidades_lista"))
    for k in ("visibilidade", "id_associacao", "id_academia"):
        if k not in modalidade:
            modalidade[k] = None
    if not modalidade.get("visibilidade"):
        modalidade["visibilidade"] = "publica"

    if contexto["is_admin"]:
        cur.execute("SELECT id, nome FROM academias ORDER BY nome")
        academias = cur.fetchall()
        cur.execute("SELECT id, nome FROM associacoes ORDER BY nome")
        associacoes = cur.fetchall()
    else:
        academias = [{"id": a["id"], "nome": a["nome"]} for a in contexto["academias_permitidas"]]
        associacoes = []
    try:
        cur.execute("SELECT academia_id FROM academia_modalidades WHERE modalidade_id = %s", (modalidade_id,))
        vinculadas = {r["academia_id"] for r in cur.fetchall()}
    except Exception:
        vinculadas = set()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        ativo = 1 if request.form.get("ativo") == "1" else 0
        visibilidade = request.form.get("visibilidade") or "publica"
        id_associacao = request.form.get("id_associacao", type=int) or None
        id_academia = request.form.get("id_academia", type=int) or None
        if not contexto["is_admin"]:
            id_academia = contexto["academia_contexto_id"]
            id_associacao = None
        if visibilidade == "privada" and id_associacao and id_academia:
            id_academia = None
        elif visibilidade == "publica":
            id_associacao = id_academia = None
        if contexto["is_admin"]:
            academia_ids = [int(x) for x in request.form.getlist("academia_ids") if str(x).strip()]
        else:
            academia_ids = [contexto["academia_contexto_id"]]
        if not nome:
            flash("Nome da modalidade é obrigatório.", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_editar", modalidade_id=modalidade_id))
        try:
            try:
                cur.execute("UPDATE modalidade SET nome = %s, descricao = %s, ativo = %s, visibilidade = %s, id_associacao = %s, id_academia = %s WHERE id = %s",
                            (nome, descricao, ativo, visibilidade, id_associacao, id_academia, modalidade_id))
            except Exception:
                cur.execute("UPDATE modalidade SET nome = %s, descricao = %s, ativo = %s WHERE id = %s", (nome, descricao, ativo, modalidade_id))
            cur.execute("DELETE FROM academia_modalidades WHERE modalidade_id = %s", (modalidade_id,))
            for aid in academia_ids:
                cur.execute(
                    "INSERT IGNORE INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                    (aid, modalidade_id),
                )
            db.commit()
            flash("Modalidade atualizada com sucesso.", "success")
            db.close()
            return redirect(url_for("configuracoes.modalidades_lista"))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao salvar: {e}", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_editar", modalidade_id=modalidade_id))

    db.close()
    return render_template(
        "configuracoes/modalidades_editar.html",
        modalidade=modalidade,
        academias=academias,
        associacoes=associacoes,
        vinculadas=vinculadas,
        is_admin=contexto["is_admin"],
        academia_contexto=contexto["academia_contexto"],
        academias_contexto=contexto["academias_permitidas"],
        academia_contexto_id=contexto["academia_contexto_id"],
    )


@bp_configuracoes.route("/modalidades/<int:modalidade_id>/vincular", methods=["GET", "POST"])
@login_required
@admin_required
def modalidades_vincular(modalidade_id):
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome, descricao, ativo FROM modalidade WHERE id = %s", (modalidade_id,))
    modalidade = cur.fetchone()
    if not modalidade:
        db.close()
        flash("Modalidade não encontrada.", "danger")
        return redirect(url_for("configuracoes.modalidades_lista"))

    cur.execute("SELECT id, nome FROM academias ORDER BY nome")
    academias = cur.fetchall()
    try:
        cur.execute("SELECT academia_id FROM academia_modalidades WHERE modalidade_id = %s", (modalidade_id,))
        vinculadas = {r["academia_id"] for r in cur.fetchall()}
    except Exception:
        vinculadas = set()

    if request.method == "POST":
        novo_ids = [int(x) for x in request.form.getlist("academia_ids") if str(x).strip()]
        try:
            cur.execute("DELETE FROM academia_modalidades WHERE modalidade_id = %s", (modalidade_id,))
            for aid in novo_ids:
                cur.execute(
                    "INSERT INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s, %s)",
                    (aid, modalidade_id),
                )
            db.commit()
            flash("Vínculos atualizados.", "success")
            db.close()
            return redirect(url_for("configuracoes.modalidades_lista"))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar vínculos: {e}", "danger")
            db.close()
            return redirect(url_for("configuracoes.modalidades_vincular", modalidade_id=modalidade_id))

    db.close()
    return render_template(
        "configuracoes/modalidades_vincular.html",
        modalidade=modalidade,
        academias=academias,
        vinculadas=vinculadas,
    )


@bp_configuracoes.route("/modalidades/<int:modalidade_id>/toggle", methods=["POST"])
@login_required
@modalidades_access_required
def modalidades_toggle(modalidade_id):
    contexto = _contexto_modalidades()
    if not contexto:
        flash("Nenhuma academia vinculada ao seu usuário.", "warning")
        return redirect(url_for("painel.home"))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome, ativo, COALESCE(visibilidade, 'publica') AS visibilidade, id_academia FROM modalidade WHERE id = %s", (modalidade_id,))
    m = cur.fetchone()
    if not m:
        db.close()
        flash("Modalidade não encontrada.", "danger")
        return redirect(url_for("configuracoes.modalidades_lista"))
    if not contexto["is_admin"]:
        visivel = m["visibilidade"] == "publica" or (m["visibilidade"] == "privada" and m.get("id_academia") == contexto["academia_contexto_id"])
        if not visivel:
            db.close()
            flash("Você não pode alterar esta modalidade.", "danger")
            return redirect(url_for("configuracoes.modalidades_lista", academia_id=contexto["academia_contexto_id"]))
    novo = 0 if m["ativo"] else 1
    cur.execute("UPDATE modalidade SET ativo = %s WHERE id = %s", (novo, modalidade_id))
    db.commit()
    db.close()
    flash(f"Modalidade «{m['nome']}» {'ativada' if novo else 'inativada'}.", "success")
    return redirect(url_for("configuracoes.modalidades_lista", academia_id=contexto["academia_contexto_id"]))


@bp_configuracoes.route("/modalidades/<int:modalidade_id>/excluir", methods=["POST"])
@login_required
@modalidades_access_required
def modalidades_excluir(modalidade_id):
    contexto = _contexto_modalidades()
    if not contexto:
        flash("Nenhuma academia vinculada ao seu usuário.", "warning")
        return redirect(url_for("painel.home"))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, COALESCE(visibilidade, 'publica') AS visibilidade, id_academia FROM modalidade WHERE id = %s",
        (modalidade_id,),
    )
    modalidade = cur.fetchone()
    if not modalidade:
        db.close()
        flash("Modalidade não encontrada.", "danger")
        return redirect(url_for("configuracoes.modalidades_lista", academia_id=contexto["academia_contexto_id"]))

    if not contexto["is_admin"]:
        visivel = modalidade["visibilidade"] == "publica" or (
            modalidade["visibilidade"] == "privada" and modalidade.get("id_academia") == contexto["academia_contexto_id"]
        )
        if not visivel:
            db.close()
            flash("Você não pode excluir esta modalidade.", "danger")
            return redirect(url_for("configuracoes.modalidades_lista", academia_id=contexto["academia_contexto_id"]))

    try:
        # Limpar vínculos antes de excluir a modalidade.
        for tabela, coluna in (
            ("aluno_modalidades", "modalidade_id"),
            ("turma_modalidades", "modalidade_id"),
            ("professor_modalidade", "modalidade_id"),
            ("academia_modalidades", "modalidade_id"),
        ):
            try:
                cur.execute(f"DELETE FROM {tabela} WHERE {coluna} = %s", (modalidade_id,))
            except Exception:
                pass
        try:
            cur.execute("DELETE FROM graduacao WHERE modalidade_id = %s", (modalidade_id,))
        except Exception:
            pass
        cur.execute("DELETE FROM modalidade WHERE id = %s", (modalidade_id,))
        db.commit()
        flash(f"Modalidade «{modalidade['nome']}» excluída com sucesso.", "success")
        db.close()
        return redirect(url_for("configuracoes.modalidades_lista", academia_id=contexto["academia_contexto_id"]))
    except Exception as e:
        db.rollback()
        db.close()
        flash(f"Não foi possível excluir a modalidade: {e}", "danger")
        return redirect(
            url_for(
                "configuracoes.modalidades_graduacoes",
                modalidade_id=modalidade_id,
                academia_id=contexto["academia_contexto_id"],
            )
        )


@bp_configuracoes.route("/modalidades/<int:modalidade_id>/graduacoes", methods=["GET", "POST"])
@login_required
@modalidades_access_required
def modalidades_graduacoes(modalidade_id):
    contexto = _contexto_modalidades()
    if not contexto:
        flash("Nenhuma academia vinculada ao seu usuário.", "warning")
        return redirect(url_for("painel.home"))

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, COALESCE(visibilidade, 'publica') AS visibilidade, id_academia FROM modalidade WHERE id = %s",
        (modalidade_id,),
    )
    modalidade = cur.fetchone()
    if not modalidade:
        db.close()
        flash("Modalidade não encontrada.", "danger")
        return redirect(url_for("configuracoes.modalidades_lista", academia_id=contexto["academia_contexto_id"]))

    if not contexto["is_admin"]:
        visivel = modalidade["visibilidade"] == "publica" or (
            modalidade["visibilidade"] == "privada" and modalidade.get("id_academia") == contexto["academia_contexto_id"]
        )
        if not visivel:
            db.close()
            flash("Você não pode acessar graduações desta modalidade.", "danger")
            return redirect(url_for("configuracoes.modalidades_lista", academia_id=contexto["academia_contexto_id"]))

    if request.method == "POST":
        ids = request.form.getlist("id")
        faixas = request.form.getlist("faixa")
        graduacoes = request.form.getlist("graduacao")
        categorias = request.form.getlist("categoria")
        ordens = request.form.getlist("ordem")

        try:
            for idx, gid in enumerate(ids):
                if not str(gid).strip().isdigit():
                    continue
                ordem_raw = (ordens[idx] if idx < len(ordens) else "") or ""
                ordem_val = int(ordem_raw) if str(ordem_raw).strip().isdigit() else 0
                cur.execute(
                    """
                    UPDATE graduacao
                    SET faixa=%s, graduacao=%s, categoria=%s, ordem=%s
                    WHERE id=%s AND modalidade_id=%s
                    """,
                    (
                        (faixas[idx] or "").strip() or None,
                        (graduacoes[idx] or "").strip() or None,
                        (categorias[idx] or "").strip() or None,
                        ordem_val,
                        int(gid),
                        modalidade_id,
                    ),
                )

            novas_faixas = request.form.getlist("nova_faixa")
            novas_graduacoes = request.form.getlist("nova_graduacao")
            novas_categorias = request.form.getlist("nova_categoria")
            novas_ordens = request.form.getlist("nova_ordem")
            total_novas = max(len(novas_faixas), len(novas_graduacoes), len(novas_categorias))
            # Próxima ordem padrão para novas (caso o usuário deixe em branco)
            cur.execute(
                "SELECT COALESCE(MAX(COALESCE(NULLIF(ordem,0), id)), 0) + 1 AS prox FROM graduacao WHERE modalidade_id = %s",
                (modalidade_id,),
            )
            row = cur.fetchone()
            prox_ordem = (row.get("prox") if row else 1) or 1
            for i in range(total_novas):
                nova_faixa = (novas_faixas[i] if i < len(novas_faixas) else "") or ""
                nova_graduacao = (novas_graduacoes[i] if i < len(novas_graduacoes) else "") or ""
                nova_categoria = (novas_categorias[i] if i < len(novas_categorias) else "") or ""
                nova_ordem = (novas_ordens[i] if i < len(novas_ordens) else "") or ""
                nova_faixa = nova_faixa.strip()
                nova_graduacao = nova_graduacao.strip()
                nova_categoria = nova_categoria.strip()
                if not (nova_faixa or nova_graduacao):
                    continue
                ordem_val = int(nova_ordem) if str(nova_ordem).strip().isdigit() else int(prox_ordem)
                if not str(nova_ordem).strip().isdigit():
                    prox_ordem = (prox_ordem or 0) + 1
                cur.execute(
                    """
                    INSERT INTO graduacao (faixa, graduacao, categoria, modalidade_id, ordem)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (nova_faixa or None, nova_graduacao or None, nova_categoria or None, modalidade_id, ordem_val),
                )

            db.commit()
            flash("Graduações da modalidade atualizadas com sucesso.", "success")
        except Exception as e:
            db.rollback()
            flash(f"Erro ao salvar graduações: {e}", "danger")
        finally:
            db.close()
        return redirect(
            url_for(
                "configuracoes.modalidades_graduacoes",
                modalidade_id=modalidade_id,
                academia_id=contexto["academia_contexto_id"],
            )
        )

    try:
        cur.execute(
            """
            SELECT id, faixa, graduacao, categoria,
                   COALESCE(ativo, 1) AS ativo,
                   COALESCE(NULLIF(ordem,0), id) AS ordem
            FROM graduacao
            WHERE modalidade_id = %s
            ORDER BY COALESCE(NULLIF(ordem,0), id), id
            """,
            (modalidade_id,),
        )
        graduacoes = cur.fetchall()
    except Exception:
        graduacoes = []
    db.close()
    return render_template(
        "configuracoes/modalidades_graduacoes.html",
        modalidade=modalidade,
        graduacoes=graduacoes,
        is_admin=contexto["is_admin"],
        academias_contexto=contexto["academias_permitidas"],
        academia_contexto_id=contexto["academia_contexto_id"],
    )


@bp_configuracoes.route(
    "/modalidades/<int:modalidade_id>/graduacoes/<int:graduacao_id>/toggle",
    methods=["POST"],
)
@login_required
@modalidades_access_required
def modalidades_graduacao_toggle(modalidade_id, graduacao_id):
    """Alterna ativo/inativo de uma graduação. Inativas não aparecem nos cadastros."""
    from flask import jsonify
    contexto = _contexto_modalidades()
    if not contexto:
        return jsonify({"ok": False, "error": "Sem academia"}), 400

    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        # Modalidade tem que pertencer ao escopo
        cur.execute(
            "SELECT id, COALESCE(visibilidade,'publica') AS visibilidade, id_academia "
            "FROM modalidade WHERE id = %s",
            (modalidade_id,),
        )
        m = cur.fetchone()
        if not m:
            return jsonify({"ok": False, "error": "Modalidade não encontrada"}), 404
        if not contexto["is_admin"]:
            visivel = m["visibilidade"] == "publica" or (
                m["visibilidade"] == "privada"
                and m.get("id_academia") == contexto["academia_contexto_id"]
            )
            if not visivel:
                return jsonify({"ok": False, "error": "Sem permissão"}), 403

        cur.execute(
            "SELECT id, faixa, graduacao, COALESCE(ativo, 1) AS ativo "
            "FROM graduacao WHERE id = %s AND modalidade_id = %s",
            (graduacao_id, modalidade_id),
        )
        g = cur.fetchone()
        if not g:
            return jsonify({"ok": False, "error": "Graduação não encontrada"}), 404

        novo = 0 if g["ativo"] else 1
        cur.execute(
            "UPDATE graduacao SET ativo = %s WHERE id = %s",
            (novo, graduacao_id),
        )

        # Após o toggle, renumera a ordem das graduações ATIVAS desta modalidade
        # de forma sequencial (1,2,3...), preservando a ordem relativa atual.
        # Assim a sequência fica sempre limpa nos formulários, sem buracos.
        cur.execute(
            """
            SELECT id FROM graduacao
            WHERE modalidade_id = %s AND COALESCE(ativo, 1) = 1
            ORDER BY COALESCE(NULLIF(ordem, 0), id), id
            """,
            (modalidade_id,),
        )
        ativas = cur.fetchall()
        for nova_ordem, row in enumerate(ativas, start=1):
            cur.execute(
                "UPDATE graduacao SET ordem = %s WHERE id = %s",
                (nova_ordem, row["id"]),
            )

        # Inativadas vão para o final (com ordem alta) para não conflitar
        # quando reativadas (ficam ao final da lista ativa).
        cur.execute(
            """
            SELECT id FROM graduacao
            WHERE modalidade_id = %s AND COALESCE(ativo, 1) = 0
            ORDER BY COALESCE(NULLIF(ordem, 0), id), id
            """,
            (modalidade_id,),
        )
        inativas = cur.fetchall()
        base_inativa = len(ativas) + 1
        for offset, row in enumerate(inativas):
            cur.execute(
                "UPDATE graduacao SET ordem = %s WHERE id = %s",
                (base_inativa + offset, row["id"]),
            )

        db.commit()
        rotulo = f"{g.get('faixa') or ''} {g.get('graduacao') or ''}".strip() or f"#{graduacao_id}"
        return jsonify({
            "ok": True,
            "ativo": bool(novo),
            "msg": f"Graduação «{rotulo}» {'ativada' if novo else 'inativada'}. Ordens renumeradas.",
        })
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        cur.close()
        db.close()
