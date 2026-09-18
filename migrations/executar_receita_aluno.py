#!/usr/bin/env python3
"""
Vínculo da receita com o aluno (`receitas.id_aluno`).

A matrícula paga vira uma receita ("Matrícula - <nome>", observação
"Pré-cadastro #N") e o pré-cadastro é apagado quando o aluno é aprovado — daí
em diante nada ligava aquele pagamento ao aluno. A ficha financeira dele achava
a matrícula pelo NOME, e dois homônimos na mesma academia veriam a matrícula um
do outro.

A tabela já tem `id_mensalidade_aluno` e `id_cobranca_avulsa`; `id_aluno` segue
a mesma ideia e serve para qualquer receita ligada a uma pessoa, não só
matrícula.

O backfill preenche as matrículas antigas SÓ quando o nome bate com exatamente
um aluno ativo da academia — homônimo fica em branco de propósito, porque
adivinhar aqui é o erro que a coluna veio evitar.

Idempotente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_receita_aluno.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLUNA = "ALTER TABLE receitas ADD COLUMN id_aluno INT NULL"
INDICE = "ALTER TABLE receitas ADD INDEX ix_receitas_aluno (id_aluno)"


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM receitas LIKE 'id_aluno'")
        if cur.fetchone():
            print("• Coluna receitas.id_aluno já existia.")
        else:
            cur.execute(COLUNA)
            conn.commit()
            print("✓ Coluna receitas.id_aluno criada.")

        cur.execute("SHOW INDEX FROM receitas WHERE Key_name = 'ix_receitas_aluno'")
        if cur.fetchone():
            print("• Índice ix_receitas_aluno já existia.")
        else:
            cur.execute(INDICE)
            conn.commit()
            print("✓ Índice ix_receitas_aluno criado.")

        # Backfill das matrículas: nome exato, um único aluno na academia.
        d = conn.cursor(dictionary=True)
        d.execute(
            """SELECT id, id_academia, descricao FROM receitas
               WHERE categoria = 'Matrículas' AND id_aluno IS NULL
                 AND descricao LIKE 'Matrícula - %'"""
        )
        pendentes = d.fetchall()
        ligadas = ambiguas = sem_aluno = 0
        for r in pendentes:
            nome = (r["descricao"] or "")[len("Matrícula - "):].strip()
            if not nome:
                sem_aluno += 1
                continue
            d.execute(
                "SELECT id FROM alunos WHERE id_academia = %s AND nome = %s",
                (r["id_academia"], nome),
            )
            achados = d.fetchall()
            if len(achados) == 1:
                cur.execute("UPDATE receitas SET id_aluno = %s WHERE id = %s",
                            (achados[0]["id"], r["id"]))
                ligadas += 1
            elif len(achados) > 1:
                ambiguas += 1
            else:
                sem_aluno += 1
        conn.commit()
        d.close()
        print(f"✓ Backfill: {ligadas} receita(s) de matrícula ligada(s) ao aluno; "
              f"{ambiguas} com nome repetido e {sem_aluno} sem aluno correspondente "
              f"ficaram sem vínculo (de {len(pendentes)}).")

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
