-- Adiciona coluna foto na tabela usuarios (avatar do usuário)
-- Execute: mysql -u user -p database < add_usuarios_foto.sql
-- Se a coluna já existir, ignore o erro.
ALTER TABLE usuarios ADD COLUMN foto VARCHAR(255) NULL DEFAULT NULL;
