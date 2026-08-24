"""
Carteira (crédito) do aluno.

Usada quando um pagamento com confirmação automática (gateway) é cancelado: o
dinheiro já entrou, então o valor vira crédito na carteira do aluno e pode ser
usado para dar baixa em outras mensalidades.

Razão em `carteira_movimentos` (tipo 'credito'/'debito'); o saldo é a soma dos
créditos menos os débitos. Todas as funções recebem um cursor já aberto (para
participarem da mesma transação da baixa/cancelamento).
"""


def saldo_aluno(cur, aluno_id):
    """Saldo atual da carteira do aluno (créditos - débitos). 0.0 se vazio."""
    if not aluno_id:
        return 0.0
    try:
        cur.execute(
            """SELECT COALESCE(SUM(CASE WHEN tipo='credito' THEN valor ELSE -valor END), 0) AS saldo
               FROM carteira_movimentos WHERE aluno_id=%s""",
            (aluno_id,),
        )
        row = cur.fetchone()
    except Exception:
        return 0.0
    if row is None:
        return 0.0
    val = row.get("saldo") if isinstance(row, dict) else row[0]
    try:
        return round(float(val or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _movimento(cur, aluno_id, id_academia, tipo, valor, descricao=None,
               origem=None, origem_id=None, criado_por=None):
    valor = round(float(valor or 0), 2)
    if not aluno_id or valor <= 0 or tipo not in ("credito", "debito"):
        return False
    cur.execute(
        """INSERT INTO carteira_movimentos
             (aluno_id, id_academia, tipo, valor, descricao, origem, origem_id, criado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (aluno_id, id_academia, tipo, valor, (descricao or "")[:255], origem, origem_id, criado_por),
    )
    return True


def creditar(cur, aluno_id, id_academia, valor, descricao=None, origem=None, origem_id=None, criado_por=None):
    """Adiciona crédito à carteira do aluno."""
    return _movimento(cur, aluno_id, id_academia, "credito", valor, descricao, origem, origem_id, criado_por)


def debitar(cur, aluno_id, id_academia, valor, descricao=None, origem=None, origem_id=None, criado_por=None):
    """Debita da carteira do aluno (não valida saldo — quem chama garante)."""
    return _movimento(cur, aluno_id, id_academia, "debito", valor, descricao, origem, origem_id, criado_por)


def saldos_por_aluno(cur, aluno_ids):
    """Saldo de vários alunos de uma vez: {aluno_id: saldo}. Só retorna quem tem saldo != 0."""
    if not aluno_ids:
        return {}
    ph = ",".join(["%s"] * len(aluno_ids))
    try:
        cur.execute(
            f"""SELECT aluno_id, COALESCE(SUM(CASE WHEN tipo='credito' THEN valor ELSE -valor END),0) AS saldo
                FROM carteira_movimentos WHERE aluno_id IN ({ph}) GROUP BY aluno_id""",
            tuple(aluno_ids),
        )
        rows = cur.fetchall()
    except Exception:
        return {}
    out = {}
    for r in rows:
        aid = r.get("aluno_id") if isinstance(r, dict) else r[0]
        val = r.get("saldo") if isinstance(r, dict) else r[1]
        try:
            s = round(float(val or 0), 2)
        except (TypeError, ValueError):
            s = 0.0
        if abs(s) > 0.001:
            out[int(aid)] = s
    return out
