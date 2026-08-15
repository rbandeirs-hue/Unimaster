# -*- coding: utf-8 -*-
"""
Geração de chave eliminatória (mata-mata) para judô.
Monta rodadas (1ª rodada, semifinal, final) com ligações entre lutas.
"""
import random


def gerar_chave_eliminatoria(cur, conn, evento_id, cat_id, categoria_nome, inscritos_cat):
    """
    Gera chave eliminatória: 1ª rodada -> semifinal -> final, com luta_origem_branco_id / luta_origem_azul_id.
    inscritos_cat: list of {"nome": str, "academia": str}
    Retorna (total_lutas_criadas, mensagem).
    """
    if len(inscritos_cat) < 2:
        return 0, "Mínimo 2 inscritos."

    random.shuffle(inscritos_cat)
    n = len(inscritos_cat)

    # 1ª rodada: ceil(n/2) lutas (pares 1-2, 3-4, ...; ímpar = bye)
    ids_por_rodada = []  # ids_por_rodada[r] = list of fight ids in round r (0-indexed)
    round_atual = 1
    posicao = 0
    # Slots para esta rodada: cada "slot" é um atleta ou bye; lutas consomem 2 slots
    participantes = list(inscritos_cat)  # copy

    def insere_luta(atleta_branco_nome, atleta_branco_academia, atleta_azul_nome, atleta_azul_academia,
                    round_num, pos, luta_origem_branco_id=None, luta_origem_azul_id=None):
        cur.execute("""
            INSERT INTO judo_lutas (evento_id, categoria_id, categoria_nome,
             atleta_branco_nome, atleta_branco_academia, atleta_azul_nome, atleta_azul_academia,
             round, posicao_rodada, luta_origem_branco_id, luta_origem_azul_id,
             status, tempo_total_segundos, tempo_restante_segundos)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'aguardando', 300, 300)
        """, (
            evento_id, cat_id, categoria_nome,
            atleta_branco_nome or "?", atleta_branco_academia or "-",
            atleta_azul_nome or "?", atleta_azul_academia or "-",
            round_num, pos, luta_origem_branco_id, luta_origem_azul_id
        ))
        return cur.lastrowid

    # Rodada 1: criar lutas (0,1), (2,3), (4,5)...
    ids_r1 = []
    for i in range(0, n, 2):
        posicao += 1
        a1 = participantes[i] if i < n else {"nome": "BYE", "academia": "-"}
        a2 = participantes[i + 1] if i + 1 < n else {"nome": "BYE", "academia": "-"}
        if a1["nome"] == "BYE" and a2["nome"] == "BYE":
            continue
        lid = insere_luta(
            a1["nome"], a1["academia"],
            a2["nome"], a2["academia"],
            round_atual, posicao, None, None
        )
        ids_r1.append(lid)
    ids_por_rodada.append(ids_r1)

    # Rodadas seguintes: cada luta é "vencedor da X" vs "vencedor da Y"
    rodada_ids = ids_r1
    round_atual = 2
    while len(rodada_ids) > 1:
        posicao = 0
        proxima_rodada = []
        for j in range(0, len(rodada_ids), 2):
            posicao += 1
            id_b = rodada_ids[j]
            id_a = rodada_ids[j + 1] if j + 1 < len(rodada_ids) else None
            lb = f"Vencedor Luta {id_b}"
            la = f"Vencedor Luta {id_a}" if id_a else "BYE"
            lid = insere_luta(lb, "-", la, "-", round_atual, posicao, id_b, id_a)
            proxima_rodada.append(lid)
        ids_por_rodada.append(proxima_rodada)
        rodada_ids = proxima_rodada
        round_atual += 1

    conn.commit()
    total = sum(len(ids) for ids in ids_por_rodada)
    byes = 1 if n % 2 else 0
    msg = f"Chave eliminatória: {total} luta(s) ({len(ids_r1)} na 1ª rodada"
    if len(ids_por_rodada) > 1:
        msg += f", semifinal e final"
    msg += f") para {categoria_nome}."
    if byes:
        msg += " 1 atleta com bye."
    return total, msg
