# Análise — Módulos Perdidos (Recuperação via Transcrições)

## Resumo

Os módulos abaixo existiam no projeto e foram perdidos. As transcrições do Cursor contêm evidências e implementações que permitem recuperá-los.

---

## 1. FINANCEIRO (`blueprints/financeiro/routes.py`)

**Status:** ARQUIVO AUSENTE (existe apenas `__init__.py`)

**Evidência nas transcrições:** Mais de 150 referências. O arquivo tinha ~2300+ linhas.

**Rotas documentadas:**
- `GET/POST /` e `/dashboard` — Dashboard com resumo
- `POST /set-academia` — Define academia ativa na session
- `GET /descontos` — Lista descontos
- `GET /mensalidades` — Lista planos de mensalidade
- `GET /mensalidades/alunos` — Lista mensalidades por aluno
- `POST /mensalidades/alunos/pagar/<id>` — Registrar pagamento
- `GET /receitas` — Lista receitas
- `GET /despesas` — Lista despesas
- `GET /alunos` — Lista alunos com mensalidades
- `GET/POST /mensalidades/vincular` — Vincular mensalidade a alunos
- `GET/POST /mensalidades/gerar-anual` — Gerar mensalidades anuais
- `GET /mensalidades/aprovacoes` — Pagamentos pendentes
- `GET/POST /configuracoes` — Menu de configurações
- `GET/POST /cora/config` — Config Cora
- `GET/POST /inter/config` — Config Banco Inter
- `GET/POST /asaas/config` — Config Asaas
- `POST /cora/webhook`, `/inter/webhook`, `/asaas/webhook` — Webhooks

**Helpers:** `_get_academias_ids`, `_get_academias_para_filtro`, `_get_academia_id_filtro`, `_calcular_desconto_aluno`

**Templates existentes:** `templates/financeiro/` (descontos, despesas, mensalidades, receitas, alunos)

---

## 2. PRESENÇAS (`blueprints/presencas/`)

**Status:** EXISTE `presencas.py` — verificar se está completo

**Evidência:** O módulo inclui agrupamento por modalidade (`_modalidades_academia`, `_turma_modalidades`).

**Registro no app:** Não está em `app.py` atual — precisa ser registrado.

---

## 3. PROFESSORES (`blueprints/professores/routes.py`)

**Status:** ARQUIVO AUSENTE (existe apenas `__init__.py`)

**Evidência:** Rotas como `@bp_professores.route("/academia/<int:academia_id>")` — CRUD de professores por academia.

---

## 4. MODALIDADES / CONFIGURAÇÕES (`blueprints/configuracoes/`)

**Status:** AUSENTE (apenas `__pycache__`)

**Evidência:** Blueprint `configuracoes` foi criado com:
- Hub: `GET /configuracoes`
- `GET /configuracoes/modalidades` — Lista modalidades
- `GET/POST /configuracoes/modalidades/cadastro`
- `GET/POST /configuracoes/modalidades/<id>/vincular`
- `POST /configuracoes/modalidades/<id>/toggle`

**Templates:** `configuracoes/hub.html`, `modalidades_lista.html`, `modalidades_cadastro.html`, `modalidades_vincular.html`

---

## 5. PRÉ-CADASTRO (`blueprints/precadastro/`)

**Status:** AUSENTE (apenas `__pycache__`)

**Evidência:** Blueprint `bp_precadastro` — pré-cadastro público por token da academia.

---

## 6. PAINEL RESPONSÁVEL (`blueprints/painel_responsavel/`)

**Status:** AUSENTE (apenas `__pycache__`)

**Evidência:** Mencionado no fluxo RBAC (modo "responsavel").

---

## 7. SERVICES (`services/`)

**Status:** PASTA VAZIA (apenas `__pycache__`)

**Evidência:** `asaas_service.py`, `cora_service.py`, `inter_service.py`, `manual_pdf.py` — integrações com gateways de pagamento.

---

## Ordem de registro no app.py (versão completa)

```python
from blueprints.presencas.presencas import bp_presencas
from blueprints.professores.routes import bp_professores
from blueprints.configuracoes import bp_configuracoes
from blueprints.financeiro.routes import bp_financeiro
from blueprints.precadastro import bp_precadastro

app.register_blueprint(bp_presencas)
app.register_blueprint(bp_professores)
app.register_blueprint(bp_configuracoes)
app.register_blueprint(bp_financeiro)
app.register_blueprint(bp_precadastro)
# + painel_responsavel se existir
```

---

## Prioridade de recuperação

1. **Financeiro** — Módulo mais crítico (templates e migrations existem)
2. **Presenças** — Registrar no app (arquivo pode estar completo)
3. **Configurações/Modalidades** — Admin, modalidades
4. **Professores** — CRUD professores
5. **Pré-cadastro** — Formulário público
6. **Painel Responsável** — Modo responsável
7. **Services** — Asaas, Cora, Inter (integrações)

---

*Documento gerado a partir da análise das transcrições em `/root/.cursor/projects/var-www-Unimaster/agent-transcripts/`*
