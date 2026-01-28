# 📋 Requisitos - Campos CATEGORIA e NOME_CATEGORIA em categorias_peso

## ✅ Implementações Realizadas

### 1. **blueprints/aluno/alunos.py**
   - ✅ Adicionado campo `categoria` ao SELECT da tabela `categorias_peso` (linha 268)
   - ✅ O campo já está sendo carregado e disponível no dicionário `cat`

### 2. **blueprints/cadastros/routes.py**
   - ✅ Adicionado mapeamento do campo `categoria` no `resolver_colunas` (linha 280)
   - ✅ Adicionado campo `categoria` ao SELECT (linha 388)
   - ✅ Adicionado campo `categoria` ao UPDATE (linha 339)
   - ✅ Adicionado processamento do campo `categoria` no formulário POST (linha 325)

### 3. **templates/categorias/gerenciar_categorias.html**
   - ✅ Adicionada coluna "Categoria" na tabela
   - ✅ Adicionado campo de input para `categoria` no formulário
   - ✅ Mantida coluna "Nome Categoria" separada

---

## 🔍 Verificações Necessárias

### 1. **Banco de Dados**
   - [ ] Verificar se a tabela `categorias_peso` possui os campos:
     - `CATEGORIA` VARCHAR(30) NULL
     - `NOME_CATEGORIA` VARCHAR(20) NOT NULL
   - [ ] Se os campos não existirem, executar o script SQL abaixo

### 2. **Script SQL de Migração** (se necessário)
```sql
-- Verificar se os campos existem
SHOW COLUMNS FROM categorias_peso LIKE 'CATEGORIA';
SHOW COLUMNS FROM categorias_peso LIKE 'NOME_CATEGORIA';

-- Se CATEGORIA não existir, adicionar:
ALTER TABLE categorias_peso 
ADD COLUMN CATEGORIA VARCHAR(30) NULL DEFAULT NULL 
AFTER ID_CLASSE_FK;

-- Se NOME_CATEGORIA não existir, adicionar:
ALTER TABLE categorias_peso 
ADD COLUMN NOME_CATEGORIA VARCHAR(20) NOT NULL DEFAULT '' 
AFTER CATEGORIA;
```

### 3. **Exibição na Lista de Alunos**
   - [ ] Verificar se deseja exibir também o campo `categoria` além de `nome_categoria`
   - [ ] Localização: `blueprints/aluno/alunos.py` linha 566
   - [ ] Sugestão: `f"Categoria: {cat.get('categoria') or cat.get('nome_categoria') or '-'}"`

---

## 🎨 Melhorias Sugeridas

### 1. **Exibição na Lista de Alunos** (Opcional)
   Atualizar a exibição para mostrar ambos os campos:
   
   **Arquivo:** `blueprints/aluno/alunos.py` (linha ~566)
   
   **Antes:**
   ```python
   partes.append(f"Categoria: {cat.get('nome_categoria') or '-'}")
   ```
   
   **Depois (sugestão):**
   ```python
   categoria_txt = cat.get('categoria') or ''
   nome_categoria_txt = cat.get('nome_categoria') or ''
   if categoria_txt and nome_categoria_txt:
       partes.append(f"Categoria: {categoria_txt} - {nome_categoria_txt}")
   elif nome_categoria_txt:
       partes.append(f"Categoria: {nome_categoria_txt}")
   else:
       partes.append("Categoria: -")
   ```

### 2. **Validação no Formulário** (Opcional)
   Adicionar validação para garantir que `NOME_CATEGORIA` não seja vazio:
   
   **Arquivo:** `blueprints/cadastros/routes.py` (linha ~330)
   
   ```python
   if not all(len(lst) == total for lst in [generos, classes_fk, categorias, nomes, pesos_min, pesos_max]):
       flash("Erro ao salvar pesos: dados inconsistentes.", "danger")
   else:
       # Adicionar validação
       for i in range(total):
           if not nomes[i] or not nomes[i].strip():
               flash(f"Erro: Nome da Categoria é obrigatório na linha {i+1}.", "danger")
               break
       else:
           # Processar atualizações...
   ```

### 3. **Índices no Banco de Dados** (Opcional)
   Considerar adicionar índices para melhorar performance:
   ```sql
   CREATE INDEX idx_categorias_peso_genero ON categorias_peso(GENERO);
   CREATE INDEX idx_categorias_peso_categoria ON categorias_peso(CATEGORIA);
   ```

---

## 🧪 Testes Recomendados

### 1. **Teste de Leitura**
   - [ ] Acessar `/cadastros/categorias/pesos`
   - [ ] Verificar se as colunas "Categoria" e "Nome Categoria" aparecem
   - [ ] Verificar se os dados são carregados corretamente

### 2. **Teste de Edição**
   - [ ] Editar uma categoria de peso
   - [ ] Preencher o campo "Categoria"
   - [ ] Preencher o campo "Nome Categoria"
   - [ ] Salvar e verificar se os dados foram persistidos

### 3. **Teste de Lista de Alunos**
   - [ ] Acessar `/alunos/lista_alunos`
   - [ ] Verificar se a categoria aparece corretamente no modal de detalhes
   - [ ] Verificar alunos com diferentes categorias de peso

### 4. **Teste de Validação**
   - [ ] Tentar salvar sem preencher "Nome Categoria" (deve falhar se NOT NULL)
   - [ ] Verificar comportamento com campo "Categoria" vazio (deve permitir se NULL)

---

## 📝 Estrutura da Tabela Esperada

```sql
CREATE TABLE `categorias_peso` (
    `ID_PESO` INT(11) NOT NULL,
    `GENERO` CHAR(1) NOT NULL COLLATE 'utf8mb4_general_ci',
    `ID_CLASSE_FK` VARCHAR(50) NOT NULL COLLATE 'utf8mb4_general_ci',
    `CATEGORIA` VARCHAR(30) NULL DEFAULT NULL COLLATE 'utf8mb4_general_ci',
    `NOME_CATEGORIA` VARCHAR(20) NOT NULL COLLATE 'utf8mb4_general_ci',
    `PESO_MIN` DECIMAL(5,2) NOT NULL,
    `PESO_MAX` DECIMAL(5,2) NULL DEFAULT NULL,
    PRIMARY KEY (`ID_PESO`) USING BTREE
)
COLLATE='utf8mb4_general_ci'
ENGINE=InnoDB;
```

---

## 🔄 Checklist Final

- [x] Campo `categoria` adicionado ao SELECT em `alunos.py`
- [x] Campo `categoria` adicionado ao mapeamento em `routes.py`
- [x] Campo `categoria` adicionado ao SELECT em `routes.py`
- [x] Campo `categoria` adicionado ao UPDATE em `routes.py`
- [x] Campo `categoria` adicionado ao formulário HTML
- [ ] Verificar estrutura da tabela no banco de dados
- [ ] Executar script SQL se necessário
- [ ] Testar leitura de dados
- [ ] Testar edição de dados
- [ ] Testar exibição na lista de alunos
- [ ] (Opcional) Melhorar exibição na lista de alunos
- [ ] (Opcional) Adicionar validações extras

---

## 📌 Notas Importantes

1. **Campo CATEGORIA**: Pode ser NULL (opcional)
2. **Campo NOME_CATEGORIA**: É NOT NULL (obrigatório)
3. **Compatibilidade**: O código usa mapeamento dinâmico de colunas para suportar variações de nomes
4. **Ordem dos Campos**: CATEGORIA vem antes de NOME_CATEGORIA na estrutura da tabela

---

## 🚀 Próximos Passos

1. Executar verificação do banco de dados
2. Executar script SQL se necessário
3. Realizar testes funcionais
4. Aplicar melhorias opcionais conforme necessidade
5. Documentar qualquer comportamento específico do negócio relacionado aos campos
