# -*- coding: utf-8 -*-
"""
Utilitários para envio de email
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import MAIL_SERVER, MAIL_PORT, MAIL_USE_TLS, MAIL_USERNAME, MAIL_PASSWORD, MAIL_DEFAULT_SENDER
from flask import current_app, url_for


def enviar_email_redefinicao_senha(email_destino, nome_usuario, token, base_url):
    """
    Envia email com link de redefinição de senha.
    
    Args:
        email_destino: Email do destinatário
        nome_usuario: Nome do usuário
        token: Token de redefinição
        base_url: URL base da aplicação (ex: https://rmservicosnet.com.br)
    
    Returns:
        bool: True se enviado com sucesso, False caso contrário
    """
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        current_app.logger.warning("Configurações de email não encontradas. Email não será enviado.")
        return False
    
    try:
        # URL do link de redefinição (usar url_for para garantir codificação correta)
        from urllib.parse import quote
        token_encoded = quote(token, safe='')
        reset_url = f"{base_url}/auth/redefinir-senha/{token_encoded}"
        
        # Criar mensagem
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Redefinição de Senha - Unimaster Judô"
        msg["From"] = MAIL_DEFAULT_SENDER
        msg["To"] = email_destino
        
        # Corpo do email em texto simples
        text = f"""
Olá {nome_usuario},

Você solicitou a redefinição de senha para sua conta no Unimaster Judô.

Clique no link abaixo para redefinir sua senha:
{reset_url}

Este link expira em 1 hora.

Se você não solicitou esta redefinição, ignore este email.

Atenciosamente,
Equipe Unimaster Judô
        """
        
        # Corpo do email em HTML
        html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Redefinição de Senha</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #0d6efd; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0;">Unimaster Judô</h1>
        <p style="margin: 10px 0 0 0;">Sistema de Gestão</p>
    </div>
    
    <div style="background-color: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px;">
        <h2 style="color: #0d6efd;">Redefinição de Senha</h2>
        
        <p>Olá <strong>{nome_usuario}</strong>,</p>
        
        <p>Você solicitou a redefinição de senha para sua conta no Unimaster Judô.</p>
        
        <p style="text-align: center; margin: 30px 0;">
            <a href="{reset_url}" 
               style="background-color: #0d6efd; color: white; padding: 12px 30px; 
                      text-decoration: none; border-radius: 5px; display: inline-block; 
                      font-weight: bold;">
                Redefinir Senha
            </a>
        </p>
        
        <p style="font-size: 12px; color: #666;">
            Ou copie e cole este link no seu navegador:<br>
            <a href="{reset_url}" style="color: #0d6efd; word-break: break-all;">{reset_url}</a>
        </p>
        
        <p style="color: #dc3545; font-size: 14px;">
            <strong>⚠️ Importante:</strong> Este link expira em <strong>1 hora</strong>.
        </p>
        
        <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
        
        <p style="font-size: 12px; color: #666;">
            Se você não solicitou esta redefinição de senha, ignore este email. 
            Sua senha permanecerá inalterada.
        </p>
        
        <p style="font-size: 12px; color: #666; margin-top: 20px;">
            Atenciosamente,<br>
            <strong>Equipe Unimaster Judô</strong>
        </p>
    </div>
</body>
</html>
        """
        
        # Adicionar partes ao email
        part1 = MIMEText(text, "plain", "utf-8")
        part2 = MIMEText(html, "html", "utf-8")
        
        msg.attach(part1)
        msg.attach(part2)
        
        # Enviar email
        context = ssl.create_default_context()
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            if MAIL_USE_TLS:
                server.starttls(context=context)
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
        
        current_app.logger.info(f"Email de redefinição de senha enviado para {email_destino}")
        return True
        
    except Exception as e:
        current_app.logger.error(f"Erro ao enviar email de redefinição de senha: {e}", exc_info=True)
        return False
