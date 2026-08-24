# -*- coding: utf-8 -*-
"""Modelos (templates) de mensagens de WhatsApp, editáveis por academia.

Cada academia pode personalizar o texto de cada tipo de mensagem. Se não houver
texto salvo, usa o padrão (DEFAULTS). Placeholders disponíveis:
  {nome}       -> primeiro nome do destinatário (responsável ou aluno)
  {aluno}      -> nome completo do aluno
  {valor}      -> valor formatado (ex.: R$ 150,00)
  {vencimento} -> data de vencimento (dd/mm/aaaa)
  {link}       -> link de pagamento (gerado na hora quando faltar; ver whatsapp_lembretes)
  {pix}        -> PIX copia e cola, quando o gateway devolver (Cora, Asaas, EFÍ)
  {academia}   -> nome da academia
  {mes}        -> competência (mm/aaaa)

Quando {link} ou {pix} ficam vazios, a linha é removida da mensagem junto com o
rótulo acima dela — para não sair "Pague pelo link:" seguido de nada.
"""
from config import get_db_connection

# Cada tipo: rótulo amigável + texto padrão + descrição
TIPOS = {
    "lembrete_vencimento": {
        "label": "Lembrete de vencimento (mensalidade a vencer)",
        "default": ("Olá {nome}! 🔔 Lembrete da mensalidade de *{aluno}*, "
                    "com vencimento em {vencimento}.\n\n💰 Valor: {valor}\n"
                    "🔗 Pague pelo link:\n{link}\n\n_{academia}_"),
    },
    "lembrete_atraso": {
        "label": "Mensalidade em atraso",
        "default": ("Olá {nome}! 🔔 A mensalidade de *{aluno}* está em atraso "
                    "(venceu em {vencimento}).\n\n💰 Valor: {valor}\n"
                    "🔗 Regularize pelo link:\n{link}\n\n_{academia}_"),
    },
    "confirmacao_pagamento": {
        "label": "Confirmação de pagamento",
        "default": ("Olá {nome}! ✅ Recebemos o pagamento da mensalidade de "
                    "*{aluno}* ({valor}). Muito obrigado!\n\n_{academia}_"),
    },
    "matricula": {
        "label": "Confirmação de matrícula",
        "default": ("Olá {nome}! 🥋 A matrícula de *{aluno}* foi recebida.\n"
                    "💰 Valor: {valor}\n🔗 Pague pelo link:\n{link}\n\n"
                    "Seja bem-vindo(a)! _{academia}_"),
    },
    "confirmacao_matricula": {
        "label": "Confirmação de pagamento da matrícula",
        "default": ("Olá {nome}! ✅ Recebemos o pagamento da matrícula de "
                    "*{aluno}* ({valor}). Está tudo certo!\n\n"
                    "Seja bem-vindo(a)! _{academia}_"),
    },
    "boas_vindas": {
        "label": "Boas-vindas ao novo aluno",
        "default": ("Olá {nome}! 🥋 Seja bem-vindo(a) à {academia}! "
                    "Estamos felizes em ter *{aluno}* na nossa equipe. "
                    "Qualquer dúvida, é só chamar por aqui."),
    },
    "aniversario": {
        "label": "Feliz aniversário (envio diário)",
        "default": ("Olá {nome}! 🎉 Hoje é um dia especial: *{aluno}* está de "
                    "aniversário!\n\nToda a equipe da {academia} deseja muitas "
                    "felicidades e um ano cheio de conquistas no tatame. 🥋🎂"),
    },
}

ORDEM = ["lembrete_vencimento", "lembrete_atraso", "confirmacao_pagamento",
         "matricula", "confirmacao_matricula", "boas_vindas", "aniversario"]


def padrao(tipo):
    return TIPOS.get(tipo, {}).get("default", "")


def carregar(academia_id):
    """Retorna {tipo: {'texto':..., 'ativo':bool}} com padrões onde não houver custom."""
    salvos = {}
    try:
        conn = get_db_connection(); cur = conn.cursor(dictionary=True)
        cur.execute("SELECT tipo, texto, ativo FROM whatsapp_templates WHERE id_academia=%s", (academia_id,))
        for r in cur.fetchall():
            salvos[r["tipo"]] = {"texto": r["texto"], "ativo": bool(r["ativo"])}
        cur.close(); conn.close()
    except Exception:
        pass
    out = {}
    for tipo in TIPOS:
        if tipo in salvos:
            out[tipo] = salvos[tipo]
        else:
            out[tipo] = {"texto": padrao(tipo), "ativo": True}
    return out


def obter(academia_id, tipo):
    """Retorna (texto, ativo) de um tipo, com fallback ao padrão."""
    try:
        conn = get_db_connection(); cur = conn.cursor(dictionary=True)
        cur.execute("SELECT texto, ativo FROM whatsapp_templates WHERE id_academia=%s AND tipo=%s", (academia_id, tipo))
        r = cur.fetchone()
        cur.close(); conn.close()
        if r:
            return r["texto"], bool(r["ativo"])
    except Exception:
        pass
    return padrao(tipo), True


def salvar(academia_id, tipo, texto, ativo):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute(
        """INSERT INTO whatsapp_templates (id_academia, tipo, texto, ativo)
           VALUES (%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE texto=VALUES(texto), ativo=VALUES(ativo)""",
        (academia_id, tipo, texto, 1 if ativo else 0),
    )
    conn.commit(); cur.close(); conn.close()


def render(texto, ctx):
    """Substitui os placeholders {chave} pelos valores do ctx (faltantes viram '')."""
    out = texto or ""
    for k in ["nome", "aluno", "valor", "vencimento", "link", "pix", "academia", "mes"]:
        out = out.replace("{" + k + "}", str(ctx.get(k, "") or ""))
    # remove linhas que ficaram com 'link' vazio (ex.: "🔗 ...\n{link}")
    linhas = [ln for ln in out.split("\n") if ln.strip() not in ("🔗 Pague pelo link:", "🔗 Regularize pelo link:")
              or ctx.get("link")]
    return "\n".join(linhas).strip()
