"""
Integração com o banco Cora (Boleto registrado + PIX) — modalidade "Integração Direta".

A configuração é POR ACADEMIA: cada academia usa a sua própria conta Cora.
As credenciais ficam na tabela `academias`, um trio por ambiente — o Cora emite
Client ID e certificado distintos para cada um, e o de stage responde 401
invalid_client em produção:
  - cora_ambiente         : 'stage' (padrão, testes) ou 'production'
  - cora_client_id        / cora_certificate        / cora_private_key       (stage)
  - cora_client_id_prod   / cora_certificate_prod   / cora_private_key_prod  (produção)

A autenticação é mTLS: o certificado e a chave privada são apresentados no
handshake TLS de TODAS as chamadas (inclusive a do token). Como o `requests`
exige caminhos de arquivo, o par é escrito em arquivos temporários com permissão
0600 durante a chamada e removido logo depois — nunca fica em disco de forma
persistente.

Uso:
    from utils.cora import CoraClient
    cli = CoraClient(client_id, certificado, chave, ambiente)
    if cli.configurado:
        r = cli.criar_cobranca("PIX", valor, vencimento, nome, cpf, ...)

Docs: https://developers.cora.com.br/docs/client-credentials-int-direta
      https://developers.cora.com.br/reference/emissão-de-boleto-registrado-v2
"""
import os
import re
import tempfile
import uuid
from contextlib import contextmanager

import requests

TIMEOUT = 30

# Integração Direta usa o host "matls-" (mutual TLS) em ambos os ambientes.
BASE_STAGE = "https://matls-clients.api.stage.cora.com.br"
BASE_PROD = "https://matls-clients.api.cora.com.br"

# Hosts do cadastro de webhooks ("endpoints") indicados pelo suporte do Cora.
API_STAGE = "https://api.stage.cora.com.br"
API_PROD = "https://api.cora.com.br"

# Margem de segurança para renovar o token antes de expirar de facto (segundos).
_MARGEM_TOKEN = 60


class CoraAPIError(RuntimeError):
    """Erro devolvido pela API do Cora, carregando o status HTTP quando existe."""

    def __init__(self, mensagem, status=None):
        super().__init__(mensagem)
        self.status = status


def separar_pem(texto):
    """Separa (certificados, chave privada) de um texto PEM.

    O Cora entrega certificado e chave no mesmo arquivo, então o conteúdo colado
    num campo pode conter os dois — e nesse caso as duas metades vêm da MESMA
    geração, que é justamente o que o mTLS exige. Devolve ('', '') para texto sem
    bloco PEM nenhum.
    """
    t = (texto or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return "", ""
    certs = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", t, re.S)
    chaves = re.findall(
        r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----.*?-----END (?:RSA |EC )?PRIVATE KEY-----", t, re.S
    )
    return "\n".join(certs), (chaves[0] if chaves else "")


def validar_par(certificado, chave):
    """Confere se certificado e chave privada são o MESMO par (o que o mTLS exige).

    Devolve None quando está tudo certo, ou uma mensagem pronta para o usuário.
    Vale a pena checar na hora de salvar: sem isso o problema só aparece depois,
    como um SSLError incompreensível no meio de uma emissão de cobrança.
    """
    import ssl

    cert = (certificado or "").strip()
    key = (chave or "").strip()
    if not (cert and key):
        return None
    cert_path = key_path = None
    try:
        fd, cert_path = tempfile.mkstemp(suffix=".pem")
        os.write(fd, (cert + "\n").encode())
        os.close(fd)
        fd, key_path = tempfile.mkstemp(suffix=".key")
        os.write(fd, (key + "\n").encode())
        os.close(fd)
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_cert_chain(cert_path, key_path)
        return None
    except ssl.SSLError as e:
        texto = str(e)
        if "KEY_VALUES_MISMATCH" in texto:
            return ("o certificado e a chave privada não são do mesmo par. "
                    "Baixe os dois arquivos da MESMA geração no painel do Cora "
                    "(Conta → Integrações via APIs) e cole os dois de novo.")
        return f"certificado ou chave inválidos ({texto[:120]})."
    except Exception as e:
        return f"não foi possível validar certificado/chave ({str(e)[:120]})."
    finally:
        for p in (cert_path, key_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _so_digitos(v):
    return re.sub(r"\D", "", str(v or ""))


def _centavos(valor):
    """Cora trabalha sempre com valores inteiros em centavos (R$ 10,01 -> 1001)."""
    return int(round(float(valor) * 100))


def _tipo_documento(doc):
    """'CPF' (11 dígitos) ou 'CNPJ' (14). Levanta erro se não for nem um nem outro."""
    d = _so_digitos(doc)
    if len(d) == 11:
        return d, "CPF"
    if len(d) == 14:
        return d, "CNPJ"
    raise RuntimeError("CPF/CNPJ do pagador inválido para emitir cobrança no Cora.")


class CoraClient:
    """Cliente Cora vinculado às credenciais de uma academia."""

    def __init__(self, client_id, certificate, private_key, ambiente="stage"):
        self.client_id = (client_id or "").strip()
        self.certificate = (certificate or "").strip()
        self.private_key = (private_key or "").strip()
        self.ambiente = (ambiente or "stage").strip().lower()
        self._token = None
        self._token_exp = 0.0

    # ------------------------------------------------------------------ base

    @property
    def configurado(self):
        """True só quando o trio completo está presente — o mTLS exige os três."""
        return bool(self.client_id and self.certificate and self.private_key)

    @property
    def is_stage(self):
        return self.ambiente not in ("prod", "production", "producao", "produção")

    def _base_url(self):
        return BASE_STAGE if self.is_stage else BASE_PROD

    def _api_url(self):
        """Host público (sem 'matls-') usado no cadastro de webhooks."""
        return API_STAGE if self.is_stage else API_PROD

    @contextmanager
    def _cert_files(self):
        """Escreve certificado e chave em arquivos temporários 0600 e apaga no fim.

        O `requests` (via urllib3/OpenSSL) só aceita caminhos de arquivo para o
        par de mTLS, daí o vaivém pelo disco. Os arquivos são criados com 0600 e
        removidos no `finally`, mesmo em caso de erro.
        """
        if not self.configurado:
            raise RuntimeError("Credenciais do Cora incompletas para esta academia "
                               "(exige Client ID, certificado e chave privada).")
        problema = validar_par(self.certificate, self.private_key)
        if problema:
            raise RuntimeError(f"Credenciais do Cora desta academia: {problema}")
        cert_path = key_path = None
        try:
            fd, cert_path = tempfile.mkstemp(suffix=".pem")
            os.write(fd, self._pem(self.certificate).encode())
            os.close(fd)
            os.chmod(cert_path, 0o600)

            fd, key_path = tempfile.mkstemp(suffix=".key")
            os.write(fd, self._pem(self.private_key).encode())
            os.close(fd)
            os.chmod(key_path, 0o600)

            yield cert_path, key_path
        finally:
            for p in (cert_path, key_path):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    @staticmethod
    def _pem(texto):
        """Normaliza o PEM colado no formulário (CRLF -> LF, garante quebra final)."""
        t = (texto or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        return t + "\n"

    def _acesso(self):
        """Devolve um access_token válido, renovando quando necessário."""
        import time

        if self._token and time.time() < self._token_exp:
            return self._token
        with self._cert_files() as (cert, key):
            r = requests.post(
                f"{self._base_url()}/token",
                cert=(cert, key),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "client_id": self.client_id},
                timeout=TIMEOUT,
            )
        if not r.ok:
            raise RuntimeError(f"Falha ao autenticar no Cora ({r.status_code}): {r.text[:300]}")
        j = r.json() or {}
        tok = j.get("access_token")
        if not tok:
            raise RuntimeError(f"Cora não devolveu access_token: {str(j)[:300]}")
        self._token = tok
        self._token_exp = time.time() + max(0, int(j.get("expires_in") or 0)) - _MARGEM_TOKEN
        return tok

    def _request(self, metodo, caminho, *, json_body=None, idempotency=True, base=None):
        """Chamada autenticada (Bearer + mTLS) à API do Cora.

        O `Idempotency-Key` é sempre um UUID — o Cora rejeita com HTTP 400
        qualquer outro formato.
        """
        headers = {
            "Authorization": f"Bearer {self._acesso()}",
            "Content-Type": "application/json",
        }
        if idempotency:
            headers["Idempotency-Key"] = str(uuid.uuid4())
        with self._cert_files() as (cert, key):
            r = requests.request(
                metodo, f"{base or self._base_url()}{caminho}",
                cert=(cert, key), headers=headers, json=json_body, timeout=TIMEOUT,
            )
        if not r.ok:
            raise CoraAPIError(
                f"Cora {metodo} {caminho} falhou ({r.status_code}): {r.text[:500]}",
                status=r.status_code,
            )
        try:
            j = r.json()
        except ValueError:
            return {}
        # `/endpoints/` responde uma lista (vazia quando não há webhook) — só o
        # corpo nulo vira dict, para os callers que esperam `.get()`.
        return {} if j is None else j

    # ------------------------------------------------------------- operações

    def testar_conexao(self):
        """Autentica e devolve um resumo — sem criar nada. Usado no botão de teste."""
        self._acesso()
        return {"ok": True, "ambiente": "stage" if self.is_stage else "production",
                "base_url": self._base_url()}

    def criar_cobranca(self, tipo, valor, vencimento, nome, cpf, email=None, telefone=None,
                       descricao=None, external_reference=None, endereco=None):
        """Emite a cobrança no Cora. Retorna dict normalizado
        {payment_id, tipo, boleto_url, pix_qrcode, pix_copia_cola}.

        `tipo` define o `payment_forms` enviado, e isso importa na prática:
          - 'PIX'    -> ['PIX']: o EMV (copia e cola) vem na hora, junto com um
                        PNG do QR Code hospedado pelo Cora.
          - 'BOLETO' -> ['BANK_SLIP', 'PIX']: o boleto sai com linha digitável
                        imediatamente, mas o registro bancário é ASSÍNCRONO e o
                        EMV do PIX só é anexado depois que o registro conclui —
                        por isso `pix_copia_cola` costuma vir vazio aqui.
        """
        doc, doc_tipo = _tipo_documento(cpf)
        venc = vencimento.strftime("%Y-%m-%d") if hasattr(vencimento, "strftime") else str(vencimento)
        nome = (str(nome or "").strip() or "Aluno")[:120]

        customer = {"name": nome, "document": {"identity": doc, "type": doc_tipo}}
        if email:
            customer["email"] = str(email).strip()[:120]
        addr = self._endereco(endereco)
        if addr:
            customer["address"] = addr

        payload = {
            "code": str(external_reference or "")[:60] or f"unimaster-{uuid.uuid4().hex[:12]}",
            "customer": customer,
            "services": [{
                "name": (descricao or "Mensalidade")[:100],
                "description": (descricao or "Mensalidade")[:250],
                "amount": _centavos(valor),
            }],
            "payment_terms": {"due_date": venc},
            "payment_forms": ["BANK_SLIP", "PIX"] if str(tipo).upper() == "BOLETO" else ["PIX"],
        }
        j = self._request("POST", "/v2/invoices", json_body=payload)
        return self._normalizar(j, tipo)

    def consultar(self, invoice_id):
        """Detalhes de um boleto — usado para conferir o status (OPEN/PAID/…)."""
        return self._request("GET", f"/v2/invoices/{invoice_id}", idempotency=False)

    def cancelar(self, invoice_id):
        """Cancela um boleto em aberto."""
        return self._request("DELETE", f"/v2/invoices/{invoice_id}")

    def simular_pagamento(self, invoice_id):
        """Marca o boleto como pago — SÓ funciona no ambiente de stage.

        É o gatilho para validar a baixa automática e o webhook sem dinheiro real.
        """
        if not self.is_stage:
            raise RuntimeError("Simulação de pagamento só existe no ambiente de stage do Cora.")
        return self._request("POST", "/v2/invoices/pay", json_body={"id": invoice_id})

    # --------------------------------------------------------------- webhooks

    # Cada combinação resource+trigger é um cadastro separado no Cora; para a
    # baixa automática basta a cobrança paga.
    WEBHOOK_EVENTOS_PADRAO = (("invoice", "paid"),)

    def _endpoints_request(self, metodo, caminho, **kwargs):
        """Chama a API de webhooks tentando os dois hosts do Cora.

        O suporte indica `api[.stage].cora.com.br/endpoints/`, mas na Integração
        Direta todas as demais chamadas passam pelo host `matls-`. O par de mTLS
        é apresentado nos dois casos, então tentamos primeiro o host que já
        autenticou o token e só caímos no host público se ele recusar a rota.
        """
        try:
            return self._request(metodo, caminho, base=self._base_url(), **kwargs)
        except CoraAPIError as e:
            if e.status not in (401, 403, 404, 405, 415):
                raise
            primeiro = str(e)
        try:
            return self._request(metodo, caminho, base=self._api_url(), **kwargs)
        except CoraAPIError as e:
            raise CoraAPIError(f"{primeiro} | {e}", status=e.status)

    def listar_webhooks(self):
        """Webhooks já cadastrados neste ambiente (lista de dicts)."""
        j = self._endpoints_request("GET", "/endpoints/", idempotency=False)
        if isinstance(j, list):
            return [x for x in j if isinstance(x, dict)]
        for chave in ("endpoints", "items", "data", "results"):
            v = (j or {}).get(chave)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return []

    def registrar_webhook(self, url, resource="invoice", trigger="paid"):
        """Cadastra UMA combinação resource+trigger (POST /endpoints/).

        Atenção aos erros 400 mais comuns apontados pelo Cora: o campo é
        `trigger` (com dois "g"), `resource` é o recurso ('invoice') e nunca o
        gatilho ('paid'), e o cadastro vale só para o ambiente em que foi feito.

        `includeResource` (padrão `false` na API) é enviado por precaução, mas
        não conte com ele: em testes no stage a notificação chega SEM corpo
        nenhum, só com os cabeçalhos Webhook-Event-Type/Webhook-Resource-Id —
        quem confirma o pagamento é o `consultar()` do lado de cá.
        """
        url = str(url or "").strip()
        if not url.lower().startswith("https://"):
            raise RuntimeError(
                f"O Cora só aceita webhook em HTTPS público — URL informada: {url or '(vazia)'}"
            )
        return self._endpoints_request("POST", "/endpoints/", json_body={
            "url": url,
            "resource": str(resource or "invoice").strip().lower(),
            "trigger": str(trigger or "paid").strip().lower(),
            "includeResource": True,
        })

    def remover_webhook(self, endpoint_id):
        """Remove um webhook cadastrado."""
        return self._endpoints_request("DELETE", f"/endpoints/{endpoint_id}")

    def sincronizar_webhooks(self, url, eventos=None):
        """Garante que `url` está cadastrada para cada (resource, trigger).

        Devolve {criados, atualizados, existentes, erros} — o cadastro de cada
        evento é independente, então um erro num evento não impede os demais.
        Um cadastro igual mas sem `includeResource` é refeito (o Cora não
        permite editar: é apagar e cadastrar de novo).
        """
        eventos = list(eventos or self.WEBHOOK_EVENTOS_PADRAO)
        alvo = str(url or "").strip()
        try:
            atuais = self.listar_webhooks()
        except Exception:
            # Sem a listagem seguimos em frente: uma duplicata vira erro no POST,
            # que é reportado ao usuário.
            atuais = []
        ja_tem = {}
        for e in atuais:
            chave = (str(e.get("url") or "").strip().rstrip("/"),
                     str(e.get("resource") or "").strip().lower(),
                     str(e.get("trigger") or "").strip().lower())
            ja_tem[chave] = e

        criados, atualizados, existentes, erros = [], [], [], []
        for resource, trigger in eventos:
            rotulo = f"{resource}.{trigger}"
            atual = ja_tem.get((alvo.rstrip("/"), resource, trigger))
            try:
                if atual and atual.get("includeResource") and atual.get("active", True):
                    existentes.append(rotulo)
                    continue
                if atual:
                    self.remover_webhook(atual.get("id"))
                    self.registrar_webhook(alvo, resource, trigger)
                    atualizados.append(rotulo)
                else:
                    self.registrar_webhook(alvo, resource, trigger)
                    criados.append(rotulo)
            except Exception as e:
                erros.append(f"{rotulo}: {e}")
        return {"url": alvo, "criados": criados, "atualizados": atualizados,
                "existentes": existentes, "erros": erros,
                "ambiente": "stage" if self.is_stage else "production"}

    # ------------------------------------------------------------- auxiliares

    @staticmethod
    def _endereco(endereco):
        """Monta o objeto `address` do Cora a partir do endereço do aluno.

        O Cora exige o endereço completo para o boleto registrado; se faltar
        qualquer campo essencial, devolve None e a emissão segue sem endereço
        (o Cora usa então os dados do titular da conta).
        """
        if not endereco:
            return None
        cep = _so_digitos(endereco.get("cep"))
        rua = str(endereco.get("street") or "").strip()
        bairro = str(endereco.get("neighborhood") or "").strip()
        cidade = str(endereco.get("city") or "").strip()
        estado = str(endereco.get("state") or "").strip().upper()[:2]
        if len(cep) != 8 or not (rua and bairro and cidade and estado):
            return None
        return {
            "street": rua[:120],
            "number": (str(endereco.get("number") or "").strip() or "S/N")[:10],
            "district": bairro[:80],
            "city": cidade[:80],
            "state": estado,
            "complement": (str(endereco.get("complement") or "").strip() or "N/A")[:60],
            "zip_code": cep,
        }

    @staticmethod
    def _normalizar(j, tipo):
        """Traduz a resposta do Cora para o formato usado pelos demais gateways."""
        opts = j.get("payment_options") or {}
        slip = opts.get("bank_slip") or {}
        # O EMV do PIX aparece no topo em algumas respostas e dentro de
        # payment_options noutras — aceitamos as duas formas.
        pix = j.get("pix") or opts.get("pix") or {}
        emv = pix.get("emv") or pix.get("payload")

        pix_qr = None
        if emv:
            try:
                from utils.qrcode_util import gerar_qr_base64
                pix_qr = gerar_qr_base64(emv)
            except Exception:
                pix_qr = None

        # `bank_slip.url` é o PDF do boleto quando há BANK_SLIP e o PNG do QR
        # Code quando a cobrança é só PIX — nos dois casos é o link do pagador.
        tipo_final = "BOLETO" if str(tipo).upper() == "BOLETO" else "PIX"
        # Sem EMV não há PIX utilizável; se existe linha digitável, entrega boleto.
        if tipo_final == "PIX" and not emv and slip.get("digitable"):
            tipo_final = "BOLETO"

        return {
            "payment_id": j.get("id"),
            "tipo": tipo_final,
            "boleto_url": slip.get("url"),
            "pix_qrcode": pix_qr,
            "pix_copia_cola": emv,
            "linha_digitavel": slip.get("digitable"),
            "status": j.get("status"),
        }
