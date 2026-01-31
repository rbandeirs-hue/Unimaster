-- Opção no cadastro do desconto: aplicar apenas quando pagamento em dia (sim/não)
-- 1 = sim (só aplica se data_pagamento <= data_vencimento), 0 = não (aplica sempre)
ALTER TABLE descontos
ADD COLUMN aplicar_apenas_pagamento_em_dia TINYINT(1) NOT NULL DEFAULT 1
COMMENT '1=sim só em dia, 0=não aplica sempre'
AFTER ativo;
