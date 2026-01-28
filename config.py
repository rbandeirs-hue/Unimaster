import mysql.connector

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="D@s@9!T2",
        database="unimaster"
    )
