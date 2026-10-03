"""Catálogo e carrinho da loja.

O carrinho vive na sessão, não no banco. A alternativa — um pedido em
rascunho — faria todo carrinho abandonado aparecer para a recepção como pedido
a atender. Estes testes fixam as consequências dessa escolha: o carrinho não
reserva nada, se ajusta sozinho quando o saldo muda, e só vira pedido no
fechamento.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_estoque_carrinho.py
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

ACADEMIA = -9940
EMAIL = "zz.carrinho@teste.local"
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
    cur.execute("""DELETE i FROM estoque_pedido_item i JOIN estoque_pedido p
                   ON p.id = i.pedido_id WHERE p.id_academia = %s""", (ACADEMIA,))
    cur.execute("DELETE FROM estoque_pedido WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("""DELETE m FROM estoque_movimento m JOIN estoque_local l
                   ON l.id = m.local_id WHERE l.id_academia = %s""", (ACADEMIA,))
    cur.execute("""DELETE s FROM estoque_saldo s JOIN estoque_local l
                   ON l.id = s.local_id WHERE l.id_academia = %s""", (ACADEMIA,))
    cur.execute("""DELETE pr FROM estoque_preco pr JOIN estoque_tabela_preco t
                   ON t.id = pr.tabela_id WHERE t.id_academia = %s""", (ACADEMIA,))
    cur.execute("DELETE FROM estoque_tabela_preco WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("""DELETE v FROM estoque_variacao v JOIN estoque_produto p
                   ON p.id = v.produto_id WHERE p.id_academia = %s""", (ACADEMIA,))
    cur.execute("DELETE FROM estoque_produto WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM estoque_categoria WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM estoque_local WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM receitas WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    cur.execute("""DELETE ru FROM roles_usuario ru JOIN usuarios u
                   ON u.id = ru.usuario_id WHERE u.email = %s""", (EMAIL,))
    cur.execute("DELETE FROM usuarios WHERE email = %s", (EMAIL,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Loja Carrinho')",
                (ACADEMIA,))
    cur.execute("UPDATE academias SET modulo_estoque = 1 WHERE id = %s", (ACADEMIA,))
    cur.execute("INSERT INTO estoque_local (id_academia, nome, padrao) "
                "VALUES (%s,'Loja',1)", (ACADEMIA,))
    ids["local"] = cur.lastrowid
    cur.execute("INSERT INTO estoque_categoria (id_academia, nome) "
                "VALUES (%s,'ZZ Vestuário')", (ACADEMIA,))
    ids["categoria"] = cur.lastrowid

    cur.execute("""INSERT INTO usuarios (nome, email, senha, perfil, ativo, cpf)
                   VALUES ('ZZ Comprador', %s, 'x', 'aluno', 1, '00000000272')""",
                (EMAIL,))
    ids["usuario"] = cur.lastrowid
    cur.execute("INSERT INTO roles_usuario (usuario_id, role_id) "
                "SELECT %s, id FROM roles WHERE chave='aluno'", (ids["usuario"],))
    cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, usuario_id)
                   VALUES (%s,'ZZ Comprador',1,%s)""", (ACADEMIA, ids["usuario"]))
    ids["aluno"] = cur.lastrowid

    from blueprints.aluno.alunos import (CAMPOS_AUTOPREENCHIVEIS_ALUNO,
                                         COLUNA_DO_CAMPO_ALUNO)
    JA = {"nome", "id_academia", "ativo", "usuario_id"}
    for campo, _r in CAMPOS_AUTOPREENCHIVEIS_ALUNO:
        col = COLUNA_DO_CAMPO_ALUNO.get(campo, campo)
        if col in JA:
            continue
        cur.execute(f"SHOW COLUMNS FROM alunos LIKE '{col}'")
        info = cur.fetchone()
        if not info:
            continue
        tipo = (info["Type"] or "").lower()
        if tipo.startswith("enum"):
            valor = tipo[5:-1].split(",")[0].strip().strip("'")
        elif "date" in tipo:
            valor = "2000-01-01"
        elif "int" in tipo or "decimal" in tipo:
            valor = 1
        else:
            m = re.search(r"\((\d+)\)", tipo)
            lim = int(m.group(1)) if m else 40
            valor = "ok"[:lim] if lim >= 2 else "X"
        cur.execute(f"UPDATE alunos SET `{col}` = %s WHERE id = %s", (valor, ids["aluno"]))

    cur.execute("""INSERT INTO estoque_tabela_preco (id_academia, nome, perfil, padrao)
                   VALUES (%s,'Aluno','aluno',1)""", (ACADEMIA,))
    ids["tabela"] = cur.lastrowid
    c.commit(); cur.close(); c.close()

    ids["kimono"] = est.criar_produto(
        nome="ZZ Kimono Loja", id_academia=ACADEMIA, custo=90,
        categoria_id=ids["categoria"], descricao="Kimono para treino",
        variacoes=[{"nome": "A2"}, {"nome": "A3"}])
    ids["faixa"] = est.criar_produto(nome="ZZ Faixa Loja", id_academia=ACADEMIA, custo=20)
    ids["sem_preco"] = est.criar_produto(nome="ZZ Sem Preco", id_academia=ACADEMIA)

    c, cur = _conn()
    cur.execute("SELECT v.id, v.nome FROM estoque_variacao v "
                "WHERE v.produto_id = %s ORDER BY v.nome", (ids["kimono"],))
    linhas = cur.fetchall()
    ids["a2"], ids["a3"] = linhas[0]["id"], linhas[1]["id"]
    cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s", (ids["faixa"],))
    ids["faixa_v"] = cur.fetchone()["id"]
    cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s",
                (ids["sem_preco"],))
    ids["sem_preco_v"] = cur.fetchone()["id"]
    for v, preco in ((ids["a2"], 220), (ids["a3"], 240), (ids["faixa_v"], 45)):
        cur.execute("INSERT INTO estoque_preco (tabela_id, variacao_id, preco) "
                    "VALUES (%s,%s,%s)", (ids["tabela"], v, preco))
    c.commit(); cur.close(); c.close()

    est.entrada(variacao_id=ids["a2"], local_id=ids["local"], quantidade=3)
    est.entrada(variacao_id=ids["a3"], local_id=ids["local"], quantidade=1)
    est.entrada(variacao_id=ids["faixa_v"], local_id=ids["local"], quantidade=10)
    est.entrada(variacao_id=ids["sem_preco_v"], local_id=ids["local"], quantidade=5)


def _cliente():
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(ids["usuario"])
        s["_fresh"] = True
        s["modo_painel"] = "aluno"
    return cli


def _token(cli, url="/estoque/loja"):
    h = cli.get(url, follow_redirects=True).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', h).group(1), h


def main():
    limpar()
    montar()
    try:
        cli = _cliente()
        tok, h = _token(cli)

        print("\nCatálogo\n")

        checar("1. a loja abre", "Loja" in h)
        checar("2. o kimono aparece como UM cartão, não um por tamanho",
               h.count('class="cat-card__nome"') == 2,
               str(h.count('class="cat-card__nome"')))
        checar("3. com as duas variações dentro",
               'A2' in h and 'A3' in h)
        checar("4. item sem preço fica fora do catálogo", "ZZ Sem Preco" not in h)
        checar("5. mostra 'a partir de' quando os tamanhos custam diferente",
               "a partir de" in h)

        hb = cli.get("/estoque/loja?busca=faixa", follow_redirects=True).get_data(as_text=True)
        checar("6. a busca filtra",
               "ZZ Faixa Loja" in hb and "ZZ Kimono Loja" not in hb)
        hc = cli.get("/estoque/loja?categoria=ZZ+Vestuário",
                     follow_redirects=True).get_data(as_text=True)
        checar("7. o filtro de categoria funciona",
               "ZZ Kimono Loja" in hc and "ZZ Faixa Loja" not in hc)

        print("\nCarrinho\n")

        cli.post(f"/estoque/carrinho/{ids['a2']}",
                 data={"csrf_token": tok, "quantidade": 2}, follow_redirects=True)
        h = cli.get("/estoque/carrinho", follow_redirects=True).get_data(as_text=True)
        checar("8. o item entra no carrinho", "ZZ Kimono Loja" in h)
        checar("9. com o total certo (2 × 220)", "440,00" in h, "esperado 440,00")

        cli.post(f"/estoque/carrinho/{ids['faixa_v']}",
                 data={"csrf_token": tok, "quantidade": 1}, follow_redirects=True)
        h = cli.get("/estoque/carrinho", follow_redirects=True).get_data(as_text=True)
        checar("10. soma o segundo item", "485,00" in h, "esperado 485,00")

        # Pedir 99 de um item com saldo 3: o carrinho corta no disponível.
        cli.post(f"/estoque/carrinho/{ids['a2']}",
                 data={"csrf_token": tok, "quantidade": 99}, follow_redirects=True)
        h = cli.get("/estoque/carrinho", follow_redirects=True).get_data(as_text=True)
        checar("11. o carrinho não deixa pedir mais do que existe",
               'value="3"' in h, "esperado quantidade 3")

        cli.post("/estoque/carrinho", data={"csrf_token": tok, "acao": "atualizar",
                                            f"qtd_{ids['a2']}": "1",
                                            f"qtd_{ids['faixa_v']}": "0"},
                 follow_redirects=True)
        h = cli.get("/estoque/carrinho", follow_redirects=True).get_data(as_text=True)
        checar("12. atualizar muda a quantidade e zero remove",
               "220,00" in h and "ZZ Faixa Loja" not in h)

        print("\nO carrinho não reserva\n")

        checar("13. o estoque segue intacto com o carrinho cheio",
               est.saldo_de(ids["a2"], ids["local"]) == 3,
               str(est.saldo_de(ids["a2"], ids["local"])))

        # Alguém levou o estoque enquanto o carrinho esperava.
        est.saida(variacao_id=ids["a2"], local_id=ids["local"], quantidade=3,
                  motivo="venda")
        h = cli.get("/estoque/carrinho", follow_redirects=True).get_data(as_text=True)
        checar("14. item que esgotou sai do carrinho com aviso",
               "carrinho" in h.lower()
               and ("saiu do catálogo" in h or "vazio" in h.lower()), "")
        est.entrada(variacao_id=ids["a2"], local_id=ids["local"], quantidade=3)

        print("\nFechamento\n")

        cli.post(f"/estoque/carrinho/{ids['a2']}",
                 data={"csrf_token": tok, "quantidade": 2}, follow_redirects=True)
        saldo_antes = est.saldo_de(ids["a2"], ids["local"])
        cli.post("/estoque/carrinho",
                 data={"csrf_token": tok, "acao": "fechar",
                       "observacao": "retiro na terça"}, follow_redirects=True)

        c, cur = _conn()
        cur.execute("""SELECT * FROM estoque_pedido WHERE id_academia = %s
                       ORDER BY id DESC LIMIT 1""", (ACADEMIA,))
        ped = cur.fetchone()
        cur.close(); c.close()
        checar("15. o carrinho vira pedido aguardando a recepção",
               ped and ped["status"] == "aguardando_pagamento", str(ped and ped["status"]))
        checar("16. com a observação do comprador",
               ped and ped["observacao"] == "retiro na terça")
        checar("17. e o estoque ainda NÃO baixou",
               est.saldo_de(ids["a2"], ids["local"]) == saldo_antes)

        h = cli.get("/estoque/carrinho", follow_redirects=True).get_data(as_text=True)
        checar("18. o carrinho é esvaziado depois de enviar",
               "vazio" in h.lower())

        print("\nA recepção não vê carrinho, só pedido\n")

        gestor = app.test_client()
        with gestor.session_transaction() as s:
            s["_user_id"] = str(USUARIO_POR_MODO["admin"])
            s["_fresh"] = True
            s["modo_painel"] = "academia"
            s["academia_gerenciamento_id"] = ACADEMIA
        h = gestor.get("/estoque/pedidos", follow_redirects=True).get_data(as_text=True)
        checar("19. o pedido enviado aparece", "ZZ Comprador" in h)

        c, cur = _conn()
        cur.execute("""INSERT INTO estoque_pedido (id_academia, local_id,
                          comprador_tipo, status, origem)
                       VALUES (%s,%s,'avulso','aberto','balcao')""",
                    (ACADEMIA, ids["local"]))
        rascunho = cur.lastrowid
        c.commit(); cur.close(); c.close()
        h = gestor.get("/estoque/pedidos", follow_redirects=True).get_data(as_text=True)
        checar("20. pedido em rascunho NÃO aparece para a recepção",
               h.count('/confirmar') == 1, str(h.count('/confirmar')))

        print("\nConferência final\n")
        checar("21. saldo e histórico batem", not est.conferir_saldos(ACADEMIA),
               str(est.conferir_saldos(ACADEMIA)))
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
