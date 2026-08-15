"""
Integração com o Mercado Pago (Checkout API — PIX / Boleto).

Configuração POR ACADEMIA (tabela academias):
  - mercadopago_access_token : Access Token da conta (produção ou teste)

Uso:
    from utils.mercadopago import MercadoPagoClient
    cli = MercadoPagoClient(access_token)
    if cli.configurado:
        r = cli.criar_cobranca("PIX", valor, vencimento, nome, cpf, email,
                               descricao="...", external_reference="ma-123")

Docs: https://www.mercadopago.com.br/developers/pt/docs/checkout-api
"""
import re
import requests

TIMEOUT = 25
BASE_URL = "https://api.mercadopago.com"


def _so_digitos(v):
    return re.sub(r"\D", "", str(v or ""))


class MercadoPagoClient:
    """Cliente Mercado Pago vinculado ao access token de uma academia."""

    def __init__(self, access_token):
        self.access_token = (access_token or "").strip()

    @property
    def configurado(self):
        return bool(self.access_token)

    def _headers(self, idem_key=None):
        if not self.access_token:
            raise RuntimeError("Access Token do Mercado Pago não configurado para esta academia.")
        h = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        if idem_key:
            h["X-Idempotency-Key"] = str(idem_key)
        return h

    def criar_cobranca(self, tipo, valor, vencimento, nome, cpf, email=None,
                       telefone=None, descricao=None, external_reference=None):
        """Cria um pagamento PIX ou BOLETO. Retorna dict normalizado:
        {payment_id, tipo, boleto_url, pix_qrcode, pix_copia_cola}."""
        tipo = "BOLETO" if str(tipo).upper() == "BOLETO" else "PIX"
        cpf_d = _so_digitos(cpf)
        nome = (nome or "Aluno").strip()
        partes = nome.split(" ", 1)
        first_name = partes[0]
        last_name = partes[1] if len(partes) > 1 else "."
        payload = {
            "transaction_amount": round(float(valor), 2),
            "description": (descricao or "Cobrança")[:255],
            "payment_method_id": "bolbradesco" if tipo == "BOLETO" else "pix",
            "payer": {
                "email": (email or "").strip() or "sem-email@unimaster.app",
                "first_name": first_name,
                "last_name": last_name,
            },
        }
        if cpf_d:
            payload["payer"]["identification"] = {"type": "CPF", "number": cpf_d}
        if external_reference is not None:
            payload["external_reference"] = str(external_reference)
        if vencimento is not None:
            try:
                dia = vencimento.strftime("%Y-%m-%d") if hasattr(vencimento, "strftime") else str(vencimento)[:10]
                payload["date_of_expiration"] = f"{dia}T23:59:59.000-03:00"
            except Exception:
                pass
        idem = f"{external_reference or 'mp'}-{tipo}"
        r = requests.post(f"{BASE_URL}/v1/payments", headers=self._headers(idem), json=payload, timeout=TIMEOUT)
        j = r.json() or {}
        if not j.get("id"):
            raise RuntimeError(f"Falha ao criar cobrança no Mercado Pago: {j.get('message') or j}")
        poi = (j.get("point_of_interaction") or {}).get("transaction_data") or {}
        td = j.get("transaction_details") or {}
        return {
            "payment_id": str(j["id"]),
            "tipo": tipo,
            "boleto_url": td.get("external_resource_url") if tipo == "BOLETO" else None,
            "pix_qrcode": poi.get("qr_code_base64") if tipo == "PIX" else None,
            "pix_copia_cola": poi.get("qr_code") if tipo == "PIX" else None,
        }

    def status_pagamento(self, payment_id):
        """Consulta o status de um pagamento. Retorna a string de status (ex.: 'approved')."""
        r = requests.get(f"{BASE_URL}/v1/payments/{payment_id}", headers=self._headers(), timeout=TIMEOUT)
        j = r.json() or {}
        return j.get("status")

    def criar_assinatura_recorrente(self, valor, descricao, payer_email, back_url,
                                    external_reference=None, frequencia_meses=1):
        """Cria uma assinatura (preapproval) com cobrança recorrente no cartão.
        Retorna {subscription_id, url} — `url` é o init_point onde o aluno autoriza
        o cartão uma vez; o Mercado Pago debita automaticamente a cada período."""
        if not (payer_email or "").strip():
            raise RuntimeError("E-mail do pagador é obrigatório para assinatura no Mercado Pago.")
        payload = {
            "reason": (descricao or "Mensalidade recorrente")[:255],
            "payer_email": payer_email.strip(),
            "back_url": back_url,
            "status": "pending",
            "auto_recurring": {
                "frequency": int(frequencia_meses or 1),
                "frequency_type": "months",
                "transaction_amount": round(float(valor), 2),
                "currency_id": "BRL",
            },
        }
        if external_reference is not None:
            payload["external_reference"] = str(external_reference)
        idem = f"preapproval-{external_reference or 'mp'}"
        r = requests.post(f"{BASE_URL}/preapproval", headers=self._headers(idem), json=payload, timeout=TIMEOUT)
        j = r.json() or {}
        if not j.get("id"):
            raise RuntimeError(f"Falha ao criar assinatura no Mercado Pago: {j.get('message') or j}")
        url = j.get("init_point") or j.get("sandbox_init_point")
        if not url:
            raise RuntimeError(f"Mercado Pago não retornou o link de autorização: {j}")
        return {"subscription_id": str(j["id"]), "url": url}

    def status_preapproval(self, preapproval_id):
        """Consulta dados de uma assinatura (preapproval)."""
        r = requests.get(f"{BASE_URL}/preapproval/{preapproval_id}", headers=self._headers(), timeout=TIMEOUT)
        return r.json() or {}
