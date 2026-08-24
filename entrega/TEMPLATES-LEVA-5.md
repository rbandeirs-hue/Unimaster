# Leva 5 — Painel da academia + Professores (visual novo)

Arquivos desta leva:

| Arquivo | Onde vai | Rota |
|---|---|---|
| \`templates/base_um2.html\` | \`templates/base_um2.html\` | — (shell novo: Public Sans, cinza-pedra, raio 3px) |
| \`templates/painel/academia_dash.html\` | substitui o atual | \`painel.index\` (modo academia) |
| \`templates/professores/lista_professores.html\` | substitui o atual | \`professores.lista\` |

\`base_um2.html\` reaproveita \`components/_shell.html\` (mesma barra lateral, mesmos
endpoints) e só repinta os tokens. As telas antigas continuam em \`base_um.html\`,
sem alteração.

## Contexto esperado — painel.index (modo academia)

Mantém o contrato da leva 3 e acrescenta os filtros e o financeiro avançado.
Em \`blueprints/academia/routes.py\`, \`_get_academia_dashboard\` já calcula tudo:

\`\`\`python
d = _get_academia_dashboard(academia_id, ano, mes)
meses_pt = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

ctx = dict(
    academia=academia,                 # .id, .nome
    academias=academias,               # para o filtro de academia
    ano=ano, mes=mes,
    mes_label=f"{meses_pt[mes-1]} de {ano}",
    meses_opcoes=list(enumerate(meses_pt, start=1)),
    anos_opcoes=range(ano - 2, ano + 1),
    turmas=turmas, modalidades=modalidades,
    turma_id=request.args.get("turma_id"),
    modalidade_id=request.args.get("modalidade_id"),

    al=dict(ativos=d["ativos"], novos=d["atual"]["novos"], baixas=d["atual"]["baixas"],
            saldo=d["saldo_alunos"], churn=d["churn_pct"],
            novos_delta=d["atual"]["novos"] - d["anterior"]["novos"],
            baixas_delta=d["atual"]["baixas"] - d["anterior"]["baixas"]),

    fin=dict(receitas=d["atual"]["receitas"], despesas=d["atual"]["despesas"],
             saldo=d["atual"]["saldo"], ticket=d["ticket_medio"],
             recebido=d["atual"]["mens_recebido"], previsto=d["atual"]["mens_previsto"],
             inadimplencia=d["inadimplencia_pct"], total_atraso=d["atrasado_valor"],
             qtd_atraso=d["inadimplentes_qtd"],
             receitas_delta=d["atual"]["receitas"] - d["anterior"]["receitas"],
             despesas_delta=d["atual"]["despesas"] - d["anterior"]["despesas"],
             saldo_delta=d["atual"]["saldo"] - d["anterior"]["saldo"]),

    avc=dict(mrr=d["mrr"], venc7_valor=d["venc7_valor"], venc7_qtd=d["venc7_qtd"],
             receitas_ano=d["receitas_ano"], despesas_ano=d["despesas_ano"],
             saldo_ano=d["saldo_ano"]),

    serie=list(reversed(d["serie"])),   # 6 itens: label, receitas, despesas
    situacoes=[("Ativos", d["ativos"]), ("Inativos", d["inativos"]),
               ("Suspensos", d["suspensos"]), ("Formados", d["formados"]),
               ("Total", d["total_alunos"])],
    inadimplentes=[dict(aluno_id=i["id"], nome=i["nome"], qtd_cobrancas=i["qtd"],
                        total=i["total"], vencimento_antigo=i["venc"])
                   for i in d["inadimplentes"]],
)
return render_template("painel/academia_dash.html", **ctx)
\`\`\`

## Contexto esperado — professores.lista

O que a rota já envia (\`blueprints/professores/routes.py\`) basta:
\`professores\` (id, nome, email, telefone, ativo, foto_url, modalidades_nomes),
\`academia\`, \`academia_id\`, \`origin\`.

Opcionais que a tela usa se existirem:

\`\`\`python
modalidades_cobertas=len({m for p in professores
                          for m in (p["modalidades_nomes"] or "").split(", ") if m and m != "—"}),
modalidades=modalidades,     # popula o filtro de modalidade
ano_atual=date.today().year,
\`\`\`

Os filtros (\`q\`, \`modalidade_id\`, \`situacao\`) chegam por querystring e ficam
preenchidos no formulário; aplique-os no SQL do \`lista()\` quando quiser ativá-los.
