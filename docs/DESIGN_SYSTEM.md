# Design System — Unimaster

Documentação do estado visual atual do sistema e proposta de padronização.
Levantamento feito sobre **234 templates Jinja** e **18 arquivos CSS** (228 KB),
mais o CSS embutido no `base.html`.

Nada aqui altera rota, regra de negócio ou banco: a proposta é de camada visual.

---

## 1. Como o visual está montado hoje

### 1.1 Base comum

`templates/base.html` (1.199 linhas) carrega, nesta ordem:

| Recurso | Origem | Observação |
|---|---|---|
| Poppins (300–700) | Google Fonts | fonte da interface |
| Bootstrap 5.3.2 | CDN jsdelivr | CSS e o bundle JS |
| Bootstrap Icons 1.10.5 | CDN jsdelivr | ícones `bi bi-*` |
| `css/base/layout.css` | local | sidebar, header, tipografia base |
| `css/components/botao_voltar.css` | local | componente isolado |

Blocos disponíveis: `title`, `extra_css`, `body_class`, `container_extra_class`,
`content`, `extra_js`.

**Ponto de atenção:** o `base.html` carrega **342 linhas de CSS inline** em uma tag
`<style>` — todo o modo noturno mora ali, fora do pipeline de arquivos estáticos
(sem cache de navegador, sem reuso).

### 1.2 Cinco linguagens visuais convivendo

O sistema não tem um design system só; tem cinco, cada um com paleta e tipografia
próprias:

| Linguagem | Onde | Prefixo | Cor de destaque | Tipografia |
|---|---|---|---|---|
| **Base Bootstrap** | maioria das telas | — | `#0d6efd` | Poppins |
| **Painel Financeiro** | `financeiro/painel/*` | `fp-` | `#c41e3a` (vinho) | Inter + Roboto Slab + JetBrains Mono |
| **Competição/SaaS** | `pages/competicao-dashboard.css` | `saas-` | `#2563eb` | herda |
| **Configurações** | `configuracoes_academia.html` | `cfg-`, `gw-` | herda | herda |
| **Placar/Chaves de judô** | `placar_judo.css`, `bracket.css` | `jv-` | tema escuro próprio | Oswald, Cinzel |

Além disso, `login/style.css` tem paleta autoral e **12 páginas não estendem
`base.html`** (login, index, pré-cadastro público, súmula de impressão,
recuperação de senha) — são ilhas visuais por natureza, mas hoje divergem sem
critério documentado.

### 1.3 Cores

Não existe paleta única. As cores mais recorrentes no código:

| Cor | Ocorrências | Papel de fato |
|---|---|---|
| `#ffffff` | 255 | superfícies |
| `#0d6efd` | 89 | primária (Bootstrap) |
| `#6c757d` | 62 | texto secundário |
| `#e9ecef` / `#dee2e6` | 97 | bordas |
| `#f8f9fa` | 42 | fundo de página |
| `#6b7280` / `#9ca3af` | 61 | texto secundário **do outro sistema** (Tailwind-like) |
| `#dc3545` | 27 | erro |
| `#10b981` / `#198754` | 43 | sucesso — **dois verdes diferentes** |
| `#2563eb` | 20 | primária do painel de competição |

O sintoma central: **cada família traz seu próprio cinza e seu próprio verde**.
`#6c757d` (Bootstrap) e `#6b7280` (Tailwind) fazem o mesmo papel em telas vizinhas.

### 1.4 Tokens existentes

Já há tokens, mas em quatro namespaces isolados e sem tokens de espaçamento:

- `layout.css` → `--primary`, `--secondary`, `--danger`, `--warning`, `--light-bg`, `--dark-bg`
- `financeiro_painel.css` → 24 tokens `--fp-*`, incluindo tipografia e sombra, com tema escuro via `[data-fp-theme='dark']`
- `competicao-dashboard.css` → 12 tokens `--saas-*`, com raio e sombra
- `base.html` → 6 tokens `--dark-mode-*`
- `login/style.css` → paleta própria com `--transition-*` e `--shadow-*`

### 1.5 Componentes

**Botões** — 1.380 usos no total. `btn-outline-*` (456) e `btn-sm` (451) dominam;
`btn-primary` (177) e `btn-success` (100) vêm depois. Há ainda botões autorais:
`.fp-btn`, `.fp-btn-mini`, `.fp-btn-registrar`, `.saas-btn-primary`, `.cfg-btn-save`.

**Cards** — 2.388 referências. O padrão de fato é `card shadow-sm` (242) e
`card border-0` (68), quase sempre com `card-body` (459) e às vezes `card-header` (102).

**Formulários** — `form-control` (680), `form-label` (660), `form-select` (338),
`input-group` (60). Bootstrap puro, sem wrapper próprio: cada tela repete a
estrutura label + campo + `form-text`.

**Tabelas** — 522 referências, `table-responsive` (63), `table table-hover` (43),
`thead class="table-light"` (33). `table-striped` aparece só 7 vezes.

**Modais** — 1.911 referências. Todos Bootstrap nativo, com `modal-dialog-centered`
frequente.

**Alertas e feedback** — `alert-*` aparece 190 vezes em telas, mas o feedback de
ação usa **toast**: o `base.html` converte `get_flashed_messages` em toasts
Bootstrap, mapeando as categorias `success`, `danger`, `warning`, `info` para
`text-bg-*`. Categorias fora dessas quatro caem em `info` silenciosamente.

**Badges** — 472 usos, majoritariamente nas variantes `bg-*-subtle text-*`.

### 1.6 Espaçamento

Utilitários Bootstrap, com forte concentração: `mb-3` (821), `me-1` (610),
`mb-0` (607), `mb-2` (399), `mb-4` (196), `p-4` (146). Ou seja, a escala real em
uso é **1 / 2 / 3 / 4** — os degraus 5+ quase não aparecem.

Raios de borda são o oposto: **10 valores diferentes** (`10px` 85×, `12px` 56×,
`999px` 44×, `16px` 38×, `8px` 35×, `14px` 35×, `0.5rem` 23×…). Não há token.

### 1.7 Responsividade

- **Breakpoints:** `768px` (80×) é o corte real do sistema; `576px` (30×) e
  `767px` (15×) aparecem em seguida — este último é o mesmo corte de 768 escrito
  de outro jeito. `992px` só 3×.
- **Duplicação de marcação:** 20 templates renderizam **o mesmo conteúdo duas
  vezes** — um bloco `d-md-none` (cards no celular) e outro `d-none d-md-block`
  (tabela no desktop). Funciona, mas dobra a manutenção e é fonte de bug: foi
  exatamente o caso dos modais de QR Code, que precisaram de ids distintos
  (`Avm`/`Avd`) para os dois blocos não colidirem.
- **CSS responsivo isolado por área:** `financeiro/responsive.css` (19 KB),
  `visitante/responsive.css` (14 KB), `academia/solicitacoes_responsive.css`,
  `academia/visitantes_responsive.css` — quatro arquivos resolvendo o mesmo
  problema em quatro lugares.

### 1.8 Dívidas visuais mensuradas

| Sintoma | Número |
|---|---|
| `style="..."` inline nos templates | **691** |
| Templates com `<style>` próprio | **100** (43% do total) |
| CSS inline dentro do `base.html` | 342 linhas |
| Templates que não estendem `base.html` | 12 |
| Namespaces de token independentes | 5 |
| Arquivos "responsive" paralelos | 4 |

---

## 2. Proposta de padronização

Ordem pensada para **não quebrar nada**: cada etapa é aditiva e reversível, e
nenhuma exige tocar em rota, view ou consulta.

### Etapa 1 — Camada de tokens (base para todo o resto)

Criar `static/css/base/tokens.css`, carregado no `base.html` **antes** dos demais.
Ele só declara variáveis: incluir o arquivo não muda um pixel enquanto ninguém o
consome.

```css
:root {
  /* Cor — nomeada por papel, não por matiz */
  --u-primary:        #0d6efd;   /* já é a primária de fato */
  --u-primary-hover:  #0b5ed7;
  --u-primary-ring:   rgba(13, 110, 253, .25);
  --u-success:        #198754;   /* unifica com #10b981 */
  --u-warning:        #ffc107;
  --u-danger:         #dc3545;
  --u-info:           #0dcaf0;

  /* Superfície e texto */
  --u-bg:             #f8f9fa;
  --u-surface:        #ffffff;
  --u-surface-alt:    #f1f3f5;
  --u-border:         #dee2e6;
  --u-text:           #212529;
  --u-text-muted:     #6c757d;   /* unifica com #6b7280 */
  --u-text-faint:     #adb5bd;

  /* Raio — três degraus resolvem os dez valores atuais */
  --u-radius-sm:      8px;
  --u-radius:         12px;
  --u-radius-pill:    999px;

  /* Sombra */
  --u-shadow-sm:      0 1px 3px rgba(15, 23, 42, .08);
  --u-shadow:         0 4px 12px rgba(15, 23, 42, .10);

  /* Espaçamento — espelha a escala Bootstrap já usada */
  --u-space-1: .25rem;  --u-space-2: .5rem;
  --u-space-3: 1rem;    --u-space-4: 1.5rem;

  /* Tipografia */
  --u-font:      'Poppins', 'Segoe UI', system-ui, sans-serif;
  --u-font-mono: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
  --u-fs-xs: .72rem; --u-fs-sm: .82rem; --u-fs-base: 1rem; --u-fs-lg: 1.15rem;
}
```

Os namespaces existentes passam a **apontar** para os tokens, em vez de repetir
valores — `--fp-accent` continua vinho (é identidade do módulo financeiro), mas
`--fp-text-muted` vira `var(--u-text-muted)`. Assim os cinzas e verdes convergem
sem repintar tela por tela.

### Etapa 2 — Modo noturno para fora do `base.html`

Mover as 342 linhas de `<style>` para `static/css/base/dark.css`. Ganho imediato:
o navegador passa a cachear, o HTML de toda página encolhe, e o tema deixa de ser
editado no meio do template. O gatilho continua o mesmo (`.dark-mode` via
`localStorage`), então nada muda no comportamento.

Nesta etapa também vale unificar o tema escuro do painel financeiro
(`[data-fp-theme='dark']`) com o global: hoje são dois mecanismos distintos.

### Etapa 3 — Macros Jinja para os padrões repetidos

Criar `templates/components/ui.html` com macros para o que já é padrão de fato:

```jinja
{% macro card(titulo=None, icone=None) %}    {# card shadow-sm + card-body #}
{% macro campo(nome, label, valor='', tipo='text', ajuda=None, obrigatorio=False) %}
{% macro tabela(colunas, vazio='Nenhum registro.') %}
{% macro botao(texto, icone=None, variante='primary', tamanho='sm', tipo='button') %}
{% macro badge_status(status) %}             {# mapa único status → cor #}
```

O `badge_status` merece destaque: hoje cada tela decide sua cor para
"pago/pendente/atrasado/cancelado", e já apareceram divergências. Um mapa único
elimina a classe de bug em que a tela mostra um estado e o banco tem outro.

Adoção é incremental — macro nova em tela nova, e as antigas migram quando forem
tocadas. Nenhuma tela quebra por não usar.

### Etapa 4 — Responsividade sem marcação duplicada

Substituir o par `d-md-none` / `d-none d-md-block` por **uma marcação só** que
vira card no celular via CSS:

```css
@media (max-width: 767.98px) {
  .u-tabela-cards thead { display: none; }
  .u-tabela-cards tr { display: block; margin-bottom: var(--u-space-3);
                       border: 1px solid var(--u-border); border-radius: var(--u-radius); }
  .u-tabela-cards td { display: flex; justify-content: space-between; border: 0; }
  .u-tabela-cards td::before { content: attr(data-label); font-weight: 600;
                               color: var(--u-text-muted); }
}
```

Cada `<td>` ganha `data-label="Aluno"` e a mesma tabela serve os dois tamanhos.
Isso elimina 20 duplicações e a classe de bug de ids repetidos.

Junto disso, consolidar os quatro `*responsive.css` em um
`static/css/base/responsive.css`, padronizando o breakpoint em **767.98px**
(o corte que já é o real) e mantendo `575.98px` para ajustes finos.

### Etapa 5 — Redução de estilo inline

Os 691 `style="..."` são, na maioria, três coisas: `font-size` miúdo, largura
fixa e cor pontual. Cobrindo com utilitários próprios:

```css
.u-fs-xs { font-size: var(--u-fs-xs); }
.u-fs-sm { font-size: var(--u-fs-sm); }
.u-w-220 { max-width: 220px; }
.u-mono  { font-family: var(--u-font-mono); font-variant-numeric: tabular-nums; }
```

`u-mono` com `tabular-nums` resolve um problema real de leitura: colunas de
dinheiro hoje "dançam" porque os dígitos têm larguras diferentes.

### Etapa 6 — Páginas fora do `base.html`

As 12 páginas públicas (login, pré-cadastro, matrícula) não devem herdar o
chrome do sistema — mas devem herdar **tokens**. Criar `templates/base_publico.html`
com o mesmo `<head>` (fontes, Bootstrap, tokens) e sem sidebar/navbar, e migrá-las
para ele. O visual permanece; o que muda é a fonte da verdade das cores.

---

## 3. Ordem sugerida e risco

| Etapa | Esforço | Risco visual | Reversão |
|---|---|---|---|
| 1. Tokens | baixo | **nenhum** (arquivo só declara) | remover o link |
| 2. Dark mode em arquivo | baixo | nenhum (mesmo CSS, outro lugar) | voltar o bloco |
| 3. Macros Jinja | médio | nenhum até serem usadas | não usar |
| 4. Tabela responsiva | médio | contido: uma tela por vez | por tela |
| 5. Utilitários | baixo | nenhum enquanto aditivo | — |
| 6. `base_publico.html` | médio | contido: 12 páginas | por página |

Nenhuma etapa toca `blueprints/`, rotas, `url_for`, nomes de campo de formulário
ou consultas — o Flask não distingue as mudanças propostas.

---

## 4. Regras para telas novas

1. Cor só via token `--u-*`; nada de hex solto no template.
2. Feedback de ação é `flash()` com uma das quatro categorias (`success`,
   `danger`, `warning`, `info`) — o `base.html` transforma em toast.
3. Tabela usa `u-tabela-cards`; não duplicar marcação por breakpoint.
4. Botão: `btn-sm` como padrão, `btn-outline-*` para ação secundária,
   preenchido só para a ação principal da tela.
5. Card: `card shadow-sm` com `card-body`; `card-header` só quando houver ação
   no cabeçalho.
6. Espaçamento: `mb-3` entre blocos, `g-3` em grid. Sem `style="margin…"`.
7. Ícone sempre `bi bi-*`, com `me-1` quando acompanha texto.

---

*Levantamento e proposta gerados a partir do código em 14/08/2026.*
