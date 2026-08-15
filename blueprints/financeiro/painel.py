"""
Painel Financeiro — porte do mockup "Sistema financeiro para academia".

Sete telas (Dashboard, Alunos, Planos, Descontos, Gerar Cobranças, Mensalidades
e Histórico) com layout próprio, servidas em Jinja + CSS puro. Nada de React,
Vite ou Tailwind: o design foi traduzido para `static/css/pages/financeiro_painel.css`.

As funções reaproveitam o que já existe no blueprint financeiro — sobretudo
`_registrar_pagamento_e_receita`, que cuida de juros, desconto e lançamento da
receita ao dar baixa numa mensalidade.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, current_app)
from flask_login import login_required

from config import get_db_connection
from utils.contexto_logo import buscar_logo_url
from blueprints.financeiro.routes import (_get_academia_id, _status_efetivo,
                                          _registrar_pagamento_e_receita,
                                          _ma_enriquecer_exibicao,
                                          _gateway_config_academia, _gateway_ativo)

bp_financeiro_painel = Blueprint(
    "financeiro_painel", __name__, url_prefix="/financeiro/painel"
)

# Blueprint sem prefixo: o link curto precisa ser curto mesmo (/p/<token>).
bp_link_pagamento = Blueprint("link_pagamento", __name__)


@bp_link_pagamento.route("/p/<token>")
def abrir_pagamento(token):
    """Redireciona o link curto para a cobrança no gateway.

    Público de propósito — quem recebe o WhatsApp não tem login. O token é
    aleatório e só expõe a página de pagamento que o gateway já publica.
    """
    from utils.links_curtos import resolver

    url, origem, registro_id = resolver(token)
    if url:
        return redirect(url)
    if origem:
        # Token válido, cobrança sem link ainda (ou já cancelada).
        return render_template("financeiro/painel/link_indisponivel.html"), 404
    return render_template("financeiro/painel/link_indisponivel.html",
                           nao_encontrado=True), 404

MESES_CURTOS = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES_LONGOS = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

# Cores das faixas — as sete do mockup, estendidas para as graduações
# compostas do sistema (ex.: "AZUL/AMARELA" usa a cor do primeiro termo).
FAIXA_CORES = {
    "BRANCA": "#e8eaf0",
    "CINZA": "#9ca3af",
    "AZUL": "#3b82f6",
    "AMARELA": "#f5c518",
    "LARANJA": "#f97316",
    "VERDE": "#22c55e",
    "ROXA": "#a855f7",
    "MARROM": "#92400e",
    "PRETA": "#444444",
    "CORAL": "#fb7185",
    "VERMELHA": "#dc2626",
}


def cor_faixa(nome):
    """Cor do ponto da faixa. Usa o primeiro termo das faixas compostas."""
    txt = (str(nome or "")).upper().strip()
    if not txt:
        return "#6b7a99"
    primeiro = txt.replace("-", "/").split("/")[0].strip()
    for chave, cor in FAIXA_CORES.items():
        if primeiro.startswith(chave):
            return cor
    for chave, cor in FAIXA_CORES.items():
        if chave in txt:
            return cor
    return "#6b7a99"


def fmt_moeda(v):
    """R$ 1.234,56 — mesmo formato do mockup (toLocaleString pt-BR)."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        n = 0.0
    return "R$ " + f"{n:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")


def fmt_mes(ano, mes):
    return f"{MESES_CURTOS[mes]} {ano}"


def _dec(valor, padrao="0"):
    try:
        return Decimal(str(valor).replace(",", ".") or padrao)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(padrao)


def _mes_ref():
    """Mês em foco: ?mes=AAAA-MM, com o mês corrente como padrão."""
    hoje = date.today()
    bruto = (request.args.get("mes") or "").strip()
    if len(bruto) == 7 and bruto[4] == "-":
        try:
            ano, mes = int(bruto[:4]), int(bruto[5:])
            if 1 <= mes <= 12 and 2000 <= ano <= 2100:
                return ano, mes
        except ValueError:
            pass
    return hoje.year, hoje.month


def _meses_disponiveis(ano, mes, qtd=3):
    """O mês em foco e os anteriores, para os botões de período."""
    out = []
    a, m = ano, mes
    for _ in range(qtd):
        out.append({"chave": f"{a:04d}-{m:02d}", "label": fmt_mes(a, m), "ano": a, "mes": m})
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return out


def _ctx_base(academia_id):
    """Nome/logo da academia e rótulo do mês — o rodapé e o topo da sidebar."""
    hoje = date.today()
    ctx = {
        "academia_id": academia_id,
        "academia_nome": None,
        "academia_logo": None,
        "mes_label_atual": fmt_mes(hoje.year, hoje.month),
        "cor_faixa": cor_faixa,
        "fmt_moeda": fmt_moeda,
        "fmt_mes": fmt_mes,
    }
    if not academia_id:
        return ctx
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome FROM academias WHERE id=%s", (academia_id,))
        ctx["academia_nome"] = (cur.fetchone() or {}).get("nome")
    except Exception:
        pass
    finally:
        conn.close()

    # A logo não fica no banco: é um arquivo em static/uploads/logos/academia_<id>.<ext>.
    try:
        ctx["academia_logo"] = buscar_logo_url("academia", academia_id)
    except Exception:
        ctx["academia_logo"] = None
    return ctx


def _sem_academia():
    flash("Selecione uma academia para acessar o financeiro.", "warning")
    return redirect(url_for("painel.home"))


def _volta(endpoint, academia_id, **extra):
    args = dict(extra)
    if academia_id:
        args["academia_id"] = academia_id
    return redirect(url_for(endpoint, **args))


# =====================================================================
# Dashboard
# =====================================================================
@bp_financeiro_painel.route("/")
@bp_financeiro_painel.route("/dashboard")
@login_required
def dashboard():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()
    ano, mes = _mes_ref()
    ant_ano, ant_mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id, ma.valor, ma.status, ma.status_pagamento, ma.data_vencimento,
                      a.id AS aluno_id, a.nome AS aluno_nome, g.faixa AS faixa
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               LEFT JOIN graduacao g ON g.id = a.graduacao_id
               WHERE a.id_academia = %s AND ma.status <> 'cancelado'
                 AND YEAR(ma.data_vencimento) = %s AND MONTH(ma.data_vencimento) = %s""",
            (academia_id, ano, mes),
        )
        do_mes = cur.fetchall()

        cur.execute(
            """SELECT COALESCE(SUM(ma.valor), 0) AS total
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               WHERE a.id_academia = %s AND ma.status = 'pago'
                 AND YEAR(ma.data_vencimento) = %s AND MONTH(ma.data_vencimento) = %s""",
            (academia_id, ant_ano, ant_mes),
        )
        receita_anterior = float((cur.fetchone() or {}).get("total") or 0)

        cur.execute(
            """SELECT a.id, a.nome, g.faixa
               FROM alunos a
               LEFT JOIN graduacao g ON g.id = a.graduacao_id
               WHERE a.id_academia = %s AND COALESCE(a.ativo, 1) = 1""",
            (academia_id,),
        )
        alunos_ativos = cur.fetchall()
    finally:
        conn.close()

    receita_mes = 0.0
    pagos = 0
    pendencias = []
    for r in do_mes:
        efetivo = (_status_efetivo(r.get("status"), r.get("data_vencimento"),
                                   r.get("status_pagamento")) or "").lower()
        valor = float(r.get("valor") or 0)
        if efetivo == "pago":
            receita_mes += valor
            pagos += 1
        else:
            pendencias.append({
                "nome": r.get("aluno_nome"),
                "faixa": r.get("faixa"),
                "valor": valor,
                "status": "Atrasado" if efetivo == "atrasado" else "Pendente",
            })

    total_cobrado = len(do_mes)
    taxa = round((pagos / total_cobrado) * 100) if total_cobrado else 0

    # Receita potencial: soma do que foi cobrado no mês (pago + em aberto).
    receita_potencial = sum(float(r.get("valor") or 0) for r in do_mes)

    faixas = {}
    for a in alunos_ativos:
        nome_faixa = a.get("faixa") or "Sem graduação"
        faixas[nome_faixa] = faixas.get(nome_faixa, 0) + 1
    faixas_ord = sorted(faixas.items(), key=lambda kv: (-kv[1], kv[0]))
    total_ativos = len(alunos_ativos) or 1

    esperada = sorted(
        ({"nome": (r.get("aluno_nome") or "").split(" ")[0], "valor": float(r.get("valor") or 0)}
         for r in do_mes),
        key=lambda x: -x["valor"],
    )[:12]

    ctx = _ctx_base(academia_id)
    ctx.update(
        ativo="dashboard",
        ano=ano, mes=mes,
        mes_label=fmt_mes(ano, mes),
        mes_chave=f"{ano:04d}-{mes:02d}",
        meses=_meses_disponiveis(date.today().year, date.today().month, 6),
        receita_mes=receita_mes,
        receita_anterior=receita_anterior,
        receita_potencial=receita_potencial,
        inadimplentes=len(pendencias),
        taxa=taxa,
        pagos=pagos,
        total_cobrado=total_cobrado,
        alunos_ativos=len(alunos_ativos),
        pendencias=sorted(pendencias, key=lambda p: -p["valor"]),
        faixas=faixas_ord,
        total_ativos=total_ativos,
        esperada=esperada,
    )
    return render_template("financeiro/painel/dashboard.html", **ctx)


# =====================================================================
# Alunos
# =====================================================================
@bp_financeiro_painel.route("/alunos")
@login_required
def alunos():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    busca = (request.args.get("q") or "").strip()
    ordem = (request.args.get("ordem") or "nome").lower()
    if ordem not in ("nome", "faixa", "mensalidade", "ingresso"):
        ordem = "nome"
    ver_inativos = request.args.get("inativos") == "1"
    sel = request.args.get("sel", type=int)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT a.id, a.nome, a.email, a.telefone, a.tel_celular, a.data_matricula,
                      COALESCE(a.ativo, 1) AS ativo, g.faixa,
                      (SELECT ma.valor FROM mensalidade_aluno ma
                        WHERE ma.aluno_id = a.id AND ma.status <> 'cancelado'
                        ORDER BY ma.data_vencimento DESC LIMIT 1) AS mensalidade
               FROM alunos a
               LEFT JOIN graduacao g ON g.id = a.graduacao_id
               WHERE a.id_academia = %s""",
            (academia_id,),
        )
        todos = cur.fetchall()
    finally:
        conn.close()

    ativos = [a for a in todos if a.get("ativo")]
    inativos = [a for a in todos if not a.get("ativo")]

    lista = todos if ver_inativos else ativos
    if busca:
        alvo = busca.lower()
        lista = [a for a in lista
                 if alvo in (a.get("nome") or "").lower()
                 or alvo in (a.get("faixa") or "").lower()]

    if ordem == "mensalidade":
        lista.sort(key=lambda a: -float(a.get("mensalidade") or 0))
    elif ordem == "faixa":
        lista.sort(key=lambda a: (a.get("faixa") or "zzz"))
    elif ordem == "ingresso":
        lista.sort(key=lambda a: (a.get("data_matricula") or date.min), reverse=True)
    else:
        lista.sort(key=lambda a: (a.get("nome") or "").lower())

    selecionado = next((a for a in todos if a["id"] == sel), None) if sel else None

    ctx = _ctx_base(academia_id)
    ctx.update(
        ativo="alunos",
        lista=lista, n_ativos=len(ativos), n_inativos=len(inativos),
        busca=busca, ordem=ordem, ver_inativos=ver_inativos,
        selecionado=selecionado,
    )
    return render_template("financeiro/painel/alunos.html", **ctx)


# =====================================================================
# Planos de mensalidade  (tabela `mensalidades`)
# =====================================================================
@bp_financeiro_painel.route("/planos")
@login_required
def planos():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    editar = request.args.get("editar", type=int)
    novo = request.args.get("novo") == "1"

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT id, nome, descricao, valor, COALESCE(ativo, 0) AS ativo, criado_em
               FROM mensalidades WHERE id_academia = %s ORDER BY ativo DESC, nome""",
            (academia_id,),
        )
        lista = cur.fetchall()
    finally:
        conn.close()

    em_edicao = next((p for p in lista if p["id"] == editar), None) if editar else None

    ctx = _ctx_base(academia_id)
    ctx.update(
        ativo="planos", lista=lista,
        n_ativos=sum(1 for p in lista if p["ativo"]),
        n_inativos=sum(1 for p in lista if not p["ativo"]),
        mostrar_form=bool(novo or em_edicao), em_edicao=em_edicao,
    )
    return render_template("financeiro/painel/planos.html", **ctx)


@bp_financeiro_painel.route("/planos/salvar", methods=["POST"])
@login_required
def planos_salvar():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    plano_id = request.form.get("id", type=int)
    nome = (request.form.get("nome") or "").strip()
    descricao = (request.form.get("descricao") or "").strip()
    valor = _dec(request.form.get("valor"))
    ativo = 1 if (request.form.get("ativo") or "ativo") == "ativo" else 0

    if not nome or valor <= 0:
        flash("Informe o nome do plano e um valor maior que zero.", "danger")
        return _volta("financeiro_painel.planos", academia_id, novo=1)

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if plano_id:
            cur.execute(
                """UPDATE mensalidades SET nome=%s, descricao=%s, valor=%s, ativo=%s
                   WHERE id=%s AND id_academia=%s""",
                (nome, descricao, valor, ativo, plano_id, academia_id),
            )
            flash("Plano atualizado.", "success")
        else:
            cur.execute(
                """INSERT INTO mensalidades (nome, descricao, valor, id_academia, ativo)
                   VALUES (%s, %s, %s, %s, %s)""",
                (nome, descricao, valor, academia_id, ativo),
            )
            flash("Plano cadastrado.", "success")
        conn.commit()
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Painel financeiro — salvar plano: {e}", exc_info=True)
        flash(f"Não foi possível salvar o plano: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.planos", academia_id)


@bp_financeiro_painel.route("/planos/<int:plano_id>/alternar", methods=["POST"])
@login_required
def planos_alternar(plano_id):
    academia_id = _get_academia_id()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE mensalidades SET ativo = IF(COALESCE(ativo,0)=1, 0, 1)
               WHERE id=%s AND id_academia=%s""",
            (plano_id, academia_id),
        )
        conn.commit()
        flash("Situação do plano alterada.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao alterar o plano: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.planos", academia_id)


@bp_financeiro_painel.route("/planos/<int:plano_id>/excluir", methods=["POST"])
@login_required
def planos_excluir(plano_id):
    academia_id = _get_academia_id()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT COUNT(*) AS n FROM mensalidade_aluno WHERE mensalidade_id=%s", (plano_id,))
        if (cur.fetchone() or {}).get("n"):
            # Plano com histórico não é apagado — vira inativo, preservando as cobranças.
            cur.execute("UPDATE mensalidades SET ativo=0 WHERE id=%s AND id_academia=%s",
                        (plano_id, academia_id))
            conn.commit()
            flash("O plano tem mensalidades lançadas, então foi desativado em vez de excluído.", "warning")
        else:
            cur.execute("DELETE FROM mensalidades WHERE id=%s AND id_academia=%s",
                        (plano_id, academia_id))
            conn.commit()
            flash("Plano excluído.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao excluir o plano: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.planos", academia_id)


# =====================================================================
# Descontos
# =====================================================================
@bp_financeiro_painel.route("/descontos")
@login_required
def descontos():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    editar = request.args.get("editar", type=int)
    novo = request.args.get("novo") == "1"
    filtro = (request.args.get("filtro") or "todos").lower()
    if filtro not in ("todos", "ativo", "inativo"):
        filtro = "todos"

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT id, nome, descricao, tipo, valor, COALESCE(ativo,0) AS ativo, criado_em
               FROM descontos WHERE id_academia = %s ORDER BY ativo DESC, nome""",
            (academia_id,),
        )
        todos = cur.fetchall()
    finally:
        conn.close()

    if filtro == "ativo":
        lista = [d for d in todos if d["ativo"]]
    elif filtro == "inativo":
        lista = [d for d in todos if not d["ativo"]]
    else:
        lista = todos

    em_edicao = next((d for d in todos if d["id"] == editar), None) if editar else None

    ctx = _ctx_base(academia_id)
    ctx.update(
        ativo="descontos", lista=lista, filtro=filtro,
        n_ativos=sum(1 for d in todos if d["ativo"]),
        n_inativos=sum(1 for d in todos if not d["ativo"]),
        mostrar_form=bool(novo or em_edicao), em_edicao=em_edicao,
    )
    return render_template("financeiro/painel/descontos.html", **ctx)


@bp_financeiro_painel.route("/descontos/salvar", methods=["POST"])
@login_required
def descontos_salvar():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    desconto_id = request.form.get("id", type=int)
    nome = (request.form.get("nome") or "").strip()
    tipo = (request.form.get("tipo") or "percentual").lower()
    if tipo not in ("percentual", "valor_fixo"):
        tipo = "percentual"
    valor = _dec(request.form.get("valor"))
    descricao = (request.form.get("descricao") or "").strip()
    ativo = 1 if (request.form.get("ativo") or "ativo") == "ativo" else 0

    if not nome or valor <= 0:
        flash("Informe o nome do desconto e um valor maior que zero.", "danger")
        return _volta("financeiro_painel.descontos", academia_id, novo=1)
    if tipo == "percentual" and valor > 100:
        flash("Um desconto percentual não pode passar de 100%.", "danger")
        return _volta("financeiro_painel.descontos", academia_id, novo=1)

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if desconto_id:
            cur.execute(
                """UPDATE descontos SET nome=%s, tipo=%s, valor=%s, descricao=%s, ativo=%s
                   WHERE id=%s AND id_academia=%s""",
                (nome, tipo, valor, descricao, ativo, desconto_id, academia_id),
            )
            flash("Desconto atualizado.", "success")
        else:
            cur.execute(
                """INSERT INTO descontos (nome, descricao, tipo, valor, id_academia, ativo)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (nome, descricao, tipo, valor, academia_id, ativo),
            )
            flash("Desconto cadastrado.", "success")
        conn.commit()
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Painel financeiro — salvar desconto: {e}", exc_info=True)
        flash(f"Não foi possível salvar o desconto: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.descontos", academia_id)


@bp_financeiro_painel.route("/descontos/<int:desconto_id>/alternar", methods=["POST"])
@login_required
def descontos_alternar(desconto_id):
    academia_id = _get_academia_id()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE descontos SET ativo = IF(COALESCE(ativo,0)=1, 0, 1)
               WHERE id=%s AND id_academia=%s""",
            (desconto_id, academia_id),
        )
        conn.commit()
        flash("Situação do desconto alterada.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao alterar o desconto: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.descontos", academia_id)


@bp_financeiro_painel.route("/descontos/<int:desconto_id>/excluir", methods=["POST"])
@login_required
def descontos_excluir(desconto_id):
    academia_id = _get_academia_id()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT COUNT(*) AS n FROM mensalidade_aluno WHERE id_desconto=%s", (desconto_id,))
        if (cur.fetchone() or {}).get("n"):
            cur.execute("UPDATE descontos SET ativo=0 WHERE id=%s AND id_academia=%s",
                        (desconto_id, academia_id))
            conn.commit()
            flash("O desconto já foi usado em cobranças, então foi desativado em vez de excluído.", "warning")
        else:
            cur.execute("DELETE FROM descontos WHERE id=%s AND id_academia=%s",
                        (desconto_id, academia_id))
            conn.commit()
            flash("Desconto excluído.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao excluir o desconto: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.descontos", academia_id)


# =====================================================================
# Formas de pagamento
# =====================================================================
FORMAS_PADRAO = ["Dinheiro", "PIX", "Cartão de crédito", "Cartão de débito", "Boleto"]


@bp_financeiro_painel.route("/formas")
@login_required
def formas():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    editar = request.args.get("editar", type=int)
    novo = request.args.get("novo") == "1"

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT id, nome, ordem, COALESCE(ativo,1) AS ativo, criado_em
               FROM formas_pagamento WHERE id_academia=%s ORDER BY ordem, nome""",
            (academia_id,),
        )
        lista = cur.fetchall()

        # Quantas cobranças já usam cada forma — define se dá para excluir.
        cur.execute(
            """SELECT id_forma_pagamento AS fid, COUNT(*) AS n
               FROM mensalidade_aluno WHERE id_forma_pagamento IS NOT NULL
               GROUP BY id_forma_pagamento""",
        )
        usos = {r["fid"]: r["n"] for r in cur.fetchall()}
    finally:
        conn.close()

    for f in lista:
        f["usos"] = usos.get(f["id"], 0)

    em_edicao = next((f for f in lista if f["id"] == editar), None) if editar else None

    ctx = _ctx_base(academia_id)
    ctx.update(
        ativo="formas", lista=lista,
        n_ativos=sum(1 for f in lista if f["ativo"]),
        n_inativos=sum(1 for f in lista if not f["ativo"]),
        mostrar_form=bool(novo or em_edicao), em_edicao=em_edicao,
        padroes=FORMAS_PADRAO,
    )
    return render_template("financeiro/painel/formas.html", **ctx)


@bp_financeiro_painel.route("/formas/salvar", methods=["POST"])
@login_required
def formas_salvar():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    forma_id = request.form.get("id", type=int)
    nome = (request.form.get("nome") or "").strip()
    ordem = request.form.get("ordem", type=int) or 0
    ativo = 1 if (request.form.get("ativo") or "ativo") == "ativo" else 0

    if not nome:
        flash("Informe o nome da forma de pagamento.", "danger")
        return _volta("financeiro_painel.formas", academia_id, novo=1)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Nome repetido na mesma academia confunde na hora de dar baixa.
        cur.execute(
            """SELECT id FROM formas_pagamento
               WHERE id_academia=%s AND LOWER(nome)=LOWER(%s) AND id <> %s""",
            (academia_id, nome, forma_id or 0),
        )
        if cur.fetchone():
            flash(f'Já existe uma forma chamada "{nome}" nesta academia.', "warning")
            return _volta("financeiro_painel.formas", academia_id)

        if forma_id:
            cur.execute(
                """UPDATE formas_pagamento SET nome=%s, ordem=%s, ativo=%s
                   WHERE id=%s AND id_academia=%s""",
                (nome[:80], ordem, ativo, forma_id, academia_id),
            )
            flash("Forma de pagamento atualizada.", "success")
        else:
            if not ordem:
                cur.execute(
                    "SELECT COALESCE(MAX(ordem),0)+1 AS o FROM formas_pagamento WHERE id_academia=%s",
                    (academia_id,),
                )
                ordem = int((cur.fetchone() or {}).get("o") or 1)
            cur.execute(
                """INSERT INTO formas_pagamento (id_academia, nome, ordem, ativo)
                   VALUES (%s, %s, %s, %s)""",
                (academia_id, nome[:80], ordem, ativo),
            )
            flash("Forma de pagamento cadastrada.", "success")
        conn.commit()
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Painel financeiro — salvar forma: {e}", exc_info=True)
        flash(f"Não foi possível salvar: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.formas", academia_id)


@bp_financeiro_painel.route("/formas/padrao", methods=["POST"])
@login_required
def formas_padrao():
    """Cria de uma vez as formas mais comuns — atalho para academia recém-criada."""
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    criadas = 0
    try:
        cur.execute("SELECT LOWER(nome) AS n FROM formas_pagamento WHERE id_academia=%s",
                    (academia_id,))
        existentes = {r["n"] for r in cur.fetchall()}
        cur.execute("SELECT COALESCE(MAX(ordem),0) AS o FROM formas_pagamento WHERE id_academia=%s",
                    (academia_id,))
        ordem = int((cur.fetchone() or {}).get("o") or 0)

        for nome in FORMAS_PADRAO:
            if nome.lower() in existentes:
                continue
            ordem += 1
            cur.execute(
                """INSERT INTO formas_pagamento (id_academia, nome, ordem, ativo)
                   VALUES (%s, %s, %s, 1)""",
                (academia_id, nome, ordem),
            )
            criadas += 1
        conn.commit()
        flash(f"{criadas} forma(s) de pagamento criada(s)." if criadas
              else "As formas padrão já estavam cadastradas.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao criar as formas padrão: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.formas", academia_id)


@bp_financeiro_painel.route("/formas/<int:forma_id>/alternar", methods=["POST"])
@login_required
def formas_alternar(forma_id):
    academia_id = _get_academia_id()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE formas_pagamento SET ativo = IF(COALESCE(ativo,1)=1, 0, 1)
               WHERE id=%s AND id_academia=%s""",
            (forma_id, academia_id),
        )
        conn.commit()
        flash("Situação da forma de pagamento alterada.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao alterar: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.formas", academia_id)


@bp_financeiro_painel.route("/formas/<int:forma_id>/excluir", methods=["POST"])
@login_required
def formas_excluir(forma_id):
    academia_id = _get_academia_id()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Forma já usada em baixas vira inativa: excluir apagaria o histórico.
        cur.execute("SELECT COUNT(*) AS n FROM mensalidade_aluno WHERE id_forma_pagamento=%s",
                    (forma_id,))
        usada = int((cur.fetchone() or {}).get("n") or 0)
        if not usada:
            cur.execute("SELECT COUNT(*) AS n FROM receitas WHERE id_forma_pagamento=%s",
                        (forma_id,))
            usada = int((cur.fetchone() or {}).get("n") or 0)

        if usada:
            cur.execute("UPDATE formas_pagamento SET ativo=0 WHERE id=%s AND id_academia=%s",
                        (forma_id, academia_id))
            conn.commit()
            flash(f"Esta forma já foi usada em {usada} lançamento(s), então foi "
                  "desativada em vez de excluída.", "warning")
        else:
            cur.execute("DELETE FROM formas_pagamento WHERE id=%s AND id_academia=%s",
                        (forma_id, academia_id))
            conn.commit()
            flash("Forma de pagamento excluída.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao excluir: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.formas", academia_id)


# =====================================================================
# Gerar cobranças
# =====================================================================
def _valor_com_desconto(valor, desconto):
    """Aplica o desconto (percentual ou valor fixo). Nunca devolve negativo."""
    v = Decimal(str(valor or 0))
    if not desconto:
        return v
    d = Decimal(str(desconto.get("valor") or 0))
    if (desconto.get("tipo") or "").lower() == "percentual":
        v = v - (v * d / Decimal("100"))
    else:
        v = v - d
    return max(Decimal("0"), v.quantize(Decimal("0.01")))


def _desconto_do_aluno(aluno_id, academia_id, valor, vencimento):
    """Desconto por vínculo (aluno_desconto) vigente na data do vencimento.

    Reaproveita o cálculo oficial do financeiro, para a cobrança gerada aqui bater
    com o valor que as outras telas mostram. Retorna (valor_final, id_desconto).
    """
    try:
        from blueprints.financeiro.routes import _valor_com_desconto as _calc
        _vi, _vd, vf, _nome = _calc(
            {"valor": valor, "data_vencimento": vencimento}, aluno_id, academia_id
        )
        if vf is not None and Decimal(str(vf)) < Decimal(str(valor)):
            # O helper não devolve o id; busca o vínculo vigente para gravar na linha.
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(
                    """SELECT d.id FROM aluno_desconto ad
                       JOIN descontos d ON d.id = ad.desconto_id AND d.ativo = 1
                       WHERE ad.aluno_id=%s AND ad.ativo=1 AND d.id_academia=%s
                         AND (ad.data_inicio IS NULL OR ad.data_inicio <= %s)
                         AND (ad.data_fim IS NULL OR ad.data_fim >= %s)
                       LIMIT 1""",
                    (aluno_id, academia_id, vencimento, vencimento),
                )
                row = cur.fetchone()
            finally:
                cur.close(); conn.close()
            return Decimal(str(vf)).quantize(Decimal("0.01")), (row or {}).get("id")
    except Exception:
        pass
    return Decimal(str(valor)), None


@bp_financeiro_painel.route("/cobrancas")
@login_required
def cobrancas():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()
    ano, mes = _mes_ref()
    filtro = (request.args.get("filtro") or "Todos")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id, ma.valor, ma.valor_original, ma.status, ma.status_pagamento,
                      ma.data_vencimento, ma.criado_em, ma.id_desconto,
                      a.id AS aluno_id, a.nome AS aluno_nome, g.faixa,
                      d.nome AS desconto_nome, d.tipo AS desconto_tipo, d.valor AS desconto_valor
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               LEFT JOIN graduacao g ON g.id = a.graduacao_id
               LEFT JOIN descontos d ON d.id = ma.id_desconto
               WHERE a.id_academia = %s
                 AND YEAR(ma.data_vencimento) = %s AND MONTH(ma.data_vencimento) = %s
               ORDER BY a.nome""",
            (academia_id, ano, mes),
        )
        do_mes = cur.fetchall()
        for r in do_mes:
            r["tipo"] = "mensalidade"

        # Cobranças avulsas do mesmo mês entram na lista: sem elas a tela dá a
        # impressão de que a cobrança sumiu (ela só vivia na tela antiga).
        cur.execute(
            """SELECT ca.id, ca.valor, ca.status, ca.data_vencimento, ca.descricao,
                      ca.created_at AS criado_em,
                      a.id AS aluno_id, a.nome AS aluno_nome, g.faixa
               FROM cobranca_avulsa ca
               JOIN alunos a ON a.id = ca.aluno_id
               LEFT JOIN graduacao g ON g.id = a.graduacao_id
               WHERE ca.id_academia = %s
                 AND YEAR(ca.data_vencimento) = %s AND MONTH(ca.data_vencimento) = %s
               ORDER BY a.nome""",
            (academia_id, ano, mes),
        )
        avulsas = cur.fetchall()
        for r in avulsas:
            r["tipo"] = "avulsa"
            r["valor_original"] = r["valor"]
            r["status_pagamento"] = None
            r["id_desconto"] = None
        do_mes = sorted(do_mes + avulsas, key=lambda r: (r.get("aluno_nome") or "").lower())

        cur.execute(
            """SELECT a.id, a.nome, g.faixa
               FROM alunos a
               LEFT JOIN graduacao g ON g.id = a.graduacao_id
               WHERE a.id_academia = %s AND COALESCE(a.ativo, 1) = 1
               ORDER BY a.nome""",
            (academia_id,),
        )
        ativos = cur.fetchall()

        cur.execute(
            """SELECT id, nome, valor FROM mensalidades
               WHERE id_academia=%s AND COALESCE(ativo,0)=1 ORDER BY nome""",
            (academia_id,),
        )
        planos_ativos = cur.fetchall()

        cur.execute(
            """SELECT id, nome, tipo, valor FROM descontos
               WHERE id_academia=%s AND COALESCE(ativo,0)=1 ORDER BY nome""",
            (academia_id,),
        )
        descontos_ativos = cur.fetchall()
    finally:
        conn.close()

    # "Sem cobrança" continua olhando só mensalidade: o painel ao lado gera
    # mensalidade do mês, e ter uma avulsa não dispensa o aluno dela.
    ja_tem = {r["aluno_id"] for r in do_mes if r.get("tipo") != "avulsa"}
    sem_cobranca = [a for a in ativos if a["id"] not in ja_tem]

    for r in do_mes:
        efetivo = (_status_efetivo(r.get("status"), r.get("data_vencimento"),
                                   r.get("status_pagamento")) or "").lower()
        if (r.get("status") or "").lower() == "cancelado":
            r["rotulo"] = "Cancelada"
        elif efetivo == "pago":
            r["rotulo"] = "Paga"
        elif efetivo == "atrasado":
            r["rotulo"] = "Atrasado"
        else:
            r["rotulo"] = "Gerada"

    lista = do_mes if filtro == "Todos" else [r for r in do_mes if r["rotulo"] == filtro]
    total = sum(float(r.get("valor") or 0) for r in lista)

    ctx = _ctx_base(academia_id)
    ctx.update(
        ativo="cobrancas", ano=ano, mes=mes,
        mes_chave=f"{ano:04d}-{mes:02d}", mes_label=fmt_mes(ano, mes),
        meses=_meses_disponiveis(date.today().year, date.today().month + 1
                                 if date.today().month < 12 else 12, 3),
        lista=lista, filtro=filtro, total=total,
        n_cobrancas=len(do_mes),
        n_pagas=sum(1 for r in do_mes if r["rotulo"] == "Paga"),
        n_geradas=sum(1 for r in do_mes if r["rotulo"] in ("Gerada", "Atrasado")),
        sem_cobranca=sem_cobranca,
        planos=planos_ativos, descontos_lista=descontos_ativos,
    )
    return render_template("financeiro/painel/cobrancas.html", **ctx)


@bp_financeiro_painel.route("/cobrancas/gerar", methods=["POST"])
@login_required
def cobrancas_gerar():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    mes_chave = (request.form.get("mes") or "").strip()
    try:
        ano, mes = int(mes_chave[:4]), int(mes_chave[5:7])
    except (ValueError, IndexError):
        hoje = date.today()
        ano, mes = hoje.year, hoje.month

    alunos_ids = [int(x) for x in request.form.getlist("aluno_id") if str(x).isdigit()]
    plano_id = request.form.get("plano_id", type=int)
    desconto_id = request.form.get("desconto_id", type=int)
    dia_venc = request.form.get("dia_vencimento", type=int) or 10
    dia_venc = min(max(dia_venc, 1), 28)
    observacao = (request.form.get("observacao") or "").strip() or None

    if not alunos_ids:
        flash("Selecione ao menos um aluno.", "warning")
        return _volta("financeiro_painel.cobrancas", academia_id, mes=f"{ano:04d}-{mes:02d}")
    if not plano_id:
        flash("Selecione o plano que será cobrado.", "warning")
        return _volta("financeiro_painel.cobrancas", academia_id, mes=f"{ano:04d}-{mes:02d}")

    vencimento = date(ano, mes, dia_venc)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    criadas = 0
    try:
        cur.execute("SELECT id, valor FROM mensalidades WHERE id=%s AND id_academia=%s",
                    (plano_id, academia_id))
        plano = cur.fetchone()
        if not plano:
            flash("Plano inválido para esta academia.", "danger")
            return _volta("financeiro_painel.cobrancas", academia_id, mes=f"{ano:04d}-{mes:02d}")

        desconto = None
        if desconto_id:
            cur.execute("SELECT id, nome, tipo, valor FROM descontos WHERE id=%s AND id_academia=%s",
                        (desconto_id, academia_id))
            desconto = cur.fetchone()

        valor_original = Decimal(str(plano.get("valor") or 0))

        for aluno_id in alunos_ids:
            # O desconto escolhido no formulário vale para todos; sem ele, cada
            # aluno ainda pode ter desconto próprio por vínculo (aluno_desconto)
            # — era o que fazia a cobrança sair com o valor cheio.
            if desconto:
                valor_final = _valor_com_desconto(valor_original, desconto)
                desconto_id_linha = desconto.get("id")
            else:
                valor_final, desconto_id_linha = _desconto_do_aluno(
                    aluno_id, academia_id, valor_original, vencimento)
            aplicado = valor_original - valor_final

            # Não duplica: um aluno já cobrado no mês é ignorado.
            cur.execute(
                """SELECT id FROM mensalidade_aluno
                   WHERE aluno_id=%s AND status <> 'cancelado'
                     AND YEAR(data_vencimento)=%s AND MONTH(data_vencimento)=%s""",
                (aluno_id, ano, mes),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """INSERT INTO mensalidade_aluno
                     (mensalidade_id, aluno_id, data_vencimento, valor, valor_original,
                      desconto_aplicado, id_desconto, status, status_pagamento, observacoes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendente', 'pendente', %s)""",
                (plano_id, aluno_id, vencimento, valor_final, valor_original,
                 aplicado, desconto_id_linha, observacao),
            )
            criadas += 1
        conn.commit()
        if criadas:
            flash(f"{criadas} cobrança(s) gerada(s) para {fmt_mes(ano, mes)}.", "success")
        else:
            flash("Nenhuma cobrança nova — os alunos selecionados já tinham cobrança no mês.", "warning")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Painel financeiro — gerar cobranças: {e}", exc_info=True)
        flash(f"Erro ao gerar as cobranças: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.cobrancas", academia_id, mes=f"{ano:04d}-{mes:02d}")


@bp_financeiro_painel.route("/cobrancas/<int:registro_id>/cancelar", methods=["POST"])
@login_required
def cobrancas_cancelar(registro_id):
    academia_id = _get_academia_id()
    mes_chave = (request.form.get("mes") or "").strip()
    tipo = (request.form.get("tipo") or "mensalidade").strip().lower()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if tipo == "avulsa":
            cur.execute(
                """UPDATE cobranca_avulsa SET status='cancelado'
                   WHERE id=%s AND id_academia=%s AND status <> 'pago'""",
                (registro_id, academia_id),
            )
        else:
            cur.execute(
                """UPDATE mensalidade_aluno ma
                   JOIN alunos a ON a.id = ma.aluno_id
                   SET ma.status='cancelado'
                   WHERE ma.id=%s AND a.id_academia=%s AND ma.status <> 'pago'""",
                (registro_id, academia_id),
            )
        conn.commit()
        flash("Cobrança cancelada.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao cancelar: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.cobrancas", academia_id, mes=mes_chave)


# =====================================================================
# Mensalidades (com baixa de pagamento)
# =====================================================================
@bp_financeiro_painel.route("/mensalidades")
@login_required
def mensalidades():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()
    ano, mes = _mes_ref()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id, ma.aluno_id, ma.valor, ma.status, ma.status_pagamento,
                      ma.data_vencimento, ma.data_pagamento, ma.id_desconto,
                      COALESCE(ma.remover_juros, 0) AS remover_juros,
                      a.nome AS aluno_nome, g.faixa, fp.nome AS forma_nome,
                      COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
                      COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
                      COALESCE(m.percentual_juros_dia, 0.033) AS percentual_juros_dia
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               JOIN mensalidades m ON m.id = ma.mensalidade_id
               LEFT JOIN graduacao g ON g.id = a.graduacao_id
               LEFT JOIN formas_pagamento fp ON fp.id = ma.id_forma_pagamento
               WHERE a.id_academia = %s AND ma.status <> 'cancelado'
                 AND YEAR(ma.data_vencimento) = %s AND MONTH(ma.data_vencimento) = %s
               ORDER BY a.nome""",
            (academia_id, ano, mes),
        )
        lista = cur.fetchall()

        cur.execute(
            """SELECT id, nome FROM formas_pagamento
               WHERE id_academia=%s AND COALESCE(ativo,1)=1 ORDER BY ordem, nome""",
            (academia_id,),
        )
        formas = cur.fetchall()
    finally:
        conn.close()

    arrecadado = pendente = 0.0
    pagos = atrasados = 0
    for r in lista:
        # Calcula multa/juros e valor final pela mesma rotina da tela clássica,
        # para os dois lugares mostrarem exatamente o mesmo número.
        try:
            _ma_enriquecer_exibicao(r, r.get("aluno_id"), academia_id)
        except Exception:
            r.setdefault("valor_final", float(r.get("valor") or 0))
            r.setdefault("tem_juros", False)
            r.setdefault("multa_val", 0)
            r.setdefault("juros_val", 0)

        efetivo = (r.get("status_efetivo")
                   or _status_efetivo(r.get("status"), r.get("data_vencimento"),
                                      r.get("status_pagamento")) or "").lower()
        r["efetivo"] = efetivo
        r["rotulo"] = {"pago": "Pago", "atrasado": "Atrasado"}.get(efetivo, "Pendente")
        r["acrescimo"] = float(r.get("multa_val") or 0) + float(r.get("juros_val") or 0)
        # Juros só é acionável enquanto a mensalidade não foi paga.
        r["pode_juros"] = efetivo != "pago" and bool(r.get("aplicar_juros_multas"))

        valor = float(r.get("valor_final") or r.get("valor") or 0)
        r["valor_exibido"] = valor
        if efetivo == "pago":
            arrecadado += valor
            pagos += 1
        else:
            pendente += valor
            if efetivo == "atrasado":
                atrasados += 1

    total = len(lista)
    taxa = round((pagos / total) * 100) if total else 0

    # Contagem global de atrasados (todos os meses) — é o que o botão dispara.
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT COUNT(*) AS n FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               WHERE a.id_academia = %s AND ma.status IN ('pendente','atrasado')
                 AND ma.data_vencimento IS NOT NULL AND ma.data_vencimento < CURDATE()
                 AND ma.valor > 0""",
            (academia_id,),
        )
        atrasados_geral = int((cur.fetchone() or {}).get("n") or 0)
    except Exception:
        atrasados_geral = atrasados
    finally:
        conn.close()

    ctx = _ctx_base(academia_id)
    ctx.update(
        ativo="mensalidades", ano=ano, mes=mes,
        mes_chave=f"{ano:04d}-{mes:02d}", mes_label=fmt_mes(ano, mes),
        meses=_meses_disponiveis(date.today().year, date.today().month, 4),
        lista=lista, formas=formas,
        arrecadado=arrecadado, pendente=pendente,
        pagos=pagos, total=total, taxa=taxa,
        atrasados=atrasados, atrasados_geral=atrasados_geral,
    )
    return render_template("financeiro/painel/mensalidades.html", **ctx)


@bp_financeiro_painel.route("/mensalidades/<int:registro_id>/pagar", methods=["POST"])
@login_required
def mensalidades_pagar(registro_id):
    """Dá baixa reaproveitando a rotina oficial (juros, desconto e receita)."""
    academia_id = _get_academia_id()
    mes_chave = (request.form.get("mes") or "").strip()
    id_forma = request.form.get("id_forma_pagamento", type=int)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               WHERE ma.id=%s AND a.id_academia=%s""",
            (registro_id, academia_id),
        )
        if not cur.fetchone():
            flash("Mensalidade não encontrada nesta academia.", "danger")
            return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)

        ok = _registrar_pagamento_e_receita(
            conn, cur, "mensalidade_aluno", registro_id, academia_id, id_forma
        )
        if ok:
            conn.commit()
            # Confirmação no WhatsApp — os demais caminhos de baixa já fazem isso;
            # sem esta chamada o aluno não era avisado ao pagar pelo painel.
            avisado = False
            try:
                from utils.whatsapp_lembretes import enviar_confirmacao_pagamento
                avisado = enviar_confirmacao_pagamento(registro_id, "mensalidade_aluno")
            except Exception as e:
                current_app.logger.warning(
                    f"Painel financeiro — confirmação WhatsApp da mensalidade {registro_id}: {e}")
            flash("Pagamento registrado e receita lançada."
                  + (" Confirmação enviada no WhatsApp." if avisado else ""), "success")
        else:
            conn.rollback()
            flash("Não foi possível registrar o pagamento desta mensalidade.", "danger")
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Painel financeiro — baixa mensalidade {registro_id}: {e}",
                                 exc_info=True)
        flash(f"Erro ao registrar o pagamento: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)


@bp_financeiro_painel.route("/mensalidades/notificar-atrasados", methods=["POST"])
@login_required
def mensalidades_notificar_atrasados():
    """Um clique: dispara o lembrete de WhatsApp para TODOS os atrasados.

    Ignora o interruptor da automação diária — aqui a ação é explícita do gestor.
    Cada lembrete gera o link de pagamento se ainda não houver (ver
    `whatsapp_lembretes.garantir_cobranca_online`).
    """
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()
    mes_chave = (request.form.get("mes") or "").strip()

    from utils import whatsapp as wpp
    from utils import whatsapp_lembretes as lem

    if not wpp.disponivel():
        flash("O serviço de WhatsApp está fora do ar — nenhuma mensagem foi enviada.", "danger")
        return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)
    if not wpp.conectado(academia_id):
        flash("O WhatsApp desta academia não está conectado. Leia o QR Code em "
              "Academia → WhatsApp e tente de novo.", "warning")
        return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)

    r = lem.enviar_lote(academia_id, somente_ativadas=False, somente_atrasadas=True)

    if not r.get("total"):
        flash("Nenhuma mensalidade em atraso para notificar.", "success")
    else:
        partes = [f"{r.get('enviados', 0)} de {r['total']} lembrete(s) enviado(s)"]
        if r.get("sem_telefone"):
            partes.append(f"{r['sem_telefone']} sem telefone")
        if r.get("falhas"):
            partes.append(f"{r['falhas']} falha(s)")
        if r.get("desativado"):
            partes.append(f"{r['desativado']} com modelo desativado")
        flash(" · ".join(partes) + ".", "success" if r.get("enviados") else "warning")
    return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)


@bp_financeiro_painel.route("/mensalidades/atualizar-links", methods=["POST"])
@login_required
def mensalidades_atualizar_links():
    """Reemite a cobrança online das mensalidades em aberto do mês.

    Serve para consertar links antigos: o endereço e o valor com desconto ficam
    congelados na URL do gateway no momento da emissão, então cobranças geradas
    antes de uma correção continuam mostrando os dados velhos ao pagador.
    """
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()
    ano, mes = _mes_ref()
    mes_chave = f"{ano:04d}-{mes:02d}"

    from utils import whatsapp_lembretes as lem

    cfg = _gateway_config_academia(academia_id)
    if not _gateway_ativo(cfg):
        flash("Nenhum gateway de cobrança online ativo nesta academia.", "warning")
        return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id, ma.aluno_id, ma.valor, ma.valor_original, ma.desconto_aplicado,
                      ma.id_desconto, ma.data_vencimento,
                      ma.asaas_boleto_url, ma.cora_boleto_url, ma.inter_boleto_url
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               WHERE a.id_academia=%s AND ma.status IN ('pendente','atrasado')
                 AND ma.valor > 0
                 AND YEAR(ma.data_vencimento)=%s AND MONTH(ma.data_vencimento)=%s""",
            (academia_id, ano, mes),
        )
        alvos = cur.fetchall()
    finally:
        conn.close()

    refeitos = falhas = 0
    for row in alvos:
        antes = lem._link_gateway(row)
        novo = lem.garantir_cobranca_online(dict(row), academia_id, forcar=True)
        if lem._link_gateway(novo) and lem._link_gateway(novo) != antes:
            refeitos += 1
        else:
            falhas += 1

    if not alvos:
        flash(f"Nenhuma mensalidade em aberto em {fmt_mes(ano, mes)}.", "success")
    elif refeitos:
        msg = f"{refeitos} link(s) atualizado(s) com o valor e o endereço corretos."
        if falhas:
            msg += f" {falhas} não puderam ser refeitos (veja o log)."
        flash(msg, "success" if not falhas else "warning")
    else:
        flash("Nenhum link pôde ser atualizado — confira as credenciais do gateway.", "danger")
    return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)


@bp_financeiro_painel.route("/mensalidades/<int:registro_id>/juros", methods=["POST"])
@login_required
def mensalidades_juros(registro_id):
    """Liga/desliga a cobrança de juros e multa de uma mensalidade.

    O clássico só sabia remover; aqui o gestor também consegue reaplicar, caso
    tenha isentado por engano.
    """
    academia_id = _get_academia_id()
    mes_chave = (request.form.get("mes") or "").strip()
    remover = (request.form.get("acao") or "remover") == "remover"

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               WHERE ma.id=%s AND a.id_academia=%s
                 AND ma.status IN ('pendente','atrasado','aguardando_confirmacao')""",
            (registro_id, academia_id),
        )
        if not cur.fetchone():
            flash("Mensalidade não encontrada nesta academia, ou já está paga.", "warning")
            return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)

        cur.execute("UPDATE mensalidade_aluno SET remover_juros=%s WHERE id=%s",
                    (1 if remover else 0, registro_id))
        conn.commit()
        flash("Juros e multa removidos desta mensalidade." if remover
              else "Juros e multa voltaram a ser cobrados nesta mensalidade.", "success")
    except Exception as e:
        conn.rollback()
        if "Unknown column 'remover_juros'" in str(e):
            flash("Recurso indisponível: falta rodar a migration "
                  "add_mensalidade_aluno_remover_juros.sql.", "warning")
        else:
            current_app.logger.error(f"Painel financeiro — juros {registro_id}: {e}", exc_info=True)
            flash(f"Erro ao alterar os juros: {e}", "danger")
    finally:
        conn.close()
    return _volta("financeiro_painel.mensalidades", academia_id, mes=mes_chave)


# =====================================================================
# Histórico de pagamentos
# =====================================================================
@bp_financeiro_painel.route("/historico")
@login_required
def historico():
    academia_id = _get_academia_id()
    if not academia_id:
        return _sem_academia()

    f_status = request.args.get("status") or "Todos"
    f_forma = request.args.get("forma") or "Todos"
    f_mes = request.args.get("mes") or "Todos"

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT ma.id, ma.valor, ma.status, ma.status_pagamento, ma.data_vencimento,
                      ma.data_pagamento, a.nome AS aluno_nome, fp.nome AS forma_nome
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               LEFT JOIN formas_pagamento fp ON fp.id = ma.id_forma_pagamento
               WHERE a.id_academia = %s AND ma.status <> 'cancelado'
                 AND ma.data_vencimento >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
               ORDER BY ma.data_vencimento DESC, a.nome""",
            (academia_id,),
        )
        registros = cur.fetchall()
    finally:
        conn.close()

    meses = []
    for r in registros:
        venc = r.get("data_vencimento")
        chave = f"{venc.year:04d}-{venc.month:02d}" if venc else "—"
        r["mes_chave"] = chave
        r["mes_label"] = fmt_mes(venc.year, venc.month) if venc else "—"
        if chave not in meses and chave != "—":
            meses.append(chave)
        efetivo = (_status_efetivo(r.get("status"), venc, r.get("status_pagamento")) or "").lower()
        r["rotulo"] = {"pago": "Pago", "atrasado": "Atrasado"}.get(efetivo, "Pendente")

    formas_usadas = sorted({r["forma_nome"] for r in registros if r.get("forma_nome")})

    lista = registros
    if f_status != "Todos":
        lista = [r for r in lista if r["rotulo"] == f_status]
    if f_forma != "Todos":
        lista = [r for r in lista if (r.get("forma_nome") or "") == f_forma]
    if f_mes != "Todos":
        lista = [r for r in lista if r["mes_chave"] == f_mes]

    total_pago = sum(float(r["valor"] or 0) for r in lista if r["rotulo"] == "Pago")
    por_forma = []
    for f in formas_usadas:
        soma = sum(float(r["valor"] or 0) for r in lista
                   if r["rotulo"] == "Pago" and r.get("forma_nome") == f)
        if soma:
            por_forma.append({"nome": f, "total": soma})

    ctx = _ctx_base(academia_id)
    ctx.update(
        ativo="historico", lista=lista,
        f_status=f_status, f_forma=f_forma, f_mes=f_mes,
        meses=[{"chave": m, "label": fmt_mes(int(m[:4]), int(m[5:]))} for m in meses],
        formas_usadas=formas_usadas,
        total_pago=total_pago, por_forma=por_forma,
    )
    return render_template("financeiro/painel/historico.html", **ctx)
