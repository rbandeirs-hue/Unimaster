#!/usr/bin/env python3
"""
MM-06 — Trava a duplicidade no banco e acelera os filtros por modalidade.

Passo 6 e último da estrutura. Até aqui, "não gerar a mesma cobrança duas vezes"
era promessa de código. Duas rotas gerando ao mesmo tempo, ou um clique duplo,
furavam a promessa — foi assim que nasceram as 11 duplicatas que o MM-01 teve de
cancelar. Agora o próprio banco recusa.

A chave é (contrato_id, aluno_id, competencia), e o aluno_id no meio não é
detalhe: o contrato de família cobre dois irmãos, cada um com a SUA cobrança no
mesmo mês. Sem o aluno_id na chave, o segundo irmão seria recusado e a cobrança
familiar deixaria de funcionar. (Foi o que a conferência mostrou: 6 pares
legítimos nos dois contratos de família.)

Cobrança antiga, sem contrato, não é afetada: contrato_id NULL não entra em
índice único no MySQL. O passo é inteiramente reversível — só cria índices.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_06_indices.py
  .venv/bin/python migrations/executar_mm_06_indices.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

UNICO = ("mensalidade_aluno", "unq_ma_contrato_aluno_competencia",
         "(contrato_id, aluno_id, competencia)")

# Índices de leitura: os cortes por modalidade e por competência passam a ser
# feitos em toda tela do sistema.
INDICES = [
    ("mensalidade_aluno", "idx_ma_aluno_competencia", "(aluno_id, competencia)"),
    ("contrato", "idx_contrato_academia_status", "(id_academia, status)"),
    ("contrato_item", "idx_ci_contrato_aluno", "(contrato_id, aluno_id)"),
    ("matricula_modalidade", "idx_matmod_aluno_status", "(aluno_id, status)"),
    ("matricula_modalidade", "idx_matmod_mod_status", "(modalidade_id, status)"),
]

SQL_CONFLITOS = """
SELECT contrato_id, aluno_id, competencia, COUNT(*) n
FROM mensalidade_aluno
WHERE contrato_id IS NOT NULL AND competencia IS NOT NULL
GROUP BY 1,2,3 HAVING COUNT(*) > 1
"""


def _tem_indice(cur, tabela, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
             AND INDEX_NAME = %s""", (tabela, nome))
    return cur.fetchone() is not None


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(SQL_CONFLITOS)
        conflitos = cur.fetchall() or []
        if conflitos:
            print(f"Índice único NÃO criado: {len(conflitos)} combinação(ões) "
                  "já repetidas. Resolva antes (MM-01 cancela duplicatas):")
            for c in conflitos[:15]:
                print(f"    contrato={c['contrato_id']} aluno={c['aluno_id']} "
                      f"competência={c['competencia']} → {c['n']} cobranças")
            sys.exit(1)

        tabela, nome, colunas = UNICO
        if _tem_indice(cur, tabela, nome):
            print(f"• Índice único {nome} já existia.")
        else:
            cur.execute(f"ALTER TABLE {tabela} ADD UNIQUE KEY {nome} {colunas}")
            conn.commit()
            print(f"✓ Índice único {nome} criado.")

        for tabela, nome, colunas in INDICES:
            if _tem_indice(cur, tabela, nome):
                print(f"• Índice {nome} já existia.")
                continue
            cur.execute(f"ALTER TABLE {tabela} ADD KEY {nome} {colunas}")
            conn.commit()
            print(f"✓ Índice {nome} criado.")

        print("\nMigração concluída. Estrutura da multimodalidade completa.")
    except Exception as e:
        conn.rollback()
        print("Erro na migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for tabela, nome, _ in [UNICO] + INDICES:
            if _tem_indice(cur, tabela, nome):
                cur.execute(f"ALTER TABLE {tabela} DROP INDEX {nome}")
                conn.commit()
                print(f"✓ Índice {nome} removido.")
        print("\nReversão concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro na reversão:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    else:
        executar_migracao()
