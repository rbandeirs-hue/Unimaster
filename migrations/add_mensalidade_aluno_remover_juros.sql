-- Opção de remover juros de uma mensalidade específica (ex: pagou em dia mas informou fora do vencimento)
ALTER TABLE mensalidade_aluno ADD COLUMN remover_juros TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=não aplicar juros/multa nesta cobrança' AFTER observacoes;
