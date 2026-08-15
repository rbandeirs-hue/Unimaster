"""
Integração com a SumUp (Online Payments API).

Diferente de Asaas/Mercado Pago/EFÍ, a SumUp NÃO devolve um QR/linha digitável
de PIX/boleto por uma chamada servidor-a-servidor. O modelo dela é:

  1. O servidor cria um "checkout" (POST /v0.1/checkouts) e recebe um checkout_id.
  2. Uma página hospedada por nós carrega o WIDGET de cartão da SumUp com esse
     checkout_id. O widget mostra cartão e, se habilitados na conta, PIX/boleto.
  3. A confirmação chega por webhook (return_url) — validamos consultando o
     checkout (GET /v0.1/checkouts/{id}) e conferindo status == 'PAID'.

Por isso, no fluxo do sistema, a SumUp se comporta como um gateway de LINK
(tipo='LINK'), onde o "link" é a nossa página hospedada.

Autenticação (por academia, tabela academias):
  - sumup_api_key       : chave SECRETA (sup_sk_...) usada como Bearer no servidor.
  - sumup_merchant_code : merchant code da conta (ex.: MXXXXXX), obrigatório no checkout.

Recorrência: cartão salvo. O primeiro checkout usa um customer_id e
purpose='SETUP_RECURRING_PAYMENT'; nas mensalidades seguintes cobramos com
POST /v0.1/checkouts (payment_type='recurring') reutilizando o token do cartão.
PIX/boleto recorrente não existe na SumUp.

Docs: https://developer.sumup.com/api
"""
import requests

TIMEOUT = 30
BASE_URL = "https://api.sumup.com"

# Scopes necessários para criar/processar cobranças online em nome do merchant.
# 'payments' exige verificação/aprovação manual da SumUp para o app OAuth.
OAUTH_SCOPES = "payments transactions.history user.profile_readonly"


def oauth_authorize_url(client_id, redirect_uri, state, scopes=OAUTH_SCOPES):
    """Monta a URL de autorização para o merchant conectar a conta (fluxo OAuth code)."""
    from urllib.parse import urlencode
    q = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
    })
    return f"{BASE_URL}/authorize?{q}"


def oauth_exchange_code(client_id, client_secret, code, redirect_uri):
    """Troca o authorization code por tokens. Retorna o JSON (access_token,
    refresh_token, expires_in, token_type, scope) ou levanta RuntimeError."""
    r = requests.post(f"{BASE_URL}/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=TIMEOUT)
    j = {}
    try:
        j = r.json() or {}
    except Exception:
        pass
    if not r.ok or not j.get("access_token"):
        raise RuntimeError(f"Falha no OAuth SumUp (code): {j.get('error_description') or j.get('error') or r.text[:200]}")
    return j


def oauth_refresh(client_id, client_secret, refresh_token):
    """Renova o access_token com o refresh_token. Retorna o JSON de tokens."""
    r = requests.post(f"{BASE_URL}/token", data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=TIMEOUT)
    j = {}
    try:
        j = r.json() or {}
    except Exception:
        pass
    if not r.ok or not j.get("access_token"):
        raise RuntimeError(f"Falha ao renovar token SumUp: {j.get('error_description') or j.get('error') or r.text[:200]}")
    return j


def obter_merchant_code(access_token):
    """Lê o merchant_code do merchant conectado (GET /v0.1/me)."""
    try:
        r = requests.get(f"{BASE_URL}/v0.1/me",
                         headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT)
        if not r.ok:
            return None
        j = r.json() or {}
    except Exception:
        return None
    mp = j.get("merchant_profile") or {}
    return mp.get("merchant_code") or j.get("merchant_code")


class SumUpClient:
    """Cliente SumUp vinculado às credenciais de uma academia."""

    def __init__(self, api_key, merchant_code=None, ambiente="producao"):
        self.api_key = (api_key or "").strip()
        self.merchant_code = (merchant_code or "").strip()
        self.ambiente = (ambiente or "producao").strip().lower()

    @property
    def configurado(self):
        return bool(self.api_key and self.merchant_code)

    def _headers(self, extra=None):
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    # ------------------------------------------------------------------ checkout
    def criar_checkout(self, valor, descricao, checkout_reference, *,
                       return_url=None, redirect_url=None, moeda="BRL",
                       customer_id=None, purpose=None, email=None):
        """Cria um checkout na SumUp e retorna o JSON de resposta (inclui 'id').
        `checkout_reference` é a nossa referência (ex.: 'mensalidade-123').
        `return_url` recebe as notificações (webhook) da SumUp.
        `redirect_url` é para onde o navegador volta após o pagamento."""
        if not self.configurado:
            raise RuntimeError("SumUp não configurado (chave secreta + merchant code) para esta academia.")
        payload = {
            "checkout_reference": str(checkout_reference)[:90],
            "amount": round(float(valor), 2),
            "currency": moeda,
            "merchant_code": self.merchant_code,
            "description": (descricao or "Cobrança")[:255],
        }
        if return_url:
            payload["return_url"] = return_url
        if redirect_url:
            payload["redirect_url"] = redirect_url
        if customer_id:
            payload["customer_id"] = str(customer_id)
        if purpose:
            payload["purpose"] = purpose
        r = requests.post(f"{BASE_URL}/v0.1/checkouts", json=payload,
                          headers=self._headers(), timeout=TIMEOUT)
        try:
            j = r.json() or {}
        except Exception:
            j = {}
        if r.status_code not in (200, 201) or not j.get("id"):
            msg = j.get("message") or (r.text[:300] if r.text else "erro desconhecido")
            raise RuntimeError(f"Falha ao criar checkout SumUp: {msg}")
        return j

    def obter_checkout(self, checkout_id):
        """Consulta um checkout. Retorna o JSON (com 'status': PENDING/PAID/FAILED) ou {}."""
        if not self.api_key or not checkout_id:
            return {}
        r = requests.get(f"{BASE_URL}/v0.1/checkouts/{checkout_id}",
                         headers=self._headers(), timeout=TIMEOUT)
        try:
            return r.json() or {} if r.ok else {}
        except Exception:
            return {}

    def checkout_pago(self, checkout_id):
        """True se o checkout está pago (status PAID)."""
        j = self.obter_checkout(checkout_id)
        return str(j.get("status") or "").upper() == "PAID"

    def listar_metodos(self, checkout_id):
        """Métodos de pagamento disponíveis para o checkout (['card','pix','boleto',...]).
        A SumUp diz: trate isto como a fonte de verdade do que a conta oferece."""
        if not self.api_key or not checkout_id:
            return []
        try:
            r = requests.get(f"{BASE_URL}/v0.1/checkouts/{checkout_id}/payment-methods",
                             headers=self._headers(), timeout=TIMEOUT)
            if not r.ok:
                return []
            j = r.json() or []
        except Exception:
            return []
        # A resposta pode vir como lista, {"items":[...]} (nível checkout) ou
        # {"available_payment_methods":[...]} (nível merchant). Itens = str ou {id:...}.
        if isinstance(j, dict):
            lista = j.get("items") or j.get("available_payment_methods") or []
        elif isinstance(j, list):
            lista = j
        else:
            lista = []
        out = []
        for it in lista:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict) and it.get("id"):
                out.append(str(it["id"]))
        return out

    def listar_metodos_merchant(self, valor=None, moeda="BRL"):
        """Métodos disponíveis a nível de conta (fallback quando o checkout lista poucos).
        Útil porque o endpoint por checkout às vezes restringe métodos (ex.: só card)."""
        if not self.api_key or not self.merchant_code:
            return []
        try:
            params = {}
            if valor:
                params = {"amount": round(float(valor), 2), "currency": moeda}
            r = requests.get(f"{BASE_URL}/v0.1/merchants/{self.merchant_code}/payment-methods",
                             headers=self._headers(), params=params, timeout=TIMEOUT)
            if not r.ok:
                return []
            j = r.json() or {}
        except Exception:
            return []
        out = []
        for it in (j.get("available_payment_methods") or j.get("items") or []):
            if isinstance(it, dict) and it.get("id"):
                out.append(str(it["id"]))
            elif isinstance(it, str):
                out.append(it)
        return out

    def processar_apm(self, checkout_id, payment_type, *, nome=None, email=None,
                      telefone=None, cpf=None):
        """Processa o checkout com um método alternativo (pix/qr_code_pix/boleto) e
        retorna o artifact normalizado:
        {tipo, pix_copia_cola, pix_qrcode_url, boleto_url, boleto_barcode, status}."""
        if not self.configurado:
            raise RuntimeError("SumUp não configurado.")
        pd = {}
        if nome:
            pd["first_name"] = str(nome).strip()[:120]
        if email and "@" in str(email):
            pd["email"] = str(email).strip()
        tax = "".join(filter(str.isdigit, str(cpf or "")))
        if tax:
            pd["tax_id"] = tax
        body = {"payment_type": payment_type}
        if pd:
            body["personal_details"] = pd
        r = requests.put(f"{BASE_URL}/v0.1/checkouts/{checkout_id}", json=body,
                         headers=self._headers(), timeout=TIMEOUT)
        try:
            j = r.json() or {}
        except Exception:
            j = {}
        if r.status_code not in (200, 201):
            msg = j.get("message") or (r.text[:300] if r.text else "erro")
            raise RuntimeError(f"Falha ao processar {payment_type} na SumUp: {msg}")
        return self._normalizar_artifact(payment_type, j)

    @staticmethod
    def _normalizar_artifact(payment_type, j):
        """Extrai o código PIX / QR / boleto do JSON de processamento."""
        out = {"tipo": payment_type, "status": str(j.get("status") or "").upper(),
               "pix_copia_cola": None, "pix_qrcode_url": None,
               "boleto_url": None, "boleto_barcode": None}
        bloco = j.get(payment_type) if isinstance(j.get(payment_type), dict) else {}
        artefatos = bloco.get("artefacts") or bloco.get("artifacts") or []
        if payment_type in ("pix", "qr_code_pix"):
            for a in artefatos:
                nome = (a.get("name") or "").lower()
                if nome == "code":
                    out["pix_copia_cola"] = a.get("content") or a.get("location")
                elif nome in ("barcode", "qr_code", "qrcode"):
                    out["pix_qrcode_url"] = a.get("location")
        elif payment_type == "boleto":
            out["boleto_barcode"] = bloco.get("barcode")
            out["boleto_url"] = bloco.get("url")
            for a in artefatos:
                if (a.get("name") or "").lower() == "invoice":
                    out["boleto_url"] = a.get("location") or out["boleto_url"]
        return out

    # ------------------------------------------------------------------ customer
    def criar_ou_obter_cliente(self, customer_id, *, nome=None, email=None, telefone=None):
        """Garante um customer na SumUp (usado para cartão salvo/recorrência).
        `customer_id` é um id estável nosso (ex.: 'aluno-12'). Retorna o customer_id."""
        if not self.api_key:
            raise RuntimeError("SumUp não configurado.")
        cid = str(customer_id)
        body = {"customer_id": cid, "personal_details": {}}
        if nome:
            body["personal_details"]["first_name"] = str(nome).strip()[:120]
        if email and "@" in str(email):
            body["personal_details"]["email"] = str(email).strip()
        # POST cria; se já existir a SumUp responde 409 — tratamos como sucesso.
        r = requests.post(f"{BASE_URL}/v0.1/customers", json=body,
                          headers=self._headers(), timeout=TIMEOUT)
        if r.status_code in (200, 201, 409):
            return cid
        try:
            msg = (r.json() or {}).get("message") or r.text[:200]
        except Exception:
            msg = r.text[:200]
        raise RuntimeError(f"Falha ao criar cliente SumUp: {msg}")

    def listar_payment_instruments(self, customer_id):
        """Cartões salvos (tokens) do cliente. Lista de dicts com 'token', 'active', etc."""
        if not self.api_key or not customer_id:
            return []
        try:
            r = requests.get(f"{BASE_URL}/v0.1/customers/{customer_id}/payment-instruments",
                             headers=self._headers(), timeout=TIMEOUT)
            if not r.ok:
                return []
            j = r.json()
        except Exception:
            return []
        return j if isinstance(j, list) else []

    def token_cartao_salvo(self, customer_id):
        """Token do primeiro cartão salvo ATIVO do cliente (ou None)."""
        for pi in self.listar_payment_instruments(customer_id):
            if isinstance(pi, dict) and pi.get("token") and pi.get("active", True):
                return pi["token"]
        return None

    def cobrar_recorrente(self, customer_id, valor, descricao, checkout_reference, *, moeda="BRL"):
        """Cobra usando o cartão salvo do cliente (merchant-initiated).
        Cria um checkout e processa com payment_type='recurring' + token do cartão salvo.
        Requer que o cliente já tenha um cartão tokenizado (via SETUP_RECURRING_PAYMENT)."""
        if not self.configurado:
            raise RuntimeError("SumUp não configurado.")
        token = self.token_cartao_salvo(customer_id)
        if not token:
            raise RuntimeError("Cliente SumUp sem cartão salvo — a assinatura ainda não foi ativada com um pagamento.")
        chk = self.criar_checkout(valor, descricao, checkout_reference,
                                  moeda=moeda, customer_id=customer_id)
        checkout_id = chk.get("id")
        r = requests.put(
            f"{BASE_URL}/v0.1/checkouts/{checkout_id}",
            json={"payment_type": "recurring", "customer_id": str(customer_id), "token": token},
            headers=self._headers(), timeout=TIMEOUT,
        )
        try:
            j = r.json() or {}
        except Exception:
            j = {}
        j.setdefault("id", checkout_id)
        return j
