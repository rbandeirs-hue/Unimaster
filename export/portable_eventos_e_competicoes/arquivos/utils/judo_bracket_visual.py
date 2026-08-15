# -*- coding: utf-8 -*-
"""
Monta payload JSON para visualização de chave eliminatória (colunas + conectores).
Exclui rodízio, melhor de 3 e trilhas de repescagem/3º da coluna principal.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _sigla(academia: Optional[str]) -> str:
    s = (academia or "-").strip() or "-"
    return s[:3].upper() if len(s) >= 3 else (s.upper() + "___")[:3]


def _is_placeholder(nome: Optional[str]) -> bool:
    if not nome:
        return True
    n = nome.strip().upper()
    if n == "BYE":
        return True
    if n.startswith("VENCEDOR LUTA") or n.startswith("PERDEDOR LUTA"):
        return True
    return False


def _marcador_tipo_vitoria(tipo: Optional[str]) -> str:
    t = (tipo or "").lower()
    if t == "ippon":
        return "I"
    if t == "wazaari":
        return "W"
    if t == "golden_score":
        return "GS"
    if t == "hansoku_make":
        return "H"
    if t == "desistencia":
        return "D"
    return "W"


def _atleta_side(luta: Dict[str, Any], lado: str) -> Dict[str, Any]:
    if lado == "branco":
        nome, ac = luta.get("atleta_branco_nome"), luta.get("atleta_branco_academia")
    else:
        nome, ac = luta.get("atleta_azul_nome"), luta.get("atleta_azul_academia")
    ph = _is_placeholder(nome)
    return {
        "nome": (nome or "—").strip() or "—",
        "sigla": "—" if ph else _sigla(ac),
        "placeholder": ph,
        "academia": (ac or "").strip(),
    }


def filtrar_lutas_chave_principal(lutas: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """
    Retorna lutas da chave principal eliminatória, ou None se a categoria não for
    visualização em árvore (rodízio / BO3).
    """
    if not lutas:
        return []
    sistemas = {(l.get("chave_sistema") or "") for l in lutas}
    if "round_robin" in sistemas or "bo3" in sistemas:
        return None
    out: List[Dict[str, Any]] = []
    for l in lutas:
        cf = (l.get("chave_fase") or "").lower()
        if "repescagem" in cf or "terceiro_lugar" in cf:
            continue
        cs = l.get("chave_sistema") or ""
        if cs == "elim_rep" and cf and not cf.startswith("principal"):
            continue
        out.append(l)
    return out


def _iniciais_nome(nome: Optional[str]) -> str:
    p = (nome or "").strip().split()
    if not p:
        return "?"
    if len(p) == 1:
        return (p[0][:2]).upper()
    return (p[0][0] + p[-1][0]).upper()


def _atleta_card_bracket(luta: Dict[str, Any], lado: str) -> Optional[Dict[str, Any]]:
    side = _atleta_side(luta, lado)
    if side.get("placeholder") or not side.get("nome") or side["nome"] == "BYE":
        return None
    lid = luta.get("id")
    return {
        "id": f"{lid}-{lado}",
        "nome": side["nome"],
        "academia": side.get("academia") or "",
        "iniciais": _iniciais_nome(side["nome"]),
        "foto_url": None,
    }


def _vencedor_id_card(luta: Dict[str, Any]) -> Optional[str]:
    v = luta.get("vencedor")
    if v == "azul":
        return f"{luta.get('id')}-azul"
    if v == "branco":
        return f"{luta.get('id')}-branco"
    return None


def _luta_para_card_javascript(luta: Dict[str, Any], fase: str) -> Dict[str, Any]:
    fin = (luta.get("status") or "") == "finalizada"
    return {
        "id": luta.get("id"),
        "fase": fase,
        "azul": _atleta_card_bracket(luta, "azul"),
        "branco": _atleta_card_bracket(luta, "branco"),
        "vencedor_id": _vencedor_id_card(luta),
        "resultado": None,
        "_encerrada": fin,
    }


def montar_payload_rodizio_round_robin(lutas_rr: List[Dict[str, Any]]) -> Dict[str, Any]:
    ord_lutas = sorted(lutas_rr, key=lambda x: (x.get("posicao_rodada") or 0, x.get("id") or 0))
    cards = [_luta_para_card_javascript(l, "rr") for l in ord_lutas]
    return {
        "tipo": "rodizio",
        "mensagem": "",
        "rounds": [{"fase": "rodizio_rr", "label": "Confrontos", "lutas": cards}],
        "rodizio_titulo": "Rodízio (todos contra todos)",
        "rounds_inferiores": [],
        "colocacoes": [],
        "classificacao": [],
        "rodizio_completo": False,
        "categoria": {"nome": "", "competicao": ""},
    }


def montar_payload_bo3_lista(lutas_bo3: List[Dict[str, Any]]) -> Dict[str, Any]:
    ord_lutas = sorted(
        lutas_bo3,
        key=lambda x: (x.get("round") or 0, x.get("posicao_rodada") or 0, x.get("id") or 0),
    )
    cards = [_luta_para_card_javascript(l, "bo3") for l in ord_lutas]
    return {
        "tipo": "rodizio",
        "mensagem": "",
        "rounds": [{"fase": "bo3_jogos", "label": "Jogos", "lutas": cards}],
        "rodizio_titulo": "Melhor de 3",
        "rounds_inferiores": [],
        "colocacoes": [],
        "classificacao": [],
        "rodizio_completo": False,
        "categoria": {"nome": "", "competicao": ""},
    }


def _labels_rodadas(n_primeira_rodada: int, n_colunas: int) -> List[str]:
    if n_colunas <= 1:
        return ["Final"]
    ptr = max(1, n_primeira_rodada)
    labels: List[str] = []
    for _ in range(n_colunas):
        if ptr >= 8:
            labels.append("Oitavas de final")
        elif ptr >= 4:
            labels.append("Quartas de final")
        elif ptr >= 2:
            labels.append("Semifinal")
        else:
            labels.append("Final")
        ptr = max(1, ptr // 2)
    return labels


def montar_payload_chave_visual(lutas: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not lutas:
        return {"tipo": "vazio", "mensagem": "Nenhuma luta nesta categoria.", "rounds": []}

    rr = [l for l in lutas if (l.get("chave_sistema") or "").strip() == "round_robin"]
    if rr and len(rr) == len(lutas):
        return montar_payload_rodizio_round_robin(rr)

    bo = [l for l in lutas if (l.get("chave_sistema") or "").strip() == "bo3"]
    if bo and len(bo) == len(lutas):
        return montar_payload_bo3_lista(bo)

    principal = filtrar_lutas_chave_principal(lutas)
    if principal is None:
        rr2 = [l for l in lutas if (l.get("chave_sistema") or "").strip() == "round_robin"]
        if rr2:
            return montar_payload_rodizio_round_robin(rr2)
        bo2 = [l for l in lutas if (l.get("chave_sistema") or "").strip() == "bo3"]
        if bo2:
            return montar_payload_bo3_lista(bo2)
        return {
            "tipo": "nao_eliminatoria",
            "mensagem": "Formato de chave não suportado na visualização. Use a lista de lutas.",
            "rounds": [],
        }
    if not principal:
        return {"tipo": "vazio", "mensagem": "Nenhuma luta da chave principal.", "rounds": []}

    by_round: Dict[int, List[Dict[str, Any]]] = {}
    for l in principal:
        r = int(l.get("round") or 1)
        by_round.setdefault(r, []).append(l)
    for r in by_round:
        by_round[r].sort(key=lambda x: (x.get("posicao_rodada") or 0, x.get("id") or 0))
    ordem_r = sorted(by_round.keys())
    n0 = len(by_round[ordem_r[0]])
    labels = _labels_rodadas(n0, len(ordem_r))

    rounds_out: List[Dict[str, Any]] = []
    for idx, r in enumerate(ordem_r):
        fase_id = f"col_{idx}"
        lutas_col: List[Dict[str, Any]] = []
        for pos, luta in enumerate(by_round[r]):
            fin = (luta.get("status") or "") == "finalizada"
            venc = luta.get("vencedor")
            lutas_col.append(
                {
                    "id": luta.get("id"),
                    "pos": pos,
                    "numero_exibicao": luta.get("id"),
                    "branco": _atleta_side(luta, "branco"),
                    "azul": _atleta_side(luta, "azul"),
                    "resultado": fin,
                    "vencedor": venc if venc in ("branco", "azul") else None,
                    "marcador_branco": _marcador_tipo_vitoria(luta.get("tipo_vitoria"))
                    if fin and venc == "branco"
                    else "",
                    "marcador_azul": _marcador_tipo_vitoria(luta.get("tipo_vitoria"))
                    if fin and venc == "azul"
                    else "",
                }
            )
        rounds_out.append(
            {
                "round": r,
                "label": labels[idx] if idx < len(labels) else f"Rodada {r}",
                "fase": fase_id,
                "lutas": lutas_col,
            }
        )

    return {"tipo": "eliminacao", "mensagem": "", "rounds": rounds_out}
