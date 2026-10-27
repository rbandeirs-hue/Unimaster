"""Check-in por QR Code.

O professor abre a tela do QR da turma num tablet ou celular no tatame; o
código muda a cada minuto. O aluno (ou o responsável, pelos filhos) lê com o
celular, já logado, e confirma: a presença cai em `presencas`, no mesmo
horário que a chamada usa (o início da turma), então aparece marcada quando o
professor abre a chamada — que continua sendo quem decide no fim.

Por que o código gira: um QR fixo impresso na parede vira foto no grupo da
turma e dá presença para quem ficou em casa. Com o código assinado por minuto
(HMAC com a chave do app), só vale quem está olhando a tela agora.

Regras do check-in:
  - só alunos matriculados na turma (aluno_turmas);
  - só no dia da aula (turmas.dias_semana, 1 = segunda … 7 = domingo) e de
    1h antes do início até 30 min depois do fim, quando a turma tem horário;
  - um registro por aluno por dia (a chave da tabela já garante).
"""
import hashlib
import hmac
import io
import time
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required

from config import get_db_connection

bp_checkin = Blueprint("checkin", __name__)

JANELA_SEG = 60          # o QR muda a cada minuto
VALE_JANELAS = 3         # código lido vale por até 3 minutos
VALE_CONFIRMAR_SEG = 15 * 60   # da leitura até o "confirmar"
ANTES_MIN, DEPOIS_MIN = 60, 30


# ------------------------------------------------------------------ código
def _assinatura(turma_id, janela):
    chave = (current_app.secret_key or "").encode() if isinstance(current_app.secret_key, str) \
        else (current_app.secret_key or b"")
    msg = f"checkin:{int(turma_id)}:{int(janela)}".encode()
    return hmac.new(chave, msg, hashlib.sha256).hexdigest()[:12]


def codigo_atual(turma_id, agora=None):
    janela = int((agora or time.time()) // JANELA_SEG)
    return f"{janela}-{_assinatura(turma_id, janela)}"


def codigo_valido(turma_id, codigo, agora=None, tolerancia=VALE_JANELAS):
    try:
        janela_txt, assin = str(codigo).split("-", 1)
        janela = int(janela_txt)
    except (ValueError, AttributeError):
        return False
    atual = int((agora or time.time()) // JANELA_SEG)
    if not 0 <= atual - janela < tolerancia:
        return False
    return hmac.compare_digest(assin, _assinatura(turma_id, janela))


# ------------------------------------------------------------------ turma
def _turma(cur, turma_id):
    cur.execute("""SELECT TurmaID, Nome, id_academia, dias_semana, hora_inicio, hora_fim
                   FROM turmas WHERE TurmaID = %s""", (turma_id,))
    return cur.fetchone()


def _minutos(td):
    if td is None:
        return None
    if hasattr(td, "total_seconds"):
        return int(td.total_seconds()) // 60
    try:
        h, m = str(td)[:5].split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def horario_aula(turma):
    m = _minutos(turma.get("hora_inicio"))
    return "00:00:00" if m is None else f"{m // 60:02d}:{m % 60:02d}:00"


def motivo_fora_de_hora(turma, agora=None):
    """None se agora é hora de aula desta turma; senão a explicação."""
    agora = agora or datetime.now()
    dias = {d.strip() for d in str(turma.get("dias_semana") or "").split(",") if d.strip()}
    hoje = str(agora.isoweekday())          # 1 = segunda … 7 = domingo
    if dias and hoje not in dias and not (hoje == "7" and "0" in dias):
        return "Hoje não tem aula desta turma."
    ini, fim = _minutos(turma.get("hora_inicio")), _minutos(turma.get("hora_fim"))
    if ini is None:
        return None
    fim = fim if fim is not None else ini + 60
    agora_min = agora.hour * 60 + agora.minute
    if agora_min < ini - ANTES_MIN:
        return f"O check-in abre 1 hora antes da aula ({ini // 60:02d}:{ini % 60:02d})."
    if agora_min > fim + DEPOIS_MIN:
        return "A aula de hoje já terminou."
    return None


def _pode_ver_tela(cur, turma):
    if current_user.has_role("admin"):
        return True
    if not (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
        return False
    cur.execute("SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id = %s",
                (current_user.id, turma["id_academia"]))
    if cur.fetchone():
        return True
    cur.execute("SELECT 1 FROM professores WHERE usuario_id = %s AND id_academia = %s",
                (current_user.id, turma["id_academia"]))
    return cur.fetchone() is not None


def alunos_do_usuario_na_turma(cur, usuario_id, turma_id):
    """O próprio aluno e os filhos (responsável) matriculados na turma."""
    cur.execute(
        """SELECT DISTINCT a.id, a.nome, a.foto
           FROM alunos a
           JOIN aluno_turmas at ON at.aluno_id = a.id AND at.TurmaID = %s
           WHERE COALESCE(a.ativo, 1) = 1 AND (
                 a.usuario_id = %s
              OR a.id IN (SELECT aluno_id FROM responsavel_alunos WHERE usuario_id = %s))
           ORDER BY a.nome""", (turma_id, usuario_id, usuario_id))
    return cur.fetchall()


def presentes_hoje(cur, turma_id, horario):
    cur.execute("""SELECT a.id, a.nome, p.responsavel_nome, p.registrado_em
                   FROM presencas p JOIN alunos a ON a.id = p.aluno_id
                   WHERE p.turma_id = %s AND p.data_presenca = %s AND p.horario_aula = %s
                     AND p.presente = 1
                   ORDER BY p.registrado_em DESC""", (turma_id, date.today(), horario))
    return cur.fetchall()


def registrar(cur, aluno_ids, turma, usuario_id, usuario_nome):
    horario = horario_aula(turma)
    for aid in aluno_ids:
        cur.execute(
            """INSERT INTO presencas (aluno_id, turma_id, data_presenca, horario_aula,
                                      responsavel_id, responsavel_nome, presente)
               VALUES (%s, %s, %s, %s, %s, %s, 1)
               ON DUPLICATE KEY UPDATE presente = 1, turma_id = VALUES(turma_id),
                   horario_aula = VALUES(horario_aula),
                   responsavel_id = VALUES(responsavel_id),
                   responsavel_nome = VALUES(responsavel_nome),
                   registrado_em = CURRENT_TIMESTAMP""",
            (aid, turma["TurmaID"], date.today(), horario, usuario_id,
             f"Check-in QR · {usuario_nome}"[:255]))


# ------------------------------------------------------------------ rotas
@bp_checkin.route("/presencas/checkin/<int:turma_id>/tela")
@login_required
def tela(turma_id):
    """Tela do QR para deixar no tatame."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        turma = _turma(cur, turma_id)
        if not turma or not _pode_ver_tela(cur, turma):
            abort(404)
        presentes = presentes_hoje(cur, turma_id, horario_aula(turma))
    finally:
        conn.close()
    return render_template("presencas/checkin_tela.html", turma=turma, presentes=presentes,
                           aviso=motivo_fora_de_hora(turma), janela_seg=JANELA_SEG,
                           shell_sem_lateral=True)


@bp_checkin.route("/presencas/checkin/<int:turma_id>/codigo")
@login_required
def codigo(turma_id):
    """QR da vez (SVG) e quem já fez check-in — a tela pede a cada minuto."""
    import qrcode
    import qrcode.image.svg
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        turma = _turma(cur, turma_id)
        if not turma or not _pode_ver_tela(cur, turma):
            abort(404)
        presentes = presentes_hoje(cur, turma_id, horario_aula(turma))
    finally:
        conn.close()
    url = url_for("checkin.ler", turma_id=turma_id, codigo=codigo_atual(turma_id), _external=True)
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return jsonify({
        "svg": buf.getvalue().decode(), "url": url,
        "presentes": [{"nome": p["nome"], "hora": p["registrado_em"].strftime("%H:%M") if p["registrado_em"] else ""}
                      for p in presentes],
        "aviso": motivo_fora_de_hora(turma),
    })


@bp_checkin.route("/checkin/<int:turma_id>/<codigo>", methods=["GET", "POST"])
@login_required
def ler(turma_id, codigo):
    """O aluno leu o QR: confirma a presença dele (ou dos filhos)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        turma = _turma(cur, turma_id)
        if not turma:
            abort(404)
        alunos = alunos_do_usuario_na_turma(cur, current_user.id, turma_id)
        erro = None
        if request.method == "POST":
            lido_em = request.form.get("lido_em", type=int) or 0
            assin = request.form.get("assin") or ""
            # O formulário carrega o momento da leitura, assinado: quem leu o
            # QR a tempo tem 15 min para confirmar, mesmo que o QR já tenha girado.
            if not (hmac.compare_digest(assin, _assinatura(turma_id, lido_em))
                    and 0 <= time.time() - lido_em < VALE_CONFIRMAR_SEG):
                erro = "O tempo para confirmar acabou. Leia o QR Code de novo."
            else:
                ids_ok = {a["id"] for a in alunos}
                marcados = [int(x) for x in request.form.getlist("aluno_id") if x.isdigit() and int(x) in ids_ok]
                fora = motivo_fora_de_hora(turma)
                if fora:
                    erro = fora
                elif not marcados:
                    erro = "Marque quem está na aula."
                else:
                    registrar(cur, marcados, turma, current_user.id, getattr(current_user, "nome", ""))
                    conn.commit()
                    nomes = ", ".join(a["nome"].split()[0] for a in alunos if a["id"] in marcados)
                    return render_template("presencas/checkin_aluno.html", turma=turma, feito=True,
                                           nomes=nomes, shell_sem_lateral=True)
            expirou = erro and erro.startswith("O tempo")
            return render_template("presencas/checkin_aluno.html", turma=turma, alunos=alunos,
                                   erro=erro, lido_em=lido_em, assin=None if expirou else assin,
                                   shell_sem_lateral=True)

        if not codigo_valido(turma_id, codigo):
            erro = "Este QR Code expirou. Leia o código que está na tela agora."
        elif not alunos:
            erro = "Você não tem aluno matriculado nesta turma."
        else:
            erro = motivo_fora_de_hora(turma)
        lido_em = int(time.time())
        # Só quem leu um código válido recebe a assinatura que libera o confirmar.
        return render_template("presencas/checkin_aluno.html", turma=turma, alunos=alunos, erro=erro,
                               lido_em=lido_em, assin=None if erro else _assinatura(turma_id, lido_em),
                               shell_sem_lateral=True)
    finally:
        conn.close()


# ------------------------------------------------------------------ evasão
@bp_checkin.route("/presencas/evasao")
@login_required
def evasao():
    """Alunos que pararam de treinar ou estão vindo menos (utils/evasao.py)."""
    from flask import session
    from utils import evasao as ev
    from utils.acesso_academia import academia_atual
    if not (current_user.has_role("admin") or current_user.has_role("gestor_academia")
            or current_user.has_role("professor")):
        abort(403)
    academia_id = request.args.get("academia_id", type=int) or academia_atual()
    if not academia_id:
        return redirect(url_for("painel.home"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if not current_user.has_role("admin"):
            cur.execute("SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id = %s",
                        (current_user.id, academia_id))
            if not cur.fetchone():
                abort(403)
        lista = ev.alunos_em_risco(cur, academia_id)
    finally:
        conn.close()
    return render_template("presencas/evasao.html", lista=lista, academia_id=academia_id,
                           janela=ev.JANELA, base_dias=ev.BASE_DIAS)
