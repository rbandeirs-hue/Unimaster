-- ======================================================
-- Script de Migração: Adicionar coluna PREVISAO na tabela faixas_judo
-- Data: 2026-01-28
-- ======================================================

-- Adicionar coluna previsao se não existir
ALTER TABLE faixas_judo 
ADD COLUMN IF NOT EXISTS previsao TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1=previsão habilitada, 0=previsão desabilitada';

-- Atualizar todos os registros existentes para 1 (true) caso algum tenha NULL ou 0
UPDATE faixas_judo SET previsao = 1 WHERE previsao IS NULL OR previsao = 0;
