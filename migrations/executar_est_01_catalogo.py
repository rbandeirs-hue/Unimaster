#!/usr/bin/env python3
"""
EST-01 — Catálogo do estoque: categorias, produtos, variações e tabelas de preço.

Modelagem, e o porquê de cada escolha
-------------------------------------
`id_academia` e `id_associacao`, os dois anuláveis, seguem exatamente o que
`receitas` já faz no sistema: o registro pertence a uma academia OU a uma
associação. Isso é o que permite a associação manter o próprio estoque e
revender para as academias sem uma segunda modelagem paralela.

Todo produto tem ao menos UMA variação, criada automaticamente com o nome
"Único". Sem isso haveria dois caminhos de código para a mesma coisa — produto
com variação e produto sem — e é desse tipo de bifurcação que nasceram os bugs
de cobrança deste projeto. Com a variação sempre presente, `estoque_saldo` e
`estoque_movimento` têm chave estrangeira de verdade, sem um id mágico 0.

Tabelas de preço (decisão do dono do sistema): o preço não fica no produto.
Cada academia/associação tem quantas tabelas quiser — "Aluno", "Professor",
"Público" — e o preço de cada item vive em `estoque_preco`. Acrescentar uma
quarta tabela amanhã é cadastro, não alteração de schema.

Colação `utf8mb4_uca1400_ai_ci` é obrigatória: é a de `alunos`, `academias`,
`modalidade` e `graduacao`, com quem estas tabelas fazem JOIN. Misturar com
`general_ci` produz "Illegal mix of collations" — já aconteceu aqui.

Aditiva e reversível: cria tabelas novas e não toca em nenhuma existente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_est_01_catalogo.py            # simulação
  .venv/bin/python migrations/executar_est_01_catalogo.py --aplicar
  .venv/bin/python migrations/executar_est_01_catalogo.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLACAO = "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci"

TABELAS = [
    ("estoque_categoria", f"""
        CREATE TABLE estoque_categoria (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) DEFAULT NULL,
            id_associacao INT(11) DEFAULT NULL,
            nome VARCHAR(80) NOT NULL,
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY unq_cat_academia (id_academia, nome),
            UNIQUE KEY unq_cat_associacao (id_associacao, nome),
            CONSTRAINT fk_estcat_academia FOREIGN KEY (id_academia)
                REFERENCES academias (id) ON DELETE CASCADE,
            CONSTRAINT fk_estcat_associacao FOREIGN KEY (id_associacao)
                REFERENCES associacoes (id) ON DELETE CASCADE
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Categorias de produto; pertence a uma academia OU associação'
    """),

    ("estoque_produto", f"""
        CREATE TABLE estoque_produto (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) DEFAULT NULL,
            id_associacao INT(11) DEFAULT NULL,
            categoria_id INT(11) DEFAULT NULL,
            nome VARCHAR(140) NOT NULL,
            sku VARCHAR(40) DEFAULT NULL COMMENT 'Código interno, opcional',
            descricao TEXT DEFAULT NULL,
            unidade VARCHAR(12) NOT NULL DEFAULT 'un',
            custo DECIMAL(10,2) NOT NULL DEFAULT 0.00
                COMMENT 'Custo de aquisição padrão; a entrada pode informar outro',
            estoque_min INT(11) NOT NULL DEFAULT 0,
            estoque_max INT(11) DEFAULT NULL,
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_prod_academia (id_academia, ativo),
            KEY idx_prod_associacao (id_associacao, ativo),
            KEY idx_prod_categoria (categoria_id),
            UNIQUE KEY unq_prod_sku_academia (id_academia, sku),
            CONSTRAINT fk_estprod_academia FOREIGN KEY (id_academia)
                REFERENCES academias (id) ON DELETE CASCADE,
            CONSTRAINT fk_estprod_associacao FOREIGN KEY (id_associacao)
                REFERENCES associacoes (id) ON DELETE CASCADE,
            CONSTRAINT fk_estprod_categoria FOREIGN KEY (categoria_id)
                REFERENCES estoque_categoria (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Produtos do estoque. O preço não fica aqui: ver estoque_preco'
    """),

    ("estoque_variacao", f"""
        CREATE TABLE estoque_variacao (
            id INT(11) NOT NULL AUTO_INCREMENT,
            produto_id INT(11) NOT NULL,
            nome VARCHAR(80) NOT NULL COMMENT '"Único" quando o produto não varia',
            sku VARCHAR(40) DEFAULT NULL,
            modalidade_id INT(11) DEFAULT NULL COMMENT 'Faixa é por modalidade',
            graduacao_id INT(11) DEFAULT NULL COMMENT 'Aponta a faixa/grau do catálogo',
            tamanho VARCHAR(20) DEFAULT NULL,
            cor VARCHAR(30) DEFAULT NULL,
            custo DECIMAL(10,2) DEFAULT NULL COMMENT 'Sobrepõe o custo do produto',
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_var_produto (produto_id, ativo),
            KEY idx_var_graduacao (graduacao_id),
            CONSTRAINT fk_estvar_produto FOREIGN KEY (produto_id)
                REFERENCES estoque_produto (id) ON DELETE CASCADE,
            CONSTRAINT fk_estvar_modalidade FOREIGN KEY (modalidade_id)
                REFERENCES modalidade (id) ON DELETE SET NULL,
            CONSTRAINT fk_estvar_graduacao FOREIGN KEY (graduacao_id)
                REFERENCES graduacao (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Sempre ao menos uma por produto; saldo e movimento apontam para cá'
    """),

    ("estoque_tabela_preco", f"""
        CREATE TABLE estoque_tabela_preco (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) DEFAULT NULL,
            id_associacao INT(11) DEFAULT NULL,
            nome VARCHAR(60) NOT NULL COMMENT 'Aluno, Professor, Público…',
            perfil VARCHAR(40) DEFAULT NULL
                COMMENT 'Chave do role sugerido (aluno, professor); livre para novos',
            padrao TINYINT(1) NOT NULL DEFAULT 0
                COMMENT 'A tabela oferecida quando nada mais se aplica',
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY unq_tab_academia (id_academia, nome),
            UNIQUE KEY unq_tab_associacao (id_associacao, nome),
            CONSTRAINT fk_esttab_academia FOREIGN KEY (id_academia)
                REFERENCES academias (id) ON DELETE CASCADE,
            CONSTRAINT fk_esttab_associacao FOREIGN KEY (id_associacao)
                REFERENCES associacoes (id) ON DELETE CASCADE
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Quantas tabelas de preço a academia quiser; acrescentar é cadastro'
    """),

    ("estoque_preco", f"""
        CREATE TABLE estoque_preco (
            tabela_id INT(11) NOT NULL,
            variacao_id INT(11) NOT NULL,
            preco DECIMAL(10,2) NOT NULL,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (tabela_id, variacao_id),
            KEY idx_preco_variacao (variacao_id),
            CONSTRAINT fk_estpreco_tabela FOREIGN KEY (tabela_id)
                REFERENCES estoque_tabela_preco (id) ON DELETE CASCADE,
            CONSTRAINT fk_estpreco_variacao FOREIGN KEY (variacao_id)
                REFERENCES estoque_variacao (id) ON DELETE CASCADE
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Preço por variação em cada tabela; ausente = não vendido naquela'
    """),
]

ORDEM_REVERSA = ["estoque_preco", "estoque_tabela_preco", "estoque_variacao",
                 "estoque_produto", "estoque_categoria"]


def _existe(cur, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (nome,))
    return cur.fetchone() is not None


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("EST-01 — simulação (nada foi gravado)\n")
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
        for nome in ORDEM_REVERSA:   # ordem inversa: as FKs dependem disso
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
