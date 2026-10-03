# -*- coding: utf-8 -*-
"""
Aniversariantes do mês filtrados por escopo:
  - aluno      → alunos das mesmas turmas (função ``aniversariantes_do_mes(..., "aluno")``)
  - aluno academias → ``aniversariantes_do_mes_aluno_associacao`` (painel / live modo aluno):
                 só as academias do próprio aluno, nunca as outras da associação
  - professor  → alunos das turmas que leciona (professor_id = professores.id)
  - professor ampliado → todos os alunos ativos das academias onde leciona (lista live)
  - academia   → todos os alunos da academia (com turma vinculada), inclusive os
                 vinculados a ela em ``alunos_academias``
"""
import logging
from datetime import date
from config import get_db_connection

logger = logging.getLogger(__name__)


def _query(sql: str, params: tuple) -> list:
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception as exc:
        logger.error("aniversariantes query error: %s", exc)
        return []
    finally:
        cur.close(); db.close()


def aniversariantes_do_mes(usuario_id: int, modo: str, mes: int = None, academia_id: int = None) -> list:
    """
    Retorna lista de dicts: id, nome, foto, data_nascimento, id_academia, turmas (str)
    modo: 'aluno' | 'professor' | 'academia' | 'gestor'
    """
    if mes is None:
        mes = date.today().month

    if modo == "aluno":
        # Busca o aluno_id correspondente ao usuario_id
        sql_aid = "SELECT id FROM alunos WHERE usuario_id = %s AND ativo = 1 LIMIT 1"
        rows = _query(sql_aid, (usuario_id,))
        if not rows:
            return []
        aluno_id = rows[0]["id"]

        sql = """
            SELECT DISTINCT
                a.id, a.nome, a.foto, a.data_nascimento, a.id_academia,
                GROUP_CONCAT(t.Nome ORDER BY t.Nome SEPARATOR ', ') AS turmas
            FROM alunos a
            JOIN aluno_turmas at2 ON at2.aluno_id = a.id
            JOIN turmas t ON t.TurmaID = at2.TurmaID
            WHERE MONTH(a.data_nascimento) = %s
              AND a.ativo = 1
              AND at2.TurmaID IN (
                  SELECT TurmaID FROM aluno_turmas WHERE aluno_id = %s
              )
            GROUP BY a.id, a.nome, a.foto, a.data_nascimento, a.id_academia
            ORDER BY DAY(a.data_nascimento), a.nome
        """
        return _query(sql, (mes, aluno_id))

    elif modo == "professor":
        prows = _query(
            "SELECT id FROM professores WHERE usuario_id = %s AND ativo = 1",
            (usuario_id,),
        )
        if not prows:
            return []
        pids = tuple(int(r["id"]) for r in prows)
        ph = ",".join(["%s"] * len(pids))
        sql = f"""
            SELECT DISTINCT
                a.id, a.nome, a.foto, a.data_nascimento, a.id_academia,
                GROUP_CONCAT(t.Nome ORDER BY t.Nome SEPARATOR ', ') AS turmas
            FROM alunos a
            JOIN aluno_turmas at2 ON at2.aluno_id = a.id
            JOIN turmas t ON t.TurmaID = at2.TurmaID
            WHERE MONTH(a.data_nascimento) = %s
              AND a.ativo = 1
              AND at2.TurmaID IN (
                  SELECT TurmaID FROM turma_professor WHERE professor_id IN ({ph})
              )
            GROUP BY a.id, a.nome, a.foto, a.data_nascimento, a.id_academia
            ORDER BY DAY(a.data_nascimento), a.nome
        """
        return _query(sql, (mes,) + pids)

    else:  # academia / gestor
        if not academia_id:
            return []
        sql = """
            SELECT DISTINCT
                a.id, a.nome, a.foto, a.data_nascimento, a.id_academia,
                GROUP_CONCAT(t.Nome ORDER BY t.Nome SEPARATOR ', ') AS turmas
            FROM alunos a
            JOIN aluno_turmas at2 ON at2.aluno_id = a.id
            JOIN turmas t ON t.TurmaID = at2.TurmaID
            WHERE MONTH(a.data_nascimento) = %s
              AND a.ativo = 1
              AND (a.id_academia = %s
                   OR EXISTS (SELECT 1 FROM alunos_academias aa
                              WHERE aa.aluno_id = a.id AND aa.academia_id = %s))
            GROUP BY a.id, a.nome, a.foto, a.data_nascimento, a.id_academia
            ORDER BY DAY(a.data_nascimento), a.nome
        """
        return _query(sql, (mes, academia_id, academia_id))


def aniversariantes_do_mes_por_aluno_id(aluno_id: int, mes: int = None) -> list:
    """Mesmo critério do modo ``aluno``, usando ``alunos.id`` (ex.: painel do responsável)."""
    if mes is None:
        mes = date.today().month
    sql = """
        SELECT DISTINCT
            a.id, a.nome, a.foto, a.data_nascimento, a.id_academia,
            GROUP_CONCAT(t.Nome ORDER BY t.Nome SEPARATOR ', ') AS turmas
        FROM alunos a
        JOIN aluno_turmas at2 ON at2.aluno_id = a.id
        JOIN turmas t ON t.TurmaID = at2.TurmaID
        WHERE MONTH(a.data_nascimento) = %s
          AND a.ativo = 1
          AND at2.TurmaID IN (
              SELECT TurmaID FROM aluno_turmas WHERE aluno_id = %s
          )
        GROUP BY a.id, a.nome, a.foto, a.data_nascimento, a.id_academia
        ORDER BY DAY(a.data_nascimento), a.nome
    """
    return _query(sql, (mes, int(aluno_id)))


def aniversariantes_do_mes_professor_ampliado(usuario_id: int, mes: int = None) -> list:
    """
    Alunos ativos com aniversário no mês, em todas as academias onde o professor
    tem turma (turma_professor + turmas.id_academia). Inclui alunos da academia
    que não estão na turma do professor — alinhado à visão “todos os alunos” da live.
    Se não houver id_academia nas turmas, recai no escopo por turma (modo professor).
    """
    if mes is None:
        mes = date.today().month
    prows = _query(
        "SELECT id FROM professores WHERE usuario_id = %s AND ativo = 1",
        (usuario_id,),
    )
    if not prows:
        return []
    pids = tuple(int(r["id"]) for r in prows)
    ph = ",".join(["%s"] * len(pids))
    sql = f"""
        SELECT DISTINCT
            a.id, a.nome, a.foto, a.data_nascimento, a.id_academia,
            GROUP_CONCAT(DISTINCT t.Nome ORDER BY t.Nome SEPARATOR ', ') AS turmas
        FROM alunos a
        LEFT JOIN aluno_turmas at2 ON at2.aluno_id = a.id
        LEFT JOIN turmas t ON t.TurmaID = at2.TurmaID
        WHERE MONTH(a.data_nascimento) = %s
          AND a.ativo = 1
          AND a.id_academia IS NOT NULL
          AND EXISTS (
            SELECT 1
            FROM turma_professor tp
            INNER JOIN turmas t2 ON t2.TurmaID = tp.TurmaID
            WHERE tp.professor_id IN ({ph})
              AND t2.id_academia IS NOT NULL
              AND t2.id_academia = a.id_academia
          )
        GROUP BY a.id, a.nome, a.foto, a.data_nascimento, a.id_academia
        ORDER BY DAY(a.data_nascimento), a.nome
    """
    rows = _query(sql, (mes,) + pids)
    if rows:
        return rows
    return aniversariantes_do_mes(usuario_id, "professor", mes=mes)


def aniversariantes_do_mes_associacao(academia_ids: list, mes: int = None) -> list:
    """Aniversariantes de todas as academias de uma associação."""
    if not academia_ids:
        return []
    if mes is None:
        mes = date.today().month
    ph = ",".join(["%s"] * len(academia_ids))
    sql = f"""
        SELECT DISTINCT
            a.id, a.nome, a.foto, a.data_nascimento, a.id_academia,
            GROUP_CONCAT(t.Nome ORDER BY t.Nome SEPARATOR ', ') AS turmas
        FROM alunos a
        JOIN aluno_turmas at2 ON at2.aluno_id = a.id
        JOIN turmas t ON t.TurmaID = at2.TurmaID
        WHERE MONTH(a.data_nascimento) = %s
          AND a.ativo = 1
          AND (a.id_academia IN ({ph})
               OR EXISTS (SELECT 1 FROM alunos_academias aa
                          WHERE aa.aluno_id = a.id AND aa.academia_id IN ({ph})))
        GROUP BY a.id, a.nome, a.foto, a.data_nascimento, a.id_academia
        ORDER BY DAY(a.data_nascimento), a.nome
    """
    return _query(sql, (mes,) + tuple(academia_ids) * 2)


def academias_ids_da_mesma_associacao_do_usuario_aluno(usuario_id: int) -> list:
    """IDs das academias na mesma associação (id_associacao) do aluno vinculado ao usuário."""
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id_academia FROM alunos WHERE usuario_id = %s AND ativo = 1 LIMIT 1",
            (int(usuario_id),),
        )
        row = cur.fetchone()
        if not row or not row.get("id_academia"):
            return []
        id_acad = int(row["id_academia"])
        cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_acad,))
        r2 = cur.fetchone()
        id_assoc = r2.get("id_associacao") if r2 else None
        if not id_assoc:
            return [id_acad]
        cur.execute(
            "SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome",
            (id_assoc,),
        )
        return [int(r["id"]) for r in cur.fetchall()]
    finally:
        cur.close()
        db.close()


def academias_ids_do_usuario_aluno(usuario_id: int) -> list:
    """IDs das academias do aluno vinculado ao usuário: a principal e as de alunos_academias."""
    db = get_db_connection()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT a.id_academia AS id FROM alunos a
               WHERE a.usuario_id = %s AND a.ativo = 1 AND a.id_academia IS NOT NULL
               UNION
               SELECT aa.academia_id FROM alunos a
               JOIN alunos_academias aa ON aa.aluno_id = a.id
               WHERE a.usuario_id = %s AND a.ativo = 1""",
            (int(usuario_id), int(usuario_id)),
        )
        return [int(r["id"]) for r in cur.fetchall() if r.get("id")]
    finally:
        cur.close()
        db.close()


def aniversariantes_do_mes_aluno_associacao(usuario_id: int, mes: int = None) -> list:
    """Aniversariantes do mês nas academias do aluno logado.

    O nome ficou da época em que a lista abria a associação inteira: o aluno
    do Projeto 323 via o aniversário do judô de outras academias. Agora é só a
    academia dele (e as que ele também frequenta).
    """
    ids = academias_ids_do_usuario_aluno(usuario_id)
    if not ids:
        return []
    return aniversariantes_do_mes_associacao(ids, mes=mes)


# ------------------------------------------------------------ notificações
def academias_ids_do_usuario(cur, usuario_id: int) -> set:
    """Academias a que o usuário pertence, por qualquer papel: vínculo de gestão
    (usuarios_academias / usuarios.id_academia), aluno (principal e vinculadas),
    responsável (as dos alunos dele) e professor (as das turmas que leciona).

    É o recorte dos avisos de aniversário: cada um só fica sabendo dos
    aniversariantes das academias dele — antes o sino e o push do dia avisavam
    a base inteira (a ArteFísica recebia os aniversários da Team Anderson Silva).
    """
    uid = int(usuario_id)
    cur.execute(
        """
        SELECT academia_id AS id FROM usuarios_academias WHERE usuario_id = %s
        UNION SELECT id_academia FROM usuarios WHERE id = %s
        UNION SELECT a.id_academia FROM alunos a WHERE a.usuario_id = %s AND a.ativo = 1
        UNION SELECT aa.academia_id FROM alunos a
              JOIN alunos_academias aa ON aa.aluno_id = a.id
              WHERE a.usuario_id = %s AND a.ativo = 1
        UNION SELECT a.id_academia FROM responsavel_alunos ra
              JOIN alunos a ON a.id = ra.aluno_id WHERE ra.usuario_id = %s
        UNION SELECT aa.academia_id FROM responsavel_alunos ra
              JOIN alunos_academias aa ON aa.aluno_id = ra.aluno_id WHERE ra.usuario_id = %s
        UNION SELECT t.id_academia FROM professores p
              JOIN turma_professor tp ON tp.professor_id = p.id
              JOIN turmas t ON t.TurmaID = tp.TurmaID
              WHERE p.usuario_id = %s AND p.ativo = 1
        """,
        (uid,) * 7,
    )
    out = set()
    for r in cur.fetchall() or []:
        v = r.get("id") if isinstance(r, dict) else r[0]
        if v:
            out.add(int(v))
    return out


def sql_aluno_nas_academias(academia_ids, alias: str = "a"):
    """(trecho, params): o aluno é de uma destas academias — principal ou vinculado."""
    ids = tuple(int(i) for i in academia_ids)
    ph = ",".join(["%s"] * len(ids))
    trecho = (f"({alias}.id_academia IN ({ph}) OR EXISTS (SELECT 1 FROM alunos_academias aa_n "
              f"WHERE aa_n.aluno_id = {alias}.id AND aa_n.academia_id IN ({ph})))")
    return trecho, ids + ids
