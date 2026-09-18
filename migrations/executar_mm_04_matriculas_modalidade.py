#!/usr/bin/env python3
"""
MM-04 — Cria a matrícula do aluno por modalidade.

Passo 4 da evolução. `aluno_modalidades` guarda só o par aluno↔modalidade, sem
data e sem situação: serve para dizer "faz judô", não para dizer "faz judô desde
março, e trancou em agosto". `matricula_modalidade` é essa segunda leitura, e é
dela que o contexto operacional (ver só o judô, só a ginástica) vai depender.

A tabela antiga NÃO é tocada. As duas convivem: quem lê `aluno_modalidades` hoje
continua lendo a mesma coisa.

De onde cada matrícula sai:

  1. `aluno_modalidades` — a fonte principal, uma matrícula por par existente;
  2. aluno sem nenhum par, numa academia que pratica UMA única modalidade — a
     matrícula é criada com essa modalidade, marcada como inferida;
  3. aluno sem par numa academia com várias (ou nenhuma) modalidades — fica
     PENDENTE, listado no fim, e nada é gravado. Chutar aqui misturaria
     modalidade de aluno, que é justamente o que não pode acontecer.

Correspondências:
  data_inicio  <- alunos.data_matricula
  status       <- ativo→ativa, suspenso→trancada, inativo/formado→encerrada
  contrato_id  fica NULL; quem preenche é o MM-05.

Idempotente: o índice único (aluno, modalidade, contrato) impede repetição.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_04_matriculas_modalidade.py            # simula
  .venv/bin/python migrations/executar_mm_04_matriculas_modalidade.py --aplicar
  .venv/bin/python migrations/executar_mm_04_matriculas_modalidade.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

ORIGENS = ("mm04_vinculo", "mm04_inferida")

STATUS_ALUNO = {
    "ativo": "ativa",
    "suspenso": "trancada",
    "inativo": "encerrada",
    "formado": "encerrada",
}

SQL_VINCULOS = """
SELECT am.aluno_id, am.modalidade_id, a.data_matricula, a.status, a.id_academia
FROM aluno_modalidades am
JOIN alunos a ON a.id = am.aluno_id
GROUP BY am.aluno_id, am.modalidade_id
ORDER BY am.aluno_id, am.modalidade_id
"""

SQL_SEM_VINCULO = """
SELECT a.id AS aluno_id, a.nome, a.data_matricula, a.status, a.id_academia
FROM alunos a
WHERE NOT EXISTS (SELECT 1 FROM aluno_modalidades am WHERE am.aluno_id = a.id)
ORDER BY a.id_academia, a.id
"""

# O que os alunos de cada academia praticam de fato — a base da inferência.
SQL_MODALIDADES_POR_ACADEMIA = """
SELECT a.id_academia, am.modalidade_id, md.nome
FROM aluno_modalidades am
JOIN alunos a ON a.id = am.aluno_id
JOIN modalidade md ON md.id = am.modalidade_id
GROUP BY a.id_academia, am.modalidade_id, md.nome
"""


def _inserir(cur, linha, modalidade_id, origem):
    cur.execute(
        """INSERT IGNORE INTO matricula_modalidade
             (aluno_id, modalidade_id, contrato_id, data_inicio, status, origem)
           VALUES (%s, %s, NULL, %s, %s, %s)""",
        (linha["aluno_id"], modalidade_id, linha["data_matricula"],
         STATUS_ALUNO.get(linha["status"], "ativa"), origem))
    return cur.rowcount


def aplicar(simular=True):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(SQL_MODALIDADES_POR_ACADEMIA)
        por_academia = {}
        for r in cur.fetchall() or []:
            por_academia.setdefault(r["id_academia"], []).append(
                (r["modalidade_id"], r["nome"]))

        cur.execute(SQL_VINCULOS)
        vinculos = cur.fetchall() or []
        criadas = 0
        for linha in vinculos:
            if not simular:
                criadas += _inserir(cur, linha, linha["modalidade_id"],
                                    "mm04_vinculo")
        print(f"  {len(vinculos)} matrícula(s) a partir de aluno_modalidades.")

        cur.execute(SQL_SEM_VINCULO)
        inferidas, pendentes = 0, []
        for linha in cur.fetchall() or []:
            opcoes = por_academia.get(linha["id_academia"], [])
            if len(opcoes) != 1:
                pendentes.append((linha, len(opcoes)))
                continue
            mod_id, mod_nome = opcoes[0]
            inferidas += 1
            print(f"  ~ {linha['nome'][:30]:30} academia {linha['id_academia']:>3}"
                  f"  → {mod_nome} (inferida)")
            if not simular:
                criadas += _inserir(cur, linha, mod_id, "mm04_inferida")

        if simular:
            conn.rollback()
            print(f"\nSIMULAÇÃO — {len(vinculos)} do vínculo + {inferidas} "
                  f"inferida(s) = {len(vinculos) + inferidas} matrícula(s). "
                  "Rode com --aplicar para valer.")
        else:
            conn.commit()
            print(f"\n✓ {criadas} matrícula(s) de modalidade criadas.")

        if pendentes:
            print(f"\n⚠ {len(pendentes)} aluno(s) sem modalidade definida — "
                  "precisam ser ajustados na ficha do aluno:")
            for linha, n in pendentes:
                motivo = ("academia com %d modalidades" % n) if n else \
                         "academia sem nenhuma modalidade registrada"
                print(f"    id={linha['aluno_id']:4} {linha['nome'][:32]:32} "
                      f"academia {linha['id_academia']} — {motivo}")
        return len(pendentes)
    except Exception as e:
        conn.rollback()
        print("Erro:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        marcas = ",".join(["%s"] * len(ORIGENS))
        cur.execute(
            f"""SELECT COUNT(*) FROM matricula_modalidade
                WHERE origem IN ({marcas}) AND contrato_id IS NOT NULL""", ORIGENS)
        presas = (cur.fetchone() or [0])[0]
        if presas:
            print(f"Reversão recusada: {presas} matrícula(s) já foram ligadas a "
                  "contrato. Reverta o MM-05 antes.")
            return 0
        cur.execute(
            f"DELETE FROM matricula_modalidade WHERE origem IN ({marcas})", ORIGENS)
        n = cur.rowcount
        conn.commit()
        print(f"✓ {n} matrícula(s) de modalidade removidas.")
        return n
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
        aplicar(simular="--aplicar" not in sys.argv)
