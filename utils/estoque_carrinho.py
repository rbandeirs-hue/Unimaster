# -*- coding: utf-8 -*-
"""Carrinho da loja.

Onde o carrinho mora
--------------------
Na sessão, não no banco. A alternativa seria usar um `estoque_pedido` com
status `aberto` como rascunho, e ela tem um custo alto: todo carrinho
abandonado viraria uma linha que a recepção veria como pedido a atender. O
carrinho é do navegador; o pedido nasce no fechamento, e aí sim é um
compromisso.

O que a sessão guarda é o mínimo — id da variação e quantidade. Preço, saldo e
nome são lidos do banco a cada exibição, porque preço de carrinho velho não
pode valer mais do que o preço de hoje. O congelamento acontece uma vez só, no
pedido, que é onde ele tem significado.

A academia entra na chave: aluno que troca de academia não leva o carrinho de
produtos que não existem lá.
"""
from flask import session

CHAVE = "estoque_carrinho"


def _cesta(academia_id):
    todas = session.get(CHAVE) or {}
    return todas.get(str(academia_id)) or {}


def _guardar(academia_id, cesta):
    todas = session.get(CHAVE) or {}
    if cesta:
        todas[str(academia_id)] = cesta
    else:
        todas.pop(str(academia_id), None)
    session[CHAVE] = todas
    session.modified = True


def itens(academia_id):
    """{variacao_id: quantidade}, com as chaves já como inteiros."""
    return {int(k): int(v) for k, v in _cesta(academia_id).items() if int(v) > 0}


def quantidade(academia_id):
    return sum(itens(academia_id).values())


def por(academia_id, variacao_id, quantidade_nova, limite=None):
    """Define a quantidade de um item. Zero ou negativo remove.

    `limite` é o saldo disponível: o carrinho não deixa pedir mais do que
    existe. Não é reserva — entre pôr no carrinho e fechar, outra pessoa pode
    levar. A recusa definitiva é na confirmação, onde o saldo é travado.
    """
    cesta = dict(_cesta(academia_id))
    try:
        qtd = int(quantidade_nova)
    except (TypeError, ValueError):
        qtd = 0
    if limite is not None:
        qtd = min(qtd, int(limite))
    if qtd > 0:
        cesta[str(int(variacao_id))] = qtd
    else:
        cesta.pop(str(int(variacao_id)), None)
    _guardar(academia_id, cesta)
    return qtd


def somar(academia_id, variacao_id, quantidade_extra=1, limite=None):
    atual = itens(academia_id).get(int(variacao_id), 0)
    return por(academia_id, variacao_id, atual + int(quantidade_extra), limite)


def limpar(academia_id):
    _guardar(academia_id, {})


def detalhar(academia_id, vitrine):
    """Junta o carrinho com o catálogo: linhas prontas para a tela.

    Item que saiu do catálogo — desativado, sem preço ou sem saldo — vira uma
    linha marcada como indisponível em vez de sumir calado. O comprador precisa
    saber por que o total mudou.
    """
    cesta = itens(academia_id)
    if not cesta:
        return [], 0, []

    por_id = {i["id"]: i for i in vitrine}
    linhas, total, alertas = [], 0, []
    for variacao_id, qtd in cesta.items():
        item = por_id.get(variacao_id)
        if not item:
            alertas.append("Um item saiu do catálogo e foi removido do carrinho.")
            por(academia_id, variacao_id, 0)
            continue
        disponivel = int(item["saldo"])
        if qtd > disponivel:
            alertas.append(
                f"{item['produto']}: só restam {disponivel}. "
                "A quantidade foi ajustada.")
            qtd = por(academia_id, variacao_id, disponivel)
            if qtd <= 0:
                continue
        subtotal = float(item["preco"]) * qtd
        total += subtotal
        linhas.append({**item, "quantidade": qtd, "subtotal": subtotal})
    linhas.sort(key=lambda x: (x["produto"], x["variacao"]))
    return linhas, total, alertas
