-- Módulo Eventos e Competições: inscrições com formulário, adesão por academia
USE unimaster;

CREATE TABLE IF NOT EXISTS eventos_competicoes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(200) NOT NULL,
  descricao TEXT NULL,
  id_associacao INT NOT NULL,
  id_formulario INT NULL,
  tipo ENUM('evento','competicao') NOT NULL DEFAULT 'evento',
  data_inicio DATETIME NULL,
  data_fim DATETIME NOT NULL COMMENT 'Após esta data não permite inscrições nem edição',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_ev_comp_assoc FOREIGN KEY (id_associacao) REFERENCES associacoes(id) ON DELETE CASCADE,
  CONSTRAINT fk_ev_comp_form FOREIGN KEY (id_formulario) REFERENCES formularios(id) ON DELETE SET NULL
);

-- Academias que aderiram ao evento (recebem inscrições de alunos)
CREATE TABLE IF NOT EXISTS eventos_competicoes_adesao (
  id INT AUTO_INCREMENT PRIMARY KEY,
  evento_id INT NOT NULL,
  academia_id INT NOT NULL,
  aderiu TINYINT(1) NOT NULL DEFAULT 1,
  data_adesao DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_ev_acad (evento_id, academia_id),
  CONSTRAINT fk_adesao_evento FOREIGN KEY (evento_id) REFERENCES eventos_competicoes(id) ON DELETE CASCADE,
  CONSTRAINT fk_adesao_academia FOREIGN KEY (academia_id) REFERENCES academias(id) ON DELETE CASCADE
);

-- Inscrições: aluno no evento (dados do formulário em JSON)
CREATE TABLE IF NOT EXISTS eventos_competicoes_inscricoes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  evento_id INT NOT NULL,
  academia_id INT NOT NULL,
  aluno_id INT NULL COMMENT 'NULL se inclusão avulsa pelo gestor',
  usuario_inscricao_id INT NULL COMMENT 'Quem fez a inscrição (aluno, responsável ou gestor)',
  dados_form JSON NULL COMMENT 'Valores dos campos do formulário',
  inclusao_avulsa TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 = gestor incluiu manualmente',
  status ENUM('rascunho','confirmada','enviada') NOT NULL DEFAULT 'confirmada',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_insc_evento FOREIGN KEY (evento_id) REFERENCES eventos_competicoes(id) ON DELETE CASCADE,
  CONSTRAINT fk_insc_academia FOREIGN KEY (academia_id) REFERENCES academias(id) ON DELETE CASCADE,
  CONSTRAINT fk_insc_aluno FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE SET NULL
);
