-- Tabela presencas (registro de presença por aluno/data)
-- Necessária para: registro_presenca, ata_presenca, historico_presenca

CREATE TABLE IF NOT EXISTS presencas (
    id INT(11) NOT NULL AUTO_INCREMENT,
    aluno_id INT(11) NOT NULL,
    data_presenca DATE NOT NULL,
    responsavel_id INT(11) NULL DEFAULT NULL,
    responsavel_nome VARCHAR(255) NULL DEFAULT NULL,
    presente TINYINT(1) NOT NULL DEFAULT 0,
    registrado_em TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_presenca_aluno_data (aluno_id, data_presenca),
    INDEX idx_data (data_presenca),
    INDEX idx_aluno (aluno_id),
    CONSTRAINT fk_presenca_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE,
    CONSTRAINT fk_presenca_usuario FOREIGN KEY (responsavel_id) REFERENCES usuarios (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
