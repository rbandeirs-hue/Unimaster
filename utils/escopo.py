# -*- coding: utf-8 -*-
"""Quais academias o usuário logado pode ver.

Por que este arquivo existe
---------------------------
Esta resolução está copiada em dez blueprints, cada cópia com pequenas
diferenças. Isso já produziu um bug real: um administrador vinculado a três
academias não enxergava as outras nove, porque a checagem de `usuarios_academias`
vinha antes da checagem de papel. Corrigir exigiu mexer em nove arquivos, e a
décima cópia continuava lá.

O módulo de estoque é o primeiro a usar esta versão única. As dez cópias
existentes NÃO foram tocadas — migrar todas de uma vez seria uma mudança de
risco alto sem pedido. O que este arquivo garante é que o problema pare de se
multiplicar.

Regras, na ordem em que valem:

1. admin vê todas as academias, sempre. Vínculo explícito não o limita;
2. quem tem vínculo em `usuarios_academias` vê o que está vinculado;
3. sem vínculo, o papel decide: federação vê as academias das suas associações,
   associação vê as suas, gestor/professor não vê nada até ser vinculado.
"""
from flask import session
from flask_login import current_user

from config import get_db_connection


def academias_do_usuario(usuario=None):
    """Lista de ids de academia que este usuário pode ver. Nunca levanta."""
    usuario = usuario or current_user
    try:
        if not getattr(usuario, "is_authenticated", False):
            return []
    except Exception:
        return []

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        eh_admin = usuario.has_role("admin")

        if eh_admin:
            cur.execute("SELECT id FROM academias ORDER BY nome")
            return [r[0] for r in cur.fetchall() or []]

        cur.execute(
            "SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s "
            "ORDER BY academia_id", (usuario.id,))
        vinculadas = [r[0] for r in cur.fetchall() or []]
        if vinculadas:
            return vinculadas

        if usuario.has_role("gestor_federacao"):
            cur.execute(
                """SELECT ac.id FROM academias ac
                   JOIN associacoes a ON a.id = ac.id_associacao
                   WHERE a.id_federacao = %s ORDER BY ac.nome""",
                (getattr(usuario, "id_federacao", None),))
            return [r[0] for r in cur.fetchall() or []]

        if usuario.has_role("gestor_associacao"):
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome",
                        (getattr(usuario, "id_associacao", None),))
            return [r[0] for r in cur.fetchall() or []]

        # Gestor de academia e professor sem vínculo não veem nada — e é o
        # correto: o vínculo é o que diz de qual academia a pessoa é.
        return []
    except Exception:
        return []
    finally:
        cur.close()
        conn.close()


def pode_ver_academia(academia_id, usuario=None):
    """A checagem que toda rota deve fazer antes de ler ou gravar.

    O id da academia chega por query string ou por campo de formulário, os dois
    editáveis por quem quiser. Confiar neles é o caminho mais curto para um
    gestor ler o estoque da academia vizinha.
    """
    if not academia_id:
        return False
    try:
        return int(academia_id) in academias_do_usuario(usuario)
    except (TypeError, ValueError):
        return False


def academia_corrente():
    """A academia em que o usuário está trabalhando agora, se houver."""
    for chave in ("academia_gerenciamento_id", "finance_academia_id"):
        valor = session.get(chave)
        if valor:
            return int(valor)
    ids = academias_do_usuario()
    return ids[0] if len(ids) == 1 else None
