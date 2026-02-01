-- Juros e multas por atraso nos planos de mensalidade
-- Multa: 2% ao mês | Juros: 0,033% ao dia (~1% ao mês)
ALTER TABLE mensalidades ADD COLUMN aplicar_juros_multas TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=ativa multa e juros por atraso' AFTER ativo;
ALTER TABLE mensalidades ADD COLUMN percentual_multa_mes DECIMAL(5,2) NOT NULL DEFAULT 2.00 COMMENT 'Multa % ao mês' AFTER aplicar_juros_multas;
ALTER TABLE mensalidades ADD COLUMN percentual_juros_dia DECIMAL(5,4) NOT NULL DEFAULT 0.0333 COMMENT 'Juros % ao dia (~1% ao mês)' AFTER percentual_multa_mes;
