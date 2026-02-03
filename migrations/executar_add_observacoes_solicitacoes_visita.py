#!/usr/bin/env python3
"""
Script para adicionar campos de observação separados na tabela solicitacoes_aprovacao
"""
import sys
import os

# Adicionar o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection

def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Verificar se os campos já existem
        cur.execute("""
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
              AND TABLE_NAME = 'solicitacoes_aprovacao' 
              AND COLUMN_NAME IN ('observacao_origem', 'observacao_destino')
        """)
        colunas_existentes = [row[0] for row in cur.fetchall()]
        
        if 'observacao_origem' not in colunas_existentes:
            cur.execute("""
                ALTER TABLE solicitacoes_aprovacao 
                ADD COLUMN observacao_origem TEXT NULL DEFAULT NULL 
                COMMENT 'Observação do gestor de origem para o destino' 
                AFTER observacao
            """)
            print("✓ Campo observacao_origem adicionado")
        else:
            print("⚠ Campo observacao_origem já existe")
        
        if 'observacao_destino' not in colunas_existentes:
            cur.execute("""
                ALTER TABLE solicitacoes_aprovacao 
                ADD COLUMN observacao_destino TEXT NULL DEFAULT NULL 
                COMMENT 'Observação do gestor de destino para aluno/origem' 
                AFTER observacao_origem
            """)
            print("✓ Campo observacao_destino adicionado")
        else:
            print("⚠ Campo observacao_destino já existe")
        
        conn.commit()
        print("\n✅ Migração concluída com sucesso!")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Erro ao executar migração: {e}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    executar_migracao()
