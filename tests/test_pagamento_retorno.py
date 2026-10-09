"""A cobrança criada pela régua de cobrança nascia sem endereço de retorno.

Sintoma: pagamento feito pelo link que o WhatsApp manda não dava baixa — nunca.
Não era "alguns": `pago_auto` (a marca da baixa automática) não existia em
nenhuma linha da base, e nenhum POST do gateway chegou ao /financeiro/webhook/*
em todo o histórico de log, enquanto 22 cobranças eram quitadas na mão.

Causa: o link é criado em dois lugares.
  * pela tela, dentro de uma request — `url_for(_external=True)` funciona;
  * pela régua de cobrança, no systemd, só com app_context — e aí o mesmo
    `url_for` levanta RuntimeError (sem SERVER_NAME não há como montar URL
    absoluta). O except engolia, `webhook_url` virava None, e a InfinitePay
    ficava sem para onde avisar.

Estes testes fixam:
  * a URL pública sai igual nos dois contextos, com e sem request;
  * a cobrança criada fora de request leva webhook_url e redirect_url;
  * a página de retorno do pagador existe, é pública e não dá baixa por
    conta própria — quem decide é a API do gateway.

Nada aqui toca em cobrança real: o cliente do gateway é substituído por um
espião e nenhuma requisição sai para fora.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_pagamento_retorno.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                      # noqa: E402
from config import get_db_connection                     # noqa: E402
from utils.links_curtos import url_publica               # noqa: E402

_falhas = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


class _EspiaoInfinitePay:
    """Entra no lugar do cliente real e guarda o que teria sido enviado."""

    ultimo = {}

    def __init__(self, handle):
        self.handle = handle

    def criar_link(self, valor, descricao, order_nsu, webhook_url=None,
                   redirect_url=None, **kw):
        _EspiaoInfinitePay.ultimo = {
            "valor": valor, "order_nsu": order_nsu,
            "webhook_url": webhook_url, "redirect_url": redirect_url,
        }
        return {"payment_id": str(order_nsu), "tipo": "LINK",
                "boleto_url": "https://checkout.infinitepay.io/teste",
                "pix_qrcode": None, "pix_copia_cola": None}


def _emitir_sem_request():
    """Chama a emissão como a régua chama: app_context, nenhuma request."""
    import utils.infinitepay as ip
    from blueprints.financeiro import routes as fin
    original = ip.InfinitePayClient
    ip.InfinitePayClient = _EspiaoInfinitePay
    try:
        with app.app_context():
            return fin._emitir_cobranca_online_bruto(
                {"gateway_pagamento": "infinitepay", "infinitepay_handle": "$teste"}, "PIX",
                nome="Fulano", cpf=None, email=None, telefone=None,
                valor=35.0, vencimento="2026-10-10", descricao="Mensalidade",
                origem="mensalidade", registro_id=999999,
            )
    finally:
        ip.InfinitePayClient = original


def main():
    print("\nBaixa automática: a cobrança precisa nascer sabendo para onde avisar\n")

    print("A URL pública funciona dentro e fora de request")
    with app.app_context():
        fora = url_publica("financeiro.webhook_infinitepay")
    with app.test_request_context("/", base_url="https://rmservicosnet.com.br"):
        dentro = url_publica("financeiro.webhook_infinitepay")
    checar("1. fora de request (o caso da régua) a URL é montada", bool(fora), repr(fora))
    checar("2. dentro de request também", bool(dentro), repr(dentro))
    checar("3. as duas são a mesma URL — o gateway não vê diferença",
           fora == dentro, f"{fora!r} != {dentro!r}")
    checar("4. é absoluta e https", str(fora).startswith("https://"), repr(fora))
    with app.app_context():
        com_arg = url_publica("financeiro.sumup_retorno", ref="mensalidade-1")
    checar("5. parâmetros de rota continuam indo na URL",
           "ref=mensalidade-1" in str(com_arg), repr(com_arg))

    print("\nA cobrança criada fora de request leva os dois caminhos de volta")
    r = _emitir_sem_request()
    env = _EspiaoInfinitePay.ultimo
    checar("6. a emissão fora de request não quebra", bool(r and r.get("boleto_url")))
    checar("7. o link vai com webhook_url — era isto que faltava",
           bool(env.get("webhook_url")), repr(env.get("webhook_url")))
    from urllib.parse import urlsplit, parse_qs
    from blueprints.financeiro.routes import _assinatura_confere
    _wh = urlsplit(str(env.get("webhook_url") or ""))
    checar("8. o webhook aponta para a nossa rota de webhook",
           _wh.path == "/financeiro/webhook/infinitepay", repr(env.get("webhook_url")))
    # O corpo que o gateway envia não é assinado; quem assina somos nós, na URL.
    with app.app_context():
        _tok = (parse_qs(_wh.query).get("k") or [""])[0]
        checar("8b. a URL leva o token que prova a origem do aviso",
               _assinatura_confere(env.get("order_nsu"), _tok), repr(_tok))
    checar("9. o link também vai com redirect_url (a segunda via de baixa)",
           str(env.get("redirect_url") or "").endswith("/financeiro/pagamento/infinitepay/retorno"),
           repr(env.get("redirect_url")))
    checar("10. a referência do pedido continua sendo origem-id",
           env.get("order_nsu") == "mensalidade-999999", repr(env.get("order_nsu")))

    print("\nA página de retorno é do pagador: pública e desconfiada")
    cli = app.test_client()
    r1 = cli.get("/financeiro/pagamento/infinitepay/retorno")
    checar("11. abre sem login (quem paga não tem conta)", r1.status_code == 200,
           str(r1.status_code))
    h1 = r1.get_data(as_text=True)
    checar("12. sem confirmação, não diz que foi pago",
           "processamento" in h1 and "confirmado" not in h1)
    r2 = cli.get("/financeiro/pagamento/infinitepay/retorno"
                 "?order_nsu=mensalidade-999999&slug=x&transaction_nsu=y")
    checar("13. parâmetro forjado na URL não vira baixa",
           "confirmado" not in r2.get_data(as_text=True))

    print("\nA baixa automática não inventa pagamento")
    from blueprints.financeiro.routes import _infinitepay_confirmar, _academia_da_cobranca
    with app.app_context():
        pago, origem, rid = _infinitepay_confirmar("mensalidade-999999", "", "")
    checar("14. sem slug/transaction_nsu não há confirmação", pago is False)
    with app.app_context():
        pago2, _, _ = _infinitepay_confirmar("lixo-sem-formato", "a", "b")
    checar("15. referência fora do padrão é recusada", pago2 is False)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT ma.id, a.id_academia FROM mensalidade_aluno ma
                       JOIN alunos a ON a.id = ma.aluno_id
                       WHERE a.id_academia IS NOT NULL ORDER BY ma.id DESC LIMIT 1""")
        amostra = cur.fetchone()
        if amostra:
            with app.app_context():
                achada = _academia_da_cobranca("mensalidade", amostra["id"])
            checar("16. a academia dona da cobrança é encontrada (é dela o handle)",
                   achada == amostra["id_academia"], f"{achada} != {amostra['id_academia']}")
        cur.execute("SELECT COUNT(*) n FROM mensalidade_aluno WHERE id = 999999")
        checar("17. o ensaio não criou nem alterou cobrança", cur.fetchone()["n"] == 0)
    finally:
        cur.close()
        conn.close()

    print("\n" + ("TUDO PASSOU" if not _falhas else f"FALHARAM {len(_falhas)}: " + "; ".join(_falhas)))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
