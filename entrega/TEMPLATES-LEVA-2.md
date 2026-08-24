# Templates Jinja — leva 2: Presença

Três telas. Mesmo padrão da leva 1: `{% extends 'base_um.html' %}`, sem
React, sem build.

| Arquivo | Rota sugerida |
|---|---|
| `templates/presencas/hub.html` | `presencas.hub` — `/presencas` |
| `templates/presencas/ranking.html` | `presencas.ranking_frequencia` |
| `templates/presencas/registro.html` | `presencas.registro` — `/presencas/registrar` |

O hub substitui os quatro cartões de escolha por abas. As quatro entradas
(Registrar, Relatório, Histórico, Ranking) ficam na mesma linha; Relatório
e Histórico são abas do próprio hub (`?aba=ata` e `?aba=hist`), as outras
duas são rotas.

---

## 1. `hub.html` — Relatório e Histórico

```python
@presencas.route('/presencas')
@login_required
def hub():
    aba = request.args.get('aba', 'ata')
    hoje = date.today()
    mes = int(request.args.get('mes', hoje.month))
    ano = int(request.args.get('ano', hoje.year))
    turma_id = request.args.get('turma_id', type=int)
    q = request.args.get('q', '')
    academia = academia_atual()

    ctx = dict(aba=aba, mes=mes, ano=ano, turma_id=turma_id, q=q,
               academia=academia, academias=academias_do_usuario(),
               turmas=turmas_da_academia(academia),
               MESES=MESES, anos=range(hoje.year, hoje.year - 4, -1))

    if aba == 'ata':
        ctx['aulas'] = aulas_com_chamada(academia, mes, ano, turma_id)
    else:
        ctx['historico'] = frequencia_por_aluno(academia, mes, ano, turma_id, q)

    return render_template('presencas/hub.html', **ctx)
```

**`aulas`** — uma por aula registrada, da mais recente para a mais antiga:

```
turma_nome, data (date), dias ('Seg, Qua e Sex'), horario ('18h00'),
professor, presentes (int), faltas (int),
observacao (str ou None), plano_aula (str ou None),
alunos: [ { nome, presente (bool), etiqueta } ]
```

`etiqueta` é `'Outra turma'`, `'Visitante'`, `'Avulso'` ou `''`.

**`historico`** — uma por aluno:

```
nome, turma, presencas (int), total_aulas (int), pct (0–100),
aulas: [ { data (date), turma, horario, presente (bool) } ]
```

O expandir usa `<details>` nativo — a lista de aulas vem no HTML, sem
requisição por linha (o sistema atual carregava uma por uma).

**Imprimir ata**: `window.print()`. Se quiser esconder o resto da página na
impressão, acrescente ao `um_css` da tela:

```css
@media print {
  .um-side, .um-topbar, .um-mobbar, .um-abas, .um-card form { display:none !important; }
  details { open: true; }
}
```

Para todas as aulas saírem abertas no papel, marque `<details open>` quando
`request.args.get('imprimir')` estiver presente.

---

## 2. `ranking.html`

```python
@presencas.route('/presencas/ranking')
@login_required
def ranking_frequencia():
    tipo = request.args.get('tipo', 'mes')       # mes | ano | periodo
    hoje = date.today()
    mes = int(request.args.get('mes', hoje.month))
    ano = int(request.args.get('ano', hoje.year))
    inicio = request.args.get('inicio', '')
    fim = request.args.get('fim', '')
    turma_id = request.args.get('turma_id', type=int)
    academia = academia_atual()

    dados = ranking_por_turma(academia, tipo, mes, ano, inicio, fim, turma_id)

    return render_template('presencas/ranking.html',
        tipo=tipo, mes=mes, ano=ano, inicio=inicio, fim=fim,
        turma_id=turma_id, academia=academia,
        academias=academias_do_usuario(), turmas=turmas_da_academia(academia),
        MESES=MESES, anos=range(hoje.year, hoje.year - 4, -1),
        ranking=dados,
        periodo_label=rotulo_periodo(tipo, mes, ano, inicio, fim),
        total_alunos=sum(len(t['alunos']) for t in dados),
        total_presencas=sum(a['total'] for t in dados for a in t['alunos']))
```

**`ranking`** — uma entrada por turma, **já ordenada** por presenças:

```
nome, alunos: [ { nome, total (int), foto (url ou None) } ]
```

O template lê `alunos[0]`, `[1]` e `[2]` para o pódio (ouro no meio, mais
alto) e usa `alunos[0].total` como base das barras. Se a turma tiver menos
de três alunos, os lugares vazios mostram `—` sem quebrar.

`rotulo_periodo` devolve `'Agosto de 2026'`, `'Ano de 2026'` ou
`'01/01/2026 a 12/08/2026'`.

---

## 3. `registro.html` — a chamada e os cinco modais

```python
@presencas.route('/presencas/registrar')
@login_required
def registro():
    turma_id = request.args.get('turma_id', type=int)
    data_str = request.args.get('data') or date.today().isoformat()
    d = date.fromisoformat(data_str)
    academia = academia_atual()
    turmas = turmas_da_academia(academia)
    turma = próxima_turma(turmas, turma_id)

    return render_template('presencas/registro.html',
        turmas=turmas, turma=turma,
        data_iso=data_str, data_br=d.strftime('%d/%m/%Y'),
        horarios=horarios_da_turma(turma), horario=request.args.get('horario'),
        alunos=alunos_da_chamada(turma, d),
        observacao_aula=obs_da_aula(turma, d),
        plano_aula=plano_da_aula(turma, d))
```

**`alunos`** — a lista da chamada:

```
id, nome, faixa, cor_faixa (hex), foto (url ou None),
presente (bool — se já houver chamada salva neste dia),
etiqueta ('Outra turma' | 'Visitante' | 'Avulso' | ''),
tem_observacao (bool — mostra o "1" no botão de observação)
```

### Rotas que os modais chamam

| Rota | Método | O que recebe |
|---|---|---|
| `presencas.salvar` | POST | `turma_id`, `data`, `horario`, `presentes` (lista de ids), `observacao_aula`, `plano_aula`, `plano_arquivo`, `incluir_alunos` (lista de ids vindos da busca) |
| `presencas.registro_avulso` | POST | `turma_id`, `data`, `nome`, `foto` (opcional) |
| `presencas.observacao_aluno` | POST | `aluno_id`, `data`, `texto` (até 2000) |
| `presencas.buscar_alunos` | GET | `?q=` → **JSON** |

O JSON da busca:

```python
@presencas.route('/presencas/buscar-alunos')
@login_required
def buscar_alunos():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    resultados = []
    for a in alunos_visiveis_para(current_user, q)[:20]:
        mesma = a.academia_id == academia_atual().id
        resultados.append(dict(
            id=a.id, nome=a.nome,
            detalhe=(f'{a.turma.nome} · mesma academia' if mesma else a.academia.nome),
            etiqueta=('Outra turma' if mesma else 'Ext.')))
    return jsonify(resultados)
```

### Comportamento já pronto no template

- Marcar/desmarcar **pinta o card de verde** e atualiza Presentes/Faltas em
  tempo real (nada de reload).
- **Marcar todos** e **Limpar**.
- Observação da aula e plano de aula ficam em campos escondidos do
  formulário — salvam junto com a chamada, num POST só.
- Busca com *debounce* de 250 ms; o botão **Adicionar** só habilita com
  algum selecionado, e o contador mostra "N selecionados".
- `Esc` fecha qualquer modal; clique fora também.
- **Barra fixa no rodapé** com o contador e o botão Registrar Presença —
  não precisa rolar até o fim.

---

## Falta ajustar em `_shell.html`

A leva 1 pedia conferir os `url_for`. Estes três entram agora:

```
presencas.hub                  presencas.registro
presencas.ranking_frequencia
```

Se você mantiver os nomes antigos (`registro_presenca`, `ata_presenca`,
`historico_presenca`), troque nos templates — são poucos pontos:
`hub.html` (4 links nas abas), `ranking.html` (1 link Voltar),
`registro.html` (4 links nas abas + 4 actions de formulário).

---

## Próximas levas

**Leva 3** — Turmas, Visitantes (4 páginas em abas), Pré-cadastro,
Eventos/Competições, Calendário, Modalidades, Usuários, WhatsApp,
Indicadores, Solicitações.

**Leva 4** — Alunos: lista, ficha, cadastro e edição.
