# -*- coding: utf-8 -*-
"""Tabela e constantes para notificações in-app (lida / oculta)."""

REF_TIPO_PARABENS_LIVE = "parabens_live"
# ref_id = alunos.id — lembrete “aniversariante hoje” para todos os utilizadores
REF_TIPO_ANIVERSARIO_HOJE = "aniversario_hoje"


def ensure_in_app_notif_estado_table(cur) -> None:
    """CREATE IF NOT EXISTS — idempotente (primeira carga sem migration manual)."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS in_app_notif_estado (
          usuario_id INT NOT NULL,
          ref_tipo     VARCHAR(32) NOT NULL DEFAULT 'parabens_live',
          ref_id       BIGINT UNSIGNED NOT NULL,
          lida         TINYINT(1) NOT NULL DEFAULT 0,
          oculta       TINYINT(1) NOT NULL DEFAULT 0,
          atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (usuario_id, ref_tipo, ref_id),
          KEY idx_usuario_lida_oculta (usuario_id, lida, oculta)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
