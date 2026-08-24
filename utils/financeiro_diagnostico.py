"""Diagnóstico dos dados financeiros já existentes.

O item 23 do plano: antes de ligar o Controle Total é preciso saber o que há
de inconsistente no que já está gravado. Nada aqui altera dados — só apura e
devolve o relatório, para a decisão ser tomada com número na mão.
"""

from config import get_db_connection


def diagnosticar(id_academia):
    """Levanta as pendências que impedem o financeiro de ser fiel à realidade."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        achados = []

        def apurar(chave, titulo, sql, args, explicacao, bloqueia=True):
            cur.execute(sql, args)
            linha = cur.fetchone()
            qtd = int(linha["n"] or 0)
            valor = float(linha.get("v") or 0)
            if qtd:
                achados.append({"chave": chave, "titulo": titulo, "quantidade": qtd,
                                "valor": valor, "explicacao": explicacao,
                                "bloqueia": bloqueia})

        # Sem conta financeira não há como dizer ONDE o dinheiro está — é o
        # dado que falta em todo pagamento anterior ao módulo novo.
        apurar("receitas_sem_lancamento",
               "Receitas ainda fora do razão",
               """SELECT COUNT(*) n, COALESCE(SUM(valor),0) v FROM receitas
                  WHERE id_academia = %s AND COALESCE(cancelada,0) = 0
                    AND id_lancamento IS NULL""",
               (id_academia,),
               "Cada uma precisa ser atribuída a uma conta financeira para entrar no saldo.")

        apurar("despesas_sem_lancamento",
               "Despesas ainda fora do razão",
               """SELECT COUNT(*) n, COALESCE(SUM(valor),0) v FROM despesas
                  WHERE id_academia = %s AND id_lancamento IS NULL""",
               (id_academia,),
               "Idem: sem conta de saída, o saldo não fecha com a realidade.")

        apurar("receitas_sem_forma",
               "Receitas sem forma de pagamento",
               """SELECT COUNT(*) n, COALESCE(SUM(valor),0) v FROM receitas
                  WHERE id_academia = %s AND COALESCE(cancelada,0) = 0
                    AND id_forma_pagamento IS NULL""",
               (id_academia,),
               "Sem a forma não dá para inferir a conta de destino automaticamente.",
               bloqueia=False)

        # Só conta como dinheiro sumido quando houve valor. Mensalidade paga de
        # valor zero (isenção, plano gratuito) não gera entrada de caixa — a
        # primeira versão desta checagem não separava as duas coisas e acusava
        # como "dinheiro que não aparece" três linhas de R$ 0,00.
        apurar("pagas_sem_receita",
               "Mensalidades pagas com valor e sem receita",
               """SELECT COUNT(*) n, COALESCE(SUM(ma.valor_pago),0) v
                  FROM mensalidade_aluno ma
                  JOIN alunos a ON a.id = ma.aluno_id
                  LEFT JOIN receitas r ON r.id_mensalidade_aluno = ma.id
                  WHERE a.id_academia = %s AND ma.status = 'pago' AND r.id IS NULL
                    AND COALESCE(ma.valor_pago, ma.valor) > 0""",
               (id_academia,),
               "Dinheiro que entrou e não aparece em lugar nenhum do financeiro.")

        apurar("pagas_zeradas_sem_receita",
               "Mensalidades isentas (R$ 0,00) sem receita",
               """SELECT COUNT(*) n, 0 v
                  FROM mensalidade_aluno ma
                  JOIN alunos a ON a.id = ma.aluno_id
                  LEFT JOIN receitas r ON r.id_mensalidade_aluno = ma.id
                  WHERE a.id_academia = %s AND ma.status = 'pago' AND r.id IS NULL
                    AND COALESCE(ma.valor_pago, ma.valor) = 0""",
               (id_academia,),
               "Não movimentam caixa; ficam de fora do razão sem prejuízo ao saldo.",
               bloqueia=False)

        apurar("receita_orfa",
               "Receitas de mensalidade órfãs",
               """SELECT COUNT(*) n, COALESCE(SUM(r.valor),0) v
                  FROM receitas r
                  LEFT JOIN mensalidade_aluno ma ON ma.id = r.id_mensalidade_aluno
                  WHERE r.id_academia = %s AND r.id_mensalidade_aluno IS NOT NULL
                    AND ma.id IS NULL""",
               (id_academia,),
               "Apontam para uma mensalidade que não existe mais.")

        apurar("pago_sem_data",
               "Mensalidades pagas sem data de pagamento",
               """SELECT COUNT(*) n, COALESCE(SUM(valor),0) v
                  FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                  WHERE a.id_academia = %s AND ma.status = 'pago'
                    AND ma.data_pagamento IS NULL""",
               (id_academia,),
               "Sem a data não há em que dia lançar a entrada no extrato.")

        apurar("valor_divergente",
               "Mensalidades pagas com valor divergente da receita",
               """SELECT COUNT(*) n, COALESCE(SUM(ABS(ma.valor_pago - r.valor)),0) v
                  FROM mensalidade_aluno ma
                  JOIN alunos a ON a.id = ma.aluno_id
                  JOIN receitas r ON r.id_mensalidade_aluno = ma.id
                  WHERE a.id_academia = %s AND ma.status = 'pago'
                    AND ma.valor_pago IS NOT NULL
                    AND ABS(ma.valor_pago - r.valor) > 0.01""",
               (id_academia,),
               "A mensalidade e a receita registram valores diferentes.")

        cur.execute("SELECT COUNT(*) n FROM fin_contas WHERE id_academia = %s AND ativo = 1",
                    (id_academia,))
        contas = int(cur.fetchone()["n"] or 0)
        if not contas:
            achados.insert(0, {
                "chave": "sem_contas", "titulo": "Nenhuma conta financeira cadastrada",
                "quantidade": 0, "valor": 0,
                "explicacao": "O modo Total exige ao menos uma conta — é onde o dinheiro fica.",
                "bloqueia": True})

        bloqueios = [a for a in achados if a["bloqueia"]]
        return {
            "achados": achados,
            "bloqueios": bloqueios,
            "contas_cadastradas": contas,
            "pode_ativar_total": not bloqueios,
        }
    finally:
        cur.close()
        conn.close()
