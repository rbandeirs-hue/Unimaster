#!/usr/bin/env python3
"""
Script para executar a migração: Adicionar coluna PREVISAO na tabela faixas_judo
"""
import os
import sys
import mysql.connector

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_db_connection

def execute_sql_file(filepath, connection):
    """Executa um arquivo SQL linha por linha."""
    with open(filepath, 'r', encoding='utf-8') as f:
        sql_script = f.read()
    
    # Remove comentários e divide em comandos
    commands = []
    current_command = []
    
    for line in sql_script.split('\n'):
        line = line.strip()
        # Ignora linhas vazias e comentários que começam com --
        if not line or line.startswith('--'):
            continue
        
        current_command.append(line)
        
        # Se a linha termina com ;, finaliza o comando
        if line.endswith(';'):
            command = ' '.join(current_command)
            if command.strip():
                commands.append(command)
            current_command = []
    
    cursor = connection.cursor()
    for command in commands:
        try:
            cursor.execute(command)
            connection.commit()
        except mysql.connector.Error as err:
            # Ignora erros de "coluna já existe"
            if 'Duplicate column name' in str(err) or 'already exists' in str(err).lower():
                print(f"  ℹ Coluna 'previsao' já existe, pulando criação")
            else:
                print(f"  ⚠ Aviso ao executar comando: {command[:50]}...")
                print(f"     {err}")
        except Exception as e:
            print(f"  ⚠ Erro inesperado: {e}")
    
    cursor.close()

if __name__ == "__main__":
    migration_file = "add_previsao_faixas_judo.sql"
    migration_path = os.path.join(os.path.dirname(__file__), migration_file)
    
    print(f"Executando migração: {migration_file}")
    print("=" * 80)
    
    conn = None
    try:
        conn = get_db_connection()
        execute_sql_file(migration_path, conn)
        
        # Verificar se a coluna foi adicionada
        cursor = conn.cursor(dictionary=True)
        cursor.execute("DESCRIBE faixas_judo")
        columns = cursor.fetchall()
        
        previsao_exists = any(col['Field'] == 'previsao' for col in columns)
        
        if previsao_exists:
            # Verificar valores
            cursor.execute("SELECT COUNT(*) as total, SUM(previsao) as com_previsao FROM faixas_judo")
            stats = cursor.fetchone()
            
            print("\n✓ Coluna 'previsao' adicionada com sucesso na tabela faixas_judo")
            print(f"\n  Total de registros: {stats['total']}")
            print(f"  Registros com previsão = 1 (true): {stats['com_previsao']}")
            print(f"  Registros com previsão = 0 (false): {stats['total'] - stats['com_previsao']}")
        else:
            print("\n⚠ Coluna 'previsao' não foi encontrada após a migração")
        
        cursor.close()
        print("=" * 80)
        print("Migração concluída!")
        
    except mysql.connector.Error as err:
        print(f"❌ Erro na migração: {err}")
    except Exception as e:
        print(f"❌ Ocorreu um erro inesperado: {e}")
    finally:
        if conn:
            conn.close()
