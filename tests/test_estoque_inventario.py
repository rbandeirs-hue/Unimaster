"""Inventário físico e autoatendimento.

O inventário existe para responder "o sistema achava X, na prateleira tem Y".
Se ele apenas sobrescrevesse o saldo, essa resposta se perderia. Por isso cada
diferença vira um movimento de ajuste — e é isso que os cenários 5 a 9 provam.

O autoatendimento tem uma trava diferente das outras telas: quem compra não tem
permissão nenhuma do módulo. O que o protege é o vínculo — só se vê o estoque
da academia do próprio cadastro.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_estoque_inventario.py
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

ACADEMIA = -9950
OUTRA = -9949
EMAIL = "zz.aluno.loja@teste.local"
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
    for aid in (ACADEMIA, OUTRA):
        cur.execute("""DELETE it FROM estoque_inventario_item it
                       JOIN estoque_inventario i ON i.id = it.inventario_id
                       WHERE i.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM estoque_inventario WHERE id_academia = %s", (aid,))
        cur.execute("""DELETE i FROM estoque_pedido_item i JOIN estoque_pedido p
                       ON p.id = i.pedido_id WHERE p.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM estoque_pedido WHERE id_academia = %s", (aid,))
        cur.execute("""DELETE m FROM estoque_movimento m JOIN estoque_local l
                       ON l.id = m.local_id WHERE l.id_academia = %s""", (aid,))
        cur.execute("""DELETE s FROM estoque_saldo s JOIN estoque_local l
                       ON l.id = s.local_id WHERE l.id_academia = %s""", (aid,))
        cur.execute("""DELETE pr FROM estoque_preco pr JOIN estoque_tabela_preco t
                       ON t.id = pr.tabela_id WHERE t.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM estoque_tabela_preco WHERE id_academia = %s", (aid,))
        cur.execute("""DELETE v FROM estoque_variacao v JOIN estoque_produto p
                       ON p.id = v.produto_id WHERE p.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM estoque_produto WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM estoque_local WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM alunos WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM receitas WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (aid,))
        cur.execute("DELETE FROM academias WHERE id = %s", (aid,))
    cur.execute("""DELETE ru FROM roles_usuario ru JOIN usuarios u ON u.id = ru.usuario_id
                   WHERE u.email = %s""", (EMAIL,))
    cur.execute("DELETE FROM usuarios WHERE email = %s", (EMAIL,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    for aid, nome in ((ACADEMIA, "ZZ Inv Academia"), (OUTRA, "ZZ Inv Outra")):
        cur.execute("INSERT INTO academias (id, nome) VALUES (%s,%s)", (aid, nome))
        cur.execute("UPDATE academias SET modulo_estoque = 1 WHERE id = %s", (aid,))
    cur.execute("INSERT INTO estoque_local (id_academia, nome, padrao) "
                "VALUES (%s,'Depósito',1)", (ACADEMIA,))
    ids["local"] = cur.lastrowid
    cur.execute("INSERT INTO estoque_local (id_academia, nome, padrao) "
                "VALUES (%s,'Depósito outra',1)", (OUTRA,))
    ids["local_outra"] = cur.lastrowid

    cur.execute("""INSERT INTO usuarios (nome, email, senha, perfil, ativo, cpf)
                   VALUES ('ZZ Aluno Loja', %s, 'x', 'aluno', 1, '00000000191')""",
                (EMAIL,))
    ids["usuario"] = cur.lastrowid
    cur.execute("INSERT INTO roles_usuario (usuario_id, role_id) "
                "SELECT %s, id FROM roles WHERE chave = 'aluno'", (ids["usuario"],))
    cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, usuario_id)
                   VALUES (%s, 'ZZ Aluno Loja', 1, %s)""", (ACADEMIA, ids["usuario"]))
    ids["aluno"] = cur.lastrowid
    # O sistema tem um portão global: aluno com cadastro incompleto é mandado
    # para /painel_aluno/completar-cadastro antes de qualquer tela. Sem isto o
    # teste da loja mediria o portão, não a loja. A lista de campos vem do
    # próprio sistema — se ela mudar, o teste acompanha.
    from blueprints.aluno.alunos import (CAMPOS_AUTOPREENCHIVEIS_ALUNO,
                                         COLUNA_DO_CAMPO_ALUNO)
    # `nome` está entre os obrigatórios, e preenchê-lo aqui apagaria o nome do
    # aluno de teste — foi o que aconteceu na primeira versão: a tela mostrava
    # "preenchido" no lugar de "ZZ Aluno Loja" e o teste acusou a tela.
    JA_DEFINIDOS = {"nome", "id_academia", "ativo", "usuario_id"}
    for campo, _rotulo in CAMPOS_AUTOPREENCHIVEIS_ALUNO:
        coluna = COLUNA_DO_CAMPO_ALUNO.get(campo, campo)
        if coluna in JA_DEFINIDOS:
            continue
        cur.execute(f"SHOW COLUMNS FROM alunos LIKE '{coluna}'")
        info = cur.fetchone()
        if not info:
            continue
        tipo = (info["Type"] or "").lower()
        if tipo.startswith("enum"):
            # Coluna com domínio fechado (sexo, por exemplo): usa o primeiro
            # valor permitido, em vez de um texto que o banco trunca.
            valor = tipo[5:-1].split(",")[0].strip().strip("'")
        elif "date" in tipo:
            valor = "2000-01-01"
        elif "int" in tipo or "decimal" in tipo:
            valor = 1
        else:
            # Respeita o tamanho declarado: `estado` é varchar(2) e um texto
            # maior estoura. O teste preenche o campo, não testa o conteúdo.
            m = re.search(r"\((\d+)\)", tipo)
            limite = int(m.group(1)) if m else 40
            valor = "preenchido"[:limite] if limite >= 2 else "X"
        cur.execute(f"UPDATE alunos SET `{coluna}` = %s WHERE id = %s",
                    (valor, ids["aluno"]))
    cur.execute("""INSERT INTO estoque_tabela_preco (id_academia, nome, perfil, padrao)
                   VALUES (%s, 'Aluno', 'aluno', 1)""", (ACADEMIA,))
    ids["tabela"] = cur.lastrowid
    c.commit(); cur.close(); c.close()

    ids["prod"] = est.criar_produto(nome="ZZ Camiseta", id_academia=ACADEMIA, custo=20,
                                    variacoes=[{"nome": "M"}, {"nome": "G"}])
    ids["prod_outra"] = est.criar_produto(nome="ZZ Produto SEGREDO",
                                          id_academia=OUTRA, custo=5)
    c, cur = _conn()
    cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s ORDER BY nome",
                (ids["prod"],))
    linhas = cur.fetchall()
    ids["g"], ids["m"] = linhas[0]["id"], linhas[1]["id"]
    cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s",
                (ids["prod_outra"],))
    ids["var_outra"] = cur.fetchone()["id"]
    for v in (ids["m"], ids["g"]):
        cur.execute("INSERT INTO estoque_preco (tabela_id, variacao_id, preco) "
                    "VALUES (%s,%s,60)", (ids["tabela"], v))
    c.commit(); cur.close(); c.close()

    est.entrada(variacao_id=ids["m"], local_id=ids["local"], quantidade=10)
    est.entrada(variacao_id=ids["g"], local_id=ids["local"], quantidade=4)
    est.entrada(variacao_id=ids["var_outra"], local_id=ids["local_outra"], quantidade=3)


def main():
    limpar()
    montar()
    try:
        print("\nAbertura do inventário\n")

        inv_id = est.abrir_inventario(local_id=ids["local"])
        inv = est.inventario(inv_id)
        checar("1. entram todas as variações do dono", len(inv["itens"]) == 2,
               str(len(inv["itens"])))
        por_var = {i["variacao_id"]: i for i in inv["itens"]}
        checar("2. o saldo do sistema é congelado na abertura",
               por_var[ids["m"]]["qtd_sistema"] == 10
               and por_var[ids["g"]]["qtd_sistema"] == 4)

        try:
            est.abrir_inventario(local_id=ids["local"])
            checar("3. dois inventários abertos no mesmo local é recusado", False, "passou")
        except est.EstoqueErro:
            checar("3. dois inventários abertos no mesmo local é recusado", True)

        print("\nContagem\n")

        est.contar(inv_id, {ids["m"]: 8})
        inv = est.inventario(inv_id)
        por_var = {i["variacao_id"]: i for i in inv["itens"]}
        checar("4. a contagem é salva e o não contado fica nulo",
               por_var[ids["m"]]["qtd_contada"] == 8
               and por_var[ids["g"]]["qtd_contada"] is None)

        try:
            est.contar(inv_id, {ids["m"]: -1})
            checar("4b. contagem negativa é recusada", False, "passou")
        except est.EstoqueErro:
            checar("4b. contagem negativa é recusada", True)

        print("\nFechamento gera ajustes\n")

        # Entre abrir e fechar houve uma venda: o ajuste tem de levar ao
        # contado, e não à diferença calculada na abertura.
        est.saida(variacao_id=ids["m"], local_id=ids["local"], quantidade=1,
                  motivo="venda")
        r = est.fechar_inventario(inv_id)
        checar("5. o saldo passa a ser o contado, não o da abertura",
               est.saldo_de(ids["m"], ids["local"]) == 8,
               str(est.saldo_de(ids["m"], ids["local"])))
        checar("6. um ajuste para o item contado", r["ajustes"] == 1, str(r))
        checar("7. o não contado não é tocado",
               est.saldo_de(ids["g"], ids["local"]) == 4)

        c, cur = _conn()
        cur.execute("""SELECT motivo, sentido, quantidade, observacao
                       FROM estoque_movimento WHERE origem = 'inventario'
                         AND origem_id = %s""", (inv_id,))
        ajuste = cur.fetchone()
        cur.execute("SELECT status FROM estoque_inventario WHERE id = %s", (inv_id,))
        status = cur.fetchone()["status"]
        cur.close(); c.close()
        checar("8. a diferença virou movimento com o porquê",
               ajuste and ajuste["motivo"] == "inventario"
               and "contado 8" in (ajuste["observacao"] or ""), str(ajuste))
        checar("9. e o inventário fica fechado", status == "fechado", status)

        try:
            est.fechar_inventario(inv_id)
            checar("10. fechar duas vezes é recusado", False, "passou")
        except est.EstoqueErro:
            checar("10. fechar duas vezes é recusado", True)

        print("\nCancelar não toca no saldo\n")

        inv2 = est.abrir_inventario(local_id=ids["local"])
        est.contar(inv2, {ids["g"]: 999})
        est.cancelar_inventario(inv2)
        checar("11. cancelado, o saldo fica como estava",
               est.saldo_de(ids["g"], ids["local"]) == 4)

        print("\nLoja do aluno (autoatendimento)\n")

        cli = app.test_client()
        with cli.session_transaction() as s:
            s["_user_id"] = str(ids["usuario"])
            s["_fresh"] = True
            s["modo_painel"] = "aluno"
        r = cli.get("/estoque/loja", follow_redirects=True)
        html = r.get_data(as_text=True)
        checar("12. o aluno abre a loja sem permissão de estoque",
               r.status_code == 200, str(r.status_code))
        checar("13. e vê o produto da academia dele", "ZZ Camiseta" in html)
        checar("14. mas não o da outra academia", "SEGREDO" not in html)
        checar("15. com o preço da tabela de aluno", "60,00" in html)

        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        saldo_antes = est.saldo_de(ids["m"], ids["local"])
        # A compra passa pelo carrinho: põe no carrinho e fecha.
        cli.post(f"/estoque/carrinho/{ids['m']}",
                 data={"csrf_token": token, "quantidade": 2}, follow_redirects=True)
        cli.post("/estoque/carrinho",
                 data={"csrf_token": token, "acao": "fechar"}, follow_redirects=True)

        c, cur = _conn()
        cur.execute("""SELECT * FROM estoque_pedido WHERE id_academia = %s
                       ORDER BY id DESC LIMIT 1""", (ACADEMIA,))
        ped = cur.fetchone()
        cur.close(); c.close()
        checar("16. o pedido é criado aguardando a recepção",
               ped and ped["status"] == "aguardando_pagamento", str(ped and ped["status"]))
        checar("17. e o estoque NÃO baixou ainda",
               est.saldo_de(ids["m"], ids["local"]) == saldo_antes,
               str(est.saldo_de(ids["m"], ids["local"])))
        checar("18. o pedido guarda a origem autoatendimento",
               ped["origem"] == "autoatendimento")

        print("\nA recepção confirma\n")

        gestor = app.test_client()
        with gestor.session_transaction() as s:
            s["_user_id"] = str(USUARIO_POR_MODO["admin"])
            s["_fresh"] = True
            s["modo_painel"] = "academia"
            s["academia_gerenciamento_id"] = ACADEMIA
        h = gestor.get("/estoque/pedidos", follow_redirects=True).get_data(as_text=True)
        checar("19. o pedido aparece para a recepção", "ZZ Aluno Loja" in h)
        tok2 = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
        gestor.post(f"/estoque/pedidos/{ped['id']}/confirmar",
                    data={"csrf_token": tok2, "forma_pagamento": "dinheiro"},
                    follow_redirects=True)
        checar("20. confirmando, o estoque baixa",
               est.saldo_de(ids["m"], ids["local"]) == saldo_antes - 2,
               str(est.saldo_de(ids["m"], ids["local"])))

        c, cur = _conn()
        cur.execute("SELECT status, id_receita FROM estoque_pedido WHERE id = %s",
                    (ped["id"],))
        p2 = cur.fetchone()
        cur.close(); c.close()
        checar("21. o pedido fica confirmado e com receita",
               p2["status"] == "confirmado" and p2["id_receita"], str(p2))

        print("\nConferência final\n")
        checar("22. saldo e histórico batem", not est.conferir_saldos(ACADEMIA),
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
