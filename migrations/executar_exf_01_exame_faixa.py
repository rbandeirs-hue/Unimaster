#!/usr/bin/env python3
"""
EXF-01 — Exame de faixa: programa por promoção, tabela de preços e prova.

Até aqui a graduação só existia como cadastro (`graduacao`, `aluno_graduacao`)
e o sistema calculava a próxima faixa e a idade mínima. O que se cobra em cada
exame, quanto custa e a nota de cada aluno ficavam no PDF do departamento
técnico e na planilha da banca. Esta migração traz isso para o banco:

  exame_faixa_programa   uma linha por promoção (de → para) de cada associação:
                         idade mínima/máxima, carência, VALOR (a tabela de
                         preços, editável) e o conteúdo cobrado em JSON.
  exame_faixa_avaliacao  a ficha da banca: técnicas sorteadas, nota de cada uma,
                         média por grupo, média geral e resultado.
  eventos_competicoes.exame_faixa
                         marca o evento como exame de faixa: o aluno que se
                         inscreve recebe o programa da sua faixa e, no dia, a
                         banca aplica a prova por ele.

O programa é semeado com o material 2026.1 da Judô ArteFísica
(utils/exame_faixa_dados.py) para cada associação que ainda não tem programa,
casando as faixas pelo nome com a tabela `graduacao` do judô. Faixa que não
casar é listada e fica de fora — nada é inventado.

Aditiva e reversível. Nenhuma linha existente muda.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_exf_01_exame_faixa.py            # simulação
  .venv/bin/python migrations/executar_exf_01_exame_faixa.py --aplicar
  .venv/bin/python migrations/executar_exf_01_exame_faixa.py --reverter
"""

import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402
from utils.exame_faixa_dados import EDICAO, PROGRAMA_2026_1  # noqa: E402

TABELA_PROGRAMA = """
CREATE TABLE IF NOT EXISTS exame_faixa_programa (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  id_associacao      INT           NULL,
  modalidade_id      INT           NULL,
  edicao             VARCHAR(20)   NULL,
  graduacao_de_id    INT           NOT NULL,
  graduacao_para_id  INT           NOT NULL,
  ordem              INT           NOT NULL DEFAULT 0,
  idade_minima       INT           NULL,
  idade_maxima       INT           NULL,
  carencia_meses     INT           NULL,
  valor              DECIMAL(10,2) NULL,
  conteudo           LONGTEXT      NOT NULL,
  ativo              TINYINT(1)    NOT NULL DEFAULT 1,
  atualizado_por     INT           NULL,
  atualizado_em      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_exf_prog_assoc_de (id_associacao, graduacao_de_id),
  KEY ix_exf_prog_para (graduacao_para_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

TABELA_AVALIACAO = """
CREATE TABLE IF NOT EXISTS exame_faixa_avaliacao (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  evento_id          INT           NULL,
  inscricao_id       INT           NULL,
  aluno_id           INT           NOT NULL,
  programa_id        INT           NULL,
  graduacao_de_id    INT           NULL,
  graduacao_para_id  INT           NULL,
  escopo             VARCHAR(12)   NOT NULL DEFAULT 'cumulativo',
  pesos              LONGTEXT      NULL,
  tecnicas           LONGTEXT      NULL,
  notas              LONGTEXT      NULL,
  medias             LONGTEXT      NULL,
  media_geral        DECIMAL(4,2)  NULL,
  nota_corte         DECIMAL(4,2)  NOT NULL DEFAULT 6.00,
  resultado          VARCHAR(12)   NOT NULL DEFAULT 'pendente',
  observacao         VARCHAR(500)  NULL,
  avaliador_id       INT           NULL,
  avaliado_em        DATETIME      NULL,
  aluno_graduacao_id INT           NULL,
  criado_em          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em      TIMESTAMP     NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_exf_aval_inscricao (inscricao_id),
  KEY ix_exf_aval_evento (evento_id),
  KEY ix_exf_aval_aluno (aluno_id),
  CONSTRAINT fk_exf_aval_aluno FOREIGN KEY (aluno_id) REFERENCES alunos (id) ON DELETE CASCADE,
  CONSTRAINT fk_exf_aval_evento FOREIGN KEY (evento_id)
    REFERENCES eventos_competicoes (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _norm(txt):
    """'Branca / Cinza' e 'BRANCA/CINZA' viram a mesma chave."""
    s = unicodedata.normalize("NFD", str(txt or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _tem_tabela(cur, tabela):
    cur.execute("SHOW TABLES LIKE %s", (tabela,))
    return cur.fetchone() is not None


def _tem_coluna(cur, tabela, coluna):
    cur.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (tabela, coluna))
    return cur.fetchone() is not None


def _modalidade_judo(cur):
    cur.execute(
        """SELECT id FROM modalidade
           WHERE LOWER(REPLACE(nome, 'ô', 'o')) LIKE '%%judo%%' ORDER BY id LIMIT 1""")
    r = cur.fetchone()
    return r["id"] if r else None


def _graduacoes_judo(cur, modalidade_id):
    """Primeira graduação ativa de cada nome de faixa, na ordem da tabela.

    As faixas coloridas têm um registro cada; a preta se repete por dan, mas o
    programa só vai até a marrom, então o primeiro de cada nome basta.
    """
    cur.execute(
        """SELECT id, faixa FROM graduacao
           WHERE modalidade_id = %s AND ativo = 1 ORDER BY ordem, id""", (modalidade_id,))
    por_nome = {}
    for g in cur.fetchall():
        por_nome.setdefault(_norm(g["faixa"]), g["id"])
    return por_nome


def _plano(cur):
    mod = _modalidade_judo(cur)
    grads = _graduacoes_judo(cur, mod) if mod else {}
    linhas, faltando = [], []
    for i, p in enumerate(PROGRAMA_2026_1, start=1):
        de_id, para_id = grads.get(_norm(p["de"])), grads.get(_norm(p["para"]))
        if not (de_id and para_id):
            faltando.append(f'{p["de"]} → {p["para"]}')
            continue
        linhas.append((i, de_id, para_id, p))
    cur.execute("SELECT id, nome FROM associacoes ORDER BY id")
    assocs = cur.fetchall()
    ja_tem = set()
    if _tem_tabela(cur, "exame_faixa_programa"):
        cur.execute("SELECT DISTINCT id_associacao FROM exame_faixa_programa")
        ja_tem = {r["id_associacao"] for r in cur.fetchall()}
    semear = [a for a in assocs if a["id"] not in ja_tem]
    return mod, linhas, faltando, assocs, semear


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        mod, linhas, faltando, assocs, semear = _plano(cur)
        print("EXF-01 — simulação (nada foi gravado)\n")
        print(f"  tabela exame_faixa_programa já existe   : {'sim' if _tem_tabela(cur, 'exame_faixa_programa') else 'não'}")
        print(f"  tabela exame_faixa_avaliacao já existe  : {'sim' if _tem_tabela(cur, 'exame_faixa_avaliacao') else 'não'}")
        print(f"  coluna eventos_competicoes.exame_faixa  : {'sim' if _tem_coluna(cur, 'eventos_competicoes', 'exame_faixa') else 'não'}")
        print(f"  modalidade judô                         : {mod or 'NÃO ENCONTRADA'}")
        print(f"  promoções do material {EDICAO} casadas   : {len(linhas)} de {len(PROGRAMA_2026_1)}")
        for f in faltando:
            print(f"      sem faixa correspondente: {f}")
        print(f"  associações a semear                    : {len(semear)} de {len(assocs)}")
        for a in semear:
            print(f"      {a['id']:>3}  {a['nome']}")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close()
        conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for nome, ddl in (("exame_faixa_programa", TABELA_PROGRAMA),
                          ("exame_faixa_avaliacao", TABELA_AVALIACAO)):
            existia = _tem_tabela(cur, nome)
            cur.execute(ddl)
            conn.commit()
            print(f"{'•' if existia else '✓'} Tabela {nome} {'já existia' if existia else 'criada'}.")

        if _tem_coluna(cur, "eventos_competicoes", "exame_faixa"):
            print("• Coluna eventos_competicoes.exame_faixa já existia.")
        else:
            cur.execute(
                "ALTER TABLE eventos_competicoes ADD COLUMN exame_faixa TINYINT(1) NOT NULL DEFAULT 0 "
                "COMMENT '1 = exame de faixa: inscrição traz o programa e a banca aplica a prova'")
            conn.commit()
            print("✓ Coluna eventos_competicoes.exame_faixa criada.")

        mod, linhas, faltando, _assocs, semear = _plano(cur)
        for f in faltando:
            print(f"⚠ Sem faixa correspondente em `graduacao`, fica de fora: {f}")
        for a in semear:
            for ordem, de_id, para_id, p in linhas:
                cur.execute(
                    """INSERT INTO exame_faixa_programa
                           (id_associacao, modalidade_id, edicao, graduacao_de_id, graduacao_para_id,
                            ordem, idade_minima, idade_maxima, carencia_meses, valor, conteudo)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (a["id"], mod, EDICAO, de_id, para_id, ordem, p["idade_minima"],
                     p["idade_maxima"], p["carencia_meses"], p["valor"],
                     json.dumps(p["conteudo"], ensure_ascii=False)))
            print(f"✓ Programa {EDICAO} semeado para {a['nome']} ({len(linhas)} promoções).")
        conn.commit()
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
        for nome in ("exame_faixa_avaliacao", "exame_faixa_programa"):
            if _tem_tabela(cur, nome):
                cur.execute(f"DROP TABLE {nome}")
                conn.commit()
                print(f"✓ Tabela {nome} removida.")
        if _tem_coluna(cur, "eventos_competicoes", "exame_faixa"):
            cur.execute("ALTER TABLE eventos_competicoes DROP COLUMN exame_faixa")
            conn.commit()
            print("✓ Coluna eventos_competicoes.exame_faixa removida.")
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
