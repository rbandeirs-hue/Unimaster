-- Status: Paga, Pendente, Atrasada, Aguardando Confirmação
-- Atualização automática: pendente -> atrasado quando vencido (feita na aplicação)
-- Comprovante e comentário do aluno

ALTER TABLE mensalidade_aluno 
MODIFY COLUMN status ENUM('pendente','pago','atrasado','aguardando_confirmacao','cancelado') NOT NULL DEFAULT 'pendente';

-- Comentário informado pelo aluno ao enviar comprovante
-- comprovante_url vem de add_comprovantes_aprovacao; se não existir, adicione:
-- ALTER TABLE mensalidade_aluno ADD COLUMN comprovante_url VARCHAR(255) NULL;
ALTER TABLE mensalidade_aluno ADD COLUMN comentario_informado TEXT NULL DEFAULT NULL;
