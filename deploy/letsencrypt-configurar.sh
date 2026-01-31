#!/bin/bash
# Solução definitiva: Let's Encrypt para rmservicosnet.com.br
# Requisito: DNS (A e AAAA) do domínio deve apontar para ESTE servidor.
#
# Uso: sudo ./deploy/letsencrypt-configurar.sh
#
# O script:
# 1. Verifica se o DNS aponta para este servidor
# 2. Aplica config Nginx com .well-known para o desafio ACME
# 3. Obtém certificado com certbot --webroot
# 4. Aplica config Nginx com HTTPS (Let's Encrypt) e redirecionamento HTTP→HTTPS
# 5. Configura renovação automática (certbot timer)

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
DOMINIO="rmservicosnet.com.br"
WWW_DOMINIO="www.rmservicosnet.com.br"
AVAILABLE="/etc/nginx/sites-available/unimaster"
WEBROOT="/var/www/html"

# IP público DESTE servidor (ajuste se usar outro método para obter)
ESTE_IP="177.153.51.151"

echo "=== Unimaster: Let's Encrypt para $DOMINIO ==="

# --- Verificar DNS (registro A deve apontar para este servidor) ---
echo "Verificando DNS..."
RESOLVIDO_IPV4=$(getent ahostsv4 "$DOMINIO" 2>/dev/null | awk '{print $1}' | sort -u | head -1)
if [[ -z "$RESOLVIDO_IPV4" ]]; then
  echo "Erro: não foi possível resolver $DOMINIO (registro A)"
  echo "Configure o DNS do domínio antes de continuar."
  exit 1
fi
if [[ "$RESOLVIDO_IPV4" != "$ESTE_IP" ]]; then
  echo "Erro: DNS de $DOMINIO aponta para $RESOLVIDO_IPV4"
  echo "      Este servidor tem o IP: $ESTE_IP"
  echo ""
  echo "Para o Let's Encrypt funcionar, o domínio precisa apontar para ESTE servidor."
  echo "No seu provedor de DNS (registro.br, Cloudflare, etc.), configure:"
  echo "  - Registro A:  $DOMINIO  ->  $ESTE_IP"
  echo "  - Registro A:  www.$DOMINIO  ->  $ESTE_IP"
  echo ""
  echo "Após alterar o DNS, aguarde alguns minutos e execute este script novamente."
  exit 1
fi
echo "DNS OK ($DOMINIO -> $ESTE_IP)."

# --- Dependências ---
if ! command -v nginx &>/dev/null; then
  echo "Nginx não encontrado. Instale: apt install nginx"
  exit 1
fi
if ! command -v certbot &>/dev/null; then
  echo "Instalando certbot..."
  apt-get update -qq
  apt-get install -y certbot python3-certbot-nginx
fi

# --- Webroot para desafio ACME ---
mkdir -p "$WEBROOT/.well-known/acme-challenge"
chown -R www-data:www-data "$WEBROOT"
chmod -R 755 "$WEBROOT"

# --- 1) Config Nginx só HTTP com .well-known ---
echo "Aplicando config Nginx (fase 1: HTTP + ACME)..."
cp "$DIR/nginx-http-acme.conf" "$AVAILABLE"
nginx -t && systemctl reload nginx

# --- 2) Obter certificado ---
echo "Obtendo certificado Let's Encrypt para $DOMINIO e $WWW_DOMINIO..."
if ! certbot certonly --webroot -w "$WEBROOT" \
  -d "$DOMINIO" -d "$WWW_DOMINIO" \
  --agree-tos --register-unsafely-without-email --non-interactive; then
  echo "Certbot falhou. Verifique:"
  echo "  - DNS de $DOMINIO e www.$DOMINIO apontando para $ESTE_IP"
  echo "  - Portas 80 e 443 abertas no firewall"
  exit 1
fi

# --- 3) Config Nginx com HTTPS (Let's Encrypt) ---
echo "Aplicando config Nginx (HTTPS com Let's Encrypt)..."
cp "$DIR/nginx-unimaster-letsencrypt.conf" "$AVAILABLE"
nginx -t && systemctl reload nginx

# --- Renovação automática ---
systemctl enable certbot.timer 2>/dev/null || true
systemctl start certbot.timer 2>/dev/null || true

echo ""
echo "=== Let's Encrypt configurado com sucesso ==="
echo "  https://${DOMINIO}"
echo "  https://${WWW_DOMINIO}"
echo ""
echo "O certificado será renovado automaticamente (certbot.timer)."
echo "Libere 80/443 no firewall: sudo ./deploy/expor-ip-publico.sh"
