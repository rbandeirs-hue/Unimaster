"""O webhook de pagamento não pode acreditar em quem bate na porta.

O endpoint é público e o corpo que a InfinitePay envia não é assinado. Aceitar
o que chega significa que qualquer um, com um `order_nsu` adivinhado — e os
ids são sequenciais —, quitaria a mensalidade de outro aluno.

A trava não depende de conhecer o formato do corpo: quem monta a URL de
callback somos nós, na emissão da cobrança. Vai nela um token derivado da
referência com o SECRET_KEY. Duas provas são aceitas, e basta uma:

  * o token `k` na URL;
  * a resposta da própria API da InfinitePay (payment_check), quando o corpo
    trouxer slug e transaction_nsu.

Sem nenhuma, não há baixa — só registro no log.

Nenhum cenário aqui encosta em cobrança real: a função de baixa é trocada por
um espião, e a referência usada é de um registro que não existe.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_webhook_assinatura.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                      # noqa: E402
from config import get_db_connection                     # noqa: E402
from blueprints.financeiro import routes as fin          # noqa: E402

# Id que não existe: mesmo se a trava falhasse, não há o que baixar.
REF = "mensalidade-999999"
_falhas = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


class _Espiao:
    """Fica no lugar da baixa: registra a chamada e não grava nada."""

    def __init__(self):
        self.chamadas = []

    def __call__(self, origem, rid, valor, gateway):
        self.chamadas.append((origem, rid, valor, gateway))


def _postar(corpo, token=None):
    """POST no webhook com a baixa e a confirmação substituídas por espiões."""
    espiao = _Espiao()
    orig_baixa = fin._baixar_cobranca_paga
    orig_matric = fin._baixar_matricula_paga
    orig_conf = fin._infinitepay_confirmar
    fin._baixar_cobranca_paga = espiao
    fin._baixar_matricula_paga = lambda **kw: espiao("precadastro", kw.get("precad_id"), None, "x")
    # Sem rede: a API responderia "não pago" para uma referência inexistente.
    fin._infinitepay_confirmar = lambda *a, **k: (False, None, None)
    try:
        url = "/financeiro/webhook/infinitepay" + (f"?k={token}" if token else "")
        r = app.test_client().post(url, json=corpo)
        return r, espiao
    finally:
        fin._baixar_cobranca_paga = orig_baixa
        fin._baixar_matricula_paga = orig_matric
        fin._infinitepay_confirmar = orig_conf


def main():
    print("\nO webhook só dá baixa no que consegue provar\n")

    with app.app_context():
        token = fin._assinatura_retorno(REF)
        outro = fin._assinatura_retorno("mensalidade-1")

    print("O token da URL")
    with app.app_context():
        checar("1. o token é estável: emitir e conferir dão o mesmo",
               token == fin._assinatura_retorno(REF) and len(token) == 24, token)
        checar("2. referências diferentes dão tokens diferentes", token != outro)
        checar("3. o token confere com a própria referência",
               fin._assinatura_confere(REF, token))
        checar("4. token de outra cobrança não serve",
               not fin._assinatura_confere(REF, outro))
        checar("5. token vazio não passa", not fin._assinatura_confere(REF, ""))
        checar("6. token adivinhado não passa",
               not fin._assinatura_confere(REF, "0" * 24))

    print("\nO POST sem prova nenhuma")
    r, espiao = _postar({"order_nsu": REF})
    checar("7. responde 200 (não dá pista a quem sonda)", r.status_code == 200)
    checar("8. nenhuma baixa é dada", espiao.chamadas == [], str(espiao.chamadas))

    print("\nO POST com o token certo na URL")
    r, espiao = _postar({"order_nsu": REF, "paid_amount": 3500}, token=token)
    checar("9. responde 200", r.status_code == 200)
    checar("10. a baixa é chamada para a cobrança da referência",
           len(espiao.chamadas) == 1 and espiao.chamadas[0][0] == "mensalidade"
           and espiao.chamadas[0][1] == 999999, str(espiao.chamadas))
    checar("11. o gateway registrado é a InfinitePay",
           espiao.chamadas and espiao.chamadas[0][3] == "InfinitePay")

    print("\nO POST com token de OUTRA cobrança (a tentativa de fraude)")
    r, espiao = _postar({"order_nsu": REF}, token=outro)
    checar("12. não dá baixa", espiao.chamadas == [], str(espiao.chamadas))

    print("\nReferência malformada")
    for corpo in ({}, {"order_nsu": "semhifen"}, {"order_nsu": "outra-coisa-9"},
                  {"order_nsu": "mensalidade-abc"}):
        _r, _e = _postar(corpo, token="qualquer")
        if _e.chamadas:
            checar(f"13. {corpo} não vira baixa", False, str(_e.chamadas))
            break
    else:
        checar("13. corpo sem referência válida nunca vira baixa", True)

    print("\nO valor anunciado não passa do valor cobrado")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT id, valor FROM mensalidade_aluno
                       WHERE valor > 0 ORDER BY id DESC LIMIT 1""")
        amostra = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if amostra:
        devido = float(amostra["valor"])
        with app.app_context():
            teto = fin._valor_plausivel("mensalidade", amostra["id"], devido * 10)
            exato = fin._valor_plausivel("mensalidade", amostra["id"], devido)
            parcial = fin._valor_plausivel("mensalidade", amostra["id"], devido / 2)
            nulo = fin._valor_plausivel("mensalidade", amostra["id"], 0)
        checar("14. valor maior que a dívida é cortado no valor da dívida",
               teto == devido, f"{teto} != {devido}")
        checar("15. valor igual passa", exato == devido)
        checar("16. valor menor passa (pagamento parcial é caso real)",
               parcial == devido / 2)
        checar("17. valor zerado vira None (usa o valor da cobrança)", nulo is None)

    print("\n" + ("TUDO PASSOU" if not _falhas else f"FALHARAM {len(_falhas)}: " + "; ".join(_falhas)))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
