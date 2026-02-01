-- Tabela responsavel_alunos: vincula usuário (responsável) a um ou mais alunos
-- Usado no modo responsável para exibir dados dos alunos vinculados
CREATE TABLE IF NOT EXISTS responsavel_alunos (
  usuario_id INT(11) NOT NULL,
  aluno_id INT(11) NOT NULL,
  PRIMARY KEY (usuario_id, aluno_id),
  CONSTRAINT fk_ra_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE,
  CONSTRAINT fk_ra_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE
) ENGINE=InnoDB;
