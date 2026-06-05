-- Vincula a receita à cobrança avulsa de origem (espelha id_mensalidade_aluno).
-- Necessário para a baixa automática (webhook Asaas) de avulsas lançar a receita.
ALTER TABLE receitas ADD COLUMN id_cobranca_avulsa INT(11) NULL;
ALTER TABLE receitas ADD INDEX idx_receitas_cobranca_avulsa (id_cobranca_avulsa);
