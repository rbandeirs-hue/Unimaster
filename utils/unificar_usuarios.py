# -*- coding: utf-8 -*-
"""
Detecção e unificação de cadastros duplicados de usuário.

Uso:
    grupos = encontrar_duplicados(cursor)
    relatorio = unificar(cursor, principal_id, perdedores_ids)

A função `unificar` move TODOS os vínculos dos usuários "perdedores" para o
"principal" e em seguida apaga os perdedores. As tabelas com restrição UNIQUE
em `usuario_id` (alunos / professores) são tratadas especialmente: se o
principal já tiver um registro ali, o vínculo do perdedor é transferido para
o principal apenas quando ele estiver livre; caso contrário o registro do
perdedor é desvinculado (usuario_id → NULL) para preservar o histórico.

NÃO faz commit nem rollback — quem chama decide.
"""

from typing import List, Dict, Any


# Tabelas com PK composta: ao migrar, primeiro INSERT IGNORE pra evitar duplicar
# a chave; depois DELETE do que sobrou nos perdedores.
_TABELAS_PK_COMPOSTA = [
    ("roles_usuario", ["usuario_id", "role_id"]),
    ("usuarios_academias", ["usuario_id", "academia_id"]),
    ("in_app_notif_estado", ["usuario_id", "ref_tipo", "ref_id"]),
]

# Tabelas onde basta atualizar usuario_id (sem unique problemática).
_TABELAS_SIMPLES = [
    "responsavel_alunos",
    "visitantes",
    "aniversario_live_eventos",
    "aniversario_mensagens",
    "password_reset_tokens",
    "push_subscriptions",
]

# Tabelas com UNIQUE em usuario_id — só migra se o principal estiver livre.
_TABELAS_USUARIO_UNICO = ["alunos", "professores"]

# Campos do próprio registro de `usuarios` que devem ser copiados do perdedor
# para o principal QUANDO o principal estiver vazio. Assim, ao fundir, os
# dados que existiam só no perdedor (ex.: foto, email, cpf, vínculos hierárquicos)
# não se perdem.
_CAMPOS_USUARIO_FILL = [
    "foto",
    "email",
    "cpf",
    "id_federacao",
    "id_associacao",
    "id_academia",
]


def _execute_safe(cursor, sql, params=()):
    try:
        cursor.execute(sql, params)
    except Exception:
        # Tabelas opcionais (ex.: in_app_notif_estado) podem não existir em
        # ambientes antigos. Ignoramos silenciosamente.
        pass


def encontrar_duplicados(cursor) -> List[Dict[str, Any]]:
    """Retorna grupos de usuários potencialmente duplicados.

    Critérios:
        1. Mesmo e-mail (case-insensitive, não-vazio).
        2. Mesmo CPF em alunos vinculados a usuários diferentes.
    """
    grupos: List[Dict[str, Any]] = []

    # 1) Por e-mail
    cursor.execute(
        """
        SELECT LOWER(email) AS chave, COUNT(*) AS qtd
        FROM usuarios
        WHERE email IS NOT NULL AND email <> ''
        GROUP BY LOWER(email)
        HAVING qtd > 1
        ORDER BY qtd DESC
        """
    )
    emails_dup = [r["chave"] for r in cursor.fetchall()]
    for email in emails_dup:
        cursor.execute(
            """
            SELECT id, nome, email, cpf, foto, COALESCE(ativo,1) AS ativo, criado_em
            FROM usuarios
            WHERE LOWER(email) = %s
            ORDER BY criado_em ASC, id ASC
            """,
            (email,),
        )
        usuarios = cursor.fetchall()
        if len(usuarios) > 1:
            grupos.append({
                "criterio": "email",
                "chave": email,
                "usuarios": usuarios,
            })

    # 2) Por CPF do aluno apontando para usuários diferentes
    cursor.execute(
        """
        SELECT REGEXP_REPLACE(COALESCE(cpf,''), '[^0-9]', '') AS cpf_n
        FROM alunos
        WHERE usuario_id IS NOT NULL
          AND cpf IS NOT NULL AND cpf <> ''
        GROUP BY cpf_n
        HAVING COUNT(DISTINCT usuario_id) > 1 AND CHAR_LENGTH(cpf_n) = 11
        """
    )
    cpfs_dup = [r["cpf_n"] for r in cursor.fetchall()]
    for cpf in cpfs_dup:
        cursor.execute(
            """
            SELECT u.id, u.nome, u.email, u.cpf, u.foto, COALESCE(u.ativo,1) AS ativo, u.criado_em
            FROM usuarios u
            JOIN alunos a ON a.usuario_id = u.id
            WHERE REGEXP_REPLACE(COALESCE(a.cpf,''), '[^0-9]', '') = %s
            ORDER BY u.criado_em ASC, u.id ASC
            """,
            (cpf,),
        )
        usuarios = cursor.fetchall()
        if len(usuarios) > 1:
            grupos.append({
                "criterio": "cpf_aluno",
                "chave": cpf,
                "usuarios": usuarios,
            })

    return grupos


def _migrar_pk_composta(cursor, perdedor: int, principal: int):
    for tabela, colunas in _TABELAS_PK_COMPOSTA:
        try:
            cur_cols = ", ".join(colunas)
            sel_cols = ", ".join(
                f"{principal}" if c == "usuario_id" else c for c in colunas
            )
            # INSERT IGNORE pega o que ainda não existe no principal
            sql_ins = (
                f"INSERT IGNORE INTO {tabela} ({cur_cols}) "
                f"SELECT {sel_cols} FROM {tabela} WHERE usuario_id = %s"
            )
            cursor.execute(sql_ins, (perdedor,))
            cursor.execute(
                f"DELETE FROM {tabela} WHERE usuario_id = %s",
                (perdedor,),
            )
        except Exception:
            # tabela inexistente / sem coluna esperada — pular
            continue


def _migrar_simples(cursor, perdedor: int, principal: int):
    for tabela in _TABELAS_SIMPLES:
        _execute_safe(
            cursor,
            f"UPDATE {tabela} SET usuario_id = %s WHERE usuario_id = %s",
            (principal, perdedor),
        )


def _completar_campos_principal(cursor, perdedor: int, principal: int) -> List[str]:
    """Para cada campo em _CAMPOS_USUARIO_FILL: se o principal está vazio e o
    perdedor tem valor, copia o valor do perdedor para o principal.
    Retorna lista de campos copiados (para log).
    """
    avisos = []
    cols = ", ".join(_CAMPOS_USUARIO_FILL)
    cursor.execute(f"SELECT {cols} FROM usuarios WHERE id = %s", (principal,))
    p_row = cursor.fetchone() or {}
    cursor.execute(f"SELECT {cols} FROM usuarios WHERE id = %s", (perdedor,))
    l_row = cursor.fetchone() or {}

    def _vazio(v):
        return v is None or (isinstance(v, str) and v.strip() == "")

    atualizar = {}
    for campo in _CAMPOS_USUARIO_FILL:
        v_p = p_row.get(campo) if isinstance(p_row, dict) else None
        v_l = l_row.get(campo) if isinstance(l_row, dict) else None
        if _vazio(v_p) and not _vazio(v_l):
            atualizar[campo] = v_l

    if atualizar:
        # CPF é UNIQUE — só copia se ninguém mais (além do perdedor) tem esse CPF.
        if "cpf" in atualizar:
            cursor.execute(
                "SELECT id FROM usuarios WHERE cpf = %s AND id NOT IN (%s, %s) LIMIT 1",
                (atualizar["cpf"], principal, perdedor),
            )
            if cursor.fetchone():
                # Outro usuário já tem esse CPF — não copia para evitar conflito.
                avisos.append(
                    f"CPF {atualizar['cpf']} pertence a outro usuário; não copiei do perdedor."
                )
                atualizar.pop("cpf", None)

        if atualizar:
            sets = ", ".join(f"{c}=%s" for c in atualizar.keys())
            valores = list(atualizar.values()) + [principal]
            try:
                # Antes de copiar campos UNIQUE (cpf), zerar o do perdedor para
                # liberar a restrição.
                if "cpf" in atualizar:
                    cursor.execute(
                        "UPDATE usuarios SET cpf = NULL WHERE id = %s",
                        (perdedor,),
                    )
                cursor.execute(
                    f"UPDATE usuarios SET {sets} WHERE id = %s",
                    tuple(valores),
                )
                avisos.append(
                    "Campos copiados do perdedor para o principal: "
                    + ", ".join(atualizar.keys())
                )
            except Exception as e:
                avisos.append(f"Falha ao copiar campos: {e}")

    return avisos


def _migrar_usuario_unico(cursor, perdedor: int, principal: int) -> List[str]:
    """
    Para alunos/professores: se o principal está livre, migra; caso contrário,
    desvincula o registro do perdedor (usuario_id → NULL) e devolve um aviso.
    """
    avisos = []
    for tabela in _TABELAS_USUARIO_UNICO:
        try:
            cursor.execute(
                f"SELECT id FROM {tabela} WHERE usuario_id = %s",
                (principal,),
            )
            principal_tem = cursor.fetchone() is not None
            cursor.execute(
                f"SELECT id FROM {tabela} WHERE usuario_id = %s",
                (perdedor,),
            )
            perdedor_tem = cursor.fetchone() is not None

            if perdedor_tem and not principal_tem:
                cursor.execute(
                    f"UPDATE {tabela} SET usuario_id = %s WHERE usuario_id = %s",
                    (principal, perdedor),
                )
            elif perdedor_tem and principal_tem:
                # Não dá pra ter dois — desvincula o do perdedor (preserva histórico).
                cursor.execute(
                    f"UPDATE {tabela} SET usuario_id = NULL WHERE usuario_id = %s",
                    (perdedor,),
                )
                avisos.append(
                    f"{tabela}: ambos os usuários tinham registro vinculado; "
                    f"o do usuário {perdedor} foi desvinculado para preservar o histórico."
                )
        except Exception as e:
            avisos.append(f"{tabela}: erro ao migrar — {e}")
    return avisos


def unificar(cursor, principal_id: int, perdedores_ids: List[int]) -> Dict[str, Any]:
    """Funde os usuários `perdedores_ids` no `principal_id`. Sem commit/rollback."""
    relatorio = {"avisos": [], "perdedores_apagados": [], "ok": False}

    if not perdedores_ids:
        relatorio["avisos"].append("Nenhum perdedor informado.")
        return relatorio
    if principal_id in perdedores_ids:
        raise ValueError("O usuário principal não pode estar entre os perdedores.")

    # Garantir que o principal existe
    cursor.execute("SELECT id FROM usuarios WHERE id = %s", (principal_id,))
    if not cursor.fetchone():
        raise ValueError(f"Usuário principal {principal_id} não encontrado.")

    for perdedor in perdedores_ids:
        cursor.execute("SELECT id FROM usuarios WHERE id = %s", (perdedor,))
        if not cursor.fetchone():
            relatorio["avisos"].append(f"Usuário {perdedor} já não existe — pulando.")
            continue

        # 1) Copiar para o principal os campos que ele tem vazios mas o perdedor preenche
        #    (foto, e-mail, CPF, hierarquia federacao/associacao/academia).
        relatorio["avisos"].extend(_completar_campos_principal(cursor, perdedor, principal_id))

        # 2) Migrar vínculos
        relatorio["avisos"].extend(_migrar_usuario_unico(cursor, perdedor, principal_id))
        _migrar_pk_composta(cursor, perdedor, principal_id)
        _migrar_simples(cursor, perdedor, principal_id)

        # 3) Apagar o perdedor
        try:
            cursor.execute("DELETE FROM usuarios WHERE id = %s", (perdedor,))
            relatorio["perdedores_apagados"].append(perdedor)
        except Exception as e:
            relatorio["avisos"].append(
                f"Não foi possível apagar o usuário {perdedor}: {e}"
            )

    relatorio["ok"] = True
    return relatorio
