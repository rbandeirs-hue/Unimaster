# blueprints/cadastros/routes.py

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from config import get_db_connection
from utils.decorators import role_required
from . import cadastros_bp
import unicodedata


# ==========================================================
# 🔹 HUB DE CADASTROS (centro de navegação)
# ==========================================================
@cadastros_bp.route("/")
@login_required
def hub():
    """
    Página principal dos Cadastros.
    Aqui o usuário vê as opções de cadastros que ele tem permissão para acessar.
    """
    return render_template("cadastros/hub.html")


# ==========================================================
# 🔹 Gerenciar Graduações (regras de transição)
# ==========================================================
@cadastros_bp.route("/graduacoes", methods=["GET", "POST"])
@role_required("admin")
def gerenciar_graduacoes():
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
    except Exception as e:
        flash(f"Erro ao conectar no banco: {e}", "danger")
        return render_template("graduacoes/gerenciar_gradacoes.html", graduacoes=[])

    cursor.execute("SHOW COLUMNS FROM graduacao")
    colunas_info = {row["Field"]: row["Type"].lower() for row in cursor.fetchall()}

    col_idade_minima = "idade_minima" if "idade_minima" in colunas_info else None
    col_carencia_meses = "carencia_meses" if "carencia_meses" in colunas_info else None
    col_carencia_dias = "carencia_dias" if "carencia_dias" in colunas_info else None
    col_carencia = "carencia" if "carencia" in colunas_info else None
    col_carencia_minima = (
        "carencia_minima" if "carencia_minima" in colunas_info else None
    )
    col_observacao = "observacao" if "observacao" in colunas_info else None

    def coluna_numerica(nome_coluna):
        tipo = colunas_info.get(nome_coluna, "")
        return any(t in tipo for t in ("int", "decimal", "float", "double"))

    if request.method == "POST":
        ids = request.form.getlist("id")
        faixas = request.form.getlist("faixa")
        graduacoes = request.form.getlist("graduacao")
        categorias = request.form.getlist("categoria")
        idades_minimas = request.form.getlist("idade_minima") if col_idade_minima else []
        carencias_meses = request.form.getlist("carencia_meses") if col_carencia_meses else []
        carencias_dias = request.form.getlist("carencia_dias") if col_carencia_dias else []
        carencias = request.form.getlist("carencia") if (col_carencia and not (col_carencia_meses or col_carencia_dias)) else []
        carencias_minimas = (
            request.form.getlist("carencia_minima") if col_carencia_minima else []
        )
        observacoes = request.form.getlist("observacao") if col_observacao else []

        total = len(ids)
        listas = [faixas, graduacoes, categorias]
        if col_idade_minima:
            listas.append(idades_minimas)
        if col_carencia_meses:
            listas.append(carencias_meses)
        if col_carencia_dias:
            listas.append(carencias_dias)
        if col_carencia and not (col_carencia_meses or col_carencia_dias):
            listas.append(carencias)
        if col_carencia_minima:
            listas.append(carencias_minimas)
        if col_observacao:
            listas.append(observacoes)

        if not all(len(lst) == total for lst in listas):
            db.close()
            flash("Erro ao salvar: dados inconsistentes no formulário.", "danger")
            return redirect(url_for("cadastros.gerenciar_graduacoes"))

        def parse_int(valor):
            valor = (valor or "").strip()
            if not valor:
                return None
            try:
                return int(valor)
            except ValueError:
                return None

        def normalizar_valor(nome_coluna, valor):
            valor = (valor or "").strip()
            if not valor:
                return None
            if coluna_numerica(nome_coluna):
                digitos = "".join(ch for ch in valor if ch.isdigit())
                return int(digitos) if digitos else None
            return valor

        try:
            for idx in range(total):
                set_partes = ["faixa=%s", "graduacao=%s", "categoria=%s"]
                valores = [
                    faixas[idx].strip() if faixas[idx] else None,
                    graduacoes[idx].strip() if graduacoes[idx] else None,
                    categorias[idx].strip() if categorias[idx] else None,
                ]

                if col_idade_minima:
                    set_partes.append("idade_minima=%s")
                    valores.append(normalizar_valor(col_idade_minima, idades_minimas[idx]))

                if col_carencia_meses:
                    set_partes.append("carencia_meses=%s")
                    valores.append(normalizar_valor(col_carencia_meses, carencias_meses[idx]))

                if col_carencia_dias:
                    set_partes.append("carencia_dias=%s")
                    valores.append(normalizar_valor(col_carencia_dias, carencias_dias[idx]))

                if col_carencia and not (col_carencia_meses or col_carencia_dias):
                    set_partes.append("carencia=%s")
                    valores.append(normalizar_valor(col_carencia, carencias[idx]))

                if col_carencia_minima:
                    set_partes.append("carencia_minima=%s")
                    valores.append(
                        normalizar_valor(col_carencia_minima, carencias_minimas[idx])
                    )

                if col_observacao:
                    set_partes.append("observacao=%s")
                    valores.append(
                        normalizar_valor(col_observacao, observacoes[idx])
                    )

                valores.append(ids[idx])
                cursor.execute(
                    f"""
                    UPDATE graduacao
                    SET {", ".join(set_partes)}
                    WHERE id=%s
                    """,
                    tuple(valores),
                )

            db.commit()
            flash("Graduações atualizadas com sucesso.", "success")
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar graduações: {e}", "danger")

    graduacoes = []
    try:
        select_cols = ["id", "faixa", "graduacao", "categoria"]
        if col_idade_minima:
            select_cols.append(col_idade_minima)
        if col_carencia_meses:
            select_cols.append(col_carencia_meses)
        if col_carencia_dias:
            select_cols.append(col_carencia_dias)
        if col_carencia and not (col_carencia_meses or col_carencia_dias):
            select_cols.append(col_carencia)
        if col_carencia_minima:
            select_cols.append(col_carencia_minima)
        if col_observacao:
            select_cols.append(col_observacao)

        cursor.execute(
            f"""
            SELECT {", ".join(select_cols)}
            FROM graduacao
            ORDER BY id
            """
        )
        graduacoes = cursor.fetchall()
    except Exception as e:
        flash(f"Erro ao carregar graduações: {e}", "danger")
    finally:
        db.close()

    return render_template(
        "graduacoes/gerenciar_gradacoes.html",
        graduacoes=graduacoes,
        col_idade_minima=col_idade_minima,
        col_carencia_meses=col_carencia_meses,
        col_carencia_dias=col_carencia_dias,
        col_carencia=col_carencia,
        col_carencia_minima=col_carencia_minima,
        col_observacao=col_observacao,
    )


# ==========================================================
# 🔹 Gerenciar Categorias (tabela categorias)
# ==========================================================
def _render_categorias():
    def parse_int(valor):
        valor = (valor or "").strip()
        if not valor:
            return None
        try:
            return int(valor)
        except ValueError:
            return None

    def parse_float(valor):
        valor = (valor or "").strip().replace(",", ".")
        if not valor:
            return None
        try:
            return float(valor)
        except ValueError:
            return None

    def carregar_colunas(cursor, tabela):
        try:
            cursor.execute(f"SHOW COLUMNS FROM {tabela}")
            cols = cursor.fetchall()
            col_map = {}
            for c in cols:
                key = c["Field"].lower()
                col_map[key] = c["Field"]
                key_norm = "".join(
                    ch for ch in unicodedata.normalize("NFKD", key) if not unicodedata.combining(ch)
                )
                col_map.setdefault(key_norm, c["Field"])
            return col_map
        except Exception:
            return {}

    def resolver_colunas(col_map, aliases):
        resolved = {}
        missing = []
        for key, options in aliases.items():
            found = None
            for opt in options:
                if opt in col_map:
                    found = col_map[opt]
                    break
            if not found:
                missing.append(key)
            resolved[key] = found
        return resolved, missing

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
    except Exception as e:
        flash(f"Erro ao conectar no banco: {e}", "danger")
        return render_template("categorias/gerenciar_categorias.html", categorias=[])

    tabela_categorias = "categorias"
    col_map = carregar_colunas(cursor, tabela_categorias)

    cols, missing = resolver_colunas(
        col_map,
        {
            "id": ["id"],
            "genero": ["genero", "sexo", "gender"],
            "id_classe": ["id_classe", "classe"],
            "categoria": ["categoria"],
            "nome_categoria": ["nome_categoria", "nome"],
            "peso_min": ["peso_min", "peso_minimo", "min_peso"],
            "peso_max": ["peso_max", "peso_maximo", "max_peso"],
            "idade_min": ["idade_min", "idade_minima", "min_idade"],
            "idade_max": ["idade_max", "idade_maxima", "max_idade"],
            "descricao": ["descricao", "notas", "observacao", "obs"],
        },
    )

    if request.method == "POST":
        form_tipo = request.form.get("form_tipo")
        try:
            if form_tipo == "categorias" and not missing:
                ids = request.form.getlist("id")
                generos = request.form.getlist("genero")
                id_classes = request.form.getlist("id_classe")
                categorias = request.form.getlist("categoria")
                nomes = request.form.getlist("nome_categoria")
                pesos_min = request.form.getlist("peso_min")
                pesos_max = request.form.getlist("peso_max")
                idades_min = request.form.getlist("idade_min")
                idades_max = request.form.getlist("idade_max")
                descricoes = request.form.getlist("descricao")

                total = len(ids)
                if not all(len(lst) == total for lst in [generos, id_classes, categorias, nomes, pesos_min, pesos_max, idades_min, idades_max, descricoes]):
                    flash("Erro ao salvar categorias: dados inconsistentes.", "danger")
                else:
                    for i in range(total):
                        cursor.execute(
                            f"""
                            UPDATE {tabela_categorias}
                            SET {cols['genero']}=%s,
                                {cols['id_classe']}=%s,
                                {cols['categoria']}=%s,
                                {cols['nome_categoria']}=%s,
                                {cols['peso_min']}=%s,
                                {cols['peso_max']}=%s,
                                {cols['idade_min']}=%s,
                                {cols['idade_max']}=%s,
                                {cols['descricao']}=%s
                            WHERE {cols['id']}=%s
                            """,
                            (
                                generos[i].strip() if generos[i] else None,
                                id_classes[i].strip() if id_classes[i] else None,
                                categorias[i].strip() if categorias[i] else None,
                                nomes[i].strip() if nomes[i] else None,
                                parse_float(pesos_min[i]),
                                parse_float(pesos_max[i]),
                                parse_int(idades_min[i]),
                                parse_int(idades_max[i]),
                                descricoes[i].strip() if descricoes[i] else None,
                                ids[i],
                            ),
                        )
                    db.commit()
                    flash("Categorias atualizadas com sucesso.", "success")
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar categorias: {e}", "danger")

    categorias_lista = []
    try:
        if not missing:
            cursor.execute(
                f"""
                SELECT {cols['id']} AS id,
                       {cols['genero']} AS genero,
                       {cols['id_classe']} AS id_classe,
                       {cols['categoria']} AS categoria,
                       {cols['nome_categoria']} AS nome_categoria,
                       {cols['peso_min']} AS peso_min,
                       {cols['peso_max']} AS peso_max,
                       {cols['idade_min']} AS idade_min,
                       {cols['idade_max']} AS idade_max,
                       {cols['descricao']} AS descricao
                FROM {tabela_categorias}
                ORDER BY {cols['id']}
                """
            )
            categorias_lista = cursor.fetchall()
        else:
            flash(
                "Tabela de categorias não encontrada ou colunas ausentes: "
                + ", ".join(missing),
                "danger",
            )
    except Exception as e:
        flash(f"Erro ao carregar categorias: {e}", "danger")
    finally:
        db.close()

    return render_template(
        "categorias/gerenciar_categorias.html",
        categorias=categorias_lista,
    )


@cadastros_bp.route("/categorias", methods=["GET", "POST"])
@role_required("admin")
def gerenciar_categorias():
    return _render_categorias()
