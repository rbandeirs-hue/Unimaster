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
# 🔹 Gerenciar Categorias (classes + pesos)
# ==========================================================
def _render_categorias(show_classes=True, show_pesos=True):
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
        return render_template("categorias/gerenciar_categorias.html", classes=[], pesos=[])

    tabela_classes = "classes_judo"
    tabela_pesos = "categorias_peso"
    col_map_classes = carregar_colunas(cursor, tabela_classes)
    col_map_pesos = carregar_colunas(cursor, tabela_pesos)

    cols_classes, missing_classes = resolver_colunas(
        col_map_classes,
        {
            "id_classe": ["id_classe", "id", "idclasse"],
            "classe": ["classe", "nome", "descricao"],
            "idade_min": ["idade_min", "idade_minima", "min_idade"],
            "idade_max": ["idade_max", "idade_maxima", "max_idade"],
            "notas": ["notas", "observacao", "obs"],
        },
    )

    cols_pesos, missing_pesos = resolver_colunas(
        col_map_pesos,
        {
            "id_peso": ["id_peso", "id", "idpeso"],
            "genero": ["genero", "sexo", "gender"],
            "id_classe_fk": ["id_classe_fk", "id_classe", "classe_id", "classe_fk"],
            "categoria": ["categoria"],
            "nome_categoria": ["nome_categoria", "nome"],
            "peso_min": ["peso_min", "peso_minimo", "min_peso"],
            "peso_max": ["peso_max", "peso_maximo", "max_peso"],
        },
    )

    if request.method == "POST":
        form_tipo = request.form.get("form_tipo")
        try:
            if form_tipo == "classes" and show_classes and not missing_classes:
                ids = request.form.getlist("id_classe")
                classes = request.form.getlist("classe")
                idades_min = request.form.getlist("idade_min")
                idades_max = request.form.getlist("idade_max")
                notas = request.form.getlist("notas")

                total = len(ids)
                if not all(len(lst) == total for lst in [classes, idades_min, idades_max, notas]):
                    flash("Erro ao salvar classes: dados inconsistentes.", "danger")
                else:
                    for i in range(total):
                        cursor.execute(
                            f"""
                            UPDATE {tabela_classes}
                            SET {cols_classes['classe']}=%s,
                                {cols_classes['idade_min']}=%s,
                                {cols_classes['idade_max']}=%s,
                                {cols_classes['notas']}=%s
                            WHERE {cols_classes['id_classe']}=%s
                            """,
                            (
                                classes[i].strip() if classes[i] else None,
                                parse_int(idades_min[i]),
                                parse_int(idades_max[i]),
                                notas[i].strip() if notas[i] else None,
                                ids[i],
                            ),
                        )
                    db.commit()
                    flash("Classes/Idades atualizadas com sucesso.", "success")

            if form_tipo == "pesos" and show_pesos and not missing_pesos:
                ids = request.form.getlist("id_peso")
                generos = request.form.getlist("genero")
                classes_fk = request.form.getlist("id_classe_fk")
                categorias = request.form.getlist("categoria")
                nomes = request.form.getlist("nome_categoria")
                pesos_min = request.form.getlist("peso_min")
                pesos_max = request.form.getlist("peso_max")

                total = len(ids)
                if not all(len(lst) == total for lst in [generos, classes_fk, categorias, nomes, pesos_min, pesos_max]):
                    flash("Erro ao salvar pesos: dados inconsistentes.", "danger")
                else:
                    for i in range(total):
                        cursor.execute(
                            f"""
                            UPDATE {tabela_pesos}
                            SET {cols_pesos['genero']}=%s,
                                {cols_pesos['id_classe_fk']}=%s,
                                {cols_pesos['categoria']}=%s,
                                {cols_pesos['nome_categoria']}=%s,
                                {cols_pesos['peso_min']}=%s,
                                {cols_pesos['peso_max']}=%s
                            WHERE {cols_pesos['id_peso']}=%s
                            """,
                            (
                                generos[i].strip() if generos[i] else None,
                                classes_fk[i].strip() if classes_fk[i] else None,
                                categorias[i].strip() if categorias[i] else None,
                                nomes[i].strip() if nomes[i] else None,
                                parse_float(pesos_min[i]),
                                parse_float(pesos_max[i]),
                                ids[i],
                            ),
                        )
                    db.commit()
                    flash("Categorias de peso atualizadas com sucesso.", "success")
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar categorias: {e}", "danger")

    classes = []
    pesos = []
    try:
        if show_classes and not missing_classes:
            cursor.execute(
                f"""
                SELECT {cols_classes['id_classe']} AS id_classe,
                       {cols_classes['classe']} AS classe,
                       {cols_classes['idade_min']} AS idade_min,
                       {cols_classes['idade_max']} AS idade_max,
                       {cols_classes['notas']} AS notas
                FROM {tabela_classes}
                ORDER BY {cols_classes['id_classe']}
                """
            )
            classes = cursor.fetchall()
        elif show_classes:
            flash(
                "Tabela de classes/idades não encontrada ou colunas ausentes: "
                + ", ".join(missing_classes),
                "danger",
            )

        if show_pesos and not missing_pesos:
            cursor.execute(
                f"""
                SELECT {cols_pesos['id_peso']} AS id_peso,
                       {cols_pesos['genero']} AS genero,
                       {cols_pesos['id_classe_fk']} AS id_classe_fk,
                       {cols_pesos['categoria']} AS categoria,
                       {cols_pesos['nome_categoria']} AS nome_categoria,
                       {cols_pesos['peso_min']} AS peso_min,
                       {cols_pesos['peso_max']} AS peso_max
                FROM {tabela_pesos}
                ORDER BY {cols_pesos['id_peso']}
                """
            )
            pesos = cursor.fetchall()
        elif show_pesos:
            flash(
                "Tabela de categorias de peso não encontrada ou colunas ausentes: "
                + ", ".join(missing_pesos),
                "danger",
            )
    except Exception as e:
        flash(f"Erro ao carregar categorias: {e}", "danger")
    finally:
        db.close()

    return render_template(
        "categorias/gerenciar_categorias.html",
        classes=classes,
        pesos=pesos,
        show_classes=show_classes,
        show_pesos=show_pesos,
    )


@cadastros_bp.route("/categorias", methods=["GET", "POST"])
@role_required("admin")
def gerenciar_categorias():
    return _render_categorias(show_classes=True, show_pesos=True)


@cadastros_bp.route("/categorias/classes", methods=["GET", "POST"])
@role_required("admin")
def categorias_classes():
    return _render_categorias(show_classes=True, show_pesos=False)


@cadastros_bp.route("/categorias/pesos", methods=["GET", "POST"])
@role_required("admin")
def categorias_pesos():
    return _render_categorias(show_classes=False, show_pesos=True)
