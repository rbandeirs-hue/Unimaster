-- Colunas do Asaas (PIX/Boleto) para cobranças avulsas, espelhando mensalidade_aluno.
-- Permite que a cobrança digital valha para todas as cobranças da academia, não só mensalidades.
ALTER TABLE cobranca_avulsa ADD COLUMN asaas_payment_id VARCHAR(500) NULL;
ALTER TABLE cobranca_avulsa ADD COLUMN asaas_tipo VARCHAR(20) NULL;
ALTER TABLE cobranca_avulsa ADD COLUMN asaas_boleto_url VARCHAR(500) NULL;
ALTER TABLE cobranca_avulsa ADD COLUMN asaas_pix_qrcode MEDIUMTEXT NULL;
ALTER TABLE cobranca_avulsa ADD COLUMN asaas_pix_copia_cola VARCHAR(500) NULL;
