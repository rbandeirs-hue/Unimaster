"""
Integração com a InfinitePay (Checkout / Link de pagamento).

Diferente de Asaas/Mercado Pago, a InfinitePay trabalha com LINK de checkout
hospedado: cria-se um link e o aluno escolhe PIX/cartão na página da InfinitePay.
Não há QR Code embutido — o aluno é direcionado ao link.

Configuração POR ACADEMIA (tabela academias):
  - infinitepay_handle : a "InfiniteTag" (handle) da conta

Confirmação de pagamento: via webhook (campo order_nsu) que a InfinitePay
envia para a URL informada na criação do link.

Docs: https://www.infinitepay.io/desenvolvedores
"""
import requests

TIMEOUT = 25
LINKS_URL = "https://api.checkout.infinitepay.io/links"


class InfinitePayClient:
    """Cliente InfinitePay vinculado ao handle (InfiniteTag) de uma academia."""

    def __init__(self, handle):
        self.handle = (handle or "").strip().lstrip("$").lstrip("@")

    @property
    def configurado(self):
        return bool(self.handle)

    @staticmethod
    def _formatar_telefone(telefone):
        """Normaliza o telefone para o formato +55DDDNXXXXXXXX esperado pela InfinitePay.
        Retorna None se não houver um número BR plausível (10–11 dígitos)."""
        tel = "".join(filter(str.isdigit, str(telefone or "")))
        if tel.startswith("55") and len(tel) > 11:
            tel = tel[2:]
        if 10 <= len(tel) <= 11:
            return "+55" + tel
        return None

    def criar_link(self, valor, descricao, order_nsu, webhook_url=None, redirect_url=None,
                   nome=None, email=None, telefone=None, endereco=None):
        """Cria um link de checkout. Retorna dict normalizado:
        {payment_id, tipo, boleto_url, pix_qrcode, pix_copia_cola}
        onde tipo='LINK' e boleto_url contém o link de pagamento.

        nome/email/telefone, quando informados, são enviados no objeto `customer`
        para que a tela de checkout da InfinitePay já venha com os dados do pagador.
        endereco (dict com cep/street/neighborhood/number/complement) é enviado no
        objeto `address`, pré-preenchendo o endereço (evita pedir o CEP no checkout)."""
        if not self.handle:
            raise RuntimeError("Handle (InfiniteTag) da InfinitePay não configurado para esta academia.")
        # Preço em centavos
        preco_centavos = int(round(float(valor) * 100))
        payload = {
            "handle": self.handle,
            "order_nsu": str(order_nsu),
            "items": [{
                "quantity": 1,
                "price": preco_centavos,
                "description": (descricao or "Cobrança")[:255],
            }],
        }
        # Pré-preenchimento dos dados do pagador (responsável financeiro / aluno)
        customer = {}
        if nome and str(nome).strip():
            customer["name"] = str(nome).strip()[:120]
        if email and "@" in str(email):
            customer["email"] = str(email).strip()
        tel_fmt = self._formatar_telefone(telefone)
        if tel_fmt:
            customer["phone_number"] = tel_fmt
        if customer:
            payload["customer"] = customer
        # Pré-preenchimento do endereço (mesmo do aluno) — evita pedir o CEP no checkout
        if endereco:
            addr = {}
            cep = "".join(filter(str.isdigit, str(endereco.get("cep") or "")))
            if len(cep) == 8:
                addr["cep"] = cep
            # Sem city/state o checkout continua pedindo o endereço ao pagador,
            # mesmo com o CEP preenchido — por isso os dois vão junto.
            for chave_api, chave_in in (("street", "street"), ("neighborhood", "neighborhood"),
                                        ("number", "number"), ("complement", "complement"),
                                        ("city", "city"), ("state", "state")):
                val = str(endereco.get(chave_in) or "").strip()
                if val:
                    addr[chave_api] = val[:120]
            # Só envia o endereço se houver CEP válido (campo-chave do checkout)
            if "cep" in addr:
                payload["address"] = addr
        if redirect_url:
            payload["redirect_url"] = redirect_url
        if webhook_url:
            payload["webhook_url"] = webhook_url
        r = requests.post(LINKS_URL, json=payload, timeout=TIMEOUT)
        try:
            j = r.json() or {}
        except Exception:
            j = {}
        # A resposta traz o link de checkout — o campo pode variar entre versões.
        data = j.get("data") if isinstance(j.get("data"), dict) else {}
        link = (j.get("url") or j.get("link") or j.get("payment_url")
                or data.get("url") or data.get("link") or data.get("payment_url"))
        if not link:
            raise RuntimeError(f"Falha ao criar link na InfinitePay: {j or r.text[:300]}")
        return {
            "payment_id": str(order_nsu),
            "tipo": "LINK",
            "boleto_url": link,
            "pix_qrcode": None,
            "pix_copia_cola": None,
        }
