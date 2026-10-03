"""A tela de categorias do administrador faz o que mostra.

Dois defeitos motivaram estes testes, os dois de "o botão existe e não faz
nada": o modal "Nova categoria" postava para uma rota que não tratava o
formulário, e a coluna Situação mostrava "N/A" porque a consulta não trazia
`ativo` — o botão Ativar/Desativar mudava a tela e nada era gravado.

Rodam contra o banco real. A categoria de teste é criada e apagada aqui; as
290 categorias de produção são lidas, e o lote é devolvido ao estado original
ao final.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_categorias_admin.py
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

NOME_TESTE = "ZZ CATEGORIA DE TESTE"
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
    cur.execute("DELETE FROM categorias WHERE nome_categoria = %s", (NOME_TESTE,))
    c.commit(); cur.close(); c.close()


def _buscar(nome):
    c, cur = _conn()
    cur.execute("SELECT * FROM categorias WHERE nome_categoria = %s", (nome,))
    linha = cur.fetchone()
    cur.close(); c.close()
    return linha


def _cliente():
    cli = app.test_client()
    with cli.session_transaction() as sess:
        sess["_user_id"] = str(USUARIO_POR_MODO["admin"])
        sess["_fresh"] = True
        sess["modo_painel"] = "admin"
    return cli


def main():
    limpar()
    cli = _cliente()
    html = cli.get("/cadastros/categorias", follow_redirects=True).get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    try:
        print("\nA tela\n")
        checar("1. abre e lista as categorias",
               html.count('class="lst-linha lin-cat lst-item') > 100,
               str(html.count('class="lst-linha lin-cat lst-item')))
        checar("2. a coluna Situação não diz mais 'N/A'", "N/A" not in html)

        print("\nCadastrar nova categoria\n")

        resp = cli.post("/cadastros/categorias", data={
            "csrf_token": token, "form_tipo": "nova_categoria",
            "genero": "FEMININO", "id_classe": "ZZ", "categoria": "TESTE",
            "nome_categoria": NOME_TESTE, "peso_min": "10,5", "peso_max": "20",
            "idade_min": "7", "idade_max": "9", "descricao": "criada pelo teste",
            "ativo": "1",
        }, follow_redirects=True)
        nova = _buscar(NOME_TESTE)
        checar("3. o modal grava de verdade", nova is not None, str(resp.status_code))
        if nova:
            checar("4. com os valores enviados",
                   nova["genero"] == "FEMININO" and float(nova["peso_min"]) == 10.5
                   and nova["idade_max"] == 9,
                   str(dict(nova)))
            checar("5. e nasce ativa", nova["ativo"] == 1, str(nova["ativo"]))

        print("\nCampos obrigatórios\n")

        cli.post("/cadastros/categorias", data={
            "csrf_token": token, "form_tipo": "nova_categoria",
            "genero": "", "nome_categoria": "",
        }, follow_redirects=True)
        c, cur = _conn()
        cur.execute("SELECT COUNT(*) AS n FROM categorias WHERE nome_categoria = ''")
        vazias = cur.fetchone()["n"]
        cur.close(); c.close()
        checar("6. sem gênero e nome, não grava lixo", vazias == 0, str(vazias))

        print("\nEditar em lote e a situação\n")

        c, cur = _conn()
        cur.execute("""SELECT id, genero, id_classe, categoria, nome_categoria,
                              peso_min, peso_max, idade_min, idade_max, descricao, ativo
                       FROM categorias ORDER BY id""")
        todas = cur.fetchall()
        cur.close(); c.close()

        alvo = next(t for t in todas if t["nome_categoria"] == NOME_TESTE)

        def _lote(mudar_ativo_de=None, novo_nome=None):
            dados = {"csrf_token": token, "form_tipo": "categorias",
                     "id": [], "genero": [], "id_classe": [], "categoria": [],
                     "nome_categoria": [], "peso_min": [], "peso_max": [],
                     "idade_min": [], "idade_max": [], "descricao": [], "ativo": []}
            for t in todas:
                dados["id"].append(str(t["id"]))
                dados["genero"].append(t["genero"] or "")
                dados["id_classe"].append(t["id_classe"] or "")
                dados["categoria"].append(t["categoria"] or "")
                nome = t["nome_categoria"] or ""
                if novo_nome and t["id"] == alvo["id"]:
                    nome = novo_nome
                dados["nome_categoria"].append(nome)
                dados["peso_min"].append("" if t["peso_min"] is None else str(t["peso_min"]))
                dados["peso_max"].append("" if t["peso_max"] is None else str(t["peso_max"]))
                dados["idade_min"].append("" if t["idade_min"] is None else str(t["idade_min"]))
                dados["idade_max"].append("" if t["idade_max"] is None else str(t["idade_max"]))
                dados["descricao"].append(t["descricao"] or "")
                ativo = t["ativo"]
                if mudar_ativo_de is not None and t["id"] == alvo["id"]:
                    ativo = mudar_ativo_de
                dados["ativo"].append("1" if ativo else "0")
            return dados

        cli.post("/cadastros/categorias", data=_lote(mudar_ativo_de=0),
                 follow_redirects=True)
        depois = _buscar(NOME_TESTE)
        checar("7. desativar pela tela sobrevive ao recarregar",
               depois and depois["ativo"] == 0, str(depois and depois["ativo"]))

        cli.post("/cadastros/categorias",
                 data=_lote(mudar_ativo_de=1, novo_nome=NOME_TESTE + " EDITADA"),
                 follow_redirects=True)
        editada = _buscar(NOME_TESTE + " EDITADA")
        checar("8. e a edição do texto grava junto",
               editada is not None and editada["ativo"] == 1,
               str(editada and dict(editada)))

        print("\nNada mais foi tocado\n")

        c, cur = _conn()
        cur.execute("""SELECT id, genero, id_classe, categoria, nome_categoria,
                              peso_min, peso_max, idade_min, idade_max, descricao, ativo
                       FROM categorias WHERE nome_categoria NOT LIKE 'ZZ %' ORDER BY id""")
        agora = cur.fetchall()
        cur.close(); c.close()
        originais = [t for t in todas if not (t["nome_categoria"] or "").startswith("ZZ ")]
        checar("9. as demais categorias seguem idênticas",
               [dict(x) for x in agora] == [dict(x) for x in originais],
               f"{len(agora)} x {len(originais)}")
    finally:
        c, cur = _conn()
        cur.execute("DELETE FROM categorias WHERE nome_categoria LIKE %s", (NOME_TESTE + "%",))
        c.commit(); cur.close(); c.close()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
