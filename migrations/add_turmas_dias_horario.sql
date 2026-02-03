-- Dias da semana (1=Seg, 2=Ter, 3=Qua, 4=Qui, 5=Sex, 6=Sab, 0=Dom) e horário de treino
ALTER TABLE turmas ADD COLUMN dias_semana VARCHAR(20) NULL DEFAULT NULL COMMENT 'Ex: 1,3,5 = Seg,Qua,Sex';
ALTER TABLE turmas ADD COLUMN hora_inicio TIME NULL DEFAULT NULL;
ALTER TABLE turmas ADD COLUMN hora_fim TIME NULL DEFAULT NULL;
