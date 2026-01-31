-- Adiciona coluna ativo na tabela usuarios (1=ativo, 0=inativo)
-- Executar apenas se a coluna ainda não existir
ALTER TABLE usuarios ADD COLUMN ativo TINYINT(1) NOT NULL DEFAULT 1;
