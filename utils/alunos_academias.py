"""
Vínculo de aluno com mais de uma academia.

Regras que valem em todo o sistema:

  * `alunos.id_academia` continua sendo a academia PRINCIPAL. É ela que conta nos
    totais e relatórios, para que a soma das academias não fique maior que o
    total real de alunos da associação.
  * `alunos_academias` guarda todos os vínculos, inclusive o principal.
  * Um aluno só pode ser vinculado a academias da MESMA associação — vincular
    entre associações diferentes misturaria escopos de acesso.

Uso típico numa listagem que deve enxergar também os alunos vinculados:

    from utils.alunos_academias import filtro_alunos_da_academia
    sql, params = filtro_alunos_da_academia(academia_id)
    cur.execute(f"SELECT * FROM alunos a WHERE {sql} AND a.ativo = 1", params)
"""


def filtro_alunos_da_academia(academia_id, alias="a"):
    """
    (trecho_sql, parâmetros) que casa os alunos de uma academia — os que a têm
    como principal e os vinculados a ela.

    Use no lugar de `a.id_academia = %s` nas telas operacionais (presença,
    turmas, eventos, financeiro). Em contagens e relatórios, continue usando
    `id_academia` direto, para o aluno contar uma vez só.
    """
    trecho = (f"({alias}.id_academia = %s OR EXISTS ("
              f"SELECT 1 FROM alunos_academias aa "
              f"WHERE aa.aluno_id = {alias}.id AND aa.academia_id = %s))")
    return trecho, [academia_id, academia_id]


def aluno_vinculado_a_academia(cur, aluno_id, academia_id):
    """True se o aluno tem a academia como principal OU como vínculo adicional.

    Use em checagens de permissão/escopo operacional (editar, excluir, financeiro)
    para que o gestor de uma academia vinculada — não só a principal — enxergue e
    opere o aluno.
    """
    if not aluno_id or not academia_id:
        return False
    cur.execute(
        """SELECT 1 FROM alunos a
           WHERE a.id = %s
             AND (a.id_academia = %s
                  OR EXISTS (SELECT 1 FROM alunos_academias aa
                             WHERE aa.aluno_id = a.id AND aa.academia_id = %s))
           LIMIT 1""",
        (aluno_id, academia_id, academia_id))
    return cur.fetchone() is not None


def academias_do_aluno(cur, aluno_id):
    """[{id, nome, principal}] das academias do aluno, principal primeiro."""
    cur.execute(
        """SELECT ac.id, ac.nome, aa.principal
           FROM alunos_academias aa
           JOIN academias ac ON ac.id = aa.academia_id
           WHERE aa.aluno_id = %s
           ORDER BY aa.principal DESC, ac.nome""",
        (aluno_id,))
    return cur.fetchall()


def academias_disponiveis_para_vinculo(cur, aluno_id):
    """
    Academias da mesma associação do aluno às quais ele ainda não está vinculado.
    """
    cur.execute(
        """SELECT ac.id, ac.nome
           FROM academias ac
           WHERE ac.id_associacao = (
                 SELECT COALESCE(a.id_associacao, ac2.id_associacao)
                 FROM alunos a
                 LEFT JOIN academias ac2 ON ac2.id = a.id_academia
                 WHERE a.id = %s)
             AND ac.id NOT IN (SELECT academia_id FROM alunos_academias WHERE aluno_id = %s)
           ORDER BY ac.nome""",
        (aluno_id, aluno_id))
    return cur.fetchall()


def vincular(cur, aluno_id, academia_id, usuario_id=None):
    """
    Vincula o aluno a uma academia adicional. Retorna (ok, mensagem).

    Recusa academia de outra associação: o vínculo é o que dá acesso aos dados
    do aluno, e atravessar associações abriria os dados para fora do escopo.
    """
    cur.execute(
        """SELECT ac.id, ac.nome, ac.id_associacao,
                  (SELECT COALESCE(a.id_associacao, ac2.id_associacao)
                   FROM alunos a LEFT JOIN academias ac2 ON ac2.id = a.id_academia
                   WHERE a.id = %s) AS assoc_aluno
           FROM academias ac WHERE ac.id = %s""",
        (aluno_id, academia_id))
    destino = cur.fetchone()
    if not destino:
        return False, "Academia não encontrada."
    if destino["assoc_aluno"] and destino["id_associacao"] != destino["assoc_aluno"]:
        return False, "Só é possível vincular a academias da mesma associação."

    cur.execute(
        """INSERT IGNORE INTO alunos_academias (aluno_id, academia_id, principal, criado_por)
           VALUES (%s, %s, 0, %s)""",
        (aluno_id, academia_id, usuario_id))
    return True, f"Aluno vinculado a {destino['nome']}."


def desvincular(cur, aluno_id, academia_id):
    """Remove um vínculo adicional. A academia principal não pode ser removida."""
    cur.execute(
        "SELECT principal FROM alunos_academias WHERE aluno_id = %s AND academia_id = %s",
        (aluno_id, academia_id))
    linha = cur.fetchone()
    if not linha:
        return False, "Vínculo não encontrado."
    if linha["principal"]:
        return False, ("Esta é a academia principal do aluno. Para trocá-la, use a "
                       "transferência de academia.")
    cur.execute("DELETE FROM alunos_academias WHERE aluno_id = %s AND academia_id = %s",
                (aluno_id, academia_id))
    return True, "Vínculo removido."


def sincronizar_principal(cur, aluno_id, academia_id):
    """
    Mantém `alunos_academias` coerente quando a academia principal muda
    (cadastro novo ou transferência).
    """
    if not academia_id:
        return
    cur.execute("UPDATE alunos_academias SET principal = 0 WHERE aluno_id = %s", (aluno_id,))
    cur.execute(
        """INSERT INTO alunos_academias (aluno_id, academia_id, principal)
           VALUES (%s, %s, 1)
           ON DUPLICATE KEY UPDATE principal = 1""",
        (aluno_id, academia_id))
