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


def vincular(cur, aluno_id, academia_id, usuario_id=None, permitir_outra_associacao=False):
    """
    Vincula o aluno a uma academia adicional. Retorna (ok, mensagem).

    Recusa academia de outra associação: o vínculo é o que dá acesso aos dados
    do aluno, e atravessar associações abriria os dados para fora do escopo.
    `permitir_outra_associacao` só é usado quando a própria academia cadastra a
    pessoa e prova que a conhece (nome e nascimento conferem com o CPF) — ver
    `matricular_pessoa_existente`.
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
    if (not permitir_outra_associacao and destino["assoc_aluno"]
            and destino["id_associacao"] != destino["assoc_aluno"]):
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


# ------------------------------------------------- pessoa já cadastrada (CPF)
def _normalizar_nome(nome):
    import unicodedata
    txt = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode()
    return " ".join(txt.lower().split())


def mesma_pessoa(existente, nome, data_nascimento):
    """O nome e o nascimento digitados conferem com o cadastro deste CPF?

    É a prova de que a academia está cadastrando a pessoa que tem na frente, e
    não pescando dados alheios pelo CPF. Nascimento tem de bater exato; o nome,
    sem acento/caixa, igual ou com o mesmo primeiro e último nome.
    """
    nasc_ex = existente.get("data_nascimento")
    nasc_ex = str(nasc_ex)[:10] if nasc_ex else ""
    if not nasc_ex or str(data_nascimento or "")[:10] != nasc_ex:
        return False
    a, b = _normalizar_nome(existente.get("nome")), _normalizar_nome(nome)
    if not a or not b:
        return False
    if a == b:
        return True
    pa, pb = a.split(), b.split()
    return pa[0] == pb[0] and pa[-1] == pb[-1]


def matricular_pessoa_existente(cur, aluno_id, academia_id, modalidades_ids=(), turma_ids=(),
                                faixas=None, usuario_id=None, datas=None):
    """Uma pessoa, várias matrículas: liga a pessoa já cadastrada (mesmo CPF) a
    esta academia, nas modalidades e turmas escolhidas, sem duplicar o cadastro.

    Não mexe nos dados pessoais nem no que é de outra academia (turmas,
    financeiro, presenças). A faixa só é gravada na modalidade que ainda não tem
    faixa — a de judô é a mesma pessoa em qualquer academia. Devolve (ok, msg).
    """
    ok, msg = vincular(cur, aluno_id, academia_id, usuario_id, permitir_outra_associacao=True)
    if not ok:
        return ok, msg
    for mid in {int(m) for m in modalidades_ids or [] if str(m).strip().isdigit()}:
        cur.execute("INSERT IGNORE INTO aluno_modalidades (aluno_id, modalidade_id) VALUES (%s, %s)",
                    (aluno_id, mid))
    for tid in {int(t) for t in turma_ids or [] if str(t).strip().isdigit()}:
        # Só turma desta academia.
        cur.execute(
            """INSERT IGNORE INTO aluno_turmas (aluno_id, TurmaID)
               SELECT %s, TurmaID FROM turmas WHERE TurmaID = %s AND id_academia = %s""",
            (aluno_id, tid, academia_id))
    if faixas:
        from utils import graduacao_modalidade as grad_mod
        atuais = {f["modalidade_id"]: f["graduacao_id"]
                  for f in grad_mod.faixas_por_modalidade(cur, [aluno_id]).get(int(aluno_id), [])}
        novas = {m: g for m, g in faixas.items() if g and not atuais.get(int(m))}
        grad_mod.gravar_faixas(cur, aluno_id, novas,
                               {int(m): (datas or {}).get(int(m)) for m in novas} if datas else None)
    return True, msg
