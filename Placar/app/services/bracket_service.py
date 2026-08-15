from collections import defaultdict
from app.models.categoria import Categoria
from app.models.competicao import Competicao
from app.models.luta import Luta
FASE_ORDEM_PRINCIPAL = ["oitavas", "quartas", "semifinal", "final"]
FASE_ORDEM_INFERIOR = [
    "repescagem_1",
    "repescagem_2",
    "disputa_3lugar_a",
    "disputa_3lugar_b",
    "disputa_3lugar",
]
FASE_LABELS = {
    "oitavas":        "Oitavas",
    "quartas":        "Quartas de Final",
    "semifinal":      "Semifinal",
    "disputa_3lugar": "Disputa de 3º lugar",
    "disputa_3lugar_a": "Disputa de 3º lugar",
    "disputa_3lugar_b": "Disputa de 3º lugar (2)",
    "final":          "Final",
    "final_bo3":      "Final (melhor de 3)",
    "repescagem_1":   "Repescagem — 1ª fase",
    "repescagem_2":   "Repescagem — 2ª fase",
}


def get_bracket(categoria_id):
    categoria  = Categoria.query.get_or_404(categoria_id)
    competicao = Competicao.query.get(categoria.competicao_id)
    lutas = (
        Luta.query
        .filter_by(categoria_id=categoria_id)
        .order_by(Luta.numero_luta)
        .all()
    )

    por_fase = {}
    for luta in lutas:
        por_fase.setdefault(luta.fase, []).append(_serializar_luta(luta))

    base = {
        "categoria": {
            "id": categoria.id,
            "nome": categoria.nome,
            "competicao": competicao.nome if competicao else None,
        },
        "disputa_3lugar": por_fase.get("disputa_3lugar"),
        "terceiros": [],
    }

    # ── Rodízio ───────────────────────────────────────────────
    if "rodizio" in por_fase:
        base["tipo"]              = "rodizio"
        base["rounds"]          = [{"fase": "rodizio", "label": "Rodízio", "lutas": por_fase["rodizio"]}]
        base["rounds_inferiores"] = []
        classif = _classificacao_rodizio(lutas)
        base["classificacao"] = classif
        rod_lutas = [l for l in lutas if l.fase == "rodizio"]
        completo = _rodizio_todas_lutas_encerradas(rod_lutas)
        base["rodizio_completo"] = completo
        base["colocacoes"] = _colocacoes_rodizio(classif) if completo else []
        return base

    # ── Final melhor de 3 ─────────────────────────────────────
    if "final_bo3" in por_fase:
        base["tipo"]              = "melhor3"
        base["rounds_inferiores"] = []
        base["rounds"] = [
            {
                "fase": "final_bo3",
                "label": FASE_LABELS["final_bo3"],
                "lutas": por_fase["final_bo3"],
            }
        ]
        base["colocacoes"] = _colocacoes_melhor_de_3(lutas)
        return base

    # ── Eliminação: chave principal (até a final) + trilha inferior (rep + pódio) ──
    rounds = [
        {"fase": fase, "label": FASE_LABELS.get(fase, fase), "lutas": por_fase[fase]}
        for fase in FASE_ORDEM_PRINCIPAL
        if fase in por_fase
    ]
    rounds_inferiores = [
        {"fase": fase, "label": FASE_LABELS.get(fase, fase), "lutas": por_fase[fase]}
        for fase in FASE_ORDEM_INFERIOR
        if fase in por_fase
    ]
    base["tipo"]             = "eliminacao"
    base["rounds"]           = rounds
    base["rounds_inferiores"] = rounds_inferiores
    base["colocacoes"]       = _colocacoes_eliminatoria(lutas)
    return base


def _perdedor_luta(luta):
    if not luta or not luta.vencedor_id:
        return None
    if luta.vencedor_id == luta.atleta_azul_id:
        return luta.atleta_branco
    if luta.vencedor_id == luta.atleta_branco_id:
        return luta.atleta_azul
    return None


def _colocacoes_eliminatoria(lutas):
    """1º / 2º da final; 3º de cada disputa de bronze (CBJ)."""
    por_fase = {}
    for l in lutas:
        por_fase.setdefault(l.fase, []).append(l)
    for f in por_fase:
        por_fase[f].sort(key=lambda x: x.numero_luta)

    out = []
    finals = por_fase.get("final") or []
    if finals:
        fl = finals[0]
        if fl.resultado and fl.vencedor_id and fl.vencedor:
            out.append({"lugar": 1, "label": "1º lugar", "atleta": _serializar_atleta(fl.vencedor)})
            p = _perdedor_luta(fl)
            if p:
                out.append({"lugar": 2, "label": "2º lugar", "atleta": _serializar_atleta(p)})

    for lu in por_fase.get("repescagem_2") or []:
        if lu.resultado and lu.vencedor_id and lu.vencedor:
            out.append({"lugar": 3, "label": "3º lugar", "atleta": _serializar_atleta(lu.vencedor)})

    for lu in por_fase.get("disputa_3lugar_a") or []:
        if lu.resultado and lu.vencedor_id and lu.vencedor:
            out.append({"lugar": 3, "label": "3º lugar", "atleta": _serializar_atleta(lu.vencedor)})

    for lu in por_fase.get("disputa_3lugar_b") or []:
        if lu.resultado and lu.vencedor_id and lu.vencedor:
            out.append({"lugar": 3, "label": "3º lugar", "atleta": _serializar_atleta(lu.vencedor)})

    for lu in por_fase.get("disputa_3lugar") or []:
        if lu.resultado and lu.vencedor_id and lu.vencedor:
            out.append({"lugar": 3, "label": "3º lugar", "atleta": _serializar_atleta(lu.vencedor)})
            p = _perdedor_luta(lu)
            if p:
                out.append({"lugar": 4, "label": "4º lugar", "atleta": _serializar_atleta(p)})

    return out


def _colocacoes_melhor_de_3(lutas):
    bo3 = sorted([l for l in lutas if l.fase == "final_bo3"], key=lambda x: x.numero_luta)
    if not bo3:
        return []
    base = next((l for l in bo3 if l.atleta_azul_id and l.atleta_branco_id), None)
    if not base:
        return []
    wins = defaultdict(int)
    for l in bo3:
        if l.resultado and l.vencedor_id:
            wins[l.vencedor_id] += 1
    a, b = base.atleta_azul_id, base.atleta_branco_id
    if wins[a] >= 2 and base.atleta_azul and base.atleta_branco:
        return [
            {"lugar": 1, "label": "1º lugar", "atleta": _serializar_atleta(base.atleta_azul)},
            {"lugar": 2, "label": "2º lugar", "atleta": _serializar_atleta(base.atleta_branco)},
        ]
    if wins[b] >= 2 and base.atleta_azul and base.atleta_branco:
        return [
            {"lugar": 1, "label": "1º lugar", "atleta": _serializar_atleta(base.atleta_branco)},
            {"lugar": 2, "label": "2º lugar", "atleta": _serializar_atleta(base.atleta_azul)},
        ]
    return []


def _colocacoes_rodizio(classificacao):
    medals = {1: "1º lugar", 2: "2º lugar", 3: "3º lugar"}
    out = []
    for row in classificacao:
        pos = row.get("posicao")
        atl = row.get("atleta")
        if not atl:
            continue
        label = medals.get(pos, f"{pos}º lugar")
        out.append({"lugar": pos, "label": label, "atleta": atl})
    return out


def _rodizio_todas_lutas_encerradas(rod_lutas):
    """True se todas as lutas do rodízio têm dois atletas e resultado."""
    if not rod_lutas:
        return False
    for l in rod_lutas:
        if not l.atleta_azul_id or not l.atleta_branco_id:
            return False
        if l.resultado is None:
            return False
    return True


# ── Classificação rodízio ─────────────────────────────────────

def _classificacao_rodizio(lutas):
    stats = defaultdict(lambda: {"vitorias": 0, "derrotas": 0, "pontos": 0, "atleta": None})

    for luta in lutas:
        for lado in ("azul", "branco"):
            atleta = luta.atleta_azul if lado == "azul" else luta.atleta_branco
            if not atleta:
                continue
            if stats[atleta.id]["atleta"] is None:
                stats[atleta.id]["atleta"] = _serializar_atleta(atleta)

        if not luta.resultado or not luta.vencedor_id:
            continue

        r = luta.resultado
        # Desempate rodízio: mesma ordem Ippon > Wazari > Yuko (valor composto).
        pts_azul = (r.ippon_azul or 0) * 1_000_000 + (r.wazari_azul or 0) * 1_000 + (r.yuko_azul or 0)
        pts_branco = (r.ippon_branco or 0) * 1_000_000 + (r.wazari_branco or 0) * 1_000 + (r.yuko_branco or 0)

        if luta.atleta_azul:
            stats[luta.atleta_azul_id]["pontos"] += pts_azul
            if luta.vencedor_id == luta.atleta_azul_id:
                stats[luta.atleta_azul_id]["vitorias"] += 1
            else:
                stats[luta.atleta_azul_id]["derrotas"] += 1

        if luta.atleta_branco:
            stats[luta.atleta_branco_id]["pontos"] += pts_branco
            if luta.vencedor_id == luta.atleta_branco_id:
                stats[luta.atleta_branco_id]["vitorias"] += 1
            else:
                stats[luta.atleta_branco_id]["derrotas"] += 1

    classificados = sorted(
        stats.values(),
        key=lambda s: (-s["vitorias"], -s["pontos"]),
    )

    return [
        {**s, "posicao": i + 1}
        for i, s in enumerate(classificados)
        if s["atleta"] is not None
    ]


# ── Serializers ───────────────────────────────────────────────

def _serializar_luta(luta):
    return {
        "id":         luta.id,
        "numero":     luta.numero_luta,
        "fase":       luta.fase,
        "azul":       _serializar_atleta(luta.atleta_azul),
        "branco":     _serializar_atleta(luta.atleta_branco),
        "vencedor_id": luta.vencedor_id,
        "resultado":  _serializar_resultado(luta.resultado),
    }


def _serializar_atleta(atleta):
    if not atleta:
        return None
    return {
        "id":       atleta.id,
        "nome":     atleta.nome,
        "academia": atleta.academia.nome if atleta.academia else None,
        "iniciais": _iniciais(atleta.nome),
        "foto_url": atleta.foto_url or None,
    }


def _iniciais(nome):
    partes = nome.strip().split()
    if len(partes) >= 2:
        return (partes[0][0] + partes[-1][0]).upper()
    return nome[:2].upper()


def _serializar_resultado(r):
    if not r:
        return None
    return {
        "ippon_azul":    r.ippon_azul,
        "wazari_azul":   r.wazari_azul,
        "yuko_azul":     r.yuko_azul,
        "shido_azul":    r.shido_azul,
        "ippon_branco":  r.ippon_branco,
        "wazari_branco": r.wazari_branco,
        "yuko_branco":   r.yuko_branco,
        "shido_branco":  r.shido_branco,
        "tempo_luta":    r.tempo_luta,
    }
