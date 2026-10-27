# ======================================================
# Blueprint: Chamada por foto
# ======================================================
"""Configuração e consentimento da chamada por foto.

A tela da chamada em si é um modo da rota de registro de presença
(`/registro_presenca?modo=foto`), porque usa a mesma lista de alunos e grava
pelo mesmo formulário. Aqui ficam:

  * gestão  — ligar/desligar na academia, acompanhar o consentimento de cada
              aluno, registrar termo assinado em papel, pedir pelo WhatsApp,
              imprimir o termo;
  * família — o responsável (ou o aluno adulto) autoriza, recusa ou retira;
  * JSON    — o navegador do professor guarda o descritor do rosto que calculou.

Regras de LGPD em utils/chamada_foto.py.
"""
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from config import get_db_connection
from utils import chamada_foto as cf
from utils.alunos_academias import filtro_alunos_da_academia
from utils.permissoes import somente_gestao

bp_chamada_foto = Blueprint("chamada_foto", __name__, url_prefix="/chamada-foto")
bp_chamada_foto.before_request(somente_gestao(livres=("autorizar", "autorizar_salvar")))

FILTROS = {
    "todos": "Todos",
    "sem_resposta": "Sem resposta",
    "aguardando": "Aguardando",
    "recusou": "Recusaram",
    "sem_foto": "Sem foto",
    "autorizou": "Autorizaram",
}


def _academia():
    from blueprints.presencas.presencas import _get_academia_filtro_presencas
    return _get_academia_filtro_presencas()


def _aluno_da_academia(cur, academia_id, aluno_id):
    t, p = filtro_alunos_da_academia(academia_id)
    cur.execute(f"""SELECT a.id, a.nome, a.foto, a.data_nascimento, a.responsavel_financeiro_nome
                    FROM alunos a WHERE a.id = %s AND {t}""", (aluno_id, *p))
    return cur.fetchone()


def _voltar_config(academia_id, filtro=None):
    return redirect(url_for("chamada_foto.configuracao", academia_id=academia_id,
                            f=filtro or request.form.get("f") or None))


# ------------------------------------------------------------------ gestão
@bp_chamada_foto.route("/configuracao")
@login_required
def configuracao():
    academia_id = _academia()
    if not academia_id:
        flash("Escolha a academia primeiro.", "warning")
        return redirect(url_for("presencas.painel_presenca"))
    filtro = request.args.get("f") or "todos"
    if filtro not in FILTROS:
        filtro = "todos"

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cf.garantir_tabelas(cur)
        conn.commit()
        cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
        academia = cur.fetchone()
        ativa = cf.academia_ativa(cur, academia_id)
        t, p = filtro_alunos_da_academia(academia_id)
        cur.execute(f"""SELECT a.id, a.nome, a.foto, a.data_nascimento, a.responsavel_financeiro_nome,
                               t.Nome AS turma_nome
                        FROM alunos a LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                        WHERE (a.ativo IS NULL OR a.ativo = 1) AND {t}
                        ORDER BY a.nome""", tuple(p))
        alunos = cur.fetchall()
        status = cf.status_dos_alunos(cur, [a["id"] for a in alunos])
    finally:
        cur.close()
        conn.close()

    contagem = {k: 0 for k in FILTROS}
    for a in alunos:
        c = status.get(a["id"]) or {}
        a["status"] = c.get("status")
        a["via"] = cf.VIAS.get(c.get("via") or "", "")
        a["pedido_em"] = c.get("pedido_em")
        a["sem_foto"] = not (a.get("foto") or "").strip()
        a["menor"] = cf.menor_de_idade(a)
        a["reconhecivel"] = a["status"] == "autorizou" and not a["sem_foto"]
        contagem["todos"] += 1
        contagem[a["status"] or "sem_resposta"] += 1
        if a["sem_foto"]:
            contagem["sem_foto"] += 1
    reconheciveis = sum(1 for a in alunos if a["reconhecivel"])

    if filtro == "sem_foto":
        lista = [a for a in alunos if a["sem_foto"]]
    elif filtro == "sem_resposta":
        lista = [a for a in alunos if not a["status"]]
    elif filtro != "todos":
        lista = [a for a in alunos if a["status"] == filtro]
    else:
        lista = alunos

    return render_template(
        "chamada_foto/configuracao.html",
        academia=academia, academia_id=academia_id, ativa=ativa,
        lista=lista, contagem=contagem, reconheciveis=reconheciveis,
        filtro=filtro, FILTROS=FILTROS, STATUS=cf.STATUS,
    )


@bp_chamada_foto.route("/configuracao/ativa", methods=["POST"])
@login_required
def definir_ativa():
    academia_id = _academia()
    if not academia_id:
        return redirect(url_for("presencas.painel_presenca"))
    ligar = request.form.get("ativa") == "1"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cf.garantir_tabelas(cur)
        cf.definir_ativa(cur, academia_id, ligar, current_user.id)
        conn.commit()
    finally:
        cur.close()
        conn.close()
    flash("Chamada por foto ligada nesta academia." if ligar
          else "Chamada por foto desligada. A chamada manual continua igual.", "success")
    return _voltar_config(academia_id)


@bp_chamada_foto.route("/aluno/<int:aluno_id>/termo-papel", methods=["POST"])
@login_required
def registrar_termo_papel(aluno_id):
    """A secretaria lança a resposta de um termo assinado em papel."""
    academia_id = _academia()
    status = request.form.get("status")
    if status not in ("autorizou", "recusou"):
        flash("Resposta inválida.", "danger")
        return _voltar_config(academia_id)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        aluno = _aluno_da_academia(cur, academia_id, aluno_id) if academia_id else None
        if not aluno:
            flash("Aluno não encontrado nesta academia.", "warning")
            return _voltar_config(academia_id)
        cf.definir_consentimento(cur, aluno_id, status, "termo_papel", current_user.id)
        conn.commit()
    finally:
        cur.close()
        conn.close()
    flash(f"{aluno['nome']}: {cf.STATUS[status][0].lower()} (termo em papel).", "success")
    return _voltar_config(academia_id)


@bp_chamada_foto.route("/aluno/<int:aluno_id>/pedir", methods=["POST"])
@login_required
def pedir_whatsapp(aluno_id):
    """Pedido individual pelo WhatsApp da academia, com o link para autorizar.

    Um por vez, de propósito: segue a regra das mensagens da ficha do aluno
    (utils/whatsapp_aluno.py) — quem clica decidiu falar com aquela pessoa.
    """
    academia_id = _academia()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        aluno = _aluno_da_academia(cur, academia_id, aluno_id) if academia_id else None
        if not aluno:
            flash("Aluno não encontrado nesta academia.", "warning")
            return _voltar_config(academia_id)
        cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
        nome_acad = (cur.fetchone() or {}).get("nome") or "a academia"
    finally:
        cur.close()
        conn.close()

    primeiro = (aluno["nome"] or "").split(" ")[0]
    link = url_for("chamada_foto.autorizar", _external=True)
    texto = (
        f"Olá! Aqui é {nome_acad}. Estamos usando a chamada por foto: o professor "
        f"tira uma foto da turma e o sistema marca a presença comparando com a foto "
        f"do cadastro. Para incluir {primeiro}, precisamos da sua autorização. "
        f"A foto da turma não é guardada e você pode retirar quando quiser. "
        f"Autorize ou recuse por aqui (entre com o seu acesso ao sistema): {link}"
    )
    from utils import whatsapp_aluno
    ok, msg = whatsapp_aluno.enviar(aluno_id, "livre", academia_id, texto_livre=texto,
                                    usuario_id=current_user.id)
    if ok:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cf.marcar_pedido(cur, aluno_id)
            conn.commit()
        finally:
            cur.close()
            conn.close()
        flash(f"Pedido enviado para {aluno['nome']}.", "success")
    else:
        flash(msg, "danger")
    return _voltar_config(academia_id)


@bp_chamada_foto.route("/termo")
@login_required
def termo():
    """Folha para imprimir: um termo por aluno, ou um em branco."""
    academia_id = _academia()
    ids = [int(x) for x in request.args.getlist("aluno_id") if x.isdigit()]
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
        academia = cur.fetchone() or {}
        alunos = []
        for aid in ids[:200]:
            a = _aluno_da_academia(cur, academia_id, aid)
            if a:
                a["menor"] = cf.menor_de_idade(a)
                alunos.append(a)
    finally:
        cur.close()
        conn.close()
    if not alunos:
        alunos = [{"nome": "", "menor": None, "responsavel_financeiro_nome": ""}]
    for a in alunos:
        a["texto"] = cf.TERMO.format(aluno=a["nome"] or "________________________________")
    return render_template("chamada_foto/termo.html", academia=academia, alunos=alunos)


@bp_chamada_foto.route("/descritores", methods=["POST"])
@login_required
def salvar_descritores():
    """O navegador do professor manda os descritores que calculou.

    Corpo: {"itens": [{"aluno_id", "origem", "foto"?, "descritor": [128]}]}; a
    academia vem na URL (?academia_id=), que passa pela checagem de acesso.
    Só grava para aluno da academia, com consentimento e (origem cadastro) com a
    mesma foto que está no cadastro agora.
    """
    dados = request.get_json(silent=True) or {}
    academia_id = _academia()
    itens = dados.get("itens") or []
    if not academia_id or not isinstance(itens, list):
        return jsonify(ok=False, erro="requisição inválida"), 400

    gravados = 0
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cf.garantir_tabelas(cur)
        ids = [i.get("aluno_id") for i in itens[:120] if isinstance(i, dict)]
        status = cf.status_dos_alunos(cur, ids)
        for item in itens[:120]:
            if not isinstance(item, dict):
                continue
            aid = item.get("aluno_id")
            origem = item.get("origem")
            desc = cf.validar_descritor(item.get("descritor"))
            if not isinstance(aid, int) or origem not in ("cadastro", "chamada") or not desc:
                continue
            if (status.get(aid) or {}).get("status") != "autorizou":
                continue
            aluno = _aluno_da_academia(cur, academia_id, aid)
            if not aluno or not aluno.get("foto"):
                continue
            if origem == "cadastro" and item.get("foto") != aluno["foto"]:
                continue
            cf.salvar_descritor(cur, aid, origem, aluno["foto"], desc)
            gravados += 1
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return jsonify(ok=True, gravados=gravados)


# ------------------------------------------------------------------ família
def _alunos_que_posso_autorizar(cur):
    """Filhos (responsavel_alunos) e o próprio cadastro de aluno do usuário."""
    cur.execute("""SELECT a.id, a.nome, a.foto, a.data_nascimento, a.responsavel_financeiro_nome,
                          a.id_academia, ac.nome AS academia_nome, 'responsavel' AS via
                   FROM responsavel_alunos ra
                   JOIN alunos a ON a.id = ra.aluno_id
                   LEFT JOIN academias ac ON ac.id = a.id_academia
                   WHERE ra.usuario_id = %s AND (a.ativo IS NULL OR a.ativo = 1)""",
                (current_user.id,))
    lista = cur.fetchall()
    vistos = {a["id"] for a in lista}
    cur.execute("""SELECT a.id, a.nome, a.foto, a.data_nascimento, a.responsavel_financeiro_nome,
                          a.id_academia, ac.nome AS academia_nome, 'aluno' AS via
                   FROM alunos a LEFT JOIN academias ac ON ac.id = a.id_academia
                   WHERE a.usuario_id = %s AND (a.ativo IS NULL OR a.ativo = 1)""",
                (current_user.id,))
    for a in cur.fetchall():
        if a["id"] not in vistos:
            lista.append(a)
    lista.sort(key=lambda a: (a["nome"] or "").lower())
    return lista


@bp_chamada_foto.route("/autorizar")
@login_required
def autorizar():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cf.garantir_tabelas(cur)
        conn.commit()
        alunos = _alunos_que_posso_autorizar(cur)
        status = cf.status_dos_alunos(cur, [a["id"] for a in alunos])
        for a in alunos:
            c = status.get(a["id"]) or {}
            a["status"] = c.get("status")
            a["respondido_em"] = c.get("respondido_em")
            a["menor"] = cf.menor_de_idade(a)
            # Menor no próprio login não decide: quem autoriza é o responsável.
            a["pode_decidir"] = a["via"] == "responsavel" or not a["menor"]
            a["academia_usa"] = cf.academia_ativa(cur, a["id_academia"])
            a["sem_foto"] = not (a.get("foto") or "").strip()
            a["texto"] = cf.TERMO.format(aluno=a["nome"])
    finally:
        cur.close()
        conn.close()
    return render_template("chamada_foto/autorizar.html", alunos=alunos, STATUS=cf.STATUS)


@bp_chamada_foto.route("/autorizar/<int:aluno_id>", methods=["POST"])
@login_required
def autorizar_salvar(aluno_id):
    status = request.form.get("status")
    if status not in ("autorizou", "recusou"):
        flash("Resposta inválida.", "danger")
        return redirect(url_for("chamada_foto.autorizar"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cf.garantir_tabelas(cur)
        aluno = next((a for a in _alunos_que_posso_autorizar(cur) if a["id"] == aluno_id), None)
        if not aluno:
            flash("Este aluno não está no seu acesso.", "warning")
            return redirect(url_for("chamada_foto.autorizar"))
        if aluno["via"] == "aluno" and cf.menor_de_idade(aluno):
            flash("Para menores de 18 anos, quem autoriza é o responsável.", "warning")
            return redirect(url_for("chamada_foto.autorizar"))
        cf.definir_consentimento(cur, aluno_id, status, aluno["via"], current_user.id)
        conn.commit()
    finally:
        cur.close()
        conn.close()
    if status == "autorizou":
        flash(f"Obrigado! {aluno['nome'].split(' ')[0]} entra na chamada por foto.", "success")
    else:
        flash(f"Pronto. {aluno['nome'].split(' ')[0]} fica fora da chamada por foto, e os dados "
              "do rosto foram apagados. A presença é marcada à mão.", "success")
    return redirect(url_for("chamada_foto.autorizar"))


# ------------------------------------------------------- tela da chamada
def pagina_chamada(*, alunos, turmas, turma_id, data_presenca, horario_aula, academia_id,
                   observacao_aula, plano_aula_texto, back_url):
    """Renderiza o modo foto da chamada com a lista que `registro_presenca` montou.

    Cada pessoa da lista vira um item com o motivo de entrar (ou não) no
    reconhecimento. Quem está bloqueado (visitando outra academia hoje) não
    entra: a gravação já o ignora.
    """
    from flask import url_for as _u
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cf.garantir_tabelas(cur)
        conn.commit()
        if not cf.academia_ativa(cur, academia_id):
            return None
        ids_alunos = [a["id"] for a in alunos if isinstance(a.get("id"), int)]
        status = cf.status_dos_alunos(cur, ids_alunos)
        fotos = {a["id"]: a.get("foto") for a in alunos
                 if isinstance(a.get("id"), int) and a.get("foto")
                 and (status.get(a["id"]) or {}).get("status") == "autorizou"}
        descritores = cf.descritores_validos(cur, fotos)
    finally:
        cur.close()
        conn.close()

    pessoas = []
    for a in alunos:
        if a.get("bloqueado"):
            continue
        aid = a.get("id")
        foto = a.get("foto") or ""
        item = {
            "id": str(aid),
            "nome": a.get("nome") or "",
            "foto_url": _u("static", filename="uploads/" + foto) if foto else "",
            "marcado": bool(a.get("marcado")),
            "outra_turma": bool(a.get("aluno_outra_turma")),
        }
        if not isinstance(aid, int):
            item["motivo"] = "visitante"
        elif (status.get(aid) or {}).get("status") != "autorizou":
            item["motivo"] = "sem_consentimento"
        elif not foto:
            item["motivo"] = "sem_foto"
        else:
            item["motivo"] = None
            d = descritores.get(aid) or {}
            item["descritores"] = d.get("lista") or []
            # Sem descritor da foto atual: o navegador calcula e devolve.
            item["calcular"] = foto if not d.get("cadastro") else None
        pessoas.append(item)

    turma = next((t for t in turmas if t.get("TurmaID") == turma_id), {}) or {}
    reconheciveis = sum(1 for p in pessoas if p["motivo"] is None)
    return render_template(
        "presencas/chamada_foto.html",
        pessoas=pessoas,
        turma_nome=turma.get("Nome") or "Turma",
        turma_id=turma_id, data_presenca=data_presenca, horario_aula=horario_aula,
        academia_id=academia_id, observacao_aula=observacao_aula,
        plano_aula_texto=plano_aula_texto, back_url=back_url,
        resumo={
            "total": sum(1 for p in pessoas if p["motivo"] != "visitante"),
            "reconheciveis": reconheciveis,
            "sem_foto": sum(1 for p in pessoas if p["motivo"] == "sem_foto"),
            "sem_consentimento": sum(1 for p in pessoas if p["motivo"] == "sem_consentimento"),
        },
    )


def ativa_na_academia(academia_id):
    """Para o botão de entrada na chamada manual."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            return cf.academia_ativa(cur, academia_id)
        finally:
            cur.close()
            conn.close()
    except Exception:
        return False
