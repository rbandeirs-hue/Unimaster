"""O filtro de modalidade do painel da academia recorta os indicadores.

A queixa
--------
"O filtro de modalidade não muda nada nos indicadores." Ele mudava — mas só
depois de clicar em "Aplicar", enquanto todo o resto do sistema aplica ao
trocar. E os números que continuam da academia inteira (Receitas, Despesas,
Saldo) não diziam isso em lugar nenhum, o que confirmava a impressão de que o
filtro estava quebrado.

Estes testes fixam as duas coisas: o que o recorte alcança, e o que ele
declaradamente não alcança.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_dash_filtro_modalidade.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                    # noqa: E402
from config import get_db_connection                   # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO    # noqa: E402

ACADEMIA = -9900
_falhas = []
ids = {}


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _conn():
    c = get_db_connection()
    return c, c.cursor(dictionary=True)


def limpar():
    c, cur = _conn()
    cur.execute("""DELETE am FROM aluno_modalidades am JOIN alunos a
                   ON a.id = am.aluno_id WHERE a.id_academia = %s""", (ACADEMIA,))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM modalidade WHERE nome LIKE 'ZZ Dash%'")
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Dash Academia')",
                (ACADEMIA,))
    for chave, nome in (("a", "ZZ Dash Alfa"), ("b", "ZZ Dash Beta")):
        cur.execute("INSERT INTO modalidade (nome, ativo, visibilidade) "
                    "VALUES (%s, 1, 'publica')", (nome,))
        ids[chave] = cur.lastrowid
    # 7 alunos na Alfa, 2 na Beta. Números diferentes de propósito: se o filtro
    # não funcionasse, os dois recortes dariam 9.
    for n in range(7):
        cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, status)
                       VALUES (%s, %s, 1, 'ativo')""", (ACADEMIA, f"ZZ Alfa {n}"))
        cur.execute("INSERT INTO aluno_modalidades (aluno_id, modalidade_id) "
                    "VALUES (%s,%s)", (cur.lastrowid, ids["a"]))
    for n in range(2):
        cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, status)
                       VALUES (%s, %s, 1, 'ativo')""", (ACADEMIA, f"ZZ Beta {n}"))
        cur.execute("INSERT INTO aluno_modalidades (aluno_id, modalidade_id) "
                    "VALUES (%s,%s)", (cur.lastrowid, ids["b"]))
    cur.execute("INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id) "
                "VALUES (%s,%s)", (USUARIO_POR_MODO["admin"], ACADEMIA))
    c.commit(); cur.close(); c.close()


def _cliente():
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO_POR_MODO["admin"])
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = ACADEMIA
    return cli


def _indicadores(cli, url):
    h = cli.get(url, follow_redirects=True).get_data(as_text=True)
    pares = re.findall(
        r'dash-ind__rotulo[^>]*>\s*([^<]+?)\s*'
        r'(?:<span class="dash-ind__alcance">([^<]*)</span>)?\s*</div>\s*'
        r'<div class="dash-ind__valor[^>]*>\s*([^<]*)<', h, re.S)
    return h, {r.strip(): (v.strip(), (a or "").strip()) for r, a, v in pares}


def main():
    limpar()
    montar()
    try:
        cli = _cliente()
        base = f"/academia/dash?academia_id={ACADEMIA}"

        print("\nO recorte muda os números\n")

        h0, sem = _indicadores(cli, base)
        _h, alfa = _indicadores(cli, base + f"&modalidade_id={ids['a']}")
        _h, beta = _indicadores(cli, base + f"&modalidade_id={ids['b']}")

        checar("1. sem filtro, conta os 9 alunos",
               sem.get("Alunos ativos", ("",))[0] == "9",
               str(sem.get("Alunos ativos")))
        checar("2. na Alfa, 7", alfa.get("Alunos ativos", ("",))[0] == "7",
               str(alfa.get("Alunos ativos")))
        checar("3. na Beta, 2", beta.get("Alunos ativos", ("",))[0] == "2",
               str(beta.get("Alunos ativos")))
        checar("4. e os dois recortes diferem entre si",
               alfa.get("Alunos ativos") != beta.get("Alunos ativos"))

        print("\nO filtro aplica ao trocar, sem depender do botão\n")

        checar("5. o formulário tem id para o script achar", 'id="formFiltros"' in h0)
        checar("6. e os selects submetem ao mudar",
               "f.submit()" in h0 and "addEventListener('change'" in h0)
        checar("7. o botão Aplicar continua existindo",
               "Aplicar" in h0)

        print("\nA tela diz o alcance de cada número\n")

        checar("8. sem filtro, nenhum indicador ganha etiqueta",
               all(a == "" for _v, a in sem.values()),
               str({k: v for k, v in sem.items() if v[1]}))
        checar("9. com filtro, os de aluno dizem 'no recorte'",
               alfa.get("Alunos ativos", ("", ""))[1] == "no recorte",
               str(alfa.get("Alunos ativos")))
        checar("10. e os financeiros dizem 'toda a academia'",
               alfa.get("Receitas", ("", ""))[1] == "toda a academia"
               and alfa.get("Despesas", ("", ""))[1] == "toda a academia",
               f"{alfa.get('Receitas')} {alfa.get('Despesas')}")
        checar("11. receita realmente não muda com o recorte",
               sem.get("Receitas") and
               sem["Receitas"][0] == alfa["Receitas"][0],
               f"{sem.get('Receitas')} {alfa.get('Receitas')}")

        print("\nA lista de alunos não repete quem tem duas modalidades\n")

        # O aluno da Alfa ganha também a Beta: com o agrupamento por modalidade
        # alimentando a tabela, ele aparecia duas vezes seguidas — e o rodapé,
        # que conta alunos distintos, dizia um número menor que o de linhas.
        c, cur = _conn()
        cur.execute("""SELECT id FROM alunos WHERE id_academia = %s
                       AND nome = 'ZZ Alfa 0'""", (ACADEMIA,))
        alvo = cur.fetchone()["id"]
        cur.execute("INSERT INTO aluno_modalidades (aluno_id, modalidade_id) "
                    "VALUES (%s,%s)", (alvo, ids["b"]))
        c.commit(); cur.close(); c.close()

        h = cli.get(f"/alunos/lista_alunos?academia_id={ACADEMIA}&filtro_ativo=ativo",
                    follow_redirects=True).get_data(as_text=True)
        from collections import Counter
        vistos = Counter(re.findall(r'data-href="[^"]*aluno_id=(\d+)', h))
        repetidos = [i for i, n in vistos.items() if n > 1]
        linhas = len(re.findall(r'<tr class="al-linha"', h))
        rodape = re.search(r'Mostrando\s+(\d+)\s+de\s+(\d+)', h)
        checar("13. aluno de duas modalidades aparece uma vez só",
               not repetidos, str(repetidos))
        checar("14. e o rodapé bate com o número de linhas",
               rodape and int(rodape.group(1)) == linhas,
               f"rodapé={rodape.group(1) if rodape else '?'} linhas={linhas}")

        print("\nFiltro inválido não vira recorte vazio\n")

        _h, invalido = _indicadores(cli, base + "&modalidade_id=999999")
        checar("12. modalidade de fora da academia é ignorada",
               invalido.get("Alunos ativos", ("",))[0] == "9",
               str(invalido.get("Alunos ativos")))
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
