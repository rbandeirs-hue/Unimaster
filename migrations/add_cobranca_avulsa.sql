-- Cobrança avulsa (uma única cobrança por aluno)
CREATE TABLE IF NOT EXISTS cobranca_avulsa (
    id INT(11) NOT NULL AUTO_INCREMENT,
    aluno_id INT(11) NOT NULL,
    id_academia INT(11) NOT NULL,
    descricao VARCHAR(255) NOT NULL,
    valor DECIMAL(10,2) NOT NULL,
    data_vencimento DATE NOT NULL,
    data_pagamento DATE NULL DEFAULT NULL,
    valor_pago DECIMAL(10,2) NULL DEFAULT NULL,
    status ENUM('pendente','pago','atrasado','cancelado') NOT NULL DEFAULT 'pendente',
    observacoes TEXT NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por INT(11) NULL DEFAULT NULL,
    PRIMARY KEY (id),
    INDEX fk_ca_aluno (aluno_id),
    INDEX fk_ca_academia (id_academia),
    INDEX idx_ca_vencimento (data_vencimento),
    INDEX idx_ca_status (status),
    CONSTRAINT fk_ca_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE,
    CONSTRAINT fk_ca_academia FOREIGN KEY (id_academia) REFERENCES academias (id) ON DELETE CASCADE,
    CONSTRAINT fk_ca_criado_por FOREIGN KEY (criado_por) REFERENCES usuarios (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Vincular receitas a cobrança avulsa (quando pago)
ALTER TABLE receitas ADD COLUMN id_cobranca_avulsa INT(11) NULL DEFAULT NULL;
ALTER TABLE receitas ADD INDEX idx_receita_cobranca_avulsa (id_cobranca_avulsa);
ALTER TABLE receitas ADD CONSTRAINT fk_receita_cobranca_avulsa FOREIGN KEY (id_cobranca_avulsa) REFERENCES cobranca_avulsa (id) ON DELETE SET NULL;
