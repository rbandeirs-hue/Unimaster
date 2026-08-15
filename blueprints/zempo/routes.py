"""
Migração e sincronização de alunos com o Zempo (CBJ).

Fluxo:
  1. A ACADEMIA revisa seus alunos, vê o que falta para cada um e solicita o
     cadastro no Zempo  ->  /zempo/solicitar
  2. A ASSOCIAÇÃO (dona das credenciais) escolhe quais solicitações migrar e
     dispara a criação no Zempo  ->  /zempo/migracoes
  3. Qualquer um dos dois sincroniza um aluno já cadastrado, pelo CPF, com
     prévia do que vai mudar  ->  /zempo/sincronizar/<id>
     ou envia o que está no sistema para o Zempo  ->  /zempo/enviar/<id>

As credenciais ficam na associação (ver utils/zempo.py).
"""
import mimetypes
import os
import re
from datetime import datetime
from urllib.parse import quote

from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_login import current_user, login_required

from config import get_db_connection
from utils.zempo import ZempoClient, ZempoError
from utils import zempo_mapper as mapper
from utils import whatsapp

bp_zempo = Blueprint("zempo", __name__, url_prefix="/zempo")


# --------------------------------------------------------------- permissões

def _pode_solicitar():
    return current_user.has_role("admin") or current_user.has_role("gestor_academia") \
        or current_user.has_role("gestor_associacao")


def _pode_migrar():
    """
    Só a associação escreve na base da CBJ.

    Quem acumula papéis (admin que também gerencia academia) fica limitado
    enquanto estiver operando no modo academia — senão a tela da academia
    ofereceria "migrar", que é justamente o que ela não pode fazer.
    """
    if session.get("modo_painel") == "academia":
        return False
    return current_user.has_role("admin") or current_user.has_role("gestor_associacao")


def _associacao_do_usuario(cur):
    """Associação em que o usuário logado opera (a da academia, se for gestor de academia)."""
    if current_user.id_associacao:
        return current_user.id_associacao
    if current_user.id_academia:
        cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (current_user.id_academia,))
        linha = cur.fetchone()
        return (linha or {}).get("id_associacao")
    return None


def _cliente(cur, id_associacao):
    """Monta o ZempoClient com as credenciais da associação. Levanta ZempoError se faltar."""
    cur.execute(
        """SELECT nome, zempo_codigo, zempo_senha, zempo_habilitado,
                  zempo_clube_id, zempo_federacao_id
           FROM associacoes WHERE id = %s""", (id_associacao,))
    assoc = cur.fetchone()
    if not assoc:
        raise ZempoError("Associação não encontrada.")
    if not assoc.get("zempo_habilitado"):
        raise ZempoError(
            f"A integração com o Zempo não está ativada para {assoc['nome']}. "
            "Configure em Associação → Integração Zempo.")
    cli = ZempoClient(assoc.get("zempo_codigo"), assoc.get("zempo_senha"),
                      assoc.get("zempo_clube_id"), assoc.get("zempo_federacao_id"))
    if not cli.configurado:
        raise ZempoError("Código e senha do Zempo não preenchidos para esta associação.")
    if not cli.clube_id or not cli.federacao_id:
        raise ZempoError(
            "Falta informar o id do clube e da federação no Zempo para esta associação.")
    return cli


# ------------------------------------------------------------------ consulta

_SELECT_ALUNO = """
    SELECT a.*, g.faixa AS faixa, ac.nome AS academia_nome
    FROM alunos a
    LEFT JOIN graduacao g ON g.id = a.graduacao_id
    LEFT JOIN academias ac ON ac.id = a.id_academia
"""


def _carregar_aluno(cur, aluno_id):
    cur.execute(_SELECT_ALUNO + " WHERE a.id = %s", (aluno_id,))
    return cur.fetchone()


# Foto usada quando o aluno não tem uma: o Zempo mostra a foto no cadastro, e
# subir a logo é melhor do que deixar o campo vazio. Troque este arquivo para
# mudar a imagem padrão de todos.
FOTO_PADRAO = os.path.join("static", "img", "zempo_foto_padrao.jpg")


def _foto_do_aluno(aluno):
    """(nome, bytes, mimetype) da foto do aluno, ou a foto padrão se ele não tiver."""
    nome_arquivo = (aluno.get("foto") or "").strip()
    caminho = None
    if nome_arquivo:
        candidato = os.path.join(current_app.root_path, "static", "uploads", nome_arquivo)
        if os.path.isfile(candidato):
            caminho = candidato
    if caminho is None:
        padrao = os.path.join(current_app.root_path, FOTO_PADRAO)
        if not os.path.isfile(padrao):
            return None
        caminho = padrao

    with open(caminho, "rb") as fh:
        conteudo = fh.read()
    mime = mimetypes.guess_type(caminho)[0] or "image/jpeg"
    return (os.path.basename(caminho), conteudo, mime)


# ------------------------------------------------- 1) academia: solicitações

@bp_zempo.route("/solicitar", methods=["GET", "POST"])
@login_required
def solicitar():
    """Academia revisa os alunos, vê pendências e solicita o cadastro no Zempo."""
    if not _pode_solicitar():
        flash("Você não tem permissão para solicitar cadastros no Zempo.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        academia_id = request.args.get("academia_id", type=int) or current_user.id_academia
        id_associacao = _associacao_do_usuario(cur)

        if request.method == "POST":
            ids = [int(i) for i in request.form.getlist("aluno_ids") if i.isdigit()]
            if not ids:
                flash("Selecione ao menos um aluno.", "warning")
                return redirect(url_for("zempo.solicitar", academia_id=academia_id))

            criadas, ja_no_zempo, em_aberto, sem_acesso = 0, 0, 0, 0
            for aluno_id in ids:
                aluno = _carregar_aluno(cur, aluno_id)
                if not aluno:
                    continue
                if not _autorizado_no_aluno(cur, aluno):
                    sem_acesso += 1
                    continue
                # Quem já tem cadastro na CBJ não entra na fila de novo: seria
                # pedir a criação de um cadastro que já existe.
                if (aluno.get("zempo") or "").strip():
                    ja_no_zempo += 1
                    continue
                # Nem quem já tem solicitação andando — em qualquer etapa do fluxo.
                cur.execute(
                    """SELECT id FROM zempo_solicitacoes
                       WHERE aluno_id = %s
                         AND status IN ('pendente','aprovada',
                                        'aguardando_academia','aguardando_associacao')""",
                    (aluno_id,))
                if cur.fetchone():
                    em_aberto += 1
                    continue
                cur.execute(
                    """INSERT INTO zempo_solicitacoes
                       (aluno_id, id_academia, id_associacao, status, solicitado_por, solicitado_em)
                       VALUES (%s, %s, %s, 'aguardando_academia', %s, %s)""",
                    (aluno_id, aluno.get("id_academia"), id_associacao,
                     current_user.id, datetime.now()))
                criadas += 1
            conn.commit()
            if criadas:
                flash(f"{criadas} solicitação(ões) enviada(s).", "success")
            if ja_no_zempo:
                flash(f"{ja_no_zempo} aluno(s) ignorado(s): já têm cadastro no Zempo. "
                      "Use 'Sincronizar' para atualizar os dados.", "info")
            if em_aberto:
                flash(f"{em_aberto} aluno(s) ignorado(s): já tinham solicitação em aberto.", "info")
            if sem_acesso:
                flash(f"{sem_acesso} aluno(s) fora do seu escopo.", "warning")
            return redirect(url_for("zempo.solicitar", academia_id=academia_id))

        academias = _academias_permitidas(cur)
        if academia_id and academia_id not in [a["id"] for a in academias]:
            academia_id = None      # fora do escopo: cai para as academias do usuário
        busca = (request.args.get("busca") or "").strip()
        alunos = _alunos_visiveis(cur, academia_id, academias, busca)

        # Link público do formulário, para a academia enviar aos alunos.
        cur.execute("SELECT slug, zempo_form_token FROM associacoes WHERE id = %s",
                    (id_associacao,))
        assoc = cur.fetchone() or {}
        identificador = (assoc.get("slug") or "").strip() or assoc.get("zempo_form_token")
        link_publico = (url_for("zempo_publico.inicio", token=identificador, _external=True)
                        if identificador else None)

        # Situação de cada aluno: no Zempo, solicitado, pronto ou com pendências.
        cur.execute(
            """SELECT aluno_id, status FROM zempo_solicitacoes
               WHERE status IN ('pendente','aprovada')""")
        em_aberto = {linha["aluno_id"] for linha in cur.fetchall()}

        linhas = []
        for aluno in alunos:
            faltando = mapper.validar_aluno(aluno)
            telefone = (aluno.get("tel_celular") or aluno.get("telefone")
                        or aluno.get("tel_residencial") or "")
            linhas.append({
                "aluno": aluno,
                "faltando": faltando,
                "solicitado": aluno["id"] in em_aberto,
                "no_zempo": bool((aluno.get("zempo") or "").strip()),
                # Usado no seletor de contatos do envio por WhatsApp.
                "telefone": telefone if len(re.sub(r"\D", "", telefone)) in (10, 11) else "",
                # Com CPF válido dá para procurar no Zempo mesmo sem número gravado.
                "tem_cpf": len(re.sub(r"\D", "", aluno.get("cpf") or "")) == 11,
            })
    finally:
        cur.close()
        conn.close()

    prontos = sum(1 for l in linhas
                  if not l["faltando"] and not l["solicitado"] and not l["no_zempo"])
    incompletos = sum(1 for l in linhas if l["faltando"])
    return render_template("zempo/solicitar.html", linhas=linhas, academias=academias,
                           academia_id=academia_id, prontos=prontos,
                           incompletos=incompletos, pode_migrar=_pode_migrar(),
                           link_publico=link_publico, busca=busca)


def _academias_permitidas(cur):
    """
    Academias que o usuário logado pode enxergar.

    É esta lista que limita a consulta — sem ela, trocar `academia_id` na URL
    exporia os alunos de qualquer outra academia.
    """
    # Operando como academia, enxerga só a própria — mesmo quem acumula papéis.
    if session.get("modo_painel") == "academia":
        academia_id = session.get("academia_gerenciamento_id") or current_user.id_academia
        if academia_id:
            cur.execute("SELECT id, nome FROM academias WHERE id = %s", (academia_id,))
            return cur.fetchall()

    if current_user.has_role("admin"):
        cur.execute("SELECT id, nome FROM academias ORDER BY nome")
        return cur.fetchall()
    if current_user.has_role("gestor_associacao") and current_user.id_associacao:
        cur.execute("SELECT id, nome FROM academias WHERE id_associacao = %s ORDER BY nome",
                    (current_user.id_associacao,))
        return cur.fetchall()
    if current_user.id_academia:
        cur.execute("SELECT id, nome FROM academias WHERE id = %s", (current_user.id_academia,))
        return cur.fetchall()
    return []


def _alunos_visiveis(cur, academia_id, academias, busca=None):
    """Alunos das academias permitidas, opcionalmente filtrados por uma delas e por busca."""
    permitidas = [a["id"] for a in academias]
    if not permitidas:
        return []
    # Um academia_id fora do escopo é ignorado em vez de honrado.
    escopo = [academia_id] if academia_id in permitidas else permitidas
    marcadores = ", ".join(["%s"] * len(escopo))
    sql = (_SELECT_ALUNO + f" WHERE a.id_academia IN ({marcadores}) AND a.ativo = 1")
    parametros = list(escopo)

    termo = (busca or "").strip()
    if termo:
        digitos = re.sub(r"\D", "", termo)
        # Só dígitos: busca por CPF ignorando pontuação. Caso contrário, por nome.
        if digitos and len(digitos) >= 3 and not re.search(r"[A-Za-zÀ-ÿ]", termo):
            sql += " AND REPLACE(REPLACE(a.cpf, '.', ''), '-', '') LIKE %s"
            parametros.append(f"%{digitos}%")
        else:
            sql += " AND a.nome LIKE %s"
            parametros.append(f"%{termo}%")

    cur.execute(sql + " ORDER BY ac.nome, a.nome", tuple(parametros))
    return cur.fetchall()


def _autorizado_no_aluno(cur, aluno):
    """True se o usuário logado pode agir sobre este aluno."""
    if current_user.has_role("admin"):
        return True
    if current_user.has_role("gestor_academia"):
        return aluno.get("id_academia") == current_user.id_academia
    if current_user.has_role("gestor_associacao"):
        cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (aluno.get("id_academia"),))
        linha = cur.fetchone()
        return bool(linha) and linha.get("id_associacao") == current_user.id_associacao
    return False


# ------------------------------------------- 2) academia: conferência dos dados

@bp_zempo.route("/enviar-link", methods=["POST"])
@login_required
def enviar_link():
    """
    Dispara o link do formulário para uma lista de números.

    Usa o WhatsApp da academia (microserviço) quando ele está pareado. Se não
    estiver, devolve os links wa.me para o navegador abrir — assim o botão nunca
    fica inútil por causa do microserviço.
    """
    if not _pode_solicitar():
        return jsonify({"erro": "sem permissão"}), 403

    numeros = []
    for bruto in (request.form.get("numeros") or "").split(","):
        digitos = re.sub(r"\D", "", bruto)
        if len(digitos) in (10, 11):
            numeros.append(digitos)
    if not numeros:
        return jsonify({"erro": "Informe ao menos um número com DDD."}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        id_associacao = _associacao_do_usuario(cur)
        cur.execute("SELECT slug, zempo_form_token FROM associacoes WHERE id = %s",
                    (id_associacao,))
        assoc = cur.fetchone() or {}
        identificador = (assoc.get("slug") or "").strip() or assoc.get("zempo_form_token")
        if not identificador:
            return jsonify({"erro": "Associação sem link de formulário configurado."}), 400
        link = url_for("zempo_publico.inicio", token=identificador, _external=True)

        academia_id = (request.form.get("academia_id", type=int)
                       or session.get("academia_gerenciamento_id")
                       or current_user.id_academia)
    finally:
        cur.close()
        conn.close()

    mensagem = ("Olá! Para fazer seu cadastro de atleta no Zempo (CBJ), "
                f"preencha seus dados aqui: {link}")

    automatico = bool(academia_id) and whatsapp.disponivel() and whatsapp.conectado(academia_id)
    resultados = []
    for numero in numeros:
        if automatico:
            ok, info = whatsapp.enviar(academia_id, numero, mensagem)
            resultados.append({"numero": numero, "enviado": ok,
                               "erro": None if ok else (info or {}).get("erro")})
        else:
            resultados.append({"numero": numero, "enviado": False,
                               "link": f"https://wa.me/55{numero}?text={quote(mensagem)}"})
    return jsonify({"automatico": automatico, "resultados": resultados})


def _conferencia_pendente(cur, academia_id=None):
    """Solicitações que aguardam a conferência da academia."""
    filtro, parametros = "", []
    if academia_id:
        filtro = " AND s.id_academia = %s"
        parametros.append(academia_id)
    elif not current_user.has_role("admin"):
        if current_user.id_academia:
            filtro = " AND s.id_academia = %s"
            parametros.append(current_user.id_academia)
        elif current_user.id_associacao:
            filtro = " AND s.id_associacao = %s"
            parametros.append(current_user.id_associacao)
    cur.execute(
        """SELECT s.*, a.nome AS aluno_nome, a.cpf, ac.nome AS academia_nome
           FROM zempo_solicitacoes s
           JOIN alunos a ON a.id = s.aluno_id
           LEFT JOIN academias ac ON ac.id = s.id_academia
           WHERE s.status = 'aguardando_academia'""" + filtro
        + " ORDER BY s.solicitado_em", tuple(parametros))
    return cur.fetchall()


@bp_zempo.route("/conferir")
@login_required
def conferir():
    """Academia vê o que os alunos enviaram pelo formulário público."""
    if not _pode_solicitar():
        flash("Você não tem permissão para conferir cadastros do Zempo.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        academia_id = request.args.get("academia_id", type=int)
        solicitacoes = _conferencia_pendente(cur, academia_id)
        for sol in solicitacoes:
            aluno = _carregar_aluno(cur, sol["aluno_id"])
            sol["faltando"] = mapper.validar_aluno(aluno) if aluno else []
    finally:
        cur.close()
        conn.close()

    return render_template("zempo/conferir.html", solicitacoes=solicitacoes,
                           academia_id=academia_id)


@bp_zempo.route("/conferir/<int:solicitacao_id>", methods=["POST"])
@login_required
def confirmar_conferencia(solicitacao_id):
    """Academia confirma os dados e passa a bola para a associação."""
    if not _pode_solicitar():
        flash("Você não tem permissão para conferir cadastros do Zempo.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        cur.execute("SELECT * FROM zempo_solicitacoes WHERE id = %s", (solicitacao_id,))
        sol = cur.fetchone()
        if not sol or sol["status"] != "aguardando_academia":
            flash("Solicitação não encontrada ou já conferida.", "warning")
            return redirect(url_for("zempo.conferir"))

        aluno = _carregar_aluno(cur, sol["aluno_id"])
        if not aluno or not _autorizado_no_aluno(cur, aluno):
            flash("Aluno fora do seu escopo.", "danger")
            return redirect(url_for("zempo.conferir"))

        if request.form.get("rejeitar"):
            cur.execute(
                """UPDATE zempo_solicitacoes
                   SET status='rejeitada', conferido_por=%s, conferido_em=%s, mensagem=%s
                   WHERE id=%s""",
                (current_user.id, datetime.now(),
                 (request.form.get("motivo") or "").strip() or None, solicitacao_id))
            conn.commit()
            flash(f"Cadastro de {aluno['nome']} devolvido.", "info")
            return redirect(url_for("zempo.conferir"))

        # Não deixa passar incompleto: a CBJ exige todos os campos.
        faltando = mapper.validar_aluno(aluno)
        if faltando:
            flash(f"{aluno['nome']} ainda está incompleto — faltam: "
                  + ", ".join(r for _, r in faltando), "danger")
            return redirect(url_for("zempo.conferir"))

        cur.execute(
            """UPDATE zempo_solicitacoes
               SET status='aguardando_associacao', conferido_por=%s, conferido_em=%s
               WHERE id=%s""",
            (current_user.id, datetime.now(), solicitacao_id))
        conn.commit()
        flash(f"{aluno['nome']} confirmado. A associação fará o cadastro na CBJ.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("zempo.conferir"))


# --------------------------------------------------- 3) associação: migração

@bp_zempo.route("/migracoes")
@login_required
def migracoes():
    """Associação vê as solicitações e escolhe quem migrar."""
    if not _pode_migrar():
        flash("Apenas a associação pode migrar cadastros para o Zempo.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        filtro = "" if current_user.has_role("admin") else " AND s.id_associacao = %s"
        parametros = [] if current_user.has_role("admin") else [current_user.id_associacao]

        # Por padrão a tela mostra só o que ainda exige ação: o que já foi migrado
        # ou rejeitado vira histórico e só aparece quando pedido.
        status_filtro = (request.args.get("status") or "pendentes").strip()
        EM_ABERTO = ("aguardando_academia", "aguardando_associacao", "pendente",
                     "aprovada", "erro")
        if status_filtro == "pendentes":
            marcadores = ", ".join(["%s"] * len(EM_ABERTO))
            filtro += f" AND s.status IN ({marcadores})"
            parametros.extend(EM_ABERTO)
        elif status_filtro != "todos":
            filtro += " AND s.status = %s"
            parametros.append(status_filtro)

        cur.execute(
            """SELECT s.*, a.nome AS aluno_nome, a.cpf, a.zempo, ac.nome AS academia_nome,
                      u.nome AS solicitante
               FROM zempo_solicitacoes s
               JOIN alunos a ON a.id = s.aluno_id
               LEFT JOIN academias ac ON ac.id = s.id_academia
               LEFT JOIN usuarios u ON u.id = s.solicitado_por
               WHERE 1 = 1""" + filtro + " ORDER BY s.solicitado_em DESC", tuple(parametros))
        solicitacoes = cur.fetchall()

        # Contagem por status, para o filtro mostrar quanto há em cada um.
        base = "" if current_user.has_role("admin") else " AND s.id_associacao = %s"
        p_base = () if current_user.has_role("admin") else (current_user.id_associacao,)
        cur.execute("SELECT s.status, COUNT(*) AS n FROM zempo_solicitacoes s "
                    "WHERE 1 = 1" + base + " GROUP BY s.status", p_base)
        contagem = {linha["status"]: linha["n"] for linha in cur.fetchall()}
        contagem["pendentes"] = sum(contagem.get(e, 0) for e in EM_ABERTO)
        contagem["todos"] = sum(v for k, v in contagem.items() if k != "pendentes")

        # Recalcula as pendências para não deixar migrar quem ainda está incompleto.
        for sol in solicitacoes:
            aluno = _carregar_aluno(cur, sol["aluno_id"])
            sol["faltando"] = mapper.validar_aluno(aluno) if aluno else []
    finally:
        cur.close()
        conn.close()

    return render_template("zempo/migracoes.html", solicitacoes=solicitacoes,
                           status_filtro=status_filtro, contagem=contagem)


@bp_zempo.route("/migracoes/excluir", methods=["POST"])
@login_required
def excluir_solicitacoes():
    """
    Remove solicitações da fila (duplicadas, erradas ou já resolvidas).

    Só apaga a linha da fila: o aluno e o vínculo com o Zempo continuam intactos.
    """
    if not _pode_migrar():
        flash("Apenas a associação pode excluir solicitações.", "danger")
        return redirect(url_for("painel.home"))

    ids = [int(i) for i in request.form.getlist("solicitacao_ids") if i.isdigit()]
    if not ids:
        flash("Selecione ao menos uma solicitação para excluir.", "warning")
        return redirect(url_for("zempo.migracoes"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        marcadores = ", ".join(["%s"] * len(ids))
        # Restringe ao escopo do usuário: nunca apaga fila de outra associação.
        filtro, parametros = "", list(ids)
        if not current_user.has_role("admin"):
            filtro = " AND id_associacao = %s"
            parametros.append(current_user.id_associacao)
        cur.execute(f"SELECT id FROM zempo_solicitacoes WHERE id IN ({marcadores})" + filtro,
                    tuple(parametros))
        permitidos = [linha["id"] for linha in cur.fetchall()]
        if permitidos:
            alvos = ", ".join(["%s"] * len(permitidos))
            cur.execute(f"DELETE FROM zempo_solicitacoes WHERE id IN ({alvos})",
                        tuple(permitidos))
            conn.commit()
        flash(f"{len(permitidos)} solicitação(ões) excluída(s).", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("zempo.migracoes"))


@bp_zempo.route("/migrar", methods=["POST"])
@login_required
def migrar():
    """Cria no Zempo os alunos das solicitações selecionadas."""
    if not _pode_migrar():
        flash("Apenas a associação pode migrar cadastros para o Zempo.", "danger")
        return redirect(url_for("painel.home"))

    ids = [int(i) for i in request.form.getlist("solicitacao_ids") if i.isdigit()]
    if not ids:
        flash("Selecione ao menos uma solicitação.", "warning")
        return redirect(url_for("zempo.migracoes"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    sucessos, erros = 0, []
    try:
        marcadores = ", ".join(["%s"] * len(ids))
        cur.execute(
            f"""SELECT s.*, a.nome AS aluno_nome FROM zempo_solicitacoes s
                JOIN alunos a ON a.id = s.aluno_id
                WHERE s.id IN ({marcadores})
                  AND s.status IN ('aguardando_associacao','pendente','aprovada','erro')""",
            tuple(ids))
        solicitacoes = cur.fetchall()

        # A tela deixa marcar qualquer linha (para permitir excluir); aqui só
        # migram as que estão em etapa válida, e o resto é informado.
        ignoradas = len(ids) - len(solicitacoes)
        if ignoradas:
            flash(f"{ignoradas} solicitação(ões) não migrada(s): já migradas, rejeitadas "
                  "ou ainda aguardando a conferência da academia.", "info")

        clientes = {}
        for sol in solicitacoes:
            nome = sol["aluno_nome"]
            try:
                id_assoc = sol["id_associacao"]
                if id_assoc not in clientes:
                    clientes[id_assoc] = _cliente(cur, id_assoc)
                cli = clientes[id_assoc]

                aluno = _carregar_aluno(cur, sol["aluno_id"])
                if not _autorizado_no_aluno(cur, aluno):
                    raise ZempoError("Aluno fora do seu escopo.")

                faltando = mapper.validar_aluno(aluno)
                if faltando:
                    raise ZempoError("Faltam campos obrigatórios: "
                                     + ", ".join(r for _, r in faltando))

                # Se já existe no Zempo com esse CPF, vincula em vez de duplicar.
                ja_existe = cli.buscar_por_cpf(aluno.get("cpf"))
                if ja_existe:
                    zempo_id, numero = ja_existe, f"JU{ja_existe}"
                    aviso = " (já existia no Zempo — apenas vinculado)"
                else:
                    payload = mapper.montar_payload(aluno, cli)
                    zempo_id, numero = cli.criar_atleta(payload, _foto_do_aluno(aluno))
                    aviso = ""

                _gravar_vinculo(cur, aluno["id"], zempo_id, numero)
                cur.execute(
                    """UPDATE zempo_solicitacoes
                       SET status='migrada', processado_por=%s, processado_em=%s,
                           zempo_id=%s, zempo_numero=%s, mensagem=%s
                       WHERE id=%s""",
                    (current_user.id, datetime.now(), zempo_id, numero,
                     ("Vinculado a cadastro existente." if aviso else None), sol["id"]))
                conn.commit()
                sucessos += 1
                if aviso:
                    flash(f"{nome}: {numero}{aviso}", "info")

            except (ZempoError, ValueError) as e:
                conn.rollback()
                cur.execute(
                    """UPDATE zempo_solicitacoes
                       SET status='erro', processado_por=%s, processado_em=%s, mensagem=%s
                       WHERE id=%s""",
                    (current_user.id, datetime.now(), str(e), sol["id"]))
                conn.commit()
                erros.append(f"{nome}: {e}")
    finally:
        cur.close()
        conn.close()

    if sucessos:
        flash(f"{sucessos} aluno(s) cadastrado(s) no Zempo.", "success")
    for erro in erros:
        flash(erro, "danger")
    return redirect(url_for("zempo.migracoes"))


def _gravar_vinculo(cur, aluno_id, zempo_id, numero):
    cur.execute(
        """UPDATE alunos SET zempo=%s, zempo_id=%s, link_zempo=%s, zempo_sincronizado_em=%s
           WHERE id=%s""",
        (numero, zempo_id,
         f"https://zempo.com.br/index.php?secao=pessoas_editar&detalhes=1&id={zempo_id}",
         datetime.now(), aluno_id))


# ----------------------------------------------------- 3) sincronização

def _preparar_sync(cur, aluno_id):
    """
    Localiza o aluno no Zempo (pelo número gravado ou pelo CPF) e calcula o diff.
    Retorna (aluno, zempo_id, diferencas). Levanta ZempoError com a razão.
    """
    aluno = _carregar_aluno(cur, aluno_id)
    if not aluno or not _autorizado_no_aluno(cur, aluno):
        raise ZempoError("Aluno não encontrado.")

    cli = _cliente(cur, _associacao_do_usuario(cur))
    zempo_id = (aluno.get("zempo_id") or "").strip() or cli.buscar_por_cpf(aluno.get("cpf"))
    if not zempo_id:
        raise ZempoError(f"{aluno['nome']} não tem cadastro no Zempo com este CPF. "
                         "Faça a migração primeiro.")

    dados_zempo = cli.ler_pessoa(zempo_id)
    # A data de registro na federação só aparece na ficha impressa.
    dados_zempo.update(cli.dados_da_ficha(zempo_id))
    # Com o cliente, o diff também traduz os ids de cidade e bairro.
    return aluno, zempo_id, mapper.comparar(dados_zempo, aluno, cliente=cli)


def _aplicar_sync(cur, aluno_id, zempo_id, diferencas, escolhidos):
    """Grava no aluno os campos escolhidos e vincula o número do Zempo."""
    atualizacoes = {}
    for dif in diferencas:
        if dif["campo"] not in escolhidos:
            continue
        valor = mapper.valor_para_banco(dif["campo"], dif["valor_zempo"])
        if valor is not None:
            atualizacoes[dif["coluna"]] = valor

    # `faixa` vem de outra tabela: vira graduacao_id.
    if "faixa" in atualizacoes:
        cur.execute("SELECT id FROM graduacao WHERE UPPER(faixa) = UPPER(%s) LIMIT 1",
                    (atualizacoes.pop("faixa"),))
        grad = cur.fetchone()
        if grad:
            atualizacoes["graduacao_id"] = grad["id"]

    if atualizacoes:
        colunas = ", ".join(f"{c} = %s" for c in atualizacoes)
        cur.execute(f"UPDATE alunos SET {colunas} WHERE id = %s",
                    tuple(atualizacoes.values()) + (aluno_id,))
    _gravar_vinculo(cur, aluno_id, zempo_id, f"JU{zempo_id}")
    return len(atualizacoes)


@bp_zempo.route("/vincular-lote/candidatos")
@login_required
def vincular_lote_candidatos():
    """Ids dos alunos que têm CPF e ainda não têm número do Zempo."""
    if not _pode_solicitar():
        return jsonify({"erro": "Sem permissão."}), 403
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        academias = _academias_permitidas(cur)
        academia_id = request.args.get("academia_id", type=int)
        if academia_id and academia_id not in [a["id"] for a in academias]:
            academia_id = None
        alunos = _alunos_visiveis(cur, academia_id, academias)
        # `refazer` reconsulta quem já foi procurado antes: um aluno sem cadastro
        # hoje pode ter sido registrado na CBJ depois da última busca.
        refazer = request.args.get("refazer") == "1"

        candidatos, ja_buscados = [], []
        for a in alunos:
            if len(re.sub(r"\D", "", a.get("cpf") or "")) != 11:
                continue
            if (a.get("zempo") or "").strip():
                continue
            if a.get("zempo_busca_em") and not refazer:
                ja_buscados.append({
                    "id": a["id"], "nome": a["nome"],
                    "em": a["zempo_busca_em"].strftime("%d/%m/%Y"),
                })
                continue
            candidatos.append({"id": a["id"], "nome": a["nome"]})

        return jsonify({"candidatos": candidatos, "ja_buscados": len(ja_buscados)})
    finally:
        cur.close()
        conn.close()


@bp_zempo.route("/vincular-lote", methods=["POST"])
@login_required
def vincular_lote():
    """
    Procura no Zempo, pelo CPF, um lote de alunos e grava o número encontrado.

    Trabalha em lotes pequenos porque cada consulta ao Zempo leva alguns segundos:
    a tela chama esta rota várias vezes e vai mostrando o progresso, em vez de
    prender uma única requisição por minutos.
    """
    if not _pode_solicitar():
        return jsonify({"erro": "Sem permissão."}), 403

    ids = [int(i) for i in request.form.getlist("aluno_ids") if i.isdigit()][:10]
    if not ids:
        return jsonify({"erro": "Nenhum aluno informado."}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    resultados = []
    try:
        try:
            cli = _cliente(cur, _associacao_do_usuario(cur))
        except ZempoError as e:
            return jsonify({"erro": str(e)}), 400

        for aluno_id in ids:
            aluno = _carregar_aluno(cur, aluno_id)
            if not aluno or not _autorizado_no_aluno(cur, aluno):
                continue
            nome = aluno["nome"]
            if (aluno.get("zempo") or "").strip():
                resultados.append({"id": aluno_id, "nome": nome, "situacao": "ja_tinha",
                                   "numero": aluno["zempo"]})
                continue
            try:
                zempo_id = cli.buscar_por_cpf(aluno.get("cpf"))
            except ZempoError as e:
                resultados.append({"id": aluno_id, "nome": nome, "situacao": "erro",
                                   "detalhe": str(e)[:120]})
                continue

            # Registra a consulta para não repetir o mesmo CPF a cada rodada.
            cur.execute(
                "UPDATE alunos SET zempo_busca_em = %s, zempo_busca_resultado = %s WHERE id = %s",
                (datetime.now(), "encontrado" if zempo_id else "nao_encontrado", aluno_id))

            if zempo_id:
                _gravar_vinculo(cur, aluno_id, zempo_id, f"JU{zempo_id}")
                conn.commit()
                resultados.append({"id": aluno_id, "nome": nome, "situacao": "vinculado",
                                   "numero": f"JU{zempo_id}"})
            else:
                conn.commit()
                resultados.append({"id": aluno_id, "nome": nome, "situacao": "nao_existe"})
    finally:
        cur.close()
        conn.close()
    return jsonify({"resultados": resultados})


@bp_zempo.route("/sincronizar/<int:aluno_id>/dados")
@login_required
def sincronizar_dados(aluno_id):
    """Diff em JSON, para o modal da lista abrir sem trocar de página."""
    if not _pode_solicitar():
        return jsonify({"erro": "Sem permissão."}), 403
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        aluno, zempo_id, diferencas = _preparar_sync(cur, aluno_id)
        return jsonify({
            "aluno": aluno["nome"],
            "zempo_id": zempo_id,
            "zempo_numero": f"JU{zempo_id}",
            "diferencas": diferencas,
            "pode_migrar": _pode_migrar(),
        })
    except ZempoError as e:
        return jsonify({"erro": str(e)}), 400
    finally:
        cur.close()
        conn.close()


@bp_zempo.route("/sincronizar/<int:aluno_id>/aplicar", methods=["POST"])
@login_required
def sincronizar_aplicar(aluno_id):
    """Aplica os campos marcados no modal."""
    if not _pode_solicitar():
        return jsonify({"erro": "Sem permissão."}), 403
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        aluno, zempo_id, diferencas = _preparar_sync(cur, aluno_id)
        escolhidos = set(request.form.getlist("campos"))
        total = _aplicar_sync(cur, aluno_id, zempo_id, diferencas, escolhidos)
        conn.commit()
        return jsonify({"ok": True, "atualizados": total, "zempo_numero": f"JU{zempo_id}"})
    except ZempoError as e:
        conn.rollback()
        return jsonify({"erro": str(e)}), 400
    finally:
        cur.close()
        conn.close()


@bp_zempo.route("/sincronizar/<int:aluno_id>", methods=["GET", "POST"])
@login_required
def sincronizar(aluno_id):
    """
    Traz os dados do Zempo para o sistema, localizando o aluno pelo CPF.
    GET mostra a prévia do que muda; POST aplica só os campos marcados.
    """
    if not _pode_solicitar():
        flash("Você não tem permissão para sincronizar com o Zempo.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        try:
            aluno, zempo_id, diferencas = _preparar_sync(cur, aluno_id)
        except ZempoError as e:
            flash(str(e), "danger")
            return redirect(url_for("zempo.solicitar"))

        if request.method == "POST":
            total = _aplicar_sync(cur, aluno_id, zempo_id, diferencas,
                                  set(request.form.getlist("campos")))
            conn.commit()
            flash(f"{total} campo(s) atualizado(s) a partir do Zempo.", "success")
            return redirect(url_for("zempo.sincronizar", aluno_id=aluno_id))
    finally:
        cur.close()
        conn.close()

    return render_template("zempo/sincronizar.html", aluno=aluno, diferencas=diferencas,
                           zempo_id=zempo_id, zempo_numero=f"JU{zempo_id}",
                           pode_migrar=_pode_migrar())


@bp_zempo.route("/enviar/<int:aluno_id>", methods=["POST"])
@login_required
def enviar(aluno_id):
    """Sentido inverso: atualiza o cadastro no Zempo com o que está no sistema."""
    if not _pode_migrar():
        flash("Apenas a associação pode alterar cadastros no Zempo.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        aluno = _carregar_aluno(cur, aluno_id)
        if not aluno or not _autorizado_no_aluno(cur, aluno):
            flash("Aluno não encontrado.", "danger")
            return redirect(url_for("zempo.solicitar"))
        try:
            cli = _cliente(cur, _associacao_do_usuario(cur))
            zempo_id = (aluno.get("zempo_id") or "").strip() or cli.buscar_por_cpf(aluno.get("cpf"))
            if not zempo_id:
                raise ZempoError("Aluno ainda não está no Zempo. Faça a migração primeiro.")

            faltando = mapper.validar_aluno(aluno)
            if faltando:
                raise ZempoError("Faltam campos obrigatórios: "
                                 + ", ".join(r for _, r in faltando))

            payload = mapper.montar_payload(aluno, cli)
            # Identidade e senha não são reenviadas numa atualização.
            for chave in ("senha", "senha2", "cpf", "nascimento"):
                payload.pop(chave, None)
            cli.atualizar_pessoa(zempo_id, payload, _foto_do_aluno(aluno))

            _gravar_vinculo(cur, aluno_id, zempo_id, f"JU{zempo_id}")
            conn.commit()
            flash(f"Cadastro de {aluno['nome']} atualizado no Zempo (JU{zempo_id}).", "success")
        except (ZempoError, ValueError) as e:
            conn.rollback()
            flash(str(e), "danger")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("zempo.sincronizar", aluno_id=aluno_id))


# --------------------------------------------------- configuração da associação

@bp_zempo.route("/configuracao", methods=["GET", "POST"])
@login_required
def configuracao():
    """Credenciais do Zempo da associação."""
    if not _pode_migrar():
        flash("Apenas a associação pode configurar a integração Zempo.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        id_associacao = request.args.get("id_associacao", type=int) or current_user.id_associacao
        if not id_associacao:
            flash("Selecione uma associação.", "warning")
            return redirect(url_for("painel.home"))

        if request.method == "POST":
            nova_senha = (request.form.get("zempo_senha") or "").strip()
            cur.execute(
                """UPDATE associacoes
                   SET zempo_codigo=%s, zempo_clube_id=%s, zempo_federacao_id=%s,
                       zempo_habilitado=%s
                   WHERE id=%s""",
                ((request.form.get("zempo_codigo") or "").strip(),
                 (request.form.get("zempo_clube_id") or "").strip(),
                 (request.form.get("zempo_federacao_id") or "").strip(),
                 1 if request.form.get("zempo_habilitado") else 0,
                 id_associacao))
            # A senha só é sobrescrita quando um novo valor é digitado.
            if nova_senha:
                cur.execute("UPDATE associacoes SET zempo_senha=%s WHERE id=%s",
                            (nova_senha, id_associacao))
            conn.commit()

            if request.form.get("testar"):
                try:
                    cli = _cliente(cur, id_associacao)
                    cli.login()
                    flash("Conexão com o Zempo funcionando.", "success")
                except ZempoError as e:
                    flash(f"Falha no teste: {e}", "danger")
            else:
                flash("Configuração do Zempo salva.", "success")
            return redirect(url_for("zempo.configuracao", id_associacao=id_associacao))

        cur.execute("SELECT * FROM associacoes WHERE id = %s", (id_associacao,))
        associacao = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    return render_template("zempo/configuracao.html", associacao=associacao,
                           senha_definida=bool((associacao or {}).get("zempo_senha")))
