#!/usr/bin/env python3
"""
Mudança de vencimento do aluno: dia fixo em `alunos` e proporcional em
`mensalidade_aluno`.

DDL: embutida aqui (o .gitignore ignora *.sql, então o runner não depende do
arquivo estar presente). Cópia legível em migrations/add_aluno_dia_vencimento.sql.
Idempotente: colunas já existentes são puladas.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_add_aluno_dia_vencimento.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

DDL = [
    # O dia de vencimento era inferido de DAY(data_vencimento) da última cobrança
    # não cancelada, então não havia como mudar o vencimento de quem estava com
    # tudo pago (só existiam cobranças pagas, e cobrança paga é histórico). Com a
    # coluna, o dia vira dado do aluno e a geração mensal o respeita.
    """ALTER TABLE alunos
         ADD COLUMN dia_vencimento TINYINT UNSIGNED NULL DEFAULT NULL
         COMMENT 'Dia fixo de vencimento das mensalidades (1-31). NULL = herda da última cobrança'""",
    # Proporcional em coluna própria (e não somado em valor_original) para ser
    # rastreável na tela e substituível: mudar o vencimento de novo troca o
    # ajuste em vez de acumular em cima do anterior.
    """ALTER TABLE mensalidade_aluno
         ADD COLUMN ajuste_proporcional DECIMAL(10,2) NOT NULL DEFAULT 0.00
         COMMENT 'Dias extras cobrados por adiamento do vencimento (soma no valor)'""",
    """ALTER TABLE mensalidade_aluno
         ADD COLUMN ajuste_proporcional_dias SMALLINT NOT NULL DEFAULT 0
         COMMENT 'Quantidade de dias que geraram o ajuste_proporcional'""",
]

COLUNAS = [
    ("alunos", "dia_vencimento"),
    ("mensalidade_aluno", "ajuste_proporcional"),
    ("mensalidade_aluno", "ajuste_proporcional_dias"),
]


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("❌ Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        for comando in DDL:
            try:
                cur.execute(comando)
                conn.commit()
                print(f"✓ {' '.join(comando.split())[:80]}")
            except Exception as err:
                if "duplicate column" in str(err).lower():
                    print(f"ℹ Já existe, pulando: {' '.join(comando.split())[:80]}")
                    conn.rollback()
                else:
                    raise

        cur2 = conn.cursor(dictionary=True)
        faltando = []
        for tabela, coluna in COLUNAS:
            cur2.execute(f"DESCRIBE {tabela}")
            if not any(c["Field"] == coluna for c in cur2.fetchall()):
                faltando.append(f"{tabela}.{coluna}")
        cur2.close()
        if faltando:
            print("⚠ Colunas não encontradas após a migração:", ", ".join(faltando))
            sys.exit(1)
        print("✅ Migração concluída.")
    except Exception as e:
        conn.rollback()
        print("❌ Erro ao executar a migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    executar_migracao()
