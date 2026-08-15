"""
Integração com o gateway EFÍ (Gerencianet) — API Pix.

Configuração POR ACADEMIA (tabela academias):
  - efi_client_id     : Client_Id da aplicação EFÍ
  - efi_client_secret : Client_Secret da aplicação EFÍ
  - efi_certificate   : certificado em PEM (cert + chave), convertido do .p12 fornecido
                        pela EFÍ (openssl pkcs12 -in cert.p12 -out cert.pem -nodes)
  - efi_pix_key       : chave Pix recebedora da conta EFÍ
  - efi_ambiente      : 'homologacao' (padrão) ou 'producao'

A API Pix da EFÍ exige certificado mTLS em todas as requisições. Geramos a cobrança
imediata (cob) e o QR Code; o aluno paga via Pix e a confirmação chega por webhook.

Docs: https://dev.efipay.com.br/docs/api-pix/
"""
import os
import re
import base64
import tempfile
import requests

TIMEOUT = 30


def _so_digitos(v):
    return re.sub(r"\D", "", str(v or ""))


class EfiClient:
    """Cliente EFÍ (API Pix) vinculado às credenciais de uma academia."""

    def __init__(self, client_id, client_secret, certificado_pem, chave_pix, ambiente="homologacao"):
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.certificado_pem = certificado_pem or ""
        self.chave_pix = (chave_pix or "").strip()
        self.ambiente = (ambiente or "homologacao").strip().lower()

    @property
    def configurado(self):
        return bool(self.client_id and self.client_secret and self.certificado_pem and self.chave_pix)

    def _base_url(self):
        if self.ambiente in ("prod", "producao", "produção", "production"):
            return "https://pix.api.efipay.com.br"
        return "https://pix-h.api.efipay.com.br"

    def _escrever_cert(self):
        """Grava o PEM num arquivo temporário (necessário para o mTLS do requests)."""
        fd, caminho = tempfile.mkstemp(suffix=".pem", prefix="efi_cert_")
        with os.fdopen(fd, "w") as f:
            f.write(self.certificado_pem)
        try:
            os.chmod(caminho, 0o600)
        except OSError:
            pass
        return caminho

    def _token(self, cert_path):
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = requests.post(
            f"{self._base_url()}/oauth/token",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json={"grant_type": "client_credentials"},
            cert=cert_path, timeout=TIMEOUT,
        )
        j = r.json() or {}
        if not j.get("access_token"):
            raise RuntimeError(f"Falha na autenticação EFÍ: {j or r.text[:300]}")
        return j["access_token"]

    def criar_cobranca_pix(self, valor, *, nome=None, cpf=None, descricao=None, external_reference=None,
                           expiracao=86400):
        """Cria uma cobrança imediata Pix (cob) e retorna dict normalizado:
        {payment_id, tipo, boleto_url, pix_qrcode, pix_copia_cola}."""
        if not self.configurado:
            raise RuntimeError("Credenciais da EFÍ incompletas (Client ID, Client Secret, certificado e chave Pix).")
        cert_path = self._escrever_cert()
        try:
            token = self._token(cert_path)
            h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            payload = {
                "calendario": {"expiracao": int(expiracao)},
                "valor": {"original": f"{float(valor):.2f}"},
                "chave": self.chave_pix,
            }
            cpf_d = _so_digitos(cpf)
            if cpf_d and len(cpf_d) == 11:
                payload["devedor"] = {"cpf": cpf_d, "nome": (nome or "Aluno")[:200]}
            if descricao:
                payload["solicitacaoPagador"] = str(descricao)[:140]
            if external_reference is not None:
                payload["infoAdicionais"] = [{"nome": "ref", "valor": str(external_reference)[:200]}]
            r = requests.post(f"{self._base_url()}/v2/cob", headers=h, json=payload, cert=cert_path, timeout=TIMEOUT)
            j = r.json() or {}
            txid = j.get("txid")
            copia_cola = j.get("pixCopiaECola")
            loc_id = (j.get("loc") or {}).get("id")
            if not txid or not (copia_cola or loc_id):
                raise RuntimeError(f"Falha ao criar cobrança Pix na EFÍ: {j or r.text[:300]}")
            # QR Code (imagem base64) a partir da location
            qr_b64 = None
            if loc_id:
                try:
                    rq = requests.get(f"{self._base_url()}/v2/loc/{loc_id}/qrcode", headers=h, cert=cert_path, timeout=TIMEOUT)
                    jq = rq.json() or {}
                    if not copia_cola:
                        copia_cola = jq.get("qrcode")
                    img = jq.get("imagemQrcode") or ""
                    if img.startswith("data:") and "," in img:
                        qr_b64 = img.split(",", 1)[1]
                    elif img:
                        qr_b64 = img
                except Exception:
                    qr_b64 = None
            return {
                "payment_id": str(txid),
                "tipo": "PIX",
                "boleto_url": None,
                "pix_qrcode": qr_b64,
                "pix_copia_cola": copia_cola,
            }
        finally:
            try:
                os.remove(cert_path)
            except OSError:
                pass

    def configurar_webhook(self, webhook_url):
        """Registra a URL de webhook para a chave Pix recebedora."""
        if not self.configurado:
            raise RuntimeError("Credenciais da EFÍ incompletas.")
        cert_path = self._escrever_cert()
        try:
            token = self._token(cert_path)
            h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "x-skip-mtls-checking": "true"}
            r = requests.put(
                f"{self._base_url()}/v2/webhook/{self.chave_pix}",
                headers=h, json={"webhookUrl": webhook_url}, cert=cert_path, timeout=TIMEOUT,
            )
            return r.ok
        finally:
            try:
                os.remove(cert_path)
            except OSError:
                pass
