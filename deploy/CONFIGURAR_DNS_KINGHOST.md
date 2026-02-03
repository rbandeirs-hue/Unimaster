# 🔧 Como Configurar DNS na Kinghost para SSL/HTTPS

## 📋 Passo a Passo na Kinghost

### 1️⃣ Acessar o Painel da Kinghost

1. Acesse: https://www.kinghost.com.br
2. Faça login na sua conta
3. Vá em **"Meus Produtos"** ou **"Painel"**

### 2️⃣ Localizar o Domínio

1. Procure por **"Domínios"** ou **"DNS"** no menu
2. Clique no domínio `rmservicosnet.com.br`
3. Procure pela opção **"Gerenciar DNS"** ou **"Zona DNS"**

### 3️⃣ Verificar Registros Atuais

Você deve ver algo como:

```
Tipo    Nome                    Valor                    TTL
A       rmservicosnet.com.br    177.153.51.151          3600
AAAA    rmservicosnet.com.br    2804:10:8036::168:246  3600
A       www.rmservicosnet.com.br 177.153.51.151        3600
AAAA    www.rmservicosnet.com.br 2804:10:8036::168:246 3600
```

### 4️⃣ Corrigir os Registros DNS

#### Opção A: Se você TEM IPv6 no servidor (menos comum)

1. Descubra o IPv6 do servidor executando no servidor:
   ```bash
   ip -6 addr show | grep "inet6" | grep -v "::1" | grep -v "fe80"
   ```

2. Edite os registros AAAA:
   - **Nome**: `rmservicosnet.com.br`
   - **Tipo**: `AAAA`
   - **Valor**: [IPv6 do servidor]
   - **TTL**: `3600` (ou padrão)

   - **Nome**: `www.rmservicosnet.com.br`
   - **Tipo**: `AAAA`
   - **Valor**: [IPv6 do servidor]
   - **TTL**: `3600` (ou padrão)

#### Opção B: Remover IPv6 (Recomendado - Mais Simples)

Se você não tem IPv6 ou não precisa dele:

1. **Exclua** os registros AAAA de:
   - `rmservicosnet.com.br`
   - `www.rmservicosnet.com.br`

2. **Mantenha apenas** os registros A (IPv4):
   - `rmservicosnet.com.br` → `177.153.51.151`
   - `www.rmservicosnet.com.br` → `177.153.51.151`

### 5️⃣ Verificar Registros A (IPv4)

Certifique-se de que os registros A estão corretos:

```
Tipo    Nome                    Valor           TTL
A       rmservicosnet.com.br    177.153.51.151 3600
A       www.rmservicosnet.com.br 177.153.51.151 3600
```

Se estiverem diferentes, edite para apontar para `177.153.51.151`

### 6️⃣ Salvar as Alterações

1. Clique em **"Salvar"** ou **"Aplicar"**
2. Aguarde a confirmação

### 7️⃣ Aguardar Propagação DNS

- **Tempo estimado**: 5 a 30 minutos
- Você pode verificar a propagação em: https://www.whatsmydns.net

### 8️⃣ Verificar se o DNS Está Correto

No servidor, execute:

```bash
# Verificar IPv4 (deve mostrar 177.153.51.151)
getent ahostsv4 rmservicosnet.com.br | awk '{print $1}' | sort -u | head -1

# Verificar IPv6 (se você removeu, não deve aparecer nada ou deve mostrar outro IP)
getent ahostsv6 rmservicosnet.com.br | awk '{print $1}' | sort -u | head -1
```

### 9️⃣ Configurar SSL/HTTPS

Após o DNS estar correto, execute no servidor:

```bash
cd /var/www/Unimaster
sudo ./deploy/letsencrypt-configurar.sh
```

## 📸 Onde Encontrar no Painel Kinghost

A interface da Kinghost pode variar, mas geralmente:

1. **Menu Principal** → **"Domínios"** ou **"DNS"**
2. Ou: **"Meus Produtos"** → Selecione o domínio → **"Gerenciar DNS"**
3. Ou: **"Painel"** → **"DNS"** → Selecione o domínio

## ⚠️ Dicas Importantes

1. **TTL**: Use `3600` (1 hora) ou o padrão da Kinghost
2. **Propagação**: Pode levar até 24 horas, mas geralmente é mais rápido (5-30 min)
3. **Backup**: Anote os valores antigos antes de alterar
4. **Teste**: Após alterar, aguarde alguns minutos antes de executar o script SSL

## 🔍 Verificação Final

Após configurar o DNS e executar o script SSL:

1. Acesse: `https://rmservicosnet.com.br`
2. Deve aparecer um **cadeado verde** 🔒
3. O certificado deve ser válido e emitido por "Let's Encrypt"

## 📞 Precisa de Ajuda?

Se tiver dificuldades:

1. Tire um print da tela de DNS da Kinghost
2. Verifique se os registros estão salvos corretamente
3. Aguarde pelo menos 15 minutos após alterar o DNS
4. Execute o script SSL novamente

## 🎯 Resumo Rápido

**O que fazer:**
1. Acessar painel Kinghost → Domínios → Gerenciar DNS
2. Remover ou corrigir registros AAAA (IPv6)
3. Verificar que registros A apontam para `177.153.51.151`
4. Aguardar propagação (5-30 min)
5. Executar script SSL no servidor
