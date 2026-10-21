"""Imprimir o material de qualquer faixa, ou o acumulado.

A apostila só saía por aluno: uma por pessoa marcada, com o material da faixa
do próximo exame dela. Quem queria o caderno de uma faixa — para a turma
inteira, para o mural, para quem ainda nem vai prestar exame — não tinha como.

Agora o mesmo diálogo imprime por faixa, e com `acumulado` a faixa sai com o
conteúdo somado desde a primeira: tudo o que se cobra até ali.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_apostila_impressao.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                      # noqa: E402
from config import get_db_connection                     # noqa: E402
from utils import exame_faixa as exf                     # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO      # noqa: E402

FOLHA = 'exf-apostila-folha"'
_falhas = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _cliente():
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(USUARIO_POR_MODO["admin"])
        sess["_fresh"] = True
        sess["modo_painel"] = "associacao"
    return c


def _programa():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id_associacao FROM exame_faixa_programa ORDER BY id LIMIT 1")
        linha = cur.fetchone()
        return exf.programa(cur, (linha or {}).get("id_associacao")) if linha else []
    finally:
        cur.close()
        conn.close()


def _tecnicas(conteudo):
    """Quantas técnicas um conteúdo cobra, somando os grupos práticos."""
    total = 0
    for chave in ("nage", "katame", "kaeshi", "renraku"):
        total += len((conteudo or {}).get(chave) or [])
    return total


def main():
    print("\nApostila: por aluno, por faixa, ou acumulada\n")
    prog = _programa()
    if len(prog) < 4:
        print("  Programa curto demais para testar.")
        return 1
    ultima = len(prog) - 1
    cli = _cliente()

    print("O conteúdo acumulado")
    acum = exf.promocao_acumulada(prog, ultima)
    checar("1. o acumulado vai da primeira faixa até a escolhida",
           acum["de"] == prog[0]["de"] and acum["para"] == prog[ultima]["para"],
           f'{acum["de"]} → {acum["para"]}')
    soma = sum(_tecnicas(p.get("conteudo")) for p in prog)
    checar("2. junta as técnicas de todas as promoções",
           _tecnicas(acum["conteudo"]) == soma,
           f'{_tecnicas(acum["conteudo"])} x {soma}')
    checar("3. é maior que o da faixa sozinha",
           _tecnicas(acum["conteudo"]) > _tecnicas(prog[ultima].get("conteudo")))
    # O acumulado reaproveita a composição do salto, mas não é um salto: a
    # apostila não pode sair marcada como se o aluno fosse pular faixa.
    checar("4. não se disfarça de salto de faixa", not acum.get("salto"))
    checar("5. diz de onde o conteúdo começa, para a revisão não repetir",
           acum.get("indice_de") == 0)
    checar("6. acumulado da primeira faixa é a própria faixa",
           _tecnicas(exf.promocao_acumulada(prog, 0)["conteudo"])
           == _tecnicas(prog[0].get("conteudo")))

    print("\nA impressão")
    r = cli.get("/exame-faixa/programa/apostilas?faixa=0", follow_redirects=True)
    h = r.get_data(as_text=True)
    checar("7. uma faixa marcada imprime uma apostila",
           r.status_code == 200 and h.count(FOLHA) == 1, f"{h.count(FOLHA)} folhas")
    checar("8. sem aluno, a apostila não mostra rótulo de aluno vazio",
           "Aluno: <strong></strong>" not in h and "Aluno: <strong>None" not in h)

    r3 = cli.get("/exame-faixa/programa/apostilas?faixa=0&faixa=1&faixa=2",
                 follow_redirects=True)
    h3 = r3.get_data(as_text=True)
    checar("9. três faixas marcadas imprimem três apostilas",
           h3.count(FOLHA) == 3, f"{h3.count(FOLHA)} folhas")

    r_ac = cli.get(f"/exame-faixa/programa/apostilas?faixa={ultima}&acumulado=1",
                   follow_redirects=True)
    h_ac = r_ac.get_data(as_text=True)
    r_so = cli.get(f"/exame-faixa/programa/apostilas?faixa={ultima}",
                   follow_redirects=True)
    h_so = r_so.get_data(as_text=True)
    n_ac = h_ac.count("exf-tecnicas__nome") + h_ac.count("exf-parl__txt")
    n_so = h_so.count("exf-tecnicas__nome") + h_so.count("exf-parl__txt")
    checar("10. o acumulado imprime muito mais técnica que a faixa sozinha",
           n_ac > n_so * 3, f"{n_ac} x {n_so}")
    checar("11. e continua numa apostila só", h_ac.count(FOLHA) == 1)
    checar("12. a apostila acumulada diz que é acumulada",
           "Material acumulado" in h_ac)
    checar("13. a apostila de uma faixa só não diz isso",
           "Material acumulado" not in h_so)
    # Marcar a mesma faixa com e sem acumulado não pode devolver o mesmo
    # material: o cache da montagem precisa distinguir os dois.
    checar("14. acumulado e faixa solta não se confundem no cache", n_ac != n_so)

    print("\nO diálogo oferece as faixas")
    hp = cli.get("/exame-faixa/programa", follow_redirects=True).get_data(as_text=True)
    caixas = re.findall(r'name="faixa" value="(\d+)"', hp)
    checar("15. o diálogo lista todas as promoções",
           len(caixas) == len(prog), f"{len(caixas)} de {len(prog)}")
    checar("16. e oferece o acumulado", 'name="acumulado"' in hp)
    checar("17. o botão de imprimir aparece mesmo sem aluno para marcar",
           "data-exf-apostila" in hp)

    print("\nNada marcado")
    r0 = cli.get("/exame-faixa/programa/apostilas", follow_redirects=True)
    checar("18. volta para o programa, sem imprimir folha nenhuma",
           r0.get_data(as_text=True).count(FOLHA) == 0
           and r0.request.path == "/exame-faixa/programa",
           r0.request.path)
    checar("19. faixa inexistente é ignorada, não quebra",
           cli.get("/exame-faixa/programa/apostilas?faixa=999",
                   follow_redirects=True).status_code == 200)

    print("\n" + ("TUDO PASSOU" if not _falhas else f"FALHARAM {len(_falhas)}: " + "; ".join(_falhas)))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
