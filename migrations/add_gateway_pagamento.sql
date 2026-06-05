-- Multi-gateway de cobrança online por academia (um gateway ativo por vez).
-- gateway_pagamento: '', 'asaas', 'mercadopago', 'infinitepay', 'cora'
-- As colunas asaas_* das cobranças passam a guardar o resultado de QUALQUER gateway
-- (payment id, tipo, link/boleto, pix). A coluna `gateway` registra qual gerou.
ALTER TABLE academias ADD COLUMN gateway_pagamento VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE academias ADD COLUMN mercadopago_access_token VARCHAR(255) NULL;
ALTER TABLE academias ADD COLUMN infinitepay_handle VARCHAR(120) NULL;

ALTER TABLE mensalidade_aluno ADD COLUMN gateway VARCHAR(20) NULL;
ALTER TABLE cobranca_avulsa ADD COLUMN gateway VARCHAR(20) NULL;

-- Academias que já usavam Asaas migram para o novo seletor automaticamente.
UPDATE academias SET gateway_pagamento = 'asaas'
WHERE asaas_habilitado = 1 AND asaas_api_key IS NOT NULL AND asaas_api_key <> '';
