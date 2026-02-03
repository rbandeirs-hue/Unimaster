# -*- coding: utf-8 -*-
"""
Blueprint Formulários — Cadastro de formulários baseados nos campos do aluno.
Visível apenas em modo federação e associação.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from config import get_db_connection
from utils.formularios_campos import CAMPOS_ALUNO_PADRAO, listar_campos_por_grupo, get_label

bp_formularios = Blueprint("formularios", __name__, url_prefix="/formularios")


def _contexto_formularios():
    """Retorna (modo, id_entidade, back_url) conforme modo painel e roles."""
    modo = session.get("modo_painel") or ""
    back_url = request.args.get("next")
    if modo == "federacao":
        fid = (
            getattr(current_user, "id_federacao", None)
            or request.args.get("federacao_id", type=int)
            or session.get("federacao_gerenciamento_id")
        )
        back_url = back_url or url_for("federacao.gerenciamento_federacao")
        return ("federacao", fid, back_url)
    if modo == "associacao":
        aid = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        back_url = back_url or url_for("associacao.gerenciamento_associacao")
        return ("associacao", aid, back_url)
    return (None, None, back_url or url_for("painel.home"))


def _pode_acessar():
    """Verifica se o usuário pode acessar o módulo formulários."""
    modo, id_ent, _ = _contexto_formularios()
    if modo == "federacao":
        return current_user.has_role("gestor_federacao") or current_user.has_role("admin")
    if modo == "associacao":
        return current_user.has_role("gestor_associacao") or current_user.has_role("admin")
    return False


@bp_formularios.route("/")
@login_required
def lista():
    if not _pode_acessar():
        flash("Acesso negado. Disponível apenas em modo federação ou associação.", "danger")
        return redirect(url_for("painel.home"))
    modo, id_ent, back_url = _contexto_formularios()
    if not id_ent and modo == "federacao" and current_user.has_role("admin"):
        flash("Selecione a federação.", "warning")
        return redirect(url_for("federacao.gerenciamento_federacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if modo == "federacao":
            cur.execute(
                "SELECT id, nome, ativo, created_at FROM formularios WHERE id_federacao = %s ORDER BY nome",
                (id_ent,),
            )
        else:
            cur.execute(
                "SELECT id, nome, ativo, created_at FROM formularios WHERE id_associacao = %s ORDER BY nome",
                (id_ent,),
            )
        formularios = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return render_template(
        "formularios/lista.html",
        formularios=formularios,
        modo=modo,
        back_url=back_url,
    )


@bp_formularios.route("/cadastro", methods=["GET", "POST"])
@login_required
def cadastro():
    if not _pode_acessar():
        flash("Acesso negado. Disponível apenas em modo federação ou associação.", "danger")
        return redirect(url_for("painel.home"))
    modo, id_ent, back_url = _contexto_formularios()
    if not id_ent and modo == "federacao" and current_user.has_role("admin"):
        flash("Selecione a federação.", "warning")
        return redirect(url_for("federacao.gerenciamento_federacao"))

    grupos = listar_campos_por_grupo()
    campos_lista = [(chave, label) for chave, (label, _) in CAMPOS_ALUNO_PADRAO.items()]

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        campo_chaves = request.form.getlist("campo_chave")
        if not nome:
            flash("Informe o nome do formulário.", "danger")
            return render_template(
                "formularios/cadastro.html",
                modo=modo,
                back_url=back_url,
                grupos=grupos,
                campos_lista=campos_lista,
            )

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            if modo == "federacao":
                cur.execute(
                    "INSERT INTO formularios (nome, id_federacao) VALUES (%s, %s)",
                    (nome, id_ent),
                )
            else:
                cur.execute(
                    "INSERT INTO formularios (nome, id_associacao) VALUES (%s, %s)",
                    (nome, id_ent),
                )
            formulario_id = cur.lastrowid
            for ordem, chave in enumerate(campo_chaves):
                if chave and chave in CAMPOS_ALUNO_PADRAO:
                    label = get_label(chave)
                    cur.execute(
                        "INSERT INTO formularios_campos (formulario_id, campo_chave, label, ordem) VALUES (%s, %s, %s, %s)",
                        (formulario_id, chave, label, ordem),
                    )
            conn.commit()
            flash("Formulário cadastrado com sucesso!", "success")
            return redirect(url_for("formularios.lista"))
        except Exception as e:
            conn.rollback()
            flash(f"Erro ao cadastrar: {e}", "danger")
        finally:
            cur.close()
            conn.close()

    return render_template(
        "formularios/cadastro.html",
        modo=modo,
        back_url=back_url,
        grupos=grupos,
        campos_lista=campos_lista,
    )


@bp_formularios.route("/editar/<int:formulario_id>", methods=["GET", "POST"])
@login_required
def editar(formulario_id):
    if not _pode_acessar():
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    modo, id_ent, back_url = _contexto_formularios()
    if not id_ent and modo == "federacao" and current_user.has_role("admin"):
        return redirect(url_for("federacao.gerenciamento_federacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if modo == "federacao":
            cur.execute(
                "SELECT id, nome, ativo FROM formularios WHERE id = %s AND id_federacao = %s",
                (formulario_id, id_ent),
            )
        else:
            cur.execute(
                "SELECT id, nome, ativo FROM formularios WHERE id = %s AND id_associacao = %s",
                (formulario_id, id_ent),
            )
        formulario = cur.fetchone()
        if not formulario:
            flash("Formulário não encontrado.", "danger")
            return redirect(url_for("formularios.lista"))

        cur.execute(
            "SELECT campo_chave, label, ordem FROM formularios_campos WHERE formulario_id = %s ORDER BY ordem",
            (formulario_id,),
        )
        campos_atuais = {r["campo_chave"]: r for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()

    grupos = listar_campos_por_grupo()
    campos_lista = [(chave, label) for chave, (label, _) in CAMPOS_ALUNO_PADRAO.items()]

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        campo_chaves = request.form.getlist("campo_chave")
        ativo = 1 if request.form.get("ativo") == "1" else 0
        if not nome:
            flash("Informe o nome do formulário.", "danger")
            return render_template(
                "formularios/editar.html",
                formulario=formulario,
                modo=modo,
                back_url=back_url,
                grupos=grupos,
                campos_lista=campos_lista,
                campos_atuais=campos_atuais,
            )

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "UPDATE formularios SET nome = %s, ativo = %s WHERE id = %s",
                (nome, ativo, formulario_id),
            )
            cur.execute("DELETE FROM formularios_campos WHERE formulario_id = %s", (formulario_id,))
            for ordem, chave in enumerate(campo_chaves):
                if chave and chave in CAMPOS_ALUNO_PADRAO:
                    label = get_label(chave)
                    cur.execute(
                        "INSERT INTO formularios_campos (formulario_id, campo_chave, label, ordem) VALUES (%s, %s, %s, %s)",
                        (formulario_id, chave, label, ordem),
                    )
            conn.commit()
            flash("Formulário atualizado!", "success")
            return redirect(url_for("formularios.lista"))
        except Exception as e:
            conn.rollback()
            flash(f"Erro ao atualizar: {e}", "danger")
        finally:
            cur.close()
            conn.close()

    return render_template(
        "formularios/editar.html",
        formulario=formulario,
        modo=modo,
        back_url=back_url,
        grupos=grupos,
        campos_lista=campos_lista,
        campos_atuais=campos_atuais,
    )


@bp_formularios.route("/excluir/<int:formulario_id>", methods=["POST"])
@login_required
def excluir(formulario_id):
    if not _pode_acessar():
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    modo, id_ent, _ = _contexto_formularios()
    if not id_ent and modo == "federacao" and current_user.has_role("admin"):
        return redirect(url_for("federacao.gerenciamento_federacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if modo == "federacao":
            cur.execute(
                "DELETE FROM formularios WHERE id = %s AND id_federacao = %s",
                (formulario_id, id_ent),
            )
        else:
            cur.execute(
                "DELETE FROM formularios WHERE id = %s AND id_associacao = %s",
                (formulario_id, id_ent),
            )
        conn.commit()
        if cur.rowcount:
            flash("Formulário excluído.", "success")
        else:
            flash("Formulário não encontrado.", "warning")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao excluir: {e}", "danger")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("formularios.lista"))
