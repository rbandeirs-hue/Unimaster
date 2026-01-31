-- ======================================================
-- Módulo Descontos: cadastro de descontos e vínculo ao aluno
-- Regra: desconto só é aplicado se pagamento for em dia (data_pagamento <= data_vencimento)
-- ======================================================

-- Tabela descontos (tipos de desconto por academia)
CREATE TABLE IF NOT EXISTS descontos (
    id INT(11) NOT NULL AUTO_INCREMENT,
    nome VARCHAR(150) NOT NULL,
    descricao TEXT NULL DEFAULT NULL,
    tipo ENUM('percentual', 'valor_fixo') NOT NULL DEFAULT 'percentual',
    valor DECIMAL(10,2) NOT NULL COMMENT 'Percentual (0-100) ou valor fixo em R$',
    id_academia INT(11) NULL DEFAULT NULL,
    id_associacao INT(11) NULL DEFAULT NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX fk_desconto_academia (id_academia),
    INDEX fk_desconto_associacao (id_associacao),
    CONSTRAINT fk_desconto_academia FOREIGN KEY (id_academia) REFERENCES academias (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_desconto_associacao FOREIGN KEY (id_associacao) REFERENCES associacoes (id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela aluno_desconto (vínculo aluno x desconto, com vigência)
CREATE TABLE IF NOT EXISTS aluno_desconto (
    id INT(11) NOT NULL AUTO_INCREMENT,
    aluno_id INT(11) NOT NULL,
    desconto_id INT(11) NOT NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    data_inicio DATE NULL DEFAULT NULL,
    data_fim DATE NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_aluno_desconto (aluno_id, desconto_id),
    INDEX fk_ad_aluno (aluno_id),
    INDEX fk_ad_desconto (desconto_id),
    CONSTRAINT fk_ad_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_ad_desconto FOREIGN KEY (desconto_id) REFERENCES descontos (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Colunas em mensalidade_aluno para registrar desconto aplicado no pagamento
ALTER TABLE mensalidade_aluno
ADD COLUMN IF NOT EXISTS valor_original DECIMAL(10,2) NULL DEFAULT NULL COMMENT 'Valor antes do desconto' AFTER valor_pago,
ADD COLUMN IF NOT EXISTS desconto_aplicado DECIMAL(10,2) NULL DEFAULT 0 COMMENT 'Valor do desconto aplicado' AFTER valor_original,
ADD COLUMN IF NOT EXISTS id_desconto INT(11) NULL DEFAULT NULL AFTER desconto_aplicado;

ALTER TABLE mensalidade_aluno
ADD INDEX IF NOT EXISTS idx_ma_id_desconto (id_desconto),
ADD CONSTRAINT fk_ma_desconto FOREIGN KEY (id_desconto) REFERENCES descontos (id) ON UPDATE CASCADE ON DELETE SET NULL;
