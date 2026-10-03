#!/usr/bin/env python3
"""
EST-03 — Inventário físico.

Por que o inventário não escreve no saldo
-----------------------------------------
Seria mais curto gravar a quantidade contada direto em `estoque_saldo`. Não
faço isso: a diferença entre o que o sistema achava e o que existe na
prateleira é justamente a informação que interessa, e sobrescrever o saldo a
apaga. Cada item contado com diferença gera um movimento de ajuste, e a coluna
`movimento_id` guarda qual foi — dá para responder "por que o saldo mudou" um
ano depois.

O inventário tem estado: `aberto` enquanto se conta, `fechado` quando os
ajustes foram gerados, `cancelado` quando se desiste. Fechar é irreversível
por design; o caminho de volta é estornar os ajustes, que são movimentos
comuns.

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_est_03_inventario.py            # simulação
  .venv/bin/python migrations/executar_est_03_inventario.py --aplicar
  .venv/bin/python migrations/executar_est_03_inventario.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLACAO = "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci"

TABELAS = [
    ("estoque_inventario", f"""
        CREATE TABLE estoque_inventario (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) DEFAULT NULL,
            id_associacao INT(11) DEFAULT NULL,
            local_id INT(11) NOT NULL,
            status VARCHAR(12) NOT NULL DEFAULT 'aberto'
                COMMENT 'aberto, fechado, cancelado',
            observacao VARCHAR(255) DEFAULT NULL,
            iniciado_por INT(11) DEFAULT NULL,
            iniciado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fechado_por INT(11) DEFAULT NULL,
            fechado_em DATETIME DEFAULT NULL,
            PRIMARY KEY (id),
            KEY idx_inv_academia (id_academia, status),
            KEY idx_inv_local (local_id, status),
            CONSTRAINT fk_estinv_local FOREIGN KEY (local_id)
                REFERENCES estoque_local (id) ON DELETE RESTRICT,
            CONSTRAINT fk_estinv_iniciou FOREIGN KEY (iniciado_por)
                REFERENCES usuarios (id) ON DELETE SET NULL,
            CONSTRAINT fk_estinv_fechou FOREIGN KEY (fechado_por)
                REFERENCES usuarios (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Contagem física de um local'
    """),

    ("estoque_inventario_item", f"""
        CREATE TABLE estoque_inventario_item (
            id INT(11) NOT NULL AUTO_INCREMENT,
            inventario_id INT(11) NOT NULL,
            variacao_id INT(11) NOT NULL,
            qtd_sistema INT(11) NOT NULL COMMENT 'Saldo no momento da abertura',
            qtd_contada INT(11) DEFAULT NULL COMMENT 'NULL = ainda não contado',
            movimento_id INT(11) DEFAULT NULL COMMENT 'Ajuste gerado ao fechar',
            PRIMARY KEY (id),
            UNIQUE KEY unq_inv_item (inventario_id, variacao_id),
            KEY idx_invitem_variacao (variacao_id),
            CONSTRAINT fk_estinvitem_inv FOREIGN KEY (inventario_id)
                REFERENCES estoque_inventario (id) ON DELETE CASCADE,
            CONSTRAINT fk_estinvitem_var FOREIGN KEY (variacao_id)
                REFERENCES estoque_variacao (id) ON DELETE RESTRICT,
            CONSTRAINT fk_estinvitem_mov FOREIGN KEY (movimento_id)
                REFERENCES estoque_movimento (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Uma linha por variação contada; a diferença vira movimento de ajuste'
    """),
]

ORDEM_REVERSA = ["estoque_inventario_item", "estoque_inventario"]


def _existe(cur, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (nome,))
    return cur.fetchone() is not None


def _pre_requisitos(cur):
    return [t for t in ("estoque_local", "estoque_movimento", "estoque_variacao")
            if not _existe(cur, t)]


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("EST-03 — simulação (nada foi gravado)\n")
        faltando = _pre_requisitos(cur)
        if faltando:
            print("  ! EST-01/EST-02 antes. Falta:", ", ".join(faltando), "\n")
        for nome, _ddl in TABELAS:
            print(f"  {'já existe' if _existe(cur, nome) else 'criar   '}  {nome}")
        print("\n  Nenhuma tabela existente é alterada.")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close()
        conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        faltando = _pre_requisitos(cur)
        if faltando:
            print("Erro: EST-01/EST-02 precisam vir antes. Falta:", ", ".join(faltando))
            sys.exit(1)
        for nome, ddl in TABELAS:
            if _existe(cur, nome):
                print(f"• {nome} já existia.")
                continue
            cur.execute(ddl)
            conn.commit()
            print(f"✓ {nome} criada.")
        print("\nMigração concluída.")
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
        for nome in ORDEM_REVERSA:
            if _existe(cur, nome):
                cur.execute(f"DROP TABLE {nome}")
                conn.commit()
                print(f"✓ {nome} removida.")
            else:
                print(f"• {nome} já não existia.")
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
    elif "--aplicar" in sys.argv:
        executar_migracao()
    else:
        simular()
