# Como Aceitar o Certificado Autoassinado no Navegador

## ⚠️ Aviso de Segurança

O certificado autoassinado é seguro para uso interno, mas os navegadores mostram um aviso porque não é emitido por uma autoridade certificadora reconhecida.

## 📋 Passos para Aceitar o Certificado

### Chrome/Edge (Chromium)

1. Ao ver o aviso "Sua conexão não é particular", clique em **"Avançado"** ou **"Advanced"**
2. Clique em **"Prosseguir para rmservicosnet.com.br (não seguro)"** ou **"Proceed to rmservicosnet.com.br (unsafe)"**
3. O site será carregado via HTTPS
4. **Importante**: Na primeira vez, você precisará aceitar o aviso. Depois disso, o navegador lembrará da sua escolha

### Firefox

1. Ao ver o aviso, clique em **"Avançado"** ou **"Advanced"**
2. Clique em **"Aceitar o Risco e Continuar"** ou **"Accept the Risk and Continue"**
3. O site será carregado via HTTPS

### Safari

1. Clique em **"Mostrar Detalhes"** ou **"Show Details"**
2. Clique em **"Visitar este site"** ou **"Visit this website"**
3. Confirme clicando em **"Visitar Site"** ou **"Visit Website"**

## 🔒 Solução Definitiva: Let's Encrypt

Para eliminar completamente o aviso, use o script que configura Let's Encrypt para `rmservicosnet.com.br` e `www.rmservicosnet.com.br`.

### Pré-requisito obrigatório: DNS

O domínio **precisa apontar para este servidor**. Hoje o DNS de `rmservicosnet.com.br` aponta para **177.12.168.246**; este servidor tem o IP **177.153.51.151**. Enquanto o DNS apontar para outro IP, o Let's Encrypt não conseguirá validar o domínio.

No seu provedor de DNS (registro.br, Cloudflare, etc.) configure:

- **Registro A:** `rmservicosnet.com.br` → **177.153.51.151**
- **Registro A:** `www.rmservicosnet.com.br` → **177.153.51.151**

(Opcional: remova ou aponte o AAAA para este servidor se quiser acesso por IPv6.)

### Como configurar (após corrigir o DNS)

```bash
cd /var/www/Unimaster
sudo ./deploy/letsencrypt-configurar.sh
```

O script:

1. Verifica se o DNS aponta para este servidor (177.153.51.151)
2. Aplica o Nginx com suporte ao desafio ACME
3. Obtém o certificado Let's Encrypt
4. Ativa HTTPS com certificado válido e redirecionamento HTTP→HTTPS
5. Habilita renovação automática (certbot.timer)

### Verificar DNS

```bash
# Deve retornar 177.153.51.151 (registro A)
getent ahostsv4 rmservicosnet.com.br
# ou
dig rmservicosnet.com.br A +short
```

## 📝 Notas Importantes

- O certificado autoassinado atual é válido por 365 dias
- O redirecionamento HTTP → HTTPS está ativo
- A configuração SSL está otimizada para segurança
- Headers de segurança foram adicionados (HSTS, X-Frame-Options, etc.)

## 🔄 Renovação Automática (Let's Encrypt)

Se você configurar o Let's Encrypt, o certificado será renovado automaticamente pelo systemd timer do certbot. Não é necessário fazer nada manualmente.
