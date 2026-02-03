# Sistema de Redefinição de Senha - Unimaster

## 📋 Visão Geral

Sistema completo de "Esqueci Minha Senha" que permite aos usuários solicitar redefinição de senha via email.

## 🗄️ Banco de Dados

A tabela `password_reset_tokens` foi criada para armazenar os tokens de redefinição:

```sql
CREATE TABLE password_reset_tokens (
    id INT(11) NOT NULL AUTO_INCREMENT,
    usuario_id INT(11) NOT NULL,
    token VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    used TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE INDEX unq_token (token),
    INDEX idx_usuario_id (usuario_id),
    INDEX idx_expires_at (expires_at),
    INDEX idx_used (used),
    CONSTRAINT fk_password_reset_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
);
```

## ⚙️ Configuração de Email

### Variáveis de Ambiente

Configure as seguintes variáveis de ambiente no seu servidor:

```bash
# Servidor SMTP (ex: Gmail, SendGrid, etc.)
export MAIL_SERVER="smtp.gmail.com"
export MAIL_PORT="587"
export MAIL_USE_TLS="True"
export MAIL_USERNAME="seu-email@gmail.com"
export MAIL_PASSWORD="sua-senha-app"
export MAIL_DEFAULT_SENDER="seu-email@gmail.com"
```

### Exemplo com Gmail

1. **Habilitar "Senhas de app" no Google Account:**
   - Acesse: https://myaccount.google.com/apppasswords
   - Gere uma senha de app específica para o Unimaster
   - Use essa senha no `MAIL_PASSWORD`

2. **Configurar no sistema:**
   ```bash
   export MAIL_SERVER="smtp.gmail.com"
   export MAIL_PORT="587"
   export MAIL_USE_TLS="True"
   export MAIL_USERNAME="seu-email@gmail.com"
   export MAIL_PASSWORD="senha-de-app-gerada"
   export MAIL_DEFAULT_SENDER="seu-email@gmail.com"
   ```

### Exemplo com SendGrid

```bash
export MAIL_SERVER="smtp.sendgrid.net"
export MAIL_PORT="587"
export MAIL_USE_TLS="True"
export MAIL_USERNAME="apikey"
export MAIL_PASSWORD="SUA_API_KEY_SENDGRID"
export MAIL_DEFAULT_SENDER="noreply@seudominio.com.br"
```

### Configuração Permanente (systemd)

Edite o arquivo de serviço `/etc/systemd/system/unimaster.service`:

```ini
[Service]
Environment="MAIL_SERVER=smtp.gmail.com"
Environment="MAIL_PORT=587"
Environment="MAIL_USE_TLS=True"
Environment="MAIL_USERNAME=seu-email@gmail.com"
Environment="MAIL_PASSWORD=senha-de-app"
Environment="MAIL_DEFAULT_SENDER=seu-email@gmail.com"
```

Depois execute:
```bash
sudo systemctl daemon-reload
sudo systemctl restart unimaster
```

## 🔗 Rotas Criadas

1. **`/auth/esqueci-senha`** - Página para solicitar redefinição
2. **`/auth/redefinir-senha/<token>`** - Página para redefinir senha com token

## 🔒 Segurança

- Tokens são gerados usando `secrets.token_urlsafe(32)` (32 bytes seguros)
- Tokens expiram em 1 hora
- Tokens anteriores são invalidados ao gerar novo token
- Tokens são marcados como "usados" após redefinição bem-sucedida
- Não revela se o email existe ou não (por segurança)

## 📧 Funcionalidades

- ✅ Solicitação de redefinição via email
- ✅ Link seguro com token único
- ✅ Expiração automática (1 hora)
- ✅ Validação de senha (mínimo 6 caracteres)
- ✅ Confirmação de senha
- ✅ Indicador de força da senha
- ✅ Email HTML formatado
- ✅ Invalidação de tokens anteriores

## 🧪 Testando

1. Acesse `/auth/esqueci-senha`
2. Digite um email cadastrado
3. Verifique a caixa de entrada do email
4. Clique no link recebido
5. Redefina a senha

## ⚠️ Troubleshooting

### Email não está sendo enviado

1. Verifique os logs: `journalctl -u unimaster -f`
2. Confirme que as variáveis de ambiente estão configuradas
3. Teste a conexão SMTP manualmente
4. Verifique se o firewall permite conexões SMTP (porta 587)

### Token inválido ou expirado

- Tokens expiram em 1 hora
- Cada novo token invalida os anteriores
- Solicite um novo link se necessário

## 📝 Notas

- O sistema não revela se um email está cadastrado (por segurança)
- Links de redefinição são únicos e descartáveis
- A senha deve ter no mínimo 6 caracteres
