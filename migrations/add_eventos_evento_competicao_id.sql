-- Vincula eventos do calendário a eventos_competicoes para rastreabilidade
USE unimaster;

ALTER TABLE eventos ADD COLUMN evento_competicao_id INT NULL DEFAULT NULL COMMENT 'ID do evento_competicoes, se origem for Eventos e Competições';
