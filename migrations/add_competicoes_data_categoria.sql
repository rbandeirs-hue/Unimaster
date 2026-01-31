-- Adiciona data_competicao e categoria em aluno_competicoes (sincronização Zempo)
-- Executar uma vez. Se der erro "Duplicate column", as colunas já existem — ignore.

ALTER TABLE aluno_competicoes ADD COLUMN data_competicao DATE NULL DEFAULT NULL COMMENT 'Data da competição' AFTER local_texto;
ALTER TABLE aluno_competicoes ADD COLUMN categoria VARCHAR(255) NULL DEFAULT NULL COMMENT 'Categoria (ex: Júnior Masculino Ligeiro -60kg)' AFTER data_competicao;
