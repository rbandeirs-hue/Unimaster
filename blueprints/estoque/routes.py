# -*- coding: utf-8 -*-
"""Módulo de estoque — telas.

A rota traduz o formulário, checa permissão e escopo, e chama `utils/estoque`.
Regra de negócio nenhuma mora aqui: quem decide se a operação pode acontecer é
o serviço, que é testável sem HTTP.

Contexto
--------
Tudo nestas telas acontece dentro de UM dono: a academia em que o gestor está
trabalhando, a associação dele, ou uma organização independente. `_contexto()`
resolve isso uma vez por requisição e todas as consultas passam por ele — é o
que impede uma academia de ler o estoque da outra mudando um número na URL.
"""
from datetime import date, timedelta

import os
import uuid

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, jsonify, current_app)
from flask_login import login_required, current_user

from config import get_db_connection
from utils import estoque as est
from utils import estoque_venda as venda
from utils.decorators import permission_required
from utils.escopo import academias_do_usuario
from utils import estoque_carrinho as carrinho

bp_estoque = Blueprint("estoque", __name__, url_prefix="/estoque")

CHAVE_ORG = "estoque_organizacao_id"
PASTA_IMAGEM = "estoque"
EXTENSOES = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _salvar_imagem(arquivo):
    """Grava a foto em static/uploads/estoque/ e devolve só o nome.

    Mesmo caminho da foto de aluno. O nome é sorteado: arquivo enviado com o
    nome do anterior sobrescreveria a foto de outro produto, e nome de arquivo
    vindo do navegador não é confiável para virar caminho em disco.
    """
    if not arquivo or not arquivo.filename:
        return None
    ext = os.path.splitext(arquivo.filename)[1].lower()
    if ext not in EXTENSOES:
        raise est.EstoqueErro(
            "Formato de imagem não aceito. Use JPG, PNG, WEBP ou GIF.")
    nome = f"prod_{uuid.uuid4().hex[:12]}{ext}"
    pasta = os.path.join(current_app.root_path, "static", "uploads", PASTA_IMAGEM)
    os.makedirs(pasta, exist_ok=True)
    arquivo.save(os.path.join(pasta, nome))
    return nome


# =====================================================================
# Contexto: de quem é o estoque que estou vendo
# =====================================================================
def _organizacoes_do_usuario():
    """Organizações independentes que este usuário acessa."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if current_user.has_role("admin"):
            cur.execute("SELECT id, nome, permite_negativo FROM estoque_organizacao "
                        "WHERE ativo = 1 ORDER BY nome")
        else:
            cur.execute(
                """SELECT o.id, o.nome, o.permite_negativo
                   FROM estoque_organizacao o
                   JOIN estoque_organizacao_usuario ou ON ou.organizacao_id = o.id
                   WHERE ou.usuario_id = %s AND o.ativo = 1 ORDER BY o.nome""",
                (current_user.id,))
        return cur.fetchall() or []
    except Exception:
        return []
    finally:
        cur.close()
        conn.close()


def _contexto():
    """Quem é o dono do estoque nesta requisição, ou None se ninguém.

    Ordem: organização escolhida na sessão; senão a academia em que o usuário
    está trabalhando. A associação entra pelo modo associação do shell.
    """
    org_id = session.get(CHAVE_ORG)
    if org_id:
        for o in _organizacoes_do_usuario():
            if o["id"] == org_id:
                return {"tipo": "organizacao", "id": o["id"], "nome": o["nome"],
                        "dono": {"id_organizacao": o["id"]},
                        "permite_negativo": bool(o["permite_negativo"])}
        session.pop(CHAVE_ORG, None)

    modo = session.get("modo_painel")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if modo == "associacao":
            aid = getattr(current_user, "id_associacao", None)
            if aid:
                cur.execute("""SELECT id, nome, COALESCE(modulo_estoque,0) AS tem_modulo
                               FROM associacoes WHERE id = %s""", (aid,))
                a = cur.fetchone()
                if a and a["tem_modulo"]:
                    return {"tipo": "associacao", "id": a["id"], "nome": a["nome"],
                            "dono": {"id_associacao": a["id"]},
                            "permite_negativo": False}
                return None

        academia_id = (session.get("academia_gerenciamento_id")
                       or session.get("finance_academia_id"))
        if not academia_id:
            permitidas = academias_do_usuario()
            academia_id = permitidas[0] if len(permitidas) == 1 else None
        if not academia_id or int(academia_id) not in academias_do_usuario():
            return None
        cur.execute("""SELECT id, nome, COALESCE(modulo_estoque,0) AS tem_modulo,
                              COALESCE(estoque_permite_negativo,0) AS neg,
                              id_associacao
                       FROM academias WHERE id = %s""", (academia_id,))
        a = cur.fetchone()
        if not a or not a["tem_modulo"]:
            return None
        return {"tipo": "academia", "id": a["id"], "nome": a["nome"],
                "dono": {"id_academia": a["id"]},
                "id_associacao": a["id_associacao"],
                "permite_negativo": bool(a["neg"])}
    finally:
        cur.close()
        conn.close()


def _exigir_contexto():
    ctx = _contexto()
    if not ctx:
        flash("O módulo de estoque não está liberado para este escopo.", "warning")
        return None
    return ctx


def _locais(ctx, incluir_consignado=True):
    """Locais que este contexto pode movimentar.

    A academia enxerga também os depósitos da associação dela, quando a
    associação liberou a revenda — é o estoque consignado.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        onde, par = [], []
        for coluna, valor in ctx["dono"].items():
            onde.append(f"l.{coluna} = %s")
            par.append(valor)
        if (incluir_consignado and ctx["tipo"] == "academia"
                and ctx.get("id_associacao")):
            cur.execute("""SELECT COALESCE(estoque_revenda,0) AS v,
                                  COALESCE(modulo_estoque,0) AS m
                           FROM associacoes WHERE id = %s""", (ctx["id_associacao"],))
            r = cur.fetchone()
            if r and r["v"] and r["m"]:
                onde.append("l.id_associacao = %s")
                par.append(ctx["id_associacao"])
        cur.execute(f"""SELECT l.id, l.nome, l.padrao, l.id_associacao,
                               (l.id_associacao IS NOT NULL
                                AND %s = 'academia') AS consignado
                        FROM estoque_local l
                        WHERE l.ativo = 1 AND ({' OR '.join(onde)})
                        ORDER BY l.padrao DESC, l.nome""", tuple([ctx["tipo"]] + par))
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


@bp_estoque.context_processor
def _injetar():
    """O shell precisa da academia para montar a lateral e o topo."""
    dados = {"menu_ativo": "estoque"}
    try:
        aid = session.get("academia_gerenciamento_id")
        if aid:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id, nome FROM academias WHERE id = %s", (aid,))
            dados["academia"] = cur.fetchone()
            dados["academia_id"] = aid
            cur.close()
            conn.close()
    except Exception:
        pass
    return dados


# =====================================================================
# Painel
# =====================================================================
@bp_estoque.route("/")
@login_required
@permission_required("estoque_ver")
def painel():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    dias = max(1, min(365, request.args.get("dias", type=int) or 30))
    dados = est.panorama(dias=dias, **ctx["dono"])
    recentes = est.movimentos(limite=12, **ctx["dono"])
    extra = {}
    if ctx["tipo"] == "organizacao":
        extra["caixa"] = venda.caixa(ctx["id"])
    if ctx["tipo"] == "academia" and ctx.get("id_associacao"):
        extra["repasse"] = venda.extrato_repasse(
            id_academia=ctx["id"], id_associacao=ctx["id_associacao"])
    return render_template("estoque/painel.html", ctx=ctx, dados=dados,
                           recentes=recentes, dias=dias, **extra)


# =====================================================================
# Produtos
# =====================================================================
@bp_estoque.route("/produtos")
@login_required
@permission_required("estoque_ver")
def produtos():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    busca = (request.args.get("busca") or "").strip()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par = est.filtro_dono("p", **ctx["dono"])
        extra, par_b = "", ()
        if busca:
            extra = " AND (p.nome LIKE %s OR p.sku LIKE %s)"
            par_b = (f"%{busca}%", f"%{busca}%")
        cur.execute(f"""
            SELECT p.id, p.nome, p.sku, p.unidade, p.custo, p.estoque_min, p.ativo,
                   c.nome AS categoria,
                   COUNT(DISTINCT v.id) AS variacoes,
                   COALESCE(SUM(s.quantidade), 0) AS saldo
            FROM estoque_produto p
            LEFT JOIN estoque_categoria c ON c.id = p.categoria_id
            LEFT JOIN estoque_variacao v ON v.produto_id = p.id AND v.ativo = 1
            LEFT JOIN estoque_saldo s ON s.variacao_id = v.id
            WHERE 1=1 {trecho} {extra}
            GROUP BY p.id, p.nome, p.sku, p.unidade, p.custo, p.estoque_min,
                     p.ativo, c.nome
            ORDER BY p.ativo DESC, p.nome""", par + par_b)
        lista = cur.fetchall() or []
    finally:
        cur.close()
        conn.close()
    return render_template("estoque/produtos.html", ctx=ctx, produtos=lista,
                           busca=busca)


@bp_estoque.route("/produtos/novo", methods=["GET", "POST"])
@login_required
@permission_required("estoque_produto_cadastrar")
def produto_novo():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))

    if request.method == "POST":
        # As variações chegam como listas paralelas. Linha sem nome é ignorada:
        # o formulário oferece linhas em branco de propósito.
        nomes = request.form.getlist("var_nome")
        tamanhos = request.form.getlist("var_tamanho")
        cores = request.form.getlist("var_cor")
        variacoes = [
            {"nome": n.strip(), "tamanho": (tamanhos[i] or "").strip() or None,
             "cor": (cores[i] or "").strip() or None}
            for i, n in enumerate(nomes) if (n or "").strip()
        ]
        try:
            produto_id = est.criar_produto(
                nome=request.form.get("nome"),
                categoria_id=request.form.get("categoria_id", type=int) or None,
                sku=(request.form.get("sku") or "").strip() or None,
                descricao=(request.form.get("descricao") or "").strip() or None,
                unidade=(request.form.get("unidade") or "un").strip(),
                custo=request.form.get("custo", type=float) or 0,
                estoque_min=request.form.get("estoque_min", type=int) or 0,
                estoque_max=request.form.get("estoque_max", type=int) or None,
                variacoes=variacoes or None,
                usuario_id=current_user.id,
                **ctx["dono"])
            imagem = _salvar_imagem(request.files.get("imagem"))
            if imagem:
                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute("UPDATE estoque_produto SET imagem = %s WHERE id = %s",
                                (imagem, produto_id))
                    conn.commit()
                finally:
                    cur.close()
                    conn.close()
            flash("Produto cadastrado.", "success")
            return redirect(url_for("estoque.produto", produto_id=produto_id))
        except est.EstoqueErro as e:
            flash(str(e), "warning")
        except Exception as e:
            flash(f"Erro ao cadastrar: {e}", "danger")

    return render_template("estoque/produto_form.html", ctx=ctx, produto=None,
                           categorias=_categorias(ctx))


def _categorias(ctx):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par = est.filtro_dono("c", **ctx["dono"])
        cur.execute(f"SELECT id, nome FROM estoque_categoria c "
                    f"WHERE c.ativo = 1 {trecho} ORDER BY nome", par)
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


@bp_estoque.route("/produtos/<int:produto_id>")
@login_required
@permission_required("estoque_ver")
def produto(produto_id):
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par = est.filtro_dono("p", **ctx["dono"])
        cur.execute(f"""SELECT p.*, c.nome AS categoria FROM estoque_produto p
                        LEFT JOIN estoque_categoria c ON c.id = p.categoria_id
                        WHERE p.id = %s {trecho}""", (produto_id,) + par)
        prod = cur.fetchone()
        if not prod:
            flash("Produto não encontrado neste estoque.", "warning")
            return redirect(url_for("estoque.produtos"))
        cur.execute("""SELECT v.*, COALESCE(SUM(s.quantidade), 0) AS saldo
                       FROM estoque_variacao v
                       LEFT JOIN estoque_saldo s ON s.variacao_id = v.id
                       WHERE v.produto_id = %s
                       GROUP BY v.id ORDER BY v.nome""", (produto_id,))
        variacoes = cur.fetchall() or []
        cur.execute("""SELECT t.id, t.nome, t.perfil, p.variacao_id, p.preco
                       FROM estoque_tabela_preco t
                       LEFT JOIN estoque_preco p ON p.tabela_id = t.id
                            AND p.variacao_id IN (
                                SELECT id FROM estoque_variacao WHERE produto_id = %s)
                       WHERE t.ativo = 1 ORDER BY t.padrao DESC, t.nome""",
                    (produto_id,))
        precos = cur.fetchall() or []
    finally:
        cur.close()
        conn.close()
    historico = est.movimentos(limite=20, **ctx["dono"])
    historico = [m for m in historico
                 if any(v["id"] == m["variacao_id"] for v in variacoes)]
    return render_template("estoque/produto.html", ctx=ctx, produto=prod,
                           variacoes=variacoes, precos=precos,
                           historico=historico,
                           tabelas=est.tabelas_de_preco(**ctx["dono"]))


@bp_estoque.route("/produtos/<int:produto_id>/imagem", methods=["POST"])
@login_required
@permission_required("estoque_produto_editar")
def produto_imagem(produto_id):
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par = est.filtro_dono("p", **ctx["dono"])
        cur.execute(f"SELECT id FROM estoque_produto p WHERE p.id = %s {trecho}",
                    (produto_id,) + par)
        if not cur.fetchone():
            flash("Produto não encontrado neste estoque.", "warning")
            return redirect(url_for("estoque.produtos"))
        nome = _salvar_imagem(request.files.get("imagem"))
        if not nome:
            flash("Escolha uma imagem.", "warning")
        else:
            cur.execute("UPDATE estoque_produto SET imagem = %s WHERE id = %s",
                        (nome, produto_id))
            conn.commit()
            flash("Imagem atualizada.", "success")
    except est.EstoqueErro as e:
        flash(str(e), "warning")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao salvar a imagem: {e}", "danger")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("estoque.produto", produto_id=produto_id))


@bp_estoque.route("/produtos/<int:produto_id>/preco", methods=["POST"])
@login_required
@permission_required("estoque_produto_editar")
def produto_preco(produto_id):
    """Grava o preço de uma variação numa tabela. Vazio apaga a linha."""
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par = est.filtro_dono("p", **ctx["dono"])
        cur.execute(f"SELECT id FROM estoque_produto p WHERE p.id = %s {trecho}",
                    (produto_id,) + par)
        if not cur.fetchone():
            flash("Produto não encontrado neste estoque.", "warning")
            return redirect(url_for("estoque.produtos"))

        tabela_id = request.form.get("tabela_id", type=int)
        gravados = 0
        for chave, valor in request.form.items():
            if not chave.startswith("preco_"):
                continue
            variacao_id = int(chave.split("_", 1)[1])
            texto = (valor or "").strip().replace(",", ".")
            if not texto:
                cur.execute("DELETE FROM estoque_preco WHERE tabela_id = %s "
                            "AND variacao_id = %s", (tabela_id, variacao_id))
                continue
            cur.execute("""INSERT INTO estoque_preco (tabela_id, variacao_id, preco)
                           VALUES (%s,%s,%s)
                           ON DUPLICATE KEY UPDATE preco = VALUES(preco)""",
                        (tabela_id, variacao_id, float(texto)))
            gravados += 1
        conn.commit()
        flash(f"{gravados} preço(s) atualizado(s).", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao salvar preços: {e}", "danger")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("estoque.produto", produto_id=produto_id))


# =====================================================================
# Movimentação
# =====================================================================
def _variacoes_do_contexto(ctx):
    """Tudo que este contexto pode movimentar, com o saldo de cada local."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        locais = [l["id"] for l in _locais(ctx)]
        if not locais:
            return []
        marcas = ", ".join(["%s"] * len(locais))
        cur.execute(f"""
            SELECT v.id, v.nome AS variacao, p.nome AS produto, p.id AS produto_id,
                   p.unidade, COALESCE(SUM(s.quantidade), 0) AS saldo
            FROM estoque_variacao v
            JOIN estoque_produto p ON p.id = v.produto_id
            LEFT JOIN estoque_saldo s ON s.variacao_id = v.id
                 AND s.local_id IN ({marcas})
            WHERE v.ativo = 1 AND p.ativo = 1
              AND EXISTS (SELECT 1 FROM estoque_local l
                          WHERE l.id IN ({marcas})
                            AND ((l.id_academia IS NOT NULL
                                  AND l.id_academia = p.id_academia)
                              OR (l.id_associacao IS NOT NULL
                                  AND l.id_associacao = p.id_associacao)
                              OR (l.id_organizacao IS NOT NULL
                                  AND l.id_organizacao = p.id_organizacao)))
            GROUP BY v.id, v.nome, p.nome, p.id, p.unidade
            ORDER BY p.nome, v.nome""", tuple(locais + locais))
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


@bp_estoque.route("/movimentar", methods=["GET", "POST"])
@login_required
@permission_required("estoque_ver")
def movimentar():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))

    if request.method == "POST":
        sentido = request.form.get("sentido")
        permissao = "estoque_entrada" if sentido == "E" else "estoque_saida"
        motivo = request.form.get("motivo") or ""
        if motivo in ("ajuste_positivo", "ajuste_negativo"):
            permissao = "estoque_ajustar"
        # A permissão é conferida aqui, e não só no decorador da tela: entrada
        # e saída são operações diferentes e podem estar em mãos diferentes.
        if not current_user.has_permission(permissao):
            flash("Você não tem permissão para esta operação.", "danger")
            return redirect(url_for("estoque.movimentar"))

        autorizar = (request.form.get("autorizar_negativo") == "1"
                     and current_user.has_permission("estoque_ajustar"))
        try:
            est.movimentar(
                variacao_id=request.form.get("variacao_id", type=int),
                local_id=request.form.get("local_id", type=int),
                sentido=sentido, motivo=motivo,
                quantidade=request.form.get("quantidade"),
                custo_unitario=request.form.get("custo_unitario", type=float),
                observacao=(request.form.get("observacao") or "").strip() or None,
                aluno_id=request.form.get("aluno_id", type=int) or None,
                usuario_id=current_user.id,
                autorizar_negativo=autorizar)
            flash("Movimentação registrada.", "success")
            return redirect(url_for("estoque.movimentar"))
        except est.EstoqueErro as e:
            flash(str(e), "warning")
        except Exception as e:
            flash(f"Erro ao movimentar: {e}", "danger")

    return render_template("estoque/movimentar.html", ctx=ctx,
                           locais=_locais(ctx),
                           itens=_variacoes_do_contexto(ctx),
                           motivos_entrada=est.MOTIVOS_ENTRADA,
                           motivos_saida=est.MOTIVOS_SAIDA,
                           internos=est.MOTIVOS_INTERNOS,
                           alunos=_alunos(ctx),
                           pode_ajustar=current_user.has_permission("estoque_ajustar"))


def _alunos(ctx):
    if ctx["tipo"] != "academia":
        return []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome FROM alunos WHERE id_academia = %s AND ativo = 1 "
                    "ORDER BY nome", (ctx["id"],))
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


@bp_estoque.route("/transferir", methods=["POST"])
@login_required
@permission_required("estoque_entrada", "estoque_saida")
def transferir():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    try:
        est.transferir(
            variacao_id=request.form.get("variacao_id", type=int),
            origem_local_id=request.form.get("origem_local_id", type=int),
            destino_local_id=request.form.get("destino_local_id", type=int),
            quantidade=request.form.get("quantidade"),
            usuario_id=current_user.id,
            observacao=(request.form.get("observacao") or "").strip() or None)
        flash("Transferência registrada nos dois locais.", "success")
    except est.EstoqueErro as e:
        flash(str(e), "warning")
    except Exception as e:
        flash(f"Erro na transferência: {e}", "danger")
    return redirect(url_for("estoque.movimentar"))


@bp_estoque.route("/historico")
@login_required
@permission_required("estoque_ver")
def historico():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    dias = max(1, min(365, request.args.get("dias", type=int) or 30))
    filtros = {"sentido": request.args.get("sentido") or None,
               "local_id": request.args.get("local_id", type=int) or None,
               "variacao_id": request.args.get("variacao_id", type=int) or None,
               "desde": date.today() - timedelta(days=dias)}
    lista = est.movimentos(limite=300, **ctx["dono"], **filtros)
    return render_template("estoque/historico.html", ctx=ctx, movimentos=lista,
                           locais=_locais(ctx), itens=_variacoes_do_contexto(ctx),
                           dias=dias, filtros=filtros,
                           pode_estornar=current_user.has_permission("estoque_ajustar"))


@bp_estoque.route("/movimento/<int:movimento_id>/estornar", methods=["POST"])
@login_required
@permission_required("estoque_ajustar")
def estornar(movimento_id):
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par = est.filtro_dono("m", **ctx["dono"])
        cur.execute(f"SELECT id FROM estoque_movimento m WHERE m.id = %s {trecho}",
                    (movimento_id,) + par)
        if not cur.fetchone():
            flash("Movimento não encontrado neste estoque.", "warning")
            return redirect(url_for("estoque.historico"))
    finally:
        cur.close()
        conn.close()
    try:
        est.estornar(movimento_id, usuario_id=current_user.id,
                     motivo_texto=(request.form.get("motivo") or "").strip() or None)
        flash("Movimento estornado. O original continua no histórico.", "success")
    except est.EstoqueErro as e:
        flash(str(e), "warning")
    return redirect(url_for("estoque.historico"))


# =====================================================================
# Venda de balcão
# =====================================================================
@bp_estoque.route("/venda", methods=["GET", "POST"])
@login_required
@permission_required("estoque_saida")
def venda_balcao():
    """Venda em uma tela só: escolhe comprador, itens e confirma.

    O pedido é criado, recebe os itens e é confirmado no mesmo POST. Se
    qualquer passo falhar, o pedido fica aberto e some da tela — não existe
    meia venda com estoque baixado.
    """
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    locais = _locais(ctx)

    if request.method == "POST":
        local_id = request.form.get("local_id", type=int)
        local = next((l for l in locais if l["id"] == local_id), None)
        if not local:
            flash("Local inválido para este estoque.", "warning")
            return redirect(url_for("estoque.venda_balcao"))

        # Vender de um depósito da associação é consignação: a academia vende,
        # a associação é dona, e nasce o débito.
        consignado = bool(local["id_associacao"]) and ctx["tipo"] == "academia"
        dono_pedido = {
            "id_academia": ctx["id"] if ctx["tipo"] == "academia" else None,
            "id_associacao": local["id_associacao"] if consignado
                             else (ctx["id"] if ctx["tipo"] == "associacao" else None),
            "id_organizacao": ctx["id"] if ctx["tipo"] == "organizacao" else None,
        }

        pedido_id = None
        try:
            pedido_id = venda.criar_pedido(
                local_id=local_id,
                comprador_tipo=request.form.get("comprador_tipo") or "avulso",
                aluno_id=request.form.get("aluno_id", type=int) or None,
                comprador_nome=(request.form.get("comprador_nome") or "").strip() or None,
                tabela_preco_id=request.form.get("tabela_preco_id", type=int) or None,
                origem="balcao", criado_por=current_user.id, **dono_pedido)

            variacoes = request.form.getlist("item_variacao")
            quantidades = request.form.getlist("item_quantidade")
            precos = request.form.getlist("item_preco")
            algum = False
            for i, v in enumerate(variacoes):
                if not v or not (quantidades[i] or "").strip():
                    continue
                preco = (precos[i] or "").strip().replace(",", ".") if i < len(precos) else ""
                venda.adicionar_item(pedido_id, int(v), quantidades[i],
                                     preco_unitario=float(preco) if preco else None)
                algum = True
            if not algum:
                raise venda.VendaErro("Escolha ao menos um item.")

            r = venda.confirmar(
                pedido_id, usuario_id=current_user.id,
                forma_pagamento=(request.form.get("forma_pagamento") or "").strip() or None,
                autorizar_negativo=(request.form.get("autorizar_negativo") == "1"
                                    and current_user.has_permission("estoque_ajustar")))
            msg = f"Venda registrada: R$ {r['total']:.2f}."
            if r["repasse"]:
                msg += (f" Repasse de R$ {r['repasse']:.2f} à associação, "
                        f"margem de R$ {r['margem']:.2f}.")
            flash(msg, "success")
            return redirect(url_for("estoque.venda_balcao"))
        except est.EstoqueErro as e:
            if pedido_id:
                try:
                    venda.cancelar(pedido_id, usuario_id=current_user.id,
                                   motivo="venda não concluída")
                except Exception:
                    pass
            flash(str(e), "warning")
        except Exception as e:
            flash(f"Erro na venda: {e}", "danger")

    return render_template("estoque/venda.html", ctx=ctx, locais=locais,
                           itens=_variacoes_do_contexto(ctx),
                           alunos=_alunos(ctx),
                           tabelas=est.tabelas_de_preco(**ctx["dono"]),
                           pode_ajustar=current_user.has_permission("estoque_ajustar"))


@bp_estoque.route("/api/preco")
@login_required
@permission_required("estoque_ver")
def api_preco():
    """Preço de um item numa tabela — a tela de venda consulta ao escolher."""
    ctx = _contexto()
    if not ctx:
        return jsonify({"erro": "sem contexto"}), 403
    preco = est.preco_de(request.args.get("variacao_id", type=int),
                         request.args.get("tabela_id", type=int) or None,
                         **ctx["dono"])
    return jsonify({"preco": float(preco) if preco is not None else None})


# =====================================================================
# Conta com a associação
# =====================================================================
@bp_estoque.route("/repasses")
@login_required
@permission_required("estoque_relatorio")
def repasses():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    if ctx["tipo"] == "associacao":
        dados = venda.extrato_repasse(id_associacao=ctx["id"])
    elif ctx["tipo"] == "academia" and ctx.get("id_associacao"):
        dados = venda.extrato_repasse(id_academia=ctx["id"],
                                      id_associacao=ctx["id_associacao"])
    else:
        dados = {"linhas": [], "em_aberto": 0}
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        coluna = "id_associacao" if ctx["tipo"] == "associacao" else "id_academia"
        cur.execute(f"""SELECT f.*, a.nome AS academia FROM estoque_repasse_fatura f
                        JOIN academias a ON a.id = f.id_academia
                        WHERE f.{coluna} = %s ORDER BY f.competencia DESC""",
                    (ctx["id"],))
        faturas = cur.fetchall() or []
    finally:
        cur.close()
        conn.close()
    return render_template("estoque/repasses.html", ctx=ctx, dados=dados,
                           faturas=faturas,
                           pode_fechar=(ctx["tipo"] == "associacao"
                                        and current_user.has_permission("estoque_config")))


@bp_estoque.route("/repasses/fechar", methods=["POST"])
@login_required
@permission_required("estoque_config")
def repasse_fechar():
    ctx = _exigir_contexto()
    if not ctx or ctx["tipo"] != "associacao":
        flash("Só a associação fecha a fatura do repasse.", "warning")
        return redirect(url_for("estoque.repasses"))
    try:
        r = venda.fechar_fatura(request.form.get("id_academia", type=int), ctx["id"],
                                (request.form.get("competencia") or "").strip(),
                                usuario_id=current_user.id)
        flash(f"Fatura fechada: R$ {r['valor']:.2f} em {r['itens']} repasse(s).",
              "success")
    except est.EstoqueErro as e:
        flash(str(e), "warning")
    return redirect(url_for("estoque.repasses"))


@bp_estoque.route("/repasses/<int:fatura_id>/quitar", methods=["POST"])
@login_required
@permission_required("estoque_config")
def repasse_quitar(fatura_id):
    try:
        r = venda.quitar_fatura(fatura_id, usuario_id=current_user.id)
        flash(f"Fatura quitada: R$ {r['valor']:.2f}. "
              "Lançada como despesa na academia e receita na associação.", "success")
    except est.EstoqueErro as e:
        flash(str(e), "warning")
    return redirect(url_for("estoque.repasses"))


# =====================================================================
# Configuração: locais e tabelas de preço
# =====================================================================
@bp_estoque.route("/config", methods=["GET", "POST"])
@login_required
@permission_required("estoque_config")
def config():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            acao = request.form.get("acao")
            nome = (request.form.get("nome") or "").strip()
            colunas = ", ".join(ctx["dono"].keys())
            marcas = ", ".join(["%s"] * len(ctx["dono"]))
            valores = tuple(ctx["dono"].values())
            if acao == "local" and nome:
                cur.execute(f"INSERT INTO estoque_local ({colunas}, nome) "
                            f"VALUES ({marcas}, %s)", valores + (nome,))
                flash("Local criado.", "success")
            elif acao == "categoria" and nome:
                cur.execute(f"INSERT INTO estoque_categoria ({colunas}, nome) "
                            f"VALUES ({marcas}, %s)", valores + (nome,))
                flash("Categoria criada.", "success")
            elif acao == "tabela" and nome:
                cur.execute(f"""INSERT INTO estoque_tabela_preco
                                ({colunas}, nome, perfil, padrao)
                                VALUES ({marcas}, %s, %s, %s)""",
                            valores + (nome,
                                       (request.form.get("perfil") or "").strip() or None,
                                       1 if request.form.get("padrao") else 0))
                flash("Tabela de preço criada.", "success")
            conn.commit()
            return redirect(url_for("estoque.config"))

        trecho, par = est.filtro_dono("x", **ctx["dono"])
        cur.execute(f"SELECT x.* FROM estoque_local x WHERE 1=1 {trecho} ORDER BY nome", par)
        locais = cur.fetchall() or []
        cur.execute(f"SELECT x.* FROM estoque_categoria x WHERE 1=1 {trecho} ORDER BY nome", par)
        categorias = cur.fetchall() or []
        cur.execute(f"SELECT x.* FROM estoque_tabela_preco x WHERE 1=1 {trecho} "
                    f"ORDER BY padrao DESC, nome", par)
        tabelas = cur.fetchall() or []
    except Exception as e:
        conn.rollback()
        flash(f"Erro: {e}", "danger")
        locais = categorias = tabelas = []
    finally:
        cur.close()
        conn.close()
    return render_template("estoque/config.html", ctx=ctx, locais=locais,
                           categorias=categorias, tabelas=tabelas)


@bp_estoque.route("/escolher/<int:organizacao_id>")
@login_required
@permission_required("estoque_ver")
def escolher_organizacao(organizacao_id):
    """Entra numa organização independente. Sair é voltar para a academia."""
    if any(o["id"] == organizacao_id for o in _organizacoes_do_usuario()):
        session[CHAVE_ORG] = organizacao_id
        return redirect(url_for("estoque.painel"))
    flash("Você não tem acesso a esse estoque.", "danger")
    return redirect(url_for("painel.home"))


@bp_estoque.route("/sair-organizacao")
@login_required
def sair_organizacao():
    session.pop(CHAVE_ORG, None)
    return redirect(url_for("painel.home"))


# =====================================================================
# Inventário físico
# =====================================================================
@bp_estoque.route("/inventario", methods=["GET", "POST"])
@login_required
@permission_required("estoque_inventario")
def inventario():
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))

    if request.method == "POST":
        try:
            inv_id = est.abrir_inventario(
                local_id=request.form.get("local_id", type=int),
                usuario_id=current_user.id,
                observacao=(request.form.get("observacao") or "").strip() or None)
            flash("Inventário aberto. Conte e depois feche para gerar os ajustes.",
                  "success")
            return redirect(url_for("estoque.inventario_contar", inventario_id=inv_id))
        except est.EstoqueErro as e:
            flash(str(e), "warning")

    return render_template("estoque/inventario.html", ctx=ctx,
                           locais=_locais(ctx, incluir_consignado=False),
                           lista=est.inventarios(**ctx["dono"]))


def _inventario_do_contexto(ctx, inventario_id):
    """Carrega o inventário garantindo que ele é deste dono."""
    inv = est.inventario(inventario_id)
    if not inv:
        return None
    for coluna, valor in ctx["dono"].items():
        if inv.get(coluna) != valor:
            return None
    return inv


@bp_estoque.route("/inventario/<int:inventario_id>", methods=["GET", "POST"])
@login_required
@permission_required("estoque_inventario")
def inventario_contar(inventario_id):
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    inv = _inventario_do_contexto(ctx, inventario_id)
    if not inv:
        flash("Inventário não encontrado neste estoque.", "warning")
        return redirect(url_for("estoque.inventario"))

    if request.method == "POST":
        acao = request.form.get("acao")
        try:
            if acao == "cancelar":
                est.cancelar_inventario(inventario_id, usuario_id=current_user.id)
                flash("Inventário cancelado. Nenhum saldo foi tocado.", "success")
                return redirect(url_for("estoque.inventario"))

            contagens = {}
            for chave, valor in request.form.items():
                if chave.startswith("qtd_"):
                    contagens[int(chave.split("_", 1)[1])] = (valor or "").strip() or None
            est.contar(inventario_id, contagens, usuario_id=current_user.id)

            if acao == "fechar":
                r = est.fechar_inventario(inventario_id, usuario_id=current_user.id)
                flash(f"Inventário fechado: {r['ajustes']} ajuste(s) — "
                      f"sobra {r['sobra']}, falta {r['falta']}. "
                      "Cada diferença virou um movimento no histórico.", "success")
                return redirect(url_for("estoque.inventario"))
            flash("Contagem salva. Dá para continuar depois.", "success")
            return redirect(url_for("estoque.inventario_contar",
                                    inventario_id=inventario_id))
        except est.EstoqueErro as e:
            flash(str(e), "warning")
            inv = _inventario_do_contexto(ctx, inventario_id)

    return render_template("estoque/inventario_contar.html", ctx=ctx, inv=inv)


# =====================================================================
# Autoatendimento — o próprio comprador faz o pedido
# =====================================================================
def _quem_sou():
    """Aluno ou visitante ligado ao usuário logado, e a academia dele.

    Devolve (tipo, id, academia_id). O comprador nunca informa a academia: ela
    vem do cadastro dele. Aceitar da URL seria deixar qualquer um comprar do
    estoque de qualquer academia.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, id_academia FROM alunos "
                    "WHERE usuario_id = %s AND ativo = 1 LIMIT 1", (current_user.id,))
        r = cur.fetchone()
        if r and r["id_academia"]:
            return "aluno", r["id"], r["id_academia"]
        cur.execute("SELECT id, id_academia FROM visitantes "
                    "WHERE usuario_id = %s AND ativo = 1 LIMIT 1", (current_user.id,))
        r = cur.fetchone()
        if r and r["id_academia"]:
            return "visitante", r["id"], r["id_academia"]
        return None, None, None
    finally:
        cur.close()
        conn.close()


def _loja_da_academia(academia_id, comprador_tipo):
    """Catálogo com preço e saldo, do ponto de vista do comprador.

    Traz o estoque da academia e o consignado da associação, quando liberado —
    para o aluno, é tudo "a loja da minha academia".
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT id_associacao, COALESCE(modulo_estoque,0) AS tem_modulo
                       FROM academias WHERE id = %s""", (academia_id,))
        ac = cur.fetchone()
        if not ac or not ac["tem_modulo"]:
            return [], []
        locais_ids, assoc = [], None
        cur.execute("SELECT id FROM estoque_local WHERE id_academia = %s AND ativo = 1",
                    (academia_id,))
        locais_ids = [r["id"] for r in cur.fetchall() or []]
        if ac["id_associacao"]:
            cur.execute("""SELECT COALESCE(estoque_revenda,0) AS v,
                                  COALESCE(modulo_estoque,0) AS m
                           FROM associacoes WHERE id = %s""", (ac["id_associacao"],))
            r = cur.fetchone()
            if r and r["v"] and r["m"]:
                assoc = ac["id_associacao"]
                cur.execute("SELECT id FROM estoque_local WHERE id_associacao = %s "
                            "AND ativo = 1", (assoc,))
                locais_ids += [x["id"] for x in cur.fetchall() or []]
        if not locais_ids:
            return [], []

        marcas = ", ".join(["%s"] * len(locais_ids))
        cur.execute(f"""
            SELECT v.id, v.nome AS variacao, v.tamanho, v.cor,
                   COALESCE(v.imagem, p.imagem) AS imagem,
                   p.id AS produto_id, p.nome AS produto, p.unidade, p.descricao,
                   c.nome AS categoria,
                   l.id AS local_id, l.nome AS local,
                   l.id_associacao AS local_assoc,
                   COALESCE(s.quantidade, 0) AS saldo
            FROM estoque_saldo s
            JOIN estoque_variacao v ON v.id = s.variacao_id AND v.ativo = 1
            JOIN estoque_produto p ON p.id = v.produto_id AND p.ativo = 1
            JOIN estoque_local l ON l.id = s.local_id
            LEFT JOIN estoque_categoria c ON c.id = p.categoria_id
            WHERE s.local_id IN ({marcas}) AND s.quantidade > 0
            ORDER BY p.nome, v.nome""", tuple(locais_ids))
        itens = cur.fetchall() or []
    finally:
        cur.close()
        conn.close()

    perfil = "aluno" if comprador_tipo == "aluno" else None
    vitrine = []
    for i in itens:
        preco = None
        if perfil:
            for t in est.tabelas_de_preco(id_academia=academia_id, perfil=perfil):
                preco = est.preco_de(i["id"], t["id"])
                if preco is not None:
                    break
            if preco is None and i["local_assoc"]:
                for t in est.tabelas_de_preco(id_associacao=i["local_assoc"],
                                              perfil=perfil):
                    preco = est.preco_de(i["id"], t["id"])
                    if preco is not None:
                        break
        if preco is None:
            preco = est.preco_de(i["id"], id_academia=academia_id)
        if preco is None and i["local_assoc"]:
            preco = est.preco_de(i["id"], id_associacao=i["local_assoc"])
        # Sem preço, o item simplesmente não vai para a vitrine: o comprador
        # não pode escolher algo que o sistema não sabe cobrar.
        if preco is None:
            continue
        i["preco"] = preco
        vitrine.append(i)
    return vitrine, []


@bp_estoque.route("/loja")
@login_required
def loja():
    """O catálogo do comprador. Sem permissão de estoque, de propósito.

    Quem entra aqui é aluno, responsável ou visitante — gente que não tem
    permissão nenhuma do módulo. A trava é outra: só se vê o estoque da
    academia do próprio cadastro, e nada é comprado por esta tela; ela só
    enche o carrinho.
    """
    tipo, pessoa_id, academia_id = _quem_sou()
    if not academia_id:
        flash("Seu cadastro não está vinculado a uma academia.", "warning")
        return redirect(url_for("painel.home"))

    vitrine, _ = _loja_da_academia(academia_id, tipo)
    busca = (request.args.get("busca") or "").strip().lower()
    categoria = (request.args.get("categoria") or "").strip()

    categorias = sorted({i["categoria"] for i in vitrine if i["categoria"]})
    if busca:
        vitrine = [i for i in vitrine
                   if busca in (i["produto"] or "").lower()
                   or busca in (i["variacao"] or "").lower()
                   or busca in (i["descricao"] or "").lower()]
    if categoria:
        vitrine = [i for i in vitrine if (i["categoria"] or "") == categoria]

    # Uma ficha por produto, com as variações dentro: mostrar Kimono A1, A2, A3
    # como três cartões faz o catálogo parecer três produtos diferentes.
    fichas = {}
    for i in vitrine:
        f = fichas.setdefault(i["produto_id"], {
            "produto_id": i["produto_id"], "produto": i["produto"],
            "descricao": i["descricao"], "categoria": i["categoria"],
            "imagem": i["imagem"], "unidade": i["unidade"], "variacoes": []})
        f["variacoes"].append(i)
        if not f["imagem"] and i["imagem"]:
            f["imagem"] = i["imagem"]
    fichas = sorted(fichas.values(), key=lambda f: f["produto"])

    # O carrinho é conferido contra o catálogo INTEIRO, não contra o filtrado:
    # buscar "faixa" não pode fazer o kimono sumir do carrinho.
    todos, _ = _loja_da_academia(academia_id, tipo)
    linhas, total, alertas = carrinho.detalhar(academia_id, todos)
    for a in alertas:
        flash(a, "warning")

    return render_template("estoque/loja.html", fichas=fichas, tipo=tipo,
                           academia_id=academia_id, categorias=categorias,
                           busca=busca, categoria=categoria,
                           carrinho_qtd=carrinho.quantidade(academia_id),
                           carrinho_total=total)


@bp_estoque.route("/carrinho", methods=["GET", "POST"])
@login_required
def carrinho_ver():
    """O carrinho e o fechamento do pedido."""
    tipo, pessoa_id, academia_id = _quem_sou()
    if not academia_id:
        flash("Seu cadastro não está vinculado a uma academia.", "warning")
        return redirect(url_for("painel.home"))

    vitrine, _ = _loja_da_academia(academia_id, tipo)

    if request.method == "POST":
        acao = request.form.get("acao")
        if acao == "limpar":
            carrinho.limpar(academia_id)
            flash("Carrinho esvaziado.", "success")
            return redirect(url_for("estoque.carrinho_ver"))
        if acao == "atualizar":
            por_id = {i["id"]: i for i in vitrine}
            for chave, valor in request.form.items():
                if not chave.startswith("qtd_"):
                    continue
                vid = int(chave.split("_", 1)[1])
                carrinho.por(academia_id, vid, valor,
                             limite=(por_id.get(vid) or {}).get("saldo"))
            flash("Carrinho atualizado.", "success")
            return redirect(url_for("estoque.carrinho_ver"))
        if acao == "fechar":
            return _fechar_carrinho(academia_id, tipo, pessoa_id, vitrine)

    linhas, total, alertas = carrinho.detalhar(academia_id, vitrine)
    for a in alertas:
        flash(a, "warning")
    return render_template("estoque/carrinho.html", linhas=linhas, total=total,
                           academia_id=academia_id)


def _marcar_aguardando(pedido_id):
    """Tira o pedido de rascunho: agora ele é um compromisso.

    É esta linha que faz o pedido aparecer para a recepção. Enquanto está
    `aberto`, ele é só o carrinho materializado, e a tela de pedidos o ignora.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE estoque_pedido SET status = 'aguardando_pagamento' "
                    "WHERE id = %s AND status = 'aberto'", (pedido_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _fechar_carrinho(academia_id, tipo, pessoa_id, vitrine):
    """Transforma o carrinho em pedido. Aqui ele deixa de ser rascunho."""
    linhas, total, alertas = carrinho.detalhar(academia_id, vitrine)
    for a in alertas:
        flash(a, "warning")
    if not linhas:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("estoque.loja"))

    locais = {l["local_id"] for l in linhas}
    if len(locais) != 1:
        flash("Os itens vêm de depósitos diferentes. "
              "Feche um pedido para cada — a entrega é separada.", "warning")
        return redirect(url_for("estoque.carrinho_ver"))
    local_id = locais.pop()
    local_assoc = linhas[0]["local_assoc"]

    pedido_id = None
    try:
        pedido_id = venda.criar_pedido(
            id_academia=academia_id, id_associacao=local_assoc,
            local_id=local_id, comprador_tipo=tipo,
            aluno_id=pessoa_id if tipo == "aluno" else None,
            visitante_id=pessoa_id if tipo == "visitante" else None,
            usuario_id=current_user.id, origem="autoatendimento",
            comprador_nome=current_user.nome, criado_por=current_user.id,
            observacao=(request.form.get("observacao") or "").strip() or None)
        for l in linhas:
            venda.adicionar_item(pedido_id, l["id"], l["quantidade"])
        _marcar_aguardando(pedido_id)
        carrinho.limpar(academia_id)
        flash("Pedido enviado. A recepção separa os itens e confirma — "
              "o estoque só baixa na confirmação.", "success")
        return redirect(url_for("estoque.meus_pedidos"))
    except est.EstoqueErro as e:
        if pedido_id:
            try:
                venda.cancelar(pedido_id, usuario_id=current_user.id)
            except Exception:
                pass
        flash(str(e), "warning")
        return redirect(url_for("estoque.carrinho_ver"))


@bp_estoque.route("/carrinho/<int:variacao_id>", methods=["POST"])
@login_required
def carrinho_por(variacao_id):
    """Põe, muda ou tira um item. Volta para onde o comprador estava."""
    tipo, _pessoa, academia_id = _quem_sou()
    if not academia_id:
        return redirect(url_for("painel.home"))
    vitrine, _ = _loja_da_academia(academia_id, tipo)
    item = next((i for i in vitrine if i["id"] == variacao_id), None)
    if not item:
        flash("Item indisponível.", "warning")
        return redirect(url_for("estoque.loja"))

    if request.form.get("acao") == "remover":
        carrinho.por(academia_id, variacao_id, 0)
        flash("Item removido do carrinho.", "success")
    else:
        qtd = carrinho.somar(academia_id, variacao_id,
                             request.form.get("quantidade", type=int) or 1,
                             limite=item["saldo"])
        if qtd:
            flash(f"{item['produto']} no carrinho ({qtd}).", "success")
        else:
            flash("Item sem saldo disponível.", "warning")
    destino = request.form.get("voltar") or url_for("estoque.loja")
    return redirect(destino)


@bp_estoque.route("/meus-pedidos")
@login_required
def meus_pedidos():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT p.*, a.nome AS academia FROM estoque_pedido p
                       LEFT JOIN academias a ON a.id = p.id_academia
                       WHERE p.usuario_id = %s
                       ORDER BY p.criado_em DESC LIMIT 50""", (current_user.id,))
        pedidos = cur.fetchall() or []
        for p in pedidos:
            cur.execute("""SELECT i.quantidade, i.preco_unitario,
                                  v.nome AS variacao, pr.nome AS produto
                           FROM estoque_pedido_item i
                           JOIN estoque_variacao v ON v.id = i.variacao_id
                           JOIN estoque_produto pr ON pr.id = v.produto_id
                           WHERE i.pedido_id = %s""", (p["id"],))
            p["itens"] = cur.fetchall() or []
    finally:
        cur.close()
        conn.close()
    return render_template("estoque/meus_pedidos.html", pedidos=pedidos)


@bp_estoque.route("/pedidos")
@login_required
@permission_required("estoque_saida")
def pedidos():
    """Pedidos do autoatendimento esperando a recepção."""
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT p.*, a.nome AS aluno_nome, l.nome AS local
                       FROM estoque_pedido p
                       LEFT JOIN alunos a ON a.id = p.aluno_id
                       JOIN estoque_local l ON l.id = p.local_id
                       WHERE p.id_academia = %s
                         AND p.status = 'aguardando_pagamento'
                       ORDER BY p.criado_em""", (ctx["id"],))
        lista = cur.fetchall() or []
        for p in lista:
            cur.execute("""SELECT i.quantidade, i.preco_unitario,
                                  v.nome AS variacao, pr.nome AS produto
                           FROM estoque_pedido_item i
                           JOIN estoque_variacao v ON v.id = i.variacao_id
                           JOIN estoque_produto pr ON pr.id = v.produto_id
                           WHERE i.pedido_id = %s""", (p["id"],))
            p["itens"] = cur.fetchall() or []
    finally:
        cur.close()
        conn.close()
    return render_template("estoque/pedidos.html", ctx=ctx, pedidos=lista)


@bp_estoque.route("/pedidos/<int:pedido_id>/<acao>", methods=["POST"])
@login_required
@permission_required("estoque_saida")
def pedido_decidir(pedido_id, acao):
    ctx = _exigir_contexto()
    if not ctx:
        return redirect(url_for("painel.home"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id_academia FROM estoque_pedido WHERE id = %s", (pedido_id,))
        p = cur.fetchone()
        if not p or p["id_academia"] != ctx["id"]:
            flash("Pedido não encontrado nesta academia.", "warning")
            return redirect(url_for("estoque.pedidos"))
    finally:
        cur.close()
        conn.close()
    try:
        if acao == "confirmar":
            r = venda.confirmar(
                pedido_id, usuario_id=current_user.id,
                forma_pagamento=(request.form.get("forma_pagamento") or "").strip() or None)
            msg = f"Pedido confirmado: R$ {r['total']:.2f}."
            if r["repasse"]:
                msg += f" Repasse de R$ {r['repasse']:.2f} à associação."
            flash(msg, "success")
        elif acao == "cancelar":
            venda.cancelar(pedido_id, usuario_id=current_user.id,
                           motivo=(request.form.get("motivo") or "").strip() or None)
            flash("Pedido cancelado.", "success")
    except est.EstoqueErro as e:
        flash(str(e), "warning")
    return redirect(url_for("estoque.pedidos"))
