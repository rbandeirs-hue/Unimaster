-- Adiciona evento_origem_id para propagar cancelamento em cascata
USE unimaster;

ALTER TABLE eventos ADD COLUMN IF NOT EXISTS evento_origem_id INT(11) NULL DEFAULT NULL 
  COMMENT 'Evento pai (quando criado por aprovação)' AFTER cor;

-- Índice para busca em cascata (MySQL 8.0+ suporta IF NOT EXISTS)
-- ALTER TABLE eventos ADD INDEX idx_evento_origem (evento_origem_id);
