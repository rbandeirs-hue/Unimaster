-- Suporte a aluno em múltiplas turmas e filtro de presenças por turma
-- 1) Tabela aluno_turmas (N:N aluno x turma)
-- 2) Coluna turma_id em presencas
-- 3) Migração de dados existentes

-- Tabela aluno_turmas
CREATE TABLE IF NOT EXISTS aluno_turmas (
    aluno_id INT(11) NOT NULL,
    TurmaID INT(11) NOT NULL,
    PRIMARY KEY (aluno_id, TurmaID),
    INDEX idx_at_turma (TurmaID),
    CONSTRAINT fk_at_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE,
    CONSTRAINT fk_at_turma FOREIGN KEY (TurmaID) REFERENCES turmas (TurmaID) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Popular a partir da turma atual do aluno
INSERT IGNORE INTO aluno_turmas (aluno_id, TurmaID)
SELECT id, TurmaID FROM alunos WHERE TurmaID IS NOT NULL;

-- Coluna turma_id em presencas
-- Se a coluna já existir, ignorar erro
ALTER TABLE presencas ADD COLUMN turma_id INT(11) NULL DEFAULT NULL COMMENT 'Turma em que a presença foi registrada' AFTER aluno_id;

-- Preencher turma_id nas presenças existentes a partir do aluno
UPDATE presencas p
INNER JOIN alunos a ON a.id = p.aluno_id AND a.TurmaID IS NOT NULL
SET p.turma_id = a.TurmaID
WHERE p.turma_id IS NULL;
