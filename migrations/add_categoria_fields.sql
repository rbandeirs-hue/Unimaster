-- ======================================================
-- Script de Migração: Adicionar campos CATEGORIA e NOME_CATEGORIA
-- Tabela: categorias_peso
-- Data: 2026-01-28
-- ======================================================

-- Verificar se os campos já existem
SELECT 
    COLUMN_NAME,
    DATA_TYPE,
    IS_NULLABLE,
    COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'categorias_peso'
  AND COLUMN_NAME IN ('CATEGORIA', 'NOME_CATEGORIA');

-- ======================================================
-- Adicionar campo CATEGORIA (se não existir)
-- ======================================================
SET @col_exists = (
    SELECT COUNT(*) 
    FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'categorias_peso'
      AND COLUMN_NAME = 'CATEGORIA'
);

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE categorias_peso 
     ADD COLUMN CATEGORIA VARCHAR(30) NULL DEFAULT NULL 
     AFTER ID_CLASSE_FK',
    'SELECT "Campo CATEGORIA já existe" AS mensagem'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ======================================================
-- Adicionar campo NOME_CATEGORIA (se não existir)
-- ======================================================
SET @col_exists = (
    SELECT COUNT(*) 
    FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'categorias_peso'
      AND COLUMN_NAME = 'NOME_CATEGORIA'
);

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE categorias_peso 
     ADD COLUMN NOME_CATEGORIA VARCHAR(20) NOT NULL DEFAULT "" 
     AFTER CATEGORIA',
    'SELECT "Campo NOME_CATEGORIA já existe" AS mensagem'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ======================================================
-- Verificar estrutura final da tabela
-- ======================================================
DESCRIBE categorias_peso;

-- ======================================================
-- Verificar dados existentes
-- ======================================================
SELECT 
    ID_PESO,
    GENERO,
    ID_CLASSE_FK,
    CATEGORIA,
    NOME_CATEGORIA,
    PESO_MIN,
    PESO_MAX
FROM categorias_peso
LIMIT 10;
