#!/usr/bin/env python3
"""
Jiu-Jitsu deixa de ser modalidade privada da ArteFísica.

Ele foi cadastrado como `privada` com `id_academia = 2`, o que o tornava
invisível para qualquer outra academia. Enquanto só a ArteFísica dava jiu-jitsu
isso não incomodava; passa a incomodar agora que o sistema será vendido para
academias independentes de jiu-jitsu — elas não conseguiriam nem selecionar a
modalidade no cadastro.

Judô e Ginástica Artística já são públicas. Jiu-jitsu é um esporte, não um bem
de uma academia: a exceção é que estava errada.

Não muda nada para a ArteFísica — ela continua vendo e usando a modalidade
exatamente como antes, com as mesmas 14 faixas, turmas e planos.

Reversível: `--reverter` devolve a modalidade a privada da academia 2.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_jiujitsu_publico.py            # simula
  .venv/bin/python migrations/executar_jiujitsu_publico.py --aplicar
  .venv/bin/python migrations/executar_jiujitsu_publico.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

NOME = "Jiu-Jitsu"
ACADEMIA_DONA = 2


def _mostrar(cur):
    cur.execute(
        "SELECT id, nome, visibilidade, id_academia FROM modalidade WHERE nome = %s",
        (NOME,))
    m = cur.fetchone()
    if not m:
        print(f"Modalidade '{NOME}' não encontrada.")
        return None
    print(f"  {m['nome']}: visibilidade={m['visibilidade']} "
          f"id_academia={m['id_academia']}")
    return m


def aplicar(simular=True):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("Antes:")
        m = _mostrar(cur)
        if not m:
            return 0
        if m["visibilidade"] == "publica" and m["id_academia"] is None:
            print("• Já está pública. Nada a fazer.")
            return 0
        if simular:
            print("\nSIMULAÇÃO — viraria pública e sem dono. "
                  "Rode com --aplicar para valer.")
            return 1
        cur.execute(
            """UPDATE modalidade SET visibilidade = 'publica', id_academia = NULL
               WHERE id = %s""", (m["id"],))
        conn.commit()
        print("\nDepois:")
        _mostrar(cur)
        print("\n✓ Jiu-Jitsu agora é visível para qualquer academia.")
        return 1
    except Exception as e:
        conn.rollback()
        print("Erro:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """UPDATE modalidade SET visibilidade = 'privada', id_academia = %s
               WHERE nome = %s""", (ACADEMIA_DONA, NOME))
        conn.commit()
        print(f"✓ Jiu-Jitsu voltou a ser privado da academia {ACADEMIA_DONA}.")
        _mostrar(cur)
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
