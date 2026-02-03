-- Vínculos N:N: federação, associação e academia com modalidades
-- Federação e Associação: quais modalidades oferecem
-- Academia: já existe academia_modalidades
-- Regras: associação pode habilitar modalidades fora da federação;
--         academia pode ofertar modalidades fora da associação/federação

-- Federação <-> Modalidade
CREATE TABLE IF NOT EXISTS federacao_modalidades (
    federacao_id INT(11) NOT NULL,
    modalidade_id INT(11) NOT NULL,
    PRIMARY KEY (federacao_id, modalidade_id),
    INDEX idx_fm_modalidade (modalidade_id),
    CONSTRAINT fk_fm_federacao FOREIGN KEY (federacao_id) REFERENCES federacoes (id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_fm_modalidade FOREIGN KEY (modalidade_id) REFERENCES modalidade (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Associação <-> Modalidade
CREATE TABLE IF NOT EXISTS associacao_modalidades (
    associacao_id INT(11) NOT NULL,
    modalidade_id INT(11) NOT NULL,
    PRIMARY KEY (associacao_id, modalidade_id),
    INDEX idx_asm_modalidade (modalidade_id),
    CONSTRAINT fk_asm_associacao FOREIGN KEY (associacao_id) REFERENCES associacoes (id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_asm_modalidade FOREIGN KEY (modalidade_id) REFERENCES modalidade (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- academia_modalidades já existe em add_modalidade_academia_modalidades.sql
