#!/usr/bin/env python3
"""
EST-06 — Estoque independente: organização própria, com financeiro próprio.

O que muda
----------
Até aqui todo registro do estoque pertencia a uma academia OU a uma associação.
Agora existe um terceiro dono: a ORGANIZAÇÃO — uma loja/depósito que usa o
módulo de estoque sozinho, sem academia, sem associação, sem aluno.

    id_academia     estoque da academia
    id_associacao   estoque da associação (consignação para as academias)
    id_organizacao  estoque independente, com caixa próprio   ← novo

Exatamente um dos três é preenchido em cada linha. Essa regra é validada no
serviço, não por CHECK: o MariaDB desta versão aceita CHECK mas a mensagem que
ele devolve não diz nada ao usuário, e a validação em Python explica o erro.

O financeiro separado
---------------------
A organização não usa `receitas`/`despesas`: aquelas tabelas são da hierarquia
federação → associação → academia e carregam regras que não se aplicam aqui.
O caixa da organização é `estoque_lancamento`, uma tabela só — entra dinheiro
na venda, sai na compra. Nenhuma tabela financeira existente é tocada.

Quem acessa
-----------
`estoque_organizacao_usuario` liga usuários à organização, no mesmo espírito de
`usuarios_academias`. Sem linha lá, ninguém vê o estoque dela — nem admin por
engano: o admin vê porque é admin, não porque a consulta vazou.

Aditiva e reversível: cria três tabelas e acrescenta uma coluna anulável às
sete tabelas de estoque que têm dono. Nenhuma linha existente muda de valor.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_est_06_organizacao.py            # simulação
  .venv/bin/python migrations/executar_est_06_organizacao.py --aplicar
  .venv/bin/python migrations/executar_est_06_organizacao.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLACAO = "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci"

TABELAS = [
    ("estoque_organizacao", f"""
        CREATE TABLE estoque_organizacao (
            id INT(11) NOT NULL AUTO_INCREMENT,
            nome VARCHAR(140) NOT NULL,
            documento VARCHAR(20) DEFAULT NULL COMMENT 'CNPJ ou CPF, opcional',
            email VARCHAR(140) DEFAULT NULL,
            telefone VARCHAR(30) DEFAULT NULL,
            permite_negativo TINYINT(1) NOT NULL DEFAULT 0,
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            criado_por INT(11) DEFAULT NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY unq_org_nome (nome),
            CONSTRAINT fk_estorg_usuario FOREIGN KEY (criado_por)
                REFERENCES usuarios (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Estoque independente: sem academia, sem associação, caixa próprio'
    """),

    ("estoque_organizacao_usuario", f"""
        CREATE TABLE estoque_organizacao_usuario (
            organizacao_id INT(11) NOT NULL,
            usuario_id INT(11) NOT NULL,
            papel VARCHAR(20) NOT NULL DEFAULT 'operador'
                COMMENT 'gestor = configura e vende; operador = movimenta; consulta = só lê',
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (organizacao_id, usuario_id),
            KEY idx_orgusr_usuario (usuario_id),
            CONSTRAINT fk_estorgusr_org FOREIGN KEY (organizacao_id)
                REFERENCES estoque_organizacao (id) ON DELETE CASCADE,
            CONSTRAINT fk_estorgusr_usuario FOREIGN KEY (usuario_id)
                REFERENCES usuarios (id) ON DELETE CASCADE
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Quem acessa a organização; mesmo espírito de usuarios_academias'
    """),

    ("estoque_lancamento", f"""
        CREATE TABLE estoque_lancamento (
            id INT(11) NOT NULL AUTO_INCREMENT,
            organizacao_id INT(11) NOT NULL,
            sentido CHAR(1) NOT NULL COMMENT 'R = recebeu, D = pagou',
            valor DECIMAL(10,2) NOT NULL,
            data DATE NOT NULL,
            categoria VARCHAR(60) DEFAULT NULL COMMENT 'Venda, Compra, Despesa…',
            descricao VARCHAR(255) NOT NULL,
            forma_pagamento VARCHAR(40) DEFAULT NULL,
            pedido_id INT(11) DEFAULT NULL,
            movimento_id INT(11) DEFAULT NULL,
            cancelado TINYINT(1) NOT NULL DEFAULT 0,
            criado_por INT(11) DEFAULT NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_lanc_org (organizacao_id, data, cancelado),
            KEY idx_lanc_pedido (pedido_id),
            CONSTRAINT fk_estlanc_org FOREIGN KEY (organizacao_id)
                REFERENCES estoque_organizacao (id) ON DELETE CASCADE,
            CONSTRAINT fk_estlanc_pedido FOREIGN KEY (pedido_id)
                REFERENCES estoque_pedido (id) ON DELETE SET NULL,
            CONSTRAINT fk_estlanc_movimento FOREIGN KEY (movimento_id)
                REFERENCES estoque_movimento (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Caixa da organização. Não toca receitas/despesas da hierarquia'
    """),
]

ORDEM_REVERSA = ["estoque_lancamento", "estoque_organizacao_usuario",
                 "estoque_organizacao"]

# As sete tabelas do estoque que carregam dono.
COM_DONO = ["estoque_categoria", "estoque_produto", "estoque_local",
            "estoque_tabela_preco", "estoque_movimento", "estoque_inventario",
            "estoque_pedido"]


def _existe(cur, nome):
    cur.execute("""SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (nome,))
    return cur.fetchone() is not None


def _tem_coluna(cur, tabela, coluna):
    cur.execute("""SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND COLUMN_NAME = %s""", (tabela, coluna))
    return cur.fetchone() is not None


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("EST-06 — simulação (nada foi gravado)\n")
        for nome, _d in TABELAS:
            print(f"  {'já existe' if _existe(cur, nome) else 'criar   '}  {nome}")
        print()
        for t in COM_DONO:
            marca = "já existe" if _tem_coluna(cur, t, "id_organizacao") else "criar   "
            print(f"  {marca}  {t}.id_organizacao")
        print("\n  Coluna anulável: nenhuma linha existente muda de valor.")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close(); conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # A coluna precisa existir antes de estoque_pedido ser referenciada,
        # então as tabelas novas vêm primeiro.
        for nome, ddl in TABELAS:
            if _existe(cur, nome):
                print(f"• {nome} já existia.")
                continue
            cur.execute(ddl); conn.commit()
            print(f"✓ {nome} criada.")

        for t in COM_DONO:
            if not _existe(cur, t):
                print(f"! {t} não existe — pulando (rode EST-01..05 antes).")
                continue
            if _tem_coluna(cur, t, "id_organizacao"):
                print(f"• {t}.id_organizacao já existia.")
                continue
            cur.execute(
                f"ALTER TABLE {t} ADD COLUMN id_organizacao INT(11) DEFAULT NULL "
                f"COMMENT 'Dono quando o estoque é independente'")
            cur.execute(
                f"ALTER TABLE {t} ADD CONSTRAINT fk_{t[:18]}_org "
                f"FOREIGN KEY (id_organizacao) REFERENCES estoque_organizacao (id) "
                f"ON DELETE CASCADE")
            cur.execute(f"CREATE INDEX idx_{t[:20]}_org ON {t} (id_organizacao)")
            conn.commit()
            print(f"✓ {t}.id_organizacao criada.")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback(); print("Erro na migração:", e); sys.exit(1)
    finally:
        cur.close(); conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for t in COM_DONO:
            if _existe(cur, t) and _tem_coluna(cur, t, "id_organizacao"):
                try:
                    cur.execute(f"ALTER TABLE {t} DROP FOREIGN KEY fk_{t[:18]}_org")
                except Exception:
                    pass
                cur.execute(f"ALTER TABLE {t} DROP COLUMN id_organizacao")
                conn.commit()
                print(f"✓ {t}.id_organizacao removida.")
        for nome in ORDEM_REVERSA:
            if _existe(cur, nome):
                cur.execute(f"DROP TABLE {nome}"); conn.commit()
                print(f"✓ {nome} removida.")
    except Exception as e:
        conn.rollback(); print("Erro na reversão:", e); sys.exit(1)
    finally:
        cur.close(); conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    elif "--aplicar" in sys.argv:
        executar_migracao()
    else:
        simular()
