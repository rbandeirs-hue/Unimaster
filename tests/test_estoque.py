"""Regras do estoque: saldo, concorrência, isolamento, estorno e transferência.

O que estes testes protegem
---------------------------
O saldo é guardado em duas formas — a linha de `estoque_saldo` e a soma do
histórico. Redundância só vale a pena se alguém conferir, e é o cenário 12 que
confere. O cenário 10 abre DUAS conexões de verdade e prova que a trava
funciona: sem ela, duas saídas simultâneas furam o estoque em silêncio.

Rodam contra o banco real, numa academia de id negativo criada e apagada a
cada execução. Nenhum dado de produção é tocado.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_estoque.py
"""
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection          # noqa: E402
from utils import estoque as est              # noqa: E402

ACADEMIA = -9980
OUTRA = -9979
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
    cur.execute("""DELETE m FROM estoque_movimento m
                   WHERE m.id_academia IN (%s, %s)""", (ACADEMIA, OUTRA))
    cur.execute("""DELETE s FROM estoque_saldo s
                   JOIN estoque_local l ON l.id = s.local_id
                   WHERE l.id_academia IN (%s, %s)""", (ACADEMIA, OUTRA))
    cur.execute("""DELETE p FROM estoque_preco p
                   JOIN estoque_tabela_preco t ON t.id = p.tabela_id
                   WHERE t.id_academia IN (%s, %s)""", (ACADEMIA, OUTRA))
    cur.execute("DELETE FROM estoque_tabela_preco WHERE id_academia IN (%s, %s)",
                (ACADEMIA, OUTRA))
    cur.execute("""DELETE v FROM estoque_variacao v
                   JOIN estoque_produto p ON p.id = v.produto_id
                   WHERE p.id_academia IN (%s, %s)""", (ACADEMIA, OUTRA))
    cur.execute("DELETE FROM estoque_produto WHERE id_academia IN (%s, %s)",
                (ACADEMIA, OUTRA))
    cur.execute("DELETE FROM estoque_local WHERE id_academia IN (%s, %s)",
                (ACADEMIA, OUTRA))
    cur.execute("DELETE FROM alunos WHERE id_academia IN (%s, %s)", (ACADEMIA, OUTRA))
    cur.execute("DELETE FROM academias WHERE id IN (%s, %s)", (ACADEMIA, OUTRA))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    for aid, nome in ((ACADEMIA, "ZZ Estoque Teste"), (OUTRA, "ZZ Estoque Vizinha")):
        cur.execute("INSERT INTO academias (id, nome) VALUES (%s, %s)", (aid, nome))
    cur.execute("""INSERT INTO estoque_local (id_academia, nome, padrao)
                   VALUES (%s, 'Depósito', 1)""", (ACADEMIA,))
    ids["local"] = cur.lastrowid
    cur.execute("""INSERT INTO estoque_local (id_academia, nome)
                   VALUES (%s, 'Recepção')""", (ACADEMIA,))
    ids["local2"] = cur.lastrowid
    cur.execute("""INSERT INTO estoque_local (id_academia, nome)
                   VALUES (%s, 'Depósito da vizinha')""", (OUTRA,))
    ids["local_outra"] = cur.lastrowid
    cur.execute("""INSERT INTO alunos (id_academia, nome, ativo)
                   VALUES (%s, 'ZZ Aluno Estoque', 1)""", (ACADEMIA,))
    ids["aluno"] = cur.lastrowid
    c.commit(); cur.close(); c.close()

    ids["produto"] = est.criar_produto(
        nome="ZZ Kimono", id_academia=ACADEMIA, custo=90, estoque_min=3,
        variacoes=[{"nome": "A2", "tamanho": "A2"}, {"nome": "A3", "tamanho": "A3"}])
    ids["simples"] = est.criar_produto(
        nome="ZZ Garrafa", id_academia=ACADEMIA, custo=10, estoque_min=2)

    c, cur = _conn()
    cur.execute("SELECT id, nome FROM estoque_variacao WHERE produto_id = %s ORDER BY id",
                (ids["produto"],))
    linhas = cur.fetchall()
    ids["a2"], ids["a3"] = linhas[0]["id"], linhas[1]["id"]
    cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s",
                (ids["simples"],))
    ids["unico"] = cur.fetchone()["id"]

    for nome, perfil, padrao in (("Aluno", "aluno", 1), ("Professor", "professor", 0)):
        cur.execute("""INSERT INTO estoque_tabela_preco
                       (id_academia, nome, perfil, padrao) VALUES (%s,%s,%s,%s)""",
                    (ACADEMIA, nome, perfil, padrao))
        ids["tab_" + perfil] = cur.lastrowid
    cur.execute("INSERT INTO estoque_preco (tabela_id, variacao_id, preco) VALUES (%s,%s,%s)",
                (ids["tab_aluno"], ids["a2"], 220))
    cur.execute("INSERT INTO estoque_preco (tabela_id, variacao_id, preco) VALUES (%s,%s,%s)",
                (ids["tab_professor"], ids["a2"], 160))
    c.commit(); cur.close(); c.close()


def main():
    limpar()
    montar()
    try:
        print("\nCatálogo\n")

        c, cur = _conn()
        cur.execute("SELECT COUNT(*) AS n FROM estoque_variacao WHERE produto_id = %s",
                    (ids["simples"],))
        n_unico = cur.fetchone()["n"]
        cur.close(); c.close()
        checar("1. produto sem variação ganha a variação 'Único'", n_unico == 1, str(n_unico))

        try:
            est.criar_produto(nome="ZZ Sem dono")
            checar("2. produto precisa de dono", False, "aceitou sem academia nem associação")
        except est.EstoqueErro:
            checar("2. produto precisa de dono", True)

        print("\nTabelas de preço\n")

        checar("3. preço do aluno vem da tabela do aluno",
               float(est.preco_de(ids["a2"], ids["tab_aluno"])) == 220.0)
        checar("4. o mesmo item tem outro preço para o professor",
               float(est.preco_de(ids["a2"], ids["tab_professor"])) == 160.0)
        checar("5. sem preço cadastrado, devolve None em vez de inventar",
               est.preco_de(ids["a3"], ids["tab_aluno"]) is None)
        checar("6. a tabela padrão responde quando não se escolhe",
               float(est.preco_de(ids["a2"], id_academia=ACADEMIA)) == 220.0)
        checar("7. as duas tabelas aparecem para a academia",
               len(est.tabelas_de_preco(id_academia=ACADEMIA)) == 2)

        print("\nEntrada e saída\n")

        est.entrada(variacao_id=ids["a2"], local_id=ids["local"], quantidade=10,
                    motivo="compra", custo_unitario=90)
        checar("8. entrada soma no saldo", est.saldo_de(ids["a2"], ids["local"]) == 10)

        est.saida(variacao_id=ids["a2"], local_id=ids["local"], quantidade=3,
                  motivo="venda", aluno_id=ids["aluno"], preco_unitario=220,
                  tabela_preco_id=ids["tab_aluno"])
        checar("9. venda subtrai do saldo", est.saldo_de(ids["a2"], ids["local"]) == 7)

        try:
            est.saida(variacao_id=ids["a2"], local_id=ids["local"], quantidade=99,
                      motivo="venda")
            checar("10. saída maior que o saldo é recusada", False, "passou")
        except est.EstoqueErro as e:
            checar("10. saída maior que o saldo é recusada", "insuficiente" in str(e).lower())

        mov = est.saida(variacao_id=ids["a2"], local_id=ids["local"], quantidade=99,
                        motivo="perda", autorizar_negativo=True)
        checar("11. com autorização explícita, passa e fica negativo",
               est.saldo_de(ids["a2"], ids["local"]) == -92)
        est.estornar(mov)
        checar("12. estorno devolve o saldo", est.saldo_de(ids["a2"], ids["local"]) == 7)

        c, cur = _conn()
        cur.execute("""SELECT COUNT(*) AS n FROM estoque_movimento
                       WHERE estorna_movimento_id = %s""", (mov,))
        tem_estorno = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM estoque_movimento WHERE id = %s", (mov,))
        original_vivo = cur.fetchone()["n"]
        cur.close(); c.close()
        checar("13. o estorno é movimento novo, e o original continua lá",
               tem_estorno == 1 and original_vivo == 1)

        try:
            est.estornar(mov)
            checar("14. não dá para estornar duas vezes", False, "passou")
        except est.EstoqueErro:
            checar("14. não dá para estornar duas vezes", True)

        print("\nQuantidade inválida\n")

        for q, rot in ((0, "zero"), (-5, "negativa"), ("abc", "não numérica")):
            try:
                est.entrada(variacao_id=ids["a2"], local_id=ids["local"], quantidade=q)
                checar(f"15/{rot}. quantidade {rot} é recusada", False, "passou")
            except est.EstoqueErro:
                checar(f"15/{rot}. quantidade {rot} é recusada", True)

        print("\nIsolamento entre academias\n")

        try:
            est.entrada(variacao_id=ids["a2"], local_id=ids["local_outra"], quantidade=1)
            checar("16. produto não entra no depósito de outra academia", False, "passou")
        except est.EstoqueErro as e:
            checar("16. produto não entra no depósito de outra academia",
                   "não pertence" in str(e).lower(), str(e))

        print("\nTransferência\n")

        est.transferir(variacao_id=ids["a2"], origem_local_id=ids["local"],
                       destino_local_id=ids["local2"], quantidade=4)
        checar("17. transferência tira da origem", est.saldo_de(ids["a2"], ids["local"]) == 3)
        checar("18. e põe no destino", est.saldo_de(ids["a2"], ids["local2"]) == 4)
        checar("19. o total não muda", est.saldo_de(ids["a2"]) == 7)

        c, cur = _conn()
        cur.execute("""SELECT id, movimento_par_id FROM estoque_movimento
                       WHERE motivo LIKE 'transferencia%' ORDER BY id DESC LIMIT 2""")
        pares = cur.fetchall()
        cur.close(); c.close()
        checar("20. os dois lados ficam ligados",
               all(p["movimento_par_id"] for p in pares) and len(pares) == 2)

        try:
            est.transferir(variacao_id=ids["a2"], origem_local_id=ids["local"],
                           destino_local_id=ids["local"], quantidade=1)
            checar("21. transferir para o mesmo local é recusado", False, "passou")
        except est.EstoqueErro:
            checar("21. transferir para o mesmo local é recusado", True)

        print("\nConcorrência (duas conexões de verdade)\n")

        est.entrada(variacao_id=ids["unico"], local_id=ids["local"], quantidade=10)
        resultados = []

        def vender():
            try:
                est.saida(variacao_id=ids["unico"], local_id=ids["local"],
                          quantidade=6, motivo="venda")
                resultados.append("ok")
            except est.EstoqueErro:
                resultados.append("recusada")
            except Exception as e:
                resultados.append("erro:" + str(e)[:40])

        t1, t2 = threading.Thread(target=vender), threading.Thread(target=vender)
        t1.start(); t2.start(); t1.join(); t2.join()
        saldo_final = est.saldo_de(ids["unico"], ids["local"])
        checar("22. duas saídas de 6 sobre saldo 10: uma passa, uma é recusada",
               sorted(resultados) == ["ok", "recusada"], str(resultados))
        checar("23. e o saldo não fura", saldo_final == 4, str(saldo_final))

        print("\nHistórico bate com o saldo\n")

        divergencias = est.conferir_saldos(ACADEMIA)
        checar("24. saldo e histórico contam a mesma coisa",
               not divergencias, str(divergencias))

        print("\nPainel\n")

        p = est.panorama(id_academia=ACADEMIA)
        checar("25. conta os produtos ativos", p["produtos"] == 2, str(p["produtos"]))
        checar("26. soma os itens em estoque", p["itens"] == 11, str(p["itens"]))
        # O A3 nunca teve entrada. Se o alerta somasse o produto inteiro, os 7
        # kimonos A2 o esconderiam — e é exatamente o tamanho que falta comprar.
        zerados = {x["variacao_id"] for x in p["sem_estoque"]}
        checar("27. o tamanho esgotado aparece mesmo com o produto tendo saldo",
               ids["a3"] in zerados,
               f"zerados={[(x['produto'], x['variacao']) for x in p['sem_estoque']]}")
        checar("27b. e o tamanho que tem saldo não é acusado",
               ids["a2"] not in zerados)
        checar("28. o valor do estoque usa o custo",
               float(p["valor"]) > 0, str(p["valor"]))

        h = est.movimentos(id_academia=ACADEMIA, limite=5)
        checar("29. o histórico traz produto, local e usuário",
               h and "produto" in h[0] and "local" in h[0])
        checar("30. venda ao aluno guarda o aluno",
               any(m["aluno_id"] == ids["aluno"] for m in
                   est.movimentos(id_academia=ACADEMIA, limite=100)))
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
