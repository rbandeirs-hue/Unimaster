-- ======================================================
-- Adicionar suporte a comprovantes e aprovação de pagamentos
-- ======================================================

-- Adicionar campos na tabela mensalidade_aluno para comprovantes e aprovação
ALTER TABLE mensalidade_aluno 
ADD COLUMN IF NOT EXISTS comprovante_url VARCHAR(255) NULL DEFAULT NULL AFTER observacoes,
ADD COLUMN IF NOT EXISTS data_pagamento_informado DATE NULL DEFAULT NULL AFTER comprovante_url,
ADD COLUMN IF NOT EXISTS status_pagamento ENUM('pendente','pendente_aprovacao','pago','cancelado','rejeitado') NOT NULL DEFAULT 'pendente' AFTER status,
ADD COLUMN IF NOT EXISTS aprovado_por INT(11) NULL DEFAULT NULL AFTER status_pagamento,
ADD COLUMN IF NOT EXISTS data_aprovacao TIMESTAMP NULL DEFAULT NULL AFTER aprovado_por,
ADD COLUMN IF NOT EXISTS observacao_aprovacao TEXT NULL DEFAULT NULL AFTER data_aprovacao;

-- Criar índices se não existirem
CREATE INDEX IF NOT EXISTS idx_status_pagamento ON mensalidade_aluno(status_pagamento);

-- Adicionar foreign key se não existir
ALTER TABLE mensalidade_aluno
ADD CONSTRAINT fk_ma_aprovado_por FOREIGN KEY (aprovado_por) REFERENCES usuarios (id) ON UPDATE CASCADE ON DELETE SET NULL;

-- Atualizar registros existentes: se status = 'pago', status_pagamento também deve ser 'pago'
UPDATE mensalidade_aluno SET status_pagamento = 'pago' WHERE status = 'pago' AND (status_pagamento IS NULL OR status_pagamento = 'pendente');
