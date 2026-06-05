-- Credenciais do Asaas por academia (cada academia usa a sua própria conta).
--   asaas_api_key       : chave de API (access_token) da conta Asaas da academia
--   asaas_ambiente      : 'sandbox' (padrão) ou 'production'
--   asaas_webhook_token  : token opcional para validar os webhooks recebidos do Asaas
ALTER TABLE academias ADD COLUMN asaas_api_key VARCHAR(512) NULL;
ALTER TABLE academias ADD COLUMN asaas_ambiente VARCHAR(20) NOT NULL DEFAULT 'sandbox';
ALTER TABLE academias ADD COLUMN asaas_webhook_token VARCHAR(255) NULL;
