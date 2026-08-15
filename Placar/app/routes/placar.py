import json
import re

from flask import Blueprint, abort, render_template, request, jsonify
from flask_login import login_required
from app.models.base import db
from app.models.luta import Luta
from app.models.categoria import Categoria

bp = Blueprint("placar", __name__)

# Cache em memória — evita queries desnecessárias enquanto o worker vive.
# Se o processo reiniciar, o estado é reconstruído do banco (estado_json).
_estado: dict = {}

# Placar avulso (sem luta no banco): por token gerado em /mesa/avulso/<token>
_estado_avulso: dict = {}
_AVULSO_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def _valid_avulso_token(t):
    return bool(t and _AVULSO_TOKEN_RE.match(t))


def _meta_avulso():
    return {
        "luta_id": None,
        "fase": "avulso",
        "numero_luta": None,
        "categoria_id": None,
    }


def _estado_interno_luta(luta_id):
    """Retorna dict de estado ou None (sem envolver em jsonify)."""
    dados = _estado.get(luta_id)
    if dados:
        return dados

    luta = Luta.query.get(luta_id)
    if not luta:
        return None

    if luta.resultado:
        dados = _estado_do_resultado(luta)
        _estado[luta_id] = dados
        return dados

    if luta.estado_json:
        try:
            dados = json.loads(luta.estado_json)
            _estado[luta_id] = dados
            return dados
        except (ValueError, TypeError):
            pass

    return None


def _estado_com_meta(luta, dados):
    """Anexa meta para o placar atualizar fase/número ao trocar de luta (URL fixa por categoria)."""
    out = dict(dados) if dados else {}
    out["meta"] = {
        "luta_id": luta.id,
        "fase": luta.fase,
        "numero_luta": luta.numero_luta,
        "categoria_id": luta.categoria_id,
    }
    return out


@bp.get("/avulso/<token>")
def pagina_avulso(token):
    if not _valid_avulso_token(token):
        abort(404)
    return render_template(
        "placar.html",
        placar_avulso=True,
        avulso_token=token,
        luta=None,
        categoria=None,
        placar_por_categoria=False,
    )


@bp.get("/estado/avulso/<token>")
def obter_estado_avulso(token):
    if not _valid_avulso_token(token):
        return jsonify({}), 404
    meta = _meta_avulso()
    dados = _estado_avulso.get(token)
    if not dados:
        return jsonify(
            {
                "status": "idle",
                "meta": meta,
                "nomes": {"azul": "Azul", "branco": "Branco"},
                "timer": {
                    "restante": 240,
                    "golden": False,
                    "extra": 0,
                    "duracaoRegulamento": 240,
                },
                "azul": {"ippon": 0, "wazari": 0, "yuko": 0, "shido": 0},
                "branco": {"ippon": 0, "wazari": 0, "yuko": 0, "shido": 0},
            }
        )
    out = dict(dados)
    m = dict(meta)
    m.update(out.get("meta") or {})
    out["meta"] = m
    out.setdefault("nomes", {"azul": "Azul", "branco": "Branco"})
    return jsonify(out)


@bp.post("/estado/avulso/<token>")
@login_required
def atualizar_estado_avulso(token):
    if not _valid_avulso_token(token):
        return jsonify({"ok": False}), 404
    dados = request.get_json()
    if not dados:
        return jsonify({"ok": False}), 400
    _estado_avulso[token] = dados
    return jsonify({"ok": True})


@bp.get("/<int:luta_id>")
def pagina(luta_id):
    luta = Luta.query.get_or_404(luta_id)
    categoria = Categoria.query.get(luta.categoria_id)
    return render_template(
        "placar.html",
        luta=luta,
        categoria=categoria,
        placar_por_categoria=False,
        placar_avulso=False,
        avulso_token=None,
    )


@bp.get("/categoria/<int:categoria_id>")
def pagina_categoria(categoria_id):
    """Placar com URL fixa por categoria; acompanha a luta que a mesa marcou como ativa."""
    categoria = Categoria.query.get_or_404(categoria_id)
    luta = None
    if categoria.placar_luta_id:
        luta = Luta.query.get(categoria.placar_luta_id)
    return render_template(
        "placar.html",
        luta=luta,
        categoria=categoria,
        placar_por_categoria=True,
        placar_avulso=False,
        avulso_token=None,
    )


@bp.post("/estado/<int:luta_id>")
@login_required
def atualizar(luta_id):
    dados = request.get_json()
    if not dados:
        return jsonify({"ok": False}), 400

    # Atualiza cache de memória
    _estado[luta_id] = dados

    # Persiste no banco (sem travar a resposta — best effort)
    try:
        luta = Luta.query.get(luta_id)
        if luta:
            luta.estado_json = json.dumps(dados)
            db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify({"ok": True})


@bp.get("/estado/<int:luta_id>")
def obter(luta_id):
    dados = _estado_interno_luta(luta_id)
    return jsonify(dados if dados else {})


@bp.get("/estado/categoria/<int:categoria_id>")
def obter_por_categoria(categoria_id):
    cat = Categoria.query.get_or_404(categoria_id)
    lid = cat.placar_luta_id
    if not lid:
        return jsonify(
            {
                "aguardando_mesa": True,
                "meta": {
                    "categoria_id": cat.id,
                    "categoria_nome": cat.nome,
                    "luta_id": None,
                    "fase": None,
                    "numero_luta": None,
                },
            }
        )

    luta = Luta.query.get(lid)
    if not luta or luta.categoria_id != categoria_id:
        return jsonify(
            {
                "aguardando_mesa": True,
                "meta": {
                    "categoria_id": cat.id,
                    "categoria_nome": cat.nome,
                    "luta_id": None,
                    "fase": None,
                    "numero_luta": None,
                },
            }
        )

    dados = _estado_interno_luta(lid)
    if not dados:
        dados = {"status": "idle"}
    return jsonify(_estado_com_meta(luta, dados))


@bp.post("/categoria/<int:categoria_id>/placar-luta")
@login_required
def registrar_placar_luta(categoria_id):
    """Mesa chama ao abrir uma luta: passa a ser a exibida no placar /placar/categoria/<id>."""
    body = request.get_json(silent=True) or {}
    luta_id = body.get("luta_id")
    if not luta_id:
        return jsonify({"ok": False, "error": "luta_id obrigatório"}), 400

    luta = Luta.query.get_or_404(int(luta_id))
    if luta.categoria_id != categoria_id:
        return jsonify({"ok": False, "error": "Luta não pertence à categoria"}), 400

    cat = Categoria.query.get_or_404(categoria_id)
    cat.placar_luta_id = luta.id
    db.session.commit()
    return jsonify({"ok": True})


def _nomes_luta_placar(luta):
    """Nomes para o telão (overlay / polling após reload ou resultado salvo)."""
    az = (luta.atleta_azul.nome if luta.atleta_azul else None) or "—"
    br = (luta.atleta_branco.nome if luta.atleta_branco else None) or "—"
    return {"azul": az, "branco": br}


def _estado_do_resultado(luta):
    r = luta.resultado
    venc = "azul" if luta.vencedor_id == luta.atleta_azul_id else "branco"
    return {
        "status": "done",
        "vencedor": venc,
        "motivo": "resultado_salvo",
        "nomes": _nomes_luta_placar(luta),
        "azul":   {"ippon": r.ippon_azul,   "wazari": r.wazari_azul,   "yuko": r.yuko_azul,   "shido": r.shido_azul},
        "branco": {"ippon": r.ippon_branco,  "wazari": r.wazari_branco, "yuko": r.yuko_branco,  "shido": r.shido_branco},
        "timer":  {
            "restante": 0,
            "golden": False,
            "extra": r.tempo_luta or 0,
            "duracaoRegulamento": 240,
        },
        "osaekomi": None,
    }
