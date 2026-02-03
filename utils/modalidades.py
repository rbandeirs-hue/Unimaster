# -*- coding: utf-8 -*-
"""
Filtro de visibilidade para modalidades.
Pública: todas associações e academias veem.
Privada associação: só a associação dona vê (id_associacao set, id_academia NULL).
Privada academia: só a academia dona vê (id_academia set) — associação NÃO vê.
"""


def filtro_visibilidade_sql(id_associacao=None, id_academia=None, prefix="m"):
    """
    Retorna (clausula_where, params) para filtrar modalidades por visibilidade.
    prefix: alias da tabela modalidade (ex: "m" ou "modalidade")
    """
    p = prefix
    if id_academia is not None and id_associacao is not None:
        return (
            f" AND (COALESCE({p}.visibilidade,'publica')='publica' OR "
            f"({p}.visibilidade='privada' AND ({p}.id_academia=%s OR {p}.id_associacao=%s)))",
            (id_academia, id_associacao)
        )
    elif id_associacao is not None:
        # Associação: não vê modalidades restritas a academia (id_academia set)
        return (
            f" AND (COALESCE({p}.visibilidade,'publica')='publica' OR "
            f"({p}.visibilidade='privada' AND {p}.id_associacao=%s AND ({p}.id_academia IS NULL OR {p}.id_academia = 0)))",
            (id_associacao,)
        )
    return "", ()
