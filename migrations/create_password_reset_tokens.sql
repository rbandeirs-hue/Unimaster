-- Tabela para armazenar tokens de redefinição de senha
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INT(11) NOT NULL AUTO_INCREMENT,
    usuario_id INT(11) NOT NULL,
    token VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    used TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE INDEX unq_token (token),
    INDEX idx_usuario_id (usuario_id),
    INDEX idx_expires_at (expires_at),
    INDEX idx_used (used),
    CONSTRAINT fk_password_reset_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
