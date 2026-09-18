#!/usr/bin/env python3
"""
Links de gateway em TEXT: VARCHAR(500) não cabe o checkout da InfinitePay.

A InfinitePay devolve um link cujo parâmetro `lenc` carrega os dados do pagador
(nome, e-mail, telefone e endereço) codificados. Quanto mais completo o cadastro
do aluno, maior o link — e passando de 500 caracteres o MySQL derrubava a
gravação inteira com:

    1406 (22001): Data too long for column 'asaas_boleto_url' at row 1

O resultado é que a cobrança era criada na InfinitePay mas o link se perdia, e a
tela mostrava erro. As colunas de URL e de PIX copia-e-cola viram TEXT (nenhuma
delas é indexada, então não há custo de índice).

Idempotente: colunas já convertidas são ignoradas.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_link_gateway_text.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

ALVOS = [
    ("mensalidade_aluno", "asaas_boleto_url"),
    ("mensalidade_aluno", "asaas_pix_copia_cola"),
    ("mensalidade_aluno", "cora_boleto_url"),
    ("mensalidade_aluno", "cora_pix_copia_cola"),
    ("mensalidade_aluno", "inter_boleto_url"),
    ("mensalidade_aluno", "inter_pix_copia_cola"),
    ("cobranca_avulsa", "asaas_boleto_url"),
    ("cobranca_avulsa", "asaas_pix_copia_cola"),
]


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        for tabela, coluna in ALVOS:
            cur.execute(
                """SELECT DATA_TYPE FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
                (tabela, coluna),
            )
            row = cur.fetchone()
            if not row:
                print(f"• {tabela}.{coluna} não existe — pulando.")
                continue
            if str(row[0]).lower() == "text":
                print(f"• {tabela}.{coluna} já era TEXT.")
                continue
            cur.execute(f"ALTER TABLE {tabela} MODIFY {coluna} TEXT NULL")
            conn.commit()
            print(f"✓ {tabela}.{coluna} convertida para TEXT.")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro na migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar_migracao()
