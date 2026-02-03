-- Solicitações de aprovação (visita em academia, etc.)
-- Fluxo: aluno solicita -> gestor academia origem aprova -> gestor academia destino aprova (turma + data) -> aluno na lista de chamada

CREATE TABLE IF NOT EXISTS solicitacoes_aprovacao (
    id INT(11) NOT NULL AUTO_INCREMENT,
    tipo VARCHAR(30) NOT NULL DEFAULT 'visita',
    aluno_id INT(11) NOT NULL,
    academia_origem_id INT(11) NOT NULL COMMENT 'Academia do aluno',
    academia_destino_id INT(11) NOT NULL COMMENT 'Academia que vai visitar',
    status VARCHAR(30) NOT NULL DEFAULT 'pendente_origem' COMMENT 'pendente_origem, aprovado_origem, rejeitado_origem, pendente_destino, aprovado_destino, rejeitado_destino',
    aprovado_origem_em DATETIME NULL DEFAULT NULL,
    aprovado_origem_por INT(11) NULL DEFAULT NULL,
    rejeitado_origem_em DATETIME NULL DEFAULT NULL,
    rejeitado_origem_por INT(11) NULL DEFAULT NULL,
    aprovado_destino_em DATETIME NULL DEFAULT NULL,
    aprovado_destino_por INT(11) NULL DEFAULT NULL,
    turma_id INT(11) NULL DEFAULT NULL COMMENT 'Turma na academia destino (quando aprovado)',
    data_visita DATE NULL DEFAULT NULL COMMENT 'Data em que vai frequentar',
    observacao TEXT NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_sol_aluno (aluno_id),
    INDEX idx_sol_academia_origem (academia_origem_id),
    INDEX idx_sol_academia_destino (academia_destino_id),
    INDEX idx_sol_status (status),
    INDEX idx_sol_data_visita (data_visita),
    INDEX idx_sol_turma (turma_id),
    CONSTRAINT fk_sol_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE,
    CONSTRAINT fk_sol_academia_origem FOREIGN KEY (academia_origem_id) REFERENCES academias (id) ON DELETE CASCADE,
    CONSTRAINT fk_sol_academia_destino FOREIGN KEY (academia_destino_id) REFERENCES academias (id) ON DELETE CASCADE,
    CONSTRAINT fk_sol_turma FOREIGN KEY (turma_id) REFERENCES turmas (TurmaID) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
