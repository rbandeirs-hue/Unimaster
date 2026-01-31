-- Criar usuário MySQL para a aplicação Unimaster
-- Execute como root: mysql -u root -p < migrations/create_unimaster_user.sql
-- Ou: mysql -u root -p e cole os comandos abaixo

-- Cria usuário (ajuste a senha conforme necessário)
CREATE USER IF NOT EXISTS 'unimaster'@'localhost' IDENTIFIED BY 'Un1m@ster_2024';
GRANT ALL PRIVILEGES ON unimaster.* TO 'unimaster'@'localhost';
FLUSH PRIVILEGES;
