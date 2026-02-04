-- Script completo para adicionar todas as colunas e tabelas de taxas
-- Execute este script no MySQL se as colunas não existirem

USE unimaster;

-- ============================================
-- PARTE 1: Colunas básicas de taxa
-- ============================================

-- Verificar e adicionar tem_taxa
SET @existe = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'unimaster' 
    AND TABLE_NAME = 'eventos_competicoes' 
    AND COLUMN_NAME = 'tem_taxa');

SET @sql = IF(@existe = 0,
    'ALTER TABLE eventos_competicoes ADD COLUMN tem_taxa TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''1 = evento tem taxa de inscrição''',
    'SELECT ''Coluna tem_taxa já existe'' AS resultado');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Verificar e adicionar valor_taxa_sugerido
SET @existe2 = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'unimaster' 
    AND TABLE_NAME = 'eventos_competicoes' 
    AND COLUMN_NAME = 'valor_taxa_sugerido');

SET @sql2 = IF(@existe2 = 0,
    'ALTER TABLE eventos_competicoes ADD COLUMN valor_taxa_sugerido DECIMAL(10,2) NULL DEFAULT NULL COMMENT ''Valor sugerido pela associação''',
    'SELECT ''Coluna valor_taxa_sugerido já existe'' AS resultado');
PREPARE stmt2 FROM @sql2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;

-- Verificar e adicionar valor_taxa na adesão
SET @existe3 = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'unimaster' 
    AND TABLE_NAME = 'eventos_competicoes_adesao' 
    AND COLUMN_NAME = 'valor_taxa');

SET @sql3 = IF(@existe3 = 0,
    'ALTER TABLE eventos_competicoes_adesao ADD COLUMN valor_taxa DECIMAL(10,2) NULL DEFAULT NULL COMMENT ''Valor da taxa definido pela academia''',
    'SELECT ''Coluna valor_taxa já existe em eventos_competicoes_adesao'' AS resultado');
PREPARE stmt3 FROM @sql3;
EXECUTE stmt3;
DEALLOCATE PREPARE stmt3;

-- ============================================
-- PARTE 2: Tabelas de pagamentos (opcional)
-- ============================================

-- Tabela de pagamentos de inscrições
CREATE TABLE IF NOT EXISTS eventos_competicoes_inscricoes_pagamentos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    inscricao_id INT NOT NULL COMMENT 'ID da inscrição',
    valor DECIMAL(10,2) NOT NULL COMMENT 'Valor pago pelo aluno',
    pago_academia TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 = academia confirmou pagamento',
    pago_associacao TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 = associação confirmou pagamento geral da academia',
    data_pagamento_academia DATETIME NULL DEFAULT NULL COMMENT 'Data em que academia confirmou',
    data_pagamento_associacao DATETIME NULL DEFAULT NULL COMMENT 'Data em que associação confirmou',
    observacoes TEXT NULL DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_pag_inscricao FOREIGN KEY (inscricao_id) REFERENCES eventos_competicoes_inscricoes(id) ON DELETE CASCADE,
    INDEX idx_pag_inscricao (inscricao_id),
    INDEX idx_pag_academia (pago_academia),
    INDEX idx_pag_associacao (pago_associacao)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela de pagamentos da academia para associação
CREATE TABLE IF NOT EXISTS eventos_competicoes_academia_pagamentos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    evento_id INT NOT NULL,
    academia_id INT NOT NULL,
    valor_total_esperado DECIMAL(10,2) NOT NULL COMMENT 'Valor total esperado (valor_taxa × quantidade de inscritos enviados)',
    valor_pago DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT 'Valor já pago pela academia',
    valor_pendente DECIMAL(10,2) NOT NULL COMMENT 'Valor ainda pendente',
    status ENUM('pendente','parcial','quitado') NOT NULL DEFAULT 'pendente',
    observacoes TEXT NULL DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_pag_acad_evento FOREIGN KEY (evento_id) REFERENCES eventos_competicoes(id) ON DELETE CASCADE,
    CONSTRAINT fk_pag_acad_academia FOREIGN KEY (academia_id) REFERENCES academias(id) ON DELETE CASCADE,
    UNIQUE KEY uk_pag_acad_evento (evento_id, academia_id),
    INDEX idx_pag_acad_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela de histórico de abatimentos
CREATE TABLE IF NOT EXISTS eventos_competicoes_academia_pagamentos_abatimentos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pagamento_id INT NOT NULL COMMENT 'ID do pagamento da academia',
    valor DECIMAL(10,2) NOT NULL COMMENT 'Valor do abatimento',
    data_abatimento DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observacoes TEXT NULL DEFAULT NULL,
    criado_por_usuario_id INT NULL DEFAULT NULL,
    CONSTRAINT fk_abat_pagamento FOREIGN KEY (pagamento_id) REFERENCES eventos_competicoes_academia_pagamentos(id) ON DELETE CASCADE,
    INDEX idx_abat_pagamento (pagamento_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

SELECT 'Migration concluída com sucesso!' AS resultado;
