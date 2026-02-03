-- Adicionar campo aprovado na tabela aulas_experimentais
-- Para controlar se a solicitação foi aprovada pelo gestor da academia

ALTER TABLE aulas_experimentais 
ADD COLUMN IF NOT EXISTS aprovado TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 = aprovado, 0 = pendente' AFTER presente;

-- Criar índice para melhorar performance nas consultas
CREATE INDEX IF NOT EXISTS idx_ae_aprovado ON aulas_experimentais(aprovado);

-- Atualizar aulas já realizadas como aprovadas (para não quebrar dados existentes)
UPDATE aulas_experimentais 
SET aprovado = 1 
WHERE data_aula <= CURDATE() AND aprovado = 0;
