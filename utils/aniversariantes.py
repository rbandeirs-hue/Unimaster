# -*- coding: utf-8 -*-
"""
Aniversariantes do mês filtrados por escopo:
  - aluno      → alunos das mesmas turmas (função ``aniversariantes_do_mes(..., "aluno")``)
  - aluno associação → ``aniversariantes_do_mes_aluno_associacao`` (painel / live modo aluno)
  - professor  → alunos das turmas que leciona (professor_id = professores.id)
  - professor ampliado → todos os alunos ativos das academias onde leciona (lista live)
  - academia   → todos os alunos da academia (com turma vinculada)
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
              AND a.id_academia = %s
            GROUP BY a.id, a.nome, a.foto, a.data_nascimento, a.id_academia
            ORDER BY DAY(a.data_nascimento), a.nome
        """
        return _query(sql, (mes, academia_id))


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
          AND a.id_academia IN ({ph})
        GROUP BY a.id, a.nome, a.foto, a.data_nascimento, a.id_academia
        ORDER BY DAY(a.data_nascimento), a.nome
    """
    return _query(sql, (mes,) + tuple(academia_ids))


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


def aniversariantes_do_mes_aluno_associacao(usuario_id: int, mes: int = None) -> list:
    """Todos os aniversariantes do mês nas academias da mesma associação do aluno logado."""
    ids = academias_ids_da_mesma_associacao_do_usuario_aluno(usuario_id)
    if not ids:
        return []
    return aniversariantes_do_mes_associacao(ids, mes=mes)
