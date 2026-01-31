-- ======================================================
-- Receitas: suporte a cancelamento (mensalidades)
-- ======================================================

ALTER TABLE receitas
ADD COLUMN cancelada TINYINT(1) NOT NULL DEFAULT 0 AFTER criado_por,
ADD COLUMN id_mensalidade_aluno INT(11) NULL DEFAULT NULL AFTER cancelada;

ALTER TABLE receitas
ADD INDEX idx_receita_cancelada (cancelada),
ADD INDEX idx_receita_mensalidade (id_mensalidade_aluno),
ADD CONSTRAINT fk_receita_mensalidade_aluno FOREIGN KEY (id_mensalidade_aluno) REFERENCES mensalidade_aluno (id) ON UPDATE CASCADE ON DELETE SET NULL;
