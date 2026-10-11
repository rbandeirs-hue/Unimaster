"""Despesa recorrente: o cadastro grava uma despesa por ocorrência.

Aluguel, internet, contador — contas que se repetem eram lançadas uma a uma
todo mês. Agora o cadastro tem "Despesa recorrente": escolhe a frequência e
quantas vezes, e as ocorrências entram de uma vez, cada uma um lançamento
comum, que se edita ou exclui sozinho.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_despesa_recorrente.py
"""
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                    # noqa: E402
from config import get_db_connection                   # noqa: E402
from blueprints.financeiro.routes import _datas_recorrencia  # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO    # noqa: E402

ACADEMIA = -9901
_falhas = []


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
    cur.execute("DELETE FROM despesas WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Recorrente')", (ACADEMIA,))
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


def _despesas():
    c, cur = _conn()
    cur.execute("SELECT descricao, valor, data FROM despesas WHERE id_academia = %s "
                "ORDER BY data, id", (ACADEMIA,))
    linhas = cur.fetchall()
    cur.close(); c.close()
    return linhas


def main():
    print("\nAs datas da série\n")

    d = _datas_recorrencia(date(2026, 1, 31), "mensal", 4)
    checar("1. mensal mantém o dia e cai no fim de meses curtos",
           d == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)],
           str(d))
    d = _datas_recorrencia(date(2026, 10, 5), "semanal", 3)
    checar("2. semanal anda de 7 em 7 dias",
           d == [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)], str(d))
    d = _datas_recorrencia(date(2028, 2, 29), "anual", 2)
    checar("3. anual em 29/02 vai para 28/02", d[1] == date(2029, 2, 28), str(d))

    limpar()
    montar()
    try:
        cli = _cliente()
        url = f"/financeiro/despesas/cadastrar?academia_id={ACADEMIA}"
        h = cli.get(url, follow_redirects=True).get_data(as_text=True)
        tok = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
        base = {"csrf_token": tok, "valor": "1500,00", "data": "2026-10-10",
                "categoria": "aluguel", "id_academia": ACADEMIA}

        print("\nA tela\n")
        checar("4. o cadastro oferece a opção", 'name="recorrente"' in h)

        print("\nO cadastro\n")
        cli.post(url, data={**base, "descricao": "Aluguel", "recorrente": "1",
                            "frequencia": "mensal", "vezes": "3"})
        linhas = _despesas()
        checar("5. grava uma despesa por ocorrência", len(linhas) == 3, str(len(linhas)))
        checar("6. uma por mês, a partir da data informada",
               [str(x["data"]) for x in linhas] == ["2026-10-10", "2026-11-10", "2026-12-10"],
               str([str(x["data"]) for x in linhas]))
        checar("7. a descrição numera a série",
               [x["descricao"] for x in linhas] == ["Aluguel (1/3)", "Aluguel (2/3)", "Aluguel (3/3)"],
               str([x["descricao"] for x in linhas]))

        limpar(); montar()
        cli.post(url, data={**base, "descricao": "Luz"})
        linhas = _despesas()
        checar("8. sem marcar, continua uma despesa só e sem numeração",
               len(linhas) == 1 and linhas[0]["descricao"] == "Luz", str(linhas))

        limpar(); montar()
        cli.post(url, data={**base, "descricao": "X", "recorrente": "1",
                            "frequencia": "mensal", "vezes": "500"})
        checar("9. quantidade fora do limite é recusada", not _despesas())

        cli.post(url, data={**base, "descricao": "X", "recorrente": "1",
                            "frequencia": "diaria", "vezes": "3"})
        checar("10. frequência desconhecida é recusada", not _despesas())

        print("\nA edição\n")
        cli.post(url, data={**base, "descricao": "Internet"})
        c, cur = _conn()
        cur.execute("SELECT id FROM despesas WHERE id_academia = %s", (ACADEMIA,))
        did = cur.fetchone()["id"]
        cur.close(); c.close()
        h = cli.get(f"/financeiro/despesas/editar/{did}?academia_id={ACADEMIA}",
                    follow_redirects=True).get_data(as_text=True)
        checar("11. editar não oferece repetição", 'name="recorrente"' not in h)
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
