# Leva 6 — Financeiro, Eventos, Calendário, Visitantes, Pré-cadastro, Usuários

Todos herdam de \`base_um2.html\` (entregue na leva 5). Se ainda não instalou
aquele arquivo, copie-o junto.

| Arquivo | Onde vai | Rota |
|---|---|---|
| \`templates/financeiro/painel_um.html\` | \`templates/financeiro/painel_um.html\` | \`financeiro_painel.dashboard\` |
| \`templates/eventos_competicoes/lista_academia.html\` | substitui o atual | \`eventos_competicoes.lista_academia\` |
| \`templates/calendario/visualizar.html\` | substitui o atual | \`calendario.visualizar\` |
| \`templates/visitantes/lista.html\` | substitui o atual | \`visitantes.lista\` |
| \`templates/precadastro/lista.html\` | substitui o atual | \`precadastro.lista\` |
| \`templates/academia/lista_usuarios.html\` | substitui o atual | \`academia.lista_usuarios\` |

## Financeiro — uma rota, sete abas

A tela lê \`?aba=\` (dashboard · mensalidades · planos · formas · descontos ·
cobrancas · historico) e só monta o bloco da aba ativa. Envie apenas o que a aba
precisa; o resto pode vir vazio.

\`\`\`python
aba = request.args.get("aba", "dashboard")
mes = int(request.args.get("mes", date.today().month))
ano = int(request.args.get("ano", date.today().year))

ctx = dict(
    aba=aba, mes=mes, ano=ano,
    mes_label=f"{MESES[mes-1]} de {ano}",
    meses_opcoes=list(enumerate(MESES, start=1)),
    anos_opcoes=range(ano - 2, ano + 1),

    # todas as abas usam a faixa de KPI do topo (dashboard/mensalidades)
    kpi=dict(receita_mes=..., receita_anterior=..., potencial=..., pendente=...,
             inadimplentes=..., adimplencia=..., ativos=...,
             pagas=..., total_cobrancas=...),

    pendencias=[dict(id=, aluno_id=, nome=, faixa=, cor_faixa=, vencimento=date, valor=, status='atrasado|pendente')],
    por_faixa=[dict(nome=, qtd=, cor=)],
    mensalidades=[dict(id=, aluno_id=, nome=, faixa=, cor_faixa=, vencimento=date,
                       valor=, juros=, isento=bool, status='pago|atrasado|pendente')],
    planos=[dict(id=, nome=, descricao=, valor=, ativo=bool)],
    formas=[dict(id=, nome=, usos=int, ativo=bool)],
    descontos=[dict(id=, nome=, tipo='percentual|fixo', valor=, motivo=, ativo=bool)],
    sem_cobranca=[dict(id=, nome=, cor_faixa=)],
    cob=dict(total=, abertas=, pagas=, valor_total=),
    cobrancas=[dict(aluno_id=, nome=, cor_faixa=, original=, desconto=, final=,
                    status='gerada|atrasado|paga|cancelada', vencimento=date)],
    competencias=['Ago 2026', 'Jul 2026', ...],
    historico=[dict(id=, aluno_id=, nome=, competencia=, vencimento=date,
                    pagamento=date|None, forma=, valor=, status=)],
    hist_total=, hist_pago=,
)
return render_template("financeiro/painel_um.html", **ctx)
\`\`\`

O POST da aba \`cobrancas\` chega no mesmo endpoint com \`alunos\` (lista de ids),
\`plano_id\`, \`desconto_id\`, \`dia_vencimento\`, \`observacao\`.

## Eventos e competições — duas abas na mesma rota

\`?aba=eventos|competicoes\`. Cada item: \`id, nome, tipo, encerra (date),
aderido (bool), inscricoes_abertas (bool), inscritos (int), formulario\`.
Também: \`academia\`, \`academias\`.
Endpoints usados: \`eventos_competicoes.detalhe|inscritos|aderir|remover_adesao\`.

## Calendário

\`\`\`python
ctx = dict(
    academia=academia, mes=mes, ano=ano, mes_label=...,
    mes_ant=, ano_ant=, mes_prox=, ano_prox=,
    visao=request.args.get("visao", "mes"),
    # 35 ou 42 células, incluindo as vazias antes do dia 1 e depois do último
    celulas=[dict(dia=int|None, hoje=bool,
                  itens=[dict(id=, nome=, tipo='aula|evento|competicao|feriado', horario=)])],
    lancamentos=[dict(id=, data=date, nome=, tipo=, horario=)],
)
\`\`\`

A célula mostra no máximo 2 itens e um link "+N lançamentos" que abre a visão
lista filtrada pelo dia — foi o que resolveu a repetição visual do mês cheio.

## Visitantes

\`?aba=visitantes|solicitacoes|diarias|matriculas\`.
\`visitantes=[dict(id, nome, foto_url, idade, telefone, aulas, ultima_aula (date), ativo)]\`,
mais \`com_agenda\`, \`convertidos\`, \`academia\`, \`academias\` e as listas das
outras abas (\`solicitacoes\`, \`diarias\`, \`matriculas\`) só para o contador.

## Pré-cadastro

\`\`\`python
links=[dict(nome='Página da academia', descricao='modalidades, horários e matrícula',
            url=url_for('externo.landing', slug=academia.slug, _external=True)),
       dict(nome='Pré-cadastro', descricao='formulário curto de interesse', url=...),
       dict(nome='Aula experimental', descricao='agendamento de aula avulsa', url=...),
       dict(nome='Matrícula', descricao='o aluno preenche os dados e recebe a cobrança', url=...)]
pessoas=[dict(id, nome, foto_url, origem_label, email, telefone, nascimento (date), criado_em (datetime))]
valor_matricula=..., gateway_ativo=bool
qtd_experimentais=, qtd_matriculas=, qtd_promovidos=
\`\`\`

## Usuários

Paginação server-side (12 por página):
\`usuarios=[dict(id, nome, foto_url, cpf, email, papeis=['Aluno','Professor'], ativo)]\`,
\`total\`, \`total_ativos\`, \`total_inativos\`, \`total_cpf_pendente\`,
\`pagina\`, \`paginas\`, \`academia\`, \`academias\`.
Filtros por querystring: \`situacao\` (ativos|inativos|todos), \`q\`, \`papel\`, \`academia_id\`.
