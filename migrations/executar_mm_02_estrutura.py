#!/usr/bin/env python3
"""
MM-02 — Estrutura da multimodalidade.

Passo 2 da evolução. Cria as tabelas novas e as colunas opcionais que a geração
por contrato vai precisar. Nada existente é apagado, renomeado ou alterado de
significado: toda coluna nova nasce com DEFAULT que reproduz o comportamento de
hoje, então o sistema continua funcionando igual enquanto ninguém preenche nada.

O que passa a existir:

  mensalidade_modalidade  quais modalidades um plano cobre (Judô+Jiu-Jitsu etc.)
  matricula_modalidade    matrícula do aluno EM uma modalidade, com vigência.
                          Convive com `aluno_modalidades`, que fica intacta —
                          aquela diz "faz", esta diz "faz desde quando, por qual
                          contrato e até quando".
  contrato                o acordo comercial. Quem paga pode ser o responsável,
                          e um contrato pode cobrir vários alunos (família).
  contrato_item           cada aluno/modalidade coberto pelo contrato.
  contrato_rateio         como o valor do contrato se divide entre os itens,
                          para o financeiro consolidado saber de quem é o quê.

Colunas novas:
  mensalidades       tipo, qtd_min, qtd_max, periodicidade, dia_vencimento_padrao,
                     permite_desconto, permite_alterar_valor,
                     permite_alterar_vencimento
  mensalidade_aluno  contrato_id, competencia, snapshot_pacote_nome,
                     snapshot_modalidades, snapshot_regra

Os `snapshot_*` congelam o que valia no momento da cobrança. Sem eles, mudar um
pacote amanhã reescreveria a leitura de um histórico já pago — que é exatamente
o que não pode acontecer.

Collation: as tabelas nascem em utf8mb4_uca1400_ai_ci, a mesma de `alunos`,
`mensalidades` e `modalidade`. O padrão do banco é utf8mb4_unicode_ci e
comparar coluna com coluna entre as duas estoura "Illegal mix of collations".

Idempotente: rodar de novo não repete nada.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_02_estrutura.py
  .venv/bin/python migrations/executar_mm_02_estrutura.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLLATE = "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci"

TABELAS = [
    ("mensalidade_modalidade", f"""
        CREATE TABLE mensalidade_modalidade (
          id INT(11) NOT NULL AUTO_INCREMENT,
          mensalidade_id INT(11) NOT NULL,
          modalidade_id INT(11) NOT NULL,
          principal TINYINT(1) NOT NULL DEFAULT 0
                    COMMENT '1=modalidade que dá nome ao pacote',
          criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY unq_mm_plano_modalidade (mensalidade_id, modalidade_id),
          KEY idx_mm_modalidade (modalidade_id),
          CONSTRAINT fk_mm_mensalidade FOREIGN KEY (mensalidade_id)
            REFERENCES mensalidades (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_mm_modalidade FOREIGN KEY (modalidade_id)
            REFERENCES modalidade (id) ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB {COLLATE}
        COMMENT='Modalidades cobertas por cada plano/pacote'
    """),
    ("contrato", f"""
        CREATE TABLE contrato (
          id INT(11) NOT NULL AUTO_INCREMENT,
          id_academia INT(11) NOT NULL,
          mensalidade_id INT(11) DEFAULT NULL COMMENT 'Pacote contratado',
          titular_aluno_id INT(11) DEFAULT NULL
                    COMMENT 'Aluno titular; NULL em contrato de família',
          responsavel_cpf VARCHAR(20) DEFAULT NULL COMMENT 'Somente dígitos',
          responsavel_nome VARCHAR(150) DEFAULT NULL,
          valor DECIMAL(10,2) NOT NULL DEFAULT 0.00,
          desconto DECIMAL(10,2) NOT NULL DEFAULT 0.00,
          dia_vencimento TINYINT(4) DEFAULT NULL COMMENT '1 a 31',
          periodicidade VARCHAR(20) NOT NULL DEFAULT 'mensal',
          data_inicio DATE DEFAULT NULL,
          data_fim DATE DEFAULT NULL,
          status ENUM('ativo','suspenso','encerrado','cancelado')
                 NOT NULL DEFAULT 'ativo',
          observacoes TEXT DEFAULT NULL,
          origem VARCHAR(30) NOT NULL DEFAULT 'manual'
                 COMMENT 'manual, migracao, precadastro...',
          criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          atualizado_em TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          KEY idx_contrato_academia (id_academia),
          KEY idx_contrato_titular (titular_aluno_id),
          KEY idx_contrato_status (status),
          KEY idx_contrato_cpf (responsavel_cpf),
          KEY idx_contrato_plano (mensalidade_id),
          CONSTRAINT fk_contrato_academia FOREIGN KEY (id_academia)
            REFERENCES academias (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_contrato_plano FOREIGN KEY (mensalidade_id)
            REFERENCES mensalidades (id) ON DELETE SET NULL ON UPDATE CASCADE,
          CONSTRAINT fk_contrato_titular FOREIGN KEY (titular_aluno_id)
            REFERENCES alunos (id) ON DELETE SET NULL ON UPDATE CASCADE
        ) ENGINE=InnoDB {COLLATE}
        COMMENT='Acordo comercial; pode cobrir mais de um aluno'
    """),
    ("contrato_item", f"""
        CREATE TABLE contrato_item (
          id INT(11) NOT NULL AUTO_INCREMENT,
          contrato_id INT(11) NOT NULL,
          aluno_id INT(11) NOT NULL,
          modalidade_id INT(11) DEFAULT NULL,
          mensalidade_id INT(11) DEFAULT NULL COMMENT 'Plano deste item',
          valor DECIMAL(10,2) NOT NULL DEFAULT 0.00,
          desconto DECIMAL(10,2) NOT NULL DEFAULT 0.00,
          status ENUM('ativo','encerrado','cancelado') NOT NULL DEFAULT 'ativo',
          data_inicio DATE DEFAULT NULL,
          data_fim DATE DEFAULT NULL,
          criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          atualizado_em TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY unq_ci_contrato_aluno_mod (contrato_id, aluno_id, modalidade_id),
          KEY idx_ci_aluno (aluno_id),
          KEY idx_ci_modalidade (modalidade_id),
          CONSTRAINT fk_ci_contrato FOREIGN KEY (contrato_id)
            REFERENCES contrato (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_ci_aluno FOREIGN KEY (aluno_id)
            REFERENCES alunos (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_ci_modalidade FOREIGN KEY (modalidade_id)
            REFERENCES modalidade (id) ON DELETE SET NULL ON UPDATE CASCADE,
          CONSTRAINT fk_ci_plano FOREIGN KEY (mensalidade_id)
            REFERENCES mensalidades (id) ON DELETE SET NULL ON UPDATE CASCADE
        ) ENGINE=InnoDB {COLLATE}
        COMMENT='Aluno/modalidade coberto por um contrato'
    """),
    ("contrato_rateio", f"""
        CREATE TABLE contrato_rateio (
          id INT(11) NOT NULL AUTO_INCREMENT,
          contrato_id INT(11) NOT NULL,
          contrato_item_id INT(11) DEFAULT NULL,
          aluno_id INT(11) NOT NULL,
          modalidade_id INT(11) DEFAULT NULL,
          percentual DECIMAL(7,4) DEFAULT NULL COMMENT 'Fatia do valor, 0 a 100',
          valor DECIMAL(10,2) NOT NULL DEFAULT 0.00,
          criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          KEY idx_cr_contrato (contrato_id),
          KEY idx_cr_item (contrato_item_id),
          KEY idx_cr_aluno (aluno_id),
          KEY idx_cr_modalidade (modalidade_id),
          CONSTRAINT fk_cr_contrato FOREIGN KEY (contrato_id)
            REFERENCES contrato (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_cr_item FOREIGN KEY (contrato_item_id)
            REFERENCES contrato_item (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_cr_aluno FOREIGN KEY (aluno_id)
            REFERENCES alunos (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_cr_modalidade FOREIGN KEY (modalidade_id)
            REFERENCES modalidade (id) ON DELETE SET NULL ON UPDATE CASCADE
        ) ENGINE=InnoDB {COLLATE}
        COMMENT='Divisão do valor do contrato entre alunos/modalidades'
    """),
    ("matricula_modalidade", f"""
        CREATE TABLE matricula_modalidade (
          id INT(11) NOT NULL AUTO_INCREMENT,
          aluno_id INT(11) NOT NULL,
          modalidade_id INT(11) NOT NULL,
          contrato_id INT(11) DEFAULT NULL,
          data_inicio DATE DEFAULT NULL,
          data_fim DATE DEFAULT NULL,
          status ENUM('ativa','trancada','encerrada') NOT NULL DEFAULT 'ativa',
          origem VARCHAR(30) NOT NULL DEFAULT 'manual',
          criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          atualizado_em TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY unq_matmod_aluno_mod_contrato
                     (aluno_id, modalidade_id, contrato_id),
          KEY idx_matmod_modalidade (modalidade_id),
          KEY idx_matmod_contrato (contrato_id),
          KEY idx_matmod_status (status),
          CONSTRAINT fk_matmod_aluno FOREIGN KEY (aluno_id)
            REFERENCES alunos (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_matmod_modalidade FOREIGN KEY (modalidade_id)
            REFERENCES modalidade (id) ON DELETE CASCADE ON UPDATE CASCADE,
          CONSTRAINT fk_matmod_contrato FOREIGN KEY (contrato_id)
            REFERENCES contrato (id) ON DELETE SET NULL ON UPDATE CASCADE
        ) ENGINE=InnoDB {COLLATE}
        COMMENT='Matricula do aluno em uma modalidade, com vigencia'
    """),
]

# (tabela, coluna, definição). O DEFAULT de cada uma reproduz o que o sistema
# já faz hoje, para que nada mude de comportamento só por existir a coluna.
COLUNAS = [
    ("mensalidades", "tipo",
     "VARCHAR(20) NOT NULL DEFAULT 'simples' "
     "COMMENT 'simples, pacote ou combo'"),
    ("mensalidades", "qtd_min",
     "TINYINT(4) NOT NULL DEFAULT 1 COMMENT 'Minimo de modalidades do pacote'"),
    ("mensalidades", "qtd_max",
     "TINYINT(4) DEFAULT NULL COMMENT 'Maximo; NULL = sem teto'"),
    ("mensalidades", "periodicidade",
     "VARCHAR(20) NOT NULL DEFAULT 'mensal'"),
    ("mensalidades", "dia_vencimento_padrao",
     "TINYINT(4) DEFAULT NULL COMMENT '1 a 31; NULL = usa a regra da academia'"),
    ("mensalidades", "permite_desconto", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("mensalidades", "permite_alterar_valor", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("mensalidades", "permite_alterar_vencimento", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("mensalidade_aluno", "contrato_id",
     "INT(11) DEFAULT NULL COMMENT 'Contrato que gerou a cobranca'"),
    ("mensalidade_aluno", "competencia",
     "CHAR(7) DEFAULT NULL COMMENT 'AAAA-MM a que a cobranca se refere'"),
    ("mensalidade_aluno", "snapshot_pacote_nome", "VARCHAR(150) DEFAULT NULL"),
    ("mensalidade_aluno", "snapshot_modalidades",
     "VARCHAR(255) DEFAULT NULL COMMENT 'Modalidades no momento da cobranca'"),
    ("mensalidade_aluno", "snapshot_regra",
     "TEXT DEFAULT NULL COMMENT 'JSON da regra aplicada'"),
]

# Índices só de leitura; o único de (contrato_id, competencia) fica para o MM-06,
# depois que os contratos existirem.
INDICES = [
    ("mensalidade_aluno", "idx_ma_contrato", "(contrato_id)"),
    ("mensalidade_aluno", "idx_ma_competencia", "(competencia)"),
    ("mensalidades", "idx_mens_tipo", "(tipo)"),
]

FK_MA_CONTRATO = "fk_ma_contrato"


def _tem_tabela(cur, tabela):
    cur.execute(
        """SELECT 1 FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (tabela,))
    return cur.fetchone() is not None


def _tem_coluna(cur, tabela, coluna):
    cur.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
             AND COLUMN_NAME = %s""", (tabela, coluna))
    return cur.fetchone() is not None


def _tem_indice(cur, tabela, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
             AND INDEX_NAME = %s""", (tabela, nome))
    return cur.fetchone() is not None


def _tem_fk(cur, tabela, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
             AND CONSTRAINT_NAME = %s AND CONSTRAINT_TYPE = 'FOREIGN KEY'""",
        (tabela, nome))
    return cur.fetchone() is not None


def executar_migracao():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        sys.exit(1)

    cur = conn.cursor()
    try:
        for tabela, ddl in TABELAS:
            if _tem_tabela(cur, tabela):
                print(f"• Tabela {tabela} já existia.")
                continue
            cur.execute(ddl)
            conn.commit()
            print(f"✓ Tabela {tabela} criada.")

        for tabela, coluna, definicao in COLUNAS:
            if _tem_coluna(cur, tabela, coluna):
                print(f"• {tabela}.{coluna} já existia.")
                continue
            cur.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")
            conn.commit()
            print(f"✓ {tabela}.{coluna} criada.")

        for tabela, nome, colunas in INDICES:
            if _tem_indice(cur, tabela, nome):
                print(f"• Índice {nome} já existia.")
                continue
            cur.execute(f"ALTER TABLE {tabela} ADD KEY {nome} {colunas}")
            conn.commit()
            print(f"✓ Índice {nome} criado.")

        # A FK entra por último: depende da tabela contrato e da coluna nova.
        if _tem_fk(cur, "mensalidade_aluno", FK_MA_CONTRATO):
            print(f"• FK {FK_MA_CONTRATO} já existia.")
        else:
            cur.execute(
                f"""ALTER TABLE mensalidade_aluno
                    ADD CONSTRAINT {FK_MA_CONTRATO} FOREIGN KEY (contrato_id)
                    REFERENCES contrato (id) ON DELETE SET NULL ON UPDATE CASCADE""")
            conn.commit()
            print(f"✓ FK {FK_MA_CONTRATO} criada.")

        print("\nMigração concluída. Nenhum dado existente foi alterado.")
    except Exception as e:
        conn.rollback()
        print("Erro na migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter(forcar=False):
    """Desfaz o MM-02. Recusa se já houver dado nas tabelas novas.

    Depois do MM-03/04/05 essas tabelas passam a valer alguma coisa, e derrubá-las
    deixaria de ser uma reversão para virar perda de dado.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        nomes = [t for t, _ in TABELAS]
        ocupadas = []
        for tabela in nomes:
            if not _tem_tabela(cur, tabela):
                continue
            cur.execute(f"SELECT COUNT(*) FROM {tabela}")
            n = (cur.fetchone() or [0])[0]
            if n:
                ocupadas.append((tabela, n))
        if ocupadas and not forcar:
            print("Reversão recusada: há dados nas tabelas novas.")
            for tabela, n in ocupadas:
                print(f"  {tabela}: {n} registro(s)")
            print("Reverta antes os passos que popularam (MM-03 em diante), "
                  "ou use --forcar se tiver certeza.")
            return 0

        cur.execute("SELECT COUNT(*) FROM mensalidade_aluno WHERE contrato_id IS NOT NULL")
        vinculadas = (cur.fetchone() or [0])[0]
        if vinculadas and not forcar:
            print(f"Reversão recusada: {vinculadas} cobrança(s) já apontam para "
                  "contrato. Reverta o MM-05 antes, ou use --forcar.")
            return 0

        if _tem_fk(cur, "mensalidade_aluno", FK_MA_CONTRATO):
            cur.execute(f"ALTER TABLE mensalidade_aluno DROP FOREIGN KEY {FK_MA_CONTRATO}")
            conn.commit()
            print(f"✓ FK {FK_MA_CONTRATO} removida.")

        for tabela, nome, _ in INDICES:
            if _tem_indice(cur, tabela, nome):
                cur.execute(f"ALTER TABLE {tabela} DROP INDEX {nome}")
                conn.commit()
                print(f"✓ Índice {nome} removido.")

        for tabela, coluna, _ in COLUNAS:
            if _tem_coluna(cur, tabela, coluna):
                cur.execute(f"ALTER TABLE {tabela} DROP COLUMN {coluna}")
                conn.commit()
                print(f"✓ {tabela}.{coluna} removida.")

        # Ordem inversa da criação: filhas antes das mães.
        for tabela in reversed(nomes):
            if _tem_tabela(cur, tabela):
                cur.execute(f"DROP TABLE {tabela}")
                conn.commit()
                print(f"✓ Tabela {tabela} removida.")

        print("\nReversão concluída.")
        return 1
    except Exception as e:
        conn.rollback()
        print("Erro na reversão:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter(forcar="--forcar" in sys.argv)
    else:
        executar_migracao()
