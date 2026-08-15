"""
Formulário público do Zempo — o aluno preenche pelo link da associação.

Fluxo (sem login):
  1. GET  /zempo/form/<token>            -> pede só o CPF
  2. POST /zempo/form/<token>/consultar  -> procura o CPF no sistema; se não achar,
     procura no Zempo; devolve o formulário já preenchido com o que existe e
     destacando o que falta
  3. POST /zempo/form/<token>/enviar     -> valida TUDO (nada incompleto passa,
     foto inclusive), grava o aluno e abre a solicitação para a academia conferir

Depois disso o cadastro segue: academia confere -> associação aprova e migra.
"""
import base64
import binascii
import os
import re
from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from config import get_db_connection
from extensions import csrf
from utils.zempo import ZempoClient, ZempoError
from utils import zempo_mapper as mapper

bp_zempo_publico = Blueprint("zempo_publico", __name__, url_prefix="/zempo/form")

# Campos que o formulário coleta, na ordem em que aparecem na tela.
# (nome no formulário, rótulo, tipo)
CAMPOS_FORM = [
    ("nome", "Nome completo", "text"),
    ("data_nascimento", "Data de nascimento", "date"),
    ("sexo", "Sexo", "sexo"),
    ("email", "E-mail", "email"),
    ("tel_celular", "Celular", "tel"),
    ("tel_residencial", "Telefone residencial", "tel"),
    ("faixa", "Graduação (faixa)", "faixa"),
    ("ultimo_exame_faixa", "Data da última graduação", "date"),
    ("peso", "Peso (kg)", "number"),
    ("rg", "RG", "text"),
    ("orgao_emissor", "Órgão emissor do RG", "text"),
    ("rg_uf", "Estado emissor do RG", "uf"),
    ("rg_data_emissao", "Data de emissão do RG", "date"),
    ("naturalidade", "Naturalidade (UF)", "uf"),
    ("nacionalidade", "Nacionalidade", "text"),
    ("cep", "CEP", "text"),
    ("rua", "Endereço (rua)", "text"),
    ("numero", "Número", "text"),
    ("complemento", "Complemento", "text"),
    ("bairro", "Bairro", "text"),
    ("cidade", "Cidade", "text"),
    ("estado", "Estado (UF)", "uf"),
    ("nome_pai", "Nome do pai", "text"),
    ("nome_mae", "Nome da mãe", "text"),
    ("responsavel_nome", "Nome do responsável", "text"),
    ("responsavel_parentesco", "Parentesco do responsável", "text"),
]

# Colunas que o aluno pode preencher — nada fora daqui é gravado a partir do
# formulário público.
COLUNAS_PERMITIDAS = {nome for nome, _, _ in CAMPOS_FORM}

# Só estes são exigidos pelo Zempo. `complemento`, pai/mãe e responsável ajudam
# mas não bloqueiam. `foto` é tratada à parte (é upload).
OBRIGATORIOS_FORM = {
    "nome", "data_nascimento", "sexo", "email", "tel_celular", "tel_residencial",
    "faixa", "ultimo_exame_faixa", "peso", "rg", "orgao_emissor", "rg_uf",
    "rg_data_emissao", "naturalidade", "cep", "rua", "numero", "bairro",
    "cidade", "estado",
}


# ------------------------------------------------------------------ contexto

def _associacao_por_token(cur, token):
    """
    Resolve a associação pelo slug do link (ex.: 'judo-artefisica').

    O token aleatório antigo continua aceito para não quebrar links já
    distribuídos.
    """
    campos = """id, nome, slug, zempo_codigo, zempo_senha, zempo_habilitado,
                zempo_clube_id, zempo_federacao_id"""
    cur.execute(f"SELECT {campos} FROM associacoes WHERE slug = %s", (token,))
    assoc = cur.fetchone()
    if not assoc:
        cur.execute(f"SELECT {campos} FROM associacoes WHERE zempo_form_token = %s", (token,))
        assoc = cur.fetchone()
    if not assoc:
        abort(404)
    return assoc


def link_da_associacao(assoc):
    """Identificador usado na URL pública: o slug, com o token como reserva."""
    return (assoc.get("slug") or "").strip() or assoc.get("zempo_form_token")


def _academias_da_associacao(cur, id_associacao):
    cur.execute("SELECT id, nome FROM academias WHERE id_associacao = %s ORDER BY nome",
                (id_associacao,))
    return cur.fetchall()


def _cliente(assoc):
    """ZempoClient da associação, ou None se ela não tem a integração pronta."""
    cli = ZempoClient(assoc.get("zempo_codigo"), assoc.get("zempo_senha"),
                      assoc.get("zempo_clube_id"), assoc.get("zempo_federacao_id"))
    if not (assoc.get("zempo_habilitado") and cli.configurado
            and cli.clube_id and cli.federacao_id):
        return None
    return cli


def _digitos(valor):
    return re.sub(r"\D", "", valor or "")


# --------------------------------------------------------------- etapa 1: CPF

@bp_zempo_publico.route("/<token>")
def inicio(token):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        assoc = _associacao_por_token(cur, token)
        token = link_da_associacao(assoc)
    finally:
        cur.close()
        conn.close()
    return render_template("zempo/publico_cpf.html", assoc=assoc, token=token)


# ------------------------------------------------- etapa 2: consulta e preenche

@bp_zempo_publico.route("/<token>/consultar", methods=["POST"])
@csrf.exempt
def consultar(token):
    """Procura o CPF no sistema e, se não achar, no Zempo. Devolve o formulário."""
    cpf_digitos = _digitos(request.form.get("cpf"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        assoc = _associacao_por_token(cur, token)
        token = link_da_associacao(assoc)
        academias = _academias_da_associacao(cur, assoc["id"])

        if len(cpf_digitos) != 11:
            flash("Informe um CPF válido, com 11 dígitos.", "warning")
            return redirect(url_for("zempo_publico.inicio", token=token))

        cpf_fmt = mapper._cpf_formatado(cpf_digitos)
        aluno, origem = _buscar_no_sistema(cur, cpf_digitos, assoc["id"])
        aviso = None

        if aluno:
            if (aluno.get("zempo") or "").strip():
                flash(f"{aluno['nome']} já está cadastrado na CBJ "
                      f"({aluno['zempo']}). Não é preciso enviar de novo.", "info")
                return redirect(url_for("zempo_publico.inicio", token=token))
            valores = _valores_do_aluno(aluno)
        else:
            valores, aviso = _valores_do_zempo(assoc, cpf_digitos)
            origem = "zempo" if valores else "novo"
            valores = valores or {}

        faltando = _faltando(valores)
    finally:
        cur.close()
        conn.close()

    if aviso:
        flash(aviso, "info")
    return render_template(
        "zempo/publico_form.html", assoc=assoc, token=token, cpf=cpf_fmt,
        campos=CAMPOS_FORM, valores=valores, faltando=faltando,
        academias=academias, aluno_id=(aluno or {}).get("id"), origem=origem,
        ufs=sorted(mapper.UF_PARA_ID), faixas=mapper.FAIXAS_EM_ORDEM)


def _buscar_no_sistema(cur, cpf_digitos, id_associacao):
    """Aluno da associação com este CPF (compara só os dígitos)."""
    cur.execute(
        """SELECT a.*, g.faixa AS faixa
           FROM alunos a
           LEFT JOIN graduacao g ON g.id = a.graduacao_id
           LEFT JOIN academias ac ON ac.id = a.id_academia
           WHERE REPLACE(REPLACE(a.cpf, '.', ''), '-', '') = %s
             AND (ac.id_associacao = %s OR a.id_associacao = %s)
           LIMIT 1""",
        (cpf_digitos, id_associacao, id_associacao))
    aluno = cur.fetchone()
    return aluno, ("sistema" if aluno else None)


def _valores_do_aluno(aluno):
    """Converte a linha de `alunos` para os valores do formulário."""
    valores = {}
    for nome, _, tipo in CAMPOS_FORM:
        bruto = aluno.get(nome)
        if tipo == "date":
            valores[nome] = bruto.strftime("%Y-%m-%d") if hasattr(bruto, "strftime") else ""
        elif bruto in (None, ""):
            valores[nome] = ""
        else:
            valores[nome] = str(bruto)
    valores["foto"] = (aluno.get("foto") or "").strip()
    return valores


def _valores_do_zempo(assoc, cpf_digitos):
    """
    Se o CPF já existir no Zempo, traz os dados de lá para o aluno só conferir.
    Retorna (valores, aviso). Falha de rede não quebra o formulário.
    """
    cli = _cliente(assoc)
    if not cli:
        return {}, None
    try:
        zempo_id = cli.buscar_por_cpf(cpf_digitos)
        if not zempo_id:
            return {}, None
        dados = cli.ler_pessoa(zempo_id)
    except ZempoError:
        return {}, None
    except Exception:
        return {}, None

    def data(valor):
        try:
            return datetime.strptime(valor, "%d/%m/%Y").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return ""

    valores = {
        "nome": dados.get("nome") or "",
        "data_nascimento": data(dados.get("nascimento")),
        "sexo": mapper.ID_PARA_SEXO.get(dados.get("sexo"), ""),
        "email": dados.get("email") or "",
        "tel_celular": dados.get("celular") or "",
        "tel_residencial": dados.get("telefone") or "",
        "faixa": mapper.ID_PARA_FAIXA.get(dados.get("graduacao"), ""),
        "ultimo_exame_faixa": data(dados.get("graduacao_data")),
        "peso": dados.get("peso") or "",
        "rg": dados.get("rg") or "",
        "orgao_emissor": dados.get("rg_orgao") or "",
        "rg_uf": mapper.ID_PARA_UF.get(dados.get("rg_estado"), ""),
        "rg_data_emissao": data(dados.get("rg_data")),
        "naturalidade": mapper.ID_PARA_UF.get(dados.get("naturalidade"), ""),
        "nacionalidade": dados.get("nacionalidade") or "Brasil",
        "cep": dados.get("cep") or "",
        "rua": dados.get("endereco") or "",
        "numero": "",
        "complemento": dados.get("complemento") or "",
        "estado": mapper.ID_PARA_UF.get(dados.get("estado"), ""),
        # cidade/bairro no Zempo são ids; o aluno digita o nome.
        "cidade": "",
        "bairro": "",
        "nome_pai": dados.get("pai") or "",
        "nome_mae": dados.get("mae") or "",
        "responsavel_nome": dados.get("responsavel") or "",
        "responsavel_parentesco": dados.get("responsavel_parentesco") or "",
    }
    return valores, ("Encontramos seu cadastro na CBJ e já preenchemos o que foi "
                     "possível. Confira e complete o que falta.")


def _faltando(valores):
    """Campos obrigatórios ainda vazios — é o que a tela destaca."""
    return {nome for nome in OBRIGATORIOS_FORM if not str(valores.get(nome) or "").strip()}


# ---------------------------------------------------------------- etapa 3: envio

@bp_zempo_publico.route("/<token>/enviar", methods=["POST"])
@csrf.exempt
def enviar(token):
    """Valida tudo, grava o aluno e abre a solicitação para a academia conferir."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        assoc = _associacao_por_token(cur, token)
        token = link_da_associacao(assoc)
        academias = _academias_da_associacao(cur, assoc["id"])

        cpf_digitos = _digitos(request.form.get("cpf"))
        aluno_id = request.form.get("aluno_id", type=int)
        valores = {nome: (request.form.get(nome) or "").strip()
                   for nome in COLUNAS_PERMITIDAS}

        # "Não possuo RG": repete o CPF no campo. Refeito aqui porque o campo vai
        # readonly no navegador e não se pode confiar só no JavaScript.
        if request.form.get("sem_rg"):
            valores["rg"] = mapper._cpf_formatado(cpf_digitos) or valores.get("rg", "")

        erros = _validar(valores, cpf_digitos)

        # Academia: a do cadastro existente prevalece. A opção "0" na lista significa
        # "minha academia não está cadastrada" — o cadastro segue mesmo assim e a
        # associação vincula a academia depois.
        escolha = request.form.get("academia_id", "").strip()
        academia_id = int(escolha) if escolha.isdigit() else None
        if aluno_id:
            cur.execute("SELECT id_academia FROM alunos WHERE id = %s", (aluno_id,))
            linha = cur.fetchone()
            academia_id = (linha or {}).get("id_academia") or academia_id
        if academia_id == 0:
            academia_id = None
        elif academia_id is None:
            erros["academia_id"] = "Selecione a academia onde você treina."
        elif academia_id not in {a["id"] for a in academias}:
            erros["academia_id"] = "Academia inválida."

        # Foto: obrigatória. Aceita arquivo enviado ou capturada pela câmera.
        arquivo = request.files.get("foto")
        da_camera = (request.form.get("foto_camera") or "").strip()
        tem_foto_atual = bool((request.form.get("foto_atual") or "").strip())
        if not tem_foto_atual and not (arquivo and arquivo.filename) and not da_camera:
            erros["foto"] = "Envie uma foto do aluno ou tire uma pela câmera."

        if erros:
            for mensagem in erros.values():
                flash(mensagem, "danger")
            return render_template(
                "zempo/publico_form.html", assoc=assoc, token=token,
                cpf=mapper._cpf_formatado(cpf_digitos), campos=CAMPOS_FORM,
                valores=valores, faltando=set(erros), academias=academias,
                aluno_id=aluno_id, origem="reenvio",
                ufs=sorted(mapper.UF_PARA_ID), faixas=mapper.FAIXAS_EM_ORDEM)

        if arquivo and arquivo.filename:
            nome_foto = _salvar_foto(arquivo)
        elif da_camera:
            nome_foto = _salvar_foto_base64(da_camera)
        else:
            nome_foto = None
        aluno_id = _gravar_aluno(cur, aluno_id, valores, cpf_digitos,
                                 academia_id, assoc["id"], nome_foto)

        # Sem academia não há quem confira: vai direto para a associação, que
        # vincula a academia antes de migrar.
        situacao = "aguardando_academia" if academia_id else "aguardando_associacao"

        # Uma solicitação em aberto por aluno.
        cur.execute(
            """SELECT id FROM zempo_solicitacoes WHERE aluno_id = %s
               AND status IN ('pendente','aprovada','aguardando_academia','aguardando_associacao')""",
            (aluno_id,))
        if not cur.fetchone():
            cur.execute(
                """INSERT INTO zempo_solicitacoes
                   (aluno_id, id_academia, id_associacao, status, origem, solicitado_em)
                   VALUES (%s, %s, %s, %s, 'formulario', %s)""",
                (aluno_id, academia_id, assoc["id"], situacao, datetime.now()))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return render_template("zempo/publico_ok.html", assoc=assoc, token=token,
                           sem_academia=not academia_id)


def _validar(valores, cpf_digitos):
    """{campo: mensagem} do que impede o envio. Nada incompleto passa."""
    erros = {}
    if len(cpf_digitos) != 11:
        erros["cpf"] = "CPF inválido."
    for nome, rotulo, _ in CAMPOS_FORM:
        if nome in OBRIGATORIOS_FORM and not valores.get(nome):
            erros[nome] = f"Preencha: {rotulo}."

    if valores.get("estado") and valores["estado"].upper() not in mapper.UF_PARA_ID:
        erros["estado"] = "Estado inválido — use a sigla (ex.: PE)."
    if valores.get("naturalidade") and valores["naturalidade"].upper() not in mapper.UF_PARA_ID:
        erros["naturalidade"] = "Naturalidade inválida — use a sigla da UF."
    if valores.get("rg_uf") and valores["rg_uf"].upper() not in mapper.UF_PARA_ID:
        erros["rg_uf"] = "Estado emissor do RG inválido."
    if valores.get("faixa") and not mapper._faixa_id(valores["faixa"]):
        erros["faixa"] = "Graduação não reconhecida pela CBJ."
    if valores.get("email") and "@" not in valores["email"]:
        erros["email"] = "E-mail inválido."
    if valores.get("peso"):
        try:
            if float(str(valores["peso"]).replace(",", ".")) <= 0:
                raise ValueError
        except ValueError:
            erros["peso"] = "Peso inválido."
    return erros


def _salvar_foto(arquivo):
    """Grava a foto em static/uploads e devolve o nome do arquivo."""
    extensao = os.path.splitext(arquivo.filename)[1].lower()
    if extensao not in (".jpg", ".jpeg", ".png", ".gif"):
        extensao = ".jpg"
    nome = f"zempo_form_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{extensao}"
    destino = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(destino, exist_ok=True)
    arquivo.save(os.path.join(destino, nome))
    return nome


def _salvar_foto_base64(data_url):
    """Grava a foto capturada pela câmera (data URL) e devolve o nome do arquivo."""
    conteudo = data_url.split(",", 1)[-1]
    try:
        binario = base64.b64decode(conteudo, validate=True)
    except (binascii.Error, ValueError):
        return None
    nome = f"zempo_form_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
    destino = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(destino, exist_ok=True)
    with open(os.path.join(destino, nome), "wb") as fh:
        fh.write(binario)
    return nome


def _gravar_aluno(cur, aluno_id, valores, cpf_digitos, academia_id, id_associacao, nome_foto):
    """Atualiza o aluno existente ou cria um novo. Devolve o id."""
    dados = {nome: (valores.get(nome) or None) for nome in COLUNAS_PERMITIDAS
             if nome != "faixa"}
    dados["cpf"] = mapper._cpf_formatado(cpf_digitos)
    dados["estado"] = (valores.get("estado") or "").upper() or None
    dados["naturalidade"] = (valores.get("naturalidade") or "").upper() or None
    dados["rg_uf"] = (valores.get("rg_uf") or "").upper() or None
    if nome_foto:
        dados["foto"] = nome_foto

    # A faixa vira graduacao_id.
    cur.execute("SELECT id FROM graduacao WHERE UPPER(faixa) = UPPER(%s) LIMIT 1",
                (valores.get("faixa"),))
    grad = cur.fetchone()
    if grad:
        dados["graduacao_id"] = grad["id"]

    if aluno_id:
        colunas = ", ".join(f"{c} = %s" for c in dados)
        cur.execute(f"UPDATE alunos SET {colunas} WHERE id = %s",
                    tuple(dados.values()) + (aluno_id,))
        return aluno_id

    dados.update({"id_academia": academia_id, "id_associacao": id_associacao,
                  "ativo": 1, "status": "ativo", "data_matricula": datetime.now().date()})
    colunas = ", ".join(dados)
    marcadores = ", ".join(["%s"] * len(dados))
    cur.execute(f"INSERT INTO alunos ({colunas}) VALUES ({marcadores})",
                tuple(dados.values()))
    return cur.lastrowid
