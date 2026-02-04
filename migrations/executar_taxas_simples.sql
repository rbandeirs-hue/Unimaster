-- Script simples para adicionar colunas de taxa
-- Execute este script no MySQL para criar as colunas necessárias

USE unimaster;

-- Adicionar coluna tem_taxa se não existir
ALTER TABLE eventos_competicoes 
ADD COLUMN IF NOT EXISTS tem_taxa TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 = evento tem taxa de inscrição';

-- Adicionar coluna valor_taxa_sugerido se não existir  
ALTER TABLE eventos_competicoes 
ADD COLUMN IF NOT EXISTS valor_taxa_sugerido DECIMAL(10,2) NULL DEFAULT NULL COMMENT 'Valor sugerido pela associação';

-- Adicionar coluna valor_taxa na tabela de adesão se não existir
ALTER TABLE eventos_competicoes_adesao 
ADD COLUMN IF NOT EXISTS valor_taxa DECIMAL(10,2) NULL DEFAULT NULL COMMENT 'Valor da taxa definido pela academia';

SELECT 'Colunas de taxa adicionadas com sucesso!' AS resultado;
