# -*- coding: utf-8 -*-
"""
Blueprint Competições — módulo de operações de judô (chaves, súmulas, placar, resultados).

MÓDULO PREPARADO PARA MIGRAÇÃO
--------------------------------
Este blueprint é intencionalmente isolado do restante do sistema.
Todas as rotas são acessadas a partir do painel interno de cada competição
(menu_competicao.html), sem entrada direta pelo menu principal da associação.

Para migrar para outro sistema basta exportar:
  - blueprints/competicoes/routes.py
  - templates/competicoes/
  - utils/judo_chaves_inteligentes.py
  - utils/judo_bracket_visual.py
  - static/css/judo_chave_visual.css
  - static/js/judo_chave_visual.js

Dependências externas (compartilhadas):
  - Tabelas: eventos_competicoes, judo_lutas, categorias, academias
  - Blueprint eventos_competicoes (placar de lutas em tempo real)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, abort, jsonify
from flask_login import login_required, current_user
from config import get_db_connection

bp_competicoes = Blueprint("competicoes", __name__, url_prefix="/competicoes")


def _get_ids_academias(cur):
    """Ids das academias do usuário (modo academia)."""
    cur.execute("""
        SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id
    """, (current_user.id,))
    vinculadas = [r["academia_id"] for r in cur.fetchall()]
    if vinculadas:
        return vinculadas
    if session.get("modo_painel") == "academia" and getattr(current_user, "id_academia", None):
        return [current_user.id_academia]
    return []


def _evento_fetch_por_assoc(cur, evento_id, id_assoc):
    """Uma linha de eventos_competicoes para telas do módulo competições (menu, título)."""
    try:
        cur.execute(
            """
            SELECT id, nome, tipo, categorias_modo
            FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
            """,
            (evento_id, id_assoc),
        )
    except Exception:
        cur.execute(
            "SELECT id, nome, tipo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc),
        )
    ev = cur.fetchone()
    if ev is not None and "categorias_modo" not in ev:
        ev["categorias_modo"] = "padrao"
    return ev


@bp_competicoes.route("/")
@login_required
def index():
    """Redireciona para lista de competições (entrada pelo painel de cada competição)."""
    return redirect(url_for("eventos_competicoes.lista_competicoes"))


@bp_competicoes.route("/inscricoes")
@login_required
def inscricoes():
    """Inscrições para competições — redireciona para lista de eventos (competições)."""
    return redirect(url_for("eventos_competicoes.lista_competicoes"))


@bp_competicoes.route("/categorias")
@login_required
def categorias():
    """Organização de categorias de peso/idade (judô)."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max, descricao
            FROM categorias
            WHERE ativo = 1
            ORDER BY genero, id_classe, peso_min
        """)
        categorias_list = cur.fetchall()
        return render_template("competicoes/categorias.html",
            categorias=categorias_list,
            back_url=url_for("competicoes.index"))
    finally:
        cur.close()
        conn.close()


def _evento_valido_competicoes(cur, evento_id):
    """Retorna evento se o usuário tem acesso (associação ou academia)."""
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    ids_acad = _get_ids_academias(cur)
    if not id_assoc and ids_acad:
        cur.execute("SELECT id_associacao FROM academias WHERE id = %s LIMIT 1", (ids_acad[0],))
        r = cur.fetchone()
        id_assoc = r["id_associacao"] if r else None
    return _evento_fetch_por_assoc(cur, evento_id, id_assoc)


def _back_nav_evento_competicoes(evento_id, cur):
    """Voltar de telas escopadas a um evento: painel (associação) ou lista de competições (academia)."""
    if session.get("modo_painel") == "associacao":
        return url_for("eventos_competicoes.painel_competicao", evento_id=evento_id)
    aid = getattr(current_user, "id_academia", None) or request.args.get("academia_id", type=int)
    if aid is None:
        ids = _get_ids_academias(cur)
        if ids:
            aid = ids[0]
    if aid:
        return url_for("eventos_competicoes.lista_competicoes", academia_id=aid)
    return url_for("eventos_competicoes.lista_competicoes")


@bp_competicoes.route("/chaves")
@login_required
def chaves_selecionar():
    """Selecionar competição para gerar chaves."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)

        if modo == "associacao" and id_assoc:
            cur.execute("""
                SELECT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                       (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                FROM eventos_competicoes ec
                WHERE ec.id_associacao = %s AND ec.tipo = 'competicao'
                ORDER BY ec.data_fim DESC
            """, (id_assoc,))
            eventos = cur.fetchall()
        elif modo == "academia" and ids_acad:
            ph = ",".join(["%s"] * len(ids_acad))
            cur.execute(f"""
                SELECT DISTINCT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                       (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                FROM eventos_competicoes ec
                INNER JOIN academias ac ON ac.id_associacao = ec.id_associacao AND ac.id IN ({ph})
                WHERE ec.tipo = 'competicao'
                ORDER BY ec.data_fim DESC
            """, tuple(ids_acad))
            eventos = cur.fetchall()
        else:
            eventos = []

        return render_template("competicoes/chaves_selecionar.html",
            eventos=eventos,
            back_url=url_for("competicoes.index"))
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/chaves/<int:evento_id>", methods=["GET", "POST"])
@login_required
def chaves_evento(evento_id):
    """Chaves por categoria — gerar lutas a partir dos inscritos."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    import json

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        evento = _evento_valido_competicoes(cur, evento_id)
        if not evento:
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("competicoes.chaves_selecionar"))

        # POST: Gerar chave para uma categoria
        if request.method == "POST":
            categoria_nome = request.form.get("categoria_nome", "").strip()
            if not categoria_nome:
                flash("Categoria não informada.", "danger")
                return redirect(url_for("competicoes.chaves_evento", evento_id=evento_id))

            cur.execute("""
                SELECT i.id, i.dados_form, ac.nome as academia_nome, a.nome as aluno_nome
                FROM eventos_competicoes_inscricoes i
                INNER JOIN academias ac ON ac.id = i.academia_id
                LEFT JOIN alunos a ON a.id = i.aluno_id
                WHERE i.evento_id = %s AND (i.status = 'enviada' OR (i.inclusao_avulsa = 1 AND i.aluno_id IS NULL))
            """, (evento_id,))
            rows = cur.fetchall()
            inscritos_cat = []
            for r in rows:
                dados = {}
                if r.get("dados_form"):
                    try:
                        dados = json.loads(r["dados_form"]) if isinstance(r["dados_form"], str) else (r["dados_form"] or {})
                    except Exception:
                        pass
                cat = dados.get("categoria") or "-"
                if cat == categoria_nome:
                    nome = dados.get("nome") or r.get("aluno_nome") or "Avulso"
                    academia = dados.get("academia") or r.get("academia_nome") or "-"
                    inscritos_cat.append({"nome": nome, "academia": academia})

            if len(inscritos_cat) < 2:
                flash(f"Categoria '{categoria_nome}' precisa de pelo menos 2 inscritos. Inscritos: {len(inscritos_cat)}.", "warning")
                return redirect(url_for("competicoes.chaves_evento", evento_id=evento_id))

            cur.execute("""
                DELETE FROM judo_lutas
                WHERE evento_id = %s
                  AND (categoria_nome = %s OR categoria_id IN (SELECT id FROM categorias WHERE nome_categoria = %s AND ativo = 1))
            """, (evento_id, categoria_nome, categoria_nome))
            conn.commit()

            from utils.judo_chaves_inteligentes import gerar_chave_inteligente, limpar_bo3_series_categoria

            limpar_bo3_series_categoria(cur, conn, evento_id, categoria_nome)

            cur.execute("SELECT id FROM categorias WHERE nome_categoria = %s AND ativo = 1 LIMIT 1", (categoria_nome,))
            cat_row = cur.fetchone()
            cat_id = cat_row["id"] if cat_row else None

            try:
                criadas, msg = gerar_chave_inteligente(cur, conn, evento_id, cat_id, categoria_nome, inscritos_cat)
                flash(msg, "success")
            except Exception as e:
                err = str(e)
                if "luta_origem_branco_id" in err or "Unknown column" in err or "1054" in err or "judo_chave_feed" in err or "judo_bo3_series" in err:
                    flash(
                        "Execute as migrações de chave: migrations/add_bracket_judo.sql e migrations/add_chave_inteligente_judo.sql",
                        "danger",
                    )
                else:
                    flash(f"Erro ao gerar chave: {e}", "danger")
            return redirect(url_for("competicoes.chaves_evento", evento_id=evento_id))

        # GET: Listar categorias com inscritos e lutas
        cur.execute("""
            SELECT i.id, i.dados_form, ac.nome as academia_nome, a.nome as aluno_nome
            FROM eventos_competicoes_inscricoes i
            INNER JOIN academias ac ON ac.id = i.academia_id
            LEFT JOIN alunos a ON a.id = i.aluno_id
            WHERE i.evento_id = %s AND (i.status = 'enviada' OR (i.inclusao_avulsa = 1 AND i.aluno_id IS NULL))
        """, (evento_id,))
        rows = cur.fetchall()
        por_categoria = {}
        for r in rows:
            dados = {}
            if r.get("dados_form"):
                try:
                    dados = json.loads(r["dados_form"]) if isinstance(r["dados_form"], str) else (r["dados_form"] or {})
                except Exception:
                    pass
            cat = dados.get("categoria") or "Sem categoria"
            if cat not in por_categoria:
                por_categoria[cat] = []
            nome = dados.get("nome") or r.get("aluno_nome") or "Avulso"
            academia = dados.get("academia") or r.get("academia_nome") or "-"
            por_categoria[cat].append({"nome": nome, "academia": academia})

        cur.execute("""
            SELECT jl.*, COALESCE(jl.categoria_nome, c.nome_categoria) as cat_nome
            FROM judo_lutas jl
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.evento_id = %s
            ORDER BY COALESCE(jl.categoria_nome, c.nome_categoria), jl.id
        """, (evento_id,))
        lutas = cur.fetchall()
        lutas_por_cat = {}
        for l in lutas:
            cn = l.get("cat_nome") or "Outras"
            if cn not in lutas_por_cat:
                lutas_por_cat[cn] = []
            lutas_por_cat[cn].append(l)

        categorias_com_inscritos = list(por_categoria.keys())
        if not categorias_com_inscritos:
            agrupado = {"MASCULINO": {}, "FEMININO": {}}
            slug_por_categoria = {}
        else:
            placeholders = ",".join(["%s"] * len(categorias_com_inscritos))
            cur.execute(f"""
                SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max
                FROM categorias
                WHERE ativo = 1 AND nome_categoria IN ({placeholders})
                ORDER BY genero, id_classe, peso_min
            """, tuple(categorias_com_inscritos))
            cat_rows = {r["nome_categoria"]: r for r in cur.fetchall()}
            agrupado = {"MASCULINO": {}, "FEMININO": {}}
            for idx, cat_nome in enumerate(categorias_com_inscritos):
                count = len(por_categoria[cat_nome])
                c = cat_rows.get(cat_nome)
                if c:
                    genero = (c.get("genero") or "MASCULINO").strip().upper()
                    if genero not in ("MASCULINO", "FEMININO"):
                        genero = "FEMININO" if "FEM" in genero else "MASCULINO"
                else:
                    genero = "MASCULINO"
                id_classe = (c.get("id_classe") or "Outros").strip() if c else "Outros"
                if c and c.get("peso_max") is not None:
                    peso_label = "-%d" % int(float(c["peso_max"]))
                elif c and c.get("peso_min") is not None:
                    peso_label = "+%d" % int(float(c["peso_min"]))
                else:
                    peso_label = (c.get("categoria") or cat_nome)[:20] if c else cat_nome[:20]
                tem_chave = cat_nome in lutas_por_cat and len(lutas_por_cat[cat_nome]) > 0
                if id_classe not in agrupado[genero]:
                    agrupado[genero][id_classe] = []
                slug = ("".join(x if x.isalnum() or x in "-_" else "_" for x in cat_nome)[:50] or "cat") + "_%d" % idx
                agrupado[genero][id_classe].append({
                    "nome_categoria": cat_nome, "peso_label": peso_label, "count": count,
                    "tem_chave": tem_chave, "slug": slug,
                })
            ordem_classe = ("SUB 5", "SUB 7", "SUB 9", "SUB 11", "SUB 13", "SUB 15", "CADETE", "JÚNIOR", "JUNIOR", "SÉNIOR", "SENIOR", "Outros")
            for g in ("MASCULINO", "FEMININO"):
                agrupado[g] = dict(sorted(agrupado[g].items(), key=lambda x: (ordem_classe.index(x[0].upper()) if x[0].upper() in ordem_classe else 99, x[0])))
            slug_por_categoria = {}
            for g in ("MASCULINO", "FEMININO"):
                for lista in agrupado[g].values():
                    for item in lista:
                        slug_por_categoria[item["nome_categoria"]] = item["slug"]

        return render_template(
            "competicoes/chaves_evento.html",
            evento=evento,
            por_categoria=por_categoria,
            lutas_por_cat=lutas_por_cat,
            agrupado=agrupado,
            slug_por_categoria=slug_por_categoria,
            back_url=_back_nav_evento_competicoes(evento_id, cur),
        )
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/sumulas")
@login_required
def sumulas_selecionar():
    """Selecionar competição para gerar súmulas."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)

        if modo == "associacao" and id_assoc:
            cur.execute("""
                SELECT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                       (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                FROM eventos_competicoes ec
                WHERE ec.id_associacao = %s AND ec.tipo = 'competicao'
                ORDER BY ec.data_fim DESC
            """, (id_assoc,))
        elif modo == "academia" and ids_acad:
            ph = ",".join(["%s"] * len(ids_acad))
            cur.execute(f"""
                SELECT DISTINCT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                       (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                FROM eventos_competicoes ec
                INNER JOIN academias ac ON ac.id_associacao = ec.id_associacao AND ac.id IN ({ph})
                WHERE ec.tipo = 'competicao'
                ORDER BY ec.data_fim DESC
            """, tuple(ids_acad))
        else:
            cur.execute("SELECT 1")
            cur.fetchall()

        eventos = cur.fetchall()
        return render_template("competicoes/sumulas_selecionar.html",
            eventos=eventos,
            back_url=url_for("competicoes.index"))
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/sumulas/<int:evento_id>")
@login_required
def sumulas_evento(evento_id):
    """Súmulas por categoria de um evento."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)
        if not id_assoc and ids_acad:
            cur.execute("SELECT id_associacao FROM academias WHERE id = %s LIMIT 1", (ids_acad[0],))
            r = cur.fetchone()
            id_assoc = r["id_associacao"] if r else None
        evento = _evento_fetch_por_assoc(cur, evento_id, id_assoc)
        if not evento:
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("competicoes.sumulas_selecionar"))

        cur.execute("""
            SELECT c.id, c.nome_categoria, c.categoria,
                   (SELECT COUNT(*) FROM judo_lutas jl WHERE jl.evento_id = %s AND jl.categoria_id = c.id) as total_lutas
            FROM categorias c
            WHERE c.id IN (SELECT DISTINCT categoria_id FROM judo_lutas WHERE evento_id = %s AND categoria_id IS NOT NULL)
            ORDER BY c.nome_categoria
        """, (evento_id, evento_id))
        categorias = cur.fetchall()

        cur.execute("""
            SELECT jl.*, c.nome_categoria
            FROM judo_lutas jl
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.evento_id = %s
            ORDER BY COALESCE(jl.categoria_id, 999), jl.created_at
        """, (evento_id,))
        lutas = cur.fetchall()

        return render_template(
            "competicoes/sumulas_evento.html",
            evento=evento,
            categorias=categorias,
            lutas=lutas,
            back_url=_back_nav_evento_competicoes(evento_id, cur),
        )
    finally:
        cur.close()
        conn.close()


def _categorias_com_lutas_evento(cur, evento_id):
    cur.execute(
        """
        SELECT DISTINCT COALESCE(jl.categoria_nome, c.nome_categoria) AS nome
        FROM judo_lutas jl
        LEFT JOIN categorias c ON c.id = jl.categoria_id
        WHERE jl.evento_id = %s AND COALESCE(jl.categoria_nome, c.nome_categoria) IS NOT NULL
        ORDER BY nome
        """,
        (evento_id,),
    )
    return [r["nome"] for r in cur.fetchall() if r.get("nome")]


def _lutas_categoria_nome(cur, evento_id, categoria_nome):
    cur.execute(
        """
        SELECT jl.*, COALESCE(jl.categoria_nome, c.nome_categoria) AS nome_categoria
        FROM judo_lutas jl
        LEFT JOIN categorias c ON c.id = jl.categoria_id
        WHERE jl.evento_id = %s
          AND (jl.categoria_nome = %s OR c.nome_categoria = %s)
        ORDER BY jl.round, jl.posicao_rodada, jl.id
        """,
        (evento_id, categoria_nome, categoria_nome),
    )
    return cur.fetchall()


def _tpl_controle_competicoes():
    u = url_for("eventos_competicoes.placar_judo_controle", luta_id=0)
    return u.replace("/0/", "/__LID__/")


@bp_competicoes.route("/chave-visual/<int:evento_id>")
@login_required
def chave_visual_evento(evento_id):
    """Chave eliminatória interativa: abrir placar por luta; vencedor avança (dados já propagados no backend)."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    categoria_nome = request.args.get("categoria", "").strip()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = _resolver_id_associacao_sumula(cur)
        cur.execute(
            "SELECT id, nome, tipo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc),
        )
        evento = cur.fetchone()
        if not evento:
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("competicoes.placar_selecionar"))
        if evento.get("tipo") != "competicao":
            flash("Use competições de judô.", "warning")
            return redirect(url_for("competicoes.placar_selecionar"))

        cats = _categorias_com_lutas_evento(cur, evento_id)
        if not categoria_nome and len(cats) == 1:
            categoria_nome = cats[0]
        if not categoria_nome and cats:
            return render_template(
                "competicoes/chave_visual_escolher.html",
                evento=evento,
                categorias=cats,
                back_url=url_for("competicoes.placar_lista", evento_id=evento_id),
            )
        if not categoria_nome:
            flash("Não há lutas com categoria neste evento.", "warning")
            return redirect(url_for("competicoes.placar_lista", evento_id=evento_id))

        api_url = url_for("competicoes.chave_visual_api", evento_id=evento_id, categoria=categoria_nome)
        return render_template(
            "eventos_competicoes/placar_chave_interativa.html",
            evento=evento,
            categoria_nome=categoria_nome,
            api_url=api_url,
            controle_url_tpl=_tpl_controle_competicoes(),
            back_url=url_for("competicoes.placar_lista", evento_id=evento_id),
            url_placar_evento=url_for("eventos_competicoes.placar_judo_lista", evento_id=evento_id),
        )
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/chave-visual/<int:evento_id>/api")
@login_required
def chave_visual_api(evento_id):
    categoria_nome = request.args.get("categoria", "").strip()
    if not categoria_nome:
        return jsonify({"tipo": "vazio", "mensagem": "Categoria não informada.", "rounds": []})

    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        return jsonify({"erro": "Acesso negado"}), 403

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = _resolver_id_associacao_sumula(cur)
        cur.execute(
            "SELECT id FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc),
        )
        if not cur.fetchone():
            return jsonify({"erro": "Evento não encontrado"}), 404

        lutas = _lutas_categoria_nome(cur, evento_id, categoria_nome)
        from utils.judo_bracket_visual import montar_payload_chave_visual

        payload = montar_payload_chave_visual(lutas)
        return jsonify(payload)
    finally:
        cur.close()
        conn.close()


def _resolver_id_associacao_sumula(cur):
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    ids_acad = _get_ids_academias(cur)
    if not id_assoc and ids_acad:
        cur.execute("SELECT id_associacao FROM academias WHERE id = %s LIMIT 1", (ids_acad[0],))
        r = cur.fetchone()
        id_assoc = r["id_associacao"] if r else None
    return id_assoc


def _evento_para_sumula(cur, evento_id, id_assoc):
    cur.execute(
        """
        SELECT ec.id, ec.nome, ec.data_inicio, ec.data_fim, ec.descricao,
               a.nome AS associacao_nome
        FROM eventos_competicoes ec
        INNER JOIN associacoes a ON a.id = ec.id_associacao
        WHERE ec.id = %s AND ec.id_associacao = %s
        """,
        (evento_id, id_assoc),
    )
    return cur.fetchone()


@bp_competicoes.route("/sumulas/<int:evento_id>/luta/<int:luta_id>/imprimir")
@login_required
def sumula_luta_imprimir(evento_id, luta_id):
    """Súmula estilo CBJ (A4) para uma luta — impressão / PDF pelo navegador."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = _resolver_id_associacao_sumula(cur)
        if not id_assoc:
            abort(403)
        evento = _evento_para_sumula(cur, evento_id, id_assoc)
        if not evento:
            abort(404)

        cur.execute(
            """
            SELECT jl.*, c.nome_categoria
            FROM judo_lutas jl
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.id = %s AND jl.evento_id = %s
            """,
            (luta_id, evento_id),
        )
        luta = cur.fetchone()
        if not luta:
            abort(404)

        return render_template(
            "competicoes/sumula_cbj_impressao.html",
            evento=evento,
            lutas=[luta],
        )
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/sumulas/<int:evento_id>/imprimir-todas")
@login_required
def sumulas_evento_imprimir_todas(evento_id):
    """Todas as súmulas do evento (uma folha A4 por luta)."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = _resolver_id_associacao_sumula(cur)
        if not id_assoc:
            abort(403)
        evento = _evento_para_sumula(cur, evento_id, id_assoc)
        if not evento:
            abort(404)

        cur.execute(
            """
            SELECT jl.*, c.nome_categoria
            FROM judo_lutas jl
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.evento_id = %s
            ORDER BY COALESCE(jl.categoria_id, 999999), jl.round, jl.posicao_rodada, jl.id
            """,
            (evento_id,),
        )
        lutas = cur.fetchall()
        if not lutas:
            flash("Nenhuma luta nesta competição para imprimir.", "warning")
            return redirect(url_for("competicoes.sumulas_evento", evento_id=evento_id))

        return render_template(
            "competicoes/sumula_cbj_impressao.html",
            evento=evento,
            lutas=lutas,
        )
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/placar")
@login_required
def placar_selecionar():
    """Seleciona competição para acessar o placar de judô."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)

        if modo == "associacao":
            if not id_assoc:
                flash("Selecione a associação.", "warning")
                return redirect(url_for("associacao.gerenciamento_associacao"))
            try:
                cur.execute("""
                    SELECT ec.id, ec.nome, ec.tipo, ec.natureza, ec.data_inicio, ec.data_fim,
                           (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                    FROM eventos_competicoes ec
                    WHERE ec.id_associacao = %s AND ec.tipo = 'competicao'
                    ORDER BY ec.data_fim DESC
                """, (id_assoc,))
            except Exception as ex_pl:
                err_pl = str(ex_pl).lower()
                if "natureza" in err_pl or "1054" in err_pl or "unknown column" in err_pl:
                    cur.execute("""
                        SELECT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                               (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                        FROM eventos_competicoes ec
                        WHERE ec.id_associacao = %s AND ec.tipo = 'competicao'
                        ORDER BY ec.data_fim DESC
                    """, (id_assoc,))
                else:
                    raise
            eventos = cur.fetchall()
            for ev in eventos:
                if "natureza" not in ev:
                    ev["natureza"] = None
        elif modo == "academia":
            if not ids_acad:
                flash("Nenhuma academia vinculada.", "warning")
                return redirect(url_for("painel.home"))
            ph = ",".join(["%s"] * len(ids_acad))
            try:
                cur.execute(f"""
                    SELECT DISTINCT ec.id, ec.nome, ec.tipo, ec.natureza, ec.data_inicio, ec.data_fim,
                           (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                    FROM eventos_competicoes ec
                    INNER JOIN academias ac ON ac.id_associacao = ec.id_associacao AND ac.id IN ({ph})
                    WHERE ec.tipo = 'competicao'
                    ORDER BY ec.data_fim DESC
                """, tuple(ids_acad))
            except Exception as ex_pl2:
                err_pl2 = str(ex_pl2).lower()
                if "natureza" in err_pl2 or "1054" in err_pl2 or "unknown column" in err_pl2:
                    cur.execute(f"""
                        SELECT DISTINCT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                               (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                        FROM eventos_competicoes ec
                        INNER JOIN academias ac ON ac.id_associacao = ec.id_associacao AND ac.id IN ({ph})
                        WHERE ec.tipo = 'competicao'
                        ORDER BY ec.data_fim DESC
                    """, tuple(ids_acad))
                else:
                    raise
            eventos = cur.fetchall()
            for ev in eventos:
                if "natureza" not in ev:
                    ev["natureza"] = None
        else:
            eventos = []

        return render_template("competicoes/placar_selecionar.html",
            eventos=eventos,
            back_url=url_for("competicoes.index"))
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/placar/<int:evento_id>")
@login_required
def placar_lista(evento_id):
    """Lista lutas da competição para gestão via placar."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)
        if not id_assoc and ids_acad:
            cur.execute("SELECT id_associacao FROM academias WHERE id = %s LIMIT 1", (ids_acad[0],))
            r = cur.fetchone()
            id_assoc = r["id_associacao"] if r else None
        evento = _evento_fetch_por_assoc(cur, evento_id, id_assoc)
        if not evento:
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("competicoes.placar_selecionar"))
        if evento.get("tipo") != "competicao":
            flash("O placar só é para competições de judô. Este registro é um evento geral.", "warning")
            return redirect(url_for("competicoes.placar_selecionar"))

        cur.execute("""
            SELECT jl.*, COALESCE(jl.categoria_nome, c.nome_categoria) AS nome_categoria_display,
                   c.nome_categoria, c.categoria
            FROM judo_lutas jl
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.evento_id = %s
            ORDER BY COALESCE(jl.categoria_nome, c.nome_categoria), jl.round, jl.posicao_rodada, jl.id
        """, (evento_id,))
        lutas = cur.fetchall()

        from collections import defaultdict

        lutas_por_categoria = defaultdict(list)
        for l in lutas:
            cn = l.get("nome_categoria_display") or l.get("categoria_nome") or "Sem categoria"
            lutas_por_categoria[cn].append(l)
        lutas_por_categoria = dict(sorted(lutas_por_categoria.items(), key=lambda x: x[0].lower()))

        cur.execute("SELECT id, categoria, nome_categoria FROM categorias ORDER BY nome_categoria")
        categorias = cur.fetchall()

        return render_template(
            "competicoes/placar_lista.html",
            evento=evento,
            lutas=lutas,
            lutas_por_categoria=lutas_por_categoria,
            categorias=categorias,
            back_url=_back_nav_evento_competicoes(evento_id, cur),
        )
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/placar/<int:evento_id>/nova-luta", methods=["GET", "POST"])
@login_required
def placar_nova_luta(evento_id):
    """Cria nova luta na competição."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)
        if not id_assoc and ids_acad:
            cur.execute("SELECT id_associacao FROM academias WHERE id = %s LIMIT 1", (ids_acad[0],))
            r = cur.fetchone()
            id_assoc = r["id_associacao"] if r else None
        evento = _evento_fetch_por_assoc(cur, evento_id, id_assoc)
        if not evento:
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("competicoes.placar_selecionar"))
        if evento.get("tipo") != "competicao":
            flash("O placar só é para competições de judô.", "warning")
            return redirect(url_for("competicoes.placar_selecionar"))

        if request.method == "POST":
            atleta_branco_nome = request.form.get("atleta_branco_nome", "").strip()
            atleta_branco_academia = request.form.get("atleta_branco_academia", "").strip() or None
            atleta_azul_nome = request.form.get("atleta_azul_nome", "").strip()
            atleta_azul_academia = request.form.get("atleta_azul_academia", "").strip() or None
            categoria_id = request.form.get("categoria_id", type=int) or None
            tempo_total = int(request.form.get("tempo_total", 300))

            if not atleta_branco_nome or not atleta_azul_nome:
                flash("Preencha os nomes dos dois atletas.", "danger")
            else:
                cur.execute("""
                    INSERT INTO judo_lutas
                    (evento_id, categoria_id, atleta_branco_nome, atleta_branco_academia,
                     atleta_azul_nome, atleta_azul_academia, tempo_total_segundos, tempo_restante_segundos,
                     id_operador, status, elapsed_time, started_at, paused_at, golden_score_started_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'aguardando', 0, NULL, NULL, NULL)
                """, (evento_id, categoria_id, atleta_branco_nome, atleta_branco_academia,
                      atleta_azul_nome, atleta_azul_academia, tempo_total, tempo_total, current_user.id))
                conn.commit()
                flash("Luta criada com sucesso!", "success")
                return redirect(url_for("competicoes.placar_lista", evento_id=evento_id))

        cur.execute("SELECT id, categoria, nome_categoria FROM categorias ORDER BY nome_categoria")
        categorias = cur.fetchall()
        return render_template("competicoes/placar_nova_luta.html",
            evento=evento, categorias=categorias,
            back_url=url_for("competicoes.placar_lista", evento_id=evento_id))
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/resultados")
@login_required
def resultados_selecionar():
    """Selecionar competição para ver/exportar resultados por categoria."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)

        if modo == "associacao" and id_assoc:
            cur.execute("""
                SELECT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                       (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id AND status = 'finalizada') as total_finalizadas
                FROM eventos_competicoes ec
                WHERE ec.id_associacao = %s
                ORDER BY ec.data_fim DESC
            """, (id_assoc,))
        elif modo == "academia" and ids_acad:
            ph = ",".join(["%s"] * len(ids_acad))
            cur.execute(f"""
                SELECT DISTINCT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                       (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id AND status = 'finalizada') as total_finalizadas
                FROM eventos_competicoes ec
                INNER JOIN academias ac ON ac.id_associacao = ec.id_associacao AND ac.id IN ({ph})
                ORDER BY ec.data_fim DESC
            """, tuple(ids_acad))
        else:
            cur.execute("SELECT 1")
            cur.fetchall()

        eventos = cur.fetchall()
        return render_template("competicoes/resultados_selecionar.html",
            eventos=eventos,
            back_url=url_for("competicoes.index"))
    finally:
        cur.close()
        conn.close()


@bp_competicoes.route("/resultados/<int:evento_id>")
@login_required
def resultados_evento(evento_id):
    """Resultados por categoria — salvos do placar."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)
        if not id_assoc and ids_acad:
            cur.execute("SELECT id_associacao FROM academias WHERE id = %s LIMIT 1", (ids_acad[0],))
            r = cur.fetchone()
            id_assoc = r["id_associacao"] if r else None
        evento = _evento_fetch_por_assoc(cur, evento_id, id_assoc)
        if not evento:
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("competicoes.resultados_selecionar"))

        cur.execute("""
            SELECT jl.id, jl.atleta_branco_nome, jl.atleta_branco_academia,
                   jl.atleta_azul_nome, jl.atleta_azul_academia, jl.vencedor, jl.tipo_vitoria,
                   jl.finalizada_em, c.nome_categoria, c.categoria
            FROM judo_lutas jl
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.evento_id = %s AND jl.status = 'finalizada'
            ORDER BY COALESCE(jl.categoria_id, 999), jl.finalizada_em
        """, (evento_id,))
        resultados = cur.fetchall()

        return render_template(
            "competicoes/resultados_evento.html",
            evento=evento,
            resultados=resultados,
            back_url=_back_nav_evento_competicoes(evento_id, cur),
        )
    finally:
        cur.close()
        conn.close()
