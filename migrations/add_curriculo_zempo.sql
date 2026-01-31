-- ======================================================
-- Currículo do atleta: link Zempo + competições + eventos
-- ======================================================
-- 1) Link Zempo: adicionar coluna link_zempo em alunos (se não existir)
-- 2) Tabelas: aluno_competicoes, aluno_eventos

-- Link do perfil Zempo (executar uma vez; se já existir, ignorar)
-- ALTER TABLE alunos ADD COLUMN link_zempo VARCHAR(500) NULL DEFAULT NULL COMMENT 'URL perfil Zempo';

-- Participações em competições (sincronizado do Zempo ou manual)
CREATE TABLE IF NOT EXISTS aluno_competicoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    aluno_id INT NOT NULL,
    colocacao VARCHAR(100) NULL,
    competicao VARCHAR(255) NULL,
    ambito VARCHAR(100) NULL,
    local_texto VARCHAR(255) NULL,
    data_competicao DATE NULL,
    categoria VARCHAR(255) NULL,
    ordem INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ac_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE,
    INDEX idx_ac_aluno (aluno_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Participações em eventos (sincronizado do Zempo ou manual)
CREATE TABLE IF NOT EXISTS aluno_eventos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    aluno_id INT NOT NULL,
    evento VARCHAR(255) NULL,
    atividade VARCHAR(255) NULL,
    ambito VARCHAR(100) NULL,
    local_texto VARCHAR(255) NULL,
    data_evento DATE NULL,
    ordem INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ae_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE,
    INDEX idx_ae_aluno (aluno_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
