# Templates Jinja — leva 3: dez telas

Mesmo padrão das levas 1 e 2. Todos herdam de `base_um.html`.

| Arquivo | Rota | Muda o quê |
|---|---|---|
| `turmas/lista.html` | `turmas.lista_turmas` | cartão sem faixa colorida, barra de ocupação, exclusão em modal |
| `visitantes/lista.html` | `visitantes.lista` | 4 páginas → 4 abas, Novo Visitante em modal |
| `precadastro/lista.html` | `precadastro.lista` | links públicos em cartões com copiar, 2 modais |
| `eventos_competicoes/lista_academia.html` | `eventos_competicoes.lista_academia` | eventos + competições em abas, adesão em modal |
| `calendario/visualizar.html` | `calendario.visualizar` | agenda ao lado da grade, 6 botões → 2 |
| `configuracoes/modalidades_lista.html` | `configuracoes.modalidades_lista` | graduações em modal via JSON |
| `academia/lista_usuarios.html` | `academia.lista_usuarios` | cartões → tabela, filtro CPF pendente |
| `academia/whatsapp.html` | `academia.whatsapp` | conexão em faixa única, QR na tela, automações em switch |
| `painel/academia_dash.html` | `painel.index` (modo academia) | deltas vs mês anterior, tabela de inadimplentes |
| `solicitacoes/lista.html` | `solicitacoes.lista` | abas por status, decisão em modal com observação |
| `components/_modal.html` | — | CSS + JS dos modais; inclua uma vez por tela que use |

---

## Padrão dos modais

Toda tela com modal faz, no começo do `um_conteudo`:

```jinja
{% include 'components/_modal.html' %}
```

Depois:

```html
<button onclick="umAbrir('meuId')">Abrir</button>

<div class="um-modal" id="meuId" onclick="umFechar(event,'meuId')">
  <form class="um-modal-cx" onclick="event.stopPropagation()" method="POST" action="...">
    <div class="um-modal-h">...</div>
    <div class="um-modal-b">...</div>
    <div class="um-modal-f">...</div>
  </form>
</div>
```

`Esc` fecha, clique fora fecha. Sem Bootstrap JS, sem dependência.

---

## Contexto de cada rota

### `turmas.lista_turmas`

```
turmas: [ nome, modalidades (lista de str), categoria, dias, horario,
          professor, local, qtd_alunos, vagas (ou None), ativa (bool), id ]
q, status ('ativas' | 'inativas' | 'todas'), academia
```

A barra de ocupação só aparece quando `vagas` está preenchido; sem vagas
mostra "N alunos matriculados". Vermelha quando lotada.

### `visitantes.lista`

Uma rota, quatro abas por `?aba=`:

```
aba, q, status, academia, turmas
lista:        visitantes: [ id, nome, email, telefone, idade, qtd_aulas, presentes, ativo ]
solicitacoes: solicitacoes: [ id, visitante_nome, turma, data, status ]
pagamentos:   pagamentos: [ visitante_nome, turma, data, valor, isento, status, comprovante ]
matriculas:   matriculas: [ aluno_id, nome, data, turma ]
```

`status` das solicitações: `Pendente`, `Aprovada`, `Recusada`.
Dos pagamentos: `Pago`, `Aguardando`, `Em aberto`, `Isento`.

### `precadastro.lista`

```
links: [ icone, titulo, descricao, url ]  — os quatro links públicos
precadastros: [ id, nome, email, telefone, origem, criado_em, pagamento ]
total, qtd_pendentes, qtd_experimentais, q, origem
valor_matricula, cupons: [ codigo, desconto, usos ]
turmas, planos  — para o modal de promover
```

`origem`: `'Matrícula'`, `'Aula experimental'`, `'Pré-cadastro'`.
`pagamento`: `'pago'`, `'pendente'` ou `None`.

Ícones dos links: `bi-globe2`, `bi-link-45deg`, `bi-stars`, `bi-mortarboard-fill`.

### `eventos_competicoes.lista_academia`

```
aba ('eventos' | 'competicoes'), academia, academias
itens: [ id, nome, prazo (date), formulario, anexo, anexo_url,
         aderiu (bool), encerrado (bool), qtd_inscritos ]
```

Rotas dos modais: `eventos_competicoes.aderir` e `.desaderir` (POST, `<id>`).

### `calendario.visualizar`

```
mes, ano, mes_label ('Agosto de 2026'), mes_abrev ('Ago'),
mes_ant, ano_ant, mes_prox, ano_prox,
primeiro_dia_semana (0=domingo), ultimo_dia, dia_hoje (ou None),
eventos_por_dia: { 12: [ {titulo, hora, tipo} ] },
agenda: [ {dia, titulo, hora, tipo} ]  — ordenada por dia
qtd_aprovar, qtd_conflitos
```

`tipo`: `aula`, `feriado`, `evento`, `competicao`. A célula mostra 3 e
"+N"; a agenda mostra tudo.

```python
primeiro_dia_semana = date(ano, mes, 1).weekday()  # 0=segunda
primeiro_dia_semana = (primeiro_dia_semana + 1) % 7  # converte p/ domingo=0
ultimo_dia = calendar.monthrange(ano, mes)[1]
dia_hoje = date.today().day if (mes, ano) == (date.today().month, date.today().year) else None
```

### `configuracoes.modalidades_lista`

```
modalidades: [ id, nome, descricao, ativa, privada, academias (lista de str) ]
academias, associacoes, academia
```

Duas rotas novas para o modal de graduações:

```python
@configuracoes.route('/modalidades/<int:id>/graduacoes.json')
def graduacoes_json(id):
    return jsonify([
        dict(faixa=g.faixa, grau=g.grau, categoria=g.categoria,
             cor=CORES_FAIXA.get(g.faixa.lower(), '#d4d4d8'))
        for g in graduacoes_da_modalidade(id)
    ])

@configuracoes.route('/modalidades/<int:id>/graduacoes/nova')
def graduacao_nova(id): ...
```

### `academia.lista_usuarios`

```
usuarios: [ id, nome, email, cpf, roles (lista de str), ativo ]
total, qtd_ativos, qtd_sem_cpf, q, status, sem_cpf (bool)
papeis  — lista de roles para o modal
academias, academia
```

`?sem_cpf=1` filtra só quem está sem CPF. Rotas: `academia.novo_usuario`,
`academia.editar_usuario`, `academia.alternar_usuario` (POST).

### `academia.whatsapp`

```
conectado (bool), numero, mostrar_qr (bool — de ?qr=1), qr_code (data-uri ou None)
automacoes: [ chave, nome, detalhe, ativa (bool) ]
```

Rotas: `whatsapp_desconectar`, `whatsapp_preferencias`, `whatsapp_teste`
(todas POST), `whatsapp_avisos`, `whatsapp_mensagens` (GET).

O switch é um checkbox escondido com um `<span>` desenhado — envia
`automacoes` como lista de chaves marcadas.

### `painel.index` — modo academia

```
mes, ano, mes_label, mes_ant, ano_ant, mes_prox, ano_prox, academia
al:  ativos, novos, novos_delta, baixas, baixas_delta, saldo, churn
fin: receitas, receitas_delta, despesas, despesas_delta, saldo, saldo_delta,
     ticket, recebido, previsto, inadimplencia, total_atraso, qtd_atraso
situacoes: [ ('Ativos', 74), ('Inativos', 12), ... ]
inadimplentes: [ aluno_id, nome, cor_faixa, qtd_cobrancas, vencimento_antigo, total ]
```

Os `*_delta` são a diferença contra o mês anterior (número, pode ser
negativo) ou `None` para não mostrar. A macro pinta verde ou vermelho
conforme o sinal fizer sentido: em `baixas`, subir é vermelho.

### `solicitacoes.lista`

```
aba ('pendentes' | 'aprovadas' | 'recusadas'), q, tipo, tipos (lista de str)
qtd_pendentes
solicitacoes: [ id, aluno_nome, turma, solicitante, tipo, detalhe,
                criada_em, status ]
```

Rotas: `solicitacoes.aprovar` e `.recusar` (POST, `<id>`, campo
`observacao` opcional).

---

## Endpoints novos nesta leva

Além dos das levas anteriores:

```
turmas.nova            turmas.editar         turmas.excluir      turmas.alunos
turmas.matricular      visitantes.detalhes   visitantes.agendar  visitantes.novo
visitantes.aprovar_solicitacao   visitantes.recusar_solicitacao
precadastro.editar     precadastro.promover  precadastro.cupons
precadastro.salvar_valor_matricula
eventos_competicoes.inscritos / .aderir / .desaderir
calendario.novo_evento / .sincronizar / .lista_eventos / .aprovar_eventos / .conflitos
configuracoes.modalidade_nova / .modalidade_editar / .modalidade_alternar
configuracoes.modalidade_excluir / .graduacoes_json / .graduacao_nova
academia.novo_usuario / .editar_usuario / .alternar_usuario
academia.whatsapp_desconectar / _preferencias / _teste / _avisos / _mensagens
solicitacoes.aprovar / .recusar
alunos.ficha
```

Confira com `flask routes` antes de subir. Onde o nome já existir com outra
grafia, é só trocar no template — cada um aparece uma ou duas vezes.

---

## Falta

**Leva 4** — Alunos: lista, ficha, cadastro e edição. É a maior do sistema
(4.700 linhas hoje, com muitos modais); vai em partes: primeiro a lista com
o modal de ações, depois a ficha, depois cadastro e edição.
