-- Campos para controle de acesso e responsável no pré-cadastro
-- Execute: mysql -u user -p database < add_precadastro_acesso.sql
-- (ignore erro se colunas já existirem)
ALTER TABLE pre_cadastro
  ADD COLUMN acesso_sistema VARCHAR(20) DEFAULT 'aluno',
  ADD COLUMN responsavel_eh_proprio TINYINT(1) DEFAULT 0,
  ADD COLUMN email_acesso VARCHAR(255) NULL;
