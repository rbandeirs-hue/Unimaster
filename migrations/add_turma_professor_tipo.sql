-- Adiciona coluna tipo em turma_professor: responsavel (1) ou auxiliar (vários)
ALTER TABLE turma_professor ADD COLUMN tipo VARCHAR(20) NOT NULL DEFAULT 'auxiliar';
-- Considera o primeiro professor (menor professor_id) de cada turma como responsável (dados existentes)
UPDATE turma_professor t1
JOIN (SELECT TurmaID, MIN(professor_id) AS pid FROM turma_professor GROUP BY TurmaID) t2
  ON t1.TurmaID = t2.TurmaID AND t1.professor_id = t2.pid
SET t1.tipo = 'responsavel';
