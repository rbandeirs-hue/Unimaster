-- ======================================================
-- Módulo Financeiro: Mensalidades, Receitas e Despesas
-- Compatível com estrutura existente (alunos, academias, associacoes)
-- ======================================================

-- Tabela mensalidades (planos de mensalidade por academia)
CREATE TABLE IF NOT EXISTS mensalidades (
    id INT(11) NOT NULL AUTO_INCREMENT,
    nome VARCHAR(150) NOT NULL,
    descricao TEXT NULL DEFAULT NULL,
    valor DECIMAL(10,2) NOT NULL,
    id_academia INT(11) NULL DEFAULT NULL,
    id_associacao INT(11) NULL DEFAULT NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX fk_mensalidade_academia (id_academia),
    INDEX fk_mensalidade_associacao (id_associacao),
    CONSTRAINT fk_mensalidade_academia FOREIGN KEY (id_academia) REFERENCES academias (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_mensalidade_associacao FOREIGN KEY (id_associacao) REFERENCES associacoes (id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela mensalidade_aluno (vínculo aluno-mensalidade com histórico de pagamentos)
CREATE TABLE IF NOT EXISTS mensalidade_aluno (
    id INT(11) NOT NULL AUTO_INCREMENT,
    mensalidade_id INT(11) NOT NULL,
    aluno_id INT(11) NOT NULL,
    data_vencimento DATE NOT NULL,
    data_pagamento DATE NULL DEFAULT NULL,
    valor DECIMAL(10,2) NOT NULL,
    valor_pago DECIMAL(10,2) NULL DEFAULT NULL,
    status ENUM('pendente','pago','atrasado','cancelado') NOT NULL DEFAULT 'pendente',
    observacoes TEXT NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX fk_ma_mensalidade (mensalidade_id),
    INDEX fk_ma_aluno (aluno_id),
    INDEX idx_data_vencimento (data_vencimento),
    INDEX idx_status (status),
    CONSTRAINT fk_ma_mensalidade FOREIGN KEY (mensalidade_id) REFERENCES mensalidades (id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_ma_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela receitas (entradas financeiras)
CREATE TABLE IF NOT EXISTS receitas (
    id INT(11) NOT NULL AUTO_INCREMENT,
    descricao VARCHAR(255) NOT NULL,
    valor DECIMAL(10,2) NOT NULL,
    data DATE NOT NULL,
    categoria VARCHAR(100) NULL DEFAULT NULL,
    id_academia INT(11) NULL DEFAULT NULL,
    id_associacao INT(11) NULL DEFAULT NULL,
    id_federacao INT(11) NULL DEFAULT NULL,
    observacoes TEXT NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por INT(11) NULL DEFAULT NULL,
    PRIMARY KEY (id),
    INDEX fk_receita_academia (id_academia),
    INDEX fk_receita_associacao (id_associacao),
    INDEX fk_receita_federacao (id_federacao),
    INDEX idx_data (data),
    INDEX idx_categoria (categoria),
    CONSTRAINT fk_receita_academia FOREIGN KEY (id_academia) REFERENCES academias (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_receita_associacao FOREIGN KEY (id_associacao) REFERENCES associacoes (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_receita_federacao FOREIGN KEY (id_federacao) REFERENCES federacoes (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_receita_usuario FOREIGN KEY (criado_por) REFERENCES usuarios (id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela despesas (saídas financeiras)
CREATE TABLE IF NOT EXISTS despesas (
    id INT(11) NOT NULL AUTO_INCREMENT,
    descricao VARCHAR(255) NOT NULL,
    valor DECIMAL(10,2) NOT NULL,
    data DATE NOT NULL,
    categoria VARCHAR(100) NULL DEFAULT NULL,
    id_academia INT(11) NULL DEFAULT NULL,
    id_associacao INT(11) NULL DEFAULT NULL,
    id_federacao INT(11) NULL DEFAULT NULL,
    observacoes TEXT NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por INT(11) NULL DEFAULT NULL,
    PRIMARY KEY (id),
    INDEX fk_despesa_academia (id_academia),
    INDEX fk_despesa_associacao (id_associacao),
    INDEX fk_despesa_federacao (id_federacao),
    INDEX idx_data (data),
    INDEX idx_categoria (categoria),
    CONSTRAINT fk_despesa_academia FOREIGN KEY (id_academia) REFERENCES academias (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_despesa_associacao FOREIGN KEY (id_associacao) REFERENCES associacoes (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_despesa_federacao FOREIGN KEY (id_federacao) REFERENCES federacoes (id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_despesa_usuario FOREIGN KEY (criado_por) REFERENCES usuarios (id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
