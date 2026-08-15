# -*- coding: utf-8 -*-
"""
Envio em massa (Web Push) no dia do aniversário: avisa todos os usuários com assinatura push
que uma pessoa está aniversariando hoje, com botão para abrir o modo ao vivo.

Disparo típico: cron HTTP GET em /push/dispatch-aniversariantes-hoje (ver blueprint notificacoes).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, List, Optional, Tuple

from config import get_db_connection
from utils.push_notifications import enviar_push_usuarios

logger = logging.getLogger(__name__)

# Ações: o service worker abre data.url para o clique no corpo e para action "abrir"
PUSH_ACOES_ANIV_DIA = [
    {"action": "abrir", "title": "Abrir e dar parabéns"},
]


def _garantir_tabela_log(cur) -> None:
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS push_aniversario_dia_envio (
                aluno_id   INT NOT NULL,
                ref_dia    DATE NOT NULL,
                enviado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (aluno_id, ref_dia)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    except Exception as exc:
        logger.warning("push_aniversario_dia_envio: não foi possível criar tabela: %s", exc)


def _listar_distinct_usuarios_com_push(cur) -> List[int]:
    cur.execute(
        """
        SELECT DISTINCT usuario_id
        FROM push_subscriptions
        WHERE usuario_id IS NOT NULL
        """
    )
    rows = cur.fetchall() or []
    out: List[int] = []
    for r in rows:
        try:
            if isinstance(r, dict):
                uid = int(r.get("usuario_id") or 0)
            else:
                uid = int(r[0] or 0)
        except (TypeError, ValueError, KeyError, IndexError):
            continue
        if uid > 0:
            out.append(uid)
    return sorted(set(out))


def _aniversariantes_hoje(cur, hoje: date) -> List[dict]:
    cur.execute(
        """
        SELECT id, nome, usuario_id
        FROM alunos
        WHERE ativo = 1
          AND data_nascimento IS NOT NULL
          AND MONTH(data_nascimento) = %s
          AND DAY(data_nascimento) = %s
        """,
        (hoje.month, hoje.day),
    )
    rows = cur.fetchall() or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            aid = int(r.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if aid <= 0:
            continue
        nome = (r.get("nome") or "").strip() or "Aniversariante"
        uid = r.get("usuario_id")
        try:
            usuario_id = int(uid) if uid is not None else 0
        except (TypeError, ValueError):
            usuario_id = 0
        out.append({"id": aid, "nome": nome, "usuario_id": usuario_id})
    return out


def _ja_enviou_hoje(cur, aluno_id: int, ref_dia: date) -> bool:
    try:
        cur.execute(
            """
            SELECT 1 FROM push_aniversario_dia_envio
            WHERE aluno_id = %s AND ref_dia = %s
            LIMIT 1
            """,
            (aluno_id, ref_dia),
        )
        return cur.fetchone() is not None
    except Exception as exc:
        logger.warning("push_aniversario_dia_envio leitura: %s", exc)
        return False


def _marcar_enviado(cur, aluno_id: int, ref_dia: date) -> None:
    cur.execute(
        """
        INSERT IGNORE INTO push_aniversario_dia_envio (aluno_id, ref_dia)
        VALUES (%s, %s)
        """,
        (aluno_id, ref_dia),
    )


def executar_push_aniversariantes_do_dia(
    ref_dia: Optional[date] = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Para cada aluno com aniversário em ref_dia (default: hoje), envia um push a todos os
    usuários que possuem assinatura push (exceto o próprio aniversariante, se tiver usuario_id).

    Retorna resumo JSON-safe para o endpoint de cron.
    """
    hoje = ref_dia or date.today()
    erros: List[str] = []
    enfileirados = 0
    total_dispositivos = 0
    pessoas = 0
    detalhes: List[dict] = []

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        _garantir_tabela_log(cur)
        conn.commit()

        destinatarios_todos = _listar_distinct_usuarios_com_push(cur)
        anivs = _aniversariantes_hoje(cur, hoje)

        for a in anivs:
            aluno_id = a["id"]
            nome = a["nome"]
            uid_aniv = a["usuario_id"]

            if not force and _ja_enviou_hoje(cur, aluno_id, hoje):
                detalhes.append(
                    {
                        "aluno_id": aluno_id,
                        "nome": nome,
                        "status": "ja_enviado",
                        "enviados": 0,
                    }
                )
                continue

            destinatarios = [u for u in destinatarios_todos if u != uid_aniv]
            if not destinatarios:
                detalhes.append(
                    {
                        "aluno_id": aluno_id,
                        "nome": nome,
                        "status": "sem_destinatarios",
                        "enviados": 0,
                    }
                )
                if not force:
                    _marcar_enviado(cur, aluno_id, hoje)
                conn.commit()
                continue

            titulo = f"🎂 {nome} faz aniversário hoje!"
            corpo = "Dê os parabéns no modo ao vivo. Toque em Abrir e dar parabéns."
            url_live = f"/aniversariante-live/?next=/painel/#/live/{aluno_id}"
            tag = f"aniv-dia-{aluno_id}-{hoje.isoformat()}"

            n = enviar_push_usuarios(
                destinatarios,
                titulo,
                corpo,
                url=url_live,
                tag=tag,
                actions=PUSH_ACOES_ANIV_DIA,
                erros_envio=erros,
                require_interaction=True,
            )
            total_dispositivos += n
            enfileirados += len(destinatarios)
            pessoas += 1
            _marcar_enviado(cur, aluno_id, hoje)
            conn.commit()

            detalhes.append(
                {
                    "aluno_id": aluno_id,
                    "nome": nome,
                    "status": "ok",
                    "enviados_dispositivos": n,
                    "destinatarios_usuarios": len(destinatarios),
                }
            )

        return {
            "ok": True,
            "ref_dia": hoje.isoformat(),
            "aniversariantes_encontrados": len(anivs),
            "push_enviado_para_pessoas": pessoas,
            "dispositivos_alcancados": total_dispositivos,
            "usuarios_contemplados_envio": enfileirados,
            "detalhes": detalhes[:40],
            "erros_amostra": list(dict.fromkeys(erros))[:8],
        }
    finally:
        cur.close()
        conn.close()


def validar_token_cron(token_param: Optional[str]) -> Tuple[bool, str]:
    import os

    expected = (os.environ.get("CRON_PUSH_TOKEN") or "").strip()
    if not expected:
        return False, "CRON_PUSH_TOKEN não configurado no servidor"
    if not token_param or token_param.strip() != expected:
        return False, "token inválido"
    return True, ""
