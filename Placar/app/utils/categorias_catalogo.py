"""
Catálogo oficial de categorias (290 linhas): CSV em `app/data/categorias_oficiais.csv`
ou geração via `gerar_arquivo_catalogo.todas_linhas()` se o arquivo não existir.
"""
from __future__ import annotations

import csv
from pathlib import Path


def _parse_decimal(val):
    if val is None:
        return None
    t = str(val).strip()
    if t in ("", r"\N", "NULL"):
        return None
    return float(t.replace(",", "."))


def _parse_int(val):
    if val is None:
        return None
    t = str(val).strip()
    if t in ("", r"\N", "NULL"):
        return None
    return int(float(t.replace(",", ".")))


def _linhas_brutas():
    p = Path(__file__).resolve().parent.parent / "data" / "categorias_oficiais.csv"
    if p.exists():
        with p.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f, delimiter=";"))
    from app.utils.gerar_arquivo_catalogo import todas_linhas

    return todas_linhas()


def templates_oficiais():
    """
    Retorna dicionários prontos para `Categoria(competicao_id=..., **tpl)`
    (exceto id da PK da competição).
    """
    out = []
    for row in _linhas_brutas():
        atv = str(row.get("ativo", "1")).strip().lower()
        if atv in ("0", "false", "n", "no"):
            continue
        genero = (row.get("genero") or "").strip().upper()
        sexo = "M" if genero.startswith("M") else "F"
        desc = (row.get("descricao") or "").strip() or None
        tpl = {
            "catalogo_id": int(row["id"]),
            "id_classe": (row.get("id_classe") or "").strip(),
            "classe_peso": (row.get("categoria") or "").strip(),
            "nome": (row.get("nome_categoria") or "").strip(),
            "sexo": sexo,
            "idade_min": _parse_int(row.get("idade_min")),
            "idade_max": _parse_int(row.get("idade_max")),
            "peso_min": _parse_decimal(row.get("peso_min")),
            "peso_max": _parse_decimal(row.get("peso_max")),
            "descricao": desc,
            "ativo": True,
            "faixa": None,
        }
        out.append(tpl)
    return out
