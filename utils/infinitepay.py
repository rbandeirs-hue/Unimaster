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

    def criar_link(self, valor, descricao, order_nsu, webhook_url=None, redirect_url=None):
        """Cria um link de checkout. Retorna dict normalizado:
        {payment_id, tipo, boleto_url, pix_qrcode, pix_copia_cola}
        onde tipo='LINK' e boleto_url contém o link de pagamento."""
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
        link = (j.get("url") or j.get("link") or j.get("payment_url")
                or (j.get("data") or {}).get("url") if isinstance(j.get("data"), dict) else None)
        if not link:
            raise RuntimeError(f"Falha ao criar link na InfinitePay: {j or r.text[:300]}")
        return {
            "payment_id": str(order_nsu),
            "tipo": "LINK",
            "boleto_url": link,
            "pix_qrcode": None,
            "pix_copia_cola": None,
        }
