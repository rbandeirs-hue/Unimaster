# Plano — Menu lateral único em todas as telas

Objetivo: encerrar a convivência de dois modelos de tela (com e sem menu lateral)
e passar **todo o sistema logado** a usar o shell de barra lateral.

Levantado sobre o código em 24/08/2026, branch `redesign-design-system`.

---

## ✅ Estado da execução — concluída em 24/08/2026

| | Antes | Depois |
|---|---|---|
| Telas logadas com menu lateral | 45 (24%) | **199 (100%)** |
| Telas em `base.html` | 141 | **4** (todas públicas/setup) |
| `base.html` | 1.205 linhas | **250** |
| Modos com lateral | 1 (academia) | **8** |
| Subsistemas de JS perdidos ao migrar | 5 | **0** |

Sem menu lateral, de propósito (herdam tokens, não o chrome): as 10 telas de
`externo/`, a inscrição pública de academia, o cadastro no Zempo por token (3)
e o `primeiro_usuario.html`.

**Ondas executadas:** 0 (fundação) → 1 (academia, 77) → 2 (aluno/responsável/
visitante, 20) → 3 (admin/federação/associação, 33) → 4 (zempo e avulsas, 10),
mais a reescrita do `solicitacoes/hub.html` e a remoção dos protótipos órfãos
(`base_um.html`, `base_um2.html`, `components/_shell.html`,
`components/sidebar.html`).

**Verificação:** `tests/test_shell_smoke.py` — 1.312 visitas em 8 modos, 0
falhas; auditoria estática da cadeia de herança; conferência de lateral, CSRF,
tema e notificações nos 7 modos alcançáveis por rota (federação não tem usuário
com CPF na base, e é coberto por teste de unidade do menu).

**Bugs corrigidos no caminho**, ambos encontrados pelo próprio processo:

1. `lista_alunos.html:3652` — POST em JSON sem `X-CSRFToken` para uma rota não
   isenta: matricular aluno em turma respondia 400.
2. `associacao.precadastro` — `from flask import url_for` dentro da função
   sombreava o import do topo, e o caminho de acesso negado estourava 500.

**Decisões tomadas** (as 5 perguntas da seção 7):

1. **Botão voltar** — mantido funcionando (`botao_voltar.css` agora entra no
   shell). Não foi removido em massa: com o cabeçalho do shell condicional, ele
   não duplica nada. Sai tela a tela na passada de refino.
2. **Modo noturno** — mantido. O tema virou arquivo e o shell ganhou o botão de
   alternar, que não tinha.
3. **Troca de academia** — o indicador virou link para `academia.escolher_academia`,
   no lugar de "saia e entre de novo".
4. **Ordem** — academia → aluno/responsável → admin/federação/associação → zempo.
5. **Protótipos órfãos** — removidos.

**O que ficou para a passada de refino** (não é bloqueio, é acabamento): subir o
`<h1>` de ~107 telas para `pagina_titulo`, e então apagar o título inline e o
botão voltar de cada uma. Enquanto isso não acontece, cada tela mostra o próprio
cabeçalho dentro do conteúdo — que é como ela já era.

---

---

## 1. Onde estamos

| Base | Telas | Tem menu lateral? |
|---|---|---|
| `base.html` | **141** | não — navbar superior |
| `base_academia.html` | **45** | **sim** — é o alvo |
| `financeiro/painel/_base.html` | 15 | herda de `base_academia.html` ✔ |
| `externo/base_externo.html` | 10 | não — e **não deve ter** (público) |
| `base_publico.html` | 1 | não — e **não deve ter** (público) |
| `base_um.html` / `base_um2.html` | 1 | protótipos órfãos — a remover |

**Migração real: 45 de 186 telas logadas (24%).**

### A notícia boa: o contrato de blocos já é compatível

| Bloco | `base.html` | `base_academia.html` | Telas que usam |
|---|---|---|---|
| `title` | ✔ | ✔ | 217 |
| `content` | ✔ | ✔ | 201 |
| `extra_css` | ✔ | ✔ | 59 |
| `extra_js` | ✔ | ✔ | 32 |
| `body_class` / `container_extra_class` | ✔ | — | **0 telas filhas** |

Nenhuma tela filha sobrescreve os dois blocos exclusivos do `base.html`. Ou seja:
**trocar `{% extends "base.html" %}` por `{% extends "base_academia.html" %}` não
quebra o contrato de blocos de nenhuma das 141 telas.** O trabalho está em outro
lugar — nos cinco bloqueadores abaixo.

---

## 2. Os cinco bloqueadores

### 🔴 Bloqueador 1 — O `base_academia.html` perde 5 subsistemas de JS do `base.html`

Isto é o mais grave e **já causou regressão**. O `base.html` carrega, em `<script>`
inline, cinco coisas que o `base_academia.html` simplesmente não tem:

| Subsistema | Linhas | O que faz | Consequência de migrar sem ele |
|---|---|---|---|
| **CSRF automático** | ~60 | injeta `csrf_token` em todo `<form method=post>`, e o header `X-CSRFToken` em `fetch()` e `XMLHttpRequest` | **POST devolve 400** |
| **Modo noturno** | 342 (CSS) + 3 funções | `.dark-mode` + `localStorage` | tela migrada perde o tema escuro |
| **Caixa de notificações** | ~190 | badge, listagem, marcar como lida | sino vira link morto |
| **Push (VAPID)** | ~250 | service worker, assinatura, ativar/desativar | usuário não consegue ativar push |
| **`layout_embed` + botão voltar** | — | modo embutido e CSS do voltar | telas embutidas quebram |

#### Regressão já existente (corrigir antes de qualquer coisa)

`templates/alunos/lista_alunos.html:3652` faz:

```js
fetch(urlPost, { method:'POST', headers:{'Content-Type':'application/json'},
                 body: JSON.stringify(payload) })     // ← sem X-CSRFToken
```

O destino é `alunos.matricular_turma_post` (`blueprints/aluno/alunos.py:4810`), que
**não** é `@csrf.exempt`. Como `lista_alunos.html` já foi migrado para
`base_academia.html`, o interceptador de `fetch` não existe mais na página →
**matricular aluno em turma pela lista de alunos responde 400.**

As outras 12 telas migradas com `fetch` estão salvas por acaso: ou mandam o header
na mão, ou postam `FormData` de um form que tem o `csrf_token` explícito.
Das 141 telas ainda por migrar, **19 usam `fetch(`** — cada uma é uma roleta.

### 🔴 Bloqueador 2 — O menu é do modo academia, cravado no template

As ~20 linhas de menu vivem dentro do `base_academia.html` como literal Jinja, e
**todo item chama `url_for(..., academia_id=academia_id)`**. Não existe menu para os
outros 7 modos: `admin`, `federacao`, `associacao`, `professor`, `aluno`,
`responsavel`, `visitante`.

Escrever mais 7 blocos desses dentro do template é inviável de manter.

### 🔴 Bloqueador 3 — O context processor só atende o modo academia

`app.py:438` — `injetar_contexto_academia()` tem a guarda:

```python
if session.get("modo_painel") != "academia":
    return {}
```

Fora do modo academia, `academia`, `academias` e `academia_id` chegam vazios. O
próprio docstring registra o sintoma: *"sem elas, a lateral perdia o item
Professores e o seletor de academia sumia — era possível entrar na tela mas não
navegar a partir dela."*

### 🟡 Bloqueador 4 — A barra de topo é do modo academia

- busca cravada em `alunos.lista_alunos` — sem sentido para aluno/responsável;
- indicador "academia desta sessão" — idem;
- sino de notificação é um `onclick="window.location=..."`, não a caixa real.

### 🟡 Bloqueador 5 — Cabeçalho de página duplicado

O shell já desenha `sh__cabecalho` com `pagina_titulo` / `pagina_subtitulo` /
`pagina_acoes`. Mas das 141 telas:

- **107 têm `<h1>`/`<h2>`/`<h3>` próprio dentro de `content`** → vira título duplicado;
- **91 incluem `botao_voltar`** → com lateral fixa, o voltar em geral perde a razão de ser.

Esses dois são o grosso do trabalho manual: são 141 × (mover título + decidir o voltar).

---

## 3. Arquitetura proposta

### 3.1 O menu sai do template e vai para Python

Criar `utils/menu.py`:

```python
def menu_do_modo(modo, ctx):
    """Devolve [(rotulo_grupo, [ItemMenu, ...]), ...] para o modo dado.

    ctx traz o escopo já resolvido (academia_id, federacao_id, aluno_id...).
    Item com href None é omitido — é assim que a permissão esconde o item.
    """
```

Uma função por modo, em Python puro: testável, sem `url_for` espalhado por Jinja, e
o `base_app.html` passa a só iterar `menu_grupos`. Adicionar um modo vira adicionar
uma lista, não editar o layout.

### 3.2 `menu_ativo` por blueprint, não por template

Marcar o item ativo em 141 templates na mão é caro e some no primeiro merge. Em vez
disso, um mapa `blueprint → chave de menu` no context processor:

```python
MENU_POR_BLUEPRINT = {"alunos": "alunos", "turmas": "turmas",
                      "financeiro": "financeiro", ...}
menu_ativo = menu_ativo_explicito or MENU_POR_BLUEPRINT.get(request.blueprint)
```

O template continua podendo sobrescrever com `{% set menu_ativo = ... %}` quando o
blueprint atende mais de um item. **Economiza ~130 edições de template.**

### 3.3 Um shell só, com alias de transição

- `base_academia.html` → renomear para **`base_app.html`** (nome honesto: serve todos os modos);
- manter `base_academia.html` como arquivo de uma linha (`{% extends "base_app.html" %}`)
  até a última tela migrar — assim as 45 já migradas não precisam ser tocadas agora;
- `base.html` sobrevive até o fim da migração e só então é removido.

### 3.4 JS do `base.html` vira arquivo compartilhado

**Este é o pré-requisito de tudo.** Extrair os `<script>` inline para:

```
static/js/base/csrf.js           ← corrige a regressão de imediato
static/js/base/tema.js           + static/css/base/theme.css (as 342 linhas)
static/js/base/notificacoes.js
static/js/base/push.js
```

e carregá-los **nas duas bases**. Ganhos: a regressão morre, o navegador passa a
cachear, e a migração deixa de ser perda de funcionalidade.

---

## 4. Ondas de migração

### Onda 0 — Pré-requisitos (nada de tela migra ainda)

| # | Tarefa | Esforço |
|---|---|---|
| 0.1 | **Corrigir o CSRF de `lista_alunos.html:3652`** (hotfix isolado) | 15 min |
| 0.2 | Extrair os 5 subsistemas de JS/CSS para arquivo e carregar nas duas bases | 1 dia |
| 0.3 | `utils/menu.py` + menus dos 8 modos | 1 dia |
| 0.4 | Context processor de shell por modo (substitui `injetar_contexto_academia`) | 0,5 dia |
| 0.5 | Topo do shell ciente de modo (busca, escopo, sino real) | 0,5 dia |
| 0.6 | `base_app.html` + alias `base_academia.html` | 1 h |
| 0.7 | **Teste de fumaça**: GET em toda rota, por papel, assert 200 | 1 dia |

O item **0.7 é inegociável**: é o único jeito realista de migrar 141 telas sem
descobrir os erros em produção.

### Ondas 1–5 — Telas

| Onda | Escopo | Telas | Por quê nessa ordem |
|---|---|---|---|
| **1** | Terminar o modo **academia** — financeiro (16), eventos_competicoes (21), competicoes (12), academia (8), presenças/turmas/alunos/calendário restantes | ~60 | menu já existe e está validado; risco menor |
| **2** | **aluno** (11) + **responsável** (4) + **visitante** (5) | 20 | menus curtos, telas simples |
| **3** | **admin / federação / associação** — painel (14), federacoes (3), associacoes (3), academias (2), usuarios (5), configuracoes (5), formularios (3) | ~35 | 3 menus novos |
| **4** | **professor** | ~10 | depende do menu do modo professor |
| **5** | zempo (8) + avulsas da raiz (3) | 11 | resíduo |

### Fora de escopo — continuam sem menu lateral

Login, `index.html`, pré-cadastro e matrícula públicos, `externo/*` (10),
pagamento público, placar/monitor/chaves de judô, `ata_presenca` (impressão).
Estas herdam **tokens**, não o chrome.

---

## 5. Checklist por tela migrada

```
[ ] extends → base_app.html
[ ] {% set menu_ativo = '...' %}  (só se o mapa por blueprint não resolver)
[ ] <h1> próprio → {% block pagina_titulo %}
[ ] subtítulo/contadores → {% block pagina_subtitulo %}
[ ] botões do topo → {% block pagina_acoes %}
[ ] remover include de botao_voltar (política da seção 7)
[ ] se tem fetch/XHR mutante: conferir CSRF (deve estar coberto pela Onda 0.2)
[ ] abrir a tela em 375px, 768px e 1440px
[ ] modo escuro ligado
```

Sugestão: `scripts/migrar_shell.py` faz os 5 primeiros passos mecanicamente e
**deixa um `TODO` onde não tiver certeza** — a revisão continua humana, mas some o
trabalho braçal de 141 arquivos.

---

## 6. Riscos e reversão

| Risco | Mitigação |
|---|---|
| POST quebrando por CSRF | Onda 0.2 antes de qualquer migração + teste de fumaça |
| Tela sem escopo (`academia_id` vazio) | context processor por modo (0.4) + assert no teste |
| Título duplicado / voltar órfão | checklist + revisão visual por tela |
| Deploy com CSS/template em cache | 3 workers gunicorn: `kill -HUP` obrigatório, e `?v=<hash>` nos `<link>` |
| Reversão | 1 linha por tela (`extends`) — reverter é `git revert` do commit da tela |

Migrar **uma tela por commit**, ou no máximo uma área por commit. Nada de commit
com 60 templates.

---

## 7. Decisões que preciso do Rodrigo antes de executar

1. **Botão voltar** (91 telas): com lateral fixa, remover de vez ou manter só em
   fluxos de edição (cadastro → ficha)?
2. **Modo noturno**: mantém no shell novo? (hoje o shell não tem, e 45 telas já
   perderam o tema escuro sem isso ter sido decidido)
3. **Troca de academia**: hoje o shell diz "para trocar, saia e entre de novo".
   Vira um seletor de verdade na lateral, ou fica como está?
4. **Ordem**: confirma academia → aluno/responsável → admin/federação/associação →
   professor → zempo?
5. **`base_um.html` / `base_um2.html` / `components/_shell.html`**: posso remover?
   (só `solicitacoes/hub.html` usa, e ele seria migrado junto)

---

## 8. Resumo do esforço

| Bloco | Esforço |
|---|---|
| Onda 0 (pré-requisitos) | **~4,5 dias** |
| 141 telas × ~15 min mecânico + revisão | **~2 a 3 semanas** |
| **Total** | **~3 a 4 semanas** |

O ponto que vale repetir: **os 4,5 dias da Onda 0 não são preparação opcional.**
Sem eles, cada tela migrada perde CSRF, tema escuro, notificações e push — foi
exatamente o que aconteceu com as 45 telas já migradas, e é por isso que existe um
400 silencioso na matrícula em turma hoje.
