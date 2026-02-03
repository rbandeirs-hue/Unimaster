-- ======================================================
-- Sistema de Visitantes e Aulas Experimentais
-- ======================================================

-- Tabela visitantes
CREATE TABLE IF NOT EXISTS visitantes (
    id INT(11) NOT NULL AUTO_INCREMENT,
    usuario_id INT(11) NULL DEFAULT NULL,
    nome VARCHAR(150) NOT NULL,
    email VARCHAR(100) NULL DEFAULT NULL,
    telefone VARCHAR(30) NULL DEFAULT NULL,
    data_nascimento DATE NULL DEFAULT NULL,
    foto VARCHAR(255) NULL DEFAULT NULL,
    id_academia INT(11) NOT NULL,
    aulas_experimentais_realizadas INT(11) NOT NULL DEFAULT 0,
    aulas_experimentais_permitidas INT(11) NULL DEFAULT NULL COMMENT 'Limite configurado pela academia',
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX fk_visitante_usuario (usuario_id),
    INDEX fk_visitante_academia (id_academia),
    INDEX idx_email (email),
    CONSTRAINT fk_visitante_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE SET NULL,
    CONSTRAINT fk_visitante_academia FOREIGN KEY (id_academia) REFERENCES academias (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela aulas_experimentais (registro de aulas experimentais realizadas)
CREATE TABLE IF NOT EXISTS aulas_experimentais (
    id INT(11) NOT NULL AUTO_INCREMENT,
    visitante_id INT(11) NOT NULL,
    turma_id INT(11) NOT NULL,
    data_aula DATE NOT NULL,
    presente TINYINT(1) NOT NULL DEFAULT 1,
    observacoes TEXT NULL DEFAULT NULL,
    registrado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    registrado_por INT(11) NULL DEFAULT NULL COMMENT 'ID do usuário que registrou',
    PRIMARY KEY (id),
    UNIQUE KEY uk_visitante_turma_data (visitante_id, turma_id, data_aula),
    INDEX idx_visitante (visitante_id),
    INDEX idx_turma (turma_id),
    INDEX idx_data (data_aula),
    CONSTRAINT fk_ae_visitante FOREIGN KEY (visitante_id) REFERENCES visitantes (id) ON DELETE CASCADE,
    CONSTRAINT fk_ae_turma FOREIGN KEY (turma_id) REFERENCES turmas (TurmaID) ON DELETE CASCADE,
    CONSTRAINT fk_ae_usuario FOREIGN KEY (registrado_por) REFERENCES usuarios (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Adicionar campo aulas_experimentais_permitidas na tabela academias
ALTER TABLE academias 
ADD COLUMN aulas_experimentais_permitidas INT(11) NULL DEFAULT 3 COMMENT 'Número de aulas experimentais permitidas para visitantes (NULL = ilimitado)';

-- Tabela visitante_turmas (N:N visitante x turma para aulas experimentais)
CREATE TABLE IF NOT EXISTS visitante_turmas (
    visitante_id INT(11) NOT NULL,
    turma_id INT(11) NOT NULL,
    data_inscricao DATE NOT NULL DEFAULT (CURRENT_DATE),
    PRIMARY KEY (visitante_id, turma_id),
    INDEX idx_turma (turma_id),
    CONSTRAINT fk_vt_visitante FOREIGN KEY (visitante_id) REFERENCES visitantes (id) ON DELETE CASCADE,
    CONSTRAINT fk_vt_turma FOREIGN KEY (turma_id) REFERENCES turmas (TurmaID) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
