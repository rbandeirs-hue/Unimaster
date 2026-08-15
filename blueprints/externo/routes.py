# -*- coding: utf-8 -*-
"""
Blueprint Acesso Externo — rotas públicas sem login.
Para uso no local da competição (tablet, celular).
- Inscrições (inscritos da competição)
- Categorias
- Súmulas
- Controle de lutas (placar)
"""
from flask import Blueprint, render_template, redirect, url_for, session, request, abort, jsonify
from config import get_db_connection

bp_externo = Blueprint("externo", __name__, url_prefix="/externo")
# Isento de CSRF globalmente via csrf.exempt(bp_externo) em app.py


def _evento_valido(evento_id):
    """Verifica se evento existe."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT id, nome, tipo, COALESCE(placar_num_areas, 1) AS placar_num_areas
                FROM eventos_competicoes WHERE id = %s
                """,
                (evento_id,),
            )
        except Exception as ex:
            err = str(ex).lower()
            if "placar_num_areas" in err or "tipo" in err or "1054" in err or "unknown column" in err:
                try:
                    cur.execute(
                        "SELECT id, nome, COALESCE(placar_num_areas, 1) AS placar_num_areas FROM eventos_competicoes WHERE id = %s",
                        (evento_id,),
                    )
                except Exception:
                    cur.execute("SELECT id, nome FROM eventos_competicoes WHERE id = %s", (evento_id,))
            else:
                raise
        row = cur.fetchone()
        if row and "placar_num_areas" not in row:
            row["placar_num_areas"] = 1
        if row and "tipo" not in row:
            row["tipo"] = "evento"
        return row
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/")
def index(evento_id):
    """Menu externo da competição — sem login."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    session["externo_evento_id"] = evento_id
    return render_template("externo/index.html", evento=evento)


@bp_externo.route("/<int:evento_id>/inscricoes")
def inscricoes(evento_id):
    """Lista inscritos da competição."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    session["externo_evento_id"] = evento_id

    import json
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT i.id, i.dados_form, i.inclusao_avulsa, ac.nome as academia_nome, a.nome as aluno_nome
            FROM eventos_competicoes_inscricoes i
            INNER JOIN academias ac ON ac.id = i.academia_id
            LEFT JOIN alunos a ON a.id = i.aluno_id
            WHERE i.evento_id = %s AND (i.status = 'enviada' OR (i.inclusao_avulsa = 1 AND i.aluno_id IS NULL))
            ORDER BY ac.nome, a.nome
        """, (evento_id,))
        rows = cur.fetchall()
        inscritos = []
        for r in rows:
            dados = {}
            if r.get("dados_form"):
                try:
                    dados = json.loads(r["dados_form"]) if isinstance(r["dados_form"], str) else (r["dados_form"] or {})
                except Exception:
                    pass
            inscritos.append({
                "id": r["id"],
                "nome": dados.get("nome") or r.get("aluno_nome") or "Avulso",
                "categoria": dados.get("categoria") or "-",
                "academia_nome": dados.get("academia") or r.get("academia_nome") or "-"
            })
        return render_template("externo/inscricoes.html", evento=evento, inscritos=inscritos)
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/categorias")
def categorias(evento_id):
    """Categorias de peso/idade."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    session["externo_evento_id"] = evento_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max
            FROM categorias WHERE ativo = 1
            ORDER BY genero, id_classe, peso_min
        """)
        categorias_list = cur.fetchall()
        return render_template("externo/categorias.html", evento=evento, categorias=categorias_list)
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/chaves", methods=["GET", "POST"])
def chaves(evento_id):
    """Chaves (brackets) por categoria. Agrupa inscritos e permite gerar lutas."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    session["externo_evento_id"] = evento_id

    import json
    from flask import flash

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # POST: Gerar chave para uma categoria
        if request.method == "POST":
            categoria_nome = request.form.get("categoria_nome", "").strip()
            if not categoria_nome:
                flash("Categoria não informada.", "danger")
                return redirect(url_for("externo.chaves", evento_id=evento_id))

            # Buscar inscritos dessa categoria
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
                flash(f"Categoria '{categoria_nome}' precisa de pelo menos 2 inscritos para gerar chave. Inscritos: {len(inscritos_cat)}.", "warning")
                return redirect(url_for("externo.chaves", evento_id=evento_id))

            # Remover lutas existentes desta categoria (regenerar chave)
            cur.execute("""
                DELETE FROM judo_lutas
                WHERE evento_id = %s
                  AND (categoria_nome = %s OR categoria_id IN (SELECT id FROM categorias WHERE nome_categoria = %s AND ativo = 1))
            """, (evento_id, categoria_nome, categoria_nome))
            conn.commit()

            from utils.judo_chaves_inteligentes import gerar_chave_inteligente, limpar_bo3_series_categoria

            limpar_bo3_series_categoria(cur, conn, evento_id, categoria_nome)

            # Buscar categoria_id (opcional)
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
                        "Execute as migrações: migrations/add_bracket_judo.sql e migrations/add_chave_inteligente_judo.sql",
                        "danger",
                    )
                else:
                    flash(f"Erro ao gerar chave: {e}", "danger")
            return redirect(url_for("externo.chaves", evento_id=evento_id))

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

        # Lutas por categoria (ordenar por rodada e posição para exibir bracket)
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

        # Só categorias com inscritos; agrupar por gênero e classe (id_classe) para o layout tipo imagem
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
                # Label de peso: -35, +81, etc.
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
                    "nome_categoria": cat_nome,
                    "peso_label": peso_label,
                    "count": count,
                    "tem_chave": tem_chave,
                    "slug": slug,
                })
            # Ordenar classes: Sub-13, Sub-15, Cadete, Júnior, Sénior, etc.
            ordem_classe = ("SUB 5", "SUB 7", "SUB 9", "SUB 11", "SUB 13", "SUB 15", "CADETE", "JÚNIOR", "JUNIOR", "SÉNIOR", "SENIOR", "Outros")
            for g in ("MASCULINO", "FEMININO"):
                agrupado[g] = dict(sorted(agrupado[g].items(), key=lambda x: (ordem_classe.index(x[0].upper()) if x[0].upper() in ordem_classe else 99, x[0])))
            slug_por_categoria = {}
            for g in ("MASCULINO", "FEMININO"):
                for lista in agrupado[g].values():
                    for item in lista:
                        slug_por_categoria[item["nome_categoria"]] = item["slug"]

        return render_template("externo/chaves.html",
            evento=evento, por_categoria=por_categoria, lutas_por_cat=lutas_por_cat, agrupado=agrupado, slug_por_categoria=slug_por_categoria)
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/sumulas")
def sumulas(evento_id):
    """Súmulas de lutas por categoria."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    session["externo_evento_id"] = evento_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT jl.*, c.nome_categoria
            FROM judo_lutas jl
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.evento_id = %s
            ORDER BY COALESCE(jl.categoria_id, 999), jl.created_at
        """, (evento_id,))
        lutas = cur.fetchall()
        return render_template("externo/sumulas.html", evento=evento, lutas=lutas)
    finally:
        cur.close()
        conn.close()


def _evento_associacao_para_sumula(cur, evento_id):
    cur.execute(
        """
        SELECT ec.id, ec.nome, ec.data_inicio, ec.data_fim, ec.descricao,
               a.nome AS associacao_nome
        FROM eventos_competicoes ec
        INNER JOIN associacoes a ON a.id = ec.id_associacao
        WHERE ec.id = %s
        """,
        (evento_id,),
    )
    return cur.fetchone()


@bp_externo.route("/<int:evento_id>/sumulas/luta/<int:luta_id>/imprimir")
def sumula_luta_imprimir_externo(evento_id, luta_id):
    """Súmula A4 (modelo CBJ) — acesso pelo link externo da competição."""
    evento_chk = _evento_valido(evento_id)
    if not evento_chk:
        abort(404)
    session["externo_evento_id"] = evento_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        evento = _evento_associacao_para_sumula(cur, evento_id)
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
        return render_template("competicoes/sumula_cbj_impressao.html", evento=evento, lutas=[luta])
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/sumulas/imprimir-todas")
def sumulas_imprimir_todas_externo(evento_id):
    """Todas as súmulas do evento em sequência (uma página por luta)."""
    evento_chk = _evento_valido(evento_id)
    if not evento_chk:
        abort(404)
    session["externo_evento_id"] = evento_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        evento = _evento_associacao_para_sumula(cur, evento_id)
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
            return "Nenhuma luta cadastrada.", 404
        return render_template("competicoes/sumula_cbj_impressao.html", evento=evento, lutas=lutas)
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/participantes-avulsos", methods=["GET", "POST"])
def participantes_avulsos(evento_id):
    """Adicionar participantes avulsos (nome, categoria, academia) sem cadastro prévio."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    session["externo_evento_id"] = evento_id

    import json
    from flask import flash

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Buscar primeira academia que aderiu ao evento
        cur.execute("""
            SELECT ea.academia_id, ac.nome as academia_nome
            FROM eventos_competicoes_adesao ea
            INNER JOIN academias ac ON ac.id = ea.academia_id
            WHERE ea.evento_id = %s AND ea.aderiu = 1
            ORDER BY ac.nome LIMIT 1
        """, (evento_id,))
        ac_row = cur.fetchone()
        if not ac_row:
            # Fallback: primeira academia da associação do evento
            cur.execute("""
                SELECT ac.id as academia_id, ac.nome as academia_nome
                FROM academias ac
                INNER JOIN eventos_competicoes ec ON ec.id_associacao = ac.id_associacao
                WHERE ec.id = %s
                ORDER BY ac.nome LIMIT 1
            """, (evento_id,))
            ac_row = cur.fetchone()
        academia_id = ac_row["academia_id"] if ac_row else None

        if request.method == "POST" and academia_id:
            nome = request.form.get("nome", "").strip()
            categoria = (request.form.get("categoria", "").strip() or request.form.get("categoria_manual", "").strip()) or "Avulso"
            academia_nome = request.form.get("academia", "").strip() or (ac_row.get("academia_nome") if ac_row else "Avulso")
            idade = request.form.get("idade", type=int)
            peso = request.form.get("peso", type=float)
            genero = request.form.get("genero", "").strip() or None
            if nome:
                dados_form = {"nome": nome, "categoria": categoria, "academia": academia_nome, "idade": idade, "peso": peso, "genero": genero}
                cur.execute("""
                    INSERT INTO eventos_competicoes_inscricoes
                    (evento_id, academia_id, aluno_id, usuario_inscricao_id, dados_form, inclusao_avulsa, status)
                    VALUES (%s, %s, NULL, NULL, %s, 1, 'enviada')
                """, (evento_id, academia_id, json.dumps(dados_form, ensure_ascii=False)))
                conn.commit()
                flash("Participante avulso adicionado com sucesso!", "success")
                return redirect(url_for("externo.participantes_avulsos", evento_id=evento_id))
            else:
                flash("Informe o nome do participante.", "danger")

        # Listar participantes avulsos (inscrições com inclusao_avulsa=1 e aluno_id NULL)
        cur.execute("""
            SELECT i.id, i.dados_form, ac.nome as academia_nome
            FROM eventos_competicoes_inscricoes i
            INNER JOIN academias ac ON ac.id = i.academia_id
            WHERE i.evento_id = %s AND i.inclusao_avulsa = 1 AND i.aluno_id IS NULL
            ORDER BY i.created_at DESC
        """, (evento_id,))
        rows = cur.fetchall()
        avulsos = []
        for r in rows:
            dados = {}
            if r.get("dados_form"):
                try:
                    dados = json.loads(r["dados_form"]) if isinstance(r["dados_form"], str) else (r["dados_form"] or {})
                except Exception:
                    pass
            avulsos.append({
                "id": r["id"],
                "nome": dados.get("nome") or "Avulso",
                "categoria": dados.get("categoria") or "-",
                "academia": dados.get("academia") or r.get("academia_nome") or "-",
                "idade": dados.get("idade"),
                "peso": dados.get("peso")
            })

        cur.execute("""
            SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max
            FROM categorias WHERE ativo = 1
            ORDER BY genero, id_classe, peso_min
        """)
        categorias_list = cur.fetchall()
        # Serializar para JSON (template usa em script)
        categorias_json = json.dumps([{
            "id": c["id"],
            "genero": c["genero"],
            "nome": c["nome_categoria"],
            "peso_min": float(c["peso_min"]) if c.get("peso_min") is not None else None,
            "peso_max": float(c["peso_max"]) if c.get("peso_max") is not None else None,
            "idade_min": int(c["idade_min"]) if c.get("idade_min") is not None else None,
            "idade_max": int(c["idade_max"]) if c.get("idade_max") is not None else None
        } for c in categorias_list], ensure_ascii=False)
        return render_template("externo/participantes_avulsos.html",
            evento=evento, avulsos=avulsos, categorias=categorias_list, categorias_json=categorias_json, academia_id=academia_id)
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/placar")
def placar_lista(evento_id):
    """Lista lutas para controle do placar."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    if evento.get("tipo") != "competicao":
        return (
            "O placar público existe apenas para competições. "
            "Este registro é um evento geral (sem lutas no sistema).",
            403,
        )
    session["externo_evento_id"] = evento_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute("""
                SELECT jl.*, c.nome_categoria, c.categoria
                FROM judo_lutas jl
                LEFT JOIN categorias c ON c.id = jl.categoria_id
                WHERE jl.evento_id = %s
                ORDER BY jl.area_num ASC, jl.id ASC
            """, (evento_id,))
        except Exception as ex:
            err = str(ex).lower()
            if "area_num" in err or "1054" in err or "unknown column" in err:
                cur.execute("""
                    SELECT jl.*, c.nome_categoria, c.categoria
                    FROM judo_lutas jl
                    LEFT JOIN categorias c ON c.id = jl.categoria_id
                    WHERE jl.evento_id = %s
                    ORDER BY jl.created_at DESC
                """, (evento_id,))
            else:
                raise
        lutas = cur.fetchall()
        return render_template("externo/placar_lista.html", evento=evento, lutas=lutas)
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/placar/<int:luta_id>/controle")
def placar_controle(evento_id, luta_id):
    """Controle do placar — sem login. Define session para API."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    if evento.get("tipo") != "competicao":
        return "Placar disponível apenas para competições.", 403
    session["externo_evento_id"] = evento_id

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT jl.*, ec.nome as evento_nome, ec.id as evento_id, c.nome_categoria, c.categoria
            FROM judo_lutas jl
            INNER JOIN eventos_competicoes ec ON ec.id = jl.evento_id
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.id = %s AND jl.evento_id = %s
        """, (luta_id, evento_id))
        luta = cur.fetchone()
        if not luta:
            return "Luta não encontrada.", 404
        from blueprints.eventos_competicoes.routes import (
            _emit_placar_monitor_luta_na_area,
            _fetch_placar_controle_modelo_evento,
            _luta_area_num,
            obter_estado_luta_completo,
        )

        an = _luta_area_num(luta)
        try:
            estado = obter_estado_luta_completo(luta_id)
            if estado:
                estado["evento_nome"] = luta.get("evento_nome")
                estado["categoria_nome"] = luta.get("nome_categoria") or luta.get("categoria_nome")
            _emit_placar_monitor_luta_na_area(evento_id, an, luta_id, estado, cur=cur)
        except Exception:
            pass
        voltar_placar_url = url_for(
            "externo.placar_voltar_lista_standby",
            evento_id=evento_id,
            luta_id=luta_id,
        )
        placar_controle_modelo = _fetch_placar_controle_modelo_evento(cur, evento_id)
        return render_template(
            "eventos_competicoes/placar_judo_controle.html",
            luta=luta,
            voltar_placar_url=voltar_placar_url,
            placar_controle_modelo=placar_controle_modelo,
        )
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/placar/<int:luta_id>/voltar-lista")
def placar_voltar_lista_standby(evento_id, luta_id):
    """Monitor da área em espera; redireciona à lista do placar externo."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    if evento.get("tipo") != "competicao":
        return "Placar disponível apenas para competições.", 403
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                "SELECT jl.id, jl.evento_id, jl.area_num FROM judo_lutas jl WHERE jl.id = %s AND jl.evento_id = %s",
                (luta_id, evento_id),
            )
        except Exception as ex:
            err = str(ex).lower()
            if "area_num" in err or "1054" in err or "unknown column" in err:
                cur.execute(
                    "SELECT jl.id, jl.evento_id FROM judo_lutas jl WHERE jl.id = %s AND jl.evento_id = %s",
                    (luta_id, evento_id),
                )
            else:
                raise
        row = cur.fetchone()
        if not row:
            return "Luta não encontrada.", 404
        from blueprints.eventos_competicoes.routes import _emit_placar_monitor_standby, _luta_area_num

        area_num = _luta_area_num(row)
        msg = f"Área {area_num} — aguardando luta"
        _emit_placar_monitor_standby(evento_id, area_num, msg)
        return redirect(url_for("externo.placar_lista", evento_id=evento_id))
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/placar/<int:luta_id>/monitor")
def placar_monitor(evento_id, luta_id):
    """Monitor/TV da área onde a luta está alocada."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    if evento.get("tipo") != "competicao":
        return "Placar disponível apenas para competições.", 403
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                "SELECT COALESCE(area_num, 1) AS area_num FROM judo_lutas WHERE id = %s AND evento_id = %s",
                (luta_id, evento_id),
            )
        except Exception as ex:
            err = str(ex).lower()
            if "area_num" in err or "1054" in err or "unknown column" in err:
                cur.execute(
                    "SELECT id FROM judo_lutas WHERE id = %s AND evento_id = %s",
                    (luta_id, evento_id),
                )
                row = cur.fetchone()
                area_num = 1 if row else 1
                if not row:
                    return "Luta não encontrada.", 404
                return redirect(
                    url_for(
                        "eventos_competicoes.placar_judo_monitor_area",
                        evento_id=evento_id,
                        area_num=area_num,
                    )
                )
            raise
        row = cur.fetchone()
        if not row:
            return "Luta não encontrada.", 404
        area_num = max(1, int(row.get("area_num") or 1))
    finally:
        cur.close()
        conn.close()
    return redirect(
        url_for(
            "eventos_competicoes.placar_judo_monitor_area",
            evento_id=evento_id,
            area_num=area_num,
        )
    )


@bp_externo.route("/<int:evento_id>/placar/chaves-monitor")
def placar_chaves_monitor(evento_id):
    """Monitor de chaves (bracket) por categoria — tela tipo TV com chave eliminatória e resultado."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    categoria_nome = request.args.get("categoria", "").strip()
    categoria_id = request.args.get("categoria_id", type=int)
    if not categoria_nome and not categoria_id:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""
                SELECT DISTINCT COALESCE(jl.categoria_nome, c.nome_categoria) as nome
                FROM judo_lutas jl
                LEFT JOIN categorias c ON c.id = jl.categoria_id
                WHERE jl.evento_id = %s AND COALESCE(jl.categoria_nome, c.nome_categoria) IS NOT NULL
                ORDER BY nome
            """, (evento_id,))
            categorias = [r["nome"] for r in cur.fetchall() if r.get("nome")]
            if len(categorias) == 1:
                categoria_nome = categorias[0]
            elif categorias:
                return render_template("externo/placar_chaves_monitor_escolher.html", evento=evento, categorias=categorias)
        finally:
            cur.close()
            conn.close()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if categoria_id:
            cur.execute("SELECT nome_categoria FROM categorias WHERE id = %s", (categoria_id,))
            r = cur.fetchone()
            categoria_nome = r["nome_categoria"] if r else ""
        cur.execute("""
            SELECT jl.*, COALESCE(jl.categoria_nome, c.nome_categoria) as cat_nome
            FROM judo_lutas jl
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.evento_id = %s AND (jl.categoria_nome = %s OR c.nome_categoria = %s)
            ORDER BY jl.id
        """, (evento_id, categoria_nome, categoria_nome))
        lutas = cur.fetchall()
        if not lutas and categoria_nome:
            cur.execute("""
                SELECT jl.*, COALESCE(jl.categoria_nome, c.nome_categoria) as cat_nome
                FROM judo_lutas jl
                LEFT JOIN categorias c ON c.id = jl.categoria_id
                WHERE jl.evento_id = %s
                ORDER BY jl.id
            """, (evento_id,))
            lutas = cur.fetchall()
        resultado_1 = resultado_2 = None
        max_round = max((l.get("round") or 1) for l in lutas) if lutas else 0
        final = next((l for l in lutas if (l.get("round") or 1) == max_round), None)
        if final and final.get("status") == "finalizada" and final.get("vencedor") in ("branco", "azul"):
            resultado_1 = {
                "nome": final["atleta_branco_nome"] if final["vencedor"] == "branco" else final["atleta_azul_nome"],
                "academia": final["atleta_branco_academia"] if final["vencedor"] == "branco" else final["atleta_azul_academia"],
            }
            resultado_2 = {
                "nome": final["atleta_azul_nome"] if final["vencedor"] == "branco" else final["atleta_branco_nome"],
                "academia": final["atleta_azul_academia"] if final["vencedor"] == "branco" else final["atleta_branco_academia"],
            }
        categoria_display = categoria_nome or (lutas[0].get("cat_nome") if lutas else "")
        return render_template("eventos_competicoes/placar_chaves_monitor.html",
            evento=evento, lutas=lutas, categoria_nome=categoria_display, resultado_1=resultado_1, resultado_2=resultado_2)
    finally:
        cur.close()
        conn.close()


def _externo_listar_categorias_lutas(cur, evento_id):
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


def _externo_lutas_por_categoria(cur, evento_id, categoria_nome):
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


@bp_externo.route("/<int:evento_id>/placar/chave-visual")
def placar_chave_visual(evento_id):
    """Chave eliminatória interativa + link para placar (atualização automática)."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    if evento.get("tipo") != "competicao":
        return "Disponível apenas para competições de judô.", 403
    session["externo_evento_id"] = evento_id

    categoria_nome = request.args.get("categoria", "").strip()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cats = _externo_listar_categorias_lutas(cur, evento_id)
        if not categoria_nome and len(cats) == 1:
            categoria_nome = cats[0]
        if not categoria_nome and cats:
            return render_template(
                "externo/placar_chave_visual_escolher.html",
                evento=evento,
                categorias=cats,
            )
        if not categoria_nome:
            return "Nenhuma luta com categoria.", 404

        api_url = url_for("externo.placar_chave_visual_api", evento_id=evento_id, categoria=categoria_nome)
        controle_tpl = url_for("externo.placar_controle", evento_id=evento_id, luta_id=0).replace("/0/", "/__LID__/")
        return render_template(
            "eventos_competicoes/placar_chave_interativa.html",
            evento=evento,
            categoria_nome=categoria_nome,
            api_url=api_url,
            controle_url_tpl=controle_tpl,
            back_url=url_for("externo.placar_lista", evento_id=evento_id),
            url_placar_evento=url_for("externo.placar_lista", evento_id=evento_id),
        )
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/placar/chave-visual/api")
def placar_chave_visual_api(evento_id):
    evento = _evento_valido(evento_id)
    if not evento:
        return jsonify({"erro": "Evento não encontrado"}), 404
    categoria_nome = request.args.get("categoria", "").strip()
    if not categoria_nome:
        return jsonify({"tipo": "vazio", "mensagem": "Categoria não informada.", "rounds": []})

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        lutas = _externo_lutas_por_categoria(cur, evento_id, categoria_nome)
        from utils.judo_bracket_visual import montar_payload_chave_visual

        return jsonify(montar_payload_chave_visual(lutas))
    finally:
        cur.close()
        conn.close()


@bp_externo.route("/<int:evento_id>/placar/nova-luta", methods=["GET", "POST"])
def placar_nova_luta(evento_id):
    """Criar nova luta — sem login."""
    evento = _evento_valido(evento_id)
    if not evento:
        return "Competição não encontrada.", 404
    if evento.get("tipo") != "competicao":
        return "Placar disponível apenas para competições.", 403
    session["externo_evento_id"] = evento_id

    from flask import flash

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            atleta_branco_nome = request.form.get("atleta_branco_nome", "").strip()
            atleta_branco_academia = request.form.get("atleta_branco_academia", "").strip() or None
            atleta_azul_nome = request.form.get("atleta_azul_nome", "").strip()
            atleta_azul_academia = request.form.get("atleta_azul_academia", "").strip() or None
            categoria_id = request.form.get("categoria_id", type=int) or None
            tempo_total = int(request.form.get("tempo_total", 300))
            nmax = max(1, min(int(evento.get("placar_num_areas") or 1), 50))
            area_num = request.form.get("area_num", type=int) or 1
            area_num = max(1, min(area_num, nmax))

            if not atleta_branco_nome or not atleta_azul_nome:
                flash("Preencha os nomes dos dois atletas.", "danger")
            else:
                try:
                    cur.execute("""
                        INSERT INTO judo_lutas (evento_id, categoria_id, area_num, atleta_branco_nome, atleta_branco_academia,
                         atleta_azul_nome, atleta_azul_academia, tempo_total_segundos, tempo_restante_segundos,
                         id_operador, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, 'aguardando')
                    """, (evento_id, categoria_id, area_num, atleta_branco_nome, atleta_branco_academia,
                          atleta_azul_nome, atleta_azul_academia, tempo_total, tempo_total))
                except Exception as ins_ex:
                    err = str(ins_ex).lower()
                    if "area_num" in err or "1054" in err or "unknown column" in err:
                        cur.execute("""
                            INSERT INTO judo_lutas (evento_id, categoria_id, atleta_branco_nome, atleta_branco_academia,
                             atleta_azul_nome, atleta_azul_academia, tempo_total_segundos, tempo_restante_segundos,
                             id_operador, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, 'aguardando')
                        """, (evento_id, categoria_id, atleta_branco_nome, atleta_branco_academia,
                              atleta_azul_nome, atleta_azul_academia, tempo_total, tempo_total))
                    else:
                        raise
                conn.commit()
                flash("Luta criada com sucesso!", "success")
                return redirect(url_for("externo.placar_lista", evento_id=evento_id))

        cur.execute("SELECT id, categoria, nome_categoria FROM categorias ORDER BY nome_categoria")
        categorias_list = cur.fetchall()
        return render_template("externo/placar_nova_luta.html", evento=evento, categorias=categorias_list)
    finally:
        cur.close()
        conn.close()
