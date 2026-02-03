-- Sincroniza usuarios_academias a partir de usuarios.id_academia
-- Para usuários que têm id_academia mas ainda não estão em usuarios_academias
-- Execute: mysql -u user -p database < sync_usuarios_academias_from_id_academia.sql
USE unimaster;

INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id)
SELECT u.id, u.id_academia
FROM usuarios u
WHERE u.id_academia IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM usuarios_academias ua
    WHERE ua.usuario_id = u.id AND ua.academia_id = u.id_academia
  );
