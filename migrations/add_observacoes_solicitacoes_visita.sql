-- Adicionar campos de observação separados para origem e destino
-- Observação origem: para professor de origem adicionar observação para destino
-- Observação destino: para professor de destino adicionar observação para aluno/origem

ALTER TABLE solicitacoes_aprovacao 
ADD COLUMN IF NOT EXISTS observacao_origem TEXT NULL DEFAULT NULL COMMENT 'Observação do gestor de origem para o destino' AFTER observacao,
ADD COLUMN IF NOT EXISTS observacao_destino TEXT NULL DEFAULT NULL COMMENT 'Observação do gestor de destino para aluno/origem' AFTER observacao_origem;
