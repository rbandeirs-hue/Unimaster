"""Liga/desliga de itens do menu por modalidade (MM-09).

A regra em uma frase: sem linha no banco vale o código; com linha, ela manda.
Estes testes cobrem os dois sentidos — desligar o que apareceria e ligar o que
o código esconderia — e o caso que mais dá errado na prática: academia com duas
modalidades, onde só uma desligou o item.

Rodam contra o banco real, com uma modalidade de teste criada e apagada a cada
execução. As regras já configuradas em produção não são tocadas.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_menu_modalidade.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                    # noqa: E402
from config import get_db_connection                   # noqa: E402
from utils import menu_modalidade as regras            # noqa: E402
from utils.menu import menu_do_modo, catalogo          # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO    # noqa: E402

PREFIXO = "ZZ Menu "
_falhas = []
ids = {}


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def limpar():
    c = get_db_connection()
    cur = c.cursor()
    cur.execute("SELECT id FROM modalidade WHERE nome LIKE %s", (PREFIXO + "%",))
    for (mid,) in cur.fetchall() or []:
        cur.execute("DELETE FROM modalidade_menu WHERE modalidade_id = %s", (mid,))
    cur.execute("DELETE FROM modalidade WHERE nome LIKE %s", (PREFIXO + "%",))
    c.commit(); cur.close(); c.close()
    regras.invalidar()


def montar():
    c = get_db_connection()
    cur = c.cursor()
    for chave, nome in (("a", PREFIXO + "Alfa"), ("b", PREFIXO + "Beta")):
        cur.execute("INSERT INTO modalidade (nome, ativo, visibilidade) "
                    "VALUES (%s, 1, 'publica')", (nome,))
        ids[chave] = cur.lastrowid
    c.commit(); cur.close(); c.close()
    regras.invalidar()


def _chaves(modo, modalidade_ids, extra=None):
    ctx = {"academia_id": 1, "menu_modalidade_ids": modalidade_ids,
           "academia_tem_judo": True, "pratica_judo": True}
    ctx.update(extra or {})
    with app.test_request_context("/"):
        return {i.chave for _g, itens in menu_do_modo(modo, ctx) for i in itens}


def main():
    limpar()
    montar()
    try:
        print("\nO padrão, sem nenhuma exceção\n")

        base = _chaves("academia", [ids["a"]])
        checar("1. modalidade nova mostra o menu inteiro",
               {"eventos", "competicoes", "solicitacoes", "turmas"} <= base,
               str(sorted(base)))

        print("\nDesligar\n")

        regras.definir(ids["a"], "academia", "eventos", False)
        regras.definir(ids["a"], "academia", "competicoes", False)
        depois = _chaves("academia", [ids["a"]])
        checar("2. item desligado some do menu",
               "eventos" not in depois and "competicoes" not in depois)
        checar("3. o resto do menu continua intacto",
               "turmas" in depois and "solicitacoes" in depois)

        print("\nAcademia com duas modalidades\n")

        mistas = _chaves("academia", [ids["a"], ids["b"]])
        checar("4. item desligado em uma só não some da academia mista",
               "eventos" in mistas,
               "sumiu — a outra modalidade perderia uma tela que usa")

        regras.definir(ids["b"], "academia", "eventos", False)
        ambas = _chaves("academia", [ids["a"], ids["b"]])
        checar("5. desligado nas duas, some",
               "eventos" not in ambas)

        print("\nLigar o que o código esconde\n")

        sem_judo = {"academia_tem_judo": False}
        escondido = _chaves("academia", [ids["a"]], sem_judo)
        checar("6. sem judô, o código esconde o Zempo",
               "zempo" not in escondido)

        regras.definir(ids["a"], "academia", "zempo", True)
        ligado = _chaves("academia", [ids["a"]], sem_judo)
        checar("7. ligar explicitamente devolve o item escondido pelo código",
               "zempo" in ligado, str(sorted(ligado)))

        print("\nApagar a exceção\n")

        checar("8. antes de apagar, há decisão explícita",
               regras.estado(ids["a"], "academia", "eventos") is False)
        regras.definir(ids["a"], "academia", "eventos", None)
        checar("9. apagada, não sobra decisão",
               regras.estado(ids["a"], "academia", "eventos") is None)
        checar("10. e o item volta ao padrão",
               "eventos" in _chaves("academia", [ids["a"]]))

        print("\nLimites\n")

        checar("11. modo fora da lista não aceita regra",
               regras.definir(ids["a"], "admin", "eventos", False) is False)
        checar("12. e o menu do admin não é filtrado por modalidade",
               "eventos" in _chaves("admin", [ids["a"]]))
        checar("13. sem modalidade em jogo, nada é escondido",
               "eventos" in _chaves("academia", []))

        print("\nA tela do administrador\n")

        checar("14. o catálogo lista item que o código esconderia",
               "zempo" in {i.chave for _g, itens in catalogo("academia") for i in itens})

        cliente = app.test_client()
        with cliente.session_transaction() as sess:
            sess["_user_id"] = str(USUARIO_POR_MODO["admin"])
            sess["_fresh"] = True
            sess["modo_painel"] = "admin"
        resp = cliente.get(f"/configuracoes/menu-modalidade?modalidade_id={ids['a']}",
                           follow_redirects=True)
        html = resp.get_data(as_text=True)
        checar("15. a tela abre", resp.status_code == 200, str(resp.status_code))
        checar("16. traz os quatro modos com modalidade determinável",
               all(f'value="{m}"' in html for m in regras.MODOS))
        checar("17. e um interruptor por item",
               html.count('type="checkbox" name="itens"') >= 40,
               str(html.count('type="checkbox" name="itens"')))
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
