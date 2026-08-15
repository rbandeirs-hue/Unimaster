# -*- coding: utf-8 -*-
"""
Sincronização de foto entre usuários e alunos.

Regra:
    - Quando o usuário tem cadastro de aluno vinculado (alunos.usuario_id == usuarios.id),
      a foto deve ser a mesma em ambas as tabelas. Atualizar em um lado propaga para o outro.
    - Professor não tem coluna foto na tabela professores — a foto exibida no painel
      de professores já é puxada via JOIN do aluno vinculado pelo mesmo usuario_id.
      Portanto, sincronizar usuarios↔alunos cobre os três casos (admin/gestor com
      aluno+professor, só aluno, só professor com aluno) sem dobrar lógica.
    - Responsáveis: a foto do responsável não é propagada para os alunos sob sua
      responsabilidade — esse vínculo é via responsavel_alunos, não via alunos.usuario_id.

As funções abaixo recebem um cursor já aberto e NÃO fazem commit; o chamador decide
quando commitar/rollback. Nenhuma delas falha se a tabela alvo não tiver a foto.
"""


def propagar_foto_usuario_para_aluno(cursor, user_id, foto):
    """Atualiza alunos.foto de TODOS os alunos vinculados a este usuário.

    Em geral só existe 1 aluno por usuario_id (UNIQUE comportamental), mas
    cobrimos múltiplos por segurança.
    """
    if not user_id or foto is None:
        return
    cursor.execute(
        "UPDATE alunos SET foto = %s WHERE usuario_id = %s",
        (foto, user_id),
    )


def propagar_foto_aluno_para_usuario(cursor, aluno_id, foto):
    """Atualiza usuarios.foto do usuário vinculado ao aluno (se houver)."""
    if not aluno_id or foto is None:
        return
    cursor.execute("SELECT usuario_id FROM alunos WHERE id = %s", (aluno_id,))
    row = cursor.fetchone()
    if not row:
        return
    user_id = row.get("usuario_id") if isinstance(row, dict) else row[0]
    if not user_id:
        return
    cursor.execute(
        "UPDATE usuarios SET foto = %s WHERE id = %s",
        (foto, user_id),
    )


def sincronizar_foto(cursor, *, user_id=None, aluno_id=None, foto=None):
    """Conveniência: atualiza o lado oposto a partir do lado fornecido.

    Use APÓS gravar a foto do lado de origem. Ex.:
        cur.execute("UPDATE usuarios SET foto = %s WHERE id = %s", (f, uid))
        sincronizar_foto(cur, user_id=uid, foto=f)
    """
    if foto is None:
        return
    if user_id:
        propagar_foto_usuario_para_aluno(cursor, user_id, foto)
    if aluno_id:
        propagar_foto_aluno_para_usuario(cursor, aluno_id, foto)
