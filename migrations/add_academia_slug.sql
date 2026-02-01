-- Slug para URL amigável (ex: /precadastro/form/academia-judo-centro)
ALTER TABLE academias ADD COLUMN slug VARCHAR(150) NULL UNIQUE;
