-- Conflitos: aulas que caem em feriados, pendentes de resolução pelo gestor
USE unimaster;

CREATE TABLE IF NOT EXISTS conflitos_aula_feriado (
    id INT(11) NOT NULL AUTO_INCREMENT,
    academia_id INT(11) NOT NULL,
    evento_id INT(11) NOT NULL COMMENT 'Evento recorrente da aula',
    data_conflito DATE NOT NULL,
    feriado_titulo VARCHAR(200) NULL DEFAULT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pendente' COMMENT 'pendente, cancelado, confirmado',
    resolvido_por_usuario_id INT(11) NULL DEFAULT NULL,
    resolvido_em DATETIME NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_conflito (evento_id, data_conflito),
    INDEX idx_conflito_academia (academia_id),
    INDEX idx_conflito_status (status),
    CONSTRAINT fk_conflito_evento FOREIGN KEY (evento_id) REFERENCES eventos (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
