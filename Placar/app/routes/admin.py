from functools import wraps
from datetime import date as dt_date
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.models.competicao import Competicao
from app.models.academia import Academia
from app.models.atleta import Atleta
from app.models.inscricao import Inscricao
from app.models.categoria import Categoria
from app.models.luta import Luta
from app.services import (
    competicao_service,
    academia_service,
    atleta_service,
    inscricao_service,
    categoria_service,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")

FAIXAS = ["branca", "cinza", "azul", "amarela", "laranja", "verde", "roxa", "marrom", "preta"]


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.papel not in ("admin", "arbitro"):
            flash("Acesso restrito.", "error")
            return redirect(url_for("home.index"))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ─────────────────────────────────────────────────

@bp.get("/")
@admin_required
def dashboard():
    stats = {
        "competicoes": Competicao.query.count(),
        "academias":   Academia.query.count(),
        "atletas":     Atleta.query.count(),
        "inscricoes":  Inscricao.query.count(),
    }
    recentes = Competicao.query.order_by(Competicao.data.desc()).limit(6).all()
    return render_template("admin/dashboard.html", stats=stats, recentes=recentes)


# ── Competições ───────────────────────────────────────────────

@bp.get("/competicoes")
@admin_required
def competicoes():
    lista = Competicao.query.order_by(Competicao.data.desc()).all()
    return render_template("admin/competicoes.html", competicoes=lista)


@bp.post("/competicoes")
@admin_required
def competicoes_criar():
    try:
        dados = _form(request.form, datas=["data"], floats=[], ints=[])
        dados["festival_aproximacao"] = request.form.get("festival_aproximacao") == "1"
        competicao_service.criar(dados)
        flash("Competição criada.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    return redirect(url_for("admin.competicoes"))


@bp.post("/competicoes/<int:id>/deletar")
@admin_required
def competicoes_deletar(id):
    try:
        competicao_service.deletar(id)
        flash("Competição removida.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    return redirect(url_for("admin.competicoes"))


# ── Competição — detalhe admin ────────────────────────────────

@bp.get("/competicao/<int:comp_id>")
@admin_required
def competicao_detalhe(comp_id):
    comp = Competicao.query.get_or_404(comp_id)
    categorias = (
        Categoria.query
        .filter_by(competicao_id=comp_id)
        .order_by(Categoria.nome)
        .all()
    )
    inscritos_total    = Inscricao.query.filter_by(competicao_id=comp_id).count()
    inscritos_confirm  = Inscricao.query.filter_by(competicao_id=comp_id, status="CONFIRMADO").count()

    # lutas geradas por categoria
    lutas_por_cat = {
        cat.id: Luta.query.filter_by(categoria_id=cat.id).count()
        for cat in categorias
    }

    return render_template(
        "admin/competicao.html",
        comp=comp,
        categorias=categorias,
        inscritos_total=inscritos_total,
        inscritos_confirm=inscritos_confirm,
        lutas_por_cat=lutas_por_cat,
    )


@bp.post("/competicao/<int:comp_id>/editar")
@admin_required
def competicao_editar(comp_id):
    try:
        dados = _form(request.form, datas=["data"], floats=[], ints=[])
        dados["festival_aproximacao"] = request.form.get("festival_aproximacao") == "1"
        competicao_service.atualizar(comp_id, dados)
        flash("Competição atualizada.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    return redirect(url_for("admin.competicao_detalhe", comp_id=comp_id))


# ── Academias ─────────────────────────────────────────────────

@bp.get("/academias")
@admin_required
def academias():
    lista = Academia.query.order_by(Academia.nome).all()
    return render_template("admin/academias.html", academias=lista)


@bp.post("/academias")
@admin_required
def academias_criar():
    try:
        academia_service.criar(_form(request.form))
        flash("Academia cadastrada.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    return redirect(url_for("admin.academias"))


# ── Atletas ───────────────────────────────────────────────────

@bp.get("/atletas")
@admin_required
def atletas():
    academia_id = request.args.get("academia_id", type=int)
    busca_q = (request.args.get("q") or "").strip()
    lista = atleta_service.listar(
        academia_id=academia_id,
        busca_nome=busca_q or None,
    )
    academias = Academia.query.order_by(Academia.nome).all()
    qv_atletas = {}
    if academia_id:
        qv_atletas["academia_id"] = academia_id
    if busca_q:
        qv_atletas["q"] = busca_q
    atletas_query_string = urlencode(qv_atletas) if qv_atletas else ""
    return render_template(
        "admin/atletas.html",
        atletas=lista,
        academias=academias,
        faixas=FAIXAS,
        filtro=academia_id,
        busca_q=busca_q,
        atletas_query_string=atletas_query_string,
    )


@bp.post("/atletas")
@admin_required
def atletas_criar():
    try:
        dados = _form(request.form, datas=["data_nascimento"], floats=["peso"], ints=["academia_id"], urls=["foto_url"])
        atleta_service.criar(dados)
        flash("Atleta cadastrado.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    return redirect(url_for("admin.atletas"))


@bp.route("/atleta/<int:atleta_id>/editar", methods=["GET", "POST"])
@admin_required
def atleta_editar(atleta_id):
    atleta = Atleta.query.get_or_404(atleta_id)
    academias = Academia.query.order_by(Academia.nome).all()
    retorno_filtro = request.args.get("academia_id", type=int)
    retorno_busca = (request.args.get("q") or "").strip()
    origem = request.args.get("origem")
    comp_voltar = request.args.get("comp_id", type=int)

    if request.method == "POST":
        retorno_filtro = request.form.get("retorno_academia_id", type=int)
        retorno_busca = (request.form.get("retorno_q") or "").strip()
        origem = request.form.get("origem")
        comp_voltar = request.form.get("comp_voltar", type=int)
        try:
            dados = _payload_atleta_form(request.form)
            atleta_service.atualizar(atleta_id, dados)
            flash("Atleta atualizado.", "success")
            if origem == "inscricoes" and comp_voltar:
                return redirect(url_for("admin.inscricoes", comp_id=comp_voltar))
            qv = {}
            if retorno_filtro:
                qv["academia_id"] = retorno_filtro
            if retorno_busca:
                qv["q"] = retorno_busca
            return redirect(
                url_for("admin.atletas") + (("?" + urlencode(qv)) if qv else "")
            )
        except Exception as e:
            flash(f"Erro: {e}", "error")

    qv_voltar = {}
    if retorno_filtro:
        qv_voltar["academia_id"] = retorno_filtro
    if retorno_busca:
        qv_voltar["q"] = retorno_busca
    voltar_atletas_href = url_for("admin.atletas") + (
        ("?" + urlencode(qv_voltar)) if qv_voltar else ""
    )

    return render_template(
        "admin/atleta_editar.html",
        atleta=atleta,
        academias=academias,
        faixas=FAIXAS,
        retorno_filtro=retorno_filtro,
        retorno_busca=retorno_busca,
        voltar_atletas_href=voltar_atletas_href,
        origem=origem,
        comp_voltar=comp_voltar,
    )


# ── Inscrições ────────────────────────────────────────────────

@bp.get("/competicao/<int:comp_id>/inscricoes")
@admin_required
def inscricoes(comp_id):
    comp   = Competicao.query.get_or_404(comp_id)
    lista  = (
        Inscricao.query
        .filter_by(competicao_id=comp_id)
        .join(Inscricao.atleta)
        .order_by(Atleta.nome)
        .all()
    )
    atletas = Atleta.query.order_by(Atleta.nome).all()
    return render_template("admin/inscricoes.html", comp=comp, inscricoes=lista, atletas=atletas)


@bp.post("/competicao/<int:comp_id>/inscricoes")
@admin_required
def inscricoes_criar(comp_id):
    try:
        inscricao_service.criar({
            "atleta_id":    int(request.form["atleta_id"]),
            "competicao_id": comp_id,
        })
        flash("Atleta inscrito.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.inscricoes", comp_id=comp_id))


@bp.post("/inscricao/<int:insc_id>/confirmar")
@admin_required
def inscricao_confirmar(insc_id):
    insc = inscricao_service.confirmar(insc_id)
    flash("Inscrição confirmada.", "success")
    return redirect(url_for("admin.inscricoes", comp_id=insc.competicao_id))


@bp.post("/inscricao/<int:insc_id>/remover")
@admin_required
def inscricao_remover(insc_id):
    insc = Inscricao.query.get_or_404(insc_id)
    comp_id = insc.competicao_id
    inscricao_service.deletar(insc_id)
    flash("Inscrição removida.", "success")
    return redirect(url_for("admin.inscricoes", comp_id=comp_id))


@bp.post("/competicao/<int:comp_id>/categorias/aproximacao")
@admin_required
def competicao_categoria_aproximacao(comp_id):
    Competicao.query.get_or_404(comp_id)
    try:
        nome = (request.form.get("nome") or "").strip()
        sexo = request.form.get("sexo")
        if not nome or sexo not in ("M", "F"):
            raise ValueError("Informe o nome e o sexo (M ou F).")
        categoria_service.criar(
            {
                "competicao_id": comp_id,
                "nome": nome,
                "sexo": sexo,
                "idade_min": _parse_opt_int(request.form.get("idade_min")),
                "idade_max": _parse_opt_int(request.form.get("idade_max")),
                "peso_min": _parse_opt_float(request.form.get("peso_min")),
                "peso_max": _parse_opt_float(request.form.get("peso_max")),
                "ativo": True,
            }
        )
        flash("Categoria criada.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    return redirect(url_for("admin.competicao_detalhe", comp_id=comp_id))


@bp.route("/categoria/<int:cat_id>/editar", methods=["GET", "POST"])
@admin_required
def categoria_editar(cat_id):
    cat = Categoria.query.get_or_404(cat_id)
    comp = Competicao.query.get_or_404(cat.competicao_id)

    if request.method == "POST":
        try:
            nome = (request.form.get("nome") or "").strip()
            sexo = request.form.get("sexo")
            if not nome or sexo not in ("M", "F"):
                raise ValueError("Informe o nome e o sexo (M ou F).")
            categoria_service.atualizar(
                cat_id,
                {
                    "nome": nome,
                    "sexo": sexo,
                    "idade_min": _parse_opt_int(request.form.get("idade_min")),
                    "idade_max": _parse_opt_int(request.form.get("idade_max")),
                    "peso_min": _parse_opt_float(request.form.get("peso_min")),
                    "peso_max": _parse_opt_float(request.form.get("peso_max")),
                    "ativo": request.form.get("ativo") == "1",
                },
            )
            flash("Categoria atualizada.", "success")
            return redirect(url_for("admin.competicao_detalhe", comp_id=comp.id))
        except Exception as e:
            flash(f"Erro: {e}", "error")

    return render_template("admin/categoria_editar.html", cat=cat, comp=comp)


@bp.post("/categoria/<int:cat_id>/excluir")
@admin_required
def categoria_excluir(cat_id):
    cat = Categoria.query.get_or_404(cat_id)
    comp_id = cat.competicao_id
    try:
        if Luta.query.filter_by(categoria_id=cat_id).count():
            raise ValueError(
                "Esta categoria já tem lutas. Use «Resetar» na lista para limpar a chave antes de excluir."
            )
        Inscricao.query.filter_by(categoria_id=cat_id).update(
            {"categoria_id": None},
            synchronize_session=False,
        )
        categoria_service.deletar(cat_id)
        flash("Categoria removida.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    return redirect(url_for("admin.competicao_detalhe", comp_id=comp_id))


# ── Util ──────────────────────────────────────────────────────

def _form(form, datas=(), floats=(), ints=(), urls=()):
    dados = {}
    for k, v in form.items():
        if not v:
            continue
        if k in datas:
            dados[k] = dt_date.fromisoformat(v)
        elif k in floats:
            dados[k] = float(v)
        elif k in ints:
            dados[k] = int(v)
        else:
            dados[k] = v
    return dados


def _parse_opt_int(raw):
    if raw is None or str(raw).strip() == "":
        return None
    return int(raw)


def _parse_opt_float(raw):
    if raw is None or str(raw).strip() == "":
        return None
    return float(str(raw).replace(",", "."))


def _payload_atleta_form(form):
    """Campos do formulário de atleta (criar/editar), com opcionais podendo ser limpos."""
    nome = (form.get("nome") or "").strip()
    if not nome:
        raise ValueError("Nome é obrigatório.")
    raw_sexo = form.get("sexo")
    sexo = raw_sexo if raw_sexo in ("M", "F") else None
    dn = form.get("data_nascimento")
    data_nascimento = dt_date.fromisoformat(dn) if dn else None
    peso = _parse_opt_float(form.get("peso"))
    faixa = (form.get("faixa") or "").strip() or None
    aid = form.get("academia_id")
    academia_id = int(aid) if aid and str(aid).strip() else None
    foto_url = (form.get("foto_url") or "").strip() or None
    return {
        "nome": nome,
        "sexo": sexo,
        "data_nascimento": data_nascimento,
        "peso": peso,
        "faixa": faixa,
        "academia_id": academia_id,
        "foto_url": foto_url,
    }
