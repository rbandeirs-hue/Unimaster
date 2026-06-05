-- Habilitar/desabilitar a cobrança digital (Asaas - PIX/Boleto) por academia.
-- 0 = desabilitado (padrão), 1 = habilitado.
ALTER TABLE academias ADD COLUMN asaas_habilitado TINYINT(1) NOT NULL DEFAULT 0;
