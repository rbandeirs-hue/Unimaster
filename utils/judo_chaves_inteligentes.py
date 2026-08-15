# -*- coding: utf-8 -*-
"""
Chaves inteligentes por quantidade de atletas:
- 2 atletas: melhor de 3 (lutas criadas sob demanda após cada resultado)
- 3 a 5: todos contra todos (combinações únicas)
- 6 a 8: eliminatória + repescagem (modelo 8 com BYE se necessário) + duas disputas de 3º
- 9+: eliminatória simples (judo_bracket.gerar_chave_eliminatoria) sem repescagem automática nesta versão
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple


def modo_por_n(n: int) -> str:
    if n == 2:
        return "bo3"
    if 3 <= n <= 5:
        return "round_robin"
    if n >= 6:
        return "elim_rep"
    return "invalido"


def _norm(a: Dict[str, Any]) -> Tuple[str, str]:
    return (a.get("nome") or "?").strip(), (a.get("academia") or "-").strip() or "-"


def _insert_luta(
    cur,
    evento_id: int,
    cat_id: Optional[int],
    cat_nome: str,
    nb: str,
    ab: str,
    na: str,
    aa: str,
    round_num: int,
    pos: int,
    lorig_b: Optional[int] = None,
    lorig_a: Optional[int] = None,
    chave_sistema: Optional[str] = None,
    chave_fase: Optional[str] = None,
    bo3_serie_id: Optional[int] = None,
) -> int:
    """INSERT judo_lutas; tenta colunas extras da migração add_chave_inteligente_judo.sql."""
    try:
        cur.execute(
            """
            INSERT INTO judo_lutas (
                evento_id, categoria_id, categoria_nome,
                atleta_branco_nome, atleta_branco_academia, atleta_azul_nome, atleta_azul_academia,
                round, posicao_rodada, luta_origem_branco_id, luta_origem_azul_id,
                chave_sistema, chave_fase, bo3_serie_id,
                status, tempo_total_segundos, tempo_restante_segundos
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'aguardando',300,300)
            """,
            (
                evento_id,
                cat_id,
                cat_nome,
                nb,
                ab,
                na,
                aa,
                round_num,
                pos,
                lorig_b,
                lorig_a,
                chave_sistema,
                chave_fase,
                bo3_serie_id,
            ),
        )
    except Exception:
        cur.execute(
            """
            INSERT INTO judo_lutas (
                evento_id, categoria_id, categoria_nome,
                atleta_branco_nome, atleta_branco_academia, atleta_azul_nome, atleta_azul_academia,
                round, posicao_rodada, luta_origem_branco_id, luta_origem_azul_id,
                status, tempo_total_segundos, tempo_restante_segundos
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'aguardando',300,300)
            """,
            (
                evento_id,
                cat_id,
                cat_nome,
                nb,
                ab,
                na,
                aa,
                round_num,
                pos,
                lorig_b,
                lorig_a,
            ),
        )
    return cur.lastrowid


def _add_feed(cur, destino_id: int, lado: str, tipo: str, origem_id: int) -> None:
    try:
        cur.execute(
            """
            INSERT INTO judo_chave_feed (destino_luta_id, destino_lado, tipo, origem_luta_id)
            VALUES (%s,%s,%s,%s)
            """,
            (destino_id, lado, tipo, origem_id),
        )
    except Exception:
        pass


def gerar_round_robin(
    cur, conn, evento_id: int, cat_id: Optional[int], cat_nome: str, atletas: List[Dict[str, Any]]
) -> Tuple[int, str]:
    n = len(atletas)
    pairs: List[Tuple[int, int]] = [(i, j) for i in range(n) for j in range(i + 1, n)]
    pos = 0
    for i, j in pairs:
        pos += 1
        ai, aj = atletas[i], atletas[j]
        nbi, abi = _norm(ai)
        naj, aaj = _norm(aj)
        _insert_luta(
            cur,
            evento_id,
            cat_id,
            cat_nome,
            nbi,
            abi,
            naj,
            aaj,
            1,
            pos,
            None,
            None,
            "round_robin",
            "todos_contra_todos",
            None,
        )
    conn.commit()
    esperado = n * (n - 1) // 2
    return pos, f"Round Robin: {pos} luta(s) ({esperado} obrigatórias) — {cat_nome}."


def gerar_bo3(
    cur, conn, evento_id: int, cat_id: Optional[int], cat_nome: str, atletas: List[Dict[str, Any]]
) -> Tuple[int, str]:
    if len(atletas) != 2:
        return 0, "Melhor de 3 exige exatamente 2 atletas."
    a0, a1 = atletas[0], atletas[1]
    n0, ac0 = _norm(a0)
    n1, ac1 = _norm(a1)
    sid = None
    try:
        cur.execute(
            """
            INSERT INTO judo_bo3_series (
                evento_id, categoria_id, categoria_nome,
                atleta_a_nome, atleta_a_academia, atleta_b_nome, atleta_b_academia,
                vitorias_a, vitorias_b, concluido
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,0,0,0)
            """,
            (evento_id, cat_id, cat_nome, n0, ac0, n1, ac1),
        )
        sid = cur.lastrowid
    except Exception:
        sid = None
    lid = _insert_luta(
        cur,
        evento_id,
        cat_id,
        cat_nome,
        n0,
        ac0,
        n1,
        ac1,
        1,
        1,
        None,
        None,
        "bo3",
        "melhor_de_3_jogo_1",
        sid,
    )
    conn.commit()
    return 1, (
        f"Melhor de 3: criada apenas a 1ª luta (#{lid}). "
        f"As próximas serão geradas automaticamente até alguém atingir 2 vitórias — {cat_nome}."
    )


def _pad8(atletas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = list(atletas)
    while len(out) < 8:
        out.append({"nome": "BYE", "academia": "-"})
    random.shuffle(out)
    return out[:8]


def gerar_eliminatoria_8_com_repescagem(
    cur, conn, evento_id: int, cat_id: Optional[int], cat_nome: str, atletas: List[Dict[str, Any]]
) -> Tuple[int, str]:
    """
    8 posições (BYE permitido). Quartas → semis → final + repescagem (perdedores QF do mesmo bloco)
    e duas disputas de 3º (perdedor SF vs vencedor rep do bloco).
    """
    p8 = _pad8(atletas)
    # QF
    lids_qf = []
    pos = 0
    for i in range(0, 8, 2):
        pos += 1
        a, b = p8[i], p8[i + 1]
        nb, ab = _norm(a)
        na, aa = _norm(b)
        lid = _insert_luta(
            cur,
            evento_id,
            cat_id,
            cat_nome,
            nb,
            ab,
            na,
            aa,
            1,
            pos,
            None,
            None,
            "elim_rep",
            "principal_quartas",
            None,
        )
        lids_qf.append(lid)
    L1, L2, L3, L4 = lids_qf
    # SF
    SF1 = _insert_luta(
        cur,
        evento_id,
        cat_id,
        cat_nome,
        f"Vencedor Luta {L1}",
        "-",
        f"Vencedor Luta {L2}",
        "-",
        2,
        1,
        L1,
        L2,
        "elim_rep",
        "principal_semifinal",
        None,
    )
    SF2 = _insert_luta(
        cur,
        evento_id,
        cat_id,
        cat_nome,
        f"Vencedor Luta {L3}",
        "-",
        f"Vencedor Luta {L4}",
        "-",
        2,
        2,
        L3,
        L4,
        "elim_rep",
        "principal_semifinal",
        None,
    )
    F = _insert_luta(
        cur,
        evento_id,
        cat_id,
        cat_nome,
        f"Vencedor Luta {SF1}",
        "-",
        f"Vencedor Luta {SF2}",
        "-",
        3,
        1,
        SF1,
        SF2,
        "elim_rep",
        "principal_final",
        None,
    )
    # Repescagem: perdedores do mesmo par de quartas que alimentam cada semi
    R1 = _insert_luta(
        cur,
        evento_id,
        cat_id,
        cat_nome,
        f"Perdedor Luta {L1}",
        "-",
        f"Perdedor Luta {L2}",
        "-",
        2,
        3,
        None,
        None,
        "elim_rep",
        "repescagem_semifinal",
        None,
    )
    R2 = _insert_luta(
        cur,
        evento_id,
        cat_id,
        cat_nome,
        f"Perdedor Luta {L3}",
        "-",
        f"Perdedor Luta {L4}",
        "-",
        2,
        4,
        None,
        None,
        "elim_rep",
        "repescagem_semifinal",
        None,
    )
    # Duas disputas de 3º lugar (bronze por bloco)
    B1 = _insert_luta(
        cur,
        evento_id,
        cat_id,
        cat_nome,
        f"Perdedor Luta {SF1}",
        "-",
        f"Vencedor Luta {R1}",
        "-",
        4,
        1,
        None,
        None,
        "elim_rep",
        "terceiro_lugar_bloco_1",
        None,
    )
    B2 = _insert_luta(
        cur,
        evento_id,
        cat_id,
        cat_nome,
        f"Perdedor Luta {SF2}",
        "-",
        f"Vencedor Luta {R2}",
        "-",
        4,
        2,
        None,
        None,
        "elim_rep",
        "terceiro_lugar_bloco_2",
        None,
    )

    # Feeds (duplicam lógica dos placeholders vencedor/perdedor para preenchimento automático)
    _add_feed(cur, SF1, "branco", "vencedor", L1)
    _add_feed(cur, SF1, "azul", "vencedor", L2)
    _add_feed(cur, SF2, "branco", "vencedor", L3)
    _add_feed(cur, SF2, "azul", "vencedor", L4)
    _add_feed(cur, F, "branco", "vencedor", SF1)
    _add_feed(cur, F, "azul", "vencedor", SF2)
    _add_feed(cur, R1, "branco", "perdedor", L1)
    _add_feed(cur, R1, "azul", "perdedor", L2)
    _add_feed(cur, R2, "branco", "perdedor", L3)
    _add_feed(cur, R2, "azul", "perdedor", L4)
    _add_feed(cur, B1, "branco", "perdedor", SF1)
    _add_feed(cur, B1, "azul", "vencedor", R1)
    _add_feed(cur, B2, "branco", "perdedor", SF2)
    _add_feed(cur, B2, "azul", "vencedor", R2)

    conn.commit()
    total = 11
    return total, (
        f"Chave eliminatória + repescagem (8 posições) + 2 disputas de 3º lugar — {total} lutas — {cat_nome}."
    )


def gerar_chave_inteligente(
    cur, conn, evento_id: int, cat_id: Optional[int], cat_nome: str, inscritos_cat: List[Dict[str, Any]]
) -> Tuple[int, str]:
    n = len(inscritos_cat)
    if n < 2:
        return 0, "Mínimo 2 inscritos."
    atletas = list(inscritos_cat)
    random.shuffle(atletas)
    modo = modo_por_n(n)
    if modo == "bo3":
        return gerar_bo3(cur, conn, evento_id, cat_id, cat_nome, atletas)
    if modo == "round_robin":
        return gerar_round_robin(cur, conn, evento_id, cat_id, cat_nome, atletas)
    if modo == "elim_rep":
        if n <= 8:
            return gerar_eliminatoria_8_com_repescagem(cur, conn, evento_id, cat_id, cat_nome, atletas)
        from utils.judo_bracket import gerar_chave_eliminatoria

        return gerar_chave_eliminatoria(cur, conn, evento_id, cat_id, cat_nome, atletas)
    return 0, "Modo inválido."


def limpar_bo3_series_categoria(cur, conn, evento_id: int, cat_nome: str) -> None:
    """Chamar após DELETE das lutas da categoria (feeds já removidos em cascata)."""
    try:
        cur.execute(
            "DELETE FROM judo_bo3_series WHERE evento_id = %s AND categoria_nome = %s",
            (evento_id, cat_nome),
        )
        conn.commit()
    except Exception:
        pass


def _nome_key(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def propagar_judo_chave_feeds(cur, luta_id: int) -> bool:
    """
    Preenche atletas nas lutas destino conforme judo_chave_feed (vencedor/perdedor).
    Retorna True se algum UPDATE foi aplicado.
    """
    cur.execute(
        """
        SELECT status, vencedor, atleta_branco_nome, atleta_branco_academia,
               atleta_azul_nome, atleta_azul_academia
        FROM judo_lutas WHERE id = %s
        """,
        (luta_id,),
    )
    row = cur.fetchone()
    if not row or row.get("status") != "finalizada" or row.get("vencedor") not in ("branco", "azul"):
        return False
    w_nome = row["atleta_branco_nome"] if row["vencedor"] == "branco" else row["atleta_azul_nome"]
    w_acad = (row["atleta_branco_academia"] if row["vencedor"] == "branco" else row["atleta_azul_academia"]) or "-"
    l_nome = row["atleta_azul_nome"] if row["vencedor"] == "branco" else row["atleta_branco_nome"]
    l_acad = (row["atleta_azul_academia"] if row["vencedor"] == "branco" else row["atleta_branco_academia"]) or "-"

    changed = False
    try:
        cur.execute("SELECT destino_luta_id, destino_lado, tipo FROM judo_chave_feed WHERE origem_luta_id = %s", (luta_id,))
        feeds = cur.fetchall()
        for f in feeds:
            tipo = f["tipo"]
            dest_id = f["destino_luta_id"]
            lado = f["destino_lado"]
            if tipo == "vencedor":
                nome, acad = w_nome, w_acad
            else:
                nome, acad = l_nome, l_acad
            if lado == "branco":
                cur.execute(
                    "UPDATE judo_lutas SET atleta_branco_nome = %s, atleta_branco_academia = %s WHERE id = %s",
                    (nome, acad or "-", dest_id),
                )
            else:
                cur.execute(
                    "UPDATE judo_lutas SET atleta_azul_nome = %s, atleta_azul_academia = %s WHERE id = %s",
                    (nome, acad or "-", dest_id),
                )
            if cur.rowcount:
                changed = True
    except Exception:
        pass
    return changed


def processar_bo3_apos_finalizacao(cur, conn, luta_id: int) -> None:
    """Atualiza série melhor-de-3; se ninguém chegou a 2 vitórias, cria a próxima luta."""
    cur.execute(
        """
        SELECT id, evento_id, categoria_id, categoria_nome, status, vencedor, chave_fase, chave_sistema,
               atleta_branco_nome, atleta_branco_academia, atleta_azul_nome, atleta_azul_academia,
               bo3_serie_id
        FROM judo_lutas WHERE id = %s
        """,
        (luta_id,),
    )
    row = cur.fetchone()
    if not row or row.get("status") != "finalizada" or row.get("vencedor") not in ("branco", "azul"):
        return
    sid = row.get("bo3_serie_id")
    if not sid or (row.get("chave_sistema") or "") != "bo3":
        return
    try:
        cur.execute("SELECT * FROM judo_bo3_series WHERE id = %s", (sid,))
        s = cur.fetchone()
    except Exception:
        return
    if not s or s.get("concluido"):
        return

    bn = _nome_key(row["atleta_branco_nome"])
    an_a = _nome_key(s["atleta_a_nome"])
    va = int(s["vitorias_a"] or 0)
    vb = int(s["vitorias_b"] or 0)
    if bn == an_a:
        if row["vencedor"] == "branco":
            va += 1
        else:
            vb += 1
    else:
        if row["vencedor"] == "branco":
            vb += 1
        else:
            va += 1

    concluido = 1 if va >= 2 or vb >= 2 else 0
    try:
        cur.execute(
            "UPDATE judo_bo3_series SET vitorias_a = %s, vitorias_b = %s, concluido = %s WHERE id = %s",
            (va, vb, concluido, sid),
        )
    except Exception:
        return

    if concluido:
        conn.commit()
        return

    chave_fase = row.get("chave_fase") or "melhor_de_3_jogo_1"
    m = re.search(r"jogo_(\d+)$", chave_fase)
    prox_jogo = (int(m.group(1)) + 1) if m else 2
    if prox_jogo > 3:
        conn.commit()
        return

    cur.execute(
        "SELECT COALESCE(MAX(posicao_rodada), 0) + 1 AS np FROM judo_lutas WHERE bo3_serie_id = %s",
        (sid,),
    )
    pr = cur.fetchone()
    if isinstance(pr, dict):
        pos = int(pr.get("np") or pr.get("NP") or 1)
    elif pr:
        pos = int(pr[0])
    else:
        pos = 1

    n0 = (s["atleta_a_nome"] or "?").strip()
    a0 = (s.get("atleta_a_academia") or "-").strip() or "-"
    n1 = (s["atleta_b_nome"] or "?").strip()
    a1 = (s.get("atleta_b_academia") or "-").strip() or "-"

    _insert_luta(
        cur,
        int(row["evento_id"]),
        row.get("categoria_id"),
        (row.get("categoria_nome") or "").strip() or "-",
        n0,
        a0,
        n1,
        a1,
        1,
        pos,
        None,
        None,
        "bo3",
        f"melhor_de_3_jogo_{prox_jogo}",
        sid,
    )
    conn.commit()
