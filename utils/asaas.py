"""
Integração com o gateway Asaas (PIX / Boleto).

A configuração é POR ACADEMIA: cada academia usa a sua própria conta Asaas.
As credenciais (chave de API e ambiente) ficam na tabela `academias`:
  - asaas_api_key  : chave de API (access_token) da conta Asaas da academia
  - asaas_ambiente : 'sandbox' (padrão) ou 'production'

Uso:
    from utils.asaas import AsaasClient
    cli = AsaasClient(api_key, ambiente)
    if cli.configurado:
        cid = cli.criar_ou_obter_cliente(nome, cpf, email, telefone)
        pay = cli.criar_cobranca(cid, valor, vencimento, "PIX")

Docs: https://docs.asaas.com/
"""
import re
import requests

TIMEOUT = 25


def _so_digitos(v):
    return re.sub(r"\D", "", str(v or ""))


class AsaasClient:
    """Cliente Asaas vinculado às credenciais de uma academia."""

    def __init__(self, api_key, ambiente="sandbox"):
        self.api_key = (api_key or "").strip()
        self.ambiente = (ambiente or "sandbox").strip().lower()

    @property
    def configurado(self):
        """True se a academia tem uma chave de API definida."""
        return bool(self.api_key)

    def _base_url(self):
        if self.ambiente in ("prod", "production", "producao", "produção"):
            return "https://api.asaas.com/v3"
        return "https://sandbox.asaas.com/api/v3"

    def _headers(self):
        if not self.api_key:
            raise RuntimeError("Chave de API do Asaas não configurada para esta academia.")
        return {"access_token": self.api_key, "Content-Type": "application/json"}

    def criar_ou_obter_cliente(self, nome, cpf, email=None, telefone=None):
        """Cria (ou reaproveita) um cliente no Asaas pelo CPF. Retorna o customer id."""
        cpf_d = _so_digitos(cpf)
        if not cpf_d:
            raise RuntimeError("CPF do aluno é obrigatório para gerar cobrança no Asaas.")
        h = self._headers()
        # Tenta localizar cliente existente pelo CPF
        r = requests.get(f"{self._base_url()}/customers", headers=h, params={"cpfCnpj": cpf_d}, timeout=TIMEOUT)
        if r.ok:
            data = r.json() or {}
            if data.get("data"):
                return data["data"][0]["id"]
        payload = {"name": nome or "Aluno", "cpfCnpj": cpf_d}
        if email:
            payload["email"] = email
        tel = _so_digitos(telefone)
        if tel:
            payload["mobilePhone"] = tel
        r = requests.post(f"{self._base_url()}/customers", headers=h, json=payload, timeout=TIMEOUT)
        j = r.json() or {}
        if not j.get("id"):
            raise RuntimeError(f"Falha ao criar cliente no Asaas: {j}")
        return j["id"]

    def criar_cobranca(self, customer_id, valor, vencimento, billing_type="PIX", descricao=None, external_reference=None):
        """Cria uma cobrança (payment). billing_type: 'PIX' ou 'BOLETO'. Retorna o JSON do payment."""
        payload = {
            "customer": customer_id,
            "billingType": "BOLETO" if str(billing_type).upper() == "BOLETO" else "PIX",
            "value": round(float(valor), 2),
            "dueDate": vencimento.strftime("%Y-%m-%d") if hasattr(vencimento, "strftime") else str(vencimento),
        }
        if descricao:
            payload["description"] = descricao[:500]
        if external_reference is not None:
            payload["externalReference"] = str(external_reference)
        r = requests.post(f"{self._base_url()}/payments", headers=self._headers(), json=payload, timeout=TIMEOUT)
        j = r.json() or {}
        if not j.get("id"):
            raise RuntimeError(f"Falha ao criar cobrança no Asaas: {j}")
        return j

    def obter_pix_qrcode(self, payment_id):
        """Retorna {encodedImage, payload, ...} do QR Code PIX da cobrança."""
        r = requests.get(f"{self._base_url()}/payments/{payment_id}/pixQrCode", headers=self._headers(), timeout=TIMEOUT)
        return r.json() or {}

    def criar_assinatura_recorrente(self, valor, descricao, external_reference=None,
                                    nome=None, ciclo="MONTHLY", metodo="cartao"):
        """Cria um LINK de pagamento recorrente — o aluno se cadastra uma vez na página
        hospedada do Asaas e a cobrança se repete automaticamente a cada ciclo.
        metodo='cartao' (débito automático no cartão) ou 'pix' (PIX recorrente).
        Retorna {subscription_id, url}.

        Usa paymentLinks com chargeType=RECURRENT (não trafega dados de cartão pelo
        nosso servidor → fora do escopo PCI)."""
        billing = "PIX" if str(metodo).lower() == "pix" else "CREDIT_CARD"
        payload = {
            "name": (nome or descricao or "Mensalidade recorrente")[:100],
            "billingType": billing,
            "chargeType": "RECURRENT",
            "subscriptionCycle": (ciclo or "MONTHLY").upper(),
            "value": round(float(valor), 2),
            "description": (descricao or "Mensalidade recorrente")[:500],
            "dueDateLimitDays": 7,
        }
        if external_reference is not None:
            payload["externalReference"] = str(external_reference)
        r = requests.post(f"{self._base_url()}/paymentLinks", headers=self._headers(), json=payload, timeout=TIMEOUT)
        j = r.json() or {}
        if not j.get("id") or not j.get("url"):
            raise RuntimeError(f"Falha ao criar assinatura recorrente no Asaas: {j}")
        return {"subscription_id": j["id"], "url": j["url"]}
