-- Tipo de vigência do vínculo aluno-desconto:
-- parcial = aplica no período normalmente
-- integral = só aplica se todas as mensalidades anteriores (data_vencimento < atual) estiverem pagas
ALTER TABLE aluno_desconto
ADD COLUMN tipo_vigencia ENUM('parcial', 'integral') NOT NULL DEFAULT 'parcial'
COMMENT 'parcial=normal, integral=só se mensalidades anteriores pagas'
AFTER data_fim;
