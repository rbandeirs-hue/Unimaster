-- Adicionar campo para previsão do próximo exame (mês e ano)
-- O aluno/responsável informa quando pretende realizar o próximo exame
ALTER TABLE alunos ADD COLUMN previsao_proximo_exame DATE NULL DEFAULT NULL COMMENT 'Data prevista (mês/ano) para o próximo exame informada pelo aluno/responsável' AFTER ultimo_exame_faixa;
