-- Adicionar campo para configuração de exportação em eventos_competicoes
ALTER TABLE eventos_competicoes 
ADD COLUMN IF NOT EXISTS configuracao_exportacao JSON NULL COMMENT 'Configuração de campos e ordem para exportação';
