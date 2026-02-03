# Mapeamento de Páginas e Fluxos de Navegação

## ✅ Trabalho Realizado

### Componente Padrão Criado
- ✅ Criado componente `templates/components/botao_voltar.html`
- ✅ Criado CSS padrão `static/css/components/botao_voltar.css`
- ✅ Adicionada função helper `get_back_url_default()` no context processor
- ✅ CSS incluído no `base.html`

### Templates Padronizados (Exemplos)
- ✅ `templates/usuarios/meu_perfil.html`
- ✅ `templates/usuarios/editar_usuario.html`
- ✅ `templates/alunos/cadastro_aluno.html`
- ✅ `templates/painel_aluno/minhas_mensalidades.html`
- ✅ `templates/painel_aluno/minha_turma.html`
- ✅ `templates/painel_aluno/minhas_presencas.html`
- ✅ `templates/calendario/aluno.html`
- ✅ `templates/calendario/aluno_responsavel.html`

### Script de Análise Criado
- ✅ Script `scripts/padronizar_botoes_voltar.py` para identificar templates sem botão voltar

## Padrão de Botão Voltar

### Componente Padrão
Todos os templates devem usar o componente padrão:
```jinja2
{% set back_url = back_url or get_back_url_default() %}
{% include 'components/botao_voltar.html' %}
```

### URLs de Retorno por Modo

#### Modo Admin
- Padrão: `painel.gerenciamento_admin`
- Listas: `painel.gerenciamento_admin`
- Cadastros/Edições: URL da lista correspondente

#### Modo Federação
- Padrão: `federacao.gerenciamento_federacao`
- Listas: `federacao.gerenciamento_federacao`
- Cadastros/Edições: URL da lista correspondente

#### Modo Associação
- Padrão: `associacao.gerenciamento_associacao`
- Listas: `associacao.gerenciamento_associacao`
- Cadastros/Edições: URL da lista correspondente

#### Modo Academia
- Padrão: `academia.painel_academia`
- Listas: `academia.painel_academia`
- Cadastros/Edições: URL da lista correspondente

#### Modo Professor
- Padrão: `professor.painel_professor`
- Listas: `professor.painel_professor`
- Cadastros/Edições: URL da lista correspondente

#### Modo Aluno
- Padrão: `painel_aluno.meu_perfil`
- Listas: `painel_aluno.meu_perfil`
- Cadastros/Edições: `painel_aluno.meu_perfil`

#### Modo Responsável
- Padrão: `painel_responsavel.meu_perfil`
- Listas: `painel_responsavel.meu_perfil`
- Cadastros/Edições: `painel_responsavel.meu_perfil`

## Templates Sem Botão Voltar (30 arquivos)

### Painéis Principais (não precisam de botão voltar)
- painel/painel_federacao.html
- painel/painel_associacao.html
- painel/painel_academia.html
- painel/painel_aluno.html
- painel/gerenciamento_federacao.html
- painel/gerenciamento_associacao.html
- painel/academia_dash.html
- painel/escolher_modo.html
- painel/sem_aluno_vinculado.html
- dashboard.html
- index.html

### Páginas que PRECISAM de botão voltar
- calendario/aluno.html → `painel_aluno.meu_perfil`
- calendario/aluno_responsavel.html → `painel_responsavel.meu_perfil`
- calendario/novo_evento.html → URL da lista de eventos
- calendario/criar_excecao.html → URL da lista de eventos
- calendario/aprovacoes.html → URL da lista de eventos
- calendario/sincronizar.html → URL da lista de eventos
- financeiro/despesas/editar_despesa.html → `financeiro.despesas.lista_despesas`

## Padrão Visual do Botão Voltar

- Classe: `btn btn-outline-secondary btn-voltar-padrao`
- Ícone: `bi bi-arrow-left`
- Texto: "Voltar"
- Largura mínima: 120px
- Sempre alinhado à esquerda em formulários
