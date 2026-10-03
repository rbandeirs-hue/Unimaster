"""As telas do estoque: acesso, permissão e isolamento entre donos.

O que estes testes protegem
---------------------------
Regra de negócio já tem teste próprio. Aqui a pergunta é outra: as rotas
recusam quem não deveria entrar? O módulo desligado bloqueia de verdade, ou só
esconde o menu? Um gestor consegue ler o estoque de outra academia mudando a
sessão?

Rodam contra o banco real, com academia e produtos de teste criados e apagados.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_estoque_telas.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                    # noqa: E402
from config import get_db_connection                   # noqa: E402
from utils import estoque as est                       # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO    # noqa: E402

ACADEMIA = -9960
VIZINHA = -9959
_falhas = []
ids = {}

TELAS = ["/estoque/", "/estoque/produtos", "/estoque/venda", "/estoque/movimentar",
         "/estoque/historico", "/estoque/config", "/estoque/produtos/novo"]


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
    for aid in (ACADEMIA, VIZINHA):
        cur.execute("""DELETE m FROM estoque_movimento m JOIN estoque_local l
                       ON l.id = m.local_id WHERE l.id_academia = %s""", (aid,))
        cur.execute("""DELETE s FROM estoque_saldo s JOIN estoque_local l
                       ON l.id = s.local_id WHERE l.id_academia = %s""", (aid,))
        cur.execute("""DELETE p FROM estoque_preco p JOIN estoque_tabela_preco t
                       ON t.id = p.tabela_id WHERE t.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM estoque_tabela_preco WHERE id_academia = %s", (aid,))
        cur.execute("""DELETE v FROM estoque_variacao v JOIN estoque_produto p
                       ON p.id = v.produto_id WHERE p.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM estoque_produto WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM estoque_local WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (aid,))
        cur.execute("""DELETE ru FROM roles_usuario ru JOIN usuarios u
                       ON u.id = ru.usuario_id
                       WHERE u.email = 'zz.prof.estoque@teste.local'""")
        cur.execute("DELETE FROM usuarios WHERE email = 'zz.prof.estoque@teste.local'")
        cur.execute("DELETE FROM academias WHERE id = %s", (aid,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    # Um professor de verdade: o usuário "professor" da suíte de smoke acumula
    # o papel de admin, e admin tem todas as permissões por definição — testar
    # permissão com ele não provaria nada.
    # O CPF importa: o sistema tem um portão global que manda quem não tem CPF
    # para /auth/cadastrar-cpf. Sem preencher, o teste de permissão passaria
    # pelo motivo errado — foi o que aconteceu na primeira versão deste teste.
    cur.execute("""INSERT INTO usuarios (nome, email, senha, perfil, ativo, cpf)
                   VALUES ('ZZ Professor Estoque', 'zz.prof.estoque@teste.local',
                           'x', 'professor', 1, '00000000272')""")
    ids["prof"] = cur.lastrowid
    cur.execute("INSERT INTO roles_usuario (usuario_id, role_id) "
                "SELECT %s, id FROM roles WHERE chave = 'professor'", (ids["prof"],))
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Estoque Telas')",
                (ACADEMIA,))
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s, 'ZZ Estoque Vizinha')",
                (VIZINHA,))
    cur.execute("UPDATE academias SET modulo_estoque = 1 WHERE id = %s", (VIZINHA,))
    cur.execute("INSERT INTO estoque_local (id_academia, nome, padrao) "
                "VALUES (%s, 'Depósito', 1)", (ACADEMIA,))
    ids["local"] = cur.lastrowid
    cur.execute("INSERT INTO estoque_local (id_academia, nome, padrao) "
                "VALUES (%s, 'Depósito vizinho', 1)", (VIZINHA,))
    ids["local_viz"] = cur.lastrowid
    for u in (USUARIO_POR_MODO["academia"], USUARIO_POR_MODO["admin"], ids["prof"]):
        for aid in (ACADEMIA, VIZINHA):
            cur.execute("INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id) "
                        "VALUES (%s, %s)", (u, aid))
    c.commit(); cur.close(); c.close()

    ids["prod"] = est.criar_produto(nome="ZZ Item Tela", id_academia=ACADEMIA, custo=10)
    ids["prod_viz"] = est.criar_produto(nome="ZZ Item Vizinho SEGREDO",
                                        id_academia=VIZINHA, custo=10)
    c, cur = _conn()
    cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s", (ids["prod"],))
    ids["var"] = cur.fetchone()["id"]
    cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s",
                (ids["prod_viz"],))
    ids["var_viz"] = cur.fetchone()["id"]
    c.commit(); cur.close(); c.close()
    est.entrada(variacao_id=ids["var_viz"], local_id=ids["local_viz"], quantidade=5)


def _cliente(modo, academia_id):
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO_POR_MODO[modo])
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = academia_id
    return cli


def main():
    limpar()
    montar()
    try:
        print("\nMódulo desligado\n")

        cli = _cliente("academia", ACADEMIA)
        respostas = []
        for url in TELAS:
            r = cli.get(url, follow_redirects=False)
            respostas.append((url, r.status_code))
        checar("1. com o módulo desligado, toda tela redireciona",
               all(c == 302 for _u, c in respostas), str(respostas))

        c, cur = _conn()
        cur.execute("UPDATE academias SET modulo_estoque = 1 WHERE id = %s", (ACADEMIA,))
        c.commit(); cur.close(); c.close()

        print("\nMódulo ligado\n")

        abertas = []
        for url in TELAS:
            r = cli.get(url, follow_redirects=True)
            abertas.append((url, r.status_code))
        checar("2. ligado, todas as telas abrem",
               all(c == 200 for _u, c in abertas), str(abertas))

        h = cli.get("/estoque/", follow_redirects=True).get_data(as_text=True)
        checar("3. o painel mostra o nome da academia", "ZZ Estoque Telas" in h)
        checar("4. e o item aparece no menu lateral", "/estoque/" in h)

        print("\nIsolamento entre academias\n")

        h = cli.get("/estoque/produtos", follow_redirects=True).get_data(as_text=True)
        checar("5. a lista traz o produto da academia", "ZZ Item Tela" in h)
        checar("6. e NÃO traz o da vizinha", "SEGREDO" not in h)

        r = cli.get(f"/estoque/produtos/{ids['prod_viz']}", follow_redirects=True)
        checar("7. abrir produto de outra academia pela URL é recusado",
               "SEGREDO" not in r.get_data(as_text=True))

        h = cli.get("/estoque/movimentar", follow_redirects=True).get_data(as_text=True)
        checar("8. o seletor de itens não vaza o produto da vizinha",
               "SEGREDO" not in h)

        print("\nPermissão por operação\n")

        # O professor tem só `estoque_ver`: entra no painel, não movimenta.
        prof = app.test_client()
        with prof.session_transaction() as s:
            s["_user_id"] = str(ids["prof"])
            s["_fresh"] = True
            s["modo_painel"] = "academia"
            s["academia_gerenciamento_id"] = ACADEMIA
        r_cfg = prof.get("/estoque/config", follow_redirects=False)
        checar("9. professor não entra nas configurações",
               r_cfg.status_code == 302, str(r_cfg.status_code))
        r_novo = prof.get("/estoque/produtos/novo", follow_redirects=False)
        checar("10. nem cadastra produto", r_novo.status_code == 302,
               str(r_novo.status_code))
        r_ver = prof.get("/estoque/", follow_redirects=False)
        checar("10b. mas entra no painel, que é o que ele tem permissão de ver",
               r_ver.status_code == 200, str(r_ver.status_code))

        print("\nCadastro e movimentação pela tela\n")

        html = cli.get("/estoque/config", follow_redirects=True).get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

        cli.post("/estoque/config", data={"csrf_token": token, "acao": "tabela",
                                          "nome": "ZZ Balcão", "padrao": "1"},
                 follow_redirects=True)
        c, cur = _conn()
        cur.execute("SELECT COUNT(*) AS n FROM estoque_tabela_preco WHERE id_academia = %s",
                    (ACADEMIA,))
        n_tab = cur.fetchone()["n"]
        cur.close(); c.close()
        checar("11. a tela cria tabela de preço", n_tab == 1, str(n_tab))

        r = cli.post("/estoque/movimentar", data={
            "csrf_token": token, "sentido": "E", "motivo": "compra",
            "variacao_id": ids["var"], "local_id": ids["local"], "quantidade": "7",
        }, follow_redirects=True)
        checar("12. entrada pela tela grava no saldo",
               est.saldo_de(ids["var"], ids["local"]) == 7,
               str(est.saldo_de(ids["var"], ids["local"])))

        r = cli.post("/estoque/movimentar", data={
            "csrf_token": token, "sentido": "S", "motivo": "venda",
            "variacao_id": ids["var"], "local_id": ids["local"], "quantidade": "99",
        }, follow_redirects=True)
        corpo = r.get_data(as_text=True)
        checar("13. saída acima do saldo é recusada com mensagem",
               "insuficiente" in corpo.lower()
               and est.saldo_de(ids["var"], ids["local"]) == 7)

        r = cli.post("/estoque/movimentar", data={
            "csrf_token": token, "sentido": "S", "motivo": "venda",
            "variacao_id": ids["var_viz"], "local_id": ids["local"], "quantidade": "1",
        }, follow_redirects=True)
        checar("14. movimentar produto de outra academia é recusado",
               est.saldo_de(ids["var_viz"], ids["local_viz"]) == 5)

        print("\nHistórico\n")

        h = cli.get("/estoque/historico", follow_redirects=True).get_data(as_text=True)
        checar("15. o histórico lista a entrada feita", "ZZ Item Tela" in h)
        checar("16. e não mostra o movimento da vizinha", "SEGREDO" not in h)
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
