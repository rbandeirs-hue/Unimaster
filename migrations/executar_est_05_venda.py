#!/usr/bin/env python3
"""
EST-05 — Pedidos de venda, consignação e o débito da academia com a associação.

O negócio que isto modela
-------------------------
A associação tem o estoque. A academia ENXERGA esse estoque e vende dele, sem
transferência: a baixa acontece no local da associação, com a academia gravada
como vendedora. O aluno paga o preço de aluno; a academia deve à associação o
preço de professor; a diferença é a margem da academia.

    Kimono A2   tabela Professor R$ 160   tabela Aluno R$ 220
    O aluno paga 220 à academia · a associação recebe 9 em vez de 10 no estoque
    A academia fica devendo 160 · margem da academia: 60

A margem nunca é digitada: é `preco_unitario - repasse_unitario`, calculada e
CONGELADA no item. Reajuste de tabela amanhã não muda o pedido de ontem — é a
mesma regra que o sistema já usa em contratos, e pela mesma razão: histórico
financeiro não se reescreve.

Dois modos de acerto, escolhidos pela associação
------------------------------------------------
  extrato — os débitos se acumulam; a associação fecha a fatura do mês e a
            academia paga uma vez só;
  venda   — cada venda já nasce como um débito seu, a acertar por venda.

O modo fica em `associacoes.estoque_repasse_modo`. Nos dois casos o débito é a
mesma linha em `estoque_repasse`; o que muda é se ele entra numa fatura.

Cliente externo
---------------
`estoque_pedido` aceita aluno, visitante (que já tem login no sistema), usuário
logado ou venda avulsa de balcão. A prazo continua sendo só para aluno: a
tabela `cobranca_avulsa` exige `aluno_id NOT NULL` e é usada pelos gateways —
mexer nela é outra análise de impacto, fora desta migração.

Aditiva e reversível. Só uma coluna nova em tabela existente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_est_05_venda.py            # simulação
  .venv/bin/python migrations/executar_est_05_venda.py --aplicar
  .venv/bin/python migrations/executar_est_05_venda.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLACAO = "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci"

TABELAS = [
    ("estoque_pedido", f"""
        CREATE TABLE estoque_pedido (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) NOT NULL COMMENT 'Quem vende e fica com a margem',
            id_associacao INT(11) DEFAULT NULL
                COMMENT 'Dona do estoque na consignação; NULL = estoque da própria academia',
            local_id INT(11) NOT NULL COMMENT 'De onde sai a mercadoria',
            tabela_preco_id INT(11) DEFAULT NULL COMMENT 'Tabela usada com o comprador',
            comprador_tipo VARCHAR(12) NOT NULL DEFAULT 'avulso'
                COMMENT 'aluno, visitante, usuario, avulso',
            aluno_id INT(11) DEFAULT NULL,
            visitante_id INT(11) DEFAULT NULL,
            usuario_id INT(11) DEFAULT NULL COMMENT 'Quem comprou logado, no autoatendimento',
            comprador_nome VARCHAR(140) DEFAULT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'aberto'
                COMMENT 'aberto, aguardando_pagamento, confirmado, cancelado',
            valor_total DECIMAL(10,2) NOT NULL DEFAULT 0.00,
            valor_repasse DECIMAL(10,2) NOT NULL DEFAULT 0.00,
            valor_margem DECIMAL(10,2) NOT NULL DEFAULT 0.00,
            origem VARCHAR(20) NOT NULL DEFAULT 'balcao'
                COMMENT 'balcao, autoatendimento',
            id_receita INT(11) DEFAULT NULL,
            id_cobranca_avulsa INT(11) DEFAULT NULL,
            observacao VARCHAR(255) DEFAULT NULL,
            criado_por INT(11) DEFAULT NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            confirmado_em DATETIME DEFAULT NULL,
            cancelado_em DATETIME DEFAULT NULL,
            PRIMARY KEY (id),
            KEY idx_ped_academia (id_academia, status, criado_em),
            KEY idx_ped_associacao (id_associacao, status),
            KEY idx_ped_aluno (aluno_id),
            KEY idx_ped_usuario (usuario_id),
            CONSTRAINT fk_estped_academia FOREIGN KEY (id_academia)
                REFERENCES academias (id) ON DELETE CASCADE,
            CONSTRAINT fk_estped_associacao FOREIGN KEY (id_associacao)
                REFERENCES associacoes (id) ON DELETE SET NULL,
            CONSTRAINT fk_estped_local FOREIGN KEY (local_id)
                REFERENCES estoque_local (id) ON DELETE RESTRICT,
            CONSTRAINT fk_estped_aluno FOREIGN KEY (aluno_id)
                REFERENCES alunos (id) ON DELETE SET NULL,
            CONSTRAINT fk_estped_usuario FOREIGN KEY (usuario_id)
                REFERENCES usuarios (id) ON DELETE SET NULL,
            CONSTRAINT fk_estped_tabela FOREIGN KEY (tabela_preco_id)
                REFERENCES estoque_tabela_preco (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Pedido de venda. O estoque só baixa na confirmação'
    """),

    ("estoque_pedido_item", f"""
        CREATE TABLE estoque_pedido_item (
            id INT(11) NOT NULL AUTO_INCREMENT,
            pedido_id INT(11) NOT NULL,
            variacao_id INT(11) NOT NULL,
            quantidade INT(11) NOT NULL,
            preco_unitario DECIMAL(10,2) NOT NULL
                COMMENT 'O que o comprador paga',
            repasse_unitario DECIMAL(10,2) NOT NULL DEFAULT 0.00
                COMMENT 'O que a academia deve à associação; 0 em estoque próprio',
            movimento_id INT(11) DEFAULT NULL
                COMMENT 'A baixa de estoque, gravada na confirmação',
            PRIMARY KEY (id),
            KEY idx_pedit_pedido (pedido_id),
            KEY idx_pedit_variacao (variacao_id),
            CONSTRAINT fk_estpedit_pedido FOREIGN KEY (pedido_id)
                REFERENCES estoque_pedido (id) ON DELETE CASCADE,
            CONSTRAINT fk_estpedit_variacao FOREIGN KEY (variacao_id)
                REFERENCES estoque_variacao (id) ON DELETE RESTRICT,
            CONSTRAINT fk_estpedit_movimento FOREIGN KEY (movimento_id)
                REFERENCES estoque_movimento (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Preço e repasse congelados no momento da venda'
    """),

    ("estoque_repasse_fatura", f"""
        CREATE TABLE estoque_repasse_fatura (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) NOT NULL,
            id_associacao INT(11) NOT NULL,
            competencia VARCHAR(7) NOT NULL COMMENT 'AAAA-MM',
            valor DECIMAL(10,2) NOT NULL DEFAULT 0.00,
            status VARCHAR(10) NOT NULL DEFAULT 'aberta'
                COMMENT 'aberta, fechada, paga',
            fechada_em DATETIME DEFAULT NULL,
            paga_em DATETIME DEFAULT NULL,
            id_receita INT(11) DEFAULT NULL COMMENT 'Receita da associação, na quitação',
            id_despesa INT(11) DEFAULT NULL COMMENT 'Despesa da academia, na quitação',
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY unq_fatura (id_academia, id_associacao, competencia),
            CONSTRAINT fk_estfat_academia FOREIGN KEY (id_academia)
                REFERENCES academias (id) ON DELETE CASCADE,
            CONSTRAINT fk_estfat_associacao FOREIGN KEY (id_associacao)
                REFERENCES associacoes (id) ON DELETE CASCADE
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Fatura mensal do que a academia deve à associação'
    """),

    ("estoque_repasse", f"""
        CREATE TABLE estoque_repasse (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) NOT NULL,
            id_associacao INT(11) NOT NULL,
            pedido_id INT(11) DEFAULT NULL,
            valor DECIMAL(10,2) NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'aberto'
                COMMENT 'aberto, faturado, pago',
            fatura_id INT(11) DEFAULT NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            quitado_em DATETIME DEFAULT NULL,
            PRIMARY KEY (id),
            KEY idx_rep_conta (id_academia, id_associacao, status),
            KEY idx_rep_pedido (pedido_id),
            KEY idx_rep_fatura (fatura_id),
            CONSTRAINT fk_estrep_academia FOREIGN KEY (id_academia)
                REFERENCES academias (id) ON DELETE CASCADE,
            CONSTRAINT fk_estrep_associacao FOREIGN KEY (id_associacao)
                REFERENCES associacoes (id) ON DELETE CASCADE,
            CONSTRAINT fk_estrep_pedido FOREIGN KEY (pedido_id)
                REFERENCES estoque_pedido (id) ON DELETE SET NULL,
            CONSTRAINT fk_estrep_fatura FOREIGN KEY (fatura_id)
                REFERENCES estoque_repasse_fatura (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Uma linha de débito por venda consignada'
    """),
]

ORDEM_REVERSA = ["estoque_repasse", "estoque_repasse_fatura",
                 "estoque_pedido_item", "estoque_pedido"]

COLUNAS = [
    ("associacoes", "estoque_repasse_modo",
     "VARCHAR(10) NOT NULL DEFAULT 'extrato' "
     "COMMENT 'extrato = fatura mensal; venda = acerto a cada venda'"),
]


def _existe(cur, nome):
    cur.execute("""SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (nome,))
    return cur.fetchone() is not None


def _tem_coluna(cur, tabela, coluna):
    cur.execute("""SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND COLUMN_NAME = %s""", (tabela, coluna))
    return cur.fetchone() is not None


def _pre(cur):
    return [t for t in ("estoque_local", "estoque_variacao", "estoque_movimento",
                        "estoque_tabela_preco") if not _existe(cur, t)]


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("EST-05 — simulação (nada foi gravado)\n")
        faltando = _pre(cur)
        if faltando:
            print("  ! EST-01/02 antes. Falta:", ", ".join(faltando), "\n")
        for nome, _ddl in TABELAS:
            print(f"  {'já existe' if _existe(cur, nome) else 'criar   '}  {nome}")
        for tab, col, _t in COLUNAS:
            print(f"  {'já existe' if _tem_coluna(cur, tab, col) else 'criar   '}  {tab}.{col}")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close(); conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        faltando = _pre(cur)
        if faltando:
            print("Erro: EST-01/02 precisam vir antes. Falta:", ", ".join(faltando))
            sys.exit(1)
        for nome, ddl in TABELAS:
            if _existe(cur, nome):
                print(f"• {nome} já existia.")
                continue
            cur.execute(ddl); conn.commit()
            print(f"✓ {nome} criada.")
        for tab, col, tipo in COLUNAS:
            if _tem_coluna(cur, tab, col):
                print(f"• {tab}.{col} já existia.")
                continue
            cur.execute(f"ALTER TABLE {tab} ADD COLUMN {col} {tipo}"); conn.commit()
            print(f"✓ {tab}.{col} criada.")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback(); print("Erro na migração:", e); sys.exit(1)
    finally:
        cur.close(); conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for nome in ORDEM_REVERSA:
            if _existe(cur, nome):
                cur.execute(f"DROP TABLE {nome}"); conn.commit()
                print(f"✓ {nome} removida.")
            else:
                print(f"• {nome} já não existia.")
        for tab, col, _t in COLUNAS:
            if _tem_coluna(cur, tab, col):
                cur.execute(f"ALTER TABLE {tab} DROP COLUMN {col}"); conn.commit()
                print(f"✓ {tab}.{col} removida.")
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
