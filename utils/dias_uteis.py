# -*- coding: utf-8 -*-
"""Dias úteis para cobrança: sábado, domingo e feriado não contam como atraso.

Duas regras, as duas pedidas pela academia:

  1. O vencimento que cai em sábado, domingo ou feriado "anda" para o próximo dia
     útil — como no boleto, ninguém paga no dia em que o banco não compensa.
  2. Os juros contam só DIAS ÚTEIS. Quem vence numa sexta e paga na segunda deve
     um dia de juros, não três: o fim de semana não é atraso.

A segunda é mais generosa que a praxe bancária (que cobra em dias corridos), e é
uma escolha da academia — está aqui em vez de espalhada pelo cálculo justamente
para poder mudar num lugar só.

Os feriados saem do próprio calendário do sistema (`eventos` com `tipo='feriado'`
e `feriado_nacional=1`) — os que a academia cadastra para si, como recesso, não
entram: fechar o tatame não fecha o banco.

O conjunto é lido uma vez por ano e guardado em memória por algumas horas: são
poucas datas e a consulta rodaria em cada linha de cada listagem de mensalidades.
"""
import logging
import threading
import time
from datetime import date, timedelta

from config import get_db_connection

logger = logging.getLogger(__name__)

# Cache por ano. Os feriados de um ano não mudam depois de cadastrados; o TTL
# existe só para o worker enxergar um feriado incluído com o sistema no ar.
_TTL_SEGUNDOS = 6 * 60 * 60
_cache = {}
_lock = threading.Lock()

# Sem nenhum feriado cadastrado no ano, ainda sobra a regra do fim de semana.
_SEM_FERIADOS = frozenset()


def feriados_do_ano(ano):
    """Datas de feriado nacional no ano, do calendário do sistema."""
    agora = time.time()
    with _lock:
        item = _cache.get(ano)
        if item and agora - item[0] < _TTL_SEGUNDOS:
            return item[1]

    datas = set()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT DISTINCT data_inicio, data_fim FROM eventos
                   WHERE tipo = 'feriado' AND COALESCE(feriado_nacional, 0) = 1
                     AND COALESCE(status, 'ativo') = 'ativo'
                     AND (YEAR(data_inicio) = %s OR YEAR(COALESCE(data_fim, data_inicio)) = %s)""",
                (ano, ano),
            )
            for ini, fim in cur.fetchall() or []:
                if not ini:
                    continue
                atual, ultimo = ini, (fim or ini)
                # Feriado prolongado vem como intervalo: cada dia dele conta.
                while atual <= ultimo:
                    if atual.year == ano:
                        datas.add(atual)
                    atual += timedelta(days=1)
        finally:
            cur.close()
            conn.close()
    except Exception:
        logger.exception("Não deu para carregar os feriados de %s", ano)
        datas = set(_SEM_FERIADOS)

    congelado = frozenset(datas)
    with _lock:
        _cache[ano] = (agora, congelado)
    return congelado


def eh_dia_util(d):
    """False em sábado, domingo e feriado nacional."""
    if d is None:
        return False
    if d.weekday() >= 5:  # 5 = sábado, 6 = domingo
        return False
    return d not in feriados_do_ano(d.year)


def proximo_dia_util(d, limite=15):
    """Primeiro dia útil a partir de `d` (o próprio, se já for útil).

    `limite` é uma trava: se o calendário estiver estranho (feriado cadastrado
    errado num intervalo enorme), a função para em vez de girar sem fim.
    """
    if d is None:
        return None
    atual = d
    for _ in range(limite):
        if eh_dia_util(atual):
            return atual
        atual += timedelta(days=1)
    return atual


def vencimento_cobravel(venc):
    """Data a partir da qual a cobrança pode ser considerada atrasada.

    É o vencimento adiado para o próximo dia útil. Use como base do cálculo de
    juros e multa — nunca para exibir o vencimento ao aluno, que continua sendo
    a data combinada.
    """
    return proximo_dia_util(venc)


def feriados_entre(inicio, fim):
    """Feriados nacionais no intervalo [inicio, fim], atravessando a virada do ano."""
    if not inicio or not fim or fim < inicio:
        return frozenset()
    datas = set()
    for ano in range(inicio.year, fim.year + 1):
        datas |= {d for d in feriados_do_ano(ano) if inicio <= d <= fim}
    return frozenset(datas)


def dias_uteis_entre(inicio, fim):
    """Dias úteis em (inicio, fim] — o dia inicial não conta, o final sim.

    Não percorre dia a dia: um atraso de meses viraria centenas de iterações em
    cada linha de cada listagem de mensalidades. Todo bloco de 7 dias corridos tem
    exatamente 5 dias de semana, então só a sobra é percorrida; os feriados que
    caem em dia de semana são descontados no fim.
    """
    if not inicio or not fim or fim <= inicio:
        return 0
    corridos = (fim - inicio).days
    semanas, resto = divmod(corridos, 7)
    uteis = semanas * 5
    d = inicio + timedelta(days=semanas * 7)
    for _ in range(resto):
        d += timedelta(days=1)
        if d.weekday() < 5:
            uteis += 1
    # Feriado em fim de semana já não estava contado.
    for f in feriados_entre(inicio + timedelta(days=1), fim):
        if f.weekday() < 5:
            uteis -= 1
    return max(uteis, 0)


def dias_de_atraso(venc, hoje=None):
    """Dias ÚTEIS de atraso, a partir do vencimento já ajustado para dia útil.

    Devolve 0 enquanto estiver dentro do prazo — inclusive no fim de semana ou
    feriado em que o vencimento caiu, e no fim de semana seguinte a ele.
    """
    if not venc:
        return 0
    hoje = hoje or date.today()
    base = vencimento_cobravel(venc)
    if not base or hoje <= base:
        return 0
    return dias_uteis_entre(base, hoje)
