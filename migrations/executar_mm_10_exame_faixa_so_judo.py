#!/usr/bin/env python3
"""
MM-10 — Exame de faixa só no judô.

O exame de faixa (programa kyu, banca, modo estudo) é do judô. Em vez de
amarrar isso no código, a regra vai para o "Menu por modalidade"
(`modalidade_menu`, MM-09): para cada modalidade ativa que NÃO é judô, o item
fica desligado nos modos em que a modalidade decide o menu:

  academia, professor     item "exame_faixa"   (Exame de faixa)
  aluno, responsável      item "exame_estudo"  (Exame de faixa — estudo)

Como o menu só esconde um item quando TODAS as modalidades em jogo o desligam,
academia de judô e jiu-jitsu continua vendo o exame (o judô quer); com o
jiu-jitsu escolhido no topo do sistema, ou numa academia/aluno sem judô, some.
O administrador pode religar pela tela Menu por modalidade.

Reversível: --reverter apaga só as linhas que esta migração criou.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_10_exame_faixa_so_judo.py            # simulação
  .venv/bin/python migrations/executar_mm_10_exame_faixa_so_judo.py --aplicar
  .venv/bin/python migrations/executar_mm_10_exame_faixa_so_judo.py --reverter
"""

import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

ITENS = [("academia", "exame_faixa"), ("professor", "exame_faixa"),
         ("aluno", "exame_estudo"), ("responsavel", "exame_estudo")]


def _eh_judo(nome):
    s = unicodedata.normalize("NFD", str(nome or "")).encode("ascii", "ignore").decode().lower()
    return "judo" in s


def _modalidades(cur):
    cur.execute("SELECT id, nome FROM modalidade WHERE ativo = 1 ORDER BY id")
    return [m for m in cur.fetchall() if not _eh_judo(m["nome"])]


def main():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        chaves = tuple({c for _m, c in ITENS})
        if "--reverter" in sys.argv:
            cur.execute(f"""DELETE FROM modalidade_menu WHERE ativo = 0
                            AND item_chave IN ({','.join(['%s'] * len(chaves))})""", chaves)
            conn.commit()
            print(f"✓ {cur.rowcount} linha(s) removida(s); o exame volta a seguir o código.")
            return
        mods = _modalidades(cur)
        if "--aplicar" not in sys.argv:
            print("MM-10 — simulação (nada foi gravado)\n")
            print("  modalidades (não judô) que deixam de ver o exame de faixa:")
            for m in mods:
                print(f"      {m['id']:>3}  {m['nome']}")
            print(f"  linhas em modalidade_menu: {len(mods) * len(ITENS)}")
            print("\nPara aplicar:  --aplicar")
            return
        n = 0
        for m in mods:
            for modo, chave in ITENS:
                cur.execute("""INSERT INTO modalidade_menu (modalidade_id, modo, item_chave, ativo)
                               VALUES (%s,%s,%s,0) ON DUPLICATE KEY UPDATE ativo = 0""", (m["id"], modo, chave))
                n += 1
        conn.commit()
        print(f"✓ Exame de faixa desligado em {len(mods)} modalidade(s) que não são judô ({n} linhas).")
        print("\nMigração concluída. Vale em até 60 s em todos os workers (cache do menu).")
    except Exception as e:
        conn.rollback()
        print("Erro:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
