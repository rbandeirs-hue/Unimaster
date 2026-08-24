# Templates Jinja — como aplicar (leva 1)

O pacote anterior era **só CSS**: dava a aparência nova, mas não mudava a
estrutura das telas. Estes arquivos são os **templates de verdade**, em
Jinja + HTML puro. Sem React, sem build, sem npm.

---

## Como funciona

Três peças:

| Arquivo | Papel |
|---|---|
| `templates/base_um.html` | shell completo: `<head>`, CSS base, grade, barra lateral, topo, flash messages, gaveta no celular |
| `templates/components/_shell.html` | macros `sidebar()`, `topbar()`, `mobbar()` |
| `templates/financeiro/painel.html` | a tela, com `{% extends 'base_um.html' %}` |

`base_um.html` **não** herda de `base.html`. É um shell paralelo: a tela
convertida usa o novo, as não convertidas continuam no antigo. Você migra
uma por vez sem quebrar nada.

Cada tela convertida declara só:

```jinja
{% extends 'base_um.html' %}
{% set um_ativo = 'financeiro' %}
{% block title %}Financeiro{% endblock %}
{% block um_css %}   /* CSS só desta tela */   {% endblock %}
{% block um_conteudo %}   <!-- conteúdo -->   {% endblock %}
```

---

## 1. Copiar

```
templates/base_um.html
templates/components/_shell.html
templates/financeiro/painel.html
templates/financeiro/_relatorio_folha.html
```

**Ajuste obrigatório em `_shell.html`:** os `url_for(...)` da barra lateral
usam nomes de endpoint que eu inferi. Rode `flask routes` e corrija os que
não existirem. Os que preciso confirmar:

```
painel.index                      presencas.hub
presencas.ranking_frequencia      solicitacoes.lista
turmas.lista_turmas               alunos.lista_alunos
professores.lista_professores     visitantes.lista
precadastro.lista                 financeiro_painel.dashboard
eventos_competicoes.lista_academia  calendario.visualizar
locais.lista                      configuracoes.modalidades_lista
academia.whatsapp                 academia.lista_usuarios
configuracoes.index               usuarios.editar_proprio
auth.logout
```

Também troque `static/img/judo-icon.png` pelo caminho real do ícone.

---

## 2. A rota do Financeiro

`painel.html` concentra as 11 abas numa única rota, com `?aba=` e `?mes=`.
Assinatura:

```python
@financeiro_painel.route('/financeiro')
@login_required
def dashboard():
    aba = request.args.get('aba', 'dashboard')
    hoje = date.today()
    mes = int(request.args.get('mes', hoje.month))
    ano = int(request.args.get('ano', hoje.year))
    academia = academia_atual()

    ctx = dict(
        aba=aba, mes=mes, ano=ano, academia=academia,
        mes_label=f'{MESES[mes-1]}/{ano}',
        mes_ant=12 if mes == 1 else mes-1,  ano_ant=ano-1 if mes == 1 else ano,
        mes_prox=1 if mes == 12 else mes+1, ano_prox=ano+1 if mes == 12 else ano,
    )

    if aba == 'dashboard':
        ctx.update(kpi=calcular_kpis(academia, mes, ano),
                   pendencias=pendencias_do_mes(academia, mes, ano),
                   faixas=alunos_por_faixa(academia))

    elif aba == 'receitas':
        rs = receitas_do_mes(academia, mes, ano)
        ctx.update(receitas=rs, total_receitas=sum(r.valor for r in rs))

    elif aba == 'despesas':
        ds = despesas_do_mes(academia, mes, ano)
        ctx.update(despesas=ds, total_despesas=sum(d.valor for d in ds))

    elif aba == 'fechamento':
        ctx.update(**dados_fechamento(academia, mes, ano))

    return render_template('financeiro/painel.html', **ctx)
```

### Formato de cada variável

**`kpi`** — objeto ou dict com: `receita_mes`, `receita_anterior`,
`receita_potencial`, `inadimplentes`, `adimplencia` (int 0–100),
`alunos_ativos`, `pagas`, `total_cobrancas`.

**`pendencias`** — lista de itens com: `nome`, `faixa`, `cor_faixa` (hex),
`valor`, `status` (`'Atrasado'` / `'Pendente'` / `'Pago'`).

**`faixas`** — lista com `nome`, `qtd`, `pct` (0–100), `cor` (hex).

**`receitas`** — lista com `id`, `descricao`, `categoria`, `data` (date),
`valor`, `automatica` (bool — as geradas por pagamento confirmado; sem
botão de editar/excluir, como no sistema atual).

**`despesas`** — `id`, `descricao`, `categoria`, `data`, `valor`.

**`fech`** — `receitas`, `despesas`, `saldo`, `em_atraso`, `qtd_atraso`.

**`entradas_cat` / `saidas_cat`** — lista com `nome`, `valor`, `pct` (0–100).
Agrupar pelo campo `categoria`, que é texto livre nos cadastros; quem estiver
vazio entra como `None` e o template escreve "Sem categoria".

Cores de faixa (mesma tabela usada nas outras telas):

```python
CORES_FAIXA = {
  'branca': '#ffffff', 'cinza': '#455a64', 'amarela': '#f9a825',
  'laranja': '#bf360c', 'verde': '#1b5e20', 'azul': '#0d47a1',
  'marrom': '#4e2b1e', 'preta': '#1a1a1a',
}
```

---

## 3. Abas ainda não convertidas

O template termina com:

```jinja
{% if aba in ['alunos','planos','formas','descontos','cobrancas','mensalidades','historico'] %}
  {% include 'financeiro/_aba_' ~ aba ~ '.html' ignore missing %}
{% endif %}
```

`ignore missing` significa que a aba fica em branco enquanto o parcial não
existir — nada quebra. Para reaproveitar as páginas atuais, salve o
conteúdo de cada uma como `financeiro/_aba_planos.html` etc. (só o miolo,
sem `{% extends %}`).

---

## 4. Impressão e PDF

`_relatorio_folha.html` é a folha A4. Serve para os dois caminhos:

- **Imprimir**: já funciona. O `@media print` esconde o resto da página e
  imprime só a folha; `@page { size: A4; margin: 14mm }` cuida da margem.
- **PDF**: rota que renderiza um HTML mínimo com o include e passa para o
  WeasyPrint:

```python
@financeiro.route('/financeiro/relatorio.pdf')
@login_required
def relatorio_pdf():
    ctx = dados_fechamento(academia_atual(), mes, ano)
    html = render_template('financeiro/relatorio_pdf.html', **ctx)
    pdf = HTML(string=html, base_url=request.url_root).write_pdf()
    return Response(pdf, mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename=financeiro-{mes}-{ano}.pdf'})
```

Onde `relatorio_pdf.html` é só:

```jinja
<!DOCTYPE html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head><body style="margin:0">{% include 'financeiro/_relatorio_folha.html' %}</body></html>
```

O `emitido_em` e `emitido_por` do rodapé vêm do contexto
(`datetime.now().strftime('%d/%m/%Y')` e `current_user.nome`).

**Excel**: `relatorio_excel` pode ser um CSV com `csv.writer` — as mesmas
listas `entradas_cat` e `saidas_cat`, uma seção cada, e a linha de saldo.

---

## 5. Ordem das próximas levas

Cada leva é um `.html` como este, no mesmo padrão. Diga qual quer primeiro:

**Leva 2** — Presença (hub em abas + Relatório + Histórico), Ranking de
frequência, Registro de presença com os cinco modais.

**Leva 3** — Turmas, Visitantes (4 páginas em abas), Pré-cadastro,
Eventos/Competições, Calendário, Modalidades, Usuários, WhatsApp,
Indicadores, Solicitações.

**Leva 4** — Alunos: lista, ficha, cadastro e edição. É a maior (4.700
linhas hoje, muitos modais); vai em partes.
