# ======================================================
# Blueprint: Professor — Painel e gerenciamento próprio
# ======================================================
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from flask_login import login_required, current_user
from config import get_db_connection

bp_professor = Blueprint("professor", __name__, url_prefix="/professor")


def _get_professor_id():
    """Retorna (primeiro professor_id, primeiro id_academia) do current_user. Usado para contexto."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, id_academia FROM professores WHERE usuario_id = %s AND ativo = 1 LIMIT 1",
            (current_user.id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return (row["id"], row.get("id_academia")) if row else (None, None)
    except Exception:
        return (None, None)


def _get_todos_professor_ids():
    """Retorna lista de (professor_id, id_academia) do current_user (pode ter mais de um por academia)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, id_academia FROM professores WHERE usuario_id = %s AND ativo = 1 ORDER BY id",
            (current_user.id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [(r["id"], r.get("id_academia")) for r in rows]
    except Exception:
        return []


def _usuario_e_professor_ou_auxiliar():
    """True se o usuário tem registro em professores e aparece em alguma turma (responsável ou auxiliar)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT 1 FROM professores p
               INNER JOIN turma_professor tp ON tp.professor_id = p.id
               WHERE p.usuario_id = %s AND p.ativo = 1 LIMIT 1""",
            (current_user.id,),
        )
        ok = cur.fetchone() is not None
        cur.close()
        conn.close()
        return ok
    except Exception:
        return False


def _get_turmas_professor(professor_ids, academia_id=None):
    """Retorna turmas vinculadas ao(s) professor(es) (responsável ou auxiliar). professor_ids: int ou lista."""
    ids = [professor_ids] if isinstance(professor_ids, int) else (professor_ids or [])
    if not ids:
        return []
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            """
            SELECT t.TurmaID, t.Nome, t.DiasHorario AS dias_horario, tp.tipo, t.id_academia
            FROM turma_professor tp
            JOIN turmas t ON t.TurmaID = tp.TurmaID
            WHERE tp.professor_id IN (%s)
            ORDER BY t.Nome
            """ % ph,
            tuple(ids),
        )
        turmas = cur.fetchall()
        cur.close()
        conn.close()
        seen = set()
        uniq = []
        for t in turmas:
            tid = t.get("TurmaID")
            if tid not in seen:
                seen.add(tid)
                uniq.append(t)
        return uniq
    except Exception:
        return []


def _push_aniv_hoje(anivs_hoje: list, hoje) -> None:
    if not anivs_hoje:
        return
    chave = f"push_aniv_{hoje.isoformat()}"
    if session.get(chave):
        return
    session[chave] = True
    try:
        from utils.push_notifications import enviar_push_usuario
        nomes = ", ".join(a["nome"].split()[0] for a in anivs_hoje[:3])
        sufixo = f" +{len(anivs_hoje)-3}" if len(anivs_hoje) > 3 else ""
        enviar_push_usuario(
            current_user.id,
            title="🎂 Aniversariantes hoje!",
            body=f"{nomes}{sufixo} fazem aniversário hoje. Envie uma mensagem!",
            url="/professor/",
            tag="aniversario",
            require_interaction=True,
        )
    except Exception:
        pass


@bp_professor.route("/")
@login_required
def painel_professor():
    """Painel do professor: acesso à presença, relatório e histórico da sua turma (responsável ou auxiliar)."""
    session["modo_painel"] = "professor"
    if not current_user.has_role("professor") and not _usuario_e_professor_ou_auxiliar():
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    todos_prof = _get_todos_professor_ids()
    if not todos_prof:
        return render_template(
            "painel/professor_sem_vinculo.html",
            back_url=url_for("painel.home"),
        )

    professor_id, academia_id = _get_professor_id()
    ids_prof = [p[0] for p in todos_prof]
    turmas = _get_turmas_professor(ids_prof, academia_id)
    academia_nome = None
    if academia_id:
        try:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
            row = cur.fetchone()
            academia_nome = row["nome"] if row else None
            cur.close()
            conn.close()
        except Exception:
            pass

    from utils.aniversariantes import aniversariantes_do_mes
    from datetime import date
    hoje = date.today()
    anivs = aniversariantes_do_mes(current_user.id, "professor", mes=hoje.month)
    anivs_hoje = [a for a in anivs if a["data_nascimento"] and
                  a["data_nascimento"].day == hoje.day]
    _push_aniv_hoje(anivs_hoje, hoje)
    return render_template(
        "painel/painel_professor.html",
        turmas=turmas,
        academia_id=academia_id,
        academia_nome=academia_nome,
        aniversariantes=anivs,
        aniversariantes_hoje=anivs_hoje,
        hoje_dia=hoje.day,
        hoje_mes=hoje.month,
        hoje_ano=hoje.year,
    )


@bp_professor.route("/minha-turma")
@login_required
def minha_turma():
    """Lista alunos das turmas em que o professor é responsável ou auxiliar (igual visão do aluno)."""
    session["modo_painel"] = "professor"
    if not current_user.has_role("professor") and not _usuario_e_professor_ou_auxiliar():
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    from blueprints.aluno.painel import _buscar_alunos_turma

    todos_prof = _get_todos_professor_ids()
    if not todos_prof:
        flash("Nenhuma turma vinculada.", "warning")
        return redirect(url_for("professor.painel_professor"))

    ids_prof = [p[0] for p in todos_prof]
    _pid, academia_id = _get_professor_id()
    turmas_raw = _get_turmas_professor(ids_prof, academia_id)
    turma_ids = [t["TurmaID"] for t in turmas_raw if t.get("TurmaID") is not None]

    turma_selecionada_id = request.args.get("turma_id", type=int)
    turmas_com_alunos = []

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for tid in turma_ids:
            cur.execute("SELECT * FROM turmas WHERE TurmaID = %s", (tid,))
            t = cur.fetchone()
            if not t:
                continue
            try:
                cur.execute(
                    """SELECT p.nome FROM turma_professor tp
                       JOIN professores p ON p.id = tp.professor_id
                       WHERE tp.TurmaID = %s AND tp.tipo = 'responsavel' LIMIT 1""",
                    (tid,),
                )
                row = cur.fetchone()
                t["Professor"] = (
                    row["nome"] if row and row.get("nome") else t.get("Professor") or "—"
                )
            except Exception:
                t["Professor"] = t.get("Professor") or "—"
            id_acad = t.get("id_academia")
            alns = _buscar_alunos_turma(cur, tid, id_acad)
            turmas_com_alunos.append((t, alns))
    finally:
        cur.close()
        conn.close()

    if turma_selecionada_id and len(turmas_com_alunos) > 1:
        turmas_com_alunos.sort(
            key=lambda x: (0 if x[0]["TurmaID"] == turma_selecionada_id else 1, x[0]["Nome"] or "")
        )
    else:
        turmas_com_alunos.sort(key=lambda x: (x[0]["Nome"] or "").lower())

    return render_template(
        "painel_aluno/minha_turma.html",
        usuario=current_user,
        aluno=None,
        turmas_com_alunos=turmas_com_alunos,
        turma_selecionada_id=turma_selecionada_id,
        voltar_url=url_for("professor.painel_professor"),
        minha_turma_url=url_for("professor.minha_turma"),
    )
