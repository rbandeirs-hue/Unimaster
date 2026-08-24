# =====================================================================
# OPCIONAL — contadores da faixa "Precisa da sua atenção".
# Cole dentro de blueprints/academia/routes.py, na função painel_academia(),
# ANTES do return render_template(...), e acrescente as chaves no render.
# Sem isso a página funciona igual, só mostra aniversariantes e Zempo.
# =====================================================================

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # total de alunos ativos e turmas (subtítulo do cabeçalho)
    cur.execute("SELECT COUNT(*) AS n FROM alunos WHERE id_academia = %s AND ativo = 1", (academia_id,))
    total_alunos = (cur.fetchone() or {}).get("n", 0)

    cur.execute("SELECT COUNT(*) AS n FROM turmas WHERE id_academia = %s", (academia_id,))
    total_turmas = (cur.fetchone() or {}).get("n", 0)

    # mensalidades em atraso
    cur.execute(
        """SELECT COUNT(*) AS n
             FROM mensalidades_alunos ma
             JOIN alunos a ON a.id = ma.aluno_id
            WHERE a.id_academia = %s
              AND ma.status IN ('pendente', 'atrasado')
              AND ma.data_vencimento < CURDATE()""",
        (academia_id,))
    mensalidades_atrasadas = (cur.fetchone() or {}).get("n", 0)

    # pre-cadastros ainda nao convertidos
    cur.execute(
        "SELECT COUNT(*) AS n FROM precadastros WHERE id_academia = %s AND (aluno_id IS NULL OR aluno_id = 0)",
        (academia_id,))
    precadastros_pendentes = (cur.fetchone() or {}).get("n", 0)

    # solicitacoes pendentes de aprovacao
    cur.execute(
        "SELECT COUNT(*) AS n FROM solicitacoes_aprovacao WHERE academia_id = %s AND status = 'pendente'",
        (academia_id,))
    solicitacoes_pendentes = (cur.fetchone() or {}).get("n", 0)

    cur.close()
    conn.close()

# ...e no render_template acrescente:
#     total_alunos=total_alunos,
#     total_turmas=total_turmas,
#     mensalidades_atrasadas=mensalidades_atrasadas,
#     precadastros_pendentes=precadastros_pendentes,
#     solicitacoes_pendentes=solicitacoes_pendentes,
#
# ATENCAO: confira os nomes de tabela/coluna no seu schema
# (mensalidades_alunos, precadastros, solicitacoes_aprovacao) antes de rodar.
