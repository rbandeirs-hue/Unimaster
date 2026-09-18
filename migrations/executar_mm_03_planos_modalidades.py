#!/usr/bin/env python3
"""
MM-03 — Diz quais modalidades cada plano cobre.

Passo 3 da evolução. Preenche `mensalidade_modalidade` e classifica os planos em
`mensalidades.tipo` / `qtd_min` / `qtd_max`. Sem isto, "Judô e Jiu-jitsu" é só um
texto: o sistema não sabe que aquele aluno treina duas coisas.

Como cada plano é resolvido, nesta ordem:

  1. pelo próprio nome — os termos judô, jiu-jitsu e ginástica são procurados no
     nome normalizado (sem acento, minúsculo). "Rendimento" NÃO é modalidade, é
     nível de treino: por isso "Judô, Rendimento e Jiu-jitsu" resolve para
     Judô + Jiu-Jitsu, como o gestor confirmou;
  2. nome genérico ("Mensalidade", "TEste") — cai para a única modalidade que os
     alunos daquela academia realmente praticam. Só vale quando é UMA;
  3. não deu para decidir — o plano é listado como PENDENTE e nada é gravado
     para ele. O resto da migração segue.

A modalidade precisa estar visível para a academia do plano: ou é global
(id_academia NULL), ou é da própria academia. Isso evita cruzar academias.

Nada é apagado. A reversão remove só as linhas que este passo criou e devolve
`tipo`/`qtd_min`/`qtd_max` ao padrão de fábrica ('simples', 1, NULL).

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_03_planos_modalidades.py            # simula
  .venv/bin/python migrations/executar_mm_03_planos_modalidades.py --aplicar
  .venv/bin/python migrations/executar_mm_03_planos_modalidades.py --reverter
"""
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

# termo procurado no nome do plano -> termo procurado no nome da modalidade.
# A ordem importa: a primeira encontrada vira a principal do pacote.
TERMOS = [
    ("judo", "judo"),
    ("jiu", "jiu"),
    ("ginastica", "ginastica"),
]


def _normalizar(texto):
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()


def _modalidades_visiveis(cur, id_academia):
    cur.execute(
        """SELECT id, nome FROM modalidade
           WHERE ativo = 1 AND (id_academia IS NULL OR id_academia = %s)
           ORDER BY id""", (id_academia,))
    return cur.fetchall() or []


def _modalidades_da_academia(cur, id_academia):
    """O que os alunos daquela academia praticam de fato."""
    cur.execute(
        """SELECT DISTINCT md.id, md.nome
           FROM aluno_modalidades am
           JOIN alunos a ON a.id = am.aluno_id
           JOIN modalidade md ON md.id = am.modalidade_id
           WHERE a.id_academia = %s""", (id_academia,))
    return cur.fetchall() or []


def _resolver(cur, plano):
    """(lista de (modalidade_id, nome), motivo) — lista vazia = pendente."""
    visiveis = _modalidades_visiveis(cur, plano["id_academia"])
    nome_plano = _normalizar(plano["nome"])

    achadas, vistos = [], set()
    for termo_plano, termo_mod in TERMOS:
        if termo_plano not in nome_plano:
            continue
        for m in visiveis:
            if termo_mod in _normalizar(m["nome"]) and m["id"] not in vistos:
                achadas.append((m["id"], m["nome"]))
                vistos.add(m["id"])
                break
    if achadas:
        return achadas, "nome do plano"

    praticadas = _modalidades_da_academia(cur, plano["id_academia"])
    if len(praticadas) == 1:
        m = praticadas[0]
        return [(m["id"], m["nome"])], "única modalidade da academia"
    return [], ("nome genérico e %d modalidade(s) na academia"
                % len(praticadas))


def aplicar(simular=True):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT m.id, m.nome, m.id_academia, m.ativo, a.nome AS academia
               FROM mensalidades m LEFT JOIN academias a ON a.id = m.id_academia
               ORDER BY m.id_academia, m.id""")
        planos = cur.fetchall() or []

        gravados, pendentes = 0, []
        for plano in planos:
            modalidades, motivo = _resolver(cur, plano)
            rotulo = f"{plano['nome'][:34]:34} ({plano['academia'] or 's/ academia'})"
            if not modalidades:
                pendentes.append((plano, motivo))
                print(f"  ? {rotulo} PENDENTE — {motivo}")
                continue

            nomes = " + ".join(n for _, n in modalidades)
            tipo = "pacote" if len(modalidades) > 1 else "simples"
            print(f"  ✓ {rotulo} {tipo:7} {nomes}   [{motivo}]")

            if simular:
                continue
            for pos, (mod_id, _) in enumerate(modalidades):
                cur.execute(
                    """INSERT IGNORE INTO mensalidade_modalidade
                         (mensalidade_id, modalidade_id, principal)
                       VALUES (%s, %s, %s)""",
                    (plano["id"], mod_id, 1 if pos == 0 else 0))
                gravados += cur.rowcount
            cur.execute(
                """UPDATE mensalidades
                      SET tipo = %s, qtd_min = %s, qtd_max = %s
                    WHERE id = %s""",
                (tipo, len(modalidades), len(modalidades), plano["id"]))

        if simular:
            conn.rollback()
            print(f"\nSIMULAÇÃO — {len(planos)} plano(s) analisados, "
                  f"{len(pendentes)} pendente(s). Rode com --aplicar para valer.")
        else:
            conn.commit()
            print(f"\n✓ {gravados} vínculo(s) plano→modalidade gravados.")
            if pendentes:
                print(f"⚠ {len(pendentes)} plano(s) ficaram sem modalidade e "
                      "precisam ser definidos na tela de planos:")
                for plano, motivo in pendentes:
                    print(f"    id={plano['id']} {plano['nome']} — {motivo}")
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
        cur.execute(
            """UPDATE mensalidades SET tipo = 'simples', qtd_min = 1, qtd_max = NULL
               WHERE id IN (SELECT mensalidade_id FROM mensalidade_modalidade)""")
        planos = cur.rowcount
        cur.execute("DELETE FROM mensalidade_modalidade")
        vinculos = cur.rowcount
        conn.commit()
        print(f"✓ {vinculos} vínculo(s) removidos e {planos} plano(s) "
              "devolvidos ao padrão.")
        return vinculos
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
