-- Modalidade (se não existir) e academia_modalidades para vínculo N:N
-- Execute se as tabelas ainda não existirem

-- Garantir coluna descricao em modalidade (ignore erro se já existir)
-- ALTER TABLE modalidade ADD COLUMN descricao TEXT NULL DEFAULT NULL;

-- Tabela modalidade (pode já existir com colunas diferentes)
CREATE TABLE IF NOT EXISTS modalidade (
    id INT(11) NOT NULL AUTO_INCREMENT,
    nome VARCHAR(150) NOT NULL,
    descricao TEXT NULL DEFAULT NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    id_academia INT(11) NULL DEFAULT NULL,
    criado_em TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_modalidade_academia (id_academia),
    CONSTRAINT fk_modalidade_academia FOREIGN KEY (id_academia) REFERENCES academias (id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela academia_modalidades (vínculo N:N academia <-> modalidade)
CREATE TABLE IF NOT EXISTS academia_modalidades (
    academia_id INT(11) NOT NULL,
    modalidade_id INT(11) NOT NULL,
    PRIMARY KEY (academia_id, modalidade_id),
    INDEX fk_am_modalidade (modalidade_id),
    CONSTRAINT fk_am_academia FOREIGN KEY (academia_id) REFERENCES academias (id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_am_modalidade FOREIGN KEY (modalidade_id) REFERENCES modalidade (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
