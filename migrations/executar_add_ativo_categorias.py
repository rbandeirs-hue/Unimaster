#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para adicionar coluna ATIVO na tabela categorias
"""
import sys
import os

# Adicionar o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection

def executar_migracao():
    """Executa a migração para adicionar coluna ativo na tabela categorias"""
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
              AND TABLE_NAME = 'categorias'
              AND COLUMN_NAME = 'ativo'
        """)
        result = cursor.fetchone()
        col_exists = result['count'] > 0 if result else False
        
        if col_exists:
            print("✓ Coluna 'ativo' já existe na tabela categorias")
        else:
            # Adicionar coluna
            cursor.execute("""
                ALTER TABLE categorias 
                ADD COLUMN ativo TINYINT(1) NOT NULL DEFAULT 1 
                COMMENT '1=ativo, 0=inativo'
            """)
            conn.commit()
            print("✓ Coluna 'ativo' adicionada com sucesso na tabela categorias")
        
        # Verificar estrutura
        cursor.execute("DESCRIBE categorias")
        colunas = cursor.fetchall()
        print("\nEstrutura da tabela categorias:")
        print("-" * 80)
        for col in colunas:
            if col['Field'] == 'ativo':
                print(f"✓ {col['Field']:20} {col['Type']:20} {col['Null']:5} {col['Default']}")
            else:
                print(f"  {col['Field']:20} {col['Type']:20} {col['Null']:5} {col['Default']}")
        
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
    print("Executando migração: add_ativo_categorias")
    print("=" * 80)
    sucesso = executar_migracao()
    print("=" * 80)
    if sucesso:
        print("Migração concluída com sucesso!")
        sys.exit(0)
    else:
        print("Migração falhou!")
        sys.exit(1)
