#!/usr/bin/env python3
"""
GR-01 — Jiu-Jitsu: faixas com grau (16 etapas × 4 graus = 64 níveis).

A escala do Jiu-Jitsu passa a começar por 16 etapas, em 4 grupos, cada etapa
com Grau 1 a Grau 4:

  Grupo Cinza    Branca · Cinza/Branca · Cinza · Cinza/Preta
  Grupo Amarelo  Amarela/Branca · Amarela · Amarela/Lisa · Amarela/Preta
  Grupo Laranja  Laranja/Branca · Laranja · Laranja/Lisa · Laranja/Preta
  Grupo Verde    Verde/Branca · Verde · Verde/Lisa · Verde/Preta

Cada nível é uma linha de `graduacao` (modalidade Jiu-Jitsu): `faixa` = a
etapa, `graduacao` = "1º grau".."4º grau", `categoria` = o grupo. Fica
configurável na tela de graduações da modalidade (nome, grupo e ordem).

As faixas adultas (Azul, Roxa, Marrom, Preta e graus) vêm depois, na mesma
escala, com a ordem empurrada para depois das 64.

Alunos não mudam (decisão do usuário): as 5 faixas antigas sem grau (Branca,
Cinza, Amarela, Laranja, Verde) ficam DESATIVADAS para novos cadastros — quem
está nelas continua nelas, e a ficha continua mostrando — e ganham a ordem da
etapa equivalente (Grau 1), para "próxima faixa" seguir fazendo sentido até a
academia reclassificar cada aluno.

Antes de gravar, faz backup das graduações do Jiu-Jitsu em /var/backups/unimaster.
`--reverter` apaga as 64 linhas novas (só se nenhum aluno/histórico as usar) e
restaura ordem, categoria e ativo das antigas a partir do backup.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_gr_01_jiujitsu_graus.py            # simulação
  .venv/bin/python migrations/executar_gr_01_jiujitsu_graus.py --aplicar
  .venv/bin/python migrations/executar_gr_01_jiujitsu_graus.py --reverter
"""

import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

DIR_BACKUP = Path("/var/backups/unimaster")
MARCA = "GR-01"  # vai em `observacao` das linhas criadas: é como o --reverter as acha

GRUPOS = [
    ("Grupo Cinza", ["Branca", "Cinza/Branca", "Cinza", "Cinza/Preta"]),
    ("Grupo Amarelo", ["Amarela/Branca", "Amarela", "Amarela/Lisa", "Amarela/Preta"]),
    ("Grupo Laranja", ["Laranja/Branca", "Laranja", "Laranja/Lisa", "Laranja/Preta"]),
    ("Grupo Verde", ["Verde/Branca", "Verde", "Verde/Lisa", "Verde/Preta"]),
]
GRAUS = ["1º grau", "2º grau", "3º grau", "4º grau"]
ANTIGAS_SEM_GRAU = ["Branca", "Cinza", "Amarela", "Laranja", "Verde"]


def _norm(t):
    s = unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _niveis():
    """[(ordem, grupo, faixa, grau)] — 64 níveis, ordem 1..64."""
    out, ordem = [], 0
    for grupo, etapas in GRUPOS:
        for etapa in etapas:
            for grau in GRAUS:
                ordem += 1
                out.append((ordem, grupo, etapa, grau))
    return out


def _modalidade(cur):
    cur.execute("""SELECT id FROM modalidade WHERE LOWER(REPLACE(REPLACE(nome,'-',''),' ','')) LIKE '%%jiujitsu%%'
                   ORDER BY id LIMIT 1""")
    r = cur.fetchone()
    return r["id"] if r else None


def _estado(cur, mod):
    cur.execute("SELECT * FROM graduacao WHERE modalidade_id = %s ORDER BY ordem, id", (mod,))
    linhas = cur.fetchall()
    novas = [g for g in linhas if (g.get("observacao") or "") == MARCA]
    antigas = [g for g in linhas if (g.get("observacao") or "") != MARCA]
    sem_grau = [g for g in antigas if _norm(g["faixa"]) in {_norm(x) for x in ANTIGAS_SEM_GRAU}]
    adultas = [g for g in antigas if g not in sem_grau]
    return linhas, novas, sem_grau, adultas


def _uso(cur, ids):
    if not ids:
        return 0
    ph = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT COUNT(*) AS n FROM alunos WHERE graduacao_id IN ({ph})", tuple(ids))
    n = cur.fetchone()["n"]
    cur.execute(f"SELECT COUNT(*) AS n FROM aluno_graduacao WHERE graduacao_id IN ({ph})", tuple(ids))
    return n + cur.fetchone()["n"]


def simular():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        mod = _modalidade(cur)
        print("GR-01 — simulação (nada foi gravado)\n")
        if not mod:
            print("  Modalidade Jiu-Jitsu não encontrada.")
            return
        _l, novas, sem_grau, adultas = _estado(cur, mod)
        print(f"  modalidade Jiu-Jitsu                 : {mod}")
        print(f"  níveis com grau já criados           : {len(novas)} de 64")
        print(f"  faixas antigas sem grau (desativar)  : {', '.join(g['faixa'] for g in sem_grau) or '—'}")
        for g in sem_grau:
            print(f"      {g['faixa']:<10} alunos: {_uso(cur, [g['id']])}")
        print(f"  faixas adultas (vão para depois)     : {', '.join(g['faixa'] for g in adultas)}")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close(); conn.close()


def aplicar():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        mod = _modalidade(cur)
        if not mod:
            print("Modalidade Jiu-Jitsu não encontrada."); sys.exit(1)
        linhas, novas, sem_grau, adultas = _estado(cur, mod)
        if novas:
            print(f"• Já existem {len(novas)} níveis criados pela GR-01 — nada a fazer.")
            return
        DIR_BACKUP.mkdir(parents=True, exist_ok=True)
        destino = DIR_BACKUP / f"graduacao_jiujitsu_pre_gr01_{datetime.now():%Y%m%d_%H%M%S}.json"
        destino.write_text(json.dumps(
            [{k: g[k] for k in ("id", "faixa", "graduacao", "categoria", "ordem", "ativo")} for g in linhas],
            ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"✓ Backup: {destino}")

        ordem_nivel = {}
        for ordem, grupo, etapa, grau in _niveis():
            cur.execute(
                """INSERT INTO graduacao (faixa, graduacao, categoria, modalidade_id, ativo, ordem, observacao)
                   VALUES (%s,%s,%s,%s,1,%s,%s)""", (etapa, grau, grupo, mod, ordem, MARCA))
            if grau == GRAUS[0]:
                ordem_nivel[_norm(etapa)] = ordem
        print("✓ 64 níveis criados (16 etapas × 4 graus).")

        for g in sem_grau:
            cur.execute("""UPDATE graduacao SET ativo = 0, ordem = %s, categoria = 'Sem grau — reclassificar'
                           WHERE id = %s""", (ordem_nivel.get(_norm(g["faixa"]), 0), g["id"]))
        print(f"✓ {len(sem_grau)} faixas antigas sem grau desativadas para novos cadastros "
              f"(alunos continuam nelas).")
        for i, g in enumerate(sorted(adultas, key=lambda x: (x["ordem"] or 0, x["id"])), start=65):
            cur.execute("UPDATE graduacao SET ordem = %s WHERE id = %s", (i, g["id"]))
        print(f"✓ {len(adultas)} faixas adultas reordenadas para depois dos 64 níveis.")
        conn.commit()
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro:", e); sys.exit(1)
    finally:
        cur.close(); conn.close()


def reverter():
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        mod = _modalidade(cur)
        _l, novas, _s, _a = _estado(cur, mod)
        ids = [g["id"] for g in novas]
        if _uso(cur, ids):
            print("Há alunos ou histórico usando os níveis novos — reclassifique-os antes de reverter.")
            sys.exit(1)
        backups = sorted(DIR_BACKUP.glob("graduacao_jiujitsu_pre_gr01_*.json"))
        if not backups:
            print("Backup não encontrado."); sys.exit(1)
        for g in json.loads(backups[-1].read_text(encoding="utf-8")):
            cur.execute("UPDATE graduacao SET categoria=%s, ordem=%s, ativo=%s WHERE id=%s",
                        (g["categoria"], g["ordem"], g["ativo"], g["id"]))
        if ids:
            cur.execute(f"DELETE FROM graduacao WHERE id IN ({','.join(['%s'] * len(ids))})", tuple(ids))
        conn.commit()
        print(f"✓ {len(ids)} níveis removidos e graduações restauradas de {backups[-1].name}.")
    except Exception as e:
        conn.rollback()
        print("Erro:", e); sys.exit(1)
    finally:
        cur.close(); conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    elif "--aplicar" in sys.argv:
        aplicar()
    else:
        simular()
