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


def enviar_email_link_pagamento(email_destino, nome, academia_nome, link, valor=None, copia_cola=None):
    """Envia por e-mail o link de pagamento (matrícula/cobrança) ao responsável.
    Retorna True se enviado, False caso contrário (best-effort)."""
    if not email_destino or "@" not in str(email_destino):
        return False
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        current_app.logger.warning("Email não configurado — link de pagamento não enviado.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Pagamento da matrícula — {academia_nome}"
        msg["From"] = MAIL_DEFAULT_SENDER or MAIL_USERNAME
        msg["To"] = email_destino
        valor_txt = (f"R$ {float(valor):.2f}" if valor else "")
        text = (
            f"Olá, {nome or ''}!\n\n"
            f"Segue o link para pagamento da matrícula na {academia_nome}"
            + (f" no valor de {valor_txt}" if valor_txt else "") + ":\n"
            f"{link}\n\n"
            + (f"PIX copia e cola:\n{copia_cola}\n\n" if copia_cola else "")
            + "Após o pagamento, sua matrícula será confirmada.\n\nEquipe Unimaster"
        )
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#1f2937">
          <h2 style="color:#0d6efd">Pagamento da matrícula</h2>
          <p>Olá, <strong>{nome or ''}</strong>!</p>
          <p>Segue o link para pagamento da matrícula na <strong>{academia_nome}</strong>{(' no valor de <strong>'+valor_txt+'</strong>') if valor_txt else ''}:</p>
          <p style="text-align:center;margin:24px 0">
            <a href="{link}" style="background:#0d6efd;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:bold">Pagar matrícula</a>
          </p>
          {('<p style="font-size:13px;color:#555"><strong>PIX copia e cola:</strong><br><span style="word-break:break-all">'+copia_cola+'</span></p>') if copia_cola else ''}
          <p style="font-size:13px;color:#555">Ou copie e cole no navegador:<br><span style="word-break:break-all">{link}</span></p>
          <p style="font-size:12px;color:#888;margin-top:20px">Após o pagamento, sua matrícula será confirmada.<br>Equipe Unimaster</p>
        </div>"""
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        context = ssl.create_default_context()
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            if MAIL_USE_TLS:
                server.starttls(context=context)
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
        current_app.logger.info(f"Link de pagamento enviado para {email_destino}")
        return True
    except Exception as e:
        current_app.logger.error(f"Erro ao enviar link de pagamento: {e}", exc_info=True)
        return False


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


def enviar_email_credenciais_acesso(email_destino, nome_destinatario, nome_aluno,
                                    academia_nome, login, senha, link_login):
    """
    Envia as credenciais de acesso ao responsável, após a promoção do pré-cadastro.

    A senha vai em texto porque é gerada na hora e só existe aqui — o sistema
    guarda apenas o hash. Retorna True se enviado (best-effort, não levanta).
    """
    if not email_destino or "@" not in str(email_destino):
        return False
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        current_app.logger.warning("Email não configurado — credenciais não enviadas.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Seu acesso ao sistema — {academia_nome}"
        msg["From"] = MAIL_DEFAULT_SENDER or MAIL_USERNAME
        msg["To"] = email_destino

        sobre_aluno = f" do aluno {nome_aluno}" if nome_aluno else ""
        text = (
            f"Olá, {nome_destinatario or ''}!\n\n"
            f"O cadastro{sobre_aluno} foi concluído na {academia_nome} e seu acesso "
            f"ao sistema já está liberado.\n\n"
            f"Endereço: {link_login}\n"
            f"Usuário: {login}\n"
            f"Senha: {senha}\n\n"
            f"Por segurança, troque a senha no primeiro acesso.\n\nEquipe Unimaster"
        )
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#1f2937">
          <h2 style="color:#0d6efd">Seu acesso ao sistema</h2>
          <p>Olá, <strong>{nome_destinatario or ''}</strong>!</p>
          <p>O cadastro{sobre_aluno} foi concluído na <strong>{academia_nome}</strong>
             e seu acesso ao sistema já está liberado.</p>
          <table style="border-collapse:collapse;margin:18px 0;font-size:15px">
            <tr><td style="padding:6px 12px 6px 0;color:#555">Usuário</td>
                <td style="padding:6px 0"><strong>{login}</strong></td></tr>
            <tr><td style="padding:6px 12px 6px 0;color:#555">Senha</td>
                <td style="padding:6px 0"><strong>{senha}</strong></td></tr>
          </table>
          <p style="text-align:center;margin:24px 0">
            <a href="{link_login}" style="background:#0d6efd;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:bold">Entrar no sistema</a>
          </p>
          <p style="font-size:13px;color:#555">Ou copie e cole no navegador:<br>
             <span style="word-break:break-all">{link_login}</span></p>
          <p style="font-size:12px;color:#888;margin-top:20px">
             Por segurança, troque a senha no primeiro acesso.<br>Equipe Unimaster</p>
        </div>"""
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        context = ssl.create_default_context()
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            if MAIL_USE_TLS:
                server.starttls(context=context)
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
        current_app.logger.info(f"Credenciais enviadas para {email_destino}")
        return True
    except Exception as e:
        current_app.logger.error(f"Erro ao enviar credenciais: {e}", exc_info=True)
        return False
