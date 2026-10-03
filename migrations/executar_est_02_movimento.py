#!/usr/bin/env python3
"""
EST-02 — Locais, saldo e movimentações.

Duas fontes, de propósito
-------------------------
`estoque_movimento` é o histórico imutável: toda entrada, saída, transferência
e ajuste vira uma linha que nunca é apagada nem editada. `estoque_saldo` é a
verdade operacional: uma linha por (local, variação) com a quantidade atual.

Guardar as duas é redundância deliberada. Somar o histórico a cada consulta
não escala e, pior, não dá onde travar: duas saídas simultâneas do mesmo item
leriam o mesmo saldo e as duas passariam. Com a linha de saldo, o serviço faz
`SELECT ... FOR UPDATE` nela antes de mexer — é o mesmo padrão que
`utils/financeiro_core.py` usa para o saldo das contas, e pela mesma razão.

A conferência entre as duas é um teste, não uma esperança: `tests/test_estoque`
recalcula o saldo pelo histórico e compara.

Transferência grava DOIS movimentos — a saída na origem e a entrada no destino
— ligados por `movimento_par_id`. É assim que a associação abastece a academia
para revenda sem que a quantidade apareça ou suma do nada em algum lugar.

Estorno também é movimento novo, em sentido contrário, apontando o original em
`estorna_movimento_id`. Nada é excluído.

Aditiva e reversível.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_est_02_movimento.py            # simulação
  .venv/bin/python migrations/executar_est_02_movimento.py --aplicar
  .venv/bin/python migrations/executar_est_02_movimento.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

COLACAO = "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci"

TABELAS = [
    ("estoque_local", f"""
        CREATE TABLE estoque_local (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) DEFAULT NULL,
            id_associacao INT(11) DEFAULT NULL,
            nome VARCHAR(100) NOT NULL,
            padrao TINYINT(1) NOT NULL DEFAULT 0
                COMMENT 'Local sugerido quando a tela não pergunta',
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY unq_local_academia (id_academia, nome),
            UNIQUE KEY unq_local_associacao (id_associacao, nome),
            CONSTRAINT fk_estlocal_academia FOREIGN KEY (id_academia)
                REFERENCES academias (id) ON DELETE CASCADE,
            CONSTRAINT fk_estlocal_associacao FOREIGN KEY (id_associacao)
                REFERENCES associacoes (id) ON DELETE CASCADE
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Onde o material fica guardado. Separado de locais_treino de propósito'
    """),

    ("estoque_saldo", f"""
        CREATE TABLE estoque_saldo (
            local_id INT(11) NOT NULL,
            variacao_id INT(11) NOT NULL,
            quantidade INT(11) NOT NULL DEFAULT 0,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (local_id, variacao_id),
            KEY idx_saldo_variacao (variacao_id),
            CONSTRAINT fk_estsaldo_local FOREIGN KEY (local_id)
                REFERENCES estoque_local (id) ON DELETE CASCADE,
            CONSTRAINT fk_estsaldo_variacao FOREIGN KEY (variacao_id)
                REFERENCES estoque_variacao (id) ON DELETE CASCADE
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Verdade operacional. Travada com FOR UPDATE antes de qualquer mudança'
    """),

    ("estoque_movimento", f"""
        CREATE TABLE estoque_movimento (
            id INT(11) NOT NULL AUTO_INCREMENT,
            id_academia INT(11) DEFAULT NULL,
            id_associacao INT(11) DEFAULT NULL,
            local_id INT(11) NOT NULL,
            variacao_id INT(11) NOT NULL,
            sentido CHAR(1) NOT NULL COMMENT 'E = entrada, S = saída',
            motivo VARCHAR(30) NOT NULL
                COMMENT 'compra, doacao, ajuste_positivo, devolucao_saida, transferencia_entrada, estorno, venda, entrega_aluno, uso_interno, perda, avaria, ajuste_negativo, devolucao_fornecedor, transferencia_saida',
            quantidade INT(11) NOT NULL,
            saldo_depois INT(11) NOT NULL
                COMMENT 'Saldo do local após este movimento; congela a história',
            custo_unitario DECIMAL(10,2) DEFAULT NULL,
            preco_unitario DECIMAL(10,2) DEFAULT NULL COMMENT 'Só em venda',
            tabela_preco_id INT(11) DEFAULT NULL,
            aluno_id INT(11) DEFAULT NULL,
            usuario_id INT(11) DEFAULT NULL,
            observacao VARCHAR(255) DEFAULT NULL,
            origem VARCHAR(30) DEFAULT NULL
                COMMENT 'receita, cobranca_avulsa, inventario, transferencia…',
            origem_id INT(11) DEFAULT NULL,
            movimento_par_id INT(11) DEFAULT NULL COMMENT 'O outro lado da transferência',
            estorna_movimento_id INT(11) DEFAULT NULL COMMENT 'Movimento que este anula',
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_mov_academia (id_academia, criado_em),
            KEY idx_mov_associacao (id_associacao, criado_em),
            KEY idx_mov_variacao (variacao_id, criado_em),
            KEY idx_mov_local (local_id, criado_em),
            KEY idx_mov_aluno (aluno_id),
            KEY idx_mov_origem (origem, origem_id),
            KEY idx_mov_estorno (estorna_movimento_id),
            CONSTRAINT fk_estmov_local FOREIGN KEY (local_id)
                REFERENCES estoque_local (id) ON DELETE RESTRICT,
            CONSTRAINT fk_estmov_variacao FOREIGN KEY (variacao_id)
                REFERENCES estoque_variacao (id) ON DELETE RESTRICT,
            CONSTRAINT fk_estmov_aluno FOREIGN KEY (aluno_id)
                REFERENCES alunos (id) ON DELETE SET NULL,
            CONSTRAINT fk_estmov_usuario FOREIGN KEY (usuario_id)
                REFERENCES usuarios (id) ON DELETE SET NULL,
            CONSTRAINT fk_estmov_tabela FOREIGN KEY (tabela_preco_id)
                REFERENCES estoque_tabela_preco (id) ON DELETE SET NULL
        ) ENGINE=InnoDB {COLACAO}
          COMMENT='Histórico imutável. RESTRICT em local e variação: não se apaga o passado'
    """),
]

ORDEM_REVERSA = ["estoque_movimento", "estoque_saldo", "estoque_local"]


def _existe(cur, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (nome,))
    return cur.fetchone() is not None


def _pre_requisitos(cur):
    faltando = [t for t in ("estoque_variacao", "estoque_tabela_preco")
                if not _existe(cur, t)]
    return faltando


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("EST-02 — simulação (nada foi gravado)\n")
        faltando = _pre_requisitos(cur)
        if faltando:
            print("  ! EST-01 ainda não foi aplicada. Falta:", ", ".join(faltando))
            print("    Rode antes: migrations/executar_est_01_catalogo.py --aplicar\n")
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
            print("Erro: EST-01 precisa vir antes. Falta:", ", ".join(faltando))
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
