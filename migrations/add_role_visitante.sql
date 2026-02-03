-- Adiciona role "Visitante" se não existir
USE unimaster;

-- Verificar se a role já existe
INSERT INTO roles (nome, chave)
SELECT 'Visitante', 'visitante'
WHERE NOT EXISTS (
    SELECT 1 FROM roles WHERE chave = 'visitante' OR nome = 'Visitante'
);
