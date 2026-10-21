# ======================================================
# Blueprint: Exame de faixa
# ======================================================
"""Exame de faixa — programa, tabela de preços, aptos, banca e modo estudo.

Duas pontas:

* Gestão (associação, academia, professor): o programa de cada promoção, a
  tabela de preços editável, a lista de quem está apto, os exames marcados e a
  banca — onde, no dia do exame, cada inscrito recebe as técnicas sorteadas e
  a nota de cada uma.

* Aluno e responsável: o modo estudo (o material da próxima faixa e de todas
  as anteriores, separado por faixa), a inscrição no exame e "meu exame", que
  mostra o que vai ser cobrado e, depois da prova, o resultado.

O exame é um evento de `eventos_competicoes` com `exame_faixa = 1`: criado
pela associação no cadastro de eventos, com adesão das academias como qualquer
evento. A diferença está na inscrição — em vez do formulário genérico, o aluno
confirma a promoção calculada pelo sistema, e a inscrição guarda a faixa e o
valor daquele momento.
"""
import json
from datetime import date, datetime

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_required

from dateutil.relativedelta import relativedelta

from config import get_db_connection
from utils import exame_faixa as exf
from utils.alunos_academias import aluno_vinculado_a_academia, filtro_alunos_da_academia

bp_exame_faixa = Blueprint("exame_faixa", __name__, url_prefix="/exame-faixa")

PAPEIS_GESTAO = ("admin", "gestor_associacao", "gestor_academia", "professor")


# ------------------------------------------------------------------ escopo
def _tem(*papeis):
    return any(current_user.has_role(p) for p in papeis)


def _escopo(cur):
    """O que o usuário de gestão enxerga: associação, academias e permissões.

    Associação (e admin) vê todas as academias da associação e edita a tabela
    de preços. Academia e professor veem só as suas academias; o programa e o
    preço vêm da associação a que a academia pertence.
    """
    if not _tem(*PAPEIS_GESTAO):
        return None
    modo = session.get("modo_painel") or ""
    esc = {"modo": modo, "id_assoc": None, "academias": [], "academia_id": None,
           "ve_todas": False, "pode_editar": False, "pode_criar": False}
    if modo in ("associacao", "admin", "federacao") and _tem("gestor_associacao", "admin"):
        id_assoc = (getattr(current_user, "id_associacao", None)
                    or session.get("associacao_gerenciamento_id"))
        if not id_assoc and current_user.has_role("admin"):
            cur.execute("SELECT id FROM associacoes ORDER BY id LIMIT 1")
            id_assoc = (cur.fetchone() or {}).get("id")
        esc["id_assoc"] = id_assoc
        esc["ve_todas"] = True
        esc["pode_editar"] = True
        esc["pode_criar"] = True
        if id_assoc:
            cur.execute("SELECT id, nome FROM academias WHERE id_associacao = %s ORDER BY nome",
                        (id_assoc,))
            esc["academias"] = cur.fetchall()
        aid = request.values.get("academia_id", type=int)
        if aid and any(a["id"] == aid for a in esc["academias"]):
            esc["academia_id"] = aid
        return esc

    from blueprints.eventos_competicoes.routes import _get_ids_academias
    ids = _get_ids_academias(cur) or []
    if not ids:
        return esc
    ph = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT id, nome, id_associacao FROM academias WHERE id IN ({ph}) ORDER BY nome",
                tuple(ids))
    esc["academias"] = cur.fetchall()
    aid = request.values.get("academia_id", type=int)
    if aid not in ids:
        aid = ids[0]
    esc["academia_id"] = aid
    esc["id_assoc"] = next((a["id_associacao"] for a in esc["academias"] if a["id"] == aid), None)
    esc["pode_editar"] = current_user.has_role("admin")
    # A academia marca o próprio exame (programa e preços seguem os da associação).
    esc["pode_criar"] = bool(esc["id_assoc"]) and _tem("gestor_academia", "admin")
    return esc


def _ids_academias_escopo(esc):
    """Academias cujos alunos entram nas listas: a escolhida ou todas."""
    if esc.get("academia_id"):
        return [esc["academia_id"]]
    return [a["id"] for a in esc["academias"]]


def _exige_escopo(cur):
    esc = _escopo(cur)
    if esc is None:
        flash("Acesso restrito à gestão da academia ou da associação.", "danger")
        return None, redirect(url_for("painel.home"))
    return esc, None


def _alunos_do_usuario(cur):
    """Alunos que o usuário acompanha no modo aluno/responsável."""
    modo = session.get("modo_painel") or ""
    if current_user.has_role("responsavel") and (modo == "responsavel" or not current_user.has_role("aluno")):
        cur.execute(
            """SELECT a.* FROM alunos a JOIN responsavel_alunos ra ON ra.aluno_id = a.id
               WHERE ra.usuario_id = %s AND a.ativo = 1 ORDER BY a.nome""", (current_user.id,))
        return cur.fetchall(), "responsavel"
    if current_user.has_role("aluno") or current_user.has_role("admin"):
        cur.execute("SELECT * FROM alunos WHERE usuario_id = %s", (current_user.id,))
        return cur.fetchall(), "aluno"
    return [], modo


def _aluno_alvo(cur):
    alunos, modo = _alunos_do_usuario(cur)
    if not alunos:
        return None, alunos, modo
    aid = request.values.get("aluno_id", type=int)
    aluno = next((a for a in alunos if a["id"] == aid), None) or alunos[0]
    return aluno, alunos, modo


# ------------------------------------------------------------------ evento
def _evento(cur, evento_id):
    try:
        cur.execute("SELECT * FROM eventos_competicoes WHERE id = %s AND exame_faixa = 1",
                    (evento_id,))
        return cur.fetchone()
    except Exception:
        return None


def _data_exame(ev):
    """Dia da prova. Exame anterior à EXF-02 cai no fim das inscrições."""
    d = ev.get("exame_data_prova") or ev.get("data_fim")
    return d.date() if isinstance(d, datetime) else d


def _hora_prova(ev):
    d = ev.get("exame_data_prova")
    return d.strftime("%H:%M") if isinstance(d, datetime) and (d.hour or d.minute) else None


def _prazo_pagamento(ev):
    """Vencimento da fatura: o prazo cadastrado, ou o dia da prova."""
    d = ev.get("exame_prazo_pagamento") or _data_exame(ev) or date.today()
    return d.date() if isinstance(d, datetime) else d


def _encerrado(ev):
    fim = ev.get("data_fim")
    return (ev.get("status") == "finalizado") or bool(fim and fim < datetime.now())


def _ainda_nao_abriu(ev):
    """Antes da abertura (data_inicio) ninguém se inscreve."""
    ini = ev.get("data_inicio")
    return bool(ini and ini > datetime.now())


def _aderiu(cur, evento_id, academia_id):
    cur.execute("SELECT aderiu FROM eventos_competicoes_adesao WHERE evento_id = %s AND academia_id = %s",
                (evento_id, academia_id))
    r = cur.fetchone()
    return bool(r and r.get("aderiu"))


def _garantir_adesao(cur, evento_id, academia_id):
    """Gestor que inscreve aluno da academia está aderindo ao exame."""
    cur.execute("SELECT id FROM eventos_competicoes_adesao WHERE evento_id = %s AND academia_id = %s",
                (evento_id, academia_id))
    r = cur.fetchone()
    if r:
        cur.execute("UPDATE eventos_competicoes_adesao SET aderiu = 1 WHERE id = %s", (r["id"],))
    else:
        cur.execute("INSERT INTO eventos_competicoes_adesao (evento_id, academia_id, aderiu) VALUES (%s,%s,1)",
                    (evento_id, academia_id))


def _inscricao_do_aluno(cur, evento_id, aluno_id):
    cur.execute(
        """SELECT * FROM eventos_competicoes_inscricoes
           WHERE evento_id = %s AND aluno_id = %s AND status = 'enviada' ORDER BY id LIMIT 1""",
        (evento_id, aluno_id))
    return cur.fetchone()


def _dados(insc):
    try:
        return json.loads(insc.get("dados_form") or "{}") or {}
    except (TypeError, ValueError):
        return {}


def _gerar_fatura(cur, ev, aluno, promo, inscricao_id):
    """Cobrança avulsa do exame: "Exame de faixa — Laranja → Verde".

    Só sai quando o exame pede fatura, a promoção tem valor e a academia usa
    o módulo financeiro — academia só acadêmica não tem onde cobrar. Devolve
    o id da cobrança ou None.
    """
    if not ev.get("exame_gera_fatura", 1):
        return None
    valor = float(promo.get("valor") or 0)
    if valor <= 0:
        return None
    try:
        from utils.modulos import tem_financeiro
        if not tem_financeiro(aluno["id_academia"]):
            return None
    except Exception:
        pass
    descricao = f"Exame de faixa — {promo['de']} → {promo['para']}"
    cur.execute(
        """INSERT INTO cobranca_avulsa
               (aluno_id, id_academia, descricao, valor, data_vencimento, status, observacoes, criado_por)
           VALUES (%s,%s,%s,%s,%s,'pendente',%s,%s)""",
        (aluno["id"], aluno["id_academia"], descricao[:255], valor, _prazo_pagamento(ev),
         f"{ev['nome']} · inscrição #{inscricao_id}", current_user.id))
    cobranca_id = cur.lastrowid
    _emitir_online(cur, cobranca_id)
    return cobranca_id


# Inclusão em lote: cada emissão no gateway leva de 1 a 3 s. Passado este
# tempo, as faturas seguintes ficam sem PIX e ele sai quando o aluno abrir
# "Meu exame" (ou pela academia, no financeiro).
_ORCAMENTO_EMISSAO_S = 40


def _emitir_online(cur, cobranca_id, forcar=False):
    """Emite o PIX/link da fatura do exame no gateway ativo da academia.

    Sem gateway, ou se o gateway recusar, a fatura fica como está — a academia
    ainda pode emitir pelo financeiro. Devolve True quando emitiu.
    """
    import time
    inicio = getattr(request, "_exf_emissao_inicio", None) if request else None
    if inicio is None and request:
        request._exf_emissao_inicio = inicio = time.monotonic()
    if not forcar and inicio is not None and time.monotonic() - inicio > _ORCAMENTO_EMISSAO_S:
        return False
    try:
        from blueprints.financeiro import routes as fin
        cur.execute(
            """SELECT ca.id, ca.valor, ca.data_vencimento, ca.descricao, ca.status, ca.id_academia,
                      ca.asaas_payment_id, a.nome, a.cpf, a.email, a.telefone,
                      a.responsavel_financeiro_nome, a.responsavel_financeiro_cpf,
                      a.responsavel_financeiro_telefone,
                      a.cep, a.rua, a.numero, a.complemento, a.bairro, a.cidade, a.estado
               FROM cobranca_avulsa ca JOIN alunos a ON a.id = ca.aluno_id
               WHERE ca.id = %s""", (cobranca_id,))
        ca = cur.fetchone()
        if not ca or ca["status"] not in ("pendente", "atrasado") or ca.get("asaas_payment_id"):
            return False
        cfg = fin._gateway_config_academia(ca["id_academia"])
        if not fin._gateway_ativo(cfg):
            return False
        nome, cpf, tel = fin._dados_pagador(ca)
        r = fin._emitir_cobranca_online(
            cfg, "PIX", nome=nome, cpf=cpf, email=ca.get("email"), telefone=tel,
            valor=ca["valor"], vencimento=ca["data_vencimento"],
            descricao=f"{ca['descricao']} - {ca['nome']}", origem="avulsa",
            registro_id=cobranca_id, endereco=fin._endereco_aluno(ca))
        cur.execute(
            """UPDATE cobranca_avulsa
               SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                   asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s, gateway=%s
               WHERE id=%s""",
            (r["payment_id"], r["tipo"], r["boleto_url"], r["pix_qrcode"], r["pix_copia_cola"],
             r["gateway"], cobranca_id))
        return True
    except Exception:
        current_app.logger.exception("Exame de faixa: PIX da fatura %s não emitido", cobranca_id)
        return False


def _criar_inscricao(cur, ev, aluno, sit, extra=None):
    """Inscreve o aluno no exame e, se o exame pedir, gera a fatura."""
    p = sit["promocao"]
    dados = dict(extra or {})
    dados["nome"] = aluno.get("nome")
    dados["exame_faixa"] = {
        "programa_id": p["id"],
        "graduacao_de_id": p["graduacao_de_id"],
        "graduacao_para_id": p["graduacao_para_id"],
        "de": p["de"], "para": p["para"],
        "valor": float(p["valor"]) if p.get("valor") is not None else None,
        "idade_no_exame": sit.get("idade"),
        "situacao": sit["status"],
        "salto": p.get("salto_motivo"),
        "escolha_professor": bool(p.get("escolha")),
        "pendencias": sit["pendencias"],
        "avisos": sit["avisos"],
    }
    cur.execute(
        """INSERT INTO eventos_competicoes_inscricoes
               (evento_id, academia_id, aluno_id, usuario_inscricao_id, dados_form, status, data_envio)
           VALUES (%s,%s,%s,%s,%s,'enviada',NOW())""",
        (ev["id"], aluno["id_academia"], aluno["id"], current_user.id,
         json.dumps(dados, ensure_ascii=False, default=str)))
    inscricao_id = cur.lastrowid
    cobranca_id = _gerar_fatura(cur, ev, aluno, p, inscricao_id)
    if cobranca_id:
        dados["exame_faixa"]["cobranca_id"] = cobranca_id
        dados["exame_faixa"]["vencimento"] = str(_prazo_pagamento(ev))
        cur.execute("UPDATE eventos_competicoes_inscricoes SET dados_form = %s WHERE id = %s",
                    (json.dumps(dados, ensure_ascii=False, default=str), inscricao_id))
    return inscricao_id, cobranca_id


def _situacao_pagamento(cur, inscricoes):
    """Anota `pagamento` ({status, rotulo, cor, vencimento}) em cada inscrição."""
    ids = {}
    for r in inscricoes:
        cid = ((r.get("exame") or {}).get("cobranca_id"))
        if cid:
            ids[cid] = r
    for r in inscricoes:
        r["pagamento"] = None
    if not ids:
        return
    ph = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT id, status, data_vencimento, asaas_payment_id FROM cobranca_avulsa WHERE id IN ({ph})",
                tuple(ids))
    hoje = date.today()
    for c in cur.fetchall():
        st = c["status"]
        if st == "pendente" and c["data_vencimento"] and c["data_vencimento"] < hoje:
            st = "atrasado"
        rot, cor = {"pago": ("Pago", "success"), "pendente": ("A pagar", "warning"),
                    "atrasado": ("Em atraso", "danger"), "cancelado": ("Cancelada", "info")}[st]
        ids[c["id"]]["pagamento"] = {"status": st, "rotulo": rot, "cor": cor, "id": c["id"],
                                     "vencimento": c["data_vencimento"],
                                     "online": bool(c.get("asaas_payment_id"))}


# -------------------------------------------------------------- navegação
def _abas(esc, ativa):
    kw = {"academia_id": esc["academia_id"]} if esc.get("academia_id") and not esc["ve_todas"] else {}
    return {"ativa": ativa, "kw": kw}


@bp_exame_faixa.route("/")
@login_required
def index():
    if _tem(*PAPEIS_GESTAO) and session.get("modo_painel") not in ("aluno", "responsavel"):
        return redirect(url_for("exame_faixa.alunos", **request.args))
    return redirect(url_for("exame_faixa.estudo", **request.args))


# ---------------------------------------------------------------- programa
def _material_da_promocao(cur, esc, prog, idx, videos, promocao=None):
    """Tudo o que a apostila de uma promoção mostra: teoria, técnicas (com QR
    dos vídeos), revisão das faixas anteriores, katas e documentos.

    `promocao` entra quando o aluno vai saltar faixa: ali o conteúdo já vem
    somado (branca → azul traz também cinza e cinza/azul), e a revisão precisa
    começar antes da faixa dele, não antes da faixa de destino.
    """
    atual = promocao or prog[idx]
    conhecimento, tecnicas = exf.blocos_estudo(atual)
    acumulado = [{"nome": g["nome"], "n": len(exf.itens_acumulados(prog, idx, g["chave"]))}
                 for g in exf.GRUPOS]
    # Revisão: o que veio das faixas anteriores e também entra no sorteio.
    anteriores = []
    # Num salto, o material já cobre da faixa do aluno até o destino: a revisão
    # começa antes da faixa dele, senão repetiria o que está logo acima.
    i_inicio = atual.get("indice_de", idx)
    if i_inicio > 0:
        for g in exf.GRUPOS:
            if g["chave"] == "teoria":
                continue
            its = [exf.rotulo_item(g, it)
                   for it in exf.itens_acumulados(prog, i_inicio - 1, g["chave"])]
            anteriores.append({"nome": g["nome"], "significado": g.get("significado"),
                               "itens": its, "n": len(its)})
    # Material: vídeo de cada técnica (com QR para a apostila), katas e
    # documentos da associação.
    exf.anotar_videos(tecnicas, videos, com_qr=True)
    cob, _extra = exf.katas_da_promocao(atual)
    chaves_cob = {k["chave"] for k in cob}
    katas = []
    for k in exf.KATAS:   # cópia: a lista do módulo é compartilhada entre requisições
        v = videos.get(exf.chave_video(k["chave"]))
        katas.append(dict(k, video=v, qr=exf.qr_svg(v["url"]) if v else None))
    katas_cobrados = [k for k in katas if k["chave"] in chaves_cob]
    katas_extra = [k for k in katas if k["chave"] not in chaves_cob]
    # Kata só entra no material a partir da faixa Verde (ou quando a promoção cobra).
    i_verde = next((i for i, p in enumerate(prog) if exf._norm(p["para"]) == "verde"), None)
    mostra_katas = bool(katas_cobrados) or (i_verde is not None and idx >= i_verde)
    return {
        "atual": atual, "conhecimento": conhecimento, "tecnicas": tecnicas,
        "termos_do_material": exf.termos_do_material(conhecimento, tecnicas),
        "acumulado": acumulado, "anteriores": anteriores,
        "katas_cobrados": katas_cobrados, "katas_extra": katas_extra, "mostra_katas": mostra_katas,
        "documentos": exf.documentos_da_associacao(cur, esc["id_assoc"], atual["id"]),
    }


def _marca_da_apostila(cur, esc):
    """Logo e nome do cabeçalho: os da academia em foco; sem logo, os da associação."""
    from utils.contexto_logo import buscar_logo_url
    marca = {"logo": None, "nome": None}
    if esc.get("academia_id"):
        cur.execute("SELECT nome FROM academias WHERE id = %s", (esc["academia_id"],))
        marca["nome"] = (cur.fetchone() or {}).get("nome")
        marca["logo"] = buscar_logo_url("academia", esc["academia_id"])
    if not marca["logo"] and esc.get("id_assoc"):
        cur.execute("SELECT nome FROM associacoes WHERE id = %s", (esc["id_assoc"],))
        nome_assoc = (cur.fetchone() or {}).get("nome")
        marca["nome"] = marca["nome"] or nome_assoc
        marca["logo"] = buscar_logo_url("associacao", esc["id_assoc"])
    return marca


def _item_apostila(aluno_id, nome, promocao):
    """Uma linha do diálogo de impressão: quem é e para que faixa vai."""
    p = promocao or {}
    return {"id": aluno_id, "nome": nome, "de": p.get("de"), "para": p.get("para"),
            "salto": bool(p.get("salto"))}


def _alunos_para_apostila(cur, esc, prog):
    """Alunos da academia em foco com a promoção do próximo exame de cada um.

    Só com academia escolhida: a apostila sai com o nome do aluno e o material
    da faixa dele, e a lista de uma associação inteira não caberia no modal.
    """
    if not (esc.get("academia_id") and prog):
        return []
    alunos = _alunos_com_situacao(cur, [esc["academia_id"]], prog)
    return [a for a in alunos if a["sit"].get("promocao")]


@bp_exame_faixa.route("/programa")
@login_required
def programa():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        prog = exf.programa(cur, esc["id_assoc"])
        idx = request.args.get("p", type=int)
        if idx is None or not (0 <= idx < len(prog)):
            idx = 0
        videos = exf.videos_da_associacao(cur, esc["id_assoc"])
        material = _material_da_promocao(cur, esc, prog, idx, videos) if prog else {"atual": None}
        marca = _marca_da_apostila(cur, esc)
        n_videos = {p["id"]: 0 for p in prog}
        for p in prog:
            nomes = set(exf.itens(p, "nage")) | set(exf.itens(p, "katame"))
            n_videos[p["id"]] = (sum(1 for n in nomes if isinstance(n, str) and exf.chave_video(n) in videos), len(nomes))
        return render_template(
            "exame_faixa/programa.html", esc=esc, abas=_abas(esc, "programa"),
            prog=prog, idx=idx, marca=marca, n_videos=n_videos,
            alunos_apostila=_alunos_para_apostila(cur, esc, prog),
            ap_acao=url_for("exame_faixa.programa_apostilas"),
            ap_ocultos={"academia_id": esc.get("academia_id") or "", "p": idx},
            ap_lista=[_item_apostila(a["id"], a["nome"], a["sit"].get("promocao"))
                      for a in _alunos_para_apostila(cur, esc, prog)],
            # Material de qualquer faixa, sem depender de aluno inscrito.
            ap_faixas=[{"indice": i, "de": p["de"], "para": p["para"],
                        "n": sum(len(exf.itens(p, g["chave"]))
                                 for g in exf.GRUPOS if g["chave"] != "teoria")}
                       for i, p in enumerate(prog)],
            ap_sem_nome=True,
            hoje_txt=datetime.now().strftime("%d/%m/%Y"), **material)
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/programa/apostilas")
@login_required
def programa_apostilas():
    """Apostilas em lote, por aluno ou por faixa.

    `aluno_id` — uma apostila por aluno marcado, com o nome dele e o material
                 da faixa do próximo exame dele (salto e escolha do professor
                 inclusos).
    `faixa`    — uma apostila por promoção escolhida, sem nome de aluno. Serve
                 para imprimir o material de qualquer faixa, não só o da turma
                 que vai prestar exame.
    `acumulado=1` — cada faixa escolhida sai com o conteúdo somado desde a
                 primeira: é o material inteiro até ali, não só o que aquela
                 promoção acrescenta.

    Sem nada marcado a tela do programa imprime ela mesma, sem nome.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        prog = exf.programa(cur, esc["id_assoc"])
        voltar = url_for("exame_faixa.programa", p=request.args.get("p", type=int),
                         academia_id=esc.get("academia_id"))
        pedidos = set(request.args.getlist("aluno_id", type=int))
        escolhidos = [a for a in _alunos_para_apostila(cur, esc, prog) if a["id"] in pedidos]
        faixas = sorted({i for i in request.args.getlist("faixa", type=int)
                         if 0 <= i < len(prog)})
        acumulado = request.args.get("acumulado") == "1"
        if not escolhidos and not faixas:
            flash("Marque ao menos um aluno ou uma faixa para imprimir.", "warning")
            return redirect(voltar)
        pares = [(a, a["sit"]["promocao"]) for a in escolhidos]
        # Faixa sem aluno: a apostila sai sem nome, com o material daquela
        # promoção ou, no acumulado, de todas até ela.
        pares += [(None, exf.promocao_acumulada(prog, i) if acumulado else prog[i])
                  for i in faixas]
        apostilas = _montar_apostilas(cur, esc, prog, pares)
        return render_template(
            "exame_faixa/apostilas.html", esc=esc, apostilas=apostilas, voltar=voltar,
            marca=_marca_da_apostila(cur, esc), hoje_txt=datetime.now().strftime("%d/%m/%Y"))
    finally:
        cur.close()
        conn.close()


def _alunos_do_exame(cur, esc, ev, prog):
    """(aluno, promoção) de todo mundo que vai prestar este exame, na ordem.

    Inscritos primeiro — a promoção vem da inscrição, que é a que vale na prova
    e pode ter sido mudada pelo professor. Depois os candidatos da academia em
    foco, ainda não inscritos: na véspera do exame o professor quer o material
    de quem VAI prestar, e esperar a inscrição ficar pronta para poder imprimir
    é o que fazia a impressão sair vazia.
    """
    saida, vistos = [], set()
    for r in _inscritos_da_banca(cur, esc, ev, prog):
        if r["promocao"] and r["aluno_id"] not in vistos:
            vistos.add(r["aluno_id"])
            saida.append(({"id": r["aluno_id"], "nome": r["nome"], "inscrito": True},
                          r["promocao"]))
    if esc.get("academia_id") and prog:
        for a in _alunos_com_situacao(cur, [esc["academia_id"]], prog,
                                      data_ref=_data_exame(ev)):
            if a["id"] in vistos or not a["sit"].get("promocao"):
                continue
            vistos.add(a["id"])
            saida.append(({"id": a["id"], "nome": a["nome"], "inscrito": False},
                          a["sit"]["promocao"]))
    return saida


def _montar_apostilas(cur, esc, prog, pares):
    """Uma apostila por aluno, a partir de (aluno, promoção).

    A promoção vem de fora porque cada tela sabe a sua: na do programa é a do
    próximo exame do aluno; na banca é a da inscrição, que pode ter sido
    mudada pelo professor. Nos dois casos, se houver salto, ela já traz o
    conteúdo somado das faixas puladas.
    """
    videos = exf.videos_da_associacao(cur, esc["id_assoc"])
    indice = {p["id"]: i for i, p in enumerate(prog)}
    materiais, apostilas = {}, []
    for aluno, promo in pares:
        if not promo:
            continue
        i = indice.get(promo.get("id"))
        if i is None:
            continue
        # O material de quem salta não serve para quem não salta, e o acumulado
        # não serve para quem quer só a faixa: a chave do cache leva as três
        # coisas — a promoção, de onde o conteúdo começa e se é acumulado.
        composta = promo.get("indice_de") is not None
        chave = (i, promo.get("indice_de"), bool(promo.get("acumulado")))
        if chave not in materiais:
            materiais[chave] = _material_da_promocao(
                cur, esc, prog, i, videos, promocao=promo if composta else None)
        # O cabeçalho sai da faixa do aluno: num salto, "Branca → Amarela/Laranja".
        apostilas.append(dict(materiais[chave], aluno=aluno, atual=promo))
    return apostilas


@bp_exame_faixa.route("/evento/<int:evento_id>/apostilas")
@login_required
def evento_apostilas(evento_id):
    """Apostilas dos inscritos num exame, para a banca imprimir no dia.

    A promoção sai da inscrição — é ela que vale na prova, inclusive quando o
    professor mudou a faixa de destino — e, havendo salto, o material já vem
    com as faixas puladas junto, porque é tudo isso que o aluno apresenta.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ev = _evento(cur, evento_id)
        if not _pode_banca(esc, ev):
            flash("Exame não encontrado.", "danger")
            return redirect(url_for("exame_faixa.exames"))
        prog = exf.programa(cur, ev["id_associacao"])
        voltar = url_for("exame_faixa.banca", evento_id=evento_id,
                         academia_id=esc.get("academia_id"))
        pedidos = set(request.args.getlist("aluno_id", type=int))
        todos = _alunos_do_exame(cur, esc, ev, prog)
        escolhidos = [(a, p) for a, p in todos if not pedidos or a["id"] in pedidos]
        if not escolhidos:
            flash("Ninguém com faixa definida para imprimir — nem inscrito, nem "
                  "candidato na academia escolhida.", "warning")
            return redirect(voltar)
        apostilas = _montar_apostilas(cur, esc, prog, escolhidos)
        return render_template(
            "exame_faixa/apostilas.html", esc=esc, apostilas=apostilas, voltar=voltar,
            marca=_marca_da_apostila(cur, esc), hoje_txt=datetime.now().strftime("%d/%m/%Y"))
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/programa/<int:programa_id>/editar", methods=["GET", "POST"])
@login_required
def editar_conteudo(programa_id):
    """Edita o que se cobra numa promoção: teoria e técnicas.

    Só a associação (dona do programa) edita. A prova de quem já foi sorteado
    não muda — a ficha guarda as técnicas sorteadas; o que muda é o estudo e
    os sorteios seguintes.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        prog = exf.programa(cur, esc["id_assoc"], so_ativos=False)
        idx = next((i for i, p in enumerate(prog) if p["id"] == programa_id), None)
        if idx is None:
            flash("Promoção não encontrada.", "danger")
            return redirect(url_for("exame_faixa.programa"))
        atual = prog[idx]
        # a aba "Programa" usa o índice entre as ativas
        ativos = [p for p in prog if p.get("ativo")]
        p_ativo = next((i for i, p in enumerate(ativos) if p["id"] == programa_id), 0)
        voltar = url_for("exame_faixa.programa", p=p_ativo, **_abas(esc, "programa")["kw"])
        if not esc["pode_editar"]:
            flash("Só a associação edita o conteúdo do programa.", "danger")
            return redirect(voltar)

        valores = exf.conteudo_para_form(atual["conteudo"])
        if request.method == "POST":
            valores = {c["chave"]: request.form.get(c["chave"], "") for c in exf.CAMPOS_CONTEUDO}
            conteudo, erros = exf.form_para_conteudo(request.form)
            edicao = (request.form.get("edicao") or "").strip()[:20] or None
            if erros:
                for e in erros:
                    flash(e, "danger")
            else:
                cur.execute(
                    """UPDATE exame_faixa_programa SET conteudo = %s, edicao = %s, atualizado_por = %s
                       WHERE id = %s AND id_associacao = %s""",
                    (json.dumps(conteudo, ensure_ascii=False), edicao, current_user.id,
                     programa_id, esc["id_assoc"]))
                conn.commit()
                flash(f"Conteúdo de {atual['de']} → {atual['para']} salvo.", "success")
                return redirect(voltar)
        return render_template(
            "exame_faixa/editar_conteudo.html", esc=esc, abas=_abas(esc, "programa"),
            atual=atual, prog=prog, campos=exf.CAMPOS_CONTEUDO, valores=valores, voltar=voltar,
            edicao=request.form.get("edicao", atual.get("edicao") or "") if request.method == "POST"
            else (atual.get("edicao") or ""))
    finally:
        cur.close()
        conn.close()


# ------------------------------------------------------------------ preços
@bp_exame_faixa.route("/precos", methods=["GET", "POST"])
@login_required
def precos():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        if request.method == "POST":
            if not esc["pode_editar"]:
                flash("Só a associação altera a tabela de preços.", "danger")
                return redirect(url_for("exame_faixa.precos"))
            prog = exf.programa(cur, esc["id_assoc"], so_ativos=False)
            alterados = 0
            for p in prog:
                pid = p["id"]
                # Só a linha que veio no formulário muda: um POST sem os campos
                # não pode zerar preço nem desativar promoção.
                if f"linha_{pid}" not in request.form:
                    continue

                def _num(campo, tipo=int, _pid=pid):
                    bruto = (request.form.get(f"{campo}_{_pid}") or "").strip()
                    if not bruto:
                        return None
                    if tipo is float:
                        bruto = bruto.replace("R$", "").strip()
                        if "," in bruto:  # "1.234,50" digitado à mão
                            bruto = bruto.replace(".", "").replace(",", ".")
                    try:
                        v = tipo(bruto)
                    except ValueError:
                        raise ValueError(f"{p['de']} → {p['para']}: valor inválido em {campo}")
                    if v < 0:
                        raise ValueError(f"{p['de']} → {p['para']}: {campo} não pode ser negativo")
                    return v

                try:
                    novo = (_num("valor", float), _num("idade_minima"), _num("idade_maxima"),
                            _num("carencia_meses"), 1 if request.form.get(f"ativo_{pid}") else 0)
                except ValueError as e:
                    flash(str(e), "danger")
                    return redirect(url_for("exame_faixa.precos"))
                antigo = (float(p["valor"]) if p.get("valor") is not None else None,
                          p.get("idade_minima"), p.get("idade_maxima"), p.get("carencia_meses"),
                          int(p.get("ativo") or 0))
                if novo != antigo:
                    cur.execute(
                        """UPDATE exame_faixa_programa
                           SET valor = %s, idade_minima = %s, idade_maxima = %s, carencia_meses = %s,
                               ativo = %s, atualizado_por = %s
                           WHERE id = %s AND id_associacao = %s""",
                        novo + (current_user.id, pid, esc["id_assoc"]))
                    alterados += 1
            conn.commit()
            flash(f"Tabela atualizada ({alterados} faixa{'s' if alterados != 1 else ''} alterada"
                  f"{'s' if alterados != 1 else ''}). Inscrições já feitas mantêm o valor da época.",
                  "success")
            return redirect(url_for("exame_faixa.precos"))

        prog = exf.programa(cur, esc["id_assoc"], so_ativos=False)
        atualizacao = None
        if prog:
            ult = max(prog, key=lambda p: p.get("atualizado_em") or datetime.min)
            if ult.get("atualizado_por"):
                cur.execute("SELECT nome FROM usuarios WHERE id = %s", (ult["atualizado_por"],))
                atualizacao = {"em": ult.get("atualizado_em"),
                               "por": (cur.fetchone() or {}).get("nome")}
        return render_template("exame_faixa/precos.html", esc=esc, abas=_abas(esc, "precos"),
                               prog=prog, atualizacao=atualizacao)
    finally:
        cur.close()
        conn.close()


# -------------------------------------------------------------------- aptos
def _alunos_com_situacao(cur, ids_academia, prog, data_ref=None):
    """Alunos ativos das academias, cada um com a situação para o exame."""
    if not ids_academia:
        return []
    ph = ",".join(["%s"] * len(ids_academia))
    # Entra quem tem a academia como principal e quem está vinculado a ela
    # (alunos_academias). O aluno aparece pela academia do escopo — é ela que
    # inscreve e cobra. Se as duas estão no escopo, vale a principal.
    cur.execute(
        f"""SELECT a.id, a.nome, a.foto, a.data_nascimento, a.graduacao_id, a.ultimo_exame_faixa,
                   ac.id AS id_academia, ac.nome AS academia_nome, g.faixa, g.graduacao AS grau
            FROM alunos a
            JOIN academias ac ON ac.id IN ({ph})
                 AND (ac.id = a.id_academia
                      OR EXISTS (SELECT 1 FROM alunos_academias aa
                                 WHERE aa.aluno_id = a.id AND aa.academia_id = ac.id))
            LEFT JOIN graduacao g ON g.id = a.graduacao_id
            WHERE a.ativo = 1 AND a.status = 'ativo'
            ORDER BY a.nome, (ac.id = a.id_academia) DESC""", tuple(ids_academia))
    vistos = set()
    alunos = []
    for a in cur.fetchall():
        if a["id"] not in vistos:
            vistos.add(a["id"])
            alunos.append(a)
    ids = [a["id"] for a in alunos]
    hist = exf.ultimas_do_historico(cur, ids)
    atrasos = exf.mensalidades_em_atraso(cur, ids, data_ref)
    laranja = exf.marcas_inicio_laranja(cur, ids)
    destinos = exf.destinos_escolhidos(cur, ids)
    liberados = exf.liberacoes(cur, ids)
    # Faixa de judô de cada um, de uma vez (o exame é só de judô).
    from utils import graduacao_modalidade as grad_mod
    mod_prog = exf.modalidade_do_programa(cur, prog)
    faixas_mod = grad_mod.faixas_por_modalidade(cur, ids) if mod_prog else {}
    for a in alunos:
        a["_liberacao"] = liberados.get(a["id"])
        if mod_prog:
            a["_faixa_prog"] = next((f for f in faixas_mod.get(a["id"], [])
                                     if f["modalidade_id"] == mod_prog), None)
        a["_ultima_hist"] = hist.get(a["id"])
        a["_inicio_laranja"] = laranja.get(a["id"])
        a["_destino"] = destinos.get(a["id"])
        a["sit"] = exf.situacao(cur, a, prog, data_ref=data_ref, atrasos=atrasos)
        a["faixa_nome"] = exf.nome_faixa(a.get("faixa")) if a.get("faixa") else "—"
    return alunos


def _proximo_exame(cur, esc):
    """O exame da associação com prova de hoje em diante, o mais próximo.

    A lista de aptos confere idade e carência na data dessa prova — é a mesma
    conta que a inclusão faz — e mostra quem da academia já está inscrito.
    """
    if not esc.get("id_assoc"):
        return None
    filtro, fparams = _filtro_dono(esc)
    try:
        cur.execute(
            f"""SELECT ec.* FROM eventos_competicoes ec
               WHERE ec.id_associacao = %s AND ec.exame_faixa = 1
                 AND COALESCE(ec.status, '') <> 'finalizado'
                 AND DATE(COALESCE(ec.exame_data_prova, ec.data_fim)) >= CURDATE(){filtro}
               ORDER BY COALESCE(ec.exame_data_prova, ec.data_fim) LIMIT 1""",
            (esc["id_assoc"],) + fparams)
        ev = cur.fetchone()
    except Exception:
        current_app.logger.exception("Próximo exame de faixa")
        return None
    if not ev:
        return None
    ev["data_exame"] = _data_exame(ev)
    ev["hora_prova"] = _hora_prova(ev)
    ev["prazo_pagamento"] = _prazo_pagamento(ev)
    ev["encerrado"] = _encerrado(ev)
    ev["nao_abriu"] = _ainda_nao_abriu(ev)
    ids = _ids_academias_escopo(esc)
    ev["inscritos_ids"] = set()
    if ids:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(f"""SELECT aluno_id FROM eventos_competicoes_inscricoes
                        WHERE evento_id = %s AND status = 'enviada' AND academia_id IN ({ph})""",
                    (ev["id"],) + tuple(ids))
        ev["inscritos_ids"] = {r["aluno_id"] for r in cur.fetchall()}
    return ev


def _requisitos(sit):
    """Idade e carência de uma linha da lista, prontas para a tela.

    `ok` é True/False, ou None quando falta o dado no cadastro.
    """
    p = sit["promocao"]
    ref = sit.get("data_ref") or date.today()
    idade = sit.get("idade")
    if p.get("salto"):
        idade_ok, idade_txt = True, f"{idade} anos · {p.get('salto_motivo')}" if idade is not None else p.get("salto_motivo")
    elif idade is None:
        idade_ok, idade_txt = None, "Sem data de nascimento"
    else:
        mn, mx = p.get("idade_minima"), p.get("idade_maxima")
        idade_ok = not ((mn and idade < int(mn) and not sit.get("idade_dezembro")) or (mx and idade > int(mx)))
        idade_txt = f"{idade} anos · exigido {p.get('idade_txt') or '—'}"
        if sit.get("idade_civil_seguinte"):
            ano_s, civil = sit["idade_civil_seguinte"]
            idade_txt += f" · idade civil em {ano_s}: {civil} anos (exame de dezembro)"

    car = int(p.get("carencia_meses") or 0)
    ult = exf._como_data(sit.get("ultima_graduacao"))
    if not car:
        c = {"ok": True, "pct": 100, "txt": "Sem carência"}
    elif not ult:
        c = {"ok": None, "pct": 0, "txt": "Sem data da faixa atual"}
    else:
        d = relativedelta(ref, ult)
        meses = max(0, d.years * 12 + d.months)
        ok = ref >= ult + relativedelta(months=car)
        c = {"ok": ok, "pct": 100 if ok else min(99, meses * 100 // car),
             "txt": f"Carência cumprida · {meses} {'mês' if meses == 1 else 'meses'}" if ok
                    else f"{meses} de {car} meses na faixa"}
    return {"idade_ok": idade_ok, "idade_txt": idade_txt,
            "car_ok": c["ok"], "car_pct": c["pct"], "car_txt": c["txt"]}


def _regra_e_liberacao(a):
    """Duas frases para a lista impressa: por que o aluno vai para aquela faixa
    e quando ele está liberado ("faz 6 anos em 14/03/2027 — liberado a partir
    de 14/03/2027")."""
    sit, p = a["sit"], a["sit"]["promocao"]
    nasc = exf._como_data(a.get("data_nascimento"))
    ref = exf._como_data(sit.get("data_ref")) or date.today()
    if p.get("escolha"):
        regra = f"{p.get('escolha_motivo') or 'Escolha do professor'}."
    elif p.get("salto"):
        regra = f"{p.get('salto_motivo')}."
    elif sit.get("idade_civil_seguinte"):
        ano_s, civil = sit["idade_civil_seguinte"]
        car = p.get("carencia_meses")
        regra = (f"Idade civil em {ano_s}: {civil} anos — {p.get('para')} liberada no exame de dezembro "
                 "(final do ano)." + (f" Carência de {car} meses na faixa." if car else ""))
    else:
        car = p.get("carencia_meses")
        regra = f"Idade {p.get('idade_txt') or 'livre'}; " + (f"carência de {car} meses na faixa." if car else "sem carência.")

    st = sit["status"]
    if sit.get("liberado"):
        lib = sit["liberado"]
        falta = [x.replace("Liberado pela academia sem cumprir: ", "") for x in sit.get("avisos", [])
                 if x.startswith("Liberado pela academia sem cumprir")]
        liberacao = "Liberado pela academia" + (f" ({lib.get('motivo')})" if lib.get("motivo") else "") \
            + (f" sem cumprir: {'; '.join(falta)}" if falta else "") + "."
    elif st == "apto" and (sit.get("idade_dezembro") or sit.get("salto_dezembro")):
        liberacao = "Apto: liberado no exame de dezembro (final do ano)."
    elif st == "apto":
        liberacao = "Liberado: cumpre idade e carência."
    elif st == "aguardando":
        partes = []
        mn = p.get("idade_minima")
        if mn and nasc and not p.get("salto") and (sit.get("idade") or 0) < int(mn):
            partes.append(f"faz {int(mn)} anos em {(nasc + relativedelta(years=int(mn))):%d/%m/%Y}")
        dc = exf._como_data(sit.get("data_carencia"))
        if dc and ref < dc:
            partes.append(f"completa {p.get('carencia_meses')} meses na faixa em {dc:%d/%m/%Y}")
        if not partes:
            partes = [x for x in sit.get("pendencias", [])]
        el = exf._como_data(sit.get("data_elegivel"))
        liberacao = " · ".join(partes) + (f" — liberado a partir de {el:%d/%m/%Y}." if el else ".")
        liberacao = liberacao[:1].upper() + liberacao[1:]
    elif st == "verificar":
        liberacao = "Falta no cadastro: " + "; ".join(sit.get("pendencias", [])) + "."
    else:
        liberacao = "; ".join(sit.get("pendencias", [])) + "."
    if sit.get("atrasos"):
        liberacao += f" {sit['atrasos']} mensalidade{'s' if sit['atrasos'] != 1 else ''} em atraso."
    return regra, liberacao


@bp_exame_faixa.route("/alunos")
@login_required
def alunos():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        prog = exf.programa(cur, esc["id_assoc"])
        proximo = _proximo_exame(cur, esc) if prog else None
        data_ref = proximo["data_exame"] if proximo else None
        todos = (_alunos_com_situacao(cur, _ids_academias_escopo(esc), prog, data_ref=data_ref)
                 if prog else [])
        com_exame = [a for a in todos if a["sit"]["promocao"]]
        for a in com_exame:
            a["req"] = _requisitos(a["sit"])
            a["regra_txt"], a["liberacao_txt"] = _regra_e_liberacao(a)
            a["inscrito"] = bool(proximo and a["id"] in proximo["inscritos_ids"])
        contagem = {k: sum(1 for a in com_exame if a["sit"]["status"] == k)
                    for k in ("apto", "aguardando", "verificar", "fora_idade")}
        contagem["salto"] = sum(1 for a in com_exame if a["sit"]["promocao"].get("salto"))
        contagem["aptos_fora"] = sum(1 for a in com_exame
                                     if a["sit"]["status"] == "apto" and not a["inscrito"])
        fora = {"sem_faixa": sum(1 for a in todos if a["sit"]["status"] == "sem_faixa"),
                "sem_programa": sum(1 for a in todos if a["sit"]["status"] == "sem_programa")}

        f_status = request.args.get("status") or ""
        f_prom = request.args.get("promocao", type=int)
        busca = (request.args.get("q") or "").strip().lower()
        lista = com_exame
        if f_status == "salto":
            lista = [a for a in lista if a["sit"]["promocao"].get("salto")]
        elif f_status in contagem:
            lista = [a for a in lista if a["sit"]["status"] == f_status]
        if f_prom:
            lista = [a for a in lista if a["sit"]["promocao"]["id"] == f_prom]
        if busca:
            lista = [a for a in lista if busca in (a["nome"] or "").lower()]

        # Um bloco por promoção, na ordem do programa. A promoção com salto
        # (Branca → Azul) é outra promoção: entra no bloco da faixa de destino.
        grupos, por_chave = [], {}
        ordem = {p["id"]: i for i, p in enumerate(prog)}
        for a in sorted(lista, key=lambda a: (ordem.get(a["sit"]["promocao"]["id"], 999),
                                              a["sit"]["promocao"]["de"], (a["nome"] or "").lower())):
            p = a["sit"]["promocao"]
            chave = (p["de"], p["para"])
            if chave not in por_chave:
                por_chave[chave] = {"promocao": p, "alunos": []}
                grupos.append(por_chave[chave])
            por_chave[chave]["alunos"].append(a)
        for g in grupos:
            g["aptos"] = sum(1 for a in g["alunos"] if a["sit"]["status"] == "apto")

        pode_inscrever = bool(proximo and esc.get("academia_id")
                              and not proximo["encerrado"] and not proximo["nao_abriu"])
        return render_template(
            "exame_faixa/alunos.html", esc=esc, abas=_abas(esc, "alunos"), prog=prog,
            alunos=lista, grupos=grupos, contagem=contagem, fora=fora, total=len(com_exame),
            proximo=proximo, pode_inscrever=pode_inscrever,
            hoje_txt=datetime.now().strftime("%d/%m/%Y %H:%M"),
            # Impressão: pela faixa atual (ordem do programa), depois idade;
            # sem idade vai para o fim da faixa, e o nome desempata.
            impressao=sorted(lista, key=lambda a: (
                a["sit"].get("indice_natural") if a["sit"].get("indice_natural") is not None else 999,
                a["sit"].get("idade") if a["sit"].get("idade") is not None else 999,
                (a.get("nome") or "").lower())), pode_liberar=_pode_liberar(esc),
            f_status=f_status, f_prom=f_prom, busca=request.args.get("q") or "",
            filtrado=bool(f_status or f_prom or busca))
    finally:
        cur.close()
        conn.close()


# ------------------------------------------------------------------- exames
def _fase_do_exame(ev):
    """Em que pé está o exame: `fase` (rótulo, cor), `etapas` e `finalizado`.

    Finalizado = prova já passou e a banca fechou todas as fichas (ou passou
    um mês da prova, para ausência sem ficha não prender o exame na lista).
    """
    hoje = date.today()
    d = ev.get("data_exame")
    passou = bool(d and d < hoje)
    fechou = (ev.get("inscritos") or 0) <= (ev.get("avaliados") or 0)
    ev["finalizado"] = (ev.get("status") == "finalizado"
                        or (passou and (fechou or (hoje - d).days > 30)))
    if ev["nao_abriu"]:
        ev["fase"] = (f"Inscrições abrem em {ev['data_inicio']:%d/%m}", "info")
    elif not ev["encerrado"]:
        ev["fase"] = ("Inscrições abertas", "success")
    elif d and d > hoje:
        ev["fase"] = ("Aguardando a prova", "warning")
    elif ev["finalizado"]:
        ev["fase"] = ("Encerrado", "info")
    else:
        ev["fase"] = ("Banca em andamento", "primary")

    def estado(feito, agora):
        return "feito" if feito else ("agora" if agora else "depois")
    fim = ev.get("data_fim")
    prazo = ev.get("prazo_pagamento")
    ev["etapas"] = [
        {"nome": "Inscrições",
         "txt": (f"até {fim:%d/%m}" if fim else "—") if not ev["encerrado"] else "encerradas",
         "estado": estado(ev["encerrado"], not ev["nao_abriu"])},
        {"nome": "Pagamento", "txt": f"até {prazo:%d/%m}" if prazo else "—",
         "estado": estado(bool(prazo and prazo < hoje), ev["encerrado"] and not (prazo and prazo < hoje))},
        {"nome": "Prova",
         "txt": (f"{d:%d/%m}" + (f" às {ev['hora_prova']}" if ev.get("hora_prova") else "")) if d else "—",
         "estado": estado(passou and fechou, bool(d and d <= hoje))},
        {"nome": "Promoção",
         "txt": (f"{ev['a_promover']} a promover" if ev.get("a_promover") else
                 ("faixas registradas" if ev.get("aprovados") else "após a banca")),
         "estado": estado(passou and fechou and not ev.get("a_promover"), bool(ev.get("a_promover")))},
    ]
    return ev


@bp_exame_faixa.route("/exames")
@login_required
def exames():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        eventos = []
        if esc["id_assoc"]:
            ids = _ids_academias_escopo(esc) or [0]
            ph = ",".join(["%s"] * len(ids))
            filtro, fparams = _filtro_dono(esc)
            try:
                cur.execute(
                    f"""SELECT ec.*,
                           (SELECT COUNT(*) FROM eventos_competicoes_inscricoes i
                             WHERE i.evento_id = ec.id AND i.status = 'enviada'
                               AND i.academia_id IN ({ph})) AS inscritos,
                           (SELECT COUNT(*) FROM exame_faixa_avaliacao av
                             JOIN eventos_competicoes_inscricoes i ON i.id = av.inscricao_id
                             WHERE av.evento_id = ec.id AND av.resultado IN ('aprovado','reprovado')
                               AND i.academia_id IN ({ph})) AS avaliados,
                           (SELECT COUNT(*) FROM exame_faixa_avaliacao av
                             JOIN eventos_competicoes_inscricoes i ON i.id = av.inscricao_id
                             WHERE av.evento_id = ec.id AND av.resultado = 'aprovado'
                               AND i.academia_id IN ({ph})) AS aprovados,
                           (SELECT COUNT(*) FROM exame_faixa_avaliacao av
                             JOIN eventos_competicoes_inscricoes i ON i.id = av.inscricao_id
                             WHERE av.evento_id = ec.id AND av.resultado = 'aprovado'
                               AND av.aluno_graduacao_id IS NULL
                               AND i.academia_id IN ({ph})) AS a_promover,
                           ao.nome AS dono_nome
                        FROM eventos_competicoes ec
                        LEFT JOIN academias ao ON ao.id = ec.exame_academia_id
                        WHERE ec.id_associacao = %s AND ec.exame_faixa = 1{filtro}
                        ORDER BY COALESCE(ec.exame_data_prova, ec.data_fim) DESC""",
                    tuple(ids) * 4 + (esc["id_assoc"],) + fparams)
                eventos = cur.fetchall()
            except Exception:
                current_app.logger.exception("Lista de exames de faixa")
                eventos = []
            for ev in eventos:
                ev["encerrado"] = _encerrado(ev)
                ev["data_exame"] = _data_exame(ev)
                ev["hora_prova"] = _hora_prova(ev)
                ev["prazo_pagamento"] = _prazo_pagamento(ev)
                ev["nao_abriu"] = _ainda_nao_abriu(ev)
                ev["aderiu"] = (True if esc["ve_todas"] or ev.get("exame_academia_id")
                                else _aderiu(cur, ev["id"], esc["academia_id"]))
                ev["pode_editar"] = _pode_editar_exame(esc, ev)
                _fase_do_exame(ev)
        # Faturas de cada exame (no escopo): pagas e em aberto, para o cartão.
        if eventos:
            ids_ev = [e["id"] for e in eventos]
            ids_ac = _ids_academias_escopo(esc) or [0]
            cur.execute(
                f"""SELECT evento_id, dados_form FROM eventos_competicoes_inscricoes
                    WHERE status = 'enviada' AND evento_id IN ({",".join(["%s"] * len(ids_ev))})
                      AND academia_id IN ({",".join(["%s"] * len(ids_ac))})""", tuple(ids_ev) + tuple(ids_ac))
            linhas = [{"evento_id": r["evento_id"], "exame": _dados(r).get("exame_faixa") or {}}
                      for r in cur.fetchall()]
            _situacao_pagamento(cur, linhas)
            por_ev = {e["id"]: e for e in eventos}
            for e in eventos:
                e["pagos"] = e["abertos"] = 0
            for r in linhas:
                st = (r["pagamento"] or {}).get("status")
                if st == "pago":
                    por_ev[r["evento_id"]]["pagos"] += 1
                elif st in ("pendente", "atrasado"):
                    por_ev[r["evento_id"]]["abertos"] += 1
        ativos = sorted([e for e in eventos if not e["finalizado"]],
                        key=lambda e: e["data_exame"] or date.max)
        encerrados = [e for e in eventos if e["finalizado"]]
        return render_template("exame_faixa/exames.html", esc=esc, abas=_abas(esc, "exames"),
                               eventos=eventos, ativos=ativos, encerrados=encerrados)
    finally:
        cur.close()
        conn.close()


# -------------------------------------------------------------------- banca
def _ve_evento(esc, ev):
    """Exame da associação do usuário; se for de uma academia, de uma das suas."""
    if not (esc and ev and esc["id_assoc"] and ev["id_associacao"] == esc["id_assoc"]):
        return False
    dono = ev.get("exame_academia_id")
    return not dono or esc["ve_todas"] or dono in [a["id"] for a in esc["academias"]]


def _pode_banca(esc, ev):
    return _ve_evento(esc, ev)


def _pode_editar_exame(esc, ev):
    """A associação edita todos; a academia, só o exame que ela mesma criou."""
    if not _ve_evento(esc, ev):
        return False
    return esc["ve_todas"] or bool(ev.get("exame_academia_id") and esc.get("pode_criar"))


def _filtro_dono(esc, alias="ec"):
    """SQL (e parâmetros) que limita aos exames que o usuário enxerga: os da
    associação e os das suas academias."""
    if esc["ve_todas"] and not esc.get("academia_id"):
        return "", ()
    ids = _ids_academias_escopo(esc) or [0]
    ph = ",".join(["%s"] * len(ids))
    return f" AND ({alias}.exame_academia_id IS NULL OR {alias}.exame_academia_id IN ({ph}))", tuple(ids)


def _bloqueio_pagamento(ev, r):
    """Por que a prova não pode ser aplicada, ou None.

    Fatura em aberto depois do prazo de pagamento — ou no dia da prova — segura
    a prova até pagar ou até a banca liberar ("Liberar prova").
    """
    pag = r.get("pagamento")
    if not pag or pag["status"] in ("pago", "cancelado"):
        return None
    if (r.get("exame") or {}).get("liberado_por"):
        return None
    hoje, prazo, prova = date.today(), _prazo_pagamento(ev), _data_exame(ev)
    if (prazo and hoje > prazo) or (prova and hoje >= prova):
        return "Fatura do exame em aberto"
    return None


def _ordenar_banca(inscritos, prog):
    ordem = {p["id"]: i for i, p in enumerate(prog)}
    return sorted(inscritos, key=lambda r: (ordem.get((r.get("promocao") or {}).get("id"), 999),
                                            (r.get("nome") or "").lower()))


def _fila(inscritos, sem=None):
    """Quem ainda faz a prova, na ordem da banca; presentes na chamada primeiro."""
    pend = [r for r in inscritos if (r.get("resultado") or "pendente") == "pendente"
            and not r.get("bloqueio") and r["inscricao_id"] != sem and r.get("promocao")]
    return [r for r in pend if r["exame"].get("presente")] + \
           [r for r in pend if not r["exame"].get("presente")]


def _inscritos_da_banca(cur, esc, ev, prog):
    """Inscritos no escopo, com pagamento, bloqueio e na ordem da banca."""
    inscritos = _inscritos(cur, ev, _ids_academias_escopo(esc), prog)
    _situacao_pagamento(cur, inscritos)
    for r in inscritos:
        r["bloqueio"] = _bloqueio_pagamento(ev, r)
    return _ordenar_banca(inscritos, prog)


def _gravar_dados_exame(cur, inscricao_id, **campos):
    """Acrescenta campos em dados_form["exame_faixa"] da inscrição."""
    cur.execute("SELECT dados_form FROM eventos_competicoes_inscricoes WHERE id = %s", (inscricao_id,))
    dados = _dados(cur.fetchone() or {})
    dados.setdefault("exame_faixa", {}).update(campos)
    cur.execute("UPDATE eventos_competicoes_inscricoes SET dados_form = %s WHERE id = %s",
                (json.dumps(dados, ensure_ascii=False, default=str), inscricao_id))


def _inscritos(cur, ev, ids_academia, prog):
    if not ids_academia:
        return []
    ph = ",".join(["%s"] * len(ids_academia))
    cur.execute(
        f"""SELECT i.id AS inscricao_id, i.aluno_id, i.academia_id, i.dados_form, i.created_at,
                   a.nome, a.foto, a.data_nascimento, {_graduacao_judo_sql(cur)} AS graduacao_id,
                   ac.nome AS academia_nome,
                   av.id AS avaliacao_id, av.media_geral, av.resultado, av.aluno_graduacao_id
            FROM eventos_competicoes_inscricoes i
            JOIN alunos a ON a.id = i.aluno_id
            JOIN academias ac ON ac.id = i.academia_id
            LEFT JOIN exame_faixa_avaliacao av ON av.inscricao_id = i.id
            WHERE i.evento_id = %s AND i.status = 'enviada' AND i.academia_id IN ({ph})
            ORDER BY a.nome""", (ev["id"],) + tuple(ids_academia))
    linhas = cur.fetchall()
    for r in linhas:
        dados = _dados(r).get("exame_faixa") or {}
        r["exame"] = dados
        r["promocao"], _i = exf.promocao_da_inscricao(prog, dados, r.get("graduacao_id"))
        rot, cor = exf.RESULTADOS.get(r.get("resultado") or "pendente", exf.RESULTADOS["pendente"])
        r["resultado_rotulo"], r["resultado_cor"] = rot, cor
    return linhas


@bp_exame_faixa.route("/evento/<int:evento_id>/banca")
@login_required
def banca(evento_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ev = _evento(cur, evento_id)
        if not _pode_banca(esc, ev):
            flash("Exame não encontrado.", "danger")
            return redirect(url_for("exame_faixa.exames"))
        prog = exf.programa(cur, ev["id_associacao"])
        inscritos = _inscritos_da_banca(cur, esc, ev, prog)
        # Depois da prova: quem passou e ainda não teve a faixa registrada.
        aprovados = [r for r in inscritos if r.get("resultado") == "aprovado"]

        grupos = []
        for p in prog:
            membros = [r for r in inscritos if r["promocao"] and r["promocao"]["id"] == p["id"]]
            if membros:
                grupos.append({"promocao": p, "inscritos": membros})
        sem_promocao = [r for r in inscritos if not r["promocao"]]

        # Quem ainda dá para incluir: só com uma academia escolhida, para a
        # lista não virar o cadastro inteiro da associação.
        candidatos = []
        if esc.get("academia_id") and prog:
            ja = {r["aluno_id"] for r in inscritos}
            candidatos = [a for a in _alunos_com_situacao(cur, [esc["academia_id"]], prog,
                                                           data_ref=_data_exame(ev))
                          if a["id"] not in ja and a["sit"]["promocao"]]
        resumo = {
            "inscritos": len(inscritos),
            "aprovados": sum(1 for r in inscritos if r.get("resultado") == "aprovado"),
            "reprovados": sum(1 for r in inscritos if r.get("resultado") == "reprovado"),
            "pendentes": sum(1 for r in inscritos if (r.get("resultado") or "pendente") == "pendente"),
            "pagos": sum(1 for r in inscritos if (r.get("pagamento") or {}).get("status") == "pago"),
            "a_promover": sum(1 for r in aprovados if not r.get("aluno_graduacao_id")),
            "bloqueados": sum(1 for r in inscritos if r.get("bloqueio")),
            "sem_sorteio": sum(1 for r in inscritos if not r.get("avaliacao_id") and r["promocao"]),
            "presentes": sum(1 for r in inscritos if r["exame"].get("presente")),
        }
        chamada = [r for r in inscritos if (r.get("resultado") or "pendente") == "pendente"]
        # Para o diálogo "Faixa do próximo exame": faixa seguinte e o que a regra daria.
        destinos = exf.destinos_escolhidos(cur, [r["aluno_id"] for r in inscritos])
        for r in inscritos:
            nat = next((x for x in prog if x["graduacao_de_id"] == r.get("graduacao_id")), None)
            r["indice_natural"] = nat["indice"] if nat else None
            r["pela_regra"] = None
            r["destino_motivo"] = (destinos.get(r["aluno_id"]) or {}).get("motivo")
            if nat:
                sal = exf.regra_de_salto(prog, nat, exf._como_data(r.get("data_nascimento")), _data_exame(ev) or date.today(),
                                         exf.inicio_laranja(cur, {"id": r["aluno_id"]}))
                r["pela_regra"] = prog[sal[0]]["para"] if sal else nat["para"]
        dono = None
        if ev.get("exame_academia_id"):
            cur.execute("SELECT nome FROM academias WHERE id = %s", (ev["exame_academia_id"],))
            dono = (cur.fetchone() or {}).get("nome")
        return render_template(
            "exame_faixa/banca.html", esc=esc, abas=_abas(esc, "exames"), ev=ev,
            ap_acao=url_for("exame_faixa.evento_apostilas", evento_id=ev["id"]),
            ap_ocultos={"academia_id": esc.get("academia_id") or ""},
            ap_lista=[dict(_item_apostila(a["id"], a["nome"], p), inscrito=a["inscrito"])
                      for a, p in _alunos_do_exame(cur, esc, ev, prog)],
            ap_sem_nome=False,
            fila=_fila(inscritos), chamada=chamada, dono=dono, prog=prog,
            pode_editar=_pode_editar_exame(esc, ev),
            data_exame=_data_exame(ev), hora_prova=_hora_prova(ev), prazo=_prazo_pagamento(ev),
            encerrado=_encerrado(ev), nao_abriu=_ainda_nao_abriu(ev), grupos=grupos,
            sem_promocao=sem_promocao, candidatos=candidatos, resumo=resumo, aprovados=aprovados)
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/evento/<int:evento_id>/incluir", methods=["POST"])
@login_required
def incluir(evento_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ev = _evento(cur, evento_id)
        if not _pode_banca(esc, ev) or not esc.get("academia_id"):
            flash("Escolha a academia para incluir alunos.", "warning")
            return redirect(url_for("exame_faixa.banca", evento_id=evento_id))
        voltar = url_for("exame_faixa.banca", evento_id=evento_id, academia_id=esc["academia_id"])
        # A lista de aptos inscreve em lote e quer voltar para ela mesma.
        pedido = request.form.get("voltar") or ""
        if pedido.startswith("/exame-faixa/") and "//" not in pedido:
            voltar = pedido
        ids = [int(x) for x in request.form.getlist("aluno_id") if str(x).isdigit()]
        forcar = bool(request.form.get("forcar"))
        if not ids:
            flash("Marque ao menos um aluno.", "warning")
            return redirect(voltar)
        prog = exf.programa(cur, ev["id_associacao"])
        ph = ",".join(["%s"] * len(ids))
        trecho, params = filtro_alunos_da_academia(esc["academia_id"], alias="alunos")
        cur.execute(f"SELECT * FROM alunos WHERE id IN ({ph}) AND {trecho}",
                    tuple(ids) + tuple(params))
        alvos = cur.fetchall()
        # Aluno vinculado: a inscrição e a fatura são da academia que inscreve.
        for a in alvos:
            a["id_academia"] = esc["academia_id"]
        incluidos, faturas, pulados = 0, 0, []
        _garantir_adesao(cur, evento_id, esc["academia_id"])
        for a in alvos:
            if _inscricao_do_aluno(cur, evento_id, a["id"]):
                continue
            sit = exf.situacao(cur, a, prog, data_ref=_data_exame(ev))
            if not sit["promocao"]:
                pulados.append(f"{a['nome']} (sem exame no programa)")
                continue
            if sit["status"] in ("aguardando", "fora_idade") and not forcar:
                pulados.append(f"{a['nome']} ({'; '.join(sit['pendencias'])})")
                continue
            _iid, cobranca = _criar_inscricao(cur, ev, a, sit, {"incluido_pela_academia": True})
            incluidos += 1
            faturas += 1 if cobranca else 0
        conn.commit()
        if incluidos:
            flash(f"{incluidos} aluno{'s' if incluidos != 1 else ''} incluído"
                  f"{'s' if incluidos != 1 else ''} no exame"
                  + (f" — {faturas} fatura{'s' if faturas != 1 else ''} gerada{'s' if faturas != 1 else ''}"
                     if faturas else "") + ".", "success")
        if pulados:
            flash("Não incluídos: " + "; ".join(pulados)
                  + ". Marque “incluir mesmo sem cumprir” para forçar.", "warning")
        return redirect(voltar)
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Incluir alunos no exame de faixa")
        flash(f"Não foi possível incluir: {e}", "danger")
        return redirect(url_for("exame_faixa.banca", evento_id=evento_id))
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/evento/<int:evento_id>/avaliar/<int:inscricao_id>", methods=["GET", "POST"])
@login_required
def avaliar(evento_id, inscricao_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ev = _evento(cur, evento_id)
        if not _pode_banca(esc, ev):
            flash("Exame não encontrado.", "danger")
            return redirect(url_for("exame_faixa.exames"))
        cur.execute(
            f"""SELECT i.*, a.nome, a.foto, a.data_nascimento, {_graduacao_judo_sql(cur)} AS graduacao_id,
                      ac.nome AS academia_nome
               FROM eventos_competicoes_inscricoes i
               JOIN alunos a ON a.id = i.aluno_id
               JOIN academias ac ON ac.id = i.academia_id
               WHERE i.id = %s AND i.evento_id = %s AND i.status = 'enviada'""",
            (inscricao_id, evento_id))
        insc = cur.fetchone()
        if not insc or insc["academia_id"] not in [a["id"] for a in esc["academias"]]:
            flash("Inscrição não encontrada.", "danger")
            return redirect(url_for("exame_faixa.banca", evento_id=evento_id))
        voltar_kw = {"academia_id": esc["academia_id"]} if esc.get("academia_id") else {}
        aqui = url_for("exame_faixa.avaliar", evento_id=evento_id, inscricao_id=inscricao_id, **voltar_kw)

        prog = exf.programa(cur, ev["id_associacao"])
        dados = _dados(insc).get("exame_faixa") or {}
        promo, idx = exf.promocao_da_inscricao(prog, dados, insc.get("graduacao_id"))
        if idx is None:
            flash("A faixa deste aluno não tem promoção no programa.", "danger")
            return redirect(url_for("exame_faixa.banca", evento_id=evento_id, **voltar_kw))

        cur.execute("SELECT * FROM exame_faixa_avaliacao WHERE inscricao_id = %s", (inscricao_id,))
        av = exf.carregar_avaliacao(cur.fetchone())

        # Fatura em aberto depois do prazo segura a prova (a banca pode liberar).
        pag = {"exame": dados}
        _situacao_pagamento(cur, [pag])
        bloqueio = _bloqueio_pagamento(ev, pag)
        aberta = not av or (av.get("resultado") or "pendente") == "pendente"
        if bloqueio and aberta and request.form.get("acao") != "ausente":
            flash(f"{insc['nome']}: {bloqueio.lower()}. Receba o pagamento ou use "
                  "“Liberar prova” na banca.", "warning")
            return redirect(url_for("exame_faixa.banca", evento_id=evento_id, **voltar_kw))

        def _depois_de_salvar():
            """Próximo da fila, ou a banca quando não sobrou ninguém."""
            if request.form.get("proximo"):
                seguinte = next(iter(_fila(_inscritos_da_banca(cur, esc, ev, prog), sem=inscricao_id)), None)
                if seguinte:
                    return redirect(url_for("exame_faixa.avaliar", evento_id=evento_id,
                                            inscricao_id=seguinte["inscricao_id"], **voltar_kw))
                flash("Não há mais ninguém aguardando prova.", "info")
            return redirect(url_for("exame_faixa.banca", evento_id=evento_id, **voltar_kw))

        if request.method == "POST":
            acao = request.form.get("acao")
            if acao == "sortear":
                if av and av.get("aluno_graduacao_id"):
                    flash("A graduação deste exame já foi registrada; a ficha não pode ser refeita.", "warning")
                    return redirect(aqui)
                escopo = "faixa" if request.form.get("escopo") == "faixa" else "cumulativo"
                pesos, qtds = {}, {}
                for pt in exf.PARTES:
                    try:
                        pesos[pt["chave"]] = max(0.0, min(10.0, float(
                            (request.form.get(f"peso_{pt['chave']}") or "0").replace(",", "."))))
                    except ValueError:
                        pesos[pt["chave"]] = exf.PESOS_PADRAO[pt["chave"]]
                for g in exf.GRUPOS:
                    qtds[g["chave"]] = max(0, min(20, request.form.get(f"qtd_{g['chave']}", type=int) or 0))
                tecnicas = exf.sortear(prog, idx, qtds, escopo)
                if not tecnicas:
                    flash("Defina ao menos uma quantidade para sortear.", "warning")
                    return redirect(aqui)
                valores = (evento_id, inscricao_id, insc["aluno_id"], promo["id"],
                           promo["graduacao_de_id"], promo["graduacao_para_id"], escopo,
                           json.dumps(pesos), json.dumps(tecnicas, ensure_ascii=False), exf.NOTA_CORTE)
                if av:
                    cur.execute(
                        """UPDATE exame_faixa_avaliacao
                           SET escopo = %s, pesos = %s, tecnicas = %s, notas = '{}', medias = '{}',
                               media_geral = NULL, resultado = 'pendente', avaliado_em = NULL
                           WHERE id = %s""",
                        (escopo, json.dumps(pesos), json.dumps(tecnicas, ensure_ascii=False), av["id"]))
                else:
                    cur.execute(
                        """INSERT INTO exame_faixa_avaliacao
                               (evento_id, inscricao_id, aluno_id, programa_id, graduacao_de_id,
                                graduacao_para_id, escopo, pesos, tecnicas, nota_corte)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", valores)
                conn.commit()
                flash("Técnicas sorteadas. Lance as notas e salve a ficha.", "success")
                return redirect(aqui)

            if not av:
                flash("Sorteie as técnicas antes de lançar notas.", "warning")
                return redirect(aqui)

            if acao == "ausente":
                cur.execute(
                    """UPDATE exame_faixa_avaliacao SET resultado = 'ausente', avaliador_id = %s,
                           avaliado_em = NOW() WHERE id = %s AND aluno_graduacao_id IS NULL""",
                    (current_user.id, av["id"]))
                conn.commit()
                flash(f"{insc['nome']} marcado como ausente.", "info")
                return _depois_de_salvar()

            if acao == "salvar":
                notas = {}
                for g in exf.GRUPOS:
                    for i, rot in enumerate(av["tecnicas"].get(g["chave"]) or []):
                        bruto = (request.form.get(f"nota_{g['chave']}_{i}") or "").strip().replace(",", ".")
                        if not bruto:
                            continue
                        try:
                            v = max(0.0, min(10.0, float(bruto)))
                        except ValueError:
                            continue
                        notas.setdefault(g["chave"], {})[rot] = v
                medias = exf.calcular_medias(notas, av["pesos"])
                geral = medias.get("geral")
                corte = float(av.get("nota_corte") or exf.NOTA_CORTE)
                resultado = "pendente" if geral is None else ("aprovado" if geral >= corte else "reprovado")
                obs = (request.form.get("observacao") or "").strip()[:500] or None
                cur.execute(
                    """UPDATE exame_faixa_avaliacao
                       SET notas = %s, medias = %s, media_geral = %s, resultado = %s, observacao = %s,
                           avaliador_id = %s, avaliado_em = NOW()
                       WHERE id = %s""",
                    (json.dumps(notas, ensure_ascii=False), json.dumps(medias), geral, resultado, obs,
                     current_user.id, av["id"]))
                msg = f"Ficha de {insc['nome']} salva"
                if geral is not None:
                    msg += f" — média {exf.nota_fmt(geral)}, {exf.RESULTADOS[resultado][0].lower()}"
                if resultado == "aprovado" and request.form.get("promover"):
                    faixa = _promover(cur, av["id"])
                    if faixa:
                        msg += f". Promovido à faixa {faixa}"
                conn.commit()
                flash(msg + ".", "success")
                if request.form.get("proximo") or request.form.get("banca"):
                    return _depois_de_salvar()
                return redirect(aqui)

            flash("Ação desconhecida.", "warning")
            return redirect(aqui)

        ordem = _inscritos_da_banca(cur, esc, ev, prog)
        posicao = next((i + 1 for i, r in enumerate(ordem) if r["inscricao_id"] == inscricao_id), None)
        disp = {c: exf.disponiveis(prog, idx, c) for c in ("cumulativo", "faixa")}
        pesos = dict(exf.PESOS_PADRAO)
        if av and all(k in av["pesos"] for k in pesos):
            pesos = av["pesos"]
        return render_template(
            "exame_faixa/avaliar.html", esc=esc, abas=_abas(esc, "exames"), ev=ev, insc=insc,
            promocao=promo, av=av, partes_ficha=exf.linhas_ficha(av) if av else [], disp=disp,
            partes=exf.PARTES, grupo_por_chave=exf.grupo_por_chave,
            pesos=pesos, qtds=exf.QTD_PADRAO,
            corte=exf.NOTA_CORTE, voltar_kw=voltar_kw, data_exame=_data_exame(ev),
            posicao=posicao, total_banca=len(ordem), pagamento=pag["pagamento"],
            idade=exf._anos(exf._como_data(insc.get("data_nascimento")), _data_exame(ev) or date.today()))
    finally:
        cur.close()
        conn.close()


# ------------------------------------------------------ criar/editar exame
def _dt_form(campo, com_hora=True):
    bruto = (request.form.get(campo) or "").strip()
    if not bruto:
        return None
    try:
        return datetime.strptime(bruto[:16], "%Y-%m-%dT%H:%M") if com_hora else \
            datetime.strptime(bruto[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _calendario_exame(cur, evento_id, nome, prova, academias, id_assoc, novo):
    """O exame entra no calendário no DIA DA PROVA (tipo 'exame')."""
    if not prova:
        return
    if not novo:
        cur.execute("""UPDATE eventos SET titulo = %s, data_inicio = %s, data_fim = %s, hora_inicio = %s,
                              hora_fim = NULL, tipo = 'exame'
                       WHERE evento_competicao_id = %s""",
                    (nome, prova.date(), prova.date(), prova.time(), evento_id))
        return
    niveis = ([("associacao", id_assoc)] if len(academias) > 1 else []) + [("academia", a) for a in academias]
    for nivel, nivel_id in niveis:
        cur.execute(
            """INSERT INTO eventos (titulo, data_inicio, data_fim, hora_inicio, tipo, recorrente, nivel,
                                    nivel_id, criado_por_usuario_id, origem_sincronizacao,
                                    evento_competicao_id, status)
               VALUES (%s,%s,%s,%s,'exame',0,%s,%s,%s,'eventos_competicoes',%s,'ativo')""",
            (nome, prova.date(), prova.date(), prova.time(), nivel, nivel_id, current_user.id, evento_id))


@bp_exame_faixa.route("/novo", methods=["GET", "POST"])
@bp_exame_faixa.route("/evento/<int:evento_id>/editar", methods=["GET", "POST"])
@login_required
def editar_exame(evento_id=None):
    """Marca (ou edita) um exame de faixa.

    A associação marca exames abertos a todas as suas academias. A academia
    marca o próprio exame, só para os alunos dela — programa, preços e regras
    continuam os da associação.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        ev = _evento(cur, evento_id) if evento_id else None
        if evento_id and not _pode_editar_exame(esc, ev):
            flash("Você não pode editar este exame.", "danger")
            return redirect(url_for("exame_faixa.exames"))
        if not evento_id and not esc.get("pode_criar"):
            flash("Só a gestão da academia ou da associação marca exames.", "danger")
            return redirect(url_for("exame_faixa.exames"))
        # Para quem é o exame: associação escolhe entre todas ou uma academia;
        # academia só marca para as suas.
        opcoes = ([{"id": "", "nome": "Todas as academias da associação"}] if esc["ve_todas"] else []) + \
            [{"id": a["id"], "nome": a["nome"]} for a in esc["academias"]]
        voltar = url_for("exame_faixa.exames", **({"academia_id": esc["academia_id"]}
                                                   if esc.get("academia_id") else {}))

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()[:255]
            descricao = (request.form.get("descricao") or "").strip() or None
            ini, fim = _dt_form("inscricoes_inicio"), _dt_form("inscricoes_fim")
            prova, prazo = _dt_form("data_prova"), _dt_form("prazo_pagamento", com_hora=False)
            gera = bool(request.form.get("gera_fatura"))
            if ev:
                dono = ev.get("exame_academia_id")
            else:
                dono = request.form.get("dono", type=int)
                if dono and dono not in [a["id"] for a in esc["academias"]]:
                    dono = None
                if not dono and not esc["ve_todas"]:
                    dono = esc.get("academia_id") or (esc["academias"][0]["id"] if esc["academias"] else None)
            erros = []
            if not nome:
                erros.append("Informe o nome do exame.")
            if not prova:
                erros.append("Informe o dia e a hora da prova.")
            if not fim:
                erros.append("Informe até quando vão as inscrições.")
            if fim and prova and fim > prova:
                erros.append("As inscrições precisam encerrar antes da prova.")
            if ini and fim and ini >= fim:
                erros.append("A abertura das inscrições precisa ser antes do encerramento.")
            if prazo and prova and prazo > prova.date():
                erros.append("O prazo de pagamento não pode ser depois da prova.")
            if erros:
                for e in erros:
                    flash(e, "danger")
                return render_template("exame_faixa/editar_exame.html", esc=esc, abas=_abas(esc, "exames"),
                                       ev=ev, opcoes=opcoes, form=request.form, voltar=voltar)
            ini = ini or datetime.now().replace(second=0, microsecond=0)
            if ev:
                cur.execute(
                    """UPDATE eventos_competicoes SET nome=%s, descricao=%s, data_inicio=%s, data_fim=%s,
                              exame_data_prova=%s, exame_prazo_pagamento=%s, exame_gera_fatura=%s
                       WHERE id=%s""",
                    (nome, descricao, ini, fim, prova, prazo, 1 if gera else 0, ev["id"]))
                _calendario_exame(cur, ev["id"], nome, prova, [], esc["id_assoc"], novo=False)
                conn.commit()
                flash("Exame atualizado. Quem já se inscreveu mantém o valor e o vencimento da fatura.", "success")
                return redirect(url_for("exame_faixa.banca", evento_id=ev["id"],
                                        **({"academia_id": esc["academia_id"]} if esc.get("academia_id") else {})))
            cur.execute(
                """INSERT INTO eventos_competicoes
                       (nome, descricao, id_associacao, tipo, data_inicio, data_fim, status, exame_faixa,
                        exame_data_prova, exame_prazo_pagamento, exame_gera_fatura, exame_academia_id)
                   VALUES (%s,%s,%s,'evento',%s,%s,'ativo',1,%s,%s,%s,%s)""",
                (nome, descricao, esc["id_assoc"], ini, fim, prova, prazo, 1 if gera else 0, dono))
            novo_id = cur.lastrowid
            if dono:
                academias = [dono]
            else:
                cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (esc["id_assoc"],))
                academias = [r["id"] for r in cur.fetchall()]
            for ac in academias:
                cur.execute("""INSERT INTO eventos_competicoes_adesao (evento_id, academia_id, aderiu, data_adesao)
                               VALUES (%s,%s,1,NOW())""", (novo_id, ac))
            _calendario_exame(cur, novo_id, nome, prova, academias, esc["id_assoc"], novo=True)
            conn.commit()
            flash("Exame de faixa marcado. As inscrições abrem para "
                  + ("os alunos da academia" if dono else "os alunos de todas as academias")
                  + (f" em {ini:%d/%m às %H:%M}" if ini > datetime.now() else "")
                  + " — a academia também pode inscrever os aptos em lote.", "success")
            return redirect(url_for("exame_faixa.banca", evento_id=novo_id,
                                    **({"academia_id": dono} if dono and not esc["ve_todas"] else {})))

        return render_template("exame_faixa/editar_exame.html", esc=esc, abas=_abas(esc, "exames"),
                               ev=ev, opcoes=opcoes, form=None, voltar=voltar)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------- ações da banca
def _banca_e_inscricao(cur, evento_id, inscricao_id=None):
    """(esc, ev, inscrição, redirect de erro). Confere escopo e dono."""
    esc, erro = _exige_escopo(cur)
    if erro:
        return None, None, None, erro
    ev = _evento(cur, evento_id)
    if not _pode_banca(esc, ev):
        flash("Exame não encontrado.", "danger")
        return None, None, None, redirect(url_for("exame_faixa.exames"))
    insc = None
    if inscricao_id:
        cur.execute(f"""SELECT i.*, a.nome, {_graduacao_judo_sql(cur)} AS graduacao_id FROM eventos_competicoes_inscricoes i
                       JOIN alunos a ON a.id = i.aluno_id
                       WHERE i.id = %s AND i.evento_id = %s AND i.status = 'enviada'""",
                    (inscricao_id, evento_id))
        insc = cur.fetchone()
        if not insc or insc["academia_id"] not in [a["id"] for a in esc["academias"]]:
            flash("Inscrição não encontrada.", "danger")
            return None, None, None, redirect(_voltar_banca(evento_id))
    return esc, ev, insc, None


def _voltar_banca(evento_id):
    v = request.form.get("voltar") or ""
    if v.startswith("/exame-faixa/") and "//" not in v:
        return v
    return url_for("exame_faixa.banca", evento_id=evento_id)


@bp_exame_faixa.route("/evento/<int:evento_id>/inscricao/<int:inscricao_id>/liberar", methods=["POST"])
@login_required
def liberar_prova(evento_id, inscricao_id):
    """A banca deixa fazer a prova com a fatura em aberto (pagou na hora, isento...)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, ev, insc, erro = _banca_e_inscricao(cur, evento_id, inscricao_id)
        if erro:
            return erro
        _gravar_dados_exame(cur, inscricao_id, liberado_por=current_user.id,
                            liberado_em=datetime.now().strftime("%Y-%m-%d %H:%M"))
        conn.commit()
        flash(f"Prova de {insc['nome']} liberada com a fatura em aberto.", "info")
        return redirect(_voltar_banca(evento_id))
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/evento/<int:evento_id>/inscricao/<int:inscricao_id>/cancelar", methods=["POST"])
@login_required
def cancelar_inscricao(evento_id, inscricao_id):
    """Tira o aluno do exame: a inscrição fica 'cancelada' e a fatura em aberto é cancelada.

    Não cancela quem já teve a faixa registrada por este exame, nem fatura paga
    (essa a academia estorna pelo financeiro).
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, ev, insc, erro = _banca_e_inscricao(cur, evento_id, inscricao_id)
        if erro:
            return erro
        cur.execute("SELECT id, aluno_graduacao_id FROM exame_faixa_avaliacao WHERE inscricao_id = %s",
                    (inscricao_id,))
        av = cur.fetchone()
        if av and av.get("aluno_graduacao_id"):
            flash("A faixa deste exame já foi registrada — a inscrição não pode ser cancelada.", "warning")
            return redirect(_voltar_banca(evento_id))
        dados = (_dados(insc).get("exame_faixa") or {})
        aviso = ""
        cid = dados.get("cobranca_id")
        if cid:
            cur.execute("SELECT * FROM cobranca_avulsa WHERE id = %s", (cid,))
            ca = cur.fetchone()
            if ca and ca["status"] == "pago":
                aviso = " A fatura já estava paga — faça o estorno pelo financeiro, se for o caso."
            elif ca and ca["status"] != "cancelado":
                try:
                    from blueprints.financeiro import routes as fin
                    if ca.get("asaas_payment_id"):
                        fin._cancelar_no_gateway(fin._gateway_config_academia(ca["id_academia"]),
                                                 ca.get("gateway"), ca.get("asaas_payment_id"))
                except Exception:
                    current_app.logger.exception("Cancelar no gateway a fatura %s", cid)
                cur.execute("UPDATE cobranca_avulsa SET status = 'cancelado' WHERE id = %s", (cid,))
                aviso = " A fatura foi cancelada."
        if av:
            cur.execute("DELETE FROM exame_faixa_avaliacao WHERE id = %s", (av["id"],))
        cur.execute("UPDATE eventos_competicoes_inscricoes SET status = 'cancelada' WHERE id = %s",
                    (inscricao_id,))
        conn.commit()
        flash(f"Inscrição de {insc['nome']} cancelada.{aviso}", "info")
        return redirect(_voltar_banca(evento_id))
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Cancelar inscrição do exame")
        flash(f"Não foi possível cancelar: {e}", "danger")
        return redirect(_voltar_banca(evento_id))
    finally:
        cur.close()
        conn.close()


def _nova_ficha(cur, ev, r, prog, resultado="pendente"):
    """Cria a ficha da inscrição: sorteio padrão (cumulativo) ou só a ausência."""
    promo, idx = exf.promocao_da_inscricao(prog, r["exame"], r.get("graduacao_id"))
    if idx is None:
        return False
    tecnicas = exf.sortear(prog, idx, exf.QTD_PADRAO, "cumulativo") if resultado == "pendente" else {}
    if resultado == "pendente" and not tecnicas:
        return False
    cur.execute(
        """INSERT INTO exame_faixa_avaliacao
               (evento_id, inscricao_id, aluno_id, programa_id, graduacao_de_id,
                graduacao_para_id, escopo, pesos, tecnicas, nota_corte, resultado,
                avaliador_id, avaliado_em)
           VALUES (%s,%s,%s,%s,%s,%s,'cumulativo',%s,%s,%s,%s,%s,%s)""",
        (ev["id"], r["inscricao_id"], r["aluno_id"], promo["id"], promo["graduacao_de_id"],
         promo["graduacao_para_id"], json.dumps(exf.PESOS_PADRAO),
         json.dumps(tecnicas, ensure_ascii=False), exf.NOTA_CORTE, resultado,
         current_user.id if resultado != "pendente" else None,
         datetime.now() if resultado != "pendente" else None))
    return True


@bp_exame_faixa.route("/evento/<int:evento_id>/sortear-todos", methods=["POST"])
@login_required
def sortear_todos(evento_id):
    """Sorteia de uma vez a prova de quem ainda não tem ficha (padrão: cumulativo)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, ev, _i, erro = _banca_e_inscricao(cur, evento_id)
        if erro:
            return erro
        prog = exf.programa(cur, ev["id_associacao"])
        n = 0
        for r in _inscritos(cur, ev, _ids_academias_escopo(esc), prog):
            if not r.get("avaliacao_id") and r["promocao"] and _nova_ficha(cur, ev, r, prog):
                n += 1
        conn.commit()
        flash(f"Prova sorteada para {n} aluno{'s' if n != 1 else ''}. Cada ficha ainda pode "
              "ser sorteada de novo antes das notas." if n else "Todos já tinham a prova sorteada.",
              "success" if n else "info")
        return redirect(_voltar_banca(evento_id))
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/evento/<int:evento_id>/presenca", methods=["POST"])
@login_required
def presenca(evento_id):
    """Chamada do dia: marca quem está presente; opcionalmente, os demais como ausentes."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, ev, _i, erro = _banca_e_inscricao(cur, evento_id)
        if erro:
            return erro
        prog = exf.programa(cur, ev["id_associacao"])
        presentes = {int(x) for x in request.form.getlist("presente") if str(x).isdigit()}
        marcar_ausentes = bool(request.form.get("ausentes"))
        n_pres = n_aus = 0
        for r in _inscritos(cur, ev, _ids_academias_escopo(esc), prog):
            if (r.get("resultado") or "pendente") != "pendente":
                continue
            esta = r["inscricao_id"] in presentes
            _gravar_dados_exame(cur, r["inscricao_id"], presente=esta)
            n_pres += esta
            if not esta and marcar_ausentes:
                if r.get("avaliacao_id"):
                    cur.execute("""UPDATE exame_faixa_avaliacao SET resultado = 'ausente', avaliador_id = %s,
                                          avaliado_em = NOW() WHERE id = %s AND aluno_graduacao_id IS NULL""",
                                (current_user.id, r["avaliacao_id"]))
                else:
                    _nova_ficha(cur, ev, r, prog, resultado="ausente")
                n_aus += 1
        conn.commit()
        flash(f"Chamada salva: {n_pres} presente{'s' if n_pres != 1 else ''}"
              + (f", {n_aus} marcado{'s' if n_aus != 1 else ''} como ausente{'s' if n_aus != 1 else ''}" if n_aus else "")
              + ".", "success")
        return redirect(_voltar_banca(evento_id))
    finally:
        cur.close()
        conn.close()


def _promover(cur, av_id):
    """Aprovado na banca: lança a faixa nova no histórico e no cadastro.

    Mesma regra do registro manual (alunos.registrar_graduacao): a faixa atual
    só muda se esta for a graduação mais recente do aluno. A data é a da prova,
    sem passar de hoje — o histórico não aceita data futura. Devolve o nome da
    faixa registrada, ou None se a ficha não está aprovada ou já foi promovida.
    """
    cur.execute(
        """SELECT av.*, ec.nome AS evento_nome, ec.exame_data_prova, ec.data_fim
           FROM exame_faixa_avaliacao av
           LEFT JOIN eventos_competicoes ec ON ec.id = av.evento_id
           WHERE av.id = %s""", (av_id,))
    av = cur.fetchone()
    if not av or av["resultado"] != "aprovado" or av.get("aluno_graduacao_id"):
        return None
    data_grad = min(_data_exame(av) or date.today(), date.today())
    cur.execute("SELECT id, faixa, graduacao FROM graduacao WHERE id = %s", (av["graduacao_para_id"],))
    g = cur.fetchone()
    if not g:
        return None
    cur.execute(
        """INSERT INTO aluno_graduacao
               (aluno_id, graduacao_id, faixa, grau, data, origem, observacao, registrado_por)
           VALUES (%s,%s,%s,%s,%s,'Exame de faixa',%s,%s)""",
        (av["aluno_id"], g["id"], g.get("faixa") or "", g.get("graduacao") or None, data_grad,
         f"{av.get('evento_nome') or 'Exame de faixa'} — média {exf.nota_fmt(av.get('media_geral'))}"[:255],
         current_user.id))
    grad_id = cur.lastrowid
    cur.execute("UPDATE exame_faixa_avaliacao SET aluno_graduacao_id = %s WHERE id = %s", (grad_id, av_id))
    # Mais recente NA MODALIDADE da faixa: graduação de jiu-jitsu não segura a de judô.
    cur.execute(
        """SELECT MAX(ag.data) AS ultima FROM aluno_graduacao ag
           LEFT JOIN graduacao gx ON gx.id = ag.graduacao_id
           WHERE ag.aluno_id = %s AND ag.id <> %s
             AND (gx.modalidade_id <=> (SELECT modalidade_id FROM graduacao WHERE id = %s))""",
        (av["aluno_id"], grad_id, g["id"]))
    ultima = (cur.fetchone() or {}).get("ultima")
    if ultima is None or data_grad >= ultima:
        from utils import graduacao_modalidade as grad_mod
        if grad_mod.registrar(cur, av["aluno_id"], g["id"], data_grad):
            cur.execute("UPDATE alunos SET ultimo_exame_faixa = %s WHERE id = %s AND graduacao_id = %s",
                        (data_grad, av["aluno_id"], g["id"]))
        else:
            cur.execute("UPDATE alunos SET graduacao_id = %s, ultimo_exame_faixa = %s WHERE id = %s",
                        (g["id"], data_grad, av["aluno_id"]))
    return exf.nome_faixa(g["faixa"])


def _avaliacoes_no_escopo(cur, esc, av_ids):
    """Fichas que o usuário pode promover: do exame da associação e das suas academias."""
    ids = [int(x) for x in av_ids if str(x).isdigit()]
    acads = [a["id"] for a in esc["academias"]]
    if not ids or not acads or not esc.get("id_assoc"):
        return []
    ph, pa = ",".join(["%s"] * len(ids)), ",".join(["%s"] * len(acads))
    cur.execute(
        f"""SELECT av.id, a.nome FROM exame_faixa_avaliacao av
            JOIN eventos_competicoes_inscricoes i ON i.id = av.inscricao_id
            JOIN eventos_competicoes ec ON ec.id = av.evento_id
            JOIN alunos a ON a.id = av.aluno_id
            WHERE av.id IN ({ph}) AND i.academia_id IN ({pa}) AND ec.id_associacao = %s""",
        tuple(ids) + tuple(acads) + (esc["id_assoc"],))
    return cur.fetchall()


@bp_exame_faixa.route("/promover", methods=["POST"])
@login_required
def promover():
    """Promove para a nova faixa os aprovados selecionados (lista da banca ou ficha do aluno)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    destino = request.form.get("voltar") or request.referrer or url_for("exame_faixa.exames")
    if not destino.startswith("/") or destino.startswith("//"):
        destino = url_for("exame_faixa.exames")
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        fichas = _avaliacoes_no_escopo(cur, esc, request.form.getlist("avaliacao_id"))
        if not fichas:
            flash("Selecione ao menos um aluno aprovado.", "warning")
            return redirect(destino)
        feitos = []
        for f in fichas:
            faixa = _promover(cur, f["id"])
            if faixa:
                feitos.append(f"{f['nome']} → {faixa}")
        conn.commit()
        if feitos:
            flash(f"{len(feitos)} aluno{'s' if len(feitos) != 1 else ''} promovido"
                  f"{'s' if len(feitos) != 1 else ''}: " + "; ".join(feitos) + ".", "success")
        else:
            flash("Nada a promover: os selecionados já tinham a faixa registrada.", "info")
        return redirect(destino)
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Promover aprovados do exame de faixa")
        flash(f"Não foi possível promover: {e}", "danger")
        return redirect(destino)
    finally:
        cur.close()
        conn.close()


# -------------------------------------------------------- aluno: modo estudo
def _exames_abertos(cur, aluno):
    """Exames de faixa em aberto na academia do aluno (aderidos)."""
    if not aluno.get("id_academia"):
        return []
    try:
        cur.execute(
            """SELECT ec.* FROM eventos_competicoes ec
               JOIN eventos_competicoes_adesao ea ON ea.evento_id = ec.id
                    AND ea.academia_id = %s AND ea.aderiu = 1
               WHERE ec.exame_faixa = 1 AND ec.status = 'ativo' AND ec.data_fim > NOW()
               ORDER BY COALESCE(ec.exame_data_prova, ec.data_fim)""", (aluno["id_academia"],))
        eventos = cur.fetchall()
    except Exception:
        return []
    for ev in eventos:
        ev["data_exame"] = _data_exame(ev)
        ev["hora_prova"] = _hora_prova(ev)
        ev["nao_abriu"] = _ainda_nao_abriu(ev)
        ev["inscricao"] = _inscricao_do_aluno(cur, ev["id"], aluno["id"])
    return eventos


def _estudo_do_aluno(prog, sit):
    """Índice da promoção em foco e as faixas liberadas para estudo.

    O aluno estuda a próxima faixa e todas as anteriores. Sem promoção (já
    passou da marrom), todo o programa fica aberto para revisão; sem faixa
    cadastrada, só a primeira.
    """
    if sit["promocao"]:
        k = sit["promocao"]["indice"]
    elif sit["status"] == "sem_faixa":
        k = 0
    else:
        k = len(prog) - 1
    return k


@bp_exame_faixa.route("/estudo")
@login_required
def estudo():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        aluno, alunos_lista, modo = _aluno_alvo(cur)
        if not aluno:
            flash("Nenhum aluno vinculado a este usuário.", "warning")
            return redirect(url_for("painel.home"))
        id_assoc = exf.associacao_da_academia(cur, aluno.get("id_academia"))
        prog = exf.programa(cur, id_assoc)
        sit = exf.situacao(cur, aluno, prog) if prog else None
        faixa_atual = None
        if aluno.get("graduacao_id"):
            cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (aluno["graduacao_id"],))
            faixa_atual = cur.fetchone()
            if faixa_atual:
                faixa_atual["nome"] = exf.nome_faixa(faixa_atual["faixa"])
                faixa_atual["cores"] = exf.cores_faixa(faixa_atual["faixa"])
        k = _estudo_do_aluno(prog, sit) if prog else 0
        liberadas = prog[: k + 1]
        idx = request.args.get("p", type=int)
        if idx is None or not (0 <= idx <= k):
            idx = k
        # Na faixa do próximo exame mostramos a promoção DO ALUNO: num salto ela
        # traz o conteúdo somado das faixas puladas. Nas abas anteriores vale a
        # linha do programa, que é o que aquela faixa cobra por si.
        promo_aluno = (sit or {}).get("promocao") or {}
        atual = (promo_aluno if (prog and idx == k and promo_aluno.get("salto"))
                 else (prog[idx] if prog else None))
        conhecimento, tecnicas = exf.blocos_estudo(atual) if atual else ([], [])
        exf.anotar_videos(tecnicas, exf.videos_da_associacao(cur, id_assoc), com_qr=True)
        return render_template(
            "exame_faixa/estudo.html", aluno=aluno, alunos=alunos_lista, modo=modo,
            prog=prog, liberadas=liberadas, k=k, idx=idx, atual=atual, sit=sit,
            faixa_atual=faixa_atual, conhecimento=conhecimento, tecnicas=tecnicas,
            termos_do_material=exf.termos_do_material(conhecimento, tecnicas),
            exames=_exames_abertos(cur, aluno) if prog else [],
            status_rotulo=exf.STATUS_ROTULO)
    finally:
        cur.close()
        conn.close()


# ------------------------------------------------------ aluno: inscrição
CAMPOS_FICHA = [
    ("responsavel_nome", "Nome do responsável", "text"),
    ("telefone", "Telefone", "tel"),
    ("email", "E-mail", "email"),
    ("instagram", "Instagram", "text"),
    ("facebook", "Facebook", "text"),
]


@bp_exame_faixa.route("/evento/<int:evento_id>/inscrever", methods=["GET", "POST"])
@login_required
def inscrever(evento_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        aluno, alunos_lista, modo = _aluno_alvo(cur)
        ev = _evento(cur, evento_id)
        if not aluno or not ev:
            flash("Exame não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.disponiveis"))
        kw = {"aluno_id": aluno["id"]}
        if _inscricao_do_aluno(cur, evento_id, aluno["id"]):
            return redirect(url_for("exame_faixa.meu_exame", evento_id=evento_id, **kw))
        dono = ev.get("exame_academia_id")
        if dono and dono != aluno.get("id_academia"):
            flash("Este exame é de outra academia.", "warning")
            return redirect(url_for("eventos_competicoes.disponiveis", **kw))
        if not _aderiu(cur, evento_id, aluno.get("id_academia")):
            # Exame da associação abre para todos os alunos: a adesão é automática.
            _garantir_adesao(cur, evento_id, aluno.get("id_academia"))
            conn.commit()

        prog = exf.programa(cur, ev["id_associacao"])
        sit = exf.situacao(cur, aluno, prog, data_ref=_data_exame(ev))
        encerrado = _encerrado(ev)
        bloqueio = None
        if encerrado:
            bloqueio = "As inscrições para este exame estão encerradas."
        elif _ainda_nao_abriu(ev):
            bloqueio = f"As inscrições abrem em {ev['data_inicio']:%d/%m/%Y às %H:%M}."
        elif not sit["promocao"]:
            bloqueio = ("A faixa atual não está cadastrada — fale com a academia."
                        if sit["status"] == "sem_faixa"
                        else "Não há promoção no programa para a faixa atual.")
        elif sit["status"] in ("aguardando", "fora_idade"):
            bloqueio = "Ainda não cumpre os requisitos na data do exame: " + "; ".join(sit["pendencias"]) + "."

        if request.method == "POST":
            if bloqueio:
                flash(bloqueio, "danger")
                return redirect(url_for("exame_faixa.inscrever", evento_id=evento_id, **kw))
            extra = {c: (request.form.get(c) or "").strip()[:200] for c, _r, _t in CAMPOS_FICHA}
            extra["notas_colegio"] = (request.form.get("notas_colegio") or "").strip()[:1000]
            comp = request.form.get("comportamento")
            extra["comportamento"] = comp if comp in ("bom", "regular", "ruim") else ""
            _iid, cobranca = _criar_inscricao(cur, ev, aluno, sit, extra)
            conn.commit()
            msg = f"Inscrição confirmada: {sit['promocao']['de']} → {sit['promocao']['para']}."
            if cobranca:
                msg += (f" Fatura de {sit['promocao']['valor_fmt']} gerada, vencimento "
                        f"{_prazo_pagamento(ev):%d/%m/%Y} — está em Minhas mensalidades.")
            flash(msg + " Abaixo está tudo o que será cobrado no exame.", "success")
            return redirect(url_for("exame_faixa.meu_exame", evento_id=evento_id, **kw))

        iniciais = {
            "responsavel_nome": aluno.get("responsavel_nome") or aluno.get("nome_mae") or aluno.get("nome_pai") or "",
            "telefone": aluno.get("tel_celular") or aluno.get("telefone") or "",
            "email": aluno.get("email") or "",
        }
        return render_template(
            "exame_faixa/inscrever.html", aluno=aluno, alunos=alunos_lista, modo=modo, ev=ev,
            data_exame=_data_exame(ev), hora_prova=_hora_prova(ev), prazo=_prazo_pagamento(ev),
            gera_fatura=bool(ev.get("exame_gera_fatura", 1)),
            sit=sit, bloqueio=bloqueio, campos=CAMPOS_FICHA,
            iniciais=iniciais, status_rotulo=exf.STATUS_ROTULO)
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/evento/<int:evento_id>/meu-exame")
@login_required
def meu_exame(evento_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        aluno, alunos_lista, modo = _aluno_alvo(cur)
        ev = _evento(cur, evento_id)
        if not aluno or not ev:
            flash("Exame não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.disponiveis"))
        insc = _inscricao_do_aluno(cur, evento_id, aluno["id"])
        if not insc:
            return redirect(url_for("exame_faixa.inscrever", evento_id=evento_id, aluno_id=aluno["id"]))
        prog = exf.programa(cur, ev["id_associacao"])
        dados = _dados(insc).get("exame_faixa") or {}
        pag = {"exame": dados}
        _situacao_pagamento(cur, [pag])
        if pag["pagamento"] and pag["pagamento"]["status"] in ("pendente", "atrasado") \
                and not pag["pagamento"]["online"] and _emitir_online(cur, pag["pagamento"]["id"], forcar=True):
            conn.commit()
            _situacao_pagamento(cur, [pag])
        promo, idx = exf.promocao_da_inscricao(prog, dados)
        cur.execute("SELECT * FROM exame_faixa_avaliacao WHERE inscricao_id = %s", (insc["id"],))
        av = exf.carregar_avaliacao(cur.fetchone())
        # Nota só aparece para o aluno quando a banca fechou a ficha.
        if av and av.get("resultado") not in ("aprovado", "reprovado", "ausente"):
            av = None
        linhas = exf.linhas_ficha(av) if av else []
        sel = request.args.get("p", type=int)
        if promo is None:
            sel = None
        elif sel is None or not (0 <= sel <= idx):
            sel = idx
        # Mesma regra da tela de estudo: na faixa do exame, a promoção do aluno.
        atual = (promo if (sel is not None and sel == idx and (promo or {}).get("salto"))
                 else (prog[sel] if sel is not None else None))
        conhecimento, tecnicas = exf.blocos_estudo(atual) if atual else ([], [])
        exf.anotar_videos(tecnicas, exf.videos_da_associacao(cur, ev.get("id_associacao")), com_qr=True)
        return render_template(
            "exame_faixa/meu_exame.html", aluno=aluno, alunos=alunos_lista, modo=modo, ev=ev,
            data_exame=_data_exame(ev), hora_prova=_hora_prova(ev), pagamento=pag["pagamento"],
            insc=insc, dados=dados, promocao=promo, av=av, linhas=linhas,
            liberadas=prog[: idx + 1] if idx is not None else [], idx=sel, k=idx, atual=atual,
            conhecimento=conhecimento, tecnicas=tecnicas,
            termos_do_material=exf.termos_do_material(conhecimento, tecnicas),
            valor_fmt=exf.moeda(dados.get("valor")))
    finally:
        cur.close()
        conn.close()


# --------------------------------------------------------------- histórico
def _historico(cur, aluno_id, so_fechadas=False):
    """Todos os exames do aluno, do mais recente ao mais antigo.

    Cada item traz a ficha organizada por parte (teórica, nage-waza,
    katame-waza) com a nota de cada técnica. Inscrição sem prova aplicada
    também aparece, como "aguardando". `so_fechadas` esconde as notas de
    fichas que a banca ainda não fechou (visão do aluno).
    """
    cur.execute(
        """SELECT i.id AS inscricao_id, i.dados_form, i.created_at, ec.id AS evento_id,
                  ec.nome AS evento_nome, ec.data_inicio, ec.data_fim, ac.nome AS academia_nome
           FROM eventos_competicoes_inscricoes i
           JOIN eventos_competicoes ec ON ec.id = i.evento_id AND ec.exame_faixa = 1
           LEFT JOIN academias ac ON ac.id = i.academia_id
           WHERE i.aluno_id = %s AND i.status = 'enviada'""", (aluno_id,))
    inscricoes = {r["inscricao_id"]: r for r in cur.fetchall()}
    cur.execute(
        """SELECT av.*, u.nome AS avaliador_nome, gd.faixa AS de_faixa, gp.faixa AS para_faixa
           FROM exame_faixa_avaliacao av
           LEFT JOIN usuarios u ON u.id = av.avaliador_id
           LEFT JOIN graduacao gd ON gd.id = av.graduacao_de_id
           LEFT JOIN graduacao gp ON gp.id = av.graduacao_para_id
           WHERE av.aluno_id = %s""", (aluno_id,))
    avaliacoes = {r["inscricao_id"]: exf.carregar_avaliacao(r) for r in cur.fetchall()}

    itens = []
    for iid in set(inscricoes) | {k for k in avaliacoes if k}:
        ins = inscricoes.get(iid) or {}
        av = avaliacoes.get(iid)
        dados = _dados(ins).get("exame_faixa") if ins else {}
        dados = dados or {}
        de = (av or {}).get("de_faixa") or dados.get("de")
        para = (av or {}).get("para_faixa") or dados.get("para")
        fechada = bool(av and av.get("resultado") in ("aprovado", "reprovado", "ausente"))
        mostra = av if (av and (fechada or not so_fechadas)) else None
        data = _data_exame(ins) if ins else None
        if not data and av:
            data = (av.get("avaliado_em") or av.get("criado_em"))
            data = data.date() if isinstance(data, datetime) else data
        res = (mostra or {}).get("resultado") or "pendente"
        rot, cor = exf.RESULTADOS.get(res, exf.RESULTADOS["pendente"])
        itens.append({
            "evento_id": ins.get("evento_id") or (av or {}).get("evento_id"),
            "evento_nome": ins.get("evento_nome") or "Exame de faixa",
            "academia_nome": ins.get("academia_nome"),
            "data": data, "inscricao_id": iid,
            "de": exf.nome_faixa(de) if de else "—", "para": exf.nome_faixa(para) if para else "—",
            "cores_de": exf.cores_faixa(de), "cores_para": exf.cores_faixa(para),
            "valor_fmt": exf.moeda(dados.get("valor")),
            "av": mostra, "partes": exf.linhas_ficha(mostra) if mostra else [],
            "resultado_rotulo": rot, "resultado_cor": cor,
            "exame": dados, "avaliacao_id": (av or {}).get("id"),
            "a_promover": bool(av and av.get("resultado") == "aprovado" and not av.get("aluno_graduacao_id")),
            "promovido": bool(av and av.get("aluno_graduacao_id")),
        })
    _situacao_pagamento(cur, itens)
    itens.sort(key=lambda x: x["data"] or date.min, reverse=True)

    cur.execute(
        """SELECT faixa, grau, data, origem, observacao FROM aluno_graduacao
           WHERE aluno_id = %s ORDER BY data DESC, id DESC""", (aluno_id,))
    graduacoes = cur.fetchall()
    for g in graduacoes:
        g["faixa_nome"] = exf.nome_faixa(g["faixa"])
        g["cores"] = exf.cores_faixa(g["faixa"])
    resumo = {
        "exames": len(itens),
        "aprovados": sum(1 for x in itens if x["av"] and x["av"]["resultado"] == "aprovado"),
        "media": None,
    }
    medias = [float(x["av"]["media_geral"]) for x in itens
              if x["av"] and x["av"].get("media_geral") is not None]
    if medias:
        resumo["media"] = sum(medias) / len(medias)
    return itens, graduacoes, resumo


@bp_exame_faixa.route("/aluno/<int:aluno_id>/historico")
@login_required
def historico_aluno(aluno_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        cur.execute(f"""SELECT a.*, g.faixa, ac.nome AS academia_nome FROM alunos a
                       LEFT JOIN graduacao g ON g.id = {_graduacao_judo_sql(cur)}
                       LEFT JOIN academias ac ON ac.id = a.id_academia WHERE a.id = %s""", (aluno_id,))
        aluno = cur.fetchone()
        if not aluno or aluno.get("id_academia") not in [a["id"] for a in esc["academias"]]:
            flash("Aluno não encontrado.", "danger")
            return redirect(url_for("exame_faixa.alunos"))
        itens, graduacoes, resumo = _historico(cur, aluno_id)
        prog = exf.programa(cur, exf.associacao_da_academia(cur, aluno.get("id_academia")))
        sit = exf.situacao(cur, aluno, prog) if prog else None
        return render_template(
            "exame_faixa/historico.html", gestao=True, esc=esc, abas=_abas(esc, "alunos"),
            aluno=aluno, itens=itens, graduacoes=graduacoes, resumo=resumo, sit=sit,
            laranja=exf.marcas_inicio_laranja(cur, [aluno_id]).get(aluno_id),
            prog=prog,
            destino=exf.destinos_escolhidos(cur, [aluno_id]).get(aluno_id),
            motivos_laranja=exf.MOTIVOS_LARANJA, status_rotulo=exf.STATUS_ROTULO)
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/aluno/<int:aluno_id>/inicio-laranja", methods=["POST"])
@login_required
def marcar_inicio_laranja(aluno_id):
    """Professor libera (ou retira) o primeiro exame direto para Laranja.

    Regra da associação: faixa preta de jiu-jitsu ou formado em Educação
    Física. O sistema não tem como deduzir isso — o professor identifica.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    voltar = url_for("exame_faixa.historico_aluno", aluno_id=aluno_id,
                     **({"academia_id": request.form.get("academia_id")} if request.form.get("academia_id") else {}))
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        cur.execute("SELECT id, nome, id_academia FROM alunos WHERE id = %s", (aluno_id,))
        aluno = cur.fetchone()
        if not aluno or aluno["id_academia"] not in [a["id"] for a in esc["academias"]]:
            flash("Aluno não encontrado.", "danger")
            return redirect(url_for("exame_faixa.alunos"))
        motivo = (request.form.get("motivo") or "").strip()
        if motivo and motivo not in exf.MOTIVOS_LARANJA:
            motivo = motivo[:80]
        cur.execute(
            """INSERT INTO exame_faixa_aluno (aluno_id, inicio_laranja, motivo, marcado_por)
               VALUES (%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE inicio_laranja = VALUES(inicio_laranja), motivo = VALUES(motivo),
                                       marcado_por = VALUES(marcado_por)""",
            (aluno_id, 1 if motivo else 0, motivo or None, current_user.id))
        conn.commit()
        flash(f"{aluno['nome']}: primeiro exame liberado para Laranja ({motivo})." if motivo
              else f"{aluno['nome']}: liberação para Laranja retirada.", "success")
        return redirect(voltar)
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/aluno/<int:aluno_id>/destino", methods=["POST"])
@login_required
def definir_destino(aluno_id):
    """O professor escolhe a faixa de destino do próximo exame do aluno.

    Passa por cima da regra de idade ("pela idade iria para Amarela, mas vai
    para Azul"). Vale enquanto o aluno estiver na faixa atual. Se ele já estiver
    inscrito num exame ainda sem notas, a inscrição e a fatura em aberto mudam
    junto.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    voltar = request.form.get("voltar") or ""
    if not (voltar.startswith("/exame-faixa/") and "//" not in voltar):
        voltar = url_for("exame_faixa.alunos")
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        aluno = _aluno_do_escopo(cur, esc, aluno_id)
        if not aluno:
            flash("Aluno não encontrado.", "danger")
            return redirect(voltar)
        prog = exf.programa(cur, exf.associacao_da_academia(cur, aluno["id_academia"]))
        exf.usar_faixa_do_programa(cur, aluno, prog)   # faixa de judô, não a principal
        nat = next((x for x in prog if x["graduacao_de_id"] == aluno.get("graduacao_id")), None)
        if not nat:
            flash(f"{aluno['nome']}: a faixa atual não tem exame no programa.", "warning")
            return redirect(voltar)
        pid = request.form.get("programa_id", type=int)
        motivo = (request.form.get("motivo") or "").strip()[:160] or None
        alvo = next((x for x in prog if x["id"] == pid), None) if pid else None
        if pid and (not alvo or alvo["indice"] < nat["indice"]):
            flash("Faixa de destino inválida para a faixa atual do aluno.", "danger")
            return redirect(voltar)
        cur.execute(
            """INSERT INTO exame_faixa_aluno (aluno_id, inicio_laranja, destino_programa_id, destino_de_id,
                                              destino_motivo, destino_por, destino_em)
               VALUES (%s, 0, %s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE destino_programa_id = VALUES(destino_programa_id),
                   destino_de_id = VALUES(destino_de_id), destino_motivo = VALUES(destino_motivo),
                   destino_por = VALUES(destino_por), destino_em = VALUES(destino_em)""",
            (aluno_id, alvo["id"] if alvo else None, aluno["graduacao_id"] if alvo else None,
             motivo if alvo else None, current_user.id))
        avisos = _reaplicar_destino(cur, aluno, prog)
        conn.commit()
        if alvo:
            msg = f"{aluno['nome']}: próximo exame para {alvo['para']} (escolha do professor)."
        else:
            msg = f"{aluno['nome']}: volta a valer a regra de idade."
        flash(" ".join([msg] + avisos), "success" if not avisos else "warning")
        return redirect(voltar)
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Definir destino do exame")
        flash(f"Não foi possível salvar: {e}", "danger")
        return redirect(voltar)
    finally:
        cur.close()
        conn.close()


def _graduacao_judo_sql(cur, alias="a"):
    """Expressão SQL da faixa de JUDÔ do aluno (o exame é só de judô)."""
    from utils import graduacao_modalidade as grad_mod
    grad_mod.tem_coluna(cur)
    return grad_mod.sql_graduacao_na_modalidade(grad_mod.id_modalidade_judo(cur), alias)


def _aluno_do_escopo(cur, esc, aluno_id):
    """O aluno, se for de uma academia do escopo — principal ou vinculada.

    Vinculado, ele vem com `id_academia` da academia do escopo, que é por onde
    ela o enxerga e decide sobre ele.
    """
    cur.execute("SELECT * FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cur.fetchone()
    if not aluno:
        return None
    # A academia escolhida primeiro; depois qualquer outra que o usuário enxerga.
    ids = _ids_academias_escopo(esc)
    ids += [a["id"] for a in esc["academias"] if a["id"] not in ids]
    for aid in ids:
        if aluno["id_academia"] == aid or aluno_vinculado_a_academia(cur, aluno_id, aid):
            aluno["id_academia"] = aid
            return aluno
    return None


def _pode_liberar(esc):
    """Liberar sem idade/carência é decisão do responsável, não do professor."""
    return bool(esc) and _tem("gestor_academia", "gestor_associacao", "admin")


@bp_exame_faixa.route("/aluno/<int:aluno_id>/liberar", methods=["POST"])
@login_required
def liberar_aluno(aluno_id):
    """O responsável da academia libera o aluno para o exame sem cumprir idade
    mínima ou carência — ou desfaz a liberação (`desfazer=1`).

    Vale enquanto o aluno estiver na faixa atual; promovido, volta a regra.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    voltar = request.form.get("voltar") or ""
    if not (voltar.startswith("/exame-faixa/") and "//" not in voltar):
        voltar = url_for("exame_faixa.alunos")
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        if not _pode_liberar(esc):
            flash("Só o responsável da academia pode liberar aluno para o exame.", "danger")
            return redirect(voltar)
        aluno = _aluno_do_escopo(cur, esc, aluno_id)
        if not aluno:
            flash("Aluno não encontrado.", "danger")
            return redirect(voltar)
        if request.form.get("desfazer"):
            cur.execute(
                """UPDATE exame_faixa_aluno SET liberado_de_id = NULL, liberado_motivo = NULL,
                          liberado_por = NULL, liberado_em = NULL WHERE aluno_id = %s""", (aluno_id,))
            conn.commit()
            flash(f"{aluno['nome']}: liberação desfeita — volta a valer idade e carência.", "success")
            return redirect(voltar)
        # A liberação vale para a faixa de JUDÔ (é ela que o exame confere).
        exf.usar_faixa_do_programa(
            cur, aluno, exf.programa(cur, exf.associacao_da_academia(cur, aluno["id_academia"])))
        if not aluno.get("graduacao_id"):
            flash(f"{aluno['nome']}: cadastre a faixa de judô antes de liberar.", "warning")
            return redirect(voltar)
        motivo = (request.form.get("motivo") or "").strip()[:160]
        if not motivo:
            flash("Informe o motivo da liberação.", "warning")
            return redirect(voltar)
        cur.execute(
            """INSERT INTO exame_faixa_aluno (aluno_id, inicio_laranja, liberado_de_id, liberado_motivo,
                                              liberado_por, liberado_em)
               VALUES (%s, 0, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE liberado_de_id = VALUES(liberado_de_id),
                   liberado_motivo = VALUES(liberado_motivo), liberado_por = VALUES(liberado_por),
                   liberado_em = VALUES(liberado_em)""",
            (aluno_id, aluno["graduacao_id"], motivo, current_user.id))
        conn.commit()
        flash(f"{aluno['nome']} liberado para o exame. Já pode ser inscrito.", "success")
        return redirect(voltar)
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Liberar aluno para o exame")
        flash(f"Não foi possível salvar: {e}", "danger")
        return redirect(voltar)
    finally:
        cur.close()
        conn.close()


def _reaplicar_destino(cur, aluno, prog):
    """Leva a nova faixa de destino às inscrições abertas do aluno.

    Só mexe em inscrição sem nota lançada; a ficha só sorteada é refeita no
    dia (apagada aqui). Fatura em aberto passa ao valor da nova promoção
    (o PIX antigo é cancelado e outro é emitido); fatura paga não muda.
    Devolve avisos para quem salvou.
    """
    avisos = []
    cur.execute(
        """SELECT i.*, ec.exame_data_prova, ec.data_fim, ec.nome AS evento_nome, ec.status AS evento_status
           FROM eventos_competicoes_inscricoes i
           JOIN eventos_competicoes ec ON ec.id = i.evento_id AND ec.exame_faixa = 1
           WHERE i.aluno_id = %s AND i.status = 'enviada'""", (aluno["id"],))
    for insc in cur.fetchall():
        prova = _data_exame(insc)
        if (prova and prova < date.today()) or insc.get("evento_status") == "finalizado":
            continue
        cur.execute("SELECT id, notas, resultado, aluno_graduacao_id FROM exame_faixa_avaliacao WHERE inscricao_id = %s",
                    (insc["id"],))
        av = cur.fetchone()
        if av and (av["aluno_graduacao_id"] or av["resultado"] != "pendente"
                   or (av.get("notas") and av["notas"] not in ("{}", "null"))):
            if av["resultado"] == "pendente":
                avisos.append(f"A ficha de {insc['evento_nome']} já tem notas — a faixa dela não mudou.")
            continue
        sit = exf.situacao(cur, aluno, prog, data_ref=_data_exame(insc))
        p = sit["promocao"]
        dados = _dados(insc)
        ef = dados.setdefault("exame_faixa", {})
        if not p or ef.get("programa_id") == p["id"] and ef.get("graduacao_de_id") == p["graduacao_de_id"]:
            continue
        ef.update({"programa_id": p["id"], "graduacao_de_id": p["graduacao_de_id"],
                   "graduacao_para_id": p["graduacao_para_id"], "de": p["de"], "para": p["para"],
                   "valor": float(p["valor"]) if p.get("valor") is not None else None,
                   "salto": p.get("salto_motivo"), "escolha_professor": bool(p.get("escolha"))})
        cur.execute("UPDATE eventos_competicoes_inscricoes SET dados_form = %s WHERE id = %s",
                    (json.dumps(dados, ensure_ascii=False, default=str), insc["id"]))
        if av:
            cur.execute("DELETE FROM exame_faixa_avaliacao WHERE id = %s", (av["id"],))
        cid = ef.get("cobranca_id")
        if cid:
            cur.execute("SELECT * FROM cobranca_avulsa WHERE id = %s", (cid,))
            ca = cur.fetchone()
            novo = float(p.get("valor") or 0)
            if ca and ca["status"] == "pago":
                if float(ca["valor"] or 0) != novo:
                    avisos.append(f"A fatura de {insc['evento_nome']} já estava paga ({exf.moeda(ca['valor'])}); "
                                  f"a nova promoção custa {exf.moeda(novo)} — acerte a diferença no financeiro.")
            elif ca and ca["status"] in ("pendente", "atrasado") and float(ca["valor"] or 0) != novo:
                if ca.get("asaas_payment_id"):
                    try:
                        from blueprints.financeiro import routes as fin
                        fin._cancelar_no_gateway(fin._gateway_config_academia(ca["id_academia"]),
                                                 ca.get("gateway"), ca.get("asaas_payment_id"))
                    except Exception:
                        current_app.logger.exception("Cancelar PIX antigo da fatura %s", cid)
                cur.execute(
                    """UPDATE cobranca_avulsa SET valor = %s, descricao = %s, asaas_payment_id = NULL,
                              asaas_tipo = NULL, asaas_boleto_url = NULL, asaas_pix_qrcode = NULL,
                              asaas_pix_copia_cola = NULL, gateway = NULL
                       WHERE id = %s""",
                    (novo, f"Exame de faixa — {p['de']} → {p['para']}"[:255], cid))
                _emitir_online(cur, cid, forcar=True)
                avisos.append(f"Fatura de {insc['evento_nome']} atualizada para {exf.moeda(novo)}.")
    return avisos


# ------------------------------------------------ vídeos e documentos
PASTA_DOCS = "exame_faixa_docs"


@bp_exame_faixa.route("/materiais", methods=["GET", "POST"])
@login_required
def materiais():
    """Vídeos das técnicas e dos katas, e documentos do programa.

    Um vídeo por técnica: o de O-soto-gari aparece em toda faixa que a cobra.
    Só a associação (dona do programa) edita; academia e aluno assistem.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    aba = request.values.get("aba") or "nage"
    if aba not in ("nage", "katame", "kaeshi", "renraku", "kata", "documentos"):
        aba = "nage"
    aqui = url_for("exame_faixa.materiais", aba=aba)
    try:
        esc, erro = _exige_escopo(cur)
        if erro:
            return erro
        if not esc.get("pode_editar"):
            flash("Só a associação cadastra vídeos e documentos do programa.", "warning")
            return redirect(url_for("exame_faixa.programa"))
        id_assoc = esc["id_assoc"]
        prog = exf.programa(cur, id_assoc)

        if request.method == "POST":
            acao = request.form.get("acao")
            if acao == "video":
                grupo = request.form.get("grupo") or "nage"
                nome = (request.form.get("nome") or "").strip()[:160]
                url = "" if request.form.get("remover") else (request.form.get("url") or "").strip()[:500]
                obs = (request.form.get("observacao") or "").strip()[:255] or None
                if not nome:
                    flash("Técnica não informada.", "danger")
                elif not url:
                    cur.execute("DELETE FROM exame_faixa_video WHERE id_associacao = %s AND chave = %s",
                                (id_assoc, exf.chave_item(grupo, nome)))
                    conn.commit()
                    flash(f"Vídeo de {nome} removido.", "info")
                elif not url.lower().startswith(("http://", "https://")):
                    flash("Cole o link completo do vídeo (começando com https://).", "danger")
                else:
                    cur.execute(
                        """INSERT INTO exame_faixa_video (id_associacao, grupo, chave, nome, url, observacao, atualizado_por)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE grupo = VALUES(grupo), nome = VALUES(nome), url = VALUES(url),
                               observacao = VALUES(observacao), atualizado_por = VALUES(atualizado_por)""",
                        (id_assoc, grupo, exf.chave_item(grupo, nome), nome, url, obs, current_user.id))
                    conn.commit()
                    aviso = "" if exf.embed_video(url) else " (abre numa aba nova — o player embutido aceita YouTube, Vimeo e Google Drive)"
                    flash(f"Vídeo de {nome} salvo{aviso}.", "success")
                return redirect(aqui + "#v-" + exf.chave_item(grupo, nome))
            if acao == "documento":
                titulo = (request.form.get("titulo") or "").strip()[:160]
                link = (request.form.get("url") or "").strip()[:500] or None
                programa_id = request.form.get("programa_id", type=int)
                if programa_id and programa_id not in [p["id"] for p in prog]:
                    programa_id = None
                arquivo = None
                f = request.files.get("arquivo")
                if f and f.filename:
                    from utils.upload_seguro import UploadInvalido, nome_seguro, validar_upload
                    import os
                    try:
                        ext = validar_upload(f, categorias=["pdf", "imagem", "planilha"])
                    except UploadInvalido as e:
                        flash(f"Arquivo recusado: {e}", "danger")
                        return redirect(aqui)
                    arquivo = nome_seguro(f"exf_{id_assoc}", ext)
                    pasta = os.path.join(current_app.root_path, "static", "uploads", PASTA_DOCS)
                    os.makedirs(pasta, exist_ok=True)
                    f.save(os.path.join(pasta, arquivo))
                if not titulo or not (arquivo or link):
                    flash("Informe o título e envie um arquivo ou cole um link.", "danger")
                    return redirect(aqui)
                if link and not link.lower().startswith(("http://", "https://")):
                    flash("O link precisa começar com https://.", "danger")
                    return redirect(aqui)
                cur.execute("""INSERT INTO exame_faixa_documento (id_associacao, titulo, arquivo, url, programa_id, enviado_por)
                               VALUES (%s,%s,%s,%s,%s,%s)""",
                            (id_assoc, titulo, arquivo, link, programa_id, current_user.id))
                conn.commit()
                flash(f"Documento “{titulo}” adicionado.", "success")
                return redirect(aqui)
            if acao == "remover_documento":
                doc_id = request.form.get("documento_id", type=int)
                cur.execute("SELECT * FROM exame_faixa_documento WHERE id = %s AND id_associacao = %s", (doc_id, id_assoc))
                d = cur.fetchone()
                if d:
                    cur.execute("DELETE FROM exame_faixa_documento WHERE id = %s", (doc_id,))
                    conn.commit()
                    if d.get("arquivo"):
                        import os
                        try:
                            os.remove(os.path.join(current_app.root_path, "static", "uploads", PASTA_DOCS, d["arquivo"]))
                        except OSError:
                            pass
                    flash(f"Documento “{d['titulo']}” removido.", "info")
                return redirect(aqui)
            flash("Ação desconhecida.", "warning")
            return redirect(aqui)

        videos = exf.videos_da_associacao(cur, id_assoc)
        listas = {g: exf.tecnicas_do_programa(prog, g) for g in ("nage", "katame", "kaeshi", "renraku")}
        listas["kata"] = [{"nome": k["nome"], "chave": exf.chave_video(k["chave"]),
                           "faixas": [k["traducao"]]} for k in exf.KATAS]
        for g, lista in listas.items():
            for t in lista:
                t["video"] = videos.get(t["chave"])
        cobertura = {g: (sum(1 for t in l if t["video"]), len(l)) for g, l in listas.items()}
        documentos = exf.documentos_da_associacao(cur, id_assoc, todos=True)
        nome_promo = {p["id"]: f"{p['de']} → {p['para']}" for p in prog}
        filtro = request.args.get("filtro")
        return render_template(
            "exame_faixa/materiais.html", esc=esc, abas=_abas(esc, "programa"), aba=aba,
            listas=listas, cobertura=cobertura, documentos=documentos, prog=prog,
            nome_promo=nome_promo, filtro=filtro, pasta_docs=PASTA_DOCS)
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.route("/meus-exames")
@login_required
def meus_exames():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        aluno, alunos_lista, modo = _aluno_alvo(cur)
        if not aluno:
            flash("Nenhum aluno vinculado a este usuário.", "warning")
            return redirect(url_for("painel.home"))
        exf.usar_faixa_do_programa(
            cur, aluno, exf.programa(cur, exf.associacao_da_academia(cur, aluno.get("id_academia"))))
        cur.execute("SELECT faixa FROM graduacao WHERE id = %s", (aluno.get("graduacao_id") or 0,))
        aluno["faixa"] = (cur.fetchone() or {}).get("faixa")
        itens, graduacoes, resumo = _historico(cur, aluno["id"], so_fechadas=True)
        return render_template(
            "exame_faixa/historico.html", gestao=False, aluno=aluno, alunos=alunos_lista,
            modo=modo, itens=itens, graduacoes=graduacoes, resumo=resumo)
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.app_template_global("exame_faixa_a_promover")
def exame_faixa_a_promover(aluno_id):
    """Exames aprovados do aluno ainda sem a faixa registrada (aviso na ficha)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT av.id, av.media_geral, gp.faixa AS para, ec.nome AS evento_nome
               FROM exame_faixa_avaliacao av
               LEFT JOIN graduacao gp ON gp.id = av.graduacao_para_id
               LEFT JOIN eventos_competicoes ec ON ec.id = av.evento_id
               WHERE av.aluno_id = %s AND av.resultado = 'aprovado' AND av.aluno_graduacao_id IS NULL""",
            (aluno_id,))
        out = cur.fetchall()
        for r in out:
            r["para"] = exf.nome_faixa(r["para"])
        return out
    except Exception:
        return []
    finally:
        cur.close()
        conn.close()


@bp_exame_faixa.app_template_filter("nota_br")
def _filtro_nota(v):
    return exf.nota_fmt(v)
