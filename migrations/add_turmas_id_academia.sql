-- Adiciona coluna id_academia à tabela turmas
-- Necessário para filtrar turmas por academia no cadastro de aluno e outras rotas

ALTER TABLE turmas ADD COLUMN id_academia INT(11) NULL DEFAULT NULL;
