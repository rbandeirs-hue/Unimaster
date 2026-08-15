# -*- coding: utf-8 -*-
"""Links curtos de pagamento.

O boleto/PIX dos gateways vem com URLs enormes — a do Cora passa de 180
caracteres, cheia de parâmetros do Google Storage, e polui a mensagem de
WhatsApp. Aqui geramos um link no nosso próprio domínio:

    https://seu-dominio.com.br/p/a7Bk3xQ2

O redirecionamento resolve a URL do gateway **na hora do clique**, lendo o
registro da cobrança. Duas consequências boas: o link não vence quando a
cobrança é reemitida, e o mesmo token serve para sempre àquela mensalidade.

A base do domínio vem de PUBLIC_BASE_URL (necessária fora de request, como no
cron dos lembretes); dentro de uma request usamos o host da própria requisição.
"""
import os
import secrets
import string

from config import get_db_connection

_ALFABETO = string.ascii_letters + string.digits
TOKEN_TAMANHO = 8

ORIGENS = {
    "mensalidade": ("mensalidade_aluno", "id"),
    "avulsa": ("cobranca_avulsa", "id"),
}


def _novo_token():
    return "".join(secrets.choice(_ALFABETO) for _ in range(TOKEN_TAMANHO))


def base_url():
    """Base pública do sistema, sem barra no fim."""
    env = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    try:
        from flask import request
        if request:
            return request.url_root.rstrip("/")
    except Exception:
        pass
    return ""


def obter_token(origem, registro_id, academia_id=None):
    """Token do registro, criando na primeira vez. None se a tabela não existir."""
    if origem not in ORIGENS or not registro_id:
        return None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT token FROM pagamento_links WHERE origem=%s AND registro_id=%s",
            (origem, registro_id),
        )
        row = cur.fetchone()
        if row:
            return row["token"]

        # Colisão de token é improvável, mas a chave é única — tenta algumas vezes.
        for _ in range(5):
            token = _novo_token()
            try:
                cur.execute(
                    """INSERT INTO pagamento_links (token, origem, registro_id, id_academia)
                       VALUES (%s, %s, %s, %s)""",
                    (token, origem, registro_id, academia_id),
                )
                conn.commit()
                return token
            except Exception as e:
                conn.rollback()
                if "uk_pagamento_links_token" in str(e):
                    continue
                if "uk_pagamento_links_registro" in str(e):
                    # Corrida: outro processo criou primeiro — usa o dele.
                    cur.execute(
                        "SELECT token FROM pagamento_links WHERE origem=%s AND registro_id=%s",
                        (origem, registro_id),
                    )
                    row = cur.fetchone()
                    return row["token"] if row else None
                raise
        return None
    except Exception:
        return None
    finally:
        cur.close()
        conn.close()


def encurtar(origem, registro_id, academia_id=None):
    """URL curta absoluta do registro, ou None se não der para montar."""
    token = obter_token(origem, registro_id, academia_id)
    if not token:
        return None
    base = base_url()
    return f"{base}/p/{token}" if base else None


def resolver(token):
    """Destino de um token: a URL de pagamento vigente da cobrança.

    Retorna (url, origem, registro_id). url vem None quando a cobrança existe mas
    ainda não tem link de gateway — quem chama decide o que mostrar.
    """
    if not token:
        return None, None, None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT origem, registro_id FROM pagamento_links WHERE token=%s", (token,)
        )
        link = cur.fetchone()
        if not link:
            return None, None, None

        origem, registro_id = link["origem"], link["registro_id"]
        tabela = ORIGENS.get(origem, (None,))[0]
        if not tabela:
            return None, origem, registro_id

        if tabela == "mensalidade_aluno":
            cur.execute(
                """SELECT asaas_boleto_url, cora_boleto_url, inter_boleto_url
                   FROM mensalidade_aluno WHERE id=%s""",
                (registro_id,),
            )
        else:
            cur.execute(
                "SELECT asaas_boleto_url FROM cobranca_avulsa WHERE id=%s", (registro_id,)
            )
        reg = cur.fetchone() or {}
        url = (reg.get("asaas_boleto_url") or reg.get("cora_boleto_url")
               or reg.get("inter_boleto_url") or "").strip() or None

        try:
            cur.execute(
                """UPDATE pagamento_links
                   SET acessos = acessos + 1, ultimo_acesso = NOW() WHERE token=%s""",
                (token,),
            )
            conn.commit()
        except Exception:
            conn.rollback()

        return url, origem, registro_id
    except Exception:
        return None, None, None
    finally:
        cur.close()
        conn.close()
