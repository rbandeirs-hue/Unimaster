"""Venda, consignação, débito com a associação e estoque independente.

O cenário que estes testes reproduzem é o descrito pelo dono do sistema:

    Kimono A2 · tabela Professor R$ 160 · tabela Aluno R$ 220
    O aluno paga 220 à academia · a associação perde 1 do estoque
    A academia fica devendo 160 · margem da academia: 60

E o segundo modo de operação: uma organização independente, sem academia e sem
associação, com caixa próprio.

Rodam contra o banco real, com academia/associação/organização de teste
criadas e apagadas aqui.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_estoque_venda.py
"""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection            # noqa: E402
from utils import estoque as est                # noqa: E402
from utils import estoque_venda as venda        # noqa: E402

ACADEMIA = -9970
ASSOC = -9970
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
    # A organização primeiro, e de dentro para fora: `estoque_movimento` tem
    # RESTRICT no local de propósito — o histórico não se apaga por cascata.
    cur.execute("SELECT id FROM estoque_organizacao WHERE nome LIKE 'ZZ Loja%'")
    orgs = [r["id"] for r in cur.fetchall() or []]
    for org in orgs:
        cur.execute("""DELETE m FROM estoque_movimento m
                       JOIN estoque_local l ON l.id = m.local_id
                       WHERE l.id_organizacao = %s""", (org,))
        cur.execute("""DELETE s FROM estoque_saldo s
                       JOIN estoque_local l ON l.id = s.local_id
                       WHERE l.id_organizacao = %s""", (org,))
        cur.execute("DELETE FROM estoque_pedido WHERE id_organizacao = %s", (org,))
        cur.execute("""DELETE v FROM estoque_variacao v
                       JOIN estoque_produto p ON p.id = v.produto_id
                       WHERE p.id_organizacao = %s""", (org,))
        cur.execute("DELETE FROM estoque_produto WHERE id_organizacao = %s", (org,))
        cur.execute("DELETE FROM estoque_local WHERE id_organizacao = %s", (org,))
        cur.execute("DELETE FROM estoque_organizacao WHERE id = %s", (org,))
    cur.execute("DELETE FROM estoque_repasse WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM estoque_repasse_fatura WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM estoque_pedido WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM estoque_movimento WHERE id_academia = %s "
                "OR id_associacao = %s", (ACADEMIA, ASSOC))
    cur.execute("""DELETE s FROM estoque_saldo s JOIN estoque_local l ON l.id = s.local_id
                   WHERE l.id_academia = %s OR l.id_associacao = %s""", (ACADEMIA, ASSOC))
    cur.execute("""DELETE pr FROM estoque_preco pr JOIN estoque_tabela_preco t
                   ON t.id = pr.tabela_id
                   WHERE t.id_academia = %s OR t.id_associacao = %s""", (ACADEMIA, ASSOC))
    cur.execute("DELETE FROM estoque_tabela_preco WHERE id_academia = %s "
                "OR id_associacao = %s", (ACADEMIA, ASSOC))
    cur.execute("""DELETE v FROM estoque_variacao v JOIN estoque_produto p
                   ON p.id = v.produto_id
                   WHERE p.id_academia = %s OR p.id_associacao = %s""", (ACADEMIA, ASSOC))
    cur.execute("DELETE FROM estoque_produto WHERE id_academia = %s OR id_associacao = %s",
                (ACADEMIA, ASSOC))
    cur.execute("DELETE FROM estoque_local WHERE id_academia = %s OR id_associacao = %s",
                (ACADEMIA, ASSOC))
    cur.execute("DELETE FROM receitas WHERE id_academia = %s OR id_associacao = %s",
                (ACADEMIA, ASSOC))
    cur.execute("DELETE FROM despesas WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM associacoes WHERE id = %s", (ASSOC,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    cur.execute("INSERT INTO associacoes (id, nome, estoque_repasse_modo) "
                "VALUES (%s, 'ZZ Assoc Estoque', 'extrato')", (ASSOC,))
    cur.execute("UPDATE associacoes SET modulo_estoque = 1, estoque_revenda = 1 "
                "WHERE id = %s", (ASSOC,))
    cur.execute("INSERT INTO academias (id, nome, id_associacao) VALUES (%s,%s,%s)",
                (ACADEMIA, "ZZ Academia Revenda", ASSOC))
    cur.execute("UPDATE academias SET modulo_estoque = 1 WHERE id = %s", (ACADEMIA,))
    cur.execute("INSERT INTO alunos (id_academia, nome, ativo) VALUES (%s,%s,1)",
                (ACADEMIA, "ZZ Comprador"))
    ids["aluno"] = cur.lastrowid
    cur.execute("INSERT INTO estoque_local (id_associacao, nome, padrao) "
                "VALUES (%s, 'Depósito da associação', 1)", (ASSOC,))
    ids["local_assoc"] = cur.lastrowid
    c.commit(); cur.close(); c.close()

    ids["produto"] = est.criar_produto(nome="ZZ Kimono Revenda", id_associacao=ASSOC,
                                       custo=90, estoque_min=2,
                                       variacoes=[{"nome": "A2", "tamanho": "A2"}])
    c, cur = _conn()
    cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s", (ids["produto"],))
    ids["a2"] = cur.fetchone()["id"]

    # Tabelas da associação: professor é o repasse; aluno é o preço sugerido.
    for nome, perfil, padrao, preco in (("Professor", "professor", 0, 160),
                                        ("Aluno", "aluno", 1, 220)):
        cur.execute("""INSERT INTO estoque_tabela_preco
                       (id_associacao, nome, perfil, padrao) VALUES (%s,%s,%s,%s)""",
                    (ASSOC, nome, perfil, padrao))
        tid = cur.lastrowid
        ids["assoc_" + perfil] = tid
        cur.execute("INSERT INTO estoque_preco (tabela_id, variacao_id, preco) "
                    "VALUES (%s,%s,%s)", (tid, ids["a2"], preco))
    c.commit(); cur.close(); c.close()

    est.entrada(variacao_id=ids["a2"], local_id=ids["local_assoc"], quantidade=10,
                motivo="compra", custo_unitario=90)


def main():
    limpar()
    montar()
    try:
        print("\nVenda consignada: a academia vende o estoque da associação\n")

        pedido = venda.criar_pedido(
            id_academia=ACADEMIA, id_associacao=ASSOC, local_id=ids["local_assoc"],
            comprador_tipo="aluno", aluno_id=ids["aluno"], origem="balcao")
        venda.adicionar_item(pedido, ids["a2"], 1)

        c, cur = _conn()
        cur.execute("SELECT * FROM estoque_pedido WHERE id = %s", (pedido,))
        p = cur.fetchone()
        cur.close(); c.close()
        checar("1. o aluno paga o preço de aluno", Decimal(str(p["valor_total"])) == 220)
        checar("2. o repasse é o preço de professor",
               Decimal(str(p["valor_repasse"])) == 160)
        checar("3. a margem é a diferença, e não é digitada",
               Decimal(str(p["valor_margem"])) == 60)
        checar("4. antes de confirmar, o estoque não mexeu",
               est.saldo_de(ids["a2"], ids["local_assoc"]) == 10)

        r = venda.confirmar(pedido, forma_pagamento="dinheiro")
        checar("5. na confirmação o estoque da associação baixa",
               est.saldo_de(ids["a2"], ids["local_assoc"]) == 9)
        checar("6. a receita da venda é da academia", r["id_receita"] is not None)

        c, cur = _conn()
        cur.execute("SELECT * FROM receitas WHERE id = %s", (r["id_receita"],))
        rec = cur.fetchone()
        cur.execute("SELECT * FROM estoque_repasse WHERE pedido_id = %s", (pedido,))
        rep = cur.fetchone()
        cur.close(); c.close()
        checar("7. a academia recebe os 220",
               rec["id_academia"] == ACADEMIA and Decimal(str(rec["valor"])) == 220)
        checar("8. e nasce um débito de 160 com a associação",
               rep and Decimal(str(rep["valor"])) == 160 and rep["status"] == "aberto")

        try:
            venda.confirmar(pedido)
            checar("9. confirmar duas vezes é recusado", False, "passou")
        except venda.VendaErro:
            checar("9. confirmar duas vezes é recusado", True)

        print("\nExtrato e fatura mensal\n")

        pedido2 = venda.criar_pedido(
            id_academia=ACADEMIA, id_associacao=ASSOC, local_id=ids["local_assoc"],
            comprador_tipo="aluno", aluno_id=ids["aluno"])
        venda.adicionar_item(pedido2, ids["a2"], 2)
        venda.confirmar(pedido2)

        ext = venda.extrato_repasse(id_academia=ACADEMIA, id_associacao=ASSOC)
        checar("10. o extrato soma o que está em aberto",
               ext["em_aberto"] == Decimal("480"), str(ext["em_aberto"]))

        from datetime import date as _d
        comp = _d.today().strftime("%Y-%m")
        fat = venda.fechar_fatura(ACADEMIA, ASSOC, comp)
        checar("11. a fatura do mês junta os repasses",
               fat["valor"] == Decimal("480") and fat["itens"] == 2, str(fat))

        try:
            venda.fechar_fatura(ACADEMIA, ASSOC, comp)
            checar("12. fechar de novo não cobra o que já foi faturado", False, "passou")
        except venda.VendaErro:
            checar("12. fechar de novo não cobra o que já foi faturado", True)

        q = venda.quitar_fatura(fat["fatura_id"])
        c, cur = _conn()
        cur.execute("SELECT id_academia, valor FROM despesas WHERE id = %s",
                    (q["id_despesa"],))
        desp = cur.fetchone()
        cur.execute("SELECT id_associacao, valor FROM receitas WHERE id = %s",
                    (q["id_receita"],))
        rec2 = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n FROM estoque_repasse "
                    "WHERE id_academia = %s AND status <> 'pago'", (ACADEMIA,))
        abertos = cur.fetchone()["n"]
        cur.close(); c.close()
        checar("13. quitar vira despesa na academia",
               desp and desp["id_academia"] == ACADEMIA and Decimal(str(desp["valor"])) == 480)
        checar("14. e receita na associação",
               rec2 and rec2["id_associacao"] == ASSOC and Decimal(str(rec2["valor"])) == 480)
        checar("15. nenhum repasse fica em aberto depois de pago", abertos == 0, str(abertos))

        print("\nCancelamento desfaz tudo\n")

        pedido3 = venda.criar_pedido(
            id_academia=ACADEMIA, id_associacao=ASSOC, local_id=ids["local_assoc"],
            comprador_tipo="avulso", comprador_nome="ZZ Cliente balcão")
        venda.adicionar_item(pedido3, ids["a2"], 1)
        venda.confirmar(pedido3)
        saldo_antes = est.saldo_de(ids["a2"], ids["local_assoc"])
        venda.cancelar(pedido3, motivo="desistiu")
        checar("16. cancelar devolve o item ao estoque",
               est.saldo_de(ids["a2"], ids["local_assoc"]) == saldo_antes + 1)
        c, cur = _conn()
        cur.execute("SELECT COUNT(*) AS n FROM estoque_repasse WHERE pedido_id = %s",
                    (pedido3,))
        rep3 = cur.fetchone()["n"]
        cur.execute("SELECT cancelada FROM receitas WHERE id = "
                    "(SELECT id_receita FROM estoque_pedido WHERE id = %s)", (pedido3,))
        cancelada = cur.fetchone()
        cur.close(); c.close()
        checar("17. o débito com a associação some junto", rep3 == 0)
        checar("18. e a receita é marcada como cancelada",
               cancelada and cancelada["cancelada"] == 1)

        print("\nTravas\n")

        c, cur = _conn()
        cur.execute("UPDATE associacoes SET estoque_revenda = 0 WHERE id = %s", (ASSOC,))
        c.commit(); cur.close(); c.close()
        try:
            venda.criar_pedido(id_academia=ACADEMIA, id_associacao=ASSOC,
                               local_id=ids["local_assoc"], comprador_tipo="avulso")
            checar("19. sem liberação da associação, a academia não vende", False, "passou")
        except venda.VendaErro:
            checar("19. sem liberação da associação, a academia não vende", True)
        c, cur = _conn()
        cur.execute("UPDATE associacoes SET estoque_revenda = 1 WHERE id = %s", (ASSOC,))
        c.commit(); cur.close(); c.close()

        print("\nEstoque independente, com caixa próprio\n")

        c, cur = _conn()
        cur.execute("INSERT INTO estoque_organizacao (nome) VALUES ('ZZ Loja Teste')")
        ids["org"] = cur.lastrowid
        cur.execute("INSERT INTO estoque_local (id_organizacao, nome, padrao) "
                    "VALUES (%s, 'Loja', 1)", (ids["org"],))
        ids["local_org"] = cur.lastrowid
        cur.execute("""INSERT INTO estoque_tabela_preco (id_organizacao, nome, padrao)
                       VALUES (%s, 'Balcão', 1)""", (ids["org"],))
        ids["tab_org"] = cur.lastrowid
        c.commit(); cur.close(); c.close()

        ids["prod_org"] = est.criar_produto(nome="ZZ Faixa Loja", id_organizacao=ids["org"],
                                            custo=20, estoque_min=1)
        c, cur = _conn()
        cur.execute("SELECT id FROM estoque_variacao WHERE produto_id = %s",
                    (ids["prod_org"],))
        ids["var_org"] = cur.fetchone()["id"]
        cur.execute("INSERT INTO estoque_preco (tabela_id, variacao_id, preco) "
                    "VALUES (%s,%s,50)", (ids["tab_org"], ids["var_org"]))
        c.commit(); cur.close(); c.close()

        est.entrada(variacao_id=ids["var_org"], local_id=ids["local_org"], quantidade=5)
        ped_org = venda.criar_pedido(id_organizacao=ids["org"], id_academia=None,
                                     local_id=ids["local_org"], comprador_tipo="avulso",
                                     comprador_nome="ZZ Cliente externo")
        checar("20. organização vende sem academia nem associação", ped_org > 0)
        venda.adicionar_item(ped_org, ids["var_org"], 2)
        rr = venda.confirmar(ped_org, forma_pagamento="pix")
        checar("21. o estoque da loja baixa",
               est.saldo_de(ids["var_org"], ids["local_org"]) == 3)
        checar("22. sem repasse: não há associação envolvida",
               rr["repasse"] == 0 and rr["repasse_id"] is None)
        checar("23. e nada foi lançado em receitas", rr["id_receita"] is None)

        cx = venda.caixa(ids["org"])
        checar("24. o caixa próprio registrou os 100",
               cx["recebido"] == Decimal("100") and cx["saldo"] == Decimal("100"), str(cx))

        pan = est.panorama(id_organizacao=ids["org"])
        checar("25. o painel da loja vê só o estoque dela",
               pan["produtos"] == 1 and pan["itens"] == 3, str(pan))
        pan_ac = est.panorama(id_academia=ACADEMIA)
        checar("26. e o painel da academia não enxerga a loja",
               pan_ac["produtos"] == 0, str(pan_ac["produtos"]))

        print("\nConferência final\n")
        checar("27. saldo e histórico continuam batendo",
               not est.conferir_saldos(), str(est.conferir_saldos()))
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
