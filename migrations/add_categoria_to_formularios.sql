-- Script para adicionar campo categoria aos formulários que têm peso e data_nascimento
-- mas não têm categoria

-- Adicionar categoria após peso nos formulários que têm peso e data_nascimento
INSERT INTO formularios_campos (formulario_id, campo_chave, label, ordem)
SELECT 
    fc_peso.formulario_id,
    'categoria' AS campo_chave,
    'Categoria' AS label,
    MAX(fc_peso.ordem) + 1 AS ordem
FROM formularios_campos fc_peso
INNER JOIN formularios_campos fc_data ON fc_data.formulario_id = fc_peso.formulario_id 
    AND fc_data.campo_chave = 'data_nascimento'
LEFT JOIN formularios_campos fc_cat ON fc_cat.formulario_id = fc_peso.formulario_id 
    AND fc_cat.campo_chave = 'categoria'
WHERE fc_peso.campo_chave = 'peso'
    AND fc_cat.id IS NULL  -- Não tem categoria ainda
GROUP BY fc_peso.formulario_id;
