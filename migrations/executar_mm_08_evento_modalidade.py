#!/usr/bin/env python3
"""
MM-08 — O evento passa a saber de qual modalidade ele é.

Hoje o calendário só consegue separar aula: o evento herda a modalidade da
turma, e quem não tem turma não tem modalidade nenhuma. Na prática isso é
quase todo o calendário — de 512 eventos ativos, 510 não têm turma. Resultado:
a academia que dá judô e jiu-jitsu vê os dois no mesmo mês, sem distinção.

Esta migração cria `eventos.modalidade_id`, nula por padrão:

  NULL  → lançamento geral (feriado, reunião, aviso). Aparece em qualquer
          recorte, e é o que continua valendo para os 595 eventos já gravados.
  id    → lançamento daquela modalidade. Some quando o contexto é outro.

O preenchimento automático só alcança o que é seguro deduzir: evento preso a
uma turma que tem exatamente uma modalidade. Turma com duas modalidades fica
NULL — chutar uma delas inventaria informação que ninguém deu.

Aditiva e reversível. Nenhuma linha existente muda de valor a não ser na
coluna nova, que até agora não existia.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_08_evento_modalidade.py            # simulação
  .venv/bin/python migrations/executar_mm_08_evento_modalidade.py --aplicar
  .venv/bin/python migrations/executar_mm_08_evento_modalidade.py --reverter
"""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

DIR_BACKUP = Path("/var/backups/unimaster")


def _tem_coluna(cur, tabela, coluna):
    cur.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (tabela, coluna))
    return cur.fetchone() is not None


def _tem_indice(cur, tabela, indice):
    cur.execute(
        """SELECT 1 FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s""",
        (tabela, indice))
    return cur.fetchone() is not None


def _backup():
    """Cópia da tabela eventos antes de mexer nela.

    O dump sai pela própria conexão da aplicação, em INSERTs: não depende do
    mysqldump estar instalado nem de a senha passar pela linha de comando.
    """
    import gzip
    DIR_BACKUP.mkdir(parents=True, exist_ok=True)
    destino = DIR_BACKUP / f"eventos_pre_mm08_{datetime.now():%Y%m%d_%H%M%S}.sql.gz"
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW CREATE TABLE eventos")
        ddl = cur.fetchone()[1]
        cur.execute("SELECT * FROM eventos ORDER BY id")
        colunas = [d[0] for d in cur.description]
        linhas = cur.fetchall()
        with gzip.open(destino, "wt", encoding="utf-8") as f:
            f.write("-- Unimaster / MM-08: eventos antes da coluna modalidade_id\n")
            f.write(f"-- {datetime.now():%Y-%m-%d %H:%M:%S} — {len(linhas)} linha(s)\n\n")
            f.write("DROP TABLE IF EXISTS eventos;\n" + ddl + ";\n\n")
            campos = ", ".join(f"`{c}`" for c in colunas)
            for linha in linhas:
                valores = ", ".join(_literal(v) for v in linha)
                f.write(f"INSERT INTO eventos ({campos}) VALUES ({valores});\n")
    finally:
        cur.close()
        conn.close()
    print(f"\u2713 Backup: {destino} ({destino.stat().st_size} bytes, {len(linhas)} linhas)")
    return destino


def _literal(valor):
    """Valor Python -> literal SQL, para o dump acima."""
    if valor is None:
        return "NULL"
    if isinstance(valor, (int, float)):
        return str(valor)
    texto = str(valor)
    return "'" + texto.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _plano(cur):
    """O que a migração faria, sem escrever nada."""
    cur.execute("SELECT COUNT(*) AS n FROM eventos")
    total = cur.fetchone()["n"]
    cur.execute(
        """SELECT m.id, m.nome, COUNT(*) AS n
           FROM eventos e
           JOIN turma_modalidades tm ON tm.turma_id = e.turma_id
           JOIN modalidade m ON m.id = tm.modalidade_id
           WHERE e.turma_id IS NOT NULL
             AND (SELECT COUNT(*) FROM turma_modalidades t2
                  WHERE t2.turma_id = e.turma_id) = 1
           GROUP BY m.id, m.nome ORDER BY n DESC""")
    por_mod = cur.fetchall() or []
    cur.execute(
        """SELECT COUNT(*) AS n FROM eventos e WHERE e.turma_id IS NOT NULL
             AND (SELECT COUNT(*) FROM turma_modalidades t2
                  WHERE t2.turma_id = e.turma_id) <> 1""")
    ambiguos = cur.fetchone()["n"]
    return total, por_mod, ambiguos


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        existe = _tem_coluna(cur, "eventos", "modalidade_id")
        total, por_mod, ambiguos = _plano(cur)
        print("MM-08 — simulação (nada foi gravado)\n")
        print(f"  coluna eventos.modalidade_id já existe : {'sim' if existe else 'não'}")
        print(f"  eventos na tabela                     : {total}")
        print(f"  seriam marcados automaticamente       : {sum(m['n'] for m in por_mod)}")
        for m in por_mod:
            print(f"      {m['nome']:<22} {m['n']}")
        print(f"  ficam gerais (NULL)                   : {total - sum(m['n'] for m in por_mod)}")
        if ambiguos:
            print(f"      dos quais com turma de várias/nenhuma modalidade: {ambiguos}")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close()
        conn.close()


def executar_migracao():
    _backup()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if _tem_coluna(cur, "eventos", "modalidade_id"):
            print("• Coluna modalidade_id já existia.")
        else:
            cur.execute(
                "ALTER TABLE eventos ADD COLUMN modalidade_id INT(11) DEFAULT NULL "
                "COMMENT 'Modalidade do lançamento; NULL = geral, aparece em todas'")
            conn.commit()
            print("✓ Coluna eventos.modalidade_id criada.")

        if _tem_indice(cur, "eventos", "idx_evento_modalidade"):
            print("• Índice idx_evento_modalidade já existia.")
        else:
            cur.execute("CREATE INDEX idx_evento_modalidade ON eventos (modalidade_id)")
            conn.commit()
            print("✓ Índice idx_evento_modalidade criado.")

        if _tem_indice(cur, "eventos", "fk_evento_modalidade"):
            print("• Chave estrangeira já existia.")
        else:
            # ON DELETE SET NULL: apagar uma modalidade não pode levar junto o
            # histórico do calendário — o lançamento volta a ser geral.
            cur.execute(
                "ALTER TABLE eventos ADD CONSTRAINT fk_evento_modalidade "
                "FOREIGN KEY (modalidade_id) REFERENCES modalidade (id) ON DELETE SET NULL")
            conn.commit()
            print("✓ Chave estrangeira fk_evento_modalidade criada.")

        # Só preenche o que está vazio: rodar de novo não desfaz escolha manual.
        cur.execute(
            """UPDATE eventos e
               JOIN turma_modalidades tm ON tm.turma_id = e.turma_id
               SET e.modalidade_id = tm.modalidade_id
               WHERE e.modalidade_id IS NULL
                 AND e.turma_id IS NOT NULL
                 AND (SELECT COUNT(*) FROM (SELECT * FROM turma_modalidades) t2
                      WHERE t2.turma_id = e.turma_id) = 1""")
        print(f"✓ {cur.rowcount} evento(s) herdaram a modalidade da turma.")
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
        if _tem_indice(cur, "eventos", "fk_evento_modalidade"):
            cur.execute("ALTER TABLE eventos DROP FOREIGN KEY fk_evento_modalidade")
            conn.commit()
            print("✓ Chave estrangeira removida.")
        if _tem_coluna(cur, "eventos", "modalidade_id"):
            cur.execute("ALTER TABLE eventos DROP COLUMN modalidade_id")
            conn.commit()
            print("✓ Coluna modalidade_id removida.")
        else:
            print("• Coluna modalidade_id já não existia.")
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
