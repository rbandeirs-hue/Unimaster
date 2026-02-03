# Padronização de Botões Voltar - Guia Completo

## ✅ O que foi implementado

### 1. Componente Padrão
- **Arquivo**: `templates/components/botao_voltar.html`
- **CSS**: `static/css/components/botao_voltar.css`
- **Função Helper**: `get_back_url_default()` em `app.py`

### 2. Padrão Visual
- Classe: `btn btn-outline-secondary btn-voltar-padrao`
- Ícone: `bi bi-arrow-left`
- Texto: "Voltar"
- Largura mínima: 120px
- Consistente em todos os modos

### 3. URLs de Retorno por Modo
A função `get_back_url_default()` retorna automaticamente:
- **Admin**: `painel.gerenciamento_admin`
- **Federação**: `federacao.gerenciamento_federacao`
- **Associação**: `associacao.gerenciamento_associacao`
- **Academia**: `academia.painel_academia`
- **Professor**: `professor.painel_professor`
- **Aluno**: `painel_aluno.meu_perfil`
- **Responsável**: `painel_responsavel.meu_perfil`

## 📋 Como usar o componente

### Uso básico (usa URL padrão do modo)
```jinja2
{% set back_url = back_url or get_back_url_default() %}
{% include 'components/botao_voltar.html' %}
```

### Uso com URL customizada
```jinja2
{% set back_url = url_for('minha_rota.especifica') %}
{% include 'components/botao_voltar.html' %}
```

### Em formulários (com botão Salvar)
```jinja2
<div class="d-flex justify-content-between gap-2">
  {% set back_url = back_url or get_back_url_default() %}
  {% include 'components/botao_voltar.html' %}
  <button type="submit" class="btn btn-primary">
    <i class="bi bi-check-lg me-1"></i> Salvar
  </button>
</div>
```

## 📊 Status Atual

- **Total de templates**: 127
- **Templates COM botão voltar**: 90
- **Templates SEM botão voltar**: 37 (principalmente painéis principais)
- **Templates usando componente padrão**: 8 (exemplos criados)

## 🔄 Próximos Passos

### Templates que PRECISAM de botão voltar (prioridade alta)
1. `calendario/novo_evento.html` → Lista de eventos
2. `calendario/criar_excecao.html` → Lista de eventos
3. `calendario/aprovacoes.html` → Lista de eventos
4. `calendario/sincronizar.html` → Lista de eventos
5. `financeiro/despesas/editar_despesa.html` → Lista de despesas
6. Todos os formulários de cadastro/edição sem botão voltar

### Templates que NÃO precisam de botão voltar
- Painéis principais (painel_federacao, painel_associacao, etc.)
- Dashboard principal
- Página de escolha de modo
- Index/login

## 🛠️ Script de Análise

Execute para verificar status:
```bash
python3 scripts/padronizar_botoes_voltar.py
```

## 📝 Checklist para Padronização

Para cada template que precisa de botão voltar:

1. [ ] Verificar se já tem botão voltar
2. [ ] Se sim, substituir pelo componente padrão
3. [ ] Se não, adicionar usando o componente padrão
4. [ ] Definir `back_url` apropriada (ou usar padrão)
5. [ ] Verificar se o fluxo de navegação faz sentido
6. [ ] Testar ida e volta entre páginas

## 🔗 Fluxos de Navegação por Módulo

### Módulo Alunos
- Lista → Cadastro → Lista
- Lista → Editar → Lista
- Meu Perfil (Aluno) → Ver Dados → Meu Perfil

### Módulo Usuários
- Lista → Cadastro → Lista
- Lista → Editar → Lista
- Meu Perfil → Editar → Meu Perfil

### Módulo Calendário
- Lista → Novo Evento → Lista
- Lista → Editar → Lista
- Aluno: Meu Perfil → Calendário → Meu Perfil

### Módulo Financeiro
- Dashboard → Mensalidades → Dashboard
- Mensalidades → Cadastrar → Mensalidades
- Mensalidades → Editar → Mensalidades
