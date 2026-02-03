-- ======================================================
-- Script de Migração: Adicionar coluna ATIVO na tabela categorias
-- Data: 2026-01-28
-- ======================================================

-- Verificar se a coluna já existe
SET @col_exists = (
    SELECT COUNT(*) 
    FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'categorias'
      AND COLUMN_NAME = 'ativo'
);

-- Adicionar coluna se não existir
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE categorias 
     ADD COLUMN ativo TINYINT(1) NOT NULL DEFAULT 1 COMMENT ''1=ativo, 0=inativo''',
    'SELECT "Coluna ativo já existe" AS mensagem'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Verificar estrutura final
DESCRIBE categorias;
