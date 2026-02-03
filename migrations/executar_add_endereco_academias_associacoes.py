#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para adicionar campos de endereço nas tabelas academias e associacoes
"""
import sys
import os

# Adicionar o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection

def executar_migracao():
    """Executa a migração para adicionar campos de endereço"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Verificar e adicionar campos em academias
        cursor.execute("SHOW COLUMNS FROM academias LIKE 'cep'")
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE academias 
                ADD COLUMN cep VARCHAR(10) NULL DEFAULT NULL COMMENT 'CEP no formato 00000-000' AFTER telefone,
                ADD COLUMN rua VARCHAR(255) NULL DEFAULT NULL COMMENT 'Logradouro/Rua' AFTER cep,
                ADD COLUMN numero VARCHAR(20) NULL DEFAULT NULL COMMENT 'Número do endereço' AFTER rua,
                ADD COLUMN complemento VARCHAR(100) NULL DEFAULT NULL COMMENT 'Complemento' AFTER numero,
                ADD COLUMN bairro VARCHAR(100) NULL DEFAULT NULL COMMENT 'Bairro' AFTER complemento
            """)
            print("✓ Campos de endereço adicionados na tabela academias")
        else:
            print("✓ Campos de endereço já existem na tabela academias")
        
        # Verificar e adicionar campos em associacoes
        cursor.execute("SHOW COLUMNS FROM associacoes LIKE 'cep'")
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE associacoes 
                ADD COLUMN cep VARCHAR(10) NULL DEFAULT NULL COMMENT 'CEP no formato 00000-000' AFTER telefone,
                ADD COLUMN rua VARCHAR(255) NULL DEFAULT NULL COMMENT 'Logradouro/Rua' AFTER cep,
                ADD COLUMN numero VARCHAR(20) NULL DEFAULT NULL COMMENT 'Número do endereço' AFTER rua,
                ADD COLUMN complemento VARCHAR(100) NULL DEFAULT NULL COMMENT 'Complemento' AFTER numero,
                ADD COLUMN bairro VARCHAR(100) NULL DEFAULT NULL COMMENT 'Bairro' AFTER complemento,
                ADD COLUMN cidade VARCHAR(100) NULL DEFAULT NULL COMMENT 'Cidade' AFTER bairro,
                ADD COLUMN uf VARCHAR(2) NULL DEFAULT NULL COMMENT 'Estado (UF)' AFTER cidade
            """)
            print("✓ Campos de endereço adicionados na tabela associacoes")
        else:
            print("✓ Campos de endereço já existem na tabela associacoes")
        
        conn.commit()
        
        # Verificar estrutura
        print("\nEstrutura da tabela academias:")
        print("-" * 80)
        cursor.execute("DESCRIBE academias")
        for col in cursor.fetchall():
            if col['Field'] in ['cep', 'rua', 'numero', 'complemento', 'bairro']:
                print(f"✓ {col['Field']:20} {col['Type']:20} {col['Null']:5} {col['Default']}")
        
        print("\nEstrutura da tabela associacoes:")
        print("-" * 80)
        cursor.execute("DESCRIBE associacoes")
        for col in cursor.fetchall():
            if col['Field'] in ['cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'uf']:
                print(f"✓ {col['Field']:20} {col['Type']:20} {col['Null']:5} {col['Default']}")
        
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
    print("Executando migração: add_endereco_academias_associacoes")
    print("=" * 80)
    sucesso = executar_migracao()
    print("=" * 80)
    if sucesso:
        print("Migração concluída com sucesso!")
        sys.exit(0)
    else:
        print("Migração falhou!")
        sys.exit(1)
