# -*- coding: utf-8 -*-
"""Módulos ligados/desligados por academia.

Hoje só o financeiro: a academia pode usar o sistema para o acadêmico (alunos,
turmas, presença, graduação) e manter a cobrança por fora. Com o módulo
desligado, o menu perde a seção e as rotas do financeiro recusam o acesso — não
basta esconder o botão, porque a URL continua sendo digitável.

O resultado fica em cache por alguns minutos: é consultado no menu de toda
página e na entrada de cada rota financeira.
"""
import threading
import time

from config import get_db_connection

_TTL_SEGUNDOS = 300
_cache = {}
_lock = threading.Lock()


def _consultar(academia_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COALESCE(modulo_financeiro, 1) FROM academias WHERE id = %s",
            (academia_id,),
        )
        r = cur.fetchone()
        return bool(r[0]) if r else True
    finally:
        cur.close()
        conn.close()


def tem_financeiro(academia_id):
    """True se a academia gere financeiro além do acadêmico.

    Sem academia definida, devolve True: quem ainda não escolheu academia não
    pode ser barrado por uma configuração que não existe para ele. A trava real
    acontece dentro da rota, onde a academia já está resolvida.
    """
    if not academia_id:
        return True
    agora = time.time()
    with _lock:
        item = _cache.get(academia_id)
        if item and agora - item[0] < _TTL_SEGUNDOS:
            return item[1]
    try:
        valor = _consultar(academia_id)
    except Exception:
        # Banco fora ou coluna ainda não migrada: não é hora de tirar o
        # financeiro de quem usa. O padrão é permitir.
        valor = True
    with _lock:
        _cache[academia_id] = (agora, valor)
    return valor


def invalidar(academia_id=None):
    """Esquece o cache — chamado ao salvar as configurações da academia."""
    with _lock:
        if academia_id is None:
            _cache.clear()
        else:
            _cache.pop(academia_id, None)
