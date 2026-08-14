-- Credenciais do Cora separadas por ambiente.
--
-- O Cora emite Client ID + certificado + chave DIFERENTES para stage e para
-- produção: a credencial de stage devolve 401 invalid_client no host de
-- produção. Antes havia um trio só, então alternar o ambiente exigia recolar
-- tudo. As colunas originais passam a valer para STAGE (é o que já estava
-- gravado nelas) e este trio guarda as de PRODUÇÃO.
ALTER TABLE academias
    ADD COLUMN cora_client_id_prod   VARCHAR(120) NULL,
    ADD COLUMN cora_certificate_prod TEXT         NULL,
    ADD COLUMN cora_private_key_prod TEXT         NULL;
