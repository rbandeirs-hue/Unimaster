# -*- coding: utf-8 -*-
"""Quais itens do menu cada modalidade mostra.

O problema que isto resolve
---------------------------
"Isto é do judô" estava escrito dentro de `utils/menu.py`: o código olhava se o
nome da modalidade continha "jud" e escondia Zempo, Locais de treino, Currículo
e os simuladores. Funcionava, mas cada combinação nova — tirar Eventos do
jiu-jitsu, devolver Modalidades para a ginástica — exigia mexer em código.

Agora a exceção é dado. A tabela `modalidade_menu` guarda apenas o que foge do
padrão:

    (modalidade_id, modo, item_chave, ativo)

Precedência, e é só isto:

  1. existe linha para (modalidade, modo, chave)  → ela manda;
  2. não existe                                   → vale a regra do código.

Ou seja, ligar explicitamente vence até o que o código esconderia, e uma tabela
vazia deixa o sistema exatamente como era antes de MM-09.

Quando a academia tem mais de uma modalidade em jogo, o item aparece se
**alguma** delas o mostra. Esconder Eventos de quem dá judô e jiu-jitsu porque
o jiu-jitsu não usa seria tirar do judô uma tela que ele usa. Com o contexto de
modalidade escolhido, só ele está em jogo — e aí o recorte é exato.
"""
import threading
import time

from config import get_db_connection

# Modos com modalidade determinável. Admin, federação e associação estão acima
# da modalidade: filtrar o menu deles por uma delas não faria sentido.
MODOS = ("academia", "professor", "aluno", "responsavel")

# 60s, e não os 300s do cache de modalidades: `invalidar()` só limpa o cache do
# worker que gravou, e são três workers em produção. Um minuto é o pior atraso
# possível entre salvar a tela e os outros workers enxergarem a mudança; a
# tabela é pequena e a consulta, barata.
_TTL_SEGUNDOS = 60
_cache = {"carregado_em": 0.0, "regras": {}}
_lock = threading.Lock()


def _consultar():
    """{(modalidade_id, modo, chave): bool} — a tabela inteira; ela é pequena."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT modalidade_id, modo, item_chave, ativo
                       FROM modalidade_menu""")
        return {(int(mid), modo, chave): bool(ativo)
                for mid, modo, chave, ativo in cur.fetchall() or []}
    finally:
        cur.close()
        conn.close()


def _regras():
    agora = time.time()
    with _lock:
        if agora - _cache["carregado_em"] < _TTL_SEGUNDOS:
            return _cache["regras"]
    try:
        regras = _consultar()
    except Exception:
        # Tabela ausente (MM-09 não aplicada) ou banco fora: sem exceções, o
        # menu segue o código. Nunca esconder por causa de uma falha de leitura.
        regras = {}
    with _lock:
        _cache["carregado_em"] = agora
        _cache["regras"] = regras
    return regras


def invalidar():
    with _lock:
        _cache["carregado_em"] = 0.0
        _cache["regras"] = {}


def decisoes(modo, modalidade_ids):
    """(ligados, desligados): chaves com decisão explícita para essas modalidades.

    `ligados`: alguma modalidade em jogo pediu o item — ele aparece, mesmo que
    o código o escondesse.

    `desligados`: **todas** as modalidades em jogo desligaram o item. Basta uma
    delas não ter linha para o item voltar a seguir o código: numa academia de
    judô e jiu-jitsu, "Eventos" desligado só no jiu-jitsu não pode sumir, ou o
    judô perderia uma tela que usa.
    """
    ids = {int(i) for i in (modalidade_ids or []) if i}
    if not ids or modo not in MODOS:
        return set(), set()
    por_chave = {}
    for (mid, m, chave), ativo in _regras().items():
        if m != modo or mid not in ids:
            continue
        por_chave.setdefault(chave, {})[mid] = ativo
    ligados, desligados = set(), set()
    for chave, estados in por_chave.items():
        if any(estados.values()):
            ligados.add(chave)
        elif len(estados) == len(ids):
            desligados.add(chave)
    return ligados, desligados


def estado(modalidade_id, modo, item_chave):
    """True/False quando há decisão explícita, None quando vale o código."""
    if not modalidade_id:
        return None
    return _regras().get((int(modalidade_id), modo, item_chave))


def definir(modalidade_id, modo, item_chave, ativo):
    """Grava a exceção. `ativo` None apaga a linha e devolve o item ao código."""
    if modo not in MODOS or not modalidade_id or not item_chave:
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if ativo is None:
            cur.execute("""DELETE FROM modalidade_menu
                           WHERE modalidade_id = %s AND modo = %s AND item_chave = %s""",
                        (modalidade_id, modo, item_chave))
        else:
            cur.execute("""INSERT INTO modalidade_menu
                           (modalidade_id, modo, item_chave, ativo)
                           VALUES (%s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE ativo = VALUES(ativo)""",
                        (modalidade_id, modo, item_chave, 1 if ativo else 0))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()
        invalidar()
