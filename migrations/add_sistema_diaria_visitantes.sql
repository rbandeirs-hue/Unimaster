-- ======================================================
-- Sistema de Diária e Mensalidade para Visitantes
-- ======================================================

-- Adicionar campo aprovado na tabela aulas_experimentais (se não existir)
SET @exist := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_SCHEMA = DATABASE() 
               AND TABLE_NAME = 'aulas_experimentais' 
               AND COLUMN_NAME = 'aprovado');
SET @sqlstmt := IF(@exist = 0, 
    'ALTER TABLE aulas_experimentais ADD COLUMN aprovado TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''0 = pendente, 1 = aprovado''', 
    'SELECT ''Campo aprovado já existe''');
PREPARE stmt FROM @sqlstmt;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Adicionar campo valor_diaria na tabela academias (se não existir)
SET @exist := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_SCHEMA = DATABASE() 
               AND TABLE_NAME = 'academias' 
               AND COLUMN_NAME = 'valor_diaria_visitante');
SET @sqlstmt := IF(@exist = 0, 
    'ALTER TABLE academias ADD COLUMN valor_diaria_visitante DECIMAL(10,2) NULL DEFAULT NULL COMMENT ''Valor da diária para visitantes que ultrapassarem o limite de aulas gratuitas''', 
    'SELECT ''Campo valor_diaria_visitante já existe''');
PREPARE stmt FROM @sqlstmt;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Tabela para pagamentos de diária de visitantes
CREATE TABLE IF NOT EXISTS visitante_pagamentos_diaria (
    id INT(11) NOT NULL AUTO_INCREMENT,
    visitante_id INT(11) NOT NULL,
    aula_experimental_id INT(11) NOT NULL,
    valor DECIMAL(10,2) NOT NULL,
    comprovante VARCHAR(255) NULL DEFAULT NULL COMMENT 'Caminho do arquivo do comprovante',
    status VARCHAR(30) NOT NULL DEFAULT 'pendente' COMMENT 'pendente, pago, confirmado',
    observacoes TEXT NULL DEFAULT NULL,
    pagamento_informado_em TIMESTAMP NULL DEFAULT NULL,
    pagamento_confirmado_em TIMESTAMP NULL DEFAULT NULL,
    confirmado_por INT(11) NULL DEFAULT NULL COMMENT 'ID do usuário que confirmou o pagamento',
    receita_id INT(11) NULL DEFAULT NULL COMMENT 'ID da receita gerada ao confirmar',
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_visitante (visitante_id),
    INDEX idx_aula (aula_experimental_id),
    INDEX idx_status (status),
    INDEX idx_receita (receita_id),
    CONSTRAINT fk_vpd_visitante FOREIGN KEY (visitante_id) REFERENCES visitantes (id) ON DELETE CASCADE,
    CONSTRAINT fk_vpd_aula FOREIGN KEY (aula_experimental_id) REFERENCES aulas_experimentais (id) ON DELETE CASCADE,
    CONSTRAINT fk_vpd_usuario FOREIGN KEY (confirmado_por) REFERENCES usuarios (id) ON DELETE SET NULL,
    CONSTRAINT fk_vpd_receita FOREIGN KEY (receita_id) REFERENCES receitas (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela para solicitações de mensalidade de visitantes
CREATE TABLE IF NOT EXISTS visitante_solicitacoes_mensalidade (
    id INT(11) NOT NULL AUTO_INCREMENT,
    visitante_id INT(11) NOT NULL,
    mensalidade_id INT(11) NOT NULL COMMENT 'ID da mensalidade escolhida',
    status VARCHAR(30) NOT NULL DEFAULT 'pendente' COMMENT 'pendente, aprovado, rejeitado',
    observacoes TEXT NULL DEFAULT NULL,
    solicitado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    aprovado_em TIMESTAMP NULL DEFAULT NULL,
    aprovado_por INT(11) NULL DEFAULT NULL COMMENT 'ID do usuário que aprovou',
    PRIMARY KEY (id),
    INDEX idx_visitante (visitante_id),
    INDEX idx_mensalidade (mensalidade_id),
    INDEX idx_status (status),
    CONSTRAINT fk_vsm_visitante FOREIGN KEY (visitante_id) REFERENCES visitantes (id) ON DELETE CASCADE,
    CONSTRAINT fk_vsm_mensalidade FOREIGN KEY (mensalidade_id) REFERENCES mensalidades (id) ON DELETE CASCADE,
    CONSTRAINT fk_vsm_usuario FOREIGN KEY (aprovado_por) REFERENCES usuarios (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
