# Templates Jinja — leva 4: Alunos

A maior tela do sistema, em três arquivos. `form_aluno.html` serve para
cadastro **e** edição — a diferença é a variável `aluno` estar presente.

| Arquivo | Rota | Substitui |
|---|---|---|
| `alunos/lista_alunos.html` | `alunos.lista_alunos` | lista em cartões (4.700 linhas) |
| `alunos/ficha.html` | `alunos.ficha` | o modal gigante de detalhes |
| `alunos/form_aluno.html` | `alunos.novo` e `alunos.editar` | cadastro e edição |

---

## 1. Lista — `alunos.lista_alunos`

```python
@alunos.route('/alunos')
@login_required
def lista_alunos():
    q = request.args.get('q', '')
    status = request.args.get('status', 'ativos')
    fin = request.args.get('fin', 'todos')
    turma_id = request.args.get('turma_id', type=int)
    graduacao = request.args.get('graduacao', '')
    modalidade = request.args.get('modalidade', '')
    sexo = request.args.get('sexo', '')
    pagina = request.args.get('pagina', 1, type=int)
    academia = academia_atual()

    consulta = filtrar_alunos(academia, q, status, fin, turma_id, graduacao, modalidade, sexo)
    pag = consulta.paginate(page=pagina, per_page=30)

    return render_template('alunos/lista_alunos.html',
        alunos=[serializar_linha(a) for a in pag.items],
        total=consulta.count(), pagina=pagina, paginas=pag.pages,
        qtd_ativos=..., qtd_inativos=..., qtd_atraso=...,
        turmas=..., graduacoes=..., modalidades=...,
        q=q, status=status, fin=fin, turma_id=turma_id,
        graduacao=graduacao, modalidade=modalidade, sexo=sexo,
        academia=academia, hoje_iso=date.today().isoformat())
```

Cada linha (`serializar_linha`):

```python
dict(
  id=a.id, nome=a.nome, foto=url_foto(a),
  graduacao=a.graduacao_nome, cor_faixa=CORES_FAIXA.get(...),
  turmas=[t.nome for t in a.turmas],
  telefone=a.celular, responsavel=a.responsavel,
  ativo=a.ativo,
  financeiro='atraso',           # atraso | pend | dia | sem
  dados_json=dict(               # o que o modal de ações usa
    nome=a.nome, foto=url_foto(a),
    graduacao=a.graduacao_nome, cor_faixa=...,
    turma=a.turmas[0].nome if a.turmas else None,
    ativo=a.ativo,
    financeiro='atraso',
    financeiro_texto='2 mensalidades em atraso',
    financeiro_valor='R$ 440,00',
    frequencia_resumo='92% no mês',
    mensalidades_resumo='2 em aberto',
    whatsapp='5581999998888',     # só dígitos, com país; None esconde a ação
  ),
)
```

`dados_json` vai no HTML por `|tojson` e o modal monta tudo em JS — um
modal só para a página inteira, em vez de um por linha.

**O modal de ações** tem oito itens em lista vertical (ficha, editar,
frequência, mensalidades, graduação, observações, WhatsApp, desistência),
com a faixa de situação financeira colorida no topo. Desistência só
aparece se `ativo`, e abre o segundo modal com data, motivo, observação e
a opção de cancelar as mensalidades em aberto.

Rota: `alunos.desistencia` (POST, campos `data`, `motivo`, `observacao`,
`cancelar_cobrancas`).

---

## 2. Ficha — `alunos.ficha`

Página em vez de modal, com quatro abas por `?aba=`.

```
aluno: id, nome, foto, graduacao, cor_faixa, ativo, idade,
       telefone, email, responsavel, whatsapp,
       academia, associacao, turmas (lista de str),
       ultima_graduacao (date), tempo_faixa ('1 ano e 3 meses'),
       financeiro, financeiro_texto, financeiro_valor
```

Por aba:

- **academico**: `graduacoes: [ data, nome, cor, exame ]`,
  `observacoes: [ data, autor, texto ]`
- **frequencia**: `freq: { pct, presencas, faltas, ultima,
  aulas: [ data, turma, horario, presente ] }`
- **financeiro**: `fin: { plano, valor, total_atraso,
  mensalidades: [ vencimento, competencia, status, valor ] }`
- **cadastro**: `cadastro: [ ('Dados Pessoais', [('CPF','123...'), ...]), ... ]`
  — lista de tuplas (seção, campos). Monte na rota na ordem que quiser.

---

## 3. Formulário — `alunos.novo` e `alunos.editar`

O mesmo arquivo. Sem `aluno` no contexto é cadastro; com, é edição.

```python
@alunos.route('/alunos/novo', methods=['GET','POST'])
def novo():
    if request.method == 'POST':
        ...
        return redirect(url_for('alunos.ficha', id=novo_aluno.id))
    return render_template('alunos/form_aluno.html',
        academia=academia_atual(), turmas=..., modalidades=...,
        graduacoes=..., academias_irmas=[])

@alunos.route('/alunos/<int:id>/editar', methods=['GET','POST'])
def editar(id):
    a = buscar(id)
    if request.method == 'POST':
        if request.form.get('acao') == 'vincular':
            vincular_academia(a, request.form['vincular_academia_id'])
            return redirect(url_for('alunos.editar', id=id))
        ...
        return redirect(url_for('alunos.ficha', id=id))
    return render_template('alunos/form_aluno.html',
        aluno=serializar_form(a), academia=..., turmas=...,
        modalidades=..., graduacoes=..., academias_irmas=...)
```

`serializar_form` precisa dos campos com sufixo `_iso` nas datas (o
`<input type="date">` exige `YYYY-MM-DD`) e das listas de ids:

```python
dict(
  id=a.id, nome=a.nome, foto=url_foto(a),
  nascimento_iso=a.nascimento.isoformat() if a.nascimento else '',
  nacionalidade=a.nacionalidade, graduacao_id=a.graduacao_id, sexo=a.sexo,
  pai=a.pai, mae=a.mae,
  turma_ids=[t.id for t in a.turmas],
  modalidade_ids=[m.id for m in a.modalidades],
  zempo=a.zempo, zempo_numero=a.zempo_numero,
  zempo_data_iso=..., peso=a.peso,
  ultima_graduacao_iso=..., cpf=a.cpf, rg=a.rg,
  orgao_emissor=a.orgao_emissor, emissao_iso=...,
  cep=a.cep, endereco=a.endereco, numero=a.numero, bairro=a.bairro,
  cidade=a.cidade, estado=a.estado, complemento=a.complemento,
  parentesco=a.parentesco, responsavel=a.responsavel,
  email=a.email, celular=a.celular, residencial=a.residencial,
  comercial=a.comercial, outro_telefone=a.outro_telefone,
  observacoes=a.observacoes,
  resp_fin_nome=..., resp_fin_cpf=..., resp_fin_tel=...,
  academias_vinculadas=[dict(id=x.id, nome=x.nome, principal=x.principal) for x in ...],
)
```

**Nove seções**, nesta ordem: Foto, Dados Pessoais, Vínculos, Filiação,
Turma e Modalidades, Documentos, Endereço, Contatos, Responsável
Financeiro. Índice fixo à direita, barra de salvar fixa no rodapé.

Dois comportamentos em JS, sem backend:

- **CEP** consulta o ViaCEP no `blur` e preenche endereço, bairro, cidade e UF.
- **Mesmo aluno** copia nome, CPF e celular para o responsável financeiro.

A caixa "Academias onde treina" só aparece na edição, e usa duas rotas GET:
`alunos.tornar_principal` e `alunos.desvincular` (ambas com `academia_id`
na query). O botão Vincular envia o próprio formulário com
`acao=vincular` — trate antes de salvar o resto.

---

## Endpoints desta leva

```
alunos.lista_alunos   alunos.novo          alunos.editar      alunos.ficha
alunos.frequencia     alunos.mensalidades  alunos.graduar     alunos.observacoes
alunos.desistencia    alunos.tornar_principal   alunos.desvincular
```

---

## Ordem sugerida de migração

Todas as quatro levas estão prontas. Se for subir aos poucos, esta é a
ordem de menor risco:

1. **Leva 1** — `base_um.html`, `_shell.html`, Financeiro. Valida a barra
   lateral e os `url_for` numa tela só.
2. **Leva 3** — as dez telas menores. Cada uma é independente.
3. **Leva 2** — Presença. O registro tem JS próprio e uma rota JSON nova.
4. **Leva 4** — Alunos. Deixe por último: é onde há mais campos e mais
   chance de faltar um dado no contexto.

Enquanto uma tela não estiver convertida, ela continua no `base.html`
antigo e funcionando. Os dois shells convivem.
