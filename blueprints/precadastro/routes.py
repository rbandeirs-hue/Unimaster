# ======================================================
# Pré-cadastro — listagem, formulário público e promover
# ======================================================
import os
import re
import base64
import unicodedata
import uuid
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from flask_login import login_required, current_user
from extensions import csrf
from config import get_db_connection
from math import ceil
from werkzeug.security import generate_password_hash

bp_precadastro = Blueprint("precadastro", __name__, url_prefix="/precadastro")


def _slugify(nome):
    """Converte nome em slug URL-amigável: 'Academia Judô Centro' -> 'academia-judo-centro'."""
    if not nome:
        return ""
    s = unicodedata.normalize("NFD", str(nome))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-") or "academia"

UPLOAD_PRECAD = "precadastro"


def _salvar_foto_precad_file(file_storage, prefix):
    """Salva foto de upload em static/uploads/precadastro/."""
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return None
    filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
    folder = os.path.join(current_app.root_path, "static", "uploads", UPLOAD_PRECAD)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    file_storage.save(filepath)
    return filename


def _salvar_foto_precad_base64(data_url, prefix):
    """Salva foto base64 (câmera) em static/uploads/precadastro/."""
    if not data_url:
        return None
    try:
        if "," in data_url:
            _, encoded = data_url.split(",", 1)
        else:
            encoded = data_url
        img_data = base64.b64decode(encoded)
    except Exception:
        return None
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
    folder = os.path.join(current_app.root_path, "static", "uploads", UPLOAD_PRECAD)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, "wb") as f:
        f.write(img_data)
    return filename


def _salvar_foto_visitante_file(file_storage, prefix="visitante"):
    """Salva foto de visitante em static/uploads/ (raiz) e retorna o nome do arquivo."""
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return None
    filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
    folder = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, filename))
    return filename


def _salvar_foto_visitante_base64(data_url, prefix="visitante"):
    """Salva foto base64 (câmera) de visitante em static/uploads/ (raiz)."""
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        encoded = data_url.split(",", 1)[1] if "," in data_url else data_url
        img_data = base64.b64decode(encoded)
    except Exception:
        return None
    filename = f"{prefix}_{uuid.uuid4().hex[:12]}.png"
    folder = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, filename), "wb") as f:
        f.write(img_data)
    return filename


def _get_academias_ids():
    """IDs de academias acessíveis (prioridade: usuarios_academias)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id", (current_user.id,))
        vinculadas = [r["academia_id"] for r in cur.fetchall()]
        if vinculadas:
            cur.close()
            conn.close()
            return vinculadas
        # Modo academia: gestor_academia/professor só veem academias de usuarios_academias (não id_academia)
        if session.get("modo_painel") == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
            cur.close()
            conn.close()
            return []
        ids = []
        if current_user.has_role("admin"):
            cur.execute("SELECT id FROM academias ORDER BY nome")
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_federacao"):
            cur.execute(
                "SELECT ac.id FROM academias ac JOIN associacoes ass ON ass.id = ac.id_associacao WHERE ass.id_federacao = %s ORDER BY ac.nome",
                (getattr(current_user, "id_federacao", None),),
            )
            ids = [r["id"] for r in cur.fetchall()]
        elif current_user.has_role("gestor_associacao"):
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome", (getattr(current_user, "id_associacao", None),))
            ids = [r["id"] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return ids
    except Exception:
        return []


def _get_academia_filtro():
    """Retorna (academia_id, academias)."""
    ids = _get_academias_ids()
    if not ids:
        return None, []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids)), tuple(ids))
    academias = cur.fetchall()
    cur.close()
    conn.close()
    if len(ids) == 1:
        return ids[0], academias
    raw = request.args.get("academia_id", type=str)
    if raw is not None:
        aid = int(raw) if raw and raw != "0" else None
        if aid is not None:
            session["academia_gerenciamento_id"] = aid
            session["finance_academia_id"] = aid
    else:
        aid = session.get("academia_gerenciamento_id")
    if aid and aid in ids:
        return aid, academias
    return ids[0], academias


@bp_precadastro.route("/")
@login_required
def lista():
    """Lista pré-cadastros da academia selecionada."""
    academia_id, academias = _get_academia_filtro()
    if not academia_id:
        flash("Selecione uma academia.", "warning")
        return redirect(url_for("academia.painel_academia"))

    busca = request.args.get("busca", "").strip()
    page = int(request.args.get("page", 1))
    por_pagina = 15
    offset = (page - 1) * por_pagina

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    where = "academia_id = %s"
    params = [academia_id]
    if busca:
        where += " AND (nome LIKE %s OR email LIKE %s OR telefone LIKE %s OR cpf LIKE %s)"
        params.extend([f"%{busca}%", f"%{busca}%", f"%{busca}%", f"%{busca}%"])

    cur.execute(f"SELECT COUNT(*) AS total FROM pre_cadastro WHERE {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(f"""
        SELECT id, nome, email, telefone, data_nascimento, sexo, foto, created_at, aula_experimental,
               COALESCE(origem,
                   CASE
                     WHEN matricula_status IS NOT NULL OR matricula_payment_id IS NOT NULL OR matricula_valor IS NOT NULL THEN 'matricula'
                     WHEN aula_experimental = 1 THEN 'aula_experimental'
                     ELSE 'precadastro'
                   END) AS origem,
               matricula_status,
               (matricula_link IS NOT NULL OR matricula_qrcode IS NOT NULL) AS tem_pagamento
        FROM pre_cadastro
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, params + [por_pagina, offset])
    precadastros = cur.fetchall()

    cur.execute("SELECT id, nome, slug, valor_matricula FROM academias WHERE id = %s", (academia_id,))
    row = cur.fetchone()
    academia_nome = row.get("nome", "") if row else ""
    academia_slug = row.get("slug") if row else ""
    valor_matricula = row.get("valor_matricula") if row else None
    if not academia_slug and academia_nome:
        academia_slug = _slugify(academia_nome)
        base_slug = academia_slug
        n = 1
        while True:
            cur.execute("SELECT id FROM academias WHERE slug = %s AND id != %s", (academia_slug, academia_id))
            if cur.fetchone() is None:
                break
            academia_slug = f"{base_slug}-{n}"
            n += 1
        cur.execute("UPDATE academias SET slug = %s WHERE id = %s", (academia_slug, academia_id))
        conn.commit()
    cur.close()
    conn.close()

    total_paginas = ceil(total / por_pagina) if total > 0 else 1

    link_publico = url_for("precadastro.form_publico", academia_slug=academia_slug or academia_id, _external=True)
    link_aula_experimental = url_for("precadastro.aula_experimental_publica", academia_slug=academia_slug or academia_id, _external=True)
    link_matricula = url_for("precadastro.matricula_publica", academia_slug=academia_slug or academia_id, _external=True)
    link_landing = url_for("precadastro.landing", academia_slug=academia_slug or academia_id, _external=True)

    return render_template(
        "precadastro/lista.html",
        precadastros=precadastros,
        busca=busca,
        pagina_atual=page,
        total_paginas=total_paginas,
        academias=academias,
        academia_id=academia_id,
        academia_nome=academia_nome,
        link_publico=link_publico,
        link_aula_experimental=link_aula_experimental,
        link_matricula=link_matricula,
        link_landing=link_landing,
        valor_matricula=valor_matricula,
    )


@bp_precadastro.route("/valor-matricula", methods=["POST"])
@login_required
def salvar_valor_matricula():
    """Define o valor da matrícula da academia (usado no link de matrícula)."""
    academia_id, _ = _get_academia_filtro()
    if not academia_id:
        flash("Selecione uma academia.", "warning")
        return redirect(url_for("precadastro.lista"))
    raw = (request.form.get("valor_matricula") or "").strip().replace(".", "").replace(",", ".") \
        if ("," in (request.form.get("valor_matricula") or "")) else (request.form.get("valor_matricula") or "").strip()
    try:
        valor = float(raw) if raw else None
        if valor is not None and valor < 0:
            valor = None
    except (TypeError, ValueError):
        valor = None
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE academias SET valor_matricula = %s WHERE id = %s", (valor, academia_id))
        conn.commit()
        flash("Valor da matrícula salvo.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao salvar valor_matricula: {e}")
        flash("Erro ao salvar o valor.", "danger")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("precadastro.lista", academia_id=academia_id))


# =====================================================================
# 🎟️  CUPONS DE DESCONTO DE MATRÍCULA
# =====================================================================
def _aplicar_cupom(cur, academia_id, codigo, valor_base):
    """Valida o cupom e calcula o desconto sobre `valor_base`.
    Retorna (cupom|None, desconto, valor_final, mensagem). cur é um cursor dict."""
    codigo = (codigo or "").strip().upper()
    valor_base = float(valor_base or 0)
    if not codigo:
        return None, 0.0, valor_base, ""
    cur.execute(
        "SELECT * FROM cupons_matricula WHERE id_academia=%s AND UPPER(codigo)=%s LIMIT 1",
        (academia_id, codigo),
    )
    c = cur.fetchone()
    if not c or not c.get("ativo"):
        return None, 0.0, valor_base, "Cupom inválido."
    hoje = date.today()
    vi, vf = c.get("validade_inicio"), c.get("validade_fim")
    if vi and hoje < vi:
        return None, 0.0, valor_base, "Cupom ainda não está válido."
    if vf and hoje > vf:
        return None, 0.0, valor_base, "Cupom expirado."
    if (c.get("uso") or "todos") == "unico" and (c.get("usos") or 0) >= 1:
        return None, 0.0, valor_base, "Cupom já utilizado."
    if (c.get("tipo") or "percentual") == "percentual":
        desc = round(valor_base * float(c.get("valor") or 0) / 100.0, 2)
    else:
        desc = round(float(c.get("valor") or 0), 2)
    desc = min(max(desc, 0.0), valor_base)
    return c, desc, round(valor_base - desc, 2), ""


@bp_precadastro.route("/cupons", methods=["GET", "POST"])
@login_required
def cupons():
    """Gerencia os cupons de desconto de matrícula da academia."""
    academia_id, academias = _get_academia_filtro()
    if not academia_id:
        flash("Selecione uma academia.", "warning")
        return redirect(url_for("precadastro.lista"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    if request.method == "POST":
        codigo = (request.form.get("codigo") or "").strip().upper()
        tipo = (request.form.get("tipo") or "percentual").strip().lower()
        if tipo not in ("percentual", "valor"):
            tipo = "percentual"
        uso = (request.form.get("uso") or "todos").strip().lower()
        if uso not in ("todos", "unico"):
            uso = "todos"
        _vr = (request.form.get("valor") or "").strip().replace(",", ".")
        try:
            valor = float(_vr) if _vr else 0.0
        except ValueError:
            valor = 0.0
        validade_inicio = request.form.get("validade_inicio") or None
        validade_fim = request.form.get("validade_fim") or None
        mostrar_form = 1 if request.form.get("mostrar_form") == "1" else 0
        if not codigo or valor <= 0:
            flash("Informe um código e um valor de desconto válido.", "danger")
        else:
            try:
                cur.execute(
                    """INSERT INTO cupons_matricula
                       (id_academia, codigo, tipo, valor, uso, validade_inicio, validade_fim, mostrar_form, ativo)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                    (academia_id, codigo, tipo, valor, uso, validade_inicio, validade_fim, mostrar_form),
                )
                conn.commit()
                flash(f"Cupom {codigo} criado.", "success")
            except Exception as e:
                conn.rollback()
                if "Duplicate" in str(e):
                    flash("Já existe um cupom com esse código nesta academia.", "danger")
                else:
                    flash("Erro ao criar o cupom.", "danger")
                    current_app.logger.error(f"Erro cupom: {e}")
    cur.execute(
        "SELECT * FROM cupons_matricula WHERE id_academia=%s ORDER BY ativo DESC, criado_em DESC",
        (academia_id,),
    )
    lista_cupons = cur.fetchall()
    cur.close()
    conn.close()
    return render_template(
        "precadastro/cupons.html",
        cupons=lista_cupons, academias=academias, academia_id=academia_id,
    )


@bp_precadastro.route("/cupons/<int:cupom_id>/toggle", methods=["POST"])
@login_required
def cupom_toggle(cupom_id):
    academia_id, _ = _get_academia_filtro()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE cupons_matricula SET ativo = 1 - ativo WHERE id=%s AND id_academia=%s", (cupom_id, academia_id))
    conn.commit(); cur.close(); conn.close()
    return redirect(url_for("precadastro.cupons", academia_id=academia_id))


@bp_precadastro.route("/cupons/<int:cupom_id>/excluir", methods=["POST"])
@login_required
def cupom_excluir(cupom_id):
    academia_id, _ = _get_academia_filtro()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM cupons_matricula WHERE id=%s AND id_academia=%s", (cupom_id, academia_id))
    conn.commit(); cur.close(); conn.close()
    flash("Cupom excluído.", "success")
    return redirect(url_for("precadastro.cupons", academia_id=academia_id))


@bp_precadastro.route("/matricula/<academia_slug>/validar-cupom", methods=["POST"])
@csrf.exempt
def validar_cupom_publico(academia_slug):
    """Valida um cupom (público, AJAX) e devolve o desconto/valor final em JSON."""
    ac = _resolver_academia_por_slug(academia_slug)
    if not ac:
        return jsonify({"valido": False, "mensagem": "Academia não encontrada."})
    codigo = (request.form.get("codigo") or request.json.get("codigo") if request.is_json else request.form.get("codigo")) or ""
    valor_base = ac.get("valor_matricula") or 0
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        c, desc, final, msg = _aplicar_cupom(cur, ac["id"], codigo, valor_base)
    finally:
        cur.close(); conn.close()
    if not c:
        return jsonify({"valido": False, "mensagem": msg or "Cupom inválido."})
    return jsonify({
        "valido": True, "desconto": desc, "valor_final": final,
        "valor_original": float(valor_base or 0),
        "mensagem": f"Cupom aplicado: desconto de R$ {desc:.2f}.",
    })


@bp_precadastro.route("/form/<academia_slug>", methods=["GET", "POST"])
@csrf.exempt
def form_publico(academia_slug):
    """Formulário público de pré-cadastro — sem login. URL usa nome da academia."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome, slug FROM academias WHERE slug = %s", (academia_slug,))
    ac = cur.fetchone()
    if not ac and academia_slug.isdigit():
        cur.execute("SELECT id, nome, slug FROM academias WHERE id = %s", (int(academia_slug),))
        ac = cur.fetchone()
    cur.close()
    conn.close()
    if not ac:
        return "<h1>Academia não encontrada</h1>", 404

    academia_id = ac["id"]
    academia_nome = ac.get("nome", "")
    academia_slug = ac.get("slug") or ""
    if not academia_slug:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        base_slug = _slugify(academia_nome) or "academia"
        academia_slug = base_slug
        n = 1
        while True:
            cur.execute("SELECT id FROM academias WHERE slug = %s AND id != %s", (academia_slug, academia_id))
            if cur.fetchone() is None:
                break
            academia_slug = f"{base_slug}-{n}"
            n += 1
        cur.execute("UPDATE academias SET slug = %s WHERE id = %s", (academia_slug, academia_id))
        conn.commit()
        cur.close()
        conn.close()

    conn_grad = get_db_connection()
    cur_grad = conn_grad.cursor(dictionary=True)
    graduacoes = []
    try:
        cur_grad.execute("SHOW COLUMNS FROM graduacao LIKE 'ativo'")
        tem_coluna_ativo = cur_grad.fetchone() is not None
        if tem_coluna_ativo:
            cur_grad.execute(
                "SELECT id, faixa, graduacao, modalidade_id FROM graduacao WHERE ativo = 1 ORDER BY faixa, graduacao"
            )
        else:
            cur_grad.execute(
                "SELECT id, faixa, graduacao, modalidade_id FROM graduacao ORDER BY faixa, graduacao"
            )
        graduacoes = cur_grad.fetchall() or []
    except Exception as e:
        current_app.logger.warning("Pré-cadastro: não foi possível listar graduações: %s", e)
    cur_grad.close()
    conn_grad.close()

    def _render_form(form_data, sucesso=False):
        return render_template(
            "precadastro/form_publico.html",
            academia_id=academia_id,
            academia_nome=academia_nome,
            academia_slug=academia_slug,
            form=form_data,
            sucesso=sucesso,
            graduacoes=graduacoes,
        )

    if request.method == "POST":
        form = request.form
        nome = (form.get("nome") or "").strip()
        if not nome:
            flash("Nome é obrigatório.", "danger")
            return _render_form(form, sucesso=False)
        graduacao_id_raw = (form.get("graduacao_id") or "").strip()
        graduacao_id = int(graduacao_id_raw) if graduacao_id_raw.isdigit() else None
        email = (form.get("email") or "").strip() or None
        if not email:
            flash("E-mail é obrigatório (será usado para recuperação de senha).", "danger")
            return _render_form(form, sucesso=False)
        telefone = (form.get("telefone") or "").strip() or None
        # Telefone é obrigatório: é por ele que as credenciais de acesso chegam
        # ao responsável por WhatsApp quando a promoção acontece.
        if not telefone or len(re.sub(r"\D", "", telefone)) not in (10, 11):
            flash("Telefone é obrigatório — informe DDD + número.", "danger")
            return _render_form(form, sucesso=False)
        data_nascimento = form.get("data_nascimento") or None
        sexo = (form.get("sexo") or "").strip() or None
        cpf = (form.get("cpf") or "").strip() or None
        observacoes = (form.get("observacoes") or "").strip() or None
        acesso_sistema = (form.get("acesso_sistema") or "aluno").strip()
        responsavel_eh_proprio = 1 if form.get("responsavel_eh_proprio") == "1" else 0
        email_acesso = (form.get("email_acesso") or "").strip() or None

        # E-mail pode repetir entre cadastros (regra do negócio: usado apenas para recuperação).
        # A unicidade é apenas no CPF do aluno (que vira o login). O CPF do responsável
        # financeiro pode aparecer em vários cadastros (1 responsável → N alunos).

        resp_nome = (form.get("responsavel_financeiro_nome") or "").strip() or None
        resp_cpf = (form.get("responsavel_financeiro_cpf") or "").strip() or None
        if responsavel_eh_proprio:
            resp_nome = nome
            resp_cpf = cpf

        # Validação: pelo menos um CPF (do aluno OU do responsável financeiro) é obrigatório
        from blueprints.auth.routes import _so_digitos, _valida_cpf
        cpf_aluno_digits = _so_digitos(cpf or "")
        cpf_resp_digits = _so_digitos(resp_cpf or "")
        if not cpf_aluno_digits and not cpf_resp_digits:
            flash(
                "Informe o CPF do aluno OU o CPF do responsável financeiro. "
                "É necessário ao menos um deles para gerar o login do sistema.",
                "danger",
            )
            return _render_form(form, sucesso=False)
        if cpf_aluno_digits and not _valida_cpf(cpf_aluno_digits):
            flash("CPF do aluno inválido. Verifique e tente novamente.", "danger")
            return _render_form(form, sucesso=False)
        if cpf_resp_digits and not _valida_cpf(cpf_resp_digits):
            flash("CPF do responsável financeiro inválido. Verifique e tente novamente.", "danger")
            return _render_form(form, sucesso=False)

        # Unicidade APENAS do CPF do aluno (será o login). O CPF do responsável financeiro
        # pode repetir entre cadastros (1 responsável → vários alunos).
        if cpf_aluno_digits:
            conn_check = get_db_connection()
            cur_check = conn_check.cursor(dictionary=True)
            try:
                cur_check.execute(
                    "SELECT id FROM pre_cadastro "
                    "WHERE REGEXP_REPLACE(COALESCE(cpf,''), '[^0-9]', '') = %s",
                    (cpf_aluno_digits,),
                )
                if cur_check.fetchone():
                    flash(
                        "Já existe um pré-cadastro com este CPF de aluno. "
                        "O CPF é o login do sistema e não pode se repetir.",
                        "danger",
                    )
                    return _render_form(form, sucesso=False)
                cur_check.execute("SELECT id FROM usuarios WHERE cpf = %s", (cpf_aluno_digits,))
                if cur_check.fetchone():
                    flash(
                        "Este CPF já está em uso por um usuário do sistema. "
                        "Não é possível criar outro cadastro com o mesmo CPF.",
                        "danger",
                    )
                    return _render_form(form, sucesso=False)
            finally:
                cur_check.close()
                conn_check.close()

        foto_filename = None
        foto_dataurl = (form.get("foto") or "").strip()
        foto_file = request.files.get("foto_arquivo")
        if foto_dataurl.startswith("data:"):
            foto_filename = _salvar_foto_precad_base64(foto_dataurl, "precad")
        elif foto_file and foto_file.filename:
            foto_filename = _salvar_foto_precad_file(foto_file, "precad")

        if not foto_filename:
            flash("A foto do aluno é obrigatória. Use a câmera ou envie uma imagem.", "danger")
            return _render_form(form, sucesso=False)

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SHOW COLUMNS FROM pre_cadastro LIKE 'acesso_sistema'")
            tem_acesso = cur.fetchone() is not None
            cur.execute("SHOW COLUMNS FROM pre_cadastro LIKE 'graduacao_id'")
            tem_graduacao = cur.fetchone() is not None
            cur.close()
        except Exception:
            tem_acesso = False
            tem_graduacao = False

        cur = conn.cursor()
        try:
            aula_experimental = 1 if form.get("aula_experimental") in ("1", "on", "true", "True") else 0
            colunas = [
                "academia_id", "nome", "email", "telefone", "data_nascimento", "sexo", "cpf",
                "observacoes", "foto", "responsavel_financeiro_nome", "responsavel_financeiro_cpf",
                "aula_experimental", "origem",
            ]
            valores = [
                academia_id, nome, email, telefone, data_nascimento, sexo, cpf,
                observacoes, foto_filename, resp_nome, resp_cpf,
                aula_experimental, ("aula_experimental" if aula_experimental else "precadastro"),
            ]
            if tem_graduacao:
                colunas.append("graduacao_id")
                valores.append(graduacao_id)
            if tem_acesso:
                colunas.extend(["acesso_sistema", "responsavel_eh_proprio", "email_acesso"])
                valores.extend([acesso_sistema, responsavel_eh_proprio, email_acesso])
            placeholders = ", ".join(["%s"] * len(colunas))
            cur.execute(
                f"INSERT INTO pre_cadastro ({', '.join(colunas)}) VALUES ({placeholders})",
                tuple(valores),
            )
            conn.commit()
            cur.close()
            conn.close()
            return _render_form({}, sucesso=True)
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            msg = str(e)
            if "Duplicate entry" in msg and (
                "responsavel_financeiro" in msg.lower() or "financeiro_cpf" in msg.lower()
            ):
                flash(
                    "O banco ainda impede repetir o CPF do responsável financeiro. "
                    "Execute no servidor: .venv/bin/python migrations/executar_drop_unique_responsavel_financeiro_cpf.py",
                    "danger",
                )
            else:
                flash(f"Erro ao salvar: {e}", "danger")

    return _render_form(request.form, sucesso=False)


def _resolver_academia_por_slug(academia_slug):
    """Retorna (id, nome, slug) da academia pelo slug (ou id). Gera slug se faltar."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome, slug, valor_matricula FROM academias WHERE slug = %s", (academia_slug,))
    ac = cur.fetchone()
    if not ac and str(academia_slug).isdigit():
        cur.execute("SELECT id, nome, slug, valor_matricula FROM academias WHERE id = %s", (int(academia_slug),))
        ac = cur.fetchone()
    if ac and not ac.get("slug"):
        base = _slugify(ac.get("nome") or "academia") or "academia"
        slug = base
        n = 1
        while True:
            cur.execute("SELECT id FROM academias WHERE slug = %s AND id != %s", (slug, ac["id"]))
            if cur.fetchone() is None:
                break
            slug = f"{base}-{n}"; n += 1
        cur.execute("UPDATE academias SET slug = %s WHERE id = %s", (slug, ac["id"]))
        conn.commit()
        ac["slug"] = slug
    cur.close()
    conn.close()
    return ac


@bp_precadastro.route("/inicio/<academia_slug>")
def landing(academia_slug):
    """Landing page pública da academia: modalidades, horários, localização e
    CTAs para matrícula e aula experimental. Uma página por academia."""
    ac = _resolver_academia_por_slug(academia_slug)
    if not ac:
        return "<h1>Academia não encontrada</h1>", 404
    academia_id = ac["id"]
    slug = ac.get("slug") or str(academia_id)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT nome, cidade, uf, email, telefone, cep, rua, numero, complemento, bairro
           FROM academias WHERE id = %s""",
        (academia_id,),
    )
    info = cur.fetchone() or {}

    # Turmas (horários de treino)
    cur.execute(
        """SELECT Nome AS nome, DiasHorario, IdadeMin, IdadeMax, Professor,
                  dias_semana, hora_inicio, hora_fim
           FROM turmas WHERE id_academia = %s
           ORDER BY hora_inicio IS NULL, hora_inicio, Nome""",
        (academia_id,),
    )
    turmas = cur.fetchall()
    for t in turmas:
        # Horário legível: usa DiasHorario, senão monta de dias_semana + horas
        horario = (t.get("DiasHorario") or "").strip()
        if not horario:
            partes = []
            if t.get("dias_semana"):
                partes.append(str(t["dias_semana"]))
            hi, hf = t.get("hora_inicio"), t.get("hora_fim")
            if hi:
                partes.append(f"{str(hi)[:5]}" + (f"–{str(hf)[:5]}" if hf else ""))
            horario = " · ".join(partes)
        t["horario_txt"] = horario
        faixa = []
        if t.get("IdadeMin"):
            faixa.append(f"{t['IdadeMin']}")
        if t.get("IdadeMax"):
            faixa.append(f"{t['IdadeMax']}")
        t["idade_txt"] = (" a ".join(faixa) + " anos") if faixa else ""

    # Modalidades ofertadas
    cur.execute(
        """SELECT m.nome FROM modalidade m
           INNER JOIN academia_modalidades am ON am.modalidade_id = m.id
           WHERE am.academia_id = %s AND m.ativo = 1 ORDER BY m.nome""",
        (academia_id,),
    )
    modalidades = [r["nome"] for r in cur.fetchall()]
    cur.close()
    conn.close()

    logo_url = None
    try:
        from utils.contexto_logo import buscar_logo_url
        logo_url = buscar_logo_url("academia", academia_id)
    except Exception:
        logo_url = None

    # Endereço para mapa / exibição
    endereco_partes = [p for p in [info.get("rua"), info.get("numero"), info.get("bairro"),
                                   info.get("cidade"), info.get("uf")] if p]
    endereco_txt = ", ".join(str(p) for p in endereco_partes)
    mapa_query = endereco_txt or f"{info.get('cidade','')} {info.get('uf','')}".strip()

    return render_template(
        "precadastro/landing.html",
        academia_nome=info.get("nome") or ac.get("nome"),
        info=info, turmas=turmas, modalidades=modalidades, logo_url=logo_url,
        endereco_txt=endereco_txt, mapa_query=mapa_query,
        link_matricula=url_for("precadastro.matricula_publica", academia_slug=slug, _external=True),
        link_aula=url_for("precadastro.aula_experimental_publica", academia_slug=slug, _external=True),
        link_precadastro=url_for("precadastro.form_publico", academia_slug=slug, _external=True),
    )


@bp_precadastro.route("/matricula/<academia_slug>", methods=["GET", "POST"])
@csrf.exempt
def matricula_publica(academia_slug):
    """Formulário público de MATRÍCULA — sem login. Ao enviar, gera a cobrança da
    matrícula (link/QR pelo gateway configurado) ou, sem gateway, mostra o valor para
    pagamento avulso."""
    ac = _resolver_academia_por_slug(academia_slug)
    if not ac:
        return "<h1>Academia não encontrada</h1>", 404
    academia_id = ac["id"]
    academia_nome = ac.get("nome", "")
    academia_slug = ac.get("slug") or str(academia_id)
    valor_matricula = ac.get("valor_matricula")

    # Cupons visíveis para o aluno (ativos, dentro da vigência, marcados para mostrar)
    cupons_visiveis = []
    try:
        _cn = get_db_connection(); _ccur = _cn.cursor(dictionary=True)
        _ccur.execute(
            """SELECT codigo, tipo, valor, validade_fim, uso, usos FROM cupons_matricula
               WHERE id_academia=%s AND ativo=1 AND mostrar_form=1
                 AND (validade_inicio IS NULL OR validade_inicio <= CURDATE())
                 AND (validade_fim IS NULL OR validade_fim >= CURDATE())
                 AND NOT (uso='unico' AND usos >= 1)
               ORDER BY criado_em DESC""",
            (academia_id,),
        )
        cupons_visiveis = _ccur.fetchall()
        _ccur.close(); _cn.close()
    except Exception:
        cupons_visiveis = []

    _logo_mat = None
    try:
        from utils.contexto_logo import buscar_logo_url
        _logo_mat = buscar_logo_url("academia", academia_id)
    except Exception:
        _logo_mat = None

    def _render(form_data=None, resultado=None):
        return render_template(
            "precadastro/matricula_publica.html",
            academia_id=academia_id, academia_nome=academia_nome, academia_slug=academia_slug,
            valor_matricula=valor_matricula, form=form_data or {}, resultado=resultado,
            cupons_visiveis=cupons_visiveis, logo_url=_logo_mat,
        )

    if request.method != "POST":
        return _render()

    from blueprints.auth.routes import _so_digitos, _valida_cpf
    form = request.form
    nome = (form.get("nome") or "").strip()
    data_nascimento = form.get("data_nascimento") or None
    sexo = (form.get("sexo") or "").strip() or None
    email = (form.get("email") or "").strip() or None
    telefone = (form.get("telefone") or "").strip() or None
    cep = (form.get("cep") or "").strip() or None
    numero = (form.get("numero") or "").strip() or None
    rua = (form.get("rua") or "").strip() or None
    bairro = (form.get("bairro") or "").strip() or None
    cidade = (form.get("cidade") or "").strip() or None
    proprio = 1 if form.get("responsavel_eh_proprio") == "1" else 0
    resp_nome = (form.get("responsavel_financeiro_nome") or "").strip() or None
    resp_cpf_raw = (form.get("responsavel_financeiro_cpf") or "").strip()
    resp_cpf_digits = _so_digitos(resp_cpf_raw)
    if proprio:
        resp_nome = nome
    cpf_aluno = resp_cpf_raw if proprio else None  # se próprio aluno, o CPF informado é o do aluno

    # Validações
    if not nome:
        flash("Informe o nome completo do aluno.", "danger")
        return _render(form)
    if not resp_cpf_digits or not _valida_cpf(resp_cpf_digits):
        flash("Informe um CPF válido do responsável financeiro (ou marque 'próprio aluno').", "danger")
        return _render(form)
    if not resp_nome:
        flash("Informe o nome do responsável financeiro (ou marque 'próprio aluno').", "danger")
        return _render(form)

    # Cupom de desconto (opcional)
    cupom_codigo = (form.get("cupom") or "").strip().upper() or None
    valor_base = float(valor_matricula or 0)
    valor_final = valor_base
    desconto = 0.0
    cupom_obj = None
    if cupom_codigo:
        _cn = get_db_connection(); _ccur = _cn.cursor(dictionary=True)
        try:
            cupom_obj, desconto, valor_final, _msg = _aplicar_cupom(_ccur, academia_id, cupom_codigo, valor_base)
        finally:
            _ccur.close(); _cn.close()
        if not cupom_obj:
            flash(_msg or "Cupom inválido.", "danger")
            return _render(form)

    # Insere o pré-cadastro
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO pre_cadastro
               (academia_id, nome, email, telefone, data_nascimento, sexo, cpf,
                responsavel_financeiro_nome, responsavel_financeiro_cpf,
                matricula_valor, matricula_valor_original, matricula_desconto, matricula_cupom,
                cep, numero, rua, bairro, cidade, origem)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'matricula')""",
            (academia_id, nome, email, telefone, data_nascimento, sexo, cpf_aluno,
             resp_nome, resp_cpf_raw,
             valor_final, valor_base, desconto, (cupom_codigo if cupom_obj else None),
             cep, numero, rua, bairro, cidade),
        )
        precad_id = cur.lastrowid
        # Consome o cupom (registra uso — para uso único, bloqueia reutilização)
        if cupom_obj:
            cur.execute("UPDATE cupons_matricula SET usos = usos + 1 WHERE id=%s", (cupom_obj["id"],))
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close(); conn.close()
        current_app.logger.error(f"Matrícula: erro ao salvar pré-cadastro: {e}", exc_info=True)
        flash("Erro ao salvar os dados. Tente novamente.", "danger")
        return _render(form)
    cur.close(); conn.close()

    # Gera a cobrança da matrícula (gateway) ou marca avulso
    resultado = {"avulso": True, "valor": valor_final, "valor_original": valor_base,
                 "desconto": desconto, "cupom": cupom_codigo if cupom_obj else None,
                 "academia_nome": academia_nome}
    try:
        from blueprints.financeiro.routes import gerar_cobranca_matricula
        _endereco = {"cep": cep, "street": rua, "neighborhood": bairro, "number": numero}
        r = gerar_cobranca_matricula(
            academia_id, nome=resp_nome or nome, cpf=resp_cpf_digits, email=email,
            telefone=telefone, valor=valor_final, precad_id=precad_id,
            descricao=f"Matrícula - {nome}", endereco=_endereco,
        )
        if r:
            qr = r.get("pix_qrcode")
            # InfinitePay devolve link sem QR PIX → gera QR do link
            if not qr and r.get("boleto_url"):
                try:
                    from utils.qrcode_util import gerar_qr_base64
                    qr = gerar_qr_base64(r.get("boleto_url"))
                except Exception:
                    qr = None
            conn = get_db_connection(); cur = conn.cursor()
            cur.execute(
                """UPDATE pre_cadastro SET matricula_gateway=%s, matricula_payment_id=%s,
                       matricula_link=%s, matricula_qrcode=%s, matricula_copia_cola=%s, matricula_status='pendente'
                   WHERE id=%s""",
                (r.get("gateway"), r.get("payment_id"), r.get("boleto_url"), qr, r.get("pix_copia_cola"), precad_id),
            )
            conn.commit(); cur.close(); conn.close()
            resultado = {
                "avulso": False, "valor": valor_final, "valor_original": valor_base,
                "desconto": desconto, "cupom": cupom_codigo if cupom_obj else None,
                "academia_nome": academia_nome,
                "gateway": r.get("gateway"), "link": r.get("boleto_url"),
                "qrcode": qr, "copia_cola": r.get("pix_copia_cola"), "tipo": r.get("tipo"),
            }
            # Envia o link de pagamento por e-mail ao responsável financeiro
            if email and r.get("boleto_url"):
                try:
                    from utils.email_utils import enviar_email_link_pagamento
                    enviar_email_link_pagamento(email, resp_nome or nome, academia_nome,
                                                r.get("boleto_url"), valor_matricula, r.get("pix_copia_cola"))
                except Exception as _e:
                    current_app.logger.error(f"Matrícula: envio de e-mail falhou (precad {precad_id}): {_e}")
    except Exception as e:
        current_app.logger.error(f"Matrícula: cobrança online falhou (precad {precad_id}): {e}")
        # cai no avulso

    # Confirmação de matrícula no WhatsApp (responsável financeiro)
    try:
        from utils.whatsapp_lembretes import enviar_evento
        enviar_evento(academia_id, "matricula", telefone, {
            "nome": (resp_nome or nome or "").split(" ")[0],
            "aluno": nome,
            "valor": (f"R$ {float(valor_final):.2f}".replace(".", ",")) if valor_final else "",
            "link": resultado.get("link") or "",
            "academia": academia_nome,
        })
    except Exception:
        pass

    return _render(form, resultado=resultado)


@bp_precadastro.route("/<int:precad_id>/pagamento")
@login_required
def matricula_pagamento(precad_id):
    """Mostra o link/QR de pagamento da matrícula de um pré-cadastro (para reenviar)."""
    academia_id, _ = _get_academia_filtro()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT p.*, ac.nome AS academia_nome
           FROM pre_cadastro p LEFT JOIN academias ac ON ac.id = p.academia_id
           WHERE p.id = %s""",
        (precad_id,),
    )
    p = cur.fetchone()
    cur.close(); conn.close()
    if not p:
        flash("Pré-cadastro não encontrado.", "danger")
        return redirect(url_for("precadastro.lista"))
    if academia_id and p["academia_id"] != academia_id and not current_user.has_role("admin"):
        flash("Sem permissão.", "danger")
        return redirect(url_for("precadastro.lista"))
    if not p.get("matricula_link") and not p.get("matricula_qrcode"):
        flash("Esta matrícula não tem cobrança online gerada.", "warning")
        return redirect(url_for("precadastro.lista", academia_id=p["academia_id"]))
    back_url = request.referrer or url_for("precadastro.lista", academia_id=p["academia_id"])
    return render_template("precadastro/matricula_pagamento.html", p=p, back_url=back_url)


@bp_precadastro.route("/<int:precad_id>/reenviar-email", methods=["POST"])
@login_required
def matricula_reenviar_email(precad_id):
    """Reenvia o link de pagamento da matrícula ao e-mail do responsável financeiro."""
    academia_id, _ = _get_academia_filtro()
    destino = request.referrer or url_for("precadastro.lista")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT p.*, ac.nome AS academia_nome
           FROM pre_cadastro p LEFT JOIN academias ac ON ac.id = p.academia_id
           WHERE p.id = %s""",
        (precad_id,),
    )
    p = cur.fetchone()
    cur.close(); conn.close()
    if not p:
        flash("Pré-cadastro não encontrado.", "danger")
        return redirect(destino)
    if academia_id and p["academia_id"] != academia_id and not current_user.has_role("admin"):
        flash("Sem permissão.", "danger")
        return redirect(destino)
    if not p.get("email"):
        flash("Este cadastro não tem e-mail para envio.", "warning")
        return redirect(destino)
    if not p.get("matricula_link"):
        flash("Esta matrícula não tem link de pagamento gerado.", "warning")
        return redirect(destino)
    from utils.email_utils import enviar_email_link_pagamento
    ok = enviar_email_link_pagamento(
        p["email"], p.get("responsavel_financeiro_nome") or p.get("nome"),
        p.get("academia_nome") or "", p.get("matricula_link"),
        p.get("matricula_valor"), p.get("matricula_copia_cola"),
    )
    flash("Link reenviado por e-mail para " + p["email"] + "." if ok else
          "Não foi possível enviar o e-mail (verifique a configuração de e-mail).",
          "success" if ok else "danger")
    return redirect(destino)


@bp_precadastro.route("/aula-experimental/<academia_slug>", methods=["GET", "POST"])
@csrf.exempt
def aula_experimental_publica(academia_slug):
    """Formulário público para a pessoa solicitar uma aula experimental — sem login.
    Cria um visitante (sem usuário) e registra a aula experimental pendente de aprovação."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT id, nome, slug FROM academias WHERE slug = %s", (academia_slug,))
    ac = cur.fetchone()
    if not ac and academia_slug.isdigit():
        cur.execute("SELECT id, nome, slug FROM academias WHERE id = %s", (int(academia_slug),))
        ac = cur.fetchone()
    if not ac:
        cur.close()
        conn.close()
        return "<h1>Academia não encontrada</h1>", 404

    academia_id = ac["id"]
    academia_nome = ac.get("nome", "")
    academia_slug = ac.get("slug") or str(academia_id)

    # Turmas disponíveis da academia
    cur.execute(
        """
        SELECT t.TurmaID AS turma_id, t.Nome AS turma_nome, t.DiasHorario,
               t.IdadeMin, t.IdadeMax, t.dias_semana
        FROM turmas t
        WHERE t.id_academia = %s
        ORDER BY t.Nome
        """,
        (academia_id,),
    )
    turmas = cur.fetchall()

    _logo_ae = None
    try:
        from utils.contexto_logo import buscar_logo_url
        _logo_ae = buscar_logo_url("academia", academia_id)
    except Exception:
        _logo_ae = None

    def _render(form_data=None, sucesso=False):
        cur.close()
        conn.close()
        return render_template(
            "precadastro/aula_experimental_publica.html",
            academia_nome=academia_nome,
            academia_slug=academia_slug,
            turmas=turmas,
            form=form_data or {},
            sucesso=sucesso,
            logo_url=_logo_ae,
        )

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip() or None
        telefone = (request.form.get("telefone") or "").strip() or None
        data_nascimento = (request.form.get("data_nascimento") or "").strip() or None
        turma_id = request.form.get("turma_id", type=int)
        data_aula = (request.form.get("data_aula") or "").strip()

        if not nome or not telefone or not turma_id or not data_aula:
            flash("Preencha nome, telefone, turma e a data desejada.", "danger")
            return _render(request.form)

        # Foto é obrigatória
        foto_filename = None
        foto_dataurl = (request.form.get("foto") or "").strip()
        foto_file = request.files.get("foto_arquivo")
        if foto_dataurl.startswith("data:"):
            foto_filename = _salvar_foto_visitante_base64(foto_dataurl)
        elif foto_file and foto_file.filename:
            foto_filename = _salvar_foto_visitante_file(foto_file)
        if not foto_filename:
            flash("A foto é obrigatória. Tire uma foto ou envie uma imagem.", "danger")
            return _render(request.form)

        try:
            data_aula_obj = datetime.strptime(data_aula, "%Y-%m-%d").date()
            if data_aula_obj < date.today():
                flash("Não é possível solicitar aula para uma data passada.", "danger")
                return _render(request.form)
        except Exception:
            flash("Data inválida.", "danger")
            return _render(request.form)

        # Turma precisa ser da academia
        turma_sel = next((t for t in turmas if t["turma_id"] == turma_id), None)
        if not turma_sel:
            flash("Turma inválida.", "danger")
            return _render(request.form)

        # A data precisa cair num dia de treino da turma (dias_semana: 0=Dom..6=Sáb)
        dias_raw = str(turma_sel.get("dias_semana") or "")
        dias_turma = {int(x) for x in dias_raw.replace(";", ",").split(",") if x.strip().isdigit()}
        if dias_turma:
            nomes = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]
            if (data_aula_obj.isoweekday() % 7) not in dias_turma:
                permitidos = ", ".join(nomes[d] for d in sorted(dias_turma))
                flash(f"A turma '{turma_sel['turma_nome']}' treina apenas: {permitidos}. Escolha uma dessas datas.", "danger")
                return _render(request.form)

        try:
            cur.execute(
                "SELECT aulas_experimentais_permitidas FROM academias WHERE id = %s",
                (academia_id,),
            )
            acad_cfg = cur.fetchone() or {}
            limite_aulas = acad_cfg.get("aulas_experimentais_permitidas")

            # Cria o visitante (sem usuário — é um lead público)
            cur.execute(
                """
                INSERT INTO visitantes (nome, email, telefone, data_nascimento, foto, usuario_id,
                                        id_academia, aulas_experimentais_permitidas, ativo)
                VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, 1)
                """,
                (nome, email, telefone, data_nascimento or None, foto_filename, academia_id, limite_aulas),
            )
            visitante_id = cur.lastrowid

            # Registra a aula experimental (pendente de aprovação)
            cur.execute(
                """
                INSERT INTO aulas_experimentais (visitante_id, turma_id, data_aula, presente, aprovado, observacoes, registrado_por)
                VALUES (%s, %s, %s, 0, 0, %s, NULL)
                """,
                (visitante_id, turma_id, data_aula, "Solicitado via link público de aula experimental"),
            )

            cur.execute(
                "INSERT IGNORE INTO visitante_turmas (visitante_id, turma_id, data_inscricao) VALUES (%s, %s, %s)",
                (visitante_id, turma_id, date.today()),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            current_app.logger.error(f"Erro na solicitação pública de aula experimental: {e}", exc_info=True)
            flash("Ocorreu um erro ao registrar sua solicitação. Tente novamente.", "danger")
            return _render(request.form)

        return _render(sucesso=True)

    return _render(request.form)


@bp_precadastro.route("/verificar-email", methods=["POST"])
def verificar_email():
    """Verifica se um email já existe (AJAX)."""
    from flask import jsonify
    data = request.get_json()
    email = (data.get("email") or "").strip().lower() if data else ""
    
    if not email:
        return jsonify({"existe": False})
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    # Verificar em pre_cadastro
    cur.execute("SELECT id FROM pre_cadastro WHERE LOWER(email) = %s", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"existe": True})
    
    # Verificar em usuarios
    cur.execute("SELECT id FROM usuarios WHERE LOWER(email) = %s", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"existe": True})
    
    cur.close()
    conn.close()
    return jsonify({"existe": False})


@bp_precadastro.route("/editar/<int:precadastro_id>", methods=["GET", "POST"])
@login_required
def editar(precadastro_id):
    """Edita um pré-cadastro existente."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM pre_cadastro WHERE id = %s", (precadastro_id,))
    pc = cur.fetchone()
    if not pc:
        cur.close()
        conn.close()
        flash("Pré-cadastro não encontrado.", "danger")
        return redirect(url_for("precadastro.lista"))

    academia_id = pc["academia_id"]
    ids = _get_academias_ids()
    if academia_id not in ids:
        cur.close()
        conn.close()
        flash("Sem permissão para editar este pré-cadastro.", "danger")
        return redirect(url_for("precadastro.lista"))

    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    ac = cur.fetchone()
    academia_nome = ac.get("nome", "") if ac else ""

    if request.method == "POST":
        form = request.form
        nome = (form.get("nome") or "").strip()
        if not nome:
            flash("Nome é obrigatório.", "danger")
            form_data = dict(form)
            form_data.update(pc)
            cur.close()
            conn.close()
            return render_template(
                "precadastro/editar.html",
                p=pc,
                academia_id=academia_id,
                academia_nome=academia_nome,
                form=form_data,
            )
        email = (form.get("email") or "").strip() or None
        telefone = (form.get("telefone") or "").strip() or None
        data_nascimento = form.get("data_nascimento") or None
        sexo = (form.get("sexo") or "").strip() or None
        cpf = (form.get("cpf") or "").strip() or None
        observacoes = (form.get("observacoes") or "").strip() or None
        acesso_sistema = (form.get("acesso_sistema") or "aluno").strip()
        responsavel_eh_proprio = 1 if form.get("responsavel_eh_proprio") == "1" else 0
        email_acesso = (form.get("email_acesso") or "").strip() or None
        resp_nome = (form.get("responsavel_financeiro_nome") or "").strip() or None
        resp_cpf = (form.get("responsavel_financeiro_cpf") or "").strip() or None
        if responsavel_eh_proprio:
            resp_nome = nome
            resp_cpf = cpf

        # Validação: pelo menos um CPF (do aluno OU do responsável financeiro) é obrigatório
        from blueprints.auth.routes import _so_digitos, _valida_cpf
        cpf_aluno_digits = _so_digitos(cpf or "")
        cpf_resp_digits = _so_digitos(resp_cpf or "")

        def _render_editar_erro(msg):
            flash(msg, "danger")
            form_data = dict(form)
            form_data.update(pc)
            cur.close()
            conn.close()
            return render_template(
                "precadastro/editar.html",
                p=pc, academia_id=academia_id, academia_nome=academia_nome,
                form=form_data,
            )

        if not cpf_aluno_digits and not cpf_resp_digits:
            return _render_editar_erro(
                "Informe o CPF do aluno OU o CPF do responsável financeiro. "
                "É necessário ao menos um deles para gerar o login do sistema."
            )
        if cpf_aluno_digits and not _valida_cpf(cpf_aluno_digits):
            return _render_editar_erro("CPF do aluno inválido. Verifique e tente novamente.")
        if cpf_resp_digits and not _valida_cpf(cpf_resp_digits):
            return _render_editar_erro("CPF do responsável financeiro inválido. Verifique e tente novamente.")

        foto_filename = pc.get("foto")
        foto_dataurl = (form.get("foto") or "").strip()
        foto_file = request.files.get("foto_arquivo")
        if foto_dataurl.startswith("data:"):
            foto_filename = _salvar_foto_precad_base64(foto_dataurl, "precad")
        elif foto_file and foto_file.filename:
            foto_filename = _salvar_foto_precad_file(foto_file, "precad")

        if not foto_filename:
            flash("A foto do aluno é obrigatória. Use a câmera ou envie uma imagem.", "danger")
            form_data = dict(form)
            form_data.update(pc)
            cur.close()
            conn.close()
            return render_template(
                "precadastro/editar.html",
                p=pc,
                academia_id=academia_id,
                academia_nome=academia_nome,
                form=form_data,
            )

        try:
            cur.execute("SHOW COLUMNS FROM pre_cadastro LIKE 'acesso_sistema'")
            tem_acesso = cur.fetchone() is not None
        except Exception:
            tem_acesso = False

        try:
            if tem_acesso:
                cur.execute(
                    """
                    UPDATE pre_cadastro SET
                        nome=%s, email=%s, telefone=%s, data_nascimento=%s, sexo=%s, cpf=%s,
                        observacoes=%s, foto=%s, responsavel_financeiro_nome=%s, responsavel_financeiro_cpf=%s,
                        acesso_sistema=%s, responsavel_eh_proprio=%s, email_acesso=%s
                    WHERE id=%s
                    """,
                    (
                        nome, email, telefone, data_nascimento, sexo, cpf,
                        observacoes, foto_filename, resp_nome, resp_cpf,
                        acesso_sistema, responsavel_eh_proprio, email_acesso,
                        precadastro_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE pre_cadastro SET
                        nome=%s, email=%s, telefone=%s, data_nascimento=%s, sexo=%s, cpf=%s,
                        observacoes=%s, foto=%s, responsavel_financeiro_nome=%s, responsavel_financeiro_cpf=%s
                    WHERE id=%s
                    """,
                    (
                        nome, email, telefone, data_nascimento, sexo, cpf,
                        observacoes, foto_filename, resp_nome, resp_cpf,
                        precadastro_id,
                    ),
                )
            conn.commit()
            cur.close()
            conn.close()
            flash("Pré-cadastro atualizado com sucesso.", "success")
            return redirect(url_for("precadastro.lista", academia_id=academia_id))
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            msg = str(e)
            if "Duplicate entry" in msg and (
                "responsavel_financeiro" in msg.lower() or "financeiro_cpf" in msg.lower()
            ):
                flash(
                    "O banco ainda impede repetir o CPF do responsável financeiro. "
                    "Execute: .venv/bin/python migrations/executar_drop_unique_responsavel_financeiro_cpf.py",
                    "danger",
                )
            else:
                flash(f"Erro ao atualizar: {e}", "danger")
            return render_template(
                "precadastro/editar.html",
                p=pc,
                academia_id=academia_id,
                academia_nome=academia_nome,
                form=dict(request.form),
            )

    cur.close()
    conn.close()
    form = {}
    for k, v in pc.items():
        if v is None:
            form[k] = ""
        elif hasattr(v, "strftime"):
            form[k] = v.strftime("%Y-%m-%d") if v else ""
        else:
            form[k] = str(v)
    form["responsavel_eh_proprio"] = "1" if pc.get("responsavel_eh_proprio") else ""
    form["acesso_sistema"] = pc.get("acesso_sistema") or "aluno"
    form["email_acesso"] = pc.get("email_acesso") or pc.get("email") or ""
    return render_template(
        "precadastro/editar.html",
        p=pc,
        academia_id=academia_id,
        academia_nome=academia_nome,
        form=form,
    )


@bp_precadastro.route("/<int:precadastro_id>/excluir", methods=["POST"])
@login_required
def excluir(precadastro_id):
    """Exclui um pré-cadastro."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, academia_id, nome FROM pre_cadastro WHERE id = %s", (precadastro_id,))
    pc = cur.fetchone()
    if not pc:
        cur.close()
        conn.close()
        flash("Pré-cadastro não encontrado.", "danger")
        return redirect(url_for("precadastro.lista"))

    academia_id = pc["academia_id"]
    ids = _get_academias_ids()
    if academia_id not in ids:
        cur.close()
        conn.close()
        flash("Sem permissão para excluir este pré-cadastro.", "danger")
        return redirect(url_for("precadastro.lista"))

    try:
        cur.execute("DELETE FROM pre_cadastro WHERE id = %s", (precadastro_id,))
        conn.commit()
        cur.close()
        conn.close()
        flash(f'Pré-cadastro de "{pc.get("nome", "")}" excluído com sucesso.', "success")
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        flash(f"Erro ao excluir: {e}", "danger")
    return redirect(url_for("precadastro.lista", academia_id=academia_id))


def _gerar_senha_aleatoria(tamanho=8):
    """
    Senha temporária legível: sem caracteres que se confundem (0/O, 1/l/I), porque
    ela é lida em e-mail ou WhatsApp e digitada à mão.
    """
    import secrets
    alfabeto = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(tamanho))


def _enviar_credenciais(cur, pc, academia_id, login, senha):
    """
    Manda as credenciais ao responsável por e-mail e, se houver telefone, também
    por WhatsApp. Retorna (destino_email, enviou_email, enviou_whatsapp).

    Best-effort: falha de envio não derruba a promoção, que já foi concluída.
    """
    from utils.email_utils import enviar_email_credenciais_acesso
    from utils import whatsapp

    destinatario = (pc.get("responsavel_nome") or pc.get("responsavel_financeiro_nome")
                    or pc.get("nome") or "").strip()
    email = (pc.get("email") or pc.get("email_acesso") or "").strip()
    telefone = (pc.get("tel_celular") or pc.get("telefone") or "").strip()

    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    linha = cur.fetchone()
    academia_nome = (linha or {}).get("nome") or "sua academia"
    link_login = url_for("auth.login", _external=True)

    enviou_email = False
    if email:
        enviou_email = enviar_email_credenciais_acesso(
            email, destinatario, pc.get("nome"), academia_nome, login, senha, link_login)

    enviou_whats = False
    digitos = re.sub(r"\D", "", telefone)
    if len(digitos) in (10, 11) and academia_id:
        try:
            if whatsapp.disponivel() and whatsapp.conectado(academia_id):
                mensagem = (
                    f"Olá, {destinatario}! O cadastro de {pc.get('nome')} foi concluído "
                    f"na {academia_nome}.\n\n"
                    f"Acesse: {link_login}\nUsuário: {login}\nSenha: {senha}\n\n"
                    "Troque a senha no primeiro acesso."
                )
                enviou_whats, _ = whatsapp.enviar(academia_id, digitos, mensagem)
        except Exception:
            enviou_whats = False

    return email, enviou_email, enviou_whats


@bp_precadastro.route("/<int:precadastro_id>/promover", methods=["GET", "POST"])
@login_required
def promover(precadastro_id):
    """Promove pré-cadastro para usuário com múltiplos perfis. GET mostra formulário, POST processa."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM pre_cadastro WHERE id = %s", (precadastro_id,))
    pc = cur.fetchone()
    if not pc:
        cur.close()
        conn.close()
        flash("Pré-cadastro não encontrado.", "danger")
        return redirect(url_for("precadastro.lista"))

    academia_id = pc["academia_id"]
    ids = _get_academias_ids()
    if academia_id not in ids:
        cur.close()
        conn.close()
        flash("Sem permissão para promover pré-cadastros desta academia.", "danger")
        return redirect(url_for("precadastro.lista"))

    cur.execute(
        """
        SELECT ac.id_associacao, ass.id_federacao
        FROM academias ac
        LEFT JOIN associacoes ass ON ass.id = ac.id_associacao
        WHERE ac.id = %s
        """,
        (academia_id,),
    )
    row = cur.fetchone()
    id_associacao = row.get("id_associacao") if row else None
    id_federacao = row.get("id_federacao") if row else None

    # Buscar roles disponíveis
    cur.execute("""
        SELECT id, nome, COALESCE(chave, LOWER(REPLACE(nome,' ','_'))) as chave 
        FROM roles 
        WHERE chave IN ('aluno', 'professor', 'gestor_academia', 'gestor_associacao', 'responsavel', 'visitante')
           OR nome IN ('Aluno', 'Professor', 'Gestor Academia', 'Gestor Associação', 'Responsável', 'Visitante')
        ORDER BY 
            CASE chave
                WHEN 'aluno' THEN 1
                WHEN 'professor' THEN 2
                WHEN 'gestor_academia' THEN 3
                WHEN 'gestor_associacao' THEN 4
                WHEN 'responsavel' THEN 5
                WHEN 'visitante' THEN 6
                ELSE 7
            END
    """)
    roles_disponiveis = cur.fetchall()

    # Buscar alunos para vínculo (aluno e responsavel)
    cur.execute(
        """SELECT id, nome, usuario_id FROM alunos WHERE id_academia = %s AND ativo = 1 AND status = 'ativo'
           ORDER BY nome""",
        (academia_id,),
    )
    todos_alunos = cur.fetchall()
    alunos_para_aluno = [a for a in todos_alunos if not a.get("usuario_id")]
    alunos_para_responsavel = todos_alunos

    if request.method == "GET":
        cur.close()
        conn.close()
        return render_template(
            "precadastro/promover.html",
            precadastro=pc,
            academia_id=academia_id,
            roles_disponiveis=roles_disponiveis,
            alunos_para_aluno=alunos_para_aluno,
            alunos_para_responsavel=alunos_para_responsavel,
        )

    # POST: Processar promoção
    roles_escolhidas = request.form.getlist("roles")
    email_usuario = (request.form.get("email_usuario") or "").strip()
    senha_usuario = (request.form.get("senha_usuario") or "").strip()
    senha_gerada = False
    tem_role_aluno = any(
        r.get("chave") == "aluno" and str(r.get("id")) in roles_escolhidas
        for r in roles_disponiveis
    )
    tem_role_responsavel = any(
        r.get("chave") == "responsavel" and str(r.get("id")) in roles_escolhidas
        for r in roles_disponiveis
    )
    aluno_ids_responsavel = [int(x) for x in request.form.getlist("aluno_ids") if str(x).strip().isdigit()]

    if not roles_escolhidas:
        cur.close()
        conn.close()
        flash("Selecione ao menos um perfil para promover.", "danger")
        return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))

    # Se precisa criar usuário, validar email e senha
    precisa_usuario = any(
        r.get("chave") in ["professor", "gestor_academia", "gestor_associacao", "responsavel", "visitante"]
        and str(r.get("id")) in roles_escolhidas
        for r in roles_disponiveis
    )
    
    # Verificar se usuário quer criar usuário mesmo quando seleciona apenas aluno
    criar_usuario_check = request.form.get("criar_usuario") == "1"
    tem_role_aluno_apenas = (
        any(r.get("chave") == "aluno" and str(r.get("id")) in roles_escolhidas for r in roles_disponiveis)
        and not precisa_usuario
    )
    
    # Se apenas aluno e checkbox marcado, também precisa criar usuário
    if tem_role_aluno_apenas and criar_usuario_check:
        precisa_usuario = True
    
    if precisa_usuario:
        if not email_usuario:
            email_usuario = pc.get("email") or pc.get("email_acesso")
        if not email_usuario:
            cur.close()
            conn.close()
            flash("E-mail é obrigatório para criar usuário. Informe um e-mail válido.", "danger")
            return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))
        # Sem senha digitada, o sistema gera uma e envia ao responsável. Assim
        # ninguém precisa inventar senha nem combiná-la por fora.
        if not senha_usuario:
            senha_usuario = _gerar_senha_aleatoria()
            senha_gerada = True

    try:
        usuario_id = None
        aluno_id = None
        origem_cpf = None  # 'aluno' | 'responsavel_financeiro' | None

        # Criar usuário se necessário
        if precisa_usuario:
            # E-mail pode repetir entre usuários (login agora é por CPF, não e-mail).

            # CPF para login:
            #   - Se a role inclui "aluno": prioriza CPF do aluno; fallback para responsável financeiro.
            #   - Se for só "responsável" (sem aluno): prioriza CPF do responsável financeiro;
            #     fallback para CPF do aluno (caso esteja preenchido como CPF do responsável).
            from blueprints.auth.routes import _so_digitos as _cpf_digits, _valida_cpf as _cpf_ok
            cpf_aluno_d = _cpf_digits(pc.get("cpf") or "")
            cpf_resp_d = _cpf_digits(pc.get("responsavel_financeiro_cpf") or "")
            cpf_login = None
            origem_cpf = None
            if tem_role_responsavel and not tem_role_aluno:
                # Usuário responsável: usa CPF do responsável financeiro
                if cpf_resp_d and _cpf_ok(cpf_resp_d):
                    cpf_login = cpf_resp_d
                    origem_cpf = "responsavel_financeiro"
                elif cpf_aluno_d and _cpf_ok(cpf_aluno_d):
                    cpf_login = cpf_aluno_d
                    origem_cpf = "aluno"
            else:
                # Demais casos: prioriza CPF do aluno
                if cpf_aluno_d and _cpf_ok(cpf_aluno_d):
                    cpf_login = cpf_aluno_d
                    origem_cpf = "aluno"
                elif cpf_resp_d and _cpf_ok(cpf_resp_d):
                    cpf_login = cpf_resp_d
                    origem_cpf = "responsavel_financeiro"

            if not cpf_login:
                cur.close()
                conn.close()
                flash(
                    "Pré-cadastro sem CPF válido (nem do aluno, nem do responsável financeiro). "
                    "Edite o pré-cadastro e informe um CPF antes de promover.",
                    "danger",
                )
                return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))

            # CPF não pode estar em uso por outro usuário
            cur.execute("SELECT id FROM usuarios WHERE cpf = %s", (cpf_login,))
            if cur.fetchone():
                cur.close()
                conn.close()
                flash(
                    "Já existe um usuário com este CPF. Verifique no cadastro se o usuário já foi criado anteriormente.",
                    "danger",
                )
                return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))

            cur.execute(
                """INSERT INTO usuarios (nome, email, cpf, senha, id_academia, id_associacao, id_federacao)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (pc.get("nome"), email_usuario, cpf_login, generate_password_hash(senha_usuario),
                 academia_id, id_associacao, id_federacao),
            )
            usuario_id = cur.lastrowid

            # Vincular roles
            for rid in roles_escolhidas:
                cur.execute("INSERT INTO roles_usuario (usuario_id, role_id) VALUES (%s, %s)", (usuario_id, rid))

            # Vincular academia
            cur.execute("INSERT INTO usuarios_academias (usuario_id, academia_id) VALUES (%s, %s)", (usuario_id, academia_id))

        # Criar/vincular aluno se role aluno está selecionada,
        # OU se for responsável (precisamos do cadastro do aluno mesmo sem login do aluno).
        aluno_criado_via_responsavel = False  # True quando o aluno foi criado só por causa do responsável
        if tem_role_aluno or tem_role_responsavel:
            aluno_id = None

            # Verificar se aluno já está cadastrado (por CPF ou nome+data_nasc)
            cpf_precad = (pc.get("cpf") or "").strip()
            cpf_digits = "".join(filter(str.isdigit, cpf_precad)) if cpf_precad else ""
            nome_precad = (pc.get("nome") or "").strip()
            data_nasc_precad = pc.get("data_nascimento")

            aluno_existente = None
            if cpf_digits and len(cpf_digits) >= 11:
                cur.execute(
                    """
                    SELECT id, nome FROM alunos
                    WHERE REPLACE(REPLACE(REPLACE(COALESCE(cpf,''), '.', ''), '-', ''), ' ', '') = %s
                    """,
                    (cpf_digits,),
                )
                aluno_existente = cur.fetchone()
            elif nome_precad:
                cur.execute(
                    """
                    SELECT id, nome FROM alunos
                    WHERE TRIM(nome) = %s AND (data_nascimento = %s OR (%s IS NULL AND data_nascimento IS NULL))
                    """,
                    (nome_precad, data_nasc_precad, data_nasc_precad),
                )
                aluno_existente = cur.fetchone()

            if aluno_existente:
                # Aluno já existe - vincular usuário ao aluno existente apenas se for "aluno"
                # (responsável NÃO sobrescreve o usuario_id do aluno).
                aluno_id = aluno_existente["id"]
                if usuario_id and tem_role_aluno:
                    cur.execute(
                        "UPDATE alunos SET usuario_id = %s WHERE id = %s AND (usuario_id IS NULL OR usuario_id = %s)",
                        (usuario_id, aluno_id, usuario_id),
                    )
            else:
                # Criar novo aluno automaticamente a partir do pré-cadastro
                # Função auxiliar para limpar valores e converter para None
                def _clean_value(val):
                    """Converte valores vazios, 'None', None para NULL."""
                    if val is None:
                        return None
                    if isinstance(val, str):
                        val = val.strip()
                        if val == "" or val.lower() in ("none", "null", "undefined", "nan"):
                            return None
                        # Verificar se é string "None" ou similar
                        if val.lower() == "none":
                            return None
                    elif isinstance(val, (int, float)):
                        # Manter números válidos (exceto NaN)
                        import math
                        if isinstance(val, float) and math.isnan(val):
                            return None
                        return val
                    return val if val else None
                
                graduacao_id = pc.get("graduacao_id")
                if graduacao_id and str(graduacao_id).isdigit():
                    graduacao_id = int(graduacao_id)
                else:
                    graduacao_id = None

                turma_id = pc.get("TurmaID")
                if turma_id and str(turma_id).isdigit():
                    turma_id = int(turma_id)
                else:
                    turma_id = None

                telefone_principal = _clean_value(pc.get("telefone") or pc.get("tel_celular"))
                
                # Limpar peso - converter para float ou None
                peso_val = _clean_value(pc.get("peso"))
                peso = None
                if peso_val:
                    try:
                        peso = float(str(peso_val).replace(",", "."))
                    except (ValueError, TypeError):
                        peso = None

                cur.execute(
                    """
                    INSERT INTO alunos (
                        nome, data_nascimento, sexo, status, ativo, data_matricula,
                        graduacao_id, peso, zempo, telefone, email, observacoes, ultimo_exame_faixa,
                        TurmaID, cpf, id_academia, id_associacao, id_federacao,
                        nome_pai, nome_mae, responsavel_nome, responsavel_parentesco,
                        nacionalidade, rg, orgao_emissor, rg_data_emissao,
                        cep, rua, numero, complemento, bairro, cidade, estado,
                        tel_residencial, tel_comercial, tel_celular, tel_outro,
                        responsavel_financeiro_nome, responsavel_financeiro_cpf, foto, usuario_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        _clean_value(pc.get("nome")),
                        _clean_value(pc.get("data_nascimento")),
                        _clean_value(pc.get("sexo")),
                        "ativo",
                        1,  # Campo ativo: usar 1 como padrão (coluna não permite NULL)
                        date.today(),
                        graduacao_id,
                        peso,
                        _clean_value(pc.get("zempo")),
                        telefone_principal,
                        _clean_value(pc.get("email")),
                        _clean_value(pc.get("observacoes")),
                        _clean_value(pc.get("ultimo_exame_faixa")),
                        turma_id,
                        _clean_value(pc.get("cpf")),
                        academia_id,
                        id_associacao,
                        id_federacao,
                        _clean_value(pc.get("nome_pai")),
                        _clean_value(pc.get("nome_mae")),
                        _clean_value(pc.get("responsavel_nome")),
                        _clean_value(pc.get("responsavel_parentesco")),
                        _clean_value(pc.get("nacionalidade")),
                        _clean_value(pc.get("rg")),
                        _clean_value(pc.get("orgao_emissor")),
                        _clean_value(pc.get("rg_data_emissao")),
                        _clean_value(pc.get("cep")),
                        _clean_value(pc.get("endereco")),
                        _clean_value(pc.get("numero")),
                        _clean_value(pc.get("complemento")),
                        _clean_value(pc.get("bairro")),
                        _clean_value(pc.get("cidade")),
                        _clean_value(pc.get("estado")),
                        _clean_value(pc.get("tel_residencial")),
                        _clean_value(pc.get("tel_comercial")),
                        _clean_value(pc.get("tel_celular")),
                        _clean_value(pc.get("tel_outro")),
                        _clean_value(pc.get("responsavel_financeiro_nome")),
                        _clean_value(pc.get("responsavel_financeiro_cpf")),
                        f"{UPLOAD_PRECAD}/{pc['foto']}" if pc.get("foto") else None,
                        # Só vincula o usuário ao aluno se a role escolhida for "aluno".
                        # Quando é só responsável, o aluno fica sem usuário (aluno não loga).
                        usuario_id if tem_role_aluno else None,
                    ),
                )
                aluno_id = cur.lastrowid
                if not tem_role_aluno and tem_role_responsavel:
                    aluno_criado_via_responsavel = True

                # Garantir vínculo correto (aluno só recebe usuario_id se for aluno)
                if usuario_id and tem_role_aluno:
                    cur.execute(
                        "UPDATE alunos SET usuario_id = %s WHERE id = %s",
                        (usuario_id, aluno_id),
                    )

        # Vincular responsável aos alunos:
        #   - aos alunos selecionados manualmente no formulário (aluno_ids_responsavel)
        #   - ao aluno do próprio pré-cadastro, se a role é "responsável" e temos um aluno_id
        if tem_role_responsavel and usuario_id:
            ids_para_vincular = list(aluno_ids_responsavel)
            if aluno_id and aluno_id not in ids_para_vincular:
                ids_para_vincular.append(aluno_id)
            for aid in ids_para_vincular:
                cur.execute(
                    "SELECT 1 FROM alunos WHERE id = %s AND id_academia = %s",
                    (aid, academia_id),
                )
                if cur.fetchone():
                    cur.execute(
                        "INSERT IGNORE INTO responsavel_alunos (usuario_id, aluno_id) VALUES (%s, %s)",
                        (usuario_id, aid),
                    )

        # Criar registro de professor se role professor está selecionada
        tem_role_professor = any(
            r.get("chave") == "professor" and str(r.get("id")) in roles_escolhidas 
            for r in roles_disponiveis
        )
        if tem_role_professor and usuario_id:
            # Verificar se já existe professor com este usuario_id
            cur.execute("SELECT id FROM professores WHERE usuario_id = %s", (usuario_id,))
            if not cur.fetchone():
                telefone_professor = pc.get("telefone") or pc.get("tel_celular") or None
                email_professor = email_usuario or pc.get("email") or None
                cur.execute(
                    """
                    INSERT INTO professores (nome, email, telefone, usuario_id, id_academia, id_associacao, ativo)
                    VALUES (%s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        pc.get("nome"),
                        email_professor,
                        telefone_professor,
                        usuario_id,
                        academia_id,
                        id_associacao,
                    ),
                )

        # Criar registro de visitante se role visitante está selecionada
        tem_role_visitante = any(
            r.get("chave") == "visitante" and str(r.get("id")) in roles_escolhidas 
            for r in roles_disponiveis
        )
        if tem_role_visitante and usuario_id:
            # Verificar se já existe visitante com este usuario_id
            cur.execute("SELECT id FROM visitantes WHERE usuario_id = %s", (usuario_id,))
            if not cur.fetchone():
                # Buscar limite de aulas da academia
                cur.execute("SELECT aulas_experimentais_permitidas FROM academias WHERE id = %s", (academia_id,))
                acad_row = cur.fetchone()
                limite_aulas = acad_row.get("aulas_experimentais_permitidas") if acad_row else None
                
                telefone_visitante = pc.get("telefone") or pc.get("tel_celular") or None
                email_visitante = email_usuario or pc.get("email") or None
                foto_visitante = f"{UPLOAD_PRECAD}/{pc['foto']}" if pc.get("foto") else None
                
                cur.execute(
                    """
                    INSERT INTO visitantes (nome, email, telefone, data_nascimento, foto, usuario_id, id_academia, aulas_experimentais_permitidas, ativo)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        pc.get("nome"),
                        email_visitante,
                        telefone_visitante,
                        pc.get("data_nascimento"),
                        foto_visitante,
                        usuario_id,
                        academia_id,
                        limite_aulas,
                    ),
                )

        # Credenciais para o responsável — antes de fechar o cursor, e depois do
        # commit: se o envio falhar, a promoção já está gravada.
        aviso_credenciais = None
        if usuario_id and senha_gerada:
            try:
                destino, por_email, por_whats = _enviar_credenciais(
                    cur, pc, academia_id, cpf_login, senha_usuario)
                canais = []
                if por_email:
                    canais.append(f"e-mail ({destino})")
                if por_whats:
                    canais.append("WhatsApp")
                if canais:
                    aviso_credenciais = ("Dados de acesso enviados por "
                                         + " e ".join(canais) + ".", "success")
                else:
                    # Sem envio, a senha precisa aparecer na tela para não se perder.
                    aviso_credenciais = (
                        f"Não foi possível enviar as credenciais. Anote e repasse ao "
                        f"responsável — usuário: {cpf_login} / senha: {senha_usuario}",
                        "warning")
            except Exception:
                current_app.logger.exception("Falha ao enviar credenciais de acesso")
                aviso_credenciais = (
                    f"Usuário criado, mas o envio das credenciais falhou. "
                    f"Usuário: {cpf_login} / senha: {senha_usuario}", "warning")

        # Remover pré-cadastro
        cur.execute("DELETE FROM pre_cadastro WHERE id = %s", (precadastro_id,))
        conn.commit()
        cur.close()
        conn.close()

        if aviso_credenciais:
            flash(aviso_credenciais[0], aviso_credenciais[1])

        perfis_criados = []
        for r in roles_disponiveis:
            if str(r.get("id")) in roles_escolhidas:
                perfis_criados.append(r.get("nome", ""))

        flash(
            f'Pré-cadastro de "{pc.get("nome")}" promovido com sucesso! Perfis criados: {", ".join(perfis_criados)}',
            "success",
        )

        # Boas-vindas ao novo aluno (WhatsApp)
        try:
            _tel_bv = (pc.get("responsavel_financeiro_telefone") or pc.get("telefone") or "").strip()
            if _tel_bv:
                _cn = get_db_connection(); _cc = _cn.cursor()
                _cc.execute("SELECT nome FROM academias WHERE id=%s", (academia_id,))
                _row = _cc.fetchone()
                _cc.close(); _cn.close()
                _ac_nome = _row[0] if _row else ""
                from utils.whatsapp_lembretes import enviar_evento
                enviar_evento(academia_id, "boas_vindas", _tel_bv, {
                    "nome": ((pc.get("responsavel_financeiro_nome") or pc.get("nome") or "").split(" ")[0]),
                    "aluno": pc.get("nome") or "",
                    "academia": _ac_nome,
                })
        except Exception:
            pass
        if origem_cpf == "responsavel_financeiro":
            flash(
                "O login foi criado com o CPF do responsável financeiro.",
                "info",
            )
        if aluno_criado_via_responsavel:
            flash(
                "O cadastro do aluno foi criado automaticamente e vinculado ao responsável. "
                "Você pode editar a ficha do aluno para complementar os dados.",
                "info",
            )
        if aluno_id:
            return redirect(url_for("alunos.editar_aluno", aluno_id=aluno_id, next=url_for("precadastro.lista", academia_id=academia_id)))
        return redirect(url_for("precadastro.lista", academia_id=academia_id))

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        current_app.logger.error(f"Erro ao promover pré-cadastro: {e}")
        flash(f"Erro ao promover: {e}", "danger")
        return redirect(url_for("precadastro.promover", precadastro_id=precadastro_id))
