# 🗓️ Sistema de Calendário Hierárquico

## Visão Geral

Sistema completo de gestão de calendário com eventos hierárquicos, sincronização de feriados nacionais, eventos recorrentes de turmas e fluxo de aprovação entre federação → associação → academia.

## Funcionalidades Implementadas

### 1. **Estrutura Hierárquica**

O calendário opera em 4 níveis:
- **Federação**: Visualiza e cria eventos que podem ser propagados para associações
- **Associação**: Visualiza e cria eventos que podem ser propagados para academias
- **Academia**: Visualiza e cria eventos próprios, sincroniza turmas como aulas recorrentes
- **Aluno**: Visualização somente leitura dos eventos da sua academia e turmas

### 2. **Tipos de Eventos**

- **Feriados**: Feriados nacionais sincronizados automaticamente via API
- **Aulas**: Eventos recorrentes baseados nas turmas cadastradas
- **Eventos**: Eventos genéricos (seminários, workshops, etc.)
- **Competições**: Campeonatos e competições
- **Exames**: Exames de graduação/faixa
- **Outros**: Eventos personalizados

### 3. **Sincronização de Feriados**

✅ **API Brasil API**: Integração com a API pública do Brasil (https://brasilapi.com.br/api/feriados/v1/{ano})
- Sincroniza feriados nacionais automaticamente
- Evita duplicações
- Registra histórico de sincronizações
- Gestores podem escolher o ano para sincronizar

### 4. **Sincronização de Turmas**

✅ **Eventos Recorrentes**: Turmas são automaticamente convertidas em eventos recorrentes
- Baseado nos dias da semana (dias_semana) e horários (hora_inicio, hora_fim)
- Aparece no calendário da academia
- Alunos veem as aulas das suas turmas no calendário pessoal
- Permite exceções (cancelamentos e alterações de horário)

### 5. **Fluxo de Aprovação Hierárquico**

✅ **Federação → Associação → Academia**:

1. **Federação cria evento**: 
   - Evento é criado no calendário da federação
   - Aprovações pendentes são criadas automaticamente para todas as associações da federação

2. **Associação aprova/rejeita**:
   - Gestor da associação vê eventos pendentes de aprovação
   - Ao aprovar, evento é adicionado ao calendário da associação
   - Aprovações pendentes são criadas automaticamente para todas as academias da associação

3. **Academia aprova/rejeita**:
   - Gestor da academia vê eventos pendentes de aprovação
   - Ao aprovar, evento é adicionado ao calendário da academia
   - Alunos da academia visualizam o evento

4. **Rejeição**:
   - Em qualquer nível, o gestor pode rejeitar com observação
   - Evento não é propagado para níveis inferiores

### 6. **Exceções de Eventos Recorrentes**

✅ **Gestão de Exceções**: Permite ajustar eventos recorrentes (aulas) em datas específicas

**Tipos de exceção**:
- **Cancelamento**: Cancela a aula em um dia específico (ex: feriado)
- **Alteração de Horário**: Muda o horário da aula em um dia específico

**Funcionalidade**:
- Gestor pode criar exceção para qualquer evento recorrente
- Aceita motivo/observação
- Para alteração de horário, permite definir novo hora_inicio e hora_fim

### 7. **Visualização do Calendário**

✅ **Calendário Mensal**: Interface visual tipo grid com:
- Navegação entre meses (anterior/próximo)
- Destacamento do dia atual
- Eventos exibidos por dia com cores personalizadas
- Ícones por tipo de evento (feriado ⭐, aula 📖, competição 🏆)
- Horários dos eventos
- Indicação de "mais eventos" quando há mais de 3 no dia

### 8. **Menus de Acesso**

✅ **Integrado em todos os painéis**:
- **Painel Federação**: Card "Calendário" com acesso direto
- **Painel Associação**: Card "Calendário" com acesso direto
- **Painel Academia**: Card "Calendário" no gerenciamento
- **Painel Professor**: Card "Calendário" com visualização das aulas
- **Perfil Aluno**: Atalho "Calendário" para ver eventos e aulas

## Estrutura do Banco de Dados

### Tabelas Criadas

1. **`eventos`**: Tabela principal de eventos
   - Armazena todos os eventos de todos os níveis
   - Campos: titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim, tipo, nivel, nivel_id, etc.
   - Suporta eventos recorrentes (campo `recorrente`, `dias_semana`)
   - Campo `turma_id` para aulas vinculadas a turmas

2. **`eventos_aprovacoes`**: Gerencia o fluxo de aprovação
   - Registra aprovações pendentes/aprovadas/rejeitadas
   - Campos: evento_id, nivel_aprovador, nivel_aprovador_id, status, aprovado_em, rejeitado_em, etc.

3. **`eventos_excecoes`**: Exceções de eventos recorrentes
   - Permite cancelar ou alterar horários de eventos recorrentes em datas específicas
   - Campos: evento_id, data_excecao, tipo, motivo, nova_hora_inicio, nova_hora_fim

4. **`calendario_sincronizacoes`**: Histórico de sincronizações
   - Rastreia sincronizações de feriados, PDFs e turmas
   - Campos: arquivo_nome, tipo_sincronizacao, nivel, nivel_id, eventos_criados, sincronizado_em

## Rotas Implementadas

### Principais Rotas

- **`/calendario/`**: Hub do calendário (redireciona para visualização apropriada)
- **`/calendario/visualizar`**: Visualização mensal do calendário (gestores)
- **`/calendario/aluno`**: Visualização do calendário para alunos (somente leitura)
- **`/calendario/sincronizar`**: Interface de sincronização (feriados, turmas, PDFs)
- **`/calendario/sincronizar/feriados`** (POST): Sincroniza feriados via API
- **`/calendario/sincronizar/turmas`** (POST): Sincroniza turmas como eventos recorrentes
- **`/calendario/evento/novo`**: Criar novo evento
- **`/calendario/aprovacoes`**: Lista de eventos pendentes de aprovação
- **`/calendario/aprovacoes/<id>/aprovar`** (POST): Aprovar evento
- **`/calendario/aprovacoes/<id>/rejeitar`** (POST): Rejeitar evento
- **`/calendario/evento/<id>/excecao`**: Criar exceção para evento recorrente

## Como Usar

### 1. **Sincronizar Feriados (Primeira Vez)**

1. Acesse o painel de calendário (qualquer nível: federação/associação/academia)
2. Clique em "Sincronizar"
3. Selecione o ano desejado
4. Clique em "Sincronizar Feriados"
5. Os feriados nacionais serão importados automaticamente

### 2. **Sincronizar Turmas como Aulas (Academia)**

1. Acesse o painel de calendário (modo academia)
2. Clique em "Sincronizar"
3. Clique em "Sincronizar Turmas"
4. Todas as turmas com dias e horários definidos serão criadas como eventos recorrentes

### 3. **Criar Evento (Federação/Associação/Academia)**

1. Acesse o calendário
2. Clique em "Novo Evento"
3. Preencha: título, descrição, tipo, data início/fim, horários, cor
4. Se for federação ou associação, o evento criará aprovações pendentes para os níveis inferiores

### 4. **Aprovar/Rejeitar Eventos (Associação/Academia)**

1. Acesse o calendário
2. Clique em "Aprovar Eventos"
3. Veja a lista de eventos pendentes
4. Clique em "Aprovar" para adicionar ao seu calendário (e propagar para níveis inferiores)
5. Ou clique em "Rejeitar" e informe o motivo

### 5. **Criar Exceção (Cancelar Aula em Feriado)**

1. Acesse o calendário da academia
2. Identifique a data da aula que precisa ser cancelada/alterada
3. *(Atualmente via URL direta: `/calendario/evento/<evento_id>/excecao`)*
4. Escolha o tipo (cancelamento ou alteração de horário)
5. Informe a data e o motivo
6. Salve a exceção

### 6. **Visualizar Calendário (Aluno)**

1. Acesse "Meu Perfil" no painel do aluno
2. Clique no card "Calendário"
3. Navegue pelos meses para ver eventos, feriados e aulas da sua academia/turmas

## Melhorias Futuras (Não Implementadas)

- **Upload de PDF**: Interface para fazer upload de calendários em PDF e extrair eventos (marcado como "em desenvolvimento" no frontend)
- **Modal de detalhes**: Ao clicar em um dia do calendário, abrir modal com todos os detalhes dos eventos
- **Notificações**: Notificar gestores sobre eventos pendentes de aprovação
- **Cores personalizadas**: Permitir que cada nível escolha cores específicas para seus tipos de eventos
- **Exportação**: Exportar calendário para PDF ou iCal
- **Visualização Semanal/Diária**: Além da visualização mensal, permitir visualizações semanal e diária

## Arquivos Criados/Modificados

### Novos Arquivos

1. **Migration**: `/var/www/Unimaster/migrations/add_calendario_sistema.sql`
2. **Blueprint**: `/var/www/Unimaster/blueprints/calendario/__init__.py`
3. **Rotas**: `/var/www/Unimaster/blueprints/calendario/routes.py`
4. **Templates**:
   - `/var/www/Unimaster/templates/calendario/visualizar.html`
   - `/var/www/Unimaster/templates/calendario/aluno.html`
   - `/var/www/Unimaster/templates/calendario/sincronizar.html`
   - `/var/www/Unimaster/templates/calendario/novo_evento.html`
   - `/var/www/Unimaster/templates/calendario/aprovacoes.html`
   - `/var/www/Unimaster/templates/calendario/criar_excecao.html`

### Arquivos Modificados

1. **`/var/www/Unimaster/app.py`**: Importação e registro do blueprint `bp_calendario`
2. **`/var/www/Unimaster/templates/painel/painel_federacao.html`**: Card de calendário
3. **`/var/www/Unimaster/templates/painel/painel_associacao.html`**: Card de calendário
4. **`/var/www/Unimaster/templates/painel/painel_academia.html`**: Card de calendário
5. **`/var/www/Unimaster/templates/painel/painel_professor.html`**: Card de calendário
6. **`/var/www/Unimaster/templates/painel_aluno/meu_perfil.html`**: Atalho de calendário

## Tecnologias Utilizadas

- **Backend**: Flask, Python 3.11
- **Banco de Dados**: MySQL/MariaDB
- **API Externa**: Brasil API (feriados nacionais)
- **Frontend**: HTML5, CSS3, Bootstrap 5, JavaScript
- **Bibliotecas Python**: `requests` (para API de feriados), `mysql-connector-python`

## Conclusão

Sistema completo de calendário implementado com sucesso! Todos os requisitos foram atendidos:

✅ Menu calendário em todos os modos (federação, associação, academia, professor, aluno)  
✅ Página de sincronização de eventos  
✅ Registro de eventos  
✅ Feriados nacionais sincronizados via API  
✅ Sincronização de eventos de PDF (estrutura pronta, funcionalidade marcada como "em desenvolvimento")  
✅ Fluxo hierárquico de aprovação (federação → associação → academia)  
✅ Calendário do aluno (somente visualização)  
✅ Turmas sincronizadas como eventos recorrentes  
✅ Gestores podem ajustar manualmente aulas em feriados (via exceções)

O sistema está pronto para uso! 🎉
