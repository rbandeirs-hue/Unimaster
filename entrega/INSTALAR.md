# Unimaster Judô — visual novo: instalação completa

Pacote único, versão atual. Substitui os guias anteriores.

O que vem aqui: a camada visual que muda **todas** as páginas por herança
de CSS, a barra lateral de navegação, o login refeito e uma página já
reescrita por inteiro (Professores).

Se você aplicou uma versão anterior e várias telas não mudaram, o motivo
está no **passo 1.3**: cada página do sistema declara o próprio `<style>`
dentro do template e esse CSS local vence a camada geral.
O arquivo `unimaster-telas.css` resolve isso, página por página.

---

## 1. Copiar os arquivos

| Origem (nesta pasta)                            | Destino no projeto                          | Ação      |
|-------------------------------------------------|---------------------------------------------|-----------|
| `static/css/unimaster.css`                      | `static/css/unimaster.css`                  | novo      |
| `static/css/unimaster-paginas.css`              | `static/css/unimaster-paginas.css`          | novo      |
| `static/css/unimaster-telas.css`                | `static/css/unimaster-telas.css`            | novo      |
| `templates/components/sidebar.html`             | `templates/components/sidebar.html`         | novo      |
| `templates/login.html`                          | `templates/login.html`                      | substitui |
| `templates/professores/lista_professores.html`  | mesmo caminho                               | substitui |

Guarde cópia dos dois que serão substituídos:

```bash
cd /caminho/do/projeto
cp templates/login.html templates/login.html.bak
cp templates/professores/lista_professores.html templates/professores/lista_professores.html.bak
```

**1.1** `unimaster.css` — paleta, tipografia, botões, campos, tabelas,
selos, modais, alertas e o esqueleto da barra lateral.
**1.2** `unimaster-paginas.css` — componentes das telas novas (indicadores,
abas, tabela em cartão, faixinha de graduação, barra fixa de formulário) e
o alinhamento do módulo Financeiro, que tem shell próprio.
**1.3** `unimaster-telas.css` — sobrescreve o CSS interno de cada template:
alunos, turmas, professores, usuários, pré-cadastro, ranking, presença,
calendário, modalidades, eventos, estados vazios e paginação.

---

## 2. Editar `templates/base.html` — três inserções

**2.1 — No `<head>`, depois da linha de `css/components/botao_voltar.css`:**

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ url_for('static', filename='css/unimaster.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/unimaster-paginas.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/unimaster-telas.css') }}">
```

A **ordem importa**: `unimaster-telas.css` por último, e os três depois do
Bootstrap e do `layout.css`.

**2.2 — Logo depois da abertura do `<body ...>`, antes de `<div class="main-content" id="main-content">`:**

```html
{% if current_user.is_authenticated and not layout_embed %}
  {% include 'components/sidebar.html' %}
{% endif %}
```

**2.3 — Dentro de `<div class="navbar-top">`, como primeiro elemento:**

```html
<button class="um-side-toggle d-lg-none" type="button" onclick="umToggleSide()" aria-label="Abrir menu">
  <i class="bi bi-list"></i>
</button>
```

---

## 3. Editar `templates/financeiro/painel/_layout.html` — duas mudanças

O módulo financeiro não herda do `base.html`.

**3.1 — No `<head>`, depois de `financeiro_painel.css`:**

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/unimaster.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/unimaster-paginas.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/unimaster-telas.css') }}">
```

**3.2 — Trocar o tema padrão (duas ocorrências de `'dark'`):**

```js
var t = localStorage.getItem('fp-theme') || 'light';          // script do <head>
pintar(localStorage.getItem('fp-theme') || 'light');          // script do fim
```

Quem já abriu o painel financeiro tem `fp-theme: dark` salvo no navegador;
nesse caso o tema muda ao clicar no botão de sol/lua uma vez.

---

## 4. Reiniciar e limpar cache

```bash
sudo systemctl restart unimaster     # ou deploy/subir.sh
```

No navegador: **Ctrl+Shift+R** (Cmd+Shift+R no Mac).

---

## 5. Conferir tela por tela

- [ ] **Login** — painel escuro à esquerda, formulário à direita, mostrar/ocultar senha.
- [ ] **Toda tela autenticada** — barra lateral escura, item ativo em vermelho.
- [ ] **Celular** — botão de menu abre a gaveta; toque fora fecha.
- [ ] **Painel** — números grandes reduzidos, cartões de 1px sem sombra.
- [ ] **Alunos** — sem sombra nos cartões, botão financeiro sem pulsar, modal com cabeçalho branco e ações em lista.
- [ ] **Turmas** — sem faixa colorida no topo do cartão.
- [ ] **Professores** — página nova em tabela.
- [ ] **Usuários** — abas Ativos/Inativos/Todos escuras quando ativas.
- [ ] **Pré-cadastro** — cartões de link neutros.
- [ ] **Ranking** — pódio com ouro/prata/bronze, 1º maior, barras pretas.
- [ ] **Presença** — indicadores sem ícone, card marcado fica verde.
- [ ] **Calendário** — eventos sem borda colorida, dia atual em vermelho claro.
- [ ] **Modalidades** — cartões sem faixa colorida.
- [ ] **Financeiro** — claro, KPIs em Inter, sem verde-neon.

---

## 6. Se algo não mudou

1. **Ordem dos `<link>`**: `unimaster-telas.css` por último.
2. **O arquivo carregou?** F12 → Network → filtre `unimaster`. 404 = arquivo
   fora de `static/css/`.
3. **Template com `<style>` próprio ainda vencendo**: me diga o arquivo e o
   elemento; acrescento a regra no `unimaster-telas.css`.
4. **Financeiro continua escuro**: console →
   `localStorage.setItem('fp-theme','light'); location.reload();`
5. **Barra lateral não aparece**: confira o include do passo 2.2 e se
   `session['modo_painel']` está preenchido — sem modo, a barra mostra só
   "Painel".

---

## 7. Desenho aprovado que ainda não está em código

O CSS deixa tudo com a aparência nova, mas algumas telas foram
**redesenhadas na estrutura** e isso exige reescrever o template. Ordem
sugerida, do mais simples ao mais arriscado:

1. **Turmas** — cabeçalho, indicadores, barra de ocupação no cartão.
2. **Visitantes** — as quatro páginas (lista, solicitações, pagamentos de
   diária, matrículas) viram uma com abas.
3. **Pré-cadastro** — links públicos em cartões; valor da matrícula e
   cupons em modal.
4. **Presença** — o hub de quatro cartões vira abas: Registrar, Relatório,
   Histórico e Ranking. Inclui as duas telas novas (Relatório e Histórico).
5. **Eventos e Competições** — duas listas quase idênticas viram uma com abas.
6. **Calendário** — agenda do mês ao lado da grade; os seis botões do
   cabeçalho viram dois.
7. **Financeiro** — as oito áreas viram abas dentro do shell do sistema,
   dispensando o layout próprio.
8. **Alunos** — lista em tabela, modal de ações em lista, ficha do aluno
   como página e o cadastro/edição em grade de 12 colunas. É a maior:
   4.700 linhas com muitos modais e JS. Fazer por partes.

Cada uma dessas telas está desenhada e navegável nos arquivos do projeto de
design; quando quiser, gero o template Jinja de uma delas por vez.

---

## 8. O que depende de você

- **Menu lateral dos modos federação, associação, aluno, responsável e
  visitante.** Só admin, academia e professor estão mapeados; os outros
  caem num item "Painel". Preciso dos endpoints de cada um.
- **Painel de pendências** (solicitações, comprovantes, pré-cadastros,
  mensalidades em atraso): não existe hoje em `painel/routes.py` — precisa
  de consultas novas.
- **Botão Voltar**: continua em todas as telas. Quando a barra lateral
  estiver validada, ele sai das que já têm item no menu.
