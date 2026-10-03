#!/usr/bin/env python3
"""
MM-09 — Liga/desliga de itens de menu por modalidade.

Até agora, "isto é do judô" estava escrito no código: `utils/menu.py` decidia
esconder Zempo, Locais de treino, Modalidades, Currículo e os simuladores
olhando se o nome da modalidade tinha "jud". Toda vez que o dono do sistema
quis outra combinação — tirar Eventos e Competições do jiu-jitsu, por exemplo —
foi preciso mexer em código e publicar.

Esta migração cria `modalidade_menu`, onde cada linha é uma exceção:

    (modalidade_id, modo, item_chave, ativo)

Sem linha, o item segue a regra do código — ou seja, nada muda para quem não
for tocado aqui. Com linha, ela manda: `ativo = 0` esconde, `ativo = 1` mostra
mesmo onde o código esconderia.

Os modos cobertos são os que têm modalidade determinável: academia, professor,
aluno e responsável. Admin, federação e associação estão acima da modalidade e
não entram.

Semeia o que já era verdade, para a tela do administrador nascer refletindo o
sistema como ele está:

  modalidades que NÃO são judô   locais, modalidades, zempo (modo academia)
                                 curriculo, sim_graduacao, sim_categoria
                                 (modos aluno e responsável)
  Jiu-Jitsu                      eventos, competicoes, solicitacoes
                                 (modo academia) — pedido do dono do sistema

Aditiva e reversível: cria tabela nova e não toca em nenhuma existente.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_09_menu_modalidade.py            # simulação
  .venv/bin/python migrations/executar_mm_09_menu_modalidade.py --aplicar
  .venv/bin/python migrations/executar_mm_09_menu_modalidade.py --reverter
"""
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

TABELA = "modalidade_menu"

# O que o código de hoje esconde de quem não faz judô.
DESLIGA_SEM_JUDO = [
    ("academia", "locais"),
    ("academia", "modalidades"),
    ("academia", "zempo"),
    ("aluno", "curriculo"),
    ("aluno", "sim_graduacao"),
    ("aluno", "sim_categoria"),
    ("responsavel", "curriculo"),
    ("responsavel", "sim_graduacao"),
    ("responsavel", "sim_categoria"),
]

# Pedido explícito para o jiu-jitsu.
DESLIGA_JIU = [
    ("academia", "eventos"),
    ("academia", "competicoes"),
    ("academia", "solicitacoes"),
]


def _normalizar(texto):
    sem = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem if not unicodedata.combining(c)).lower()


def _tem_tabela(cur, nome):
    cur.execute(
        """SELECT 1 FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (nome,))
    return cur.fetchone() is not None


def _plano(cur):
    cur.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY nome")
    linhas = []
    for m in cur.fetchall() or []:
        nome = _normalizar(m["nome"])
        regras = []
        if "jud" not in nome:
            regras += DESLIGA_SEM_JUDO
        if "jiu" in nome:
            regras += DESLIGA_JIU
        linhas.append((m["id"], m["nome"], regras))
    return linhas


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("MM-09 — simulação (nada foi gravado)\n")
        print(f"  tabela {TABELA} já existe : "
              f"{'sim' if _tem_tabela(cur, TABELA) else 'não'}\n")
        for _id, nome, regras in _plano(cur):
            print(f"  {nome}")
            if not regras:
                print("      nada a desligar (mostra tudo)")
            for modo, chave in regras:
                print(f"      desliga  {modo:<12} {chave}")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close()
        conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if _tem_tabela(cur, TABELA):
            print(f"• Tabela {TABELA} já existia.")
        else:
            cur.execute(f"""
                CREATE TABLE {TABELA} (
                    id INT(11) NOT NULL AUTO_INCREMENT,
                    modalidade_id INT(11) NOT NULL,
                    modo VARCHAR(30) NOT NULL
                        COMMENT 'academia, professor, aluno, responsavel',
                    item_chave VARCHAR(50) NOT NULL
                        COMMENT 'chave do Item em utils/menu.py',
                    ativo TINYINT(1) NOT NULL DEFAULT 1,
                    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY unq_menu_modalidade (modalidade_id, modo, item_chave),
                    CONSTRAINT fk_menu_modalidade FOREIGN KEY (modalidade_id)
                        REFERENCES modalidade (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Exceções de menu por modalidade; sem linha vale o código'
            """)
            conn.commit()
            print(f"✓ Tabela {TABELA} criada.")

        gravadas = 0
        for mid, nome, regras in _plano(cur):
            for modo, chave in regras:
                # INSERT IGNORE: rodar de novo não desfaz o que o administrador
                # tiver mudado na tela depois.
                cur.execute(
                    f"""INSERT IGNORE INTO {TABELA}
                        (modalidade_id, modo, item_chave, ativo)
                        VALUES (%s, %s, %s, 0)""", (mid, modo, chave))
                gravadas += cur.rowcount
            if regras:
                print(f"✓ {nome}: {len(regras)} regra(s) consideradas.")
        conn.commit()
        print(f"\n{gravadas} linha(s) gravada(s). Migração concluída.")
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
        if _tem_tabela(cur, TABELA):
            cur.execute(f"DROP TABLE {TABELA}")
            conn.commit()
            print(f"✓ Tabela {TABELA} removida — o menu volta a seguir só o código.")
        else:
            print(f"• Tabela {TABELA} já não existia.")
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
