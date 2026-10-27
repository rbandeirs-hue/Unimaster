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
import os

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
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
        cur.execute(f"""SELECT DISTINCT d.aluno_id FROM chamada_foto_rosto d
                        JOIN alunos a ON a.id = d.aluno_id
                        WHERE d.origem = 'chamada' AND d.face_id IS NOT NULL AND {t}""", tuple(p))
        aprendidos = {r["aluno_id"] for r in cur.fetchall()}
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
        a["aprendido"] = a["id"] in aprendidos
        a["reconhecivel"] = a["status"] == "autorizou" and (not a["sem_foto"] or a["aprendido"])
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
    # Diagnóstico do aparelho (motor, autoteste, cadastros lidos): é o que dá
    # para ver de um celular que não está aqui.
    if isinstance(dados.get("diag"), dict):
        import json as _json
        from flask import current_app
        current_app.logger.warning("chamada_foto diag academia=%s usuario=%s %s", academia_id,
                                   getattr(current_user, "id", None),
                                   _json.dumps(dados["diag"], ensure_ascii=False)[:600])
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
            if not aluno:
                continue
            # O de cadastro vale para a foto atual; o de chamada não depende de foto.
            if origem == "cadastro" and (not aluno.get("foto") or item.get("foto") != aluno["foto"]):
                continue
            cf.salvar_descritor(cur, aid, origem, aluno["foto"], desc)
            gravados += 1
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return jsonify(ok=True, gravados=gravados)


# ------------------------------------------------ reconhecimento (AWS)
def _consentidos_da_academia(cur, academia_id, ids):
    """Dos ids pedidos, os alunos da academia que autorizaram: {id: aluno}."""
    ids = [int(i) for i in ids if str(i).isdigit()][:300]
    if not ids:
        return {}
    status = cf.status_dos_alunos(cur, ids)
    t, p = filtro_alunos_da_academia(academia_id)
    ph = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT a.id, a.nome, a.foto FROM alunos a WHERE a.id IN ({ph}) AND {t}", (*ids, *p))
    return {a["id"]: a for a in cur.fetchall() if (status.get(a["id"]) or {}).get("status") == "autorizou"}


def _json_erro(e):
    from utils.rekognition import ErroReconhecimento
    msg = str(e) if isinstance(e, ErroReconhecimento) else "Não foi possível falar com o reconhecimento agora."
    current_app.logger.warning("chamada_foto: %s", repr(e)[:300])
    return jsonify(ok=False, erro=msg), 502


@bp_chamada_foto.route("/preparar", methods=["POST"])
@login_required
def preparar():
    """Leva ao Rekognition a foto do cadastro de quem ainda não foi.

    Corpo: {"ids": [aluno_id, ...]}. Devolve quem ficou com referência e quem
    tem foto sem rosto (fica marcado para não tentar de novo até trocar a foto).
    """
    from utils import rekognition
    academia_id = _academia()
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    if not academia_id or not rekognition.configurado():
        return jsonify(ok=False, erro="Reconhecimento não configurado."), 400
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    prontos, sem_rosto = [], []
    try:
        cf.garantir_tabelas(cur)
        alunos = _consentidos_da_academia(cur, academia_id, ids)
        ja = cf.rostos_dos_alunos(cur, list(alunos))
        pasta = os.path.join(current_app.root_path, "static", "uploads")
        for aid, a in alunos.items():
            foto = a.get("foto")
            cad = next((r for r in ja.get(aid, []) if r["origem"] == "cadastro"), None)
            if not foto or (cad and cad["foto"] == foto):
                continue
            caminho = os.path.realpath(os.path.join(pasta, foto))
            if not caminho.startswith(os.path.realpath(pasta) + os.sep) or not os.path.isfile(caminho):
                continue
            face = rekognition.indexar(academia_id, aid, rekognition.abrir(caminho))
            cf.registrar_rosto(cur, academia_id, aid, face, "cadastro", foto)
            conn.commit()
            (prontos if face else sem_rosto).append(str(aid))
    except Exception as e:
        conn.rollback()
        return _json_erro(e)
    finally:
        cur.close()
        conn.close()
    return jsonify(ok=True, prontos=prontos, sem_rosto=sem_rosto)


@bp_chamada_foto.route("/analisar", methods=["POST"])
@login_required
def analisar():
    """Uma foto da turma → os rostos e, para cada um, os alunos parecidos.

    Multipart: `foto` (JPEG) e `ids` (alunos da chamada que autorizaram, separados
    por vírgula). A foto só passa pela memória: não é gravada aqui nem na AWS.
    As caixas voltam em pixels da imagem recebida.
    """
    from utils import rekognition
    academia_id = _academia()
    arquivo = request.files.get("foto")
    if not academia_id or not arquivo or not rekognition.configurado():
        return jsonify(ok=False, erro="Requisição inválida."), 400
    try:
        img = rekognition.abrir(arquivo.read())
    except Exception:
        return jsonify(ok=False, erro="A foto não abriu. Tente outra."), 400
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        validos = {str(i) for i in _consentidos_da_academia(
            cur, academia_id, (request.form.get("ids") or "").split(","))}
    finally:
        cur.close()
        conn.close()
    try:
        rostos = rekognition.detectar(img)
        achados = rekognition.buscar(academia_id, img, rostos) if rostos else []
    except Exception as e:
        return _json_erro(e)
    out = []
    for r, m in zip(rostos, achados):
        out.append({"box": {"x": round(r["x"], 1), "y": round(r["y"], 1), "width": round(r["w"], 1), "height": round(r["h"], 1)},
                    # Só quem está nesta chamada e autorizou: a coleção é da academia inteira.
                    "matches": [x for x in m if x["id"] in validos][:5]})
    current_app.logger.info("chamada_foto analisar academia=%s %sx%s rostos=%s", academia_id, img.width, img.height, len(out))
    return jsonify(ok=True, largura=img.width, altura=img.height, rostos=out)


@bp_chamada_foto.route("/aprender", methods=["POST"])
@login_required
def aprender():
    """Rosto identificado na chamada vira referência do aluno (se autorizou).

    Multipart: `aluno_id` e `rosto` (JPEG recortado no celular). Guarda até
    MAX_CHAMADA por aluno: o mais antigo sai quando entra um novo.
    """
    from utils import rekognition
    academia_id = _academia()
    arquivo = request.files.get("rosto")
    aid = request.form.get("aluno_id", type=int)
    if not academia_id or not arquivo or not aid or not rekognition.configurado():
        return jsonify(ok=False, erro="Requisição inválida."), 400
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if aid not in _consentidos_da_academia(cur, academia_id, [aid]):
            return jsonify(ok=False, erro="Sem consentimento."), 403
        face = rekognition.indexar(academia_id, aid, rekognition.abrir(arquivo.read()))
        if face:
            cf.registrar_rosto(cur, academia_id, aid, face, "chamada")
            conn.commit()
    except Exception as e:
        conn.rollback()
        return _json_erro(e)
    finally:
        cur.close()
        conn.close()
    return jsonify(ok=True, guardado=bool(face))


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
        from utils import rekognition
        if not rekognition.configurado():
            return None
        ids_alunos = [a["id"] for a in alunos if isinstance(a.get("id"), int)]
        status = cf.status_dos_alunos(cur, ids_alunos)
        # Todo aluno com consentimento, com foto ou sem: quem não tem foto no
        # cadastro também aprende pelos rostos identificados na chamada.
        consentidos = [a["id"] for a in alunos if isinstance(a.get("id"), int)
                       and (status.get(a["id"]) or {}).get("status") == "autorizou"]
        rostos = cf.rostos_dos_alunos(cur, consentidos)
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
        consentiu = isinstance(aid, int) and (status.get(aid) or {}).get("status") == "autorizou"
        # Só quem consentiu pode ter o rosto guardado ao ser identificado.
        item["pode_aprender"] = consentiu
        linhas = (rostos.get(aid) or []) if consentiu else []
        item["referencias"] = sum(1 for r in linhas if r["face_id"])
        cadastro = next((r for r in linhas if r["origem"] == "cadastro"), None)
        # Foto do cadastro já tentada e sem rosto: não tenta de novo até trocar a foto.
        item["sem_rosto"] = bool(cadastro and cadastro["foto"] == foto and not cadastro["face_id"])
        if not isinstance(aid, int):
            item["motivo"] = "visitante"
        elif not consentiu:
            item["motivo"] = "sem_consentimento"
        elif not foto and not item["referencias"]:
            item["motivo"] = "sem_foto"
        else:
            item["motivo"] = None
            # Foto do cadastro ainda não levada ao reconhecimento (ou trocada).
            item["indexar"] = bool(foto) and not (cadastro and cadastro["foto"] == foto)
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
