"""
Legado: a geração automática usa o catálogo oficial em
`app/utils/categorias_catalogo.py` (290 categorias) e `app/data/categorias_oficiais.csv`.

A lista abaixo permanece apenas como referência histórica — não é mais usada em `gerar_categorias`.
"""

CATEGORIAS_CBJ = [
    # ── MIRIM ────────────────────────────────────────────────
    {"nome": "Mirim M -30kg",  "sexo": "M", "idade_min": 9,  "idade_max": 10, "peso_min": None, "peso_max": 30.0, "faixa": "branca"},
    {"nome": "Mirim M -34kg",  "sexo": "M", "idade_min": 9,  "idade_max": 10, "peso_min": 30.0, "peso_max": 34.0, "faixa": "branca"},
    {"nome": "Mirim M -38kg",  "sexo": "M", "idade_min": 9,  "idade_max": 10, "peso_min": 34.0, "peso_max": 38.0, "faixa": "branca"},
    {"nome": "Mirim M -42kg",  "sexo": "M", "idade_min": 9,  "idade_max": 10, "peso_min": 38.0, "peso_max": 42.0, "faixa": "branca"},
    {"nome": "Mirim M +42kg",  "sexo": "M", "idade_min": 9,  "idade_max": 10, "peso_min": 42.0, "peso_max": None, "faixa": "branca"},
    {"nome": "Mirim F -28kg",  "sexo": "F", "idade_min": 9,  "idade_max": 10, "peso_min": None, "peso_max": 28.0, "faixa": "branca"},
    {"nome": "Mirim F -32kg",  "sexo": "F", "idade_min": 9,  "idade_max": 10, "peso_min": 28.0, "peso_max": 32.0, "faixa": "branca"},
    {"nome": "Mirim F -36kg",  "sexo": "F", "idade_min": 9,  "idade_max": 10, "peso_min": 32.0, "peso_max": 36.0, "faixa": "branca"},
    {"nome": "Mirim F +36kg",  "sexo": "F", "idade_min": 9,  "idade_max": 10, "peso_min": 36.0, "peso_max": None, "faixa": "branca"},

    # ── INFANTIL ─────────────────────────────────────────────
    {"nome": "Infantil M -34kg", "sexo": "M", "idade_min": 11, "idade_max": 12, "peso_min": None, "peso_max": 34.0, "faixa": "branca"},
    {"nome": "Infantil M -38kg", "sexo": "M", "idade_min": 11, "idade_max": 12, "peso_min": 34.0, "peso_max": 38.0, "faixa": "branca"},
    {"nome": "Infantil M -42kg", "sexo": "M", "idade_min": 11, "idade_max": 12, "peso_min": 38.0, "peso_max": 42.0, "faixa": "branca"},
    {"nome": "Infantil M -46kg", "sexo": "M", "idade_min": 11, "idade_max": 12, "peso_min": 42.0, "peso_max": 46.0, "faixa": "branca"},
    {"nome": "Infantil M -50kg", "sexo": "M", "idade_min": 11, "idade_max": 12, "peso_min": 46.0, "peso_max": 50.0, "faixa": "branca"},
    {"nome": "Infantil M +50kg", "sexo": "M", "idade_min": 11, "idade_max": 12, "peso_min": 50.0, "peso_max": None, "faixa": "branca"},
    {"nome": "Infantil F -32kg", "sexo": "F", "idade_min": 11, "idade_max": 12, "peso_min": None, "peso_max": 32.0, "faixa": "branca"},
    {"nome": "Infantil F -36kg", "sexo": "F", "idade_min": 11, "idade_max": 12, "peso_min": 32.0, "peso_max": 36.0, "faixa": "branca"},
    {"nome": "Infantil F -40kg", "sexo": "F", "idade_min": 11, "idade_max": 12, "peso_min": 36.0, "peso_max": 40.0, "faixa": "branca"},
    {"nome": "Infantil F -44kg", "sexo": "F", "idade_min": 11, "idade_max": 12, "peso_min": 40.0, "peso_max": 44.0, "faixa": "branca"},
    {"nome": "Infantil F +44kg", "sexo": "F", "idade_min": 11, "idade_max": 12, "peso_min": 44.0, "peso_max": None, "faixa": "branca"},

    # ── INFANTO-JUVENIL ──────────────────────────────────────
    {"nome": "Infanto M -42kg", "sexo": "M", "idade_min": 13, "idade_max": 14, "peso_min": None, "peso_max": 42.0, "faixa": "amarela"},
    {"nome": "Infanto M -46kg", "sexo": "M", "idade_min": 13, "idade_max": 14, "peso_min": 42.0, "peso_max": 46.0, "faixa": "amarela"},
    {"nome": "Infanto M -50kg", "sexo": "M", "idade_min": 13, "idade_max": 14, "peso_min": 46.0, "peso_max": 50.0, "faixa": "amarela"},
    {"nome": "Infanto M -55kg", "sexo": "M", "idade_min": 13, "idade_max": 14, "peso_min": 50.0, "peso_max": 55.0, "faixa": "amarela"},
    {"nome": "Infanto M -60kg", "sexo": "M", "idade_min": 13, "idade_max": 14, "peso_min": 55.0, "peso_max": 60.0, "faixa": "amarela"},
    {"nome": "Infanto M +60kg", "sexo": "M", "idade_min": 13, "idade_max": 14, "peso_min": 60.0, "peso_max": None, "faixa": "amarela"},
    {"nome": "Infanto F -40kg", "sexo": "F", "idade_min": 13, "idade_max": 14, "peso_min": None, "peso_max": 40.0, "faixa": "amarela"},
    {"nome": "Infanto F -44kg", "sexo": "F", "idade_min": 13, "idade_max": 14, "peso_min": 40.0, "peso_max": 44.0, "faixa": "amarela"},
    {"nome": "Infanto F -48kg", "sexo": "F", "idade_min": 13, "idade_max": 14, "peso_min": 44.0, "peso_max": 48.0, "faixa": "amarela"},
    {"nome": "Infanto F -52kg", "sexo": "F", "idade_min": 13, "idade_max": 14, "peso_min": 48.0, "peso_max": 52.0, "faixa": "amarela"},
    {"nome": "Infanto F +52kg", "sexo": "F", "idade_min": 13, "idade_max": 14, "peso_min": 52.0, "peso_max": None, "faixa": "amarela"},

    # ── JUVENIL ──────────────────────────────────────────────
    {"nome": "Juvenil M -50kg", "sexo": "M", "idade_min": 15, "idade_max": 17, "peso_min": None, "peso_max": 50.0, "faixa": "verde"},
    {"nome": "Juvenil M -55kg", "sexo": "M", "idade_min": 15, "idade_max": 17, "peso_min": 50.0, "peso_max": 55.0, "faixa": "verde"},
    {"nome": "Juvenil M -60kg", "sexo": "M", "idade_min": 15, "idade_max": 17, "peso_min": 55.0, "peso_max": 60.0, "faixa": "verde"},
    {"nome": "Juvenil M -66kg", "sexo": "M", "idade_min": 15, "idade_max": 17, "peso_min": 60.0, "peso_max": 66.0, "faixa": "verde"},
    {"nome": "Juvenil M -73kg", "sexo": "M", "idade_min": 15, "idade_max": 17, "peso_min": 66.0, "peso_max": 73.0, "faixa": "verde"},
    {"nome": "Juvenil M -81kg", "sexo": "M", "idade_min": 15, "idade_max": 17, "peso_min": 73.0, "peso_max": 81.0, "faixa": "verde"},
    {"nome": "Juvenil M +81kg", "sexo": "M", "idade_min": 15, "idade_max": 17, "peso_min": 81.0, "peso_max": None, "faixa": "verde"},
    {"nome": "Juvenil F -44kg", "sexo": "F", "idade_min": 15, "idade_max": 17, "peso_min": None, "peso_max": 44.0, "faixa": "verde"},
    {"nome": "Juvenil F -48kg", "sexo": "F", "idade_min": 15, "idade_max": 17, "peso_min": 44.0, "peso_max": 48.0, "faixa": "verde"},
    {"nome": "Juvenil F -52kg", "sexo": "F", "idade_min": 15, "idade_max": 17, "peso_min": 48.0, "peso_max": 52.0, "faixa": "verde"},
    {"nome": "Juvenil F -57kg", "sexo": "F", "idade_min": 15, "idade_max": 17, "peso_min": 52.0, "peso_max": 57.0, "faixa": "verde"},
    {"nome": "Juvenil F -63kg", "sexo": "F", "idade_min": 15, "idade_max": 17, "peso_min": 57.0, "peso_max": 63.0, "faixa": "verde"},
    {"nome": "Juvenil F +63kg", "sexo": "F", "idade_min": 15, "idade_max": 17, "peso_min": 63.0, "peso_max": None, "faixa": "verde"},

    # ── SENIOR ───────────────────────────────────────────────
    {"nome": "Senior M -60kg", "sexo": "M", "idade_min": 15, "idade_max": 99, "peso_min": None, "peso_max": 60.0, "faixa": "azul"},
    {"nome": "Senior M -66kg", "sexo": "M", "idade_min": 15, "idade_max": 99, "peso_min": 60.0, "peso_max": 66.0, "faixa": "azul"},
    {"nome": "Senior M -73kg", "sexo": "M", "idade_min": 15, "idade_max": 99, "peso_min": 66.0, "peso_max": 73.0, "faixa": "azul"},
    {"nome": "Senior M -81kg", "sexo": "M", "idade_min": 15, "idade_max": 99, "peso_min": 73.0, "peso_max": 81.0, "faixa": "azul"},
    {"nome": "Senior M -90kg", "sexo": "M", "idade_min": 15, "idade_max": 99, "peso_min": 81.0, "peso_max": 90.0, "faixa": "azul"},
    {"nome": "Senior M -100kg","sexo": "M", "idade_min": 15, "idade_max": 99, "peso_min": 90.0, "peso_max": 100.0,"faixa": "azul"},
    {"nome": "Senior M +100kg","sexo": "M", "idade_min": 15, "idade_max": 99, "peso_min": 100.0,"peso_max": None, "faixa": "azul"},
    {"nome": "Senior F -48kg", "sexo": "F", "idade_min": 15, "idade_max": 99, "peso_min": None, "peso_max": 48.0, "faixa": "azul"},
    {"nome": "Senior F -52kg", "sexo": "F", "idade_min": 15, "idade_max": 99, "peso_min": 48.0, "peso_max": 52.0, "faixa": "azul"},
    {"nome": "Senior F -57kg", "sexo": "F", "idade_min": 15, "idade_max": 99, "peso_min": 52.0, "peso_max": 57.0, "faixa": "azul"},
    {"nome": "Senior F -63kg", "sexo": "F", "idade_min": 15, "idade_max": 99, "peso_min": 57.0, "peso_max": 63.0, "faixa": "azul"},
    {"nome": "Senior F -70kg", "sexo": "F", "idade_min": 15, "idade_max": 99, "peso_min": 63.0, "peso_max": 70.0, "faixa": "azul"},
    {"nome": "Senior F -78kg", "sexo": "F", "idade_min": 15, "idade_max": 99, "peso_min": 70.0, "peso_max": 78.0, "faixa": "azul"},
    {"nome": "Senior F +78kg", "sexo": "F", "idade_min": 15, "idade_max": 99, "peso_min": 78.0, "peso_max": None, "faixa": "azul"},
]
