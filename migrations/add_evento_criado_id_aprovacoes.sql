-- evento_criado_id: vincula aprovação ao evento criado (para cascata no cancelamento)
USE unimaster;

ALTER TABLE eventos_aprovacoes 
ADD COLUMN IF NOT EXISTS evento_criado_id INT(11) NULL DEFAULT NULL 
COMMENT 'ID do evento criado na aprovação (cascata no cancelamento)' 
AFTER observacao;
