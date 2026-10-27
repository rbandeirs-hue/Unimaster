# -*- coding: utf-8 -*-
"""Venda do estoque: pedido, confirmação, consignação e o débito com a associação.

O fluxo, em uma frase
---------------------
O pedido nasce aberto, recebe itens com preço congelado, e só na CONFIRMAÇÃO é
que o estoque baixa, o dinheiro é lançado e o débito com a associação nasce.

Por que a baixa não acontece no pedido
--------------------------------------
No balcão daria na mesma. No autoatendimento, não: dez pessoas "comprando" o
último kimono deixariam o saldo em -9 sem ninguém ter pago. Um mecanismo só
atende os dois casos — no balcão a confirmação é imediata, no autoatendimento
ela é o pagamento.

Consignação
-----------
A associação é dona do estoque; a academia vende dele sem transferência. O
aluno paga o preço da tabela dele; a academia deve à associação o preço da
tabela de professor; a diferença é a margem da academia.

    Kimono A2 · Professor R$ 160 · Aluno R$ 220
    aluno paga 220 → academia deve 160 → margem 60

Os dois valores são congelados no item. Reajuste de tabela amanhã não muda o
pedido de ontem: histórico financeiro não se reescreve.

Dois modos de acerto, à escolha da associação (`estoque_repasse_modo`):

  extrato — os débitos ficam abertos e entram na fatura do mês;
  venda   — cada venda já nasce como um débito seu, a acertar na hora.

Nos dois casos o débito é a mesma linha em `estoque_repasse`. O que muda é se
ele é agrupado numa fatura.
"""
from datetime import date
from decimal import Decimal

from config import get_db_connection
from utils.financeiro_core import auditar
from utils import estoque as est

STATUS_ABERTO = "aberto"
STATUS_AGUARDANDO = "aguardando_pagamento"
STATUS_CONFIRMADO = "confirmado"
STATUS_CANCELADO = "cancelado"

# Perfil de tabela de preço sugerido por tipo de comprador. O externo cai na
# tabela padrão, que é o que o dono do estoque definiu como preço de balcão.
PERFIL_POR_COMPRADOR = {"aluno": "aluno", "visitante": None,
                        "usuario": None, "avulso": None}


class VendaErro(est.EstoqueErro):
    """Recusa de regra na venda. Herda de EstoqueErro para a rota tratar uma só."""


def _conn():
    return get_db_connection()


# ------------------------------------------------------------------ pedido
def criar_pedido(*, id_academia=None, id_associacao=None, id_organizacao=None,
                 local_id, comprador_tipo="avulso", aluno_id=None,
                 visitante_id=None, usuario_id=None, comprador_nome=None,
                 tabela_preco_id=None, origem="balcao", observacao=None,
                 criado_por=None):
    """Abre um pedido vazio. Nada sai do estoque ainda.

    `id_associacao` preenchido junto com `id_academia` significa consignação:
    a academia vende, a associação é dona da mercadoria.
    """
    if comprador_tipo not in ("aluno", "visitante", "usuario", "avulso"):
        raise VendaErro("Tipo de comprador inválido.")
    if comprador_tipo == "aluno" and not aluno_id:
        raise VendaErro("Escolha o aluno comprador.")
    if origem not in ("balcao", "autoatendimento"):
        raise VendaErro("Origem do pedido inválida.")
    if not (id_academia or id_organizacao):
        raise VendaErro("O pedido precisa de uma academia ou organização vendedora.")

    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        local = est._local(cur, local_id)
        # Consignação: o local é da associação, mas quem vende é a academia.
        if id_associacao:
            if local["id_associacao"] != id_associacao:
                raise VendaErro("O local não pertence à associação informada.")
            if not _revenda_liberada(cur, id_associacao):
                raise VendaErro(
                    "Esta associação não liberou a revenda do estoque dela.")
        elif id_organizacao:
            if local["id_organizacao"] != id_organizacao:
                raise VendaErro("O local não pertence a esta organização.")
        elif local["id_academia"] != id_academia:
            raise VendaErro("O local não pertence a esta academia.")

        cur.execute(
            """INSERT INTO estoque_pedido
               (id_academia, id_associacao, id_organizacao, local_id, tabela_preco_id,
                comprador_tipo, aluno_id, visitante_id, usuario_id, comprador_nome,
                origem, observacao, criado_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (id_academia, id_associacao, id_organizacao, local_id, tabela_preco_id,
             comprador_tipo, aluno_id, visitante_id, usuario_id,
             (comprador_nome or "").strip() or None, origem, observacao, criado_por))
        pedido_id = cur.lastrowid
        conn.commit()
        return pedido_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _revenda_liberada(cur, id_associacao):
    cur.execute("SELECT COALESCE(estoque_revenda, 0) AS v, "
                "COALESCE(modulo_estoque, 0) AS m FROM associacoes WHERE id = %s",
                (id_associacao,))
    r = cur.fetchone()
    return bool(r and r["v"] and r["m"])


def _pedido(cur, pedido_id, travar=False):
    cur.execute("SELECT * FROM estoque_pedido WHERE id = %s"
                + (" FOR UPDATE" if travar else ""), (pedido_id,))
    p = cur.fetchone()
    if not p:
        raise VendaErro("Pedido não encontrado.")
    return p


def _preco_de_venda(cur, pedido, variacao_id):
    """Quanto o comprador paga, e de qual tabela saiu.

    Ordem de busca, e o porquê dela:

      1. a tabela escolhida no pedido — decisão explícita de quem vende;
      2. a tabela da ACADEMIA para o perfil do comprador. É ela que define a
         margem: a academia pode vender mais caro ou mais barato do que a
         associação sugere;
      3. a tabela da ASSOCIAÇÃO para o mesmo perfil. Sem isto, a academia que
         ainda não montou tabela própria simplesmente não conseguiria vender o
         estoque consignado — que é o caso mais comum no começo;
      4. a tabela padrão do dono do estoque, que é o preço de balcão.

    Sem preço em nenhuma, recusa. Inventar um número aqui seria pior.
    """
    if pedido["tabela_preco_id"]:
        p = est.preco_de(variacao_id, pedido["tabela_preco_id"])
        if p is not None:
            return p, pedido["tabela_preco_id"]

    perfil = PERFIL_POR_COMPRADOR.get(pedido["comprador_tipo"])
    if perfil:
        donos = [{"id_academia": pedido["id_academia"]},
                 {"id_associacao": pedido["id_associacao"]},
                 {"id_organizacao": pedido["id_organizacao"]}]
        for dono in donos:
            if not list(dono.values())[0]:
                continue
            for t in est.tabelas_de_preco(perfil=perfil, **dono):
                p = est.preco_de(variacao_id, t["id"])
                if p is not None:
                    return p, t["id"]

    # Padrão: o do dono do ESTOQUE primeiro (é dele a mercadoria), depois o da
    # academia vendedora.
    for dono in ({"id_associacao": pedido["id_associacao"]},
                 {"id_organizacao": pedido["id_organizacao"]},
                 {"id_academia": pedido["id_academia"]}):
        if not list(dono.values())[0]:
            continue
        p = est.preco_de(variacao_id, **dono)
        if p is not None:
            return p, None

    raise VendaErro(
        "Este item não tem preço em nenhuma tabela aplicável a este pedido. "
        "Cadastre o preço antes de vender.")


def _repasse_de(cur, pedido, variacao_id):
    """Quanto a academia deve à associação por este item.

    É o preço da tabela de PROFESSOR da associação — foi a regra definida pelo
    dono do sistema. Sem consignação, o repasse é zero.
    """
    if not pedido["id_associacao"]:
        return Decimal("0.00")
    for t in est.tabelas_de_preco(id_associacao=pedido["id_associacao"],
                                  perfil="professor"):
        p = est.preco_de(variacao_id, t["id"])
        if p is not None:
            return p
    raise VendaErro(
        "A associação não tem preço de professor para este item — "
        "sem ele não dá para saber quanto a academia passa a dever.")


def adicionar_item(pedido_id, variacao_id, quantidade, preco_unitario=None):
    """Põe um item no pedido, com preço e repasse congelados.

    `preco_unitario` só é aceito de quem opera o balcão e quer dar desconto; o
    repasse NÃO é negociável por aqui, porque é dívida com terceiro.
    """
    quantidade = est._int_positivo(quantidade)
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        pedido = _pedido(cur, pedido_id)
        if pedido["status"] != STATUS_ABERTO:
            raise VendaErro("Só dá para mexer nos itens de um pedido aberto.")

        v = est._variacao(cur, variacao_id)
        local = est._local(cur, pedido["local_id"])
        if not est._mesmo_dono(v, local):
            raise VendaErro("O produto não pertence ao dono deste local.")

        if preco_unitario is None:
            preco_unitario, tabela_id = _preco_de_venda(cur, pedido, variacao_id)
            if tabela_id and not pedido["tabela_preco_id"]:
                cur.execute("UPDATE estoque_pedido SET tabela_preco_id = %s WHERE id = %s",
                            (tabela_id, pedido_id))
        repasse = _repasse_de(cur, pedido, variacao_id)

        cur.execute(
            """INSERT INTO estoque_pedido_item
               (pedido_id, variacao_id, quantidade, preco_unitario, repasse_unitario)
               VALUES (%s,%s,%s,%s,%s)""",
            (pedido_id, variacao_id, quantidade, preco_unitario, repasse))
        item_id = cur.lastrowid
        _recalcular(cur, pedido_id)
        conn.commit()
        return item_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _recalcular(cur, pedido_id):
    """Totais do pedido a partir dos itens. A margem nunca é digitada."""
    cur.execute(
        """SELECT COALESCE(SUM(quantidade * preco_unitario), 0) AS total,
                  COALESCE(SUM(quantidade * repasse_unitario), 0) AS repasse
           FROM estoque_pedido_item WHERE pedido_id = %s""", (pedido_id,))
    r = cur.fetchone()
    total = Decimal(str(r["total"] or 0))
    repasse = Decimal(str(r["repasse"] or 0))
    cur.execute(
        """UPDATE estoque_pedido SET valor_total = %s, valor_repasse = %s,
                                     valor_margem = %s WHERE id = %s""",
        (total, repasse, total - repasse, pedido_id))
    return total, repasse


# ------------------------------------------------------------- confirmação
def confirmar(pedido_id, usuario_id=None, forma_pagamento=None,
              autorizar_negativo=False, data_venda=None):
    """O momento em que tudo acontece, numa transação só.

    Baixa o estoque item a item, lança o dinheiro e cria o débito com a
    associação. Se qualquer passo falhar, nada fica gravado — não existe meia
    venda com o estoque baixado e o dinheiro não lançado.
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        pedido = _pedido(cur, pedido_id, travar=True)
        if pedido["status"] == STATUS_CONFIRMADO:
            raise VendaErro("Este pedido já foi confirmado.")
        if pedido["status"] == STATUS_CANCELADO:
            raise VendaErro("Pedido cancelado não pode ser confirmado.")

        cur.execute("SELECT * FROM estoque_pedido_item WHERE pedido_id = %s ORDER BY id",
                    (pedido_id,))
        itens = cur.fetchall() or []
        if not itens:
            raise VendaErro("Pedido sem itens.")

        total, repasse = _recalcular(cur, pedido_id)

        for item in itens:
            mov_id = est.movimentar(
                variacao_id=item["variacao_id"], local_id=pedido["local_id"],
                sentido="S", motivo="venda", quantidade=item["quantidade"],
                usuario_id=usuario_id, preco_unitario=item["preco_unitario"],
                tabela_preco_id=pedido["tabela_preco_id"],
                aluno_id=pedido["aluno_id"],
                origem="pedido", origem_id=pedido_id,
                observacao=f"Pedido {pedido_id}",
                autorizar_negativo=autorizar_negativo,
                conn=conn, cur=cur)
            cur.execute("UPDATE estoque_pedido_item SET movimento_id = %s WHERE id = %s",
                        (mov_id, item["id"]))

        quando = data_venda or date.today()
        id_receita = _lancar_entrada(cur, pedido, total, quando, forma_pagamento,
                                     usuario_id)
        repasse_id = _gerar_repasse(cur, pedido, repasse)

        cur.execute(
            """UPDATE estoque_pedido SET status = %s, confirmado_em = NOW(),
                                         id_receita = %s WHERE id = %s""",
            (STATUS_CONFIRMADO, id_receita, pedido_id))

        auditar(cur, pedido["id_academia"], "estoque_pedido", pedido_id, "confirmar",
                valor_novo=total, usuario_id=usuario_id,
                detalhes=f"{len(itens)} item(ns) · repasse {repasse} · "
                         f"margem {total - repasse}")
        conn.commit()
        return {"pedido_id": pedido_id, "total": total, "repasse": repasse,
                "margem": total - repasse, "id_receita": id_receita,
                "repasse_id": repasse_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _lancar_entrada(cur, pedido, total, quando, forma_pagamento, usuario_id):
    """Onde o dinheiro da venda é registrado.

    Academia: `receitas`, que é o financeiro que ela já usa — a venda aparece
    junto com mensalidade e matrícula, sem um segundo lugar para conferir.

    Organização independente: `estoque_lancamento`, o caixa dela. Não uso
    `receitas` porque aquela tabela pertence à hierarquia federação →
    associação → academia, e a organização não está em nenhuma delas.
    """
    if total <= 0:
        return None

    descricao = f"Venda de estoque · pedido {pedido['id']}"
    if pedido["id_organizacao"]:
        cur.execute(
            """INSERT INTO estoque_lancamento
               (organizacao_id, sentido, valor, data, categoria, descricao,
                forma_pagamento, pedido_id, criado_por)
               VALUES (%s,'R',%s,%s,'Venda',%s,%s,%s,%s)""",
            (pedido["id_organizacao"], total, quando, descricao,
             forma_pagamento, pedido["id"], usuario_id))
        return None

    cur.execute(
        """INSERT INTO receitas
           (descricao, valor, data, categoria, id_academia, id_aluno, criado_por)
           VALUES (%s,%s,%s,'Estoque',%s,%s,%s)""",
        (descricao, total, quando, pedido["id_academia"], pedido["aluno_id"],
         usuario_id))
    from utils.financeiro_core import espelhar_receita
    espelhar_receita(cur, cur.lastrowid)  # receita → caixa (utils/financeiro_core.py)
    return cur.lastrowid


def _gerar_repasse(cur, pedido, valor):
    """O débito da academia com a associação.

    Nasce aberto nos dois modos. No modo `venda` ele é para acertar já; no modo
    `extrato` fica esperando o fechamento da fatura do mês. A diferença é da
    tela e do fechamento, não do dado — assim trocar de modo não reescreve
    dívida antiga.
    """
    if not pedido["id_associacao"] or valor <= 0:
        return None
    cur.execute(
        """INSERT INTO estoque_repasse
           (id_academia, id_associacao, pedido_id, valor, status)
           VALUES (%s,%s,%s,%s,'aberto')""",
        (pedido["id_academia"], pedido["id_associacao"], pedido["id"], valor))
    return cur.lastrowid


def cancelar(pedido_id, usuario_id=None, motivo=None):
    """Cancela o pedido. Se já estava confirmado, estorna tudo.

    Pedido confirmado não é apagado nem volta a aberto: a mercadoria saiu, o
    dinheiro foi lançado e o débito nasceu. O caminho é desfazer cada um por
    onde ele é desfeito — estorno de estoque, cancelamento da receita, baixa
    do repasse — e tudo continua visível no histórico.
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        pedido = _pedido(cur, pedido_id, travar=True)
        if pedido["status"] == STATUS_CANCELADO:
            raise VendaErro("Este pedido já está cancelado.")

        if pedido["status"] == STATUS_CONFIRMADO:
            cur.execute("""SELECT id, movimento_id FROM estoque_pedido_item
                           WHERE pedido_id = %s AND movimento_id IS NOT NULL""",
                        (pedido_id,))
            for item in cur.fetchall() or []:
                orig = item["movimento_id"]
                cur.execute("SELECT * FROM estoque_movimento WHERE id = %s FOR UPDATE",
                            (orig,))
                m = cur.fetchone()
                if not m:
                    continue
                est.movimentar(
                    variacao_id=m["variacao_id"], local_id=m["local_id"],
                    sentido="E", motivo="estorno", quantidade=m["quantidade"],
                    usuario_id=usuario_id, custo_unitario=m["custo_unitario"],
                    estorna_movimento_id=orig,
                    observacao=motivo or f"Cancelamento do pedido {pedido_id}",
                    autorizar_negativo=True, conn=conn, cur=cur)

            if pedido["id_receita"]:
                cur.execute("UPDATE receitas SET cancelada = 1 WHERE id = %s",
                            (pedido["id_receita"],))
            if pedido["id_organizacao"]:
                cur.execute("UPDATE estoque_lancamento SET cancelado = 1 "
                            "WHERE pedido_id = %s", (pedido_id,))

            cur.execute("""SELECT id, status FROM estoque_repasse
                           WHERE pedido_id = %s FOR UPDATE""", (pedido_id,))
            for rep in cur.fetchall() or []:
                if rep["status"] == "pago":
                    raise VendaErro(
                        "O repasse desta venda já foi pago à associação. "
                        "Cancelar aqui deixaria a conta errada — acerte com ela primeiro.")
                cur.execute("DELETE FROM estoque_repasse WHERE id = %s", (rep["id"],))

        cur.execute("""UPDATE estoque_pedido SET status = %s, cancelado_em = NOW()
                       WHERE id = %s""", (STATUS_CANCELADO, pedido_id))
        auditar(cur, pedido["id_academia"], "estoque_pedido", pedido_id, "cancelar",
                motivo=motivo, usuario_id=usuario_id)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ------------------------------------------------------ conta com a associação
def extrato_repasse(id_academia=None, id_associacao=None, status=None):
    """O que a academia deve, linha a linha."""
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        onde, par = ["1=1"], []
        if id_academia:
            onde.append("r.id_academia = %s"); par.append(id_academia)
        if id_associacao:
            onde.append("r.id_associacao = %s"); par.append(id_associacao)
        if status:
            onde.append("r.status = %s"); par.append(status)
        cur.execute(f"""
            SELECT r.*, a.nome AS academia, p.confirmado_em, p.comprador_nome
            FROM estoque_repasse r
            JOIN academias a ON a.id = r.id_academia
            LEFT JOIN estoque_pedido p ON p.id = r.pedido_id
            WHERE {' AND '.join(onde)}
            ORDER BY r.criado_em DESC""", tuple(par))
        linhas = cur.fetchall() or []
        total = sum(Decimal(str(x["valor"])) for x in linhas if x["status"] != "pago")
        return {"linhas": linhas, "em_aberto": total}
    finally:
        cur.close()
        conn.close()


def fechar_fatura(id_academia, id_associacao, competencia, usuario_id=None):
    """Junta os repasses abertos da competência numa fatura.

    Competência no formato AAAA-MM. Só entra repasse `aberto`: fechar duas
    vezes o mesmo mês não cobra de novo o que já foi faturado.
    """
    if not (competencia and len(competencia) == 7 and competencia[4] == "-"):
        raise VendaErro("Competência inválida. Use AAAA-MM.")
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        # CONCAT em vez de DATE_FORMAT(..., '%Y-%m'): o conector desta base não
        # desescapa o '%%' e grava o literal '%Y-%m' na consulta. Já custou 747
        # linhas erradas neste projeto uma vez.
        cur.execute("""SELECT id, valor FROM estoque_repasse
                       WHERE id_academia = %s AND id_associacao = %s
                         AND status = 'aberto'
                         AND CONCAT(YEAR(criado_em), '-',
                                    LPAD(MONTH(criado_em), 2, '0')) = %s
                       FOR UPDATE""",
                    (id_academia, id_associacao, competencia))
        abertos = cur.fetchall() or []
        if not abertos:
            raise VendaErro("Nenhum repasse em aberto nesta competência.")
        total = sum(Decimal(str(r["valor"])) for r in abertos)

        cur.execute(
            """INSERT INTO estoque_repasse_fatura
               (id_academia, id_associacao, competencia, valor, status, fechada_em)
               VALUES (%s,%s,%s,%s,'fechada',NOW())
               ON DUPLICATE KEY UPDATE valor = valor + VALUES(valor),
                                       status = 'fechada', fechada_em = NOW()""",
            (id_academia, id_associacao, competencia, total))
        cur.execute("""SELECT id FROM estoque_repasse_fatura
                       WHERE id_academia = %s AND id_associacao = %s
                         AND competencia = %s""",
                    (id_academia, id_associacao, competencia))
        fatura_id = cur.fetchone()["id"]

        ids = tuple(r["id"] for r in abertos)
        marcas = ", ".join(["%s"] * len(ids))
        cur.execute(f"""UPDATE estoque_repasse SET status = 'faturado', fatura_id = %s
                        WHERE id IN ({marcas})""", (fatura_id,) + ids)
        auditar(cur, id_academia, "estoque_repasse_fatura", fatura_id, "fechar",
                valor_novo=total, usuario_id=usuario_id,
                detalhes=f"{competencia}: {len(abertos)} repasse(s)")
        conn.commit()
        return {"fatura_id": fatura_id, "valor": total, "itens": len(abertos)}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def quitar_fatura(fatura_id, usuario_id=None, data_pagamento=None):
    """A academia pagou: vira despesa nela e receita na associação."""
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM estoque_repasse_fatura WHERE id = %s FOR UPDATE",
                    (fatura_id,))
        f = cur.fetchone()
        if not f:
            raise VendaErro("Fatura não encontrada.")
        if f["status"] == "paga":
            raise VendaErro("Esta fatura já está paga.")

        quando = data_pagamento or date.today()
        descricao = f"Repasse de estoque {f['competencia']}"
        cur.execute(
            """INSERT INTO despesas (descricao, valor, data, categoria,
                                     id_academia, criado_por)
               VALUES (%s,%s,%s,'Estoque',%s,%s)""",
            (descricao, f["valor"], quando, f["id_academia"], usuario_id))
        id_despesa = cur.lastrowid
        cur.execute(
            """INSERT INTO receitas (descricao, valor, data, categoria,
                                     id_associacao, criado_por)
               VALUES (%s,%s,%s,'Estoque',%s,%s)""",
            (descricao, f["valor"], quando, f["id_associacao"], usuario_id))
        id_receita = cur.lastrowid

        cur.execute("""UPDATE estoque_repasse_fatura
                       SET status = 'paga', paga_em = NOW(),
                           id_despesa = %s, id_receita = %s WHERE id = %s""",
                    (id_despesa, id_receita, fatura_id))
        cur.execute("""UPDATE estoque_repasse SET status = 'pago', quitado_em = NOW()
                       WHERE fatura_id = %s""", (fatura_id,))
        auditar(cur, f["id_academia"], "estoque_repasse_fatura", fatura_id, "quitar",
                valor_novo=f["valor"], usuario_id=usuario_id)
        conn.commit()
        return {"id_despesa": id_despesa, "id_receita": id_receita,
                "valor": f["valor"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def caixa(organizacao_id, desde=None, ate=None):
    """Resumo do financeiro próprio da organização independente."""
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        onde, par = ["organizacao_id = %s", "cancelado = 0"], [organizacao_id]
        if desde:
            onde.append("data >= %s"); par.append(desde)
        if ate:
            onde.append("data <= %s"); par.append(ate)
        cur.execute(f"""SELECT sentido, COALESCE(SUM(valor), 0) AS total,
                               COUNT(*) AS n
                        FROM estoque_lancamento
                        WHERE {' AND '.join(onde)} GROUP BY sentido""", tuple(par))
        por = {r["sentido"]: r for r in cur.fetchall() or []}
        entrou = Decimal(str(por.get("R", {}).get("total", 0)))
        saiu = Decimal(str(por.get("D", {}).get("total", 0)))
        return {"recebido": entrou, "pago": saiu, "saldo": entrou - saiu,
                "lancamentos": sum(r["n"] for r in por.values())}
    finally:
        cur.close()
        conn.close()
