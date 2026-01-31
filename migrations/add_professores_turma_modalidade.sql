-- ======================================================
-- Professores, vínculo turma-professor e turma-modalidade
-- Compatível com estrutura existente (turmas, academias, associacoes, modalidade)
-- ======================================================

-- Tabela professores (vinculado à academia e associação)
CREATE TABLE IF NOT EXISTS professores (
    id INT(11) NOT NULL AUTO_INCREMENT,
    nome VARCHAR(150) NOT NULL,
    email VARCHAR(100) NULL DEFAULT NULL,
    telefone VARCHAR(30) NULL DEFAULT NULL,
    id_academia INT(11) NULL DEFAULT NULL,
    id_associacao INT(11) NULL DEFAULT NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX fk_professor_academia (id_academia),
    INDEX fk_professor_associacao (id_associacao),
    CONSTRAINT fk_professor_academia FOREIGN KEY (id_academia) REFERENCES academias (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_professor_associacao FOREIGN KEY (id_associacao) REFERENCES associacoes (id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Turma <-> Professor (N:N)
CREATE TABLE IF NOT EXISTS turma_professor (
    TurmaID INT(11) NOT NULL,
    professor_id INT(11) NOT NULL,
    PRIMARY KEY (TurmaID, professor_id),
    INDEX fk_tp_professor (professor_id),
    CONSTRAINT fk_tp_turma FOREIGN KEY (TurmaID) REFERENCES turmas (TurmaID) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_tp_professor FOREIGN KEY (professor_id) REFERENCES professores (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Turma <-> Modalidade (N:N) — só se a tabela modalidade existir com coluna id
CREATE TABLE IF NOT EXISTS turma_modalidade (
    TurmaID INT(11) NOT NULL,
    modalidade_id INT(11) NOT NULL,
    PRIMARY KEY (TurmaID, modalidade_id),
    INDEX fk_tm_modalidade (modalidade_id),
    CONSTRAINT fk_tm_turma FOREIGN KEY (TurmaID) REFERENCES turmas (TurmaID) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_tm_modalidade FOREIGN KEY (modalidade_id) REFERENCES modalidade (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
