# Como Configurar SSL/HTTPS para Resolver "Não Seguro"

## Problema Atual

O site está aparecendo como "não seguro" porque está usando um certificado autoassinado. Para resolver isso, você precisa configurar um certificado válido do Let's Encrypt.

## ⚠️ Problema Identificado

O DNS IPv6 (`2804:10:8036::168:246`) está apontando para outro servidor, o que impede o Let's Encrypt de validar o domínio via IPv6.

## Soluções

### Opção 1: Configurar DNS IPv6 (Recomendado)

No seu provedor de DNS (registro.br, Cloudflare, etc.), configure:

1. **Registro AAAA (IPv6)**: `rmservicosnet.com.br` → IPv6 público do servidor
2. **Registro AAAA (IPv6)**: `www.rmservicosnet.com.br` → IPv6 público do servidor

Para descobrir o IPv6 público do servidor:
```bash
ip -6 addr show | grep "inet6" | grep -v "::1" | grep -v "fe80"
```

### Opção 2: Usar Apenas IPv4 (Mais Rápido)

Se você não precisa de IPv6, pode configurar o certificado apenas para IPv4:

```bash
cd /var/www/Unimaster
sudo certbot certonly --standalone -d rmservicosnet.com.br --agree-tos --register-unsafely-without-email --non-interactive --preferred-challenges http
```

Depois, atualize a configuração do nginx para usar o certificado Let's Encrypt:

```bash
sudo cp /var/www/Unimaster/deploy/nginx-unimaster-letsencrypt.conf /etc/nginx/sites-available/unimaster
sudo nginx -t && sudo systemctl reload nginx
```

### Opção 3: Desabilitar IPv6 Temporariamente

Se você não precisa de IPv6, pode desabilitar no nginx temporariamente:

1. Edite `/etc/nginx/sites-available/unimaster`
2. Remova ou comente a linha `listen [::]:80 default_server;`
3. Recarregue o nginx: `sudo systemctl reload nginx`
4. Execute o script novamente: `sudo ./deploy/letsencrypt-configurar.sh`

## Verificação

Após configurar o certificado, verifique:

1. Acesse `https://rmservicosnet.com.br`
2. O navegador deve mostrar um cadeado verde
3. O certificado deve ser válido e emitido por "Let's Encrypt"

## Renovação Automática

O certificado Let's Encrypt expira a cada 90 dias. A renovação automática já está configurada via `certbot.timer`.

Para verificar o status:
```bash
sudo systemctl status certbot.timer
```

Para renovar manualmente:
```bash
sudo certbot renew
```
