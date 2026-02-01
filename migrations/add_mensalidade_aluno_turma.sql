-- Vincular registro de mensalidade_aluno à turma
-- Alunos sem turma matriculada não aparecem na lista de mensalidades

ALTER TABLE mensalidade_aluno ADD COLUMN turma_id INT(11) NULL DEFAULT NULL COMMENT 'Turma à qual a cobrança se refere' AFTER aluno_id;
ALTER TABLE mensalidade_aluno ADD INDEX idx_ma_turma (turma_id);
ALTER TABLE mensalidade_aluno ADD CONSTRAINT fk_ma_turma FOREIGN KEY (turma_id) REFERENCES turmas (TurmaID) ON UPDATE CASCADE ON DELETE SET NULL;
