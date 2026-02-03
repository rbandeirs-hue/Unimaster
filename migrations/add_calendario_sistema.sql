-- ============================================================
-- 🗓️ SISTEMA DE CALENDÁRIO HIERÁRQUICO
-- ============================================================

USE unimaster;

-- Tabela de eventos (base para todos os níveis)
CREATE TABLE IF NOT EXISTS eventos (
    id INT(11) NOT NULL AUTO_INCREMENT,
    titulo VARCHAR(200) NOT NULL,
    descricao TEXT NULL DEFAULT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE NULL DEFAULT NULL COMMENT 'Se NULL, evento de 1 dia',
    hora_inicio TIME NULL DEFAULT NULL,
    hora_fim TIME NULL DEFAULT NULL,
    tipo VARCHAR(30) NOT NULL DEFAULT 'evento' COMMENT 'evento, feriado, aula, competicao, exame, outros',
    recorrente TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Se é recorrente (turmas)',
    dias_semana VARCHAR(20) NULL DEFAULT NULL COMMENT 'Para eventos recorrentes: 0,1,2,3,4,5,6',
    nivel VARCHAR(30) NOT NULL COMMENT 'federacao, associacao, academia, turma',
    nivel_id INT(11) NULL DEFAULT NULL COMMENT 'ID da federacao/associacao/academia/turma',
    
    -- Origem do evento (quem criou)
    criado_por_usuario_id INT(11) NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    
    -- Campos específicos para feriados sincronizados
    feriado_nacional TINYINT(1) NOT NULL DEFAULT 0,
    origem_sincronizacao VARCHAR(100) NULL DEFAULT NULL COMMENT 'API, PDF, manual',
    
    -- Status
    status VARCHAR(30) NOT NULL DEFAULT 'ativo' COMMENT 'ativo, cancelado, reprogramado',
    
    -- Turma específica (se for aula)
    turma_id INT(11) NULL DEFAULT NULL,
    
    -- Cores para visualização
    cor VARCHAR(20) NULL DEFAULT NULL COMMENT 'Código hex da cor para display',
    
    PRIMARY KEY (id),
    INDEX idx_evento_data_inicio (data_inicio),
    INDEX idx_evento_data_fim (data_fim),
    INDEX idx_evento_nivel (nivel, nivel_id),
    INDEX idx_evento_tipo (tipo),
    INDEX idx_evento_turma (turma_id),
    INDEX idx_evento_status (status),
    CONSTRAINT fk_evento_turma FOREIGN KEY (turma_id) REFERENCES turmas (TurmaID) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela de aprovações de eventos (fluxo hierárquico)
CREATE TABLE IF NOT EXISTS eventos_aprovacoes (
    id INT(11) NOT NULL AUTO_INCREMENT,
    evento_id INT(11) NOT NULL,
    nivel_aprovador VARCHAR(30) NOT NULL COMMENT 'associacao, academia',
    nivel_aprovador_id INT(11) NOT NULL COMMENT 'ID da associacao/academia que deve aprovar',
    status VARCHAR(30) NOT NULL DEFAULT 'pendente' COMMENT 'pendente, aprovado, rejeitado',
    aprovado_em DATETIME NULL DEFAULT NULL,
    aprovado_por_usuario_id INT(11) NULL DEFAULT NULL,
    rejeitado_em DATETIME NULL DEFAULT NULL,
    rejeitado_por_usuario_id INT(11) NULL DEFAULT NULL,
    observacao TEXT NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (id),
    INDEX idx_aprov_evento (evento_id),
    INDEX idx_aprov_nivel (nivel_aprovador, nivel_aprovador_id),
    INDEX idx_aprov_status (status),
    CONSTRAINT fk_aprov_evento FOREIGN KEY (evento_id) REFERENCES eventos (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela de exceções de eventos recorrentes (ex: cancelamento de aula em feriado)
CREATE TABLE IF NOT EXISTS eventos_excecoes (
    id INT(11) NOT NULL AUTO_INCREMENT,
    evento_id INT(11) NOT NULL COMMENT 'Evento recorrente de origem',
    data_excecao DATE NOT NULL,
    tipo VARCHAR(30) NOT NULL DEFAULT 'cancelamento' COMMENT 'cancelamento, alteracao_horario, outros',
    motivo TEXT NULL DEFAULT NULL,
    nova_hora_inicio TIME NULL DEFAULT NULL,
    nova_hora_fim TIME NULL DEFAULT NULL,
    criado_por_usuario_id INT(11) NULL DEFAULT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (id),
    UNIQUE KEY uk_evento_data (evento_id, data_excecao),
    INDEX idx_exc_evento (evento_id),
    INDEX idx_exc_data (data_excecao),
    CONSTRAINT fk_exc_evento FOREIGN KEY (evento_id) REFERENCES eventos (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- Tabela de sincronização de arquivos (para rastreamento de PDFs sincronizados)
CREATE TABLE IF NOT EXISTS calendario_sincronizacoes (
    id INT(11) NOT NULL AUTO_INCREMENT,
    arquivo_nome VARCHAR(255) NOT NULL,
    arquivo_hash VARCHAR(64) NULL DEFAULT NULL COMMENT 'MD5 do arquivo',
    tipo_sincronizacao VARCHAR(30) NOT NULL COMMENT 'pdf, api, manual',
    nivel VARCHAR(30) NOT NULL COMMENT 'federacao, associacao, academia',
    nivel_id INT(11) NOT NULL,
    eventos_criados INT(11) NOT NULL DEFAULT 0,
    sincronizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sincronizado_por_usuario_id INT(11) NULL DEFAULT NULL,
    
    PRIMARY KEY (id),
    INDEX idx_sync_nivel (nivel, nivel_id),
    INDEX idx_sync_data (sincronizado_em)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
