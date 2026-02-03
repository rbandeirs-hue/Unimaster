-- Tabela para armazenar anexos de eventos/competições
CREATE TABLE IF NOT EXISTS eventos_competicoes_anexos (
    id INT(11) NOT NULL AUTO_INCREMENT,
    evento_id INT(11) NOT NULL,
    nome_arquivo VARCHAR(255) NOT NULL COMMENT 'Nome original do arquivo',
    caminho_arquivo VARCHAR(500) NOT NULL COMMENT 'Caminho relativo do arquivo no servidor',
    tamanho_bytes BIGINT(20) NULL DEFAULT NULL COMMENT 'Tamanho do arquivo em bytes',
    tipo_mime VARCHAR(100) NULL DEFAULT NULL COMMENT 'Tipo MIME do arquivo',
    descricao TEXT NULL DEFAULT NULL COMMENT 'Descrição opcional do anexo',
    criado_por INT(11) NULL DEFAULT NULL COMMENT 'ID do usuário que fez o upload',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_evento_id (evento_id),
    INDEX idx_created_at (created_at),
    CONSTRAINT fk_anexo_evento FOREIGN KEY (evento_id) REFERENCES eventos_competicoes(id) ON DELETE CASCADE,
    CONSTRAINT fk_anexo_usuario FOREIGN KEY (criado_por) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
