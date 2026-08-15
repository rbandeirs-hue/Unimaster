"""
Gera `app/data/categorias_oficiais.csv` — 290 categorias (tabela oficial).
Uso: python -m app.utils.gerar_arquivo_catalogo
"""
from __future__ import annotations

import csv
from pathlib import Path

DESC_SUB5 = "Atletas que completam 3 ou 4 anos no ano vigente. (Menores de 5 anos)"
DESC_SUB7 = "Atletas que completam 5 ou 6 anos no ano vigente. (Menores de 7 anos)"
DESC_SUB9_11 = "Atletas que completam 9 ou 10 anos no ano vigente. (Menores de 11 anos)"
DESC_SUB13 = "Atletas que completam 11 ou 12 anos no ano vigente. (Menores de 13 anos)"
DESC_SUB15 = "Atletas que completam 13 ou 14 anos no ano vigente. (Menores de 15 anos)"
DESC_CADETE = "Atletas que completam 15, 16 ou 17 anos no ano vigente. (Menores de 18 anos)"
DESC_JUNIOR = "Atletas que completam 15 a 20 anos no ano vigente. (Menores de 21 anos)"
DESC_SUB23 = "Atletas que completam 15 a 22 anos no ano vigente. (Menores de 23 anos)"
DESC_SENIOR = "Atletas que completam 15 anos ou mais no ano vigente. (Acima de 15 anos)"


def _emit(rows, cid, genero, id_classe, cat, nome, pmin, pmax, imin, imax, desc, ativo=1):
    rows.append(
        {
            "id": cid,
            "genero": genero,
            "id_classe": id_classe,
            "categoria": cat,
            "nome_categoria": nome,
            "peso_min": "" if pmin is None else f"{pmin:.2f}",
            "peso_max": "" if pmax is None else f"{pmax:.2f}",
            "idade_min": "" if imin is None else str(imin),
            "idade_max": "" if imax is None else str(imax),
            "descricao": desc,
            "ativo": str(ativo),
        }
    )
    return cid + 1


def _ladder(rows, cid, genero, id_classe, imin, imax, desc, spec):
    for cat, nome, pmin, pmax, d in spec:
        cid = _emit(rows, cid, genero, id_classe, cat, nome, pmin, pmax, imin, imax, d)
    return cid


def todas_linhas():
    rows = []
    cid = 1

    # SUB 5–11 (mesma estrutura de pesos por faixa etária)
    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "SUB 5",
        3,
        4,
        DESC_SUB5,
        [
            ("SUPERLIGEIRO", "SUB 5 MASCULINO SUPERLIGEIRO (-18 kg)", 0.0, 18.0, DESC_SUB5),
            ("LIGEIRO", "SUB 5 MASCULINO LIGEIRO (-20 kg)", 18.01, 20.0, DESC_SUB5),
            ("MEIO LEVE", "SUB 5 MASCULINO MEIO LEVE (-22 kg)", 20.01, 22.0, DESC_SUB5),
            ("LEVE", "SUB 5 MASCULINO LEVE (-24 kg)", 22.01, 24.0, DESC_SUB5),
            ("MEIO-MÉDIO", "SUB 5 MASCULINO MEIO-MÉDIO (-26 kg)", 24.01, 26.0, DESC_SUB5),
            ("MÉDIO", "SUB 5 MASCULINO MÉDIO (-28 kg)", 26.01, 28.0, DESC_SUB5),
            ("MEIO-PESADO", "SUB 5 MASCULINO MEIO-PESADO (-30 kg)", 28.01, 30.0, DESC_SUB5),
            ("PESADO", "SUB 5 MASCULINO PESADO (+30 kg)", 30.01, None, DESC_SUB5),
            ("SUPERPESADO", "SUB 5 MASCULINO SUPERPESADO", None, None, DESC_SUB5),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "SUB 5",
        3,
        4,
        DESC_SUB5,
        [
            ("SUPER LIGEIRO", "SUB 5 FEMININO SUPER LIGEIRO (-18 kg)", 0.0, 18.0, DESC_SUB5),
            ("LIGEIRO", "SUB 5 FEMININO LIGEIRO (-20 kg)", 18.01, 20.0, DESC_SUB5),
            ("MEIO LEVE", "SUB 5 FEMININO MEIO LEVE (-22 kg)", 20.01, 22.0, DESC_SUB5),
            ("LEVE", "SUB 5 FEMININO LEVE (-24 kg)", 22.01, 24.0, DESC_SUB5),
            ("MEIO-MÉDIO", "SUB 5 FEMININO MEIO-MÉDIO (-26 kg)", 24.01, 26.0, DESC_SUB5),
            ("MÉDIO", "SUB 5 FEMININO MÉDIO (-28 kg)", 26.01, 28.0, DESC_SUB5),
            ("MEIO PESADO", "SUB 5 FEMININO MEIO PESADO (-30 kg)", 28.01, 30.0, DESC_SUB5),
            ("PESADO", "SUB 5 FEMININO PESADO (+30 kg)", 30.01, None, DESC_SUB5),
            ("SUPER PESADO", "SUB 5 FEMININO SUPER PESADO", None, None, DESC_SUB5),
        ],
    )

    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "SUB 7",
        5,
        6,
        DESC_SUB7,
        [
            ("SUPERLIGEIRO", "SUB 7 MASCULINO SUPERLIGEIRO (-22 kg)", 0.0, 22.0, DESC_SUB7),
            ("LIGEIRO", "SUB 7 MASCULINO LIGEIRO (-24 kg)", 22.01, 24.0, DESC_SUB7),
            ("MEIO LEVE", "SUB 7 MASCULINO MEIO LEVE (-26 kg)", 24.01, 26.0, DESC_SUB7),
            ("LEVE", "SUB 7 MASCULINO LEVE (-28 kg)", 26.01, 28.0, DESC_SUB7),
            ("MEIO-MÉDIO", "SUB 7 MASCULINO MEIO-MÉDIO (-30 kg)", 28.01, 30.0, DESC_SUB7),
            ("MÉDIO", "SUB 7 MASCULINO MÉDIO (-32 kg)", 30.01, 32.0, DESC_SUB7),
            ("MEIO-PESADO", "SUB 7 MASCULINO MEIO-PESADO (-35 kg)", 32.01, 35.0, DESC_SUB7),
            ("PESADO", "SUB 7 MASCULINO PESADO (+35 kg)", 35.01, None, DESC_SUB7),
            ("SUPERPESADO", "SUB 7 MASCULINO SUPERPESADO", None, None, DESC_SUB7),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "SUB 7",
        5,
        6,
        DESC_SUB7,
        [
            ("SUPER LIGEIRO", "SUB 7 FEMININO SUPER LIGEIRO (-22 kg)", 0.0, 22.0, DESC_SUB7),
            ("LIGEIRO", "SUB 7 FEMININO LIGEIRO (-24 kg)", 22.01, 24.0, DESC_SUB7),
            ("MEIO LEVE", "SUB 7 FEMININO MEIO LEVE (-26 kg)", 24.01, 26.0, DESC_SUB7),
            ("LEVE", "SUB 7 FEMININO LEVE (-28 kg)", 26.01, 28.0, DESC_SUB7),
            ("MEIO-MÉDIO", "SUB 7 FEMININO MEIO-MÉDIO (-30 kg)", 28.01, 30.0, DESC_SUB7),
            ("MÉDIO", "SUB 7 FEMININO MÉDIO (-32 kg)", 30.01, 32.0, DESC_SUB7),
            ("MEIO PESADO", "SUB 7 FEMININO MEIO PESADO (-35 kg)", 32.01, 35.0, DESC_SUB7),
            ("PESADO", "SUB 7 FEMININO PESADO (+35 kg)", 35.01, None, DESC_SUB7),
            ("SUPER PESADO", "SUB 7 FEMININO SUPER PESADO", None, None, DESC_SUB7),
        ],
    )

    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "SUB 9",
        7,
        8,
        DESC_SUB9_11,
        [
            ("SUPERLIGEIRO", "SUB 9 MASCULINO SUPERLIGEIRO (-28 kg)", 0.0, 28.0, DESC_SUB9_11),
            ("LIGEIRO", "SUB 9 MASCULINO LIGEIRO (-30 kg)", 28.01, 30.0, DESC_SUB9_11),
            ("MEIO LEVE", "SUB 9 MASCULINO MEIO LEVE (-33 kg)", 30.01, 33.0, DESC_SUB9_11),
            ("LEVE", "SUB 9 MASCULINO LEVE (-36 kg)", 33.01, 36.0, DESC_SUB9_11),
            ("MEIO-MÉDIO", "SUB 9 MASCULINO MEIO-MÉDIO (-40 kg)", 36.01, 40.0, DESC_SUB9_11),
            ("MÉDIO", "SUB 9 MASCULINO MÉDIO (-45 kg)", 40.01, 45.0, DESC_SUB9_11),
            ("MEIO-PESADO", "SUB 9 MASCULINO MEIO-PESADO (-50 kg)", 45.01, 50.0, DESC_SUB9_11),
            ("PESADO", "SUB 9 MASCULINO PESADO (+50 kg)", 50.01, None, DESC_SUB9_11),
            ("SUPERPESADO", "SUB 9 MASCULINO SUPERPESADO", None, None, DESC_SUB9_11),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "SUB 9",
        7,
        8,
        DESC_SUB9_11,
        [
            ("SUPER LIGEIRO", "SUB 9 FEMININO SUPER LIGEIRO (-28 kg)", 0.0, 28.0, DESC_SUB9_11),
            ("LIGEIRO", "SUB 9 FEMININO LIGEIRO (-30 kg)", 28.01, 30.0, DESC_SUB9_11),
            ("MEIO LEVE", "SUB 9 FEMININO MEIO LEVE (-33 kg)", 30.01, 33.0, DESC_SUB9_11),
            ("LEVE", "SUB 9 FEMININO LEVE (-36 kg)", 33.01, 36.0, DESC_SUB9_11),
            ("MEIO-MÉDIO", "SUB 9 FEMININO MEIO-MÉDIO (-40 kg)", 36.01, 40.0, DESC_SUB9_11),
            ("MÉDIO", "SUB 9 FEMININO MÉDIO (-45 kg)", 40.01, 45.0, DESC_SUB9_11),
            ("MEIO PESADO", "SUB 9 FEMININO MEIO PESADO (-50 kg)", 45.01, 50.0, DESC_SUB9_11),
            ("PESADO", "SUB 9 FEMININO PESADO (+50 kg)", 50.01, None, DESC_SUB9_11),
            ("SUPER PESADO", "SUB 9 FEMININO SUPER PESADO", None, None, DESC_SUB9_11),
        ],
    )

    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "SUB 11",
        9,
        10,
        DESC_SUB9_11,
        [
            ("SUPERLIGEIRO", "SUB 11 MASCULINO SUPERLIGEIRO (-28 kg)", 0.0, 28.0, DESC_SUB9_11),
            ("LIGEIRO", "SUB 11 MASCULINO LIGEIRO (-30 kg)", 28.01, 30.0, DESC_SUB9_11),
            ("MEIO LEVE", "SUB 11 MASCULINO MEIO LEVE (-33 kg)", 30.01, 33.0, DESC_SUB9_11),
            ("LEVE", "SUB 11 MASCULINO LEVE (-36 kg)", 33.01, 36.0, DESC_SUB9_11),
            ("MEIO-MÉDIO", "SUB 11 MASCULINO MEIO-MÉDIO (-40 kg)", 36.01, 40.0, DESC_SUB9_11),
            ("MÉDIO", "SUB 11 MASCULINO MÉDIO (-45 kg)", 40.01, 45.0, DESC_SUB9_11),
            ("MEIO-PESADO", "SUB 11 MASCULINO MEIO-PESADO (-50 kg)", 45.01, 50.0, DESC_SUB9_11),
            ("PESADO", "SUB 11 MASCULINO PESADO (+50 kg)", 50.01, None, DESC_SUB9_11),
            ("SUPERPESADO", "SUB 11 MASCULINO SUPERPESADO", None, None, ""),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "SUB 11",
        9,
        10,
        DESC_SUB9_11,
        [
            ("SUPER LIGEIRO", "SUB 11 FEMININO SUPER LIGEIRO (-28 kg)", 0.0, 28.0, DESC_SUB9_11),
            ("LIGEIRO", "SUB 11 FEMININO LIGEIRO (-30 kg)", 28.01, 30.0, DESC_SUB9_11),
            ("MEIO LEVE", "SUB 11 FEMININO MEIO LEVE (-33 kg)", 30.01, 33.0, DESC_SUB9_11),
            ("LEVE", "SUB 11 FEMININO LEVE (-36 kg)", 33.01, 36.0, DESC_SUB9_11),
            ("MEIO-MÉDIO", "SUB 11 FEMININO MEIO-MÉDIO (-40 kg)", 36.01, 40.0, DESC_SUB9_11),
            ("MÉDIO", "SUB 11 FEMININO MÉDIO (-45 kg)", 40.01, 45.0, DESC_SUB9_11),
            ("MEIO PESADO", "SUB 11 FEMININO MEIO PESADO (-50 kg)", 45.01, 50.0, DESC_SUB9_11),
            ("PESADO", "SUB 11 FEMININO PESADO (+50 kg)", 50.01, None, DESC_SUB9_11),
            ("SUPER PESADO", "SUB 11 FEMININO SUPER PESADO", None, None, ""),
        ],
    )

    # SUB 13 M — duas faixas "LEVE"
    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "SUB 13",
        11,
        12,
        DESC_SUB13,
        [
            ("SUPERLIGEIRO", "SUB 13 MASCULINO SUPERLIGEIRO (-35 kg)", 0.0, 35.0, DESC_SUB13),
            ("LIGEIRO", "SUB 13 MASCULINO LIGEIRO (-40 kg)", 35.01, 40.0, DESC_SUB13),
            ("LEVE", "SUB 13 MASCULINO LEVE (-45 kg)", 40.01, 45.0, DESC_SUB13),
            ("LEVE", "SUB 13 MASCULINO LEVE (-50 kg)", 45.01, 50.0, DESC_SUB13),
            ("MEIO-MÉDIO", "SUB 13 MASCULINO MEIO-MÉDIO (-55 kg)", 50.01, 55.0, DESC_SUB13),
            ("MÉDIO", "SUB 13 MASCULINO MÉDIO (-60 kg)", 55.01, 60.0, DESC_SUB13),
            ("MEIO-PESADO", "SUB 13 MASCULINO MEIO-PESADO (-66 kg)", 60.01, 66.0, DESC_SUB13),
            ("PESADO", "SUB 13 MASCULINO PESADO (-73 kg)", 66.01, 73.0, DESC_SUB13),
            ("SUPERPESADO", "SUB 13 MASCULINO SUPERPESADO (+73 kg)", 73.01, None, DESC_SUB13),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "SUB 13",
        11,
        12,
        DESC_SUB13,
        [
            ("SUPER LIGEIRO", "SUB 13 FEMININO SUPER LIGEIRO (-32 kg)", 0.0, 32.0, DESC_SUB13),
            ("LIGEIRO", "SUB 13 FEMININO LIGEIRO (-40 kg)", 35.01, 40.0, DESC_SUB13),
            ("MEIO LEVE", "SUB 13 FEMININO MEIO LEVE (-45 kg)", 40.01, 45.0, DESC_SUB13),
            ("LEVE", "SUB 13 FEMININO LEVE (-50 kg)", 45.01, 50.0, DESC_SUB13),
            ("MEIO-MÉDIO", "SUB 13 FEMININO MEIO-MÉDIO (-55 kg)", 50.01, 55.0, DESC_SUB13),
            ("MÉDIO", "SUB 13 FEMININO MÉDIO (-60 kg)", 55.01, 60.0, DESC_SUB13),
            ("MEIO PESADO", "SUB 13 FEMININO MEIO PESADO (-66 kg)", 60.01, 66.0, DESC_SUB13),
            ("PESADO", "SUB 13 FEMININO PESADO (-73 kg)", 66.01, 73.0, DESC_SUB13),
            ("SUPER PESADO", "SUB 13 FEMININO SUPER PESADO (+63 kg)", 73.01, None, DESC_SUB13),
        ],
    )

    # SUB 15 M — rótulos conforme tabela (incl. duplicata MEIO-PESADO id 96–98)
    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "SUB 15",
        13,
        14,
        DESC_SUB15,
        [
            ("LIGEIRO", "SUB 15 MASCULINO LIGEIRO (-40 kg)", 0.0, 40.0, DESC_SUB15),
            ("MEIO-LEVE", "SUB 15 MASCULINO MEIO-LEVE (-45 kg)", 40.01, 45.0, DESC_SUB15),
            ("LEVE", "SUB 15 MASCULINO LEVE (-50 kg)", 45.01, 50.0, DESC_SUB15),
            ("MEIO-MÉDIO", "SUB 15 MASCULINO MEIO-MÉDIO (-55 kg)", 50.01, 55.0, DESC_SUB15),
            ("MÉDIO", "SUB 15 MASCULINO MÉDIO (-60 kg)", 55.01, 60.0, DESC_SUB15),
            ("MEIO-PESADO", "SUB 15 MASCULINO MEIO-PESADO (-66 kg)", 60.01, 66.0, DESC_SUB15),
            ("PESADO", "SUB 15 MASCULINO PESADO (-73 kg)", 66.01, 73.0, DESC_SUB15),
            ("MEIO-PESADO", "SUB 15 MASCULINO MEIO-PESADO (-81 kg)", 73.01, 81.0, DESC_SUB15),
            ("SUPER PESADO", "SUB 15 MASCULINO SUPER PESADO (+100 kg)", 100.01, None, DESC_SUB15),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "SUB 15",
        13,
        14,
        DESC_SUB15,
        [
            ("LIGEIRO", "SUB 15 FEMININO LIGEIRO (-36 kg)", 0.0, 36.0, DESC_SUB15),
            ("MEIO-LEVE", "SUB 15 FEMININO MEIO-LEVE (-40 kg)", 36.01, 40.0, DESC_SUB15),
            ("LEVE", "SUB 15 FEMININO LEVE (-44 kg)", 40.01, 44.0, DESC_SUB15),
            ("MEIO-MÉDIO", "SUB 15 FEMININO MEIO-MÉDIO (-48 kg)", 44.01, 48.0, DESC_SUB15),
            ("MÉDIO", "SUB 15 FEMININO MÉDIO (-52 kg)", 48.01, 52.0, DESC_SUB15),
            ("MEIO-PESADO", "SUB 15 FEMININO MEIO-PESADO (-57 kg)", 52.01, 57.0, DESC_SUB15),
            ("PESADO", "SUB 15 FEMININO PESADO (-63 kg)", 57.01, 63.0, DESC_SUB15),
            ("MEIO-PESADO", "SUB 15 FEMININO MEIO-PESADO (-70 kg)", 63.01, 70.0, DESC_SUB15),
            ("SUPER PESADO", "SUB 15 FEMININO SUPER PESADO (+70 kg)", 70.01, None, DESC_SUB15),
        ],
    )

    # CADETE
    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "CADETE",
        15,
        17,
        DESC_CADETE,
        [
            ("LIGEIRO", "CADETE MASCULINO LIGEIRO (-60 kg)", 55.01, 60.0, DESC_CADETE),
            ("MEIO-LEVE", "CADETE MASCULINO MEIO-LEVE (-66 kg)", 60.01, 66.0, DESC_CADETE),
            ("LEVE", "CADETE MASCULINO LEVE (-73 kg)", 66.01, 73.0, DESC_CADETE),
            ("MEIO-MÉDIO", "CADETE MASCULINO MEIO-MÉDIO (-81 kg)", 73.01, 81.0, DESC_CADETE),
            ("MÉDIO", "CADETE MASCULINO MÉDIO (-90 kg)", 81.01, 90.0, DESC_CADETE),
            ("MEIO-PESADO", "CADETE MASCULINO MEIO-PESADO (-100 kg)", 90.01, 100.0, DESC_CADETE),
            ("SUPER PESADO", "CADETE MASCULINO SUPER PESADO (+100 kg)", 100.01, None, DESC_CADETE),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "CADETE",
        15,
        17,
        DESC_CADETE,
        [
            ("LIGEIRO", "CADETE FEMININO LIGEIRO (-48 kg)", 44.01, 48.0, DESC_CADETE),
            ("MEIO-LEVE", "CADETE FEMININO MEIO-LEVE (-52 kg)", 48.01, 52.0, DESC_CADETE),
            ("LEVE", "CADETE FEMININO LEVE (-57 kg)", 52.01, 57.0, DESC_CADETE),
            ("MEIO-MÉDIO", "CADETE FEMININO MEIO-MÉDIO (-63 kg)", 57.01, 63.0, DESC_CADETE),
            ("MÉDIO", "CADETE FEMININO MÉDIO (-70 kg)", 63.01, 70.0, DESC_CADETE),
            ("MEIO-PESADO", "CADETE FEMININO MEIO-PESADO (-78 kg)", 70.01, 78.0, DESC_CADETE),
            ("SUPER PESADO", "CADETE FEMININO SUPER PESADO (+78 kg)", 78.01, None, DESC_CADETE),
        ],
    )

    # JÚNIOR
    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "JÚNIOR",
        15,
        20,
        DESC_JUNIOR,
        [
            ("LIGEIRO", "JÚNIOR MASCULINO LIGEIRO (-60 kg)", 55.01, 60.0, DESC_JUNIOR),
            ("MEIO-LEVE", "JÚNIOR MASCULINO MEIO-LEVE (-66 kg)", 60.01, 66.0, DESC_JUNIOR),
            ("LEVE", "JÚNIOR MASCULINO LEVE (-73 kg)", 66.01, 73.0, DESC_JUNIOR),
            ("MEIO-MÉDIO", "JÚNIOR MASCULINO MEIO-MÉDIO (-81 kg)", 73.01, 81.0, DESC_JUNIOR),
            ("MÉDIO", "JÚNIOR MASCULINO MÉDIO (-90 kg)", 81.01, 90.0, DESC_JUNIOR),
            ("MEIO-PESADO", "JÚNIOR MASCULINO MEIO-PESADO (-100 kg)", 90.01, 100.0, DESC_JUNIOR),
            ("SUPER PESADO", "JÚNIOR MASCULINO SUPER PESADO (+100 kg)", 100.01, None, DESC_JUNIOR),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "JÚNIOR",
        15,
        20,
        DESC_JUNIOR,
        [
            ("LIGEIRO", "JÚNIOR FEMININO LIGEIRO (-48 kg)", 44.01, 48.0, DESC_JUNIOR),
            ("MEIO-LEVE", "JÚNIOR FEMININO MEIO-LEVE (-52 kg)", 48.01, 52.0, DESC_JUNIOR),
            ("LEVE", "JÚNIOR FEMININO LEVE (-57 kg)", 52.01, 57.0, DESC_JUNIOR),
            ("MEIO-MÉDIO", "JÚNIOR FEMININO MEIO-MÉDIO (-63 kg)", 57.01, 63.0, DESC_JUNIOR),
            ("MÉDIO", "JÚNIOR FEMININO MÉDIO (-70 kg)", 63.01, 70.0, DESC_JUNIOR),
            ("MEIO-PESADO", "JÚNIOR FEMININO MEIO-PESADO (-78 kg)", 70.01, 78.0, DESC_JUNIOR),
            ("SUPER PESADO", "JÚNIOR FEMININO SUPER PESADO (+78 kg)", 78.01, None, DESC_JUNIOR),
        ],
    )

    # SUB-23
    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "SUB-23",
        15,
        22,
        DESC_SUB23,
        [
            ("LIGEIRO", "SUB-23 MASCULINO LIGEIRO (-60 kg)", 55.01, 60.0, DESC_SUB23),
            ("MEIO-LEVE", "SUB-23 MASCULINO MEIO-LEVE (-66 kg)", 60.01, 66.0, DESC_SUB23),
            ("LEVE", "SUB-23 MASCULINO LEVE (-73 kg)", 66.01, 73.0, DESC_SUB23),
            ("MEIO-MÉDIO", "SUB-23 MASCULINO MEIO-MÉDIO (-81 kg)", 73.01, 81.0, DESC_SUB23),
            ("MÉDIO", "SUB-23 MASCULINO MÉDIO (-90 kg)", 81.01, 90.0, DESC_SUB23),
            ("MEIO-PESADO", "SUB-23 MASCULINO MEIO-PESADO (-100 kg)", 90.01, 100.0, DESC_SUB23),
            ("SUPER PESADO", "SUB-23 MASCULINO SUPER PESADO (+100 kg)", 100.01, None, DESC_SUB23),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "SUB-23",
        15,
        22,
        DESC_SUB23,
        [
            ("LIGEIRO", "SUB-23 FEMININO LIGEIRO (-48 kg)", 44.01, 48.0, DESC_SUB23),
            ("MEIO-LEVE", "SUB-23 FEMININO MEIO-LEVE (-52 kg)", 48.01, 52.0, DESC_SUB23),
            ("LEVE", "SUB-23 FEMININO LEVE (-57 kg)", 52.01, 57.0, DESC_SUB23),
            ("MEIO-MÉDIO", "SUB-23 FEMININO MEIO-MÉDIO (-63 kg)", 57.01, 63.0, DESC_SUB23),
            ("MÉDIO", "SUB-23 FEMININO MÉDIO (-70 kg)", 63.01, 70.0, DESC_SUB23),
            ("MEIO-PESADO", "SUB-23 FEMININO MEIO-PESADO (-78 kg)", 70.01, 78.0, DESC_SUB23),
            ("SUPER PESADO", "SUB-23 FEMININO SUPER PESADO (+78 kg)", 78.01, None, DESC_SUB23),
        ],
    )

    # SÊNIOR (idade_max aberta)
    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "SÊNIOR",
        15,
        None,
        DESC_SENIOR,
        [
            ("LIGEIRO", "SÊNIOR MASCULINO LIGEIRO (-60 kg)", 55.01, 60.0, DESC_SENIOR),
            ("MEIO-LEVE", "SÊNIOR MASCULINO MEIO-LEVE (-66 kg)", 60.01, 66.0, DESC_SENIOR),
            ("LEVE", "SÊNIOR MASCULINO LEVE (-73 kg)", 66.01, 73.0, DESC_SENIOR),
            ("MEIO-MÉDIO", "SÊNIOR MASCULINO MEIO-MÉDIO (-81 kg)", 73.01, 81.0, DESC_SENIOR),
            ("MÉDIO", "SÊNIOR MASCULINO MÉDIO (-90 kg)", 81.01, 90.0, DESC_SENIOR),
            ("MEIO-PESADO", "SÊNIOR MASCULINO MEIO-PESADO (-100 kg)", 90.01, 100.0, DESC_SENIOR),
            ("SUPER PESADO", "SÊNIOR MASCULINO SUPER PESADO (+100 kg)", 100.01, None, DESC_SENIOR),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "SÊNIOR",
        15,
        None,
        DESC_SENIOR,
        [
            ("LIGEIRO", "SÊNIOR FEMININO LIGEIRO (-48 kg)", 44.01, 48.0, DESC_SENIOR),
            ("MEIO-LEVE", "SÊNIOR FEMININO MEIO-LEVE (-52 kg)", 48.01, 52.0, DESC_SENIOR),
            ("LEVE", "SÊNIOR FEMININO LEVE (-57 kg)", 52.01, 57.0, DESC_SENIOR),
            ("MEIO-MÉDIO", "SÊNIOR FEMININO MEIO-MÉDIO (-63 kg)", 57.01, 63.0, DESC_SENIOR),
            ("MÉDIO", "SÊNIOR FEMININO MÉDIO (-70 kg)", 63.01, 70.0, DESC_SENIOR),
            ("MEIO-PESADO", "SÊNIOR FEMININO MEIO-PESADO (-78 kg)", 70.01, 78.0, DESC_SENIOR),
            ("SUPER PESADO", "SÊNIOR FEMININO SUPER PESADO (+78 kg)", 78.01, None, DESC_SENIOR),
        ],
    )

    def master_block(label, imin, imax, desc_m, desc_f):
        nonlocal cid
        m_weights = [
            ("LIGEIRO", f"{label} MASCULINO LIGEIRO (-60 kg)", 0.0, 60.0),
            ("MEIO-LEVE", f"{label} MASCULINO MEIO-LEVE (-66 kg)", 60.01, 66.0),
            ("LEVE", f"{label} MASCULINO LEVE (-73 kg)", 66.01, 73.0),
            ("MEIO-MÉDIO", f"{label} MASCULINO MEIO-MÉDIO (-81 kg)", 73.01, 81.0),
            ("MÉDIO", f"{label} MASCULINO MÉDIO (-90 kg)", 81.01, 90.0),
            ("MEIO-PESADO", f"{label} MASCULINO MEIO-PESADO (-100 kg)", 90.01, 100.0),
            ("SUPER PESADO", f"{label} MASCULINO SUPER PESADO (+100 kg)", 100.01, None),
        ]
        f_weights = [
            ("LIGEIRO", f"{label} FEMININO LIGEIRO (-48 kg)", 0.0, 48.0),
            ("MEIO-LEVE", f"{label} FEMININO MEIO-LEVE (-52 kg)", 48.01, 52.0),
            ("LEVE", f"{label} FEMININO LEVE (-57 kg)", 52.01, 57.0),
            ("MEIO-MÉDIO", f"{label} FEMININO MEIO-MÉDIO (-63 kg)", 57.01, 63.0),
            ("MÉDIO", f"{label} FEMININO MÉDIO (-70 kg)", 63.01, 70.0),
            ("MEIO-PESADO", f"{label} FEMININO MEIO-PESADO (-78 kg)", 70.01, 78.0),
            ("SUPER PESADO", f"{label} FEMININO SUPER PESADO (+78 kg)", 78.01, None),
        ]
        spec_m = [(a, b, c, d, desc_m) for a, b, c, d in m_weights]
        spec_f = [(a, b, c, d, desc_f) for a, b, c, d in f_weights]
        cid = _ladder(rows, cid, "MASCULINO", label, imin, imax, desc_m, spec_m)
        cid = _ladder(rows, cid, "FEMININO", label, imin, imax, desc_f, spec_f)

    for mi in range(1, 7):
        label = f"MASTER {mi}"
        a, b = (30 + (mi - 1) * 5, 34 + (mi - 1) * 5)
        d = f"Atletas que completam {a} a {b} anos no ano vigente. (Master)"
        master_block(label, a, b, d, d)

    d78 = "Atletas que completam {a} a {b} anos no ano vigente. (Master - Sem Shime-waza)"
    master_block("MASTER 7", 60, 64, d78.format(a=60, b=64), d78.format(a=60, b=64))
    master_block("MASTER 8", 65, 69, d78.format(a=65, b=69), d78.format(a=65, b=69))

    desc9 = "Atletas que completam 70 anos ou mais no ano vigente. (Master - A partir de 70 - Sem Shime-waza)"
    cid = _ladder(
        rows,
        cid,
        "MASCULINO",
        "MASTER 9",
        70,
        None,
        desc9,
        [
            ("LIGEIRO", "MASTER 9 MASCULINO LIGEIRO (-60 kg)", 0.0, 60.0, desc9),
            ("MEIO-LEVE", "MASTER 9 MASCULINO MEIO-LEVE (-66 kg)", 60.01, 66.0, desc9),
            ("LEVE", "MASTER 9 MASCULINO LEVE (-73 kg)", 66.01, 73.0, desc9),
            ("MEIO-MÉDIO", "MASTER 9 MASCULINO MEIO-MÉDIO (-81 kg)", 73.01, 81.0, desc9),
            ("MÉDIO", "MASTER 9 MASCULINO MÉDIO (-90 kg)", 81.01, 90.0, desc9),
            ("MEIO-PESADO", "MASTER 9 MASCULINO MEIO-PESADO (-100 kg)", 90.01, 100.0, desc9),
            ("SUPER PESADO", "MASTER 9 MASCULINO SUPER PESADO (+100 kg)", 100.01, None, desc9),
        ],
    )
    cid = _ladder(
        rows,
        cid,
        "FEMININO",
        "MASTER 9",
        70,
        None,
        desc9,
        [
            ("LIGEIRO", "MASTER 9 FEMININO LIGEIRO (-48 kg)", 0.0, 48.0, desc9),
            ("MEIO-LEVE", "MASTER 9 FEMININO MEIO-LEVE (-52 kg)", 48.01, 52.0, desc9),
            ("LEVE", "MASTER 9 FEMININO LEVE (-57 kg)", 52.01, 57.0, desc9),
            ("MEIO-MÉDIO", "MASTER 9 FEMININO MEIO-MÉDIO (-63 kg)", 57.01, 63.0, desc9),
            ("MÉDIO", "MASTER 9 FEMININO MÉDIO (-70 kg)", 63.01, 70.0, desc9),
            ("MEIO-PESADO", "MASTER 9 FEMININO MEIO-PESADO (-78 kg)", 70.01, 78.0, desc9),
            ("SUPER PESADO", "MASTER 9 FEMININO SUPER PESADO (+78 kg)", 78.01, None, desc9),
        ],
    )

    assert cid == 291, f"esperado 290 categorias, obteve {cid - 1}"
    assert len(rows) == 290
    return rows


def escrever_csv(dest: Path | None = None) -> Path:
    dest = dest or Path(__file__).resolve().parent.parent / "data" / "categorias_oficiais.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows = todas_linhas()
    fieldnames = [
        "id",
        "genero",
        "id_classe",
        "categoria",
        "nome_categoria",
        "peso_min",
        "peso_max",
        "idade_min",
        "idade_max",
        "descricao",
        "ativo",
    ]
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return dest


if __name__ == "__main__":
    p = escrever_csv()
    print(f"Escrito: {p} ({290} linhas)")
