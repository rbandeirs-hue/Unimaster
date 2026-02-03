-- Modalidades: visibilidade publica ou privada
USE unimaster;

ALTER TABLE modalidade 
  ADD COLUMN IF NOT EXISTS visibilidade VARCHAR(20) NOT NULL DEFAULT 'publica' 
    COMMENT 'publica: todos veem; privada: só dono' AFTER ativo,
  ADD COLUMN IF NOT EXISTS id_associacao INT(11) NULL DEFAULT NULL 
    COMMENT 'Dono quando privada (nível associação)' AFTER visibilidade,
  ADD COLUMN IF NOT EXISTS id_academia INT(11) NULL DEFAULT NULL 
    COMMENT 'Dono quando privada (nível academia)' AFTER id_associacao;
