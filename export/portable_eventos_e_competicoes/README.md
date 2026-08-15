# Pacote portável: `eventos_competicoes` + `competicoes`

Esta pasta contém uma cópia dos **blueprints**, **templates**, **CSS/JS** e **utils** usados pelo fluxo de competições (inscrições, chaves, súmulas, placar judô, resultados) para levar a outro projeto Flask.

- **Cópia física:** subpasta `arquivos/` (espelho parcial do repositório).
- **Este README:** análise de separação dos blueprints e passos de integração, incluindo uso com o **Cursor**.

---

## 1. Os blueprints estão bem separados?

**Em estrutura de código, sim:** cada blueprint vive na sua pasta (`blueprints/eventos_competicoes/`, `blueprints/competicoes/`), com `Blueprint` e `url_prefix` próprios, e **não há `import` de um blueprint dentro do outro**.

**Em responsabilidade de negócio, estão distribuídos de forma intencional:**

| Blueprint | `url_prefix` | Papel principal |
|-----------|--------------|-----------------|
| `eventos_competicoes` | `/eventos-competicoes` | CRUD de evento/competição, listas, inscrições (público, academia, associação), consolidar, importação Excel, categorias por aproximação, painel, **placar judô** (lista, controle, monitor, APIs, WebSocket), anexos, impressão/exportação. |
| `competicoes` | `/competicoes` | Operações de judô “pós-inscrição”: categorias (modo padrão), **chaves**, geração/visualização de chave, **súmulas**, fluxo de **placar** (criação de lutas no módulo competições), **resultados**. |

**O acoplamento existe por URLs e dados, não por módulos Python:**

- `competicoes/routes.py` chama `url_for("eventos_competicoes.…")` para voltar ao painel, listas, placar em tempo real e template `eventos_competicoes/placar_chave_interativa.html`.
- `eventos_competicoes/routes.py` chama `url_for("competicoes.…")` (ex.: `chaves_evento` após recalcular categorias por aproximação com `retorno=chaves`).
- `templates/components/menu_competicao.html` é a **ponte visual**: abas que misturam rotas dos dois blueprints (e `embed=1` para iframe).

**Conclusão:** a separação em **dois blueprints** é coerente (evento/inscrição vs. chaves/súmulas/placar-lista), mas **não são independentes**: em outro sistema você deve implantar **os dois** (ou refatorar o menu e os `url_for`).

**Dependências opcionais no restante do monólito:** vários templates de `competicoes` referenciam `url_for('externo.…')` (TV, acesso externo). Se o projeto destino não tiver o blueprint `externo`, remova ou substitua esses links após a cópia.

---

## 2. O que está em `arquivos/`

```
arquivos/
  blueprints/competicoes/       # routes.py + __init__.py
  blueprints/eventos_competicoes/
  templates/eventos_competicoes/
  templates/competicoes/
  templates/components/       # menu_competicao.html, botao_voltar.html
  static/css/base/layout.css   # classe body.layout-embed, container full width
  static/css/components/botao_voltar.css
  static/css/pages/competicao-dashboard.css
  static/css/placar_judo.css, bracket.css, bracket_light.css, judo_chave_visual.css
  static/js/placar_judo_controle.js, placar_judo_monitor.js, bracket_unimaster.js, judo_chave_visual.js
  utils/formularios_campos.py, judo_chaves_inteligentes.py, judo_bracket.py, judo_bracket_visual.py
```

**Não incluído** (o projeto destino já deve ter equivalente ou você adapta):

- `templates/base.html` (todos os templates estendem `base.html`).
- `config.py` / `get_db_connection`, modelos de usuário, `flask_login`, registro em `app.py`, `SocketIO`, migrations/SQL.

---

## 3. Dependências Python (além do Flask usual)

- **openpyxl** — importação de inscrições e geração de planilha modelo (`pip install openpyxl`).
- **Flask-Login** — `login_required`, `current_user`, papéis (`has_role`, etc.) como no projeto de origem.
- **Flask-SocketIO** — placar em tempo real e handlers no `app.py` de origem; se não usar SocketIO, será preciso desativar ou stubar o que chama `get_socketio()` / `emit`.

---

## 4. Integração no outro sistema (passo a passo)

1. **Copiar** o conteúdo de `arquivos/` para a raiz do projeto Flask (mesmos caminhos relativos: `blueprints/`, `templates/`, `static/`, `utils/`).

2. **Mesclar `base.html`** (ou criar um `base_competicao.html` e alterar `{% extends %}` em massa). No mínimo, o layout de origem usa:
   - `layout_embed` no `<body>` e no `container-fluid` (ver `templates/base.html` no repositório Unimaster: `layout-embed`, bloco `container_extra_class`).
   - Links para `css/base/layout.css` e `css/components/botao_voltar.css` (ou copie os estilos necessários).

3. **Context processor / `before_request`:** garantir que os templates recebam `layout_embed` quando `request.args.get('embed') == '1'` (como no app de origem), senão o menu duplica dentro do iframe.

4. **Registrar blueprints** no `app.py` (ou factory), na ordem habitual:

   ```python
   from blueprints.eventos_competicoes import bp_eventos_competicoes
   from blueprints.competicoes import bp_competicoes

   app.register_blueprint(bp_eventos_competicoes)
   app.register_blueprint(bp_competicoes)
   ```

   Nomes dos blueprints devem permanecer `eventos_competicoes` e `competicoes` para que `url_for` e o menu funcionem.

5. **`get_db_connection`:** os `routes.py` importam `from config import get_db_connection`. No destino, implemente a mesma API (context manager ou função que devolve cursor/dict) apontando para as tabelas esperadas (`eventos_competicoes`, `eventos_competicoes_inscricoes`, `judo_lutas`, `categorias`, `academias`, etc.).

6. **Sessão `modo_painel`:** várias telas checam `session.get('modo_painel') == 'associacao'` (e similares). Replique a lógica de modo de painel ou simplifique as condições no destino.

7. **Import circular opcional:** `eventos_competicoes/routes.py` pode importar `socketio` ou `iniciar_broadcast_periodico` de `app` em runtime; no destino, prefira expor SocketIO só via `current_app.extensions['socketio']` para evitar ciclo.

8. **Smoke test:** após login, abrir `/eventos-competicoes/`, criar/editar competição, abrir `/eventos-competicoes/<id>/painel-competicao`, navegar abas para `/competicoes/...` e `/eventos-competicoes/...` com e sem `?embed=1`.

---

## 5. Como usar o Cursor no projeto de destino

1. **Abrir o repositório de destino** no Cursor e, se quiser comparar, abrir esta pasta `export/portable_eventos_e_competicoes/arquivos` em outra janela ou anexar arquivos ao chat.

2. **Arrastar ou @mencionar** pastas no prompt, por exemplo:
   - `@arquivos/blueprints/eventos_competicoes/routes.py`
   - `@app.py` do destino  
   Peça: *“Registre os blueprints `bp_eventos_competicoes` e `bp_competicoes` como no Unimaster e ajuste imports.”*

3. **Tarefa guiada em etapas** (um prompt por etapa reduz erro):
   - Etapa A: copiar arquivos e `git status`.
   - Etapa B: alinhar `base.html` / `layout_embed`.
   - Etapa C: `config.get_db_connection` e variáveis de ambiente.
   - Etapa D: remover ou stubar `externo` nos templates copiados.

4. **Regras do projeto:** se quiser persistir convenções, crie uma rule no Cursor (por exemplo: “sempre preservar nomes `eventos_competicoes` e `competicoes` nos `url_for`”).

---

## 6. Referência rápida no monólito de origem

- Registro: `app.py` (imports `bp_eventos_competicoes`, `bp_competicoes` e `register_blueprint`).
- Prefixos: `eventos_competicoes` → `/eventos-competicoes`; `competicoes` → `/competicoes`.

Para atualizar este pacote no futuro, reaplique o script de cópia ou sincronize manualmente os mesmos caminhos listados na seção 2.
