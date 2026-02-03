-- Tabela formularios: formulários de cadastro baseados no modelo do aluno
-- Federação cria formulários (id_federacao); Associação cria formulários (id_associacao)
CREATE TABLE IF NOT EXISTS formularios (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(200) NOT NULL,
  id_federacao INT NULL,
  id_associacao INT NULL,
  ativo TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT chk_formulario_owner CHECK (
    (id_federacao IS NOT NULL AND id_associacao IS NULL) OR
    (id_federacao IS NULL AND id_associacao IS NOT NULL)
  )
);

-- Tabela formularios_campos: quais campos do aluno o formulário inclui
CREATE TABLE IF NOT EXISTS formularios_campos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  formulario_id INT NOT NULL,
  campo_chave VARCHAR(80) NOT NULL,
  label VARCHAR(150) NULL,
  obrigatorio TINYINT(1) NOT NULL DEFAULT 0,
  ordem INT NOT NULL DEFAULT 0,
  CONSTRAINT fk_form_campos_form FOREIGN KEY (formulario_id) REFERENCES formularios(id) ON DELETE CASCADE,
  UNIQUE KEY uk_form_campo (formulario_id, campo_chave)
);
