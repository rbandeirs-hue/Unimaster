# 🔒 Como Resolver o Problema "Não Seguro" - Configuração SSL

## 📋 Situação Atual

O site está aparecendo como "não seguro" porque está usando um **certificado autoassinado**. Para resolver isso definitivamente, você precisa configurar um certificado válido do **Let's Encrypt**.

## ⚠️ Problema Identificado

O Let's Encrypt não consegue validar o domínio porque:

1. **DNS IPv4 (A)**: ✅ Está correto - aponta para `177.153.51.151`
2. **DNS IPv6 (AAAA)**: ❌ Está apontando para `2804:10:8036::168:246` (outro servidor)

O Let's Encrypt tenta validar via IPv6 e não consegue acessar este servidor.

## ✅ Solução: Corrigir DNS IPv6

### Passo 1: Descobrir o IPv6 do Servidor

Execute no servidor:
```bash
ip -6 addr show | grep "inet6" | grep -v "::1" | grep -v "fe80"
```

Ou verifique no painel do seu provedor de hospedagem/VPS.

### Passo 2: Configurar DNS no Provedor

Acesse seu provedor de DNS (registro.br, Cloudflare, etc.) e configure:

**Opção A - Se você TEM IPv6 público:**
- **Registro AAAA**: `rmservicosnet.com.br` → [IPv6 do servidor]
- **Registro AAAA**: `www.rmservicosnet.com.br` → [IPv6 do servidor]

**Opção B - Se você NÃO TEM IPv6 público (Recomendado):**
- **Remova** os registros AAAA de `rmservicosnet.com.br` e `www.rmservicosnet.com.br`
- Isso força o Let's Encrypt a usar apenas IPv4

### Passo 3: Aguardar Propagação DNS

Após alterar o DNS, aguarde 5-15 minutos para a propagação.

### Passo 4: Executar Script de Configuração

```bash
cd /var/www/Unimaster
sudo ./deploy/letsencrypt-configurar.sh
```

## 🔄 Alternativa: Usar Apenas IPv4

Se você não precisa de IPv6, pode configurar o nginx para não escutar IPv6:

1. Edite `/etc/nginx/sites-available/unimaster`
2. Remova ou comente as linhas com `[::]:80` e `[::]:443`
3. Recarregue: `sudo systemctl reload nginx`
4. Execute o script novamente

## 📝 Verificação

Após configurar:

1. Acesse `https://rmservicosnet.com.br`
2. O navegador deve mostrar um **cadeado verde** 🔒
3. O certificado deve ser válido e emitido por "Let's Encrypt"

## 🔄 Renovação Automática

O certificado Let's Encrypt expira a cada 90 dias. A renovação automática está configurada.

Para verificar:
```bash
sudo systemctl status certbot.timer
```

## 📞 Precisa de Ajuda?

Se o problema persistir após corrigir o DNS IPv6, verifique:

1. Portas 80 e 443 estão abertas no firewall
2. O DNS IPv4 está correto
3. O nginx está rodando corretamente
