-- Script para verificar e adicionar colunas de taxa se não existirem
-- Execute este script se as colunas tem_taxa e valor_taxa_sugerido não existirem

USE unimaster;

-- Verificar e adicionar tem_taxa se não existir
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'unimaster' 
    AND TABLE_NAME = 'eventos_competicoes' 
    AND COLUMN_NAME = 'tem_taxa');

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE eventos_competicoes ADD COLUMN tem_taxa TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''1 = evento tem taxa de inscrição''',
    'SELECT ''Coluna tem_taxa já existe'' AS resultado');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Verificar e adicionar valor_taxa_sugerido se não existir
SET @col_exists2 = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'unimaster' 
    AND TABLE_NAME = 'eventos_competicoes' 
    AND COLUMN_NAME = 'valor_taxa_sugerido');

SET @sql2 = IF(@col_exists2 = 0,
    'ALTER TABLE eventos_competicoes ADD COLUMN valor_taxa_sugerido DECIMAL(10,2) NULL DEFAULT NULL COMMENT ''Valor sugerido pela associação (pode ser aumentado pela academia)''',
    'SELECT ''Coluna valor_taxa_sugerido já existe'' AS resultado');
PREPARE stmt2 FROM @sql2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;

-- Verificar e adicionar valor_taxa na tabela de adesão se não existir
SET @col_exists3 = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'unimaster' 
    AND TABLE_NAME = 'eventos_competicoes_adesao' 
    AND COLUMN_NAME = 'valor_taxa');

SET @sql3 = IF(@col_exists3 = 0,
    'ALTER TABLE eventos_competicoes_adesao ADD COLUMN valor_taxa DECIMAL(10,2) NULL DEFAULT NULL COMMENT ''Valor da taxa definido pela academia (pode ser maior que o sugerido)''',
    'SELECT ''Coluna valor_taxa já existe em eventos_competicoes_adesao'' AS resultado');
PREPARE stmt3 FROM @sql3;
EXECUTE stmt3;
DEALLOCATE PREPARE stmt3;

SELECT 'Verificação concluída!' AS resultado;
