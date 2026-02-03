#!/usr/bin/env python3
"""
Script para adicionar role "Visitante" se não existir.
Execute: python3 migrations/executar_add_role_visitante.py
OU execute diretamente: mysql -u user -p database < migrations/add_role_visitante.sql
"""
import os
import sys

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import get_db_connection
    
    def executar():
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        
        try:
            # Verificar se a role já existe
            cur.execute("SELECT id FROM roles WHERE chave = 'visitante' OR nome = 'Visitante'")
            existe = cur.fetchone()
            
            if not existe:
                # Inserir role Visitante
                cur.execute("INSERT INTO roles (nome, chave) VALUES ('Visitante', 'visitante')")
                conn.commit()
                print("✅ Role 'Visitante' criada com sucesso!")
            else:
                print("ℹ️  Role 'Visitante' já existe (ID: {})".format(existe.get('id')))
            
            cur.close()
            conn.close()
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            print(f"❌ Erro ao executar migração: {e}")
            sys.exit(1)
    
    if __name__ == "__main__":
        executar()
except ImportError as e:
    print("⚠️  Não foi possível importar módulos necessários.")
    print("   Execute diretamente via MySQL:")
    print("   mysql -u user -p database < migrations/add_role_visitante.sql")
    sys.exit(1)
