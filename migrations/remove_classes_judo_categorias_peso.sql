-- Script para remover tabelas classes_judo e categorias_peso
-- Após migração completa para tabela categorias

-- Remover tabelas antigas (descomente quando tiver certeza que não são mais necessárias)
-- DROP TABLE IF EXISTS categorias_peso;
-- DROP TABLE IF EXISTS classes_judo;

-- Verificar se as tabelas existem antes de remover
SELECT 'Verificando tabelas a serem removidas...' AS status;

SELECT 
    TABLE_NAME,
    TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME IN ('classes_judo', 'categorias_peso');

-- IMPORTANTE: Descomente as linhas abaixo apenas após confirmar que:
-- 1. Todos os dados foram migrados para a tabela categorias
-- 2. O código não faz mais referência a essas tabelas
-- 3. Você fez backup do banco de dados

-- DROP TABLE IF EXISTS categorias_peso;
-- DROP TABLE IF EXISTS classes_judo;
