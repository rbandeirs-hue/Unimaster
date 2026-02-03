#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para adicionar coluna APROVADO na tabela aulas_experimentais
"""
import sys
import os

# Adicionar o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection

def executar_migracao():
    """Executa a migração para adicionar coluna aprovado na tabela aulas_experimentais"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Verificar se a coluna já existe
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'aulas_experimentais'
              AND COLUMN_NAME = 'aprovado'
        """)
        result = cursor.fetchone()
        col_exists = result['count'] > 0 if result else False
        
        if col_exists:
            print("✓ Coluna 'aprovado' já existe na tabela aulas_experimentais")
        else:
            # Adicionar coluna
            cursor.execute("""
                ALTER TABLE aulas_experimentais 
                ADD COLUMN aprovado TINYINT(1) NOT NULL DEFAULT 0 
                COMMENT '1 = aprovado, 0 = pendente' AFTER presente
            """)
            conn.commit()
            print("✓ Coluna 'aprovado' adicionada com sucesso na tabela aulas_experimentais")
        
        # Criar índice
        cursor.execute("SHOW INDEX FROM aulas_experimentais WHERE Key_name = 'idx_ae_aprovado'")
        if not cursor.fetchone():
            cursor.execute("CREATE INDEX idx_ae_aprovado ON aulas_experimentais(aprovado)")
            conn.commit()
            print("✓ Índice 'idx_ae_aprovado' criado com sucesso")
        else:
            print("✓ Índice 'idx_ae_aprovado' já existe")
        
        # Atualizar aulas já realizadas como aprovadas
        cursor.execute("""
            UPDATE aulas_experimentais 
            SET aprovado = 1 
            WHERE data_aula <= CURDATE() AND aprovado = 0
        """)
        rows_updated = cursor.rowcount
        conn.commit()
        if rows_updated > 0:
            print(f"✓ {rows_updated} aulas já realizadas foram marcadas como aprovadas")
        else:
            print("✓ Nenhuma aula precisou ser atualizada")
        
        return True
        
    except Exception as e:
        print(f"✗ Erro ao executar migração: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    print("Executando migração: add_aprovado_aulas_experimentais")
    print("=" * 60)
    if executar_migracao():
        print("=" * 60)
        print("✓ Migração concluída com sucesso!")
    else:
        print("=" * 60)
        print("✗ Migração falhou!")
        sys.exit(1)
