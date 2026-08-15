# ======================================================
# 🧩 Blueprint: Painel do Aluno
# ======================================================

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_required, current_user
from config import get_db_connection
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from blueprints.presencas.presencas import _garantir_tabela_presencas_observacao_aluno


bp_painel_aluno = Blueprint(
    "painel_aluno",
    __name__,
    url_prefix="/painel_aluno"
)


def _build_endereco_completo(aluno):
    """Monta o endereço completo para exibição no currículo."""
    partes = []
    rua = aluno.get("rua") or aluno.get("endereco") or ""
    numero = aluno.get("numero")
    if rua:
        partes.append(f"{rua}{', ' + str(numero) if numero else ''}")
    elif numero:
        partes.append(f"Nº {numero}")
    if aluno.get("complemento"):
        partes.append(str(aluno.get("complemento")))
    if aluno.get("bairro"):
        partes.append(str(aluno.get("bairro")))
    cidade = aluno.get("cidade") or ""
    estado = aluno.get("estado") or ""
    if cidade or estado:
        partes.append(f"{cidade}{' - ' + estado if estado else ''}".strip(" -"))
    cep = aluno.get("cep")
    if cep:
        cep_str = str(cep).replace("-", "").replace(".", "")[:8]
        partes.append(f"CEP {cep_str}")
    aluno["endereco_completo"] = ", ".join(p for p in partes if p) or None


def _get_aluno():
    """Retorna o aluno vinculado ao usuário ou None."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM alunos WHERE usuario_id = %s", (current_user.id,))
    aluno = cur.fetchone()
    cur.close()
    conn.close()
    return aluno


def _aluno_required(f):
    """Decorator: exige role aluno/admin e aluno vinculado."""
    from functools import wraps
    @wraps(f)
    def _view(*a, **kw):
        if not (current_user.has_role("aluno") or current_user.has_role("admin")):
            flash("Acesso restrito aos alunos.", "danger")
            return redirect(url_for("painel.home"))
        aluno = _get_aluno()
        if not aluno:
            flash("Nenhum aluno está vinculado a este usuário.", "warning")
            return redirect(url_for("painel.home"))
        return f(*a, aluno=aluno, **kw)
    return _view


def _enriquecer_aluno_painel(aluno):
    """Adiciona academia_nome, turma_nome, modalidades, faixa, proxima_faixa ao aluno."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Inicializar valores padrão
        aluno.setdefault("academia_nome", None)
        aluno.setdefault("turma_nome", None)
        aluno.setdefault("faixa_nome", None)
        aluno.setdefault("graduacao_nome", None)
        
        cur.execute(
            """SELECT ac.nome AS academia_nome, t.Nome AS turma_nome
               FROM alunos a
               LEFT JOIN academias ac ON ac.id = a.id_academia
               LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
               WHERE a.id = %s""",
            (aluno["id"],),
        )
        row = cur.fetchone()
        if row:
            aluno["academia_nome"] = row.get("academia_nome")
            aluno["turma_nome"] = row.get("turma_nome")
        
        # Se não encontrou turma no JOIN, tentar buscar diretamente pelo TurmaID
        if not aluno.get("turma_nome") and aluno.get("TurmaID"):
            cur.execute("SELECT Nome FROM turmas WHERE TurmaID = %s", (aluno.get("TurmaID"),))
            turma_row = cur.fetchone()
            if turma_row:
                aluno["turma_nome"] = turma_row.get("Nome")
        
        # Se ainda não encontrou, tentar buscar via aluno_turmas
        if not aluno.get("turma_nome"):
            cur.execute(
                """SELECT t.Nome FROM aluno_turmas at
                   INNER JOIN turmas t ON t.TurmaID = at.TurmaID
                   WHERE at.aluno_id = %s
                   ORDER BY at.TurmaID LIMIT 1""",
                (aluno["id"],),
            )
            turma_row = cur.fetchone()
            if turma_row:
                aluno["turma_nome"] = turma_row.get("Nome")
        
        cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (aluno.get("graduacao_id"),))
        g = cur.fetchone()
        if g:
            aluno["faixa_nome"] = g.get("faixa")
            aluno["graduacao_nome"] = g.get("graduacao")
        cur.execute(
            """SELECT m.nome FROM modalidade m
               INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id
               WHERE am.aluno_id = %s ORDER BY m.nome""",
            (aluno["id"],),
        )
        modalidades_list = [r["nome"] for r in cur.fetchall()]
        aluno["modalidades"] = modalidades_list
        aluno["modalidades_nomes"] = ", ".join(modalidades_list) if modalidades_list else "-"
        aluno["proxima_faixa"] = "—"
        cur.execute("SELECT id, faixa, graduacao FROM graduacao ORDER BY id")
        faixas = cur.fetchall()
        gid = aluno.get("graduacao_id")
        for i, f in enumerate(faixas):
            if f["id"] == gid and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                aluno["proxima_faixa"] = f"{proxima.get('faixa', '')} {proxima.get('graduacao', '')}".strip() or "—"
                break
    except Exception:
        pass
    finally:
        cur.close()
        conn.close()


def _formatar_carencia(meses, dias):
    """Formata carência em formato legível (anos, meses, dias).
    
    Converte meses e dias em anos quando apropriado:
    - Se tiver meses, usa apenas meses (não soma com dias, pois são equivalentes)
    - Se não tiver meses mas tiver dias, usa dias
    - 12 meses ou mais = X anos
    - Exemplo: 6 meses + 180 dias = 6 meses (não soma, pois são equivalentes)
    """
    if not meses and not dias:
        return "Sem carência"
    
    # Se tiver meses, usar apenas meses (não somar com dias)
    if meses > 0:
        # Converter meses em anos (12 meses = 1 ano)
        anos = meses // 12
        meses_finais = meses % 12
        
        partes = []
        if anos > 0:
            partes.append(f"{anos} {'ano' if anos == 1 else 'anos'}")
        if meses_finais > 0:
            partes.append(f"{meses_finais} {'mês' if meses_finais == 1 else 'meses'}")
        
        return " + ".join(partes) if partes else "Sem carência"
    
    # Se não tiver meses mas tiver dias, usar dias
    if dias > 0:
        # Converter dias para meses primeiro (30 dias = 1 mês)
        meses_totais = dias // 30
        dias_restantes = dias % 30
        
        # Converter meses em anos (12 meses = 1 ano)
        anos = meses_totais // 12
        meses_finais = meses_totais % 12
        
        partes = []
        if anos > 0:
            partes.append(f"{anos} {'ano' if anos == 1 else 'anos'}")
        if meses_finais > 0:
            partes.append(f"{meses_finais} {'mês' if meses_finais == 1 else 'meses'}")
        if dias_restantes > 0:
            partes.append(f"{dias_restantes} {'dia' if dias_restantes == 1 else 'dias'}")
        
        return " + ".join(partes) if partes else "Sem carência"
    
    return "Sem carência"


def _calcular_graduacao_prevista(aluno):
    """Calcula a linha do tempo de graduações previstas para o aluno baseado em faixas_judo com previsao=1."""
    if not aluno or not aluno.get("id"):
        return []
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    graduacoes_previstas = []
    
    try:
        # Buscar dados do aluno
        # Usar previsao_proximo_exame se disponível, senão usar ultimo_exame_faixa
        previsao_proximo_exame = aluno.get("previsao_proximo_exame")
        ultimo_exame = aluno.get("ultimo_exame_faixa")
        graduacao_atual_id = aluno.get("graduacao_id")
        data_nascimento = aluno.get("data_nascimento")
        
        # Determinar a data base para o cálculo
        # Se não houver previsao_proximo_exame informada, não calcular (retornar vazio)
        if not previsao_proximo_exame:
            return []
        
        # Usar previsao_proximo_exame como data base
        data_base_calculo = previsao_proximo_exame
        
        if not graduacao_atual_id:
            return []
        
        # Converter data_nascimento se for string
        if isinstance(data_nascimento, str):
            try:
                data_nascimento = datetime.strptime(data_nascimento[:10], "%Y-%m-%d").date()
            except:
                return []
        
        # Converter data_base_calculo se for string
        if isinstance(data_base_calculo, str):
            try:
                data_base_calculo = datetime.strptime(data_base_calculo[:10], "%Y-%m-%d").date()
            except:
                return []
        
        # Converter ultimo_exame se for string (para uso posterior se necessário)
        if isinstance(ultimo_exame, str):
            try:
                ultimo_exame = datetime.strptime(ultimo_exame[:10], "%Y-%m-%d").date()
            except:
                ultimo_exame = None
        
        # Buscar todas as faixas com previsao = 1, ordenadas por ID
        cur.execute("""
            SELECT ID, Faixa, Graduacao, Idade_Minima, Carencia_Meses, Carencia_Dias
            FROM faixas_judo
            WHERE previsao = 1
            ORDER BY ID
        """)
        faixas_previstas = cur.fetchall()
        
        if not faixas_previstas:
            return []
        
        # Encontrar a posição da faixa atual do aluno
        # Precisamos mapear graduacao_id para ID de faixas_judo
        # Vamos buscar a faixa atual na tabela graduacao e tentar encontrar correspondência
        cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (graduacao_atual_id,))
        faixa_atual_info = cur.fetchone()
        
        if not faixa_atual_info:
            return []
        
        # Encontrar o índice da faixa atual em faixas_judo
        indice_atual = -1
        faixa_atual_norm = faixa_atual_info.get("faixa", "").upper().strip()
        graduacao_atual_norm = faixa_atual_info.get("graduacao", "").upper().strip()
        
        # Normalizar removendo caracteres especiais, espaços extras e normalizando barras
        def normalizar_texto(texto):
            if not texto:
                return ""
            texto = texto.upper().strip()
            # Remover caracteres especiais e normalizar variações
            texto = texto.replace("°", "").replace("º", "").replace("ª", "").replace("°", "")
            texto = texto.replace("Û", "U").replace("Ü", "U").replace("Ù", "U")
            texto = texto.replace("Â", "A").replace("Ã", "A").replace("Á", "A")
            # Normalizar barras (remover espaços ao redor)
            texto = texto.replace(" / ", "/").replace(" /", "/").replace("/ ", "/")
            # Remover espaços múltiplos
            while "  " in texto:
                texto = texto.replace("  ", " ")
            return texto.strip()
        
        faixa_atual_norm = normalizar_texto(faixa_atual_norm)
        graduacao_atual_norm = normalizar_texto(graduacao_atual_norm)
        
        for i, fj in enumerate(faixas_previstas):
            fj_faixa_norm = normalizar_texto(fj.get("Faixa", ""))
            fj_graduacao_norm = normalizar_texto(fj.get("Graduacao", ""))
            
            # Comparar faixa e graduação (case-insensitive, normalizado)
            # Aceita match se faixa E graduação corresponderem
            faixa_match = fj_faixa_norm == faixa_atual_norm
            graduacao_match = fj_graduacao_norm == graduacao_atual_norm
            
            if faixa_match and graduacao_match:
                indice_atual = i
                break
        
        # Se não encontrou com match exato, tentar apenas por graduação (mais flexível)
        # Mas só aceitar se a faixa também fizer sentido
        if indice_atual == -1:
            for i, fj in enumerate(faixas_previstas):
                fj_faixa_norm = normalizar_texto(fj.get("Faixa", ""))
                fj_graduacao_norm = normalizar_texto(fj.get("Graduacao", ""))
                # Comparação mais flexível: verifica se as graduações são equivalentes
                # E se a faixa tem alguma relação (contém ou é contida)
                if fj_graduacao_norm == graduacao_atual_norm:
                    # Verificar se a faixa também corresponde (pelo menos parcialmente)
                    if faixa_atual_norm in fj_faixa_norm or fj_faixa_norm in faixa_atual_norm:
                        indice_atual = i
                        break
        
        # Se ainda não encontrou, tentar apenas por faixa (último recurso)
        # Mas só aceitar se a graduação também fizer sentido
        if indice_atual == -1:
            for i, fj in enumerate(faixas_previstas):
                fj_faixa_norm = normalizar_texto(fj.get("Faixa", ""))
                fj_graduacao_norm = normalizar_texto(fj.get("Graduacao", ""))
                # Comparação mais flexível: verifica se as faixas são equivalentes
                # E se a graduação tem alguma relação
                if fj_faixa_norm == faixa_atual_norm:
                    # Verificar se a graduação também corresponde (pelo menos parcialmente)
                    if graduacao_atual_norm in fj_graduacao_norm or fj_graduacao_norm in graduacao_atual_norm:
                        indice_atual = i
                        break
        
        # Se ainda não encontrou, retornar vazio (não há como calcular sem saber a posição atual)
        if indice_atual == -1:
            return []
        
        # Calcular graduações previstas começando da PRÓXIMA faixa após a atual
        # range(indice_atual + 1, ...) garante que começamos da próxima faixa
        hoje = date.today()
        
        # Debug: verificar se o índice está correto
        if indice_atual >= 0 and indice_atual < len(faixas_previstas):
            faixa_atual_debug = faixas_previstas[indice_atual]
            if indice_atual + 1 < len(faixas_previstas):
                proxima_faixa_debug = faixas_previstas[indice_atual + 1]
                # Log para debug (pode remover depois)
                from flask import current_app
                try:
                    current_app.logger.debug(f"Faixa atual encontrada: {faixa_atual_debug.get('Faixa')} {faixa_atual_debug.get('Graduacao')} (índice {indice_atual})")
                    current_app.logger.debug(f"Próxima faixa será: {proxima_faixa_debug.get('Faixa')} {proxima_faixa_debug.get('Graduacao')} (índice {indice_atual + 1})")
                except:
                    pass
        
        for i in range(indice_atual + 1, len(faixas_previstas)):
            faixa = faixas_previstas[i]
            
            # Obter carência e idade mínima da faixa
            carencia_meses = faixa.get("Carencia_Meses") or 0
            carencia_dias = faixa.get("Carencia_Dias") or 0
            idade_minima = faixa.get("Idade_Minima") or 0
            
            # Se é a primeira faixa após a atual, usar a data informada pelo usuário como data prevista
            if i == indice_atual + 1:
                # A data informada é a data da próxima graduação (primeira prevista)
                data_prevista = data_base_calculo
                
                # Verificar se precisa aguardar a idade mínima
                data_idade_minima = None
                if idade_minima > 0 and data_nascimento:
                    data_idade_minima = data_nascimento + relativedelta(years=idade_minima)
                    # Se a data informada é anterior à idade mínima, usar a data da idade mínima
                    if data_idade_minima and data_prevista < data_idade_minima:
                        data_prevista = data_idade_minima
                
                # Garantir que a data prevista seja sempre no futuro (maior ou igual a hoje)
                if data_prevista < hoje:
                    data_prevista = hoje
            else:
                # Para as faixas seguintes, calcular a partir da faixa anterior + carência
                # Determinar a data base (data prevista da faixa anterior)
                data_base_para_carencia = graduacoes_previstas[-1]["data_prevista"]
                
                # PASSO 1: Calcular quando o aluno terá a idade mínima necessária
                data_idade_minima = None
                if idade_minima > 0 and data_nascimento:
                    # Data em que o aluno completará a idade mínima
                    data_idade_minima = data_nascimento + relativedelta(years=idade_minima)
                
                # PASSO 2: Aplicar carência da faixa atual a partir da data base
                # Se tiver meses, usar meses (não somar com dias, pois são equivalentes)
                # Se não tiver meses mas tiver dias, usar dias
                data_apos_carencia = data_base_para_carencia
                if carencia_meses > 0:
                    data_apos_carencia = data_apos_carencia + relativedelta(months=carencia_meses)
                elif carencia_dias > 0:
                    data_apos_carencia = data_apos_carencia + relativedelta(days=carencia_dias)
                
                # PASSO 3: Verificar se precisa aguardar a idade mínima
                # A data prevista será a mais recente entre: data após carência e data da idade mínima
                if data_idade_minima:
                    data_prevista = max(data_apos_carencia, data_idade_minima)
                else:
                    data_prevista = data_apos_carencia
                
                # Garantir que a data prevista seja sempre no futuro (maior ou igual a hoje)
                if data_prevista < hoje:
                    data_prevista = hoje
            
            # Calcular idade do aluno na data prevista
            idade_prevista = None
            if data_nascimento:
                idade_prevista = (data_prevista.year - data_nascimento.year - 
                                ((data_prevista.month, data_prevista.day) < 
                                 (data_nascimento.month, data_nascimento.day)))
            
            # Verificar se atende idade mínima na data prevista
            atende_idade_minima = idade_prevista is not None and idade_prevista >= idade_minima if idade_minima > 0 else True
            
            # Calcular ano previsto
            ano_previsto = data_prevista.year
            
            # Formatar carência em formato legível
            carencia_formatada = _formatar_carencia(carencia_meses, carencia_dias)
            
            graduacoes_previstas.append({
                "faixa": faixa.get("Faixa", ""),
                "graduacao": faixa.get("Graduacao", ""),
                "nome_completo": f"{faixa.get('Faixa', '')} {faixa.get('Graduacao', '')}".strip(),
                "data_prevista": data_prevista,
                "data_prevista_formatada": str(data_prevista.year),
                "ano_previsto": ano_previsto,
                "idade_prevista": idade_prevista,
                "idade_minima": idade_minima,
                "atende_idade_minima": atende_idade_minima,
                "carencia_meses": carencia_meses,
                "carencia_dias": carencia_dias,
                "carencia_formatada": carencia_formatada,
            })
        
        return graduacoes_previstas
        
    except Exception as e:
        import traceback
        print(f"Erro ao calcular graduação prevista: {e}")
        traceback.print_exc()
        return []
    finally:
        cur.close()
        conn.close()


def _enviar_push_aniversariantes_hoje(anivs_hoje: list, hoje) -> None:
    """Envia push ao usuário logado sobre aniversariantes do dia (uma vez por dia)."""
    if not anivs_hoje:
        return
    chave = f"push_aniv_{hoje.isoformat()}"
    if session.get(chave):
        return
    session[chave] = True
    try:
        from utils.push_notifications import enviar_push_usuario
        nomes = ", ".join(a["nome"].split()[0] for a in anivs_hoje[:3])
        sufixo = f" +{len(anivs_hoje)-3}" if len(anivs_hoje) > 3 else ""
        enviar_push_usuario(
            current_user.id,
            title="🎂 Aniversariantes hoje!",
            body=f"{nomes}{sufixo} fazem aniversário hoje. Envie uma mensagem!",
            url="/aluno/",
            tag="aniversario",
            require_interaction=True,
        )
    except Exception:
        pass


@bp_painel_aluno.route("/")
@login_required
@_aluno_required
def painel(aluno):
    session["modo_painel"] = "aluno"
    stats = _stats_painel_aluno(aluno)
    from utils.aniversariantes import aniversariantes_do_mes_aluno_associacao
    from datetime import date
    hoje = date.today()
    anivs = aniversariantes_do_mes_aluno_associacao(current_user.id, mes=hoje.month) or []
    anivs_hoje = [a for a in anivs if a["data_nascimento"] and
                  a["data_nascimento"].day == hoje.day]
    _enviar_push_aniversariantes_hoje(anivs_hoje, hoje)
    return render_template(
        "painel/painel_aluno.html",
        usuario=current_user,
        aluno=aluno,
        stats=stats,
        aniversariantes=anivs,
        aniversariantes_hoje=anivs_hoje,
        hoje_dia=hoje.day,
        hoje_mes=hoje.month,
        hoje_ano=hoje.year,
    )


@bp_painel_aluno.route("/meu-perfil")
@login_required
@_aluno_required
def meu_perfil(aluno):
    session["modo_painel"] = "aluno"
    _enriquecer_aluno_painel(aluno)
    from blueprints.aluno.alunos import enriquecer_aluno_para_modal
    enriquecer_aluno_para_modal(aluno)
    from utils.aniversariantes import aniversariantes_do_mes_aluno_associacao
    from datetime import date
    hoje = date.today()
    anivs = aniversariantes_do_mes_aluno_associacao(current_user.id, mes=hoje.month) or []
    anivs_hoje = [a for a in anivs if a["data_nascimento"] and
                  a["data_nascimento"].day == hoje.day]
    _enviar_push_aniversariantes_hoje(anivs_hoje, hoje)
    return render_template(
        "painel_aluno/meu_perfil.html",
        usuario=current_user,
        aluno=aluno,
        aniversariantes=anivs,
        aniversariantes_hoje=anivs_hoje,
        hoje_dia=hoje.day,
        hoje_mes=hoje.month,
        hoje_ano=hoje.year,
    )


@bp_painel_aluno.route("/simular-graduacao-prevista", methods=["GET", "POST"])
@login_required
@_aluno_required
def simular_graduacao_prevista(aluno):
    """Simula e exibe graduações previstas baseado na data informada pelo usuário."""
    try:
        session["modo_painel"] = "aluno"
        _enriquecer_aluno_painel(aluno)
        from blueprints.aluno.alunos import enriquecer_aluno_para_modal
        enriquecer_aluno_para_modal(aluno)
        
        graduacoes_previstas = []
        previsao_proximo_exame = None
        
        if request.method == "POST":
            # Obter mês/ano informado pelo usuário
            previsao_mes_ano = request.form.get("previsao_mes_ano", "").strip()
            if previsao_mes_ano:
                try:
                    # Converter formato YYYY-MM para date (primeiro dia do mês)
                    previsao_proximo_exame = datetime.strptime(previsao_mes_ano + "-01", "%Y-%m-%d").date()
                except ValueError:
                    flash("Data inválida. Use o formato mês/ano.", "danger")
                    return redirect(url_for("painel_aluno.simular_graduacao_prevista"))
        
        # Não usar previsão do banco, só calcular se informado no formulário
        if not previsao_proximo_exame:
            graduacoes_previstas = []
            previsao_input = None
        else:
            # Criar cópia do aluno com a previsão para o cálculo
            aluno_calculo = aluno.copy()
            aluno_calculo["previsao_proximo_exame"] = previsao_proximo_exame
            
            # Calcular graduações previstas usando a data informada
            graduacoes_previstas = _calcular_graduacao_prevista(aluno_calculo)
            
            # Formatar previsão para exibição no formulário
            if isinstance(previsao_proximo_exame, date):
                previsao_input = previsao_proximo_exame.strftime("%Y-%m")
            else:
                try:
                    previsao_input = datetime.strptime(str(previsao_proximo_exame)[:10], "%Y-%m-%d").strftime("%Y-%m")
                except:
                    previsao_input = None
        
        return render_template(
            "painel_aluno/simular_graduacao_prevista.html",
            aluno=aluno,
            graduacoes_previstas=graduacoes_previstas,
            previsao_proximo_exame_input=previsao_input,
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Erro em simular_graduacao_prevista: {e}", exc_info=True)
        flash(f"Erro ao carregar página: {str(e)}", "danger")
        return redirect(url_for("painel_aluno.painel"))


@bp_painel_aluno.route("/simular-categorias", methods=["GET", "POST"])
@login_required
@_aluno_required
def simular_categorias(aluno):
    """Simula e exibe categorias disponíveis baseado em peso, data de nascimento e sexo."""
    try:
        session["modo_painel"] = "aluno"
        
        categorias_disponiveis = []
        peso = None
        data_nascimento = None
        sexo = None
        idade_calculada = None
        
        # Formatar data_nascimento do aluno para o template se não vier do POST
        aluno_data_nasc_str = None
        if aluno:
            try:
                aluno_data_nasc = aluno.get("data_nascimento")
                if aluno_data_nasc:
                    if isinstance(aluno_data_nasc, date):
                        aluno_data_nasc_str = aluno_data_nasc.strftime("%Y-%m-%d")
                    else:
                        aluno_data_nasc_str = str(aluno_data_nasc)[:10]
            except Exception:
                aluno_data_nasc_str = None
        
        if request.method == "POST":
            peso_str = request.form.get("peso", "").strip()
            data_nascimento = request.form.get("data_nascimento", "").strip()
            sexo = request.form.get("sexo", "").strip()
            
            if peso_str and data_nascimento and sexo:
                try:
                    peso = float(peso_str)
                    nasc = datetime.strptime(data_nascimento[:10], "%Y-%m-%d").date()
                    hoje = date.today()
                    idade_calculada = hoje.year - nasc.year
                    genero_upper = sexo.upper()
                    
                    if genero_upper in ("M", "F") and peso > 0:
                        conn = get_db_connection()
                        cur = conn.cursor(dictionary=True)
                        try:
                            # Mapear M/F para MASCULINO/FEMININO
                            genero_db = "MASCULINO" if genero_upper == "M" else "FEMININO" if genero_upper == "F" else genero_upper
                            cur.execute("""
                                SELECT id, genero, id_classe, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max, descricao
                                FROM categorias
                                WHERE UPPER(genero) = UPPER(%s)
                                AND (
                                    (idade_min IS NULL OR %s >= idade_min)
                                    AND (idade_max IS NULL OR %s <= idade_max)
                                )
                                AND (
                                    (peso_min IS NULL OR %s >= peso_min)
                                    AND (peso_max IS NULL OR %s <= peso_max)
                                )
                                ORDER BY nome_categoria
                            """, (genero_db, idade_calculada, idade_calculada, peso, peso))
                            categorias_disponiveis = cur.fetchall()
                        finally:
                            cur.close()
                            conn.close()
                except Exception as e:
                    flash(f"Erro ao calcular categorias: {e}", "danger")
        
        # Garantir que categorias_disponiveis seja sempre uma lista
        if categorias_disponiveis is None:
            categorias_disponiveis = []
        
        return render_template(
            "painel_aluno/simular_categorias.html",
            aluno=aluno,
            categorias_disponiveis=categorias_disponiveis,
            peso=peso,
            data_nascimento=data_nascimento or aluno_data_nasc_str,
            sexo=sexo,
            idade_calculada=idade_calculada,
        )
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Erro em simular_categorias: {e}", exc_info=True)
        flash(f"Erro ao carregar página: {str(e)}", "danger")
        return redirect(url_for("painel_aluno.painel"))


def _ranking_frequencia_turmas_do_aluno(aluno):
    """Turmas do aluno com pódio de frequência (mês/ano)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        ids = set()
        if aluno.get("TurmaID"):
            ids.add(aluno["TurmaID"])
        cur.execute("SELECT TurmaID FROM aluno_turmas WHERE aluno_id = %s", (aluno["id"],))
        for r in cur.fetchall():
            if r.get("TurmaID"):
                ids.add(r["TurmaID"])
        if not ids:
            cur.close()
            conn.close()
            return []
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            f"SELECT TurmaID, Nome FROM turmas WHERE TurmaID IN ({ph}) ORDER BY Nome",
            tuple(ids),
        )
        turmas_info = cur.fetchall()
        from utils.ranking_frequencia import ranking_frequencia_por_turmas

        out = ranking_frequencia_por_turmas(cur, turmas_info)
        cur.close()
        conn.close()
        return out
    except Exception:
        return []


def _stats_painel_aluno(aluno):
    """Retorna estatísticas básicas para o dashboard do aluno."""
    stats = {"mensalidades_pendentes": 0, "presencas_mes": 0, "turmas_count": 0}
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        hoje = datetime.today()
        cur.execute(
            """SELECT COUNT(*) as c FROM mensalidade_aluno ma
               JOIN mensalidades m ON m.id = ma.mensalidade_id
               WHERE ma.aluno_id = %s AND (ma.status = 'pendente' OR ma.status IS NULL)
               AND ma.data_vencimento < %s""",
            (aluno["id"], hoje.strftime("%Y-%m-%d")),
        )
        stats["mensalidades_pendentes"] = cur.fetchone().get("c") or 0
        cur.execute(
            """SELECT COUNT(*) as c FROM presencas
               WHERE aluno_id = %s AND presente = 1
               AND MONTH(data_presenca) = %s AND YEAR(data_presenca) = %s""",
            (aluno["id"], hoje.month, hoje.year),
        )
        stats["presencas_mes"] = cur.fetchone().get("c") or 0
        cur.execute(
            """SELECT COUNT(DISTINCT TurmaID) as c FROM aluno_turmas WHERE aluno_id = %s""",
            (aluno["id"],),
        )
        r = cur.fetchone()
        if r and (r.get("c") or 0) > 0:
            stats["turmas_count"] = r.get("c") or 0
        else:
            cur.execute("SELECT 1 FROM alunos WHERE id = %s AND TurmaID IS NOT NULL", (aluno["id"],))
            stats["turmas_count"] = 1 if cur.fetchone() else 0
        cur.close()
        conn.close()
    except Exception:
        pass
    return stats


def _calcular_valor_com_juros_multas(ma, hoje=None):
    """Calcula valor ajustado com multa (2% flat ao atrasar) e juros (0,033%/dia) quando atrasado.
    Retorna (valor_total, valor_original, multa_val, juros_val). multa_val/juros_val são None quando não aplicável."""
    hoje = hoje or date.today()
    valor = float(ma.get("valor") or 0)
    if ma.get("status") == "pago" or not ma.get("aplicar_juros_multas") or ma.get("remover_juros"):
        return valor, None, None, None
    try:
        venc = ma.get("data_vencimento")
        if isinstance(venc, str):
            venc = datetime.strptime(venc[:10], "%Y-%m-%d").date()
        if venc >= hoje:
            return valor, None, None, None
    except Exception:
        return valor, None, None, None
    dias = (hoje - venc).days
    if dias <= 0:
        return valor, None, None, None
    # Multa: 2% flat ao atrasar (não por mês)
    pct_multa = float(ma.get("percentual_multa_mes") or 2) / 100
    multa = round(valor * pct_multa, 2)
    # Juros: 0,033% ao dia (contagem diária)
    pct_juros_dia = float(ma.get("percentual_juros_dia") or 0.033) / 100
    juros = round(valor * pct_juros_dia * dias, 2)
    total = round(valor + multa + juros, 2)
    return total, round(valor, 2), multa, juros


def _status_efetivo_painel(status, data_venc, status_pagamento=None):
    """Pendente_aprovacao -> aguardando_confirmacao. Pendente vencido -> atrasado."""
    if status_pagamento == "pendente_aprovacao":
        return "aguardando_confirmacao"
    if status_pagamento == "pago":
        return "pago"
    if status and status not in ("pendente",):
        return status
    try:
        venc = data_venc if isinstance(data_venc, date) else (date.fromisoformat(str(data_venc)[:10]) if data_venc else None)
        if venc and venc < date.today():
            return "atrasado"
    except Exception:
        pass
    return status or "pendente"


@bp_painel_aluno.route("/mensalidades")
@login_required
@_aluno_required
def minhas_mensalidades(aluno):
    from blueprints.financeiro.routes import _valor_com_desconto

    mes_arg = request.args.get("mes", type=int)
    mes = mes_arg if (mes_arg and 1 <= mes_arg <= 12) else None
    ano_arg = request.args.get("ano", type=int)
    ano = ano_arg if (ano_arg and 2000 <= ano_arg <= 2100) else date.today().year

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE mensalidade_aluno SET status = 'atrasado' WHERE aluno_id = %s AND status = 'pendente' AND data_vencimento < CURDATE()",
            (aluno["id"],),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    cur.close()
    cur = conn.cursor(dictionary=True)
    hoje = date.today()
    id_academia = aluno.get("id_academia")

    if mes:
        where_clause = "ma.aluno_id = %s AND MONTH(ma.data_vencimento) = %s AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'"
        params = (aluno["id"], mes, ano)
    else:
        where_clause = "ma.aluno_id = %s AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'"
        params = (aluno["id"], ano)
    try:
        cur.execute(f"""
            SELECT ma.id, ma.mensalidade_id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                   ma.status_pagamento, ma.comprovante_url, ma.observacoes,
                   ma.valor_original, ma.desconto_aplicado, ma.id_desconto,
                   COALESCE(ma.remover_juros, 0) AS remover_juros,
                   ma.asaas_tipo, ma.asaas_boleto_url, ma.asaas_pix_qrcode, ma.asaas_pix_copia_cola,
                   m.nome as plano_nome, m.id_academia,
                   COALESCE(m.aplicar_juros_multas, 0) AS aplicar_juros_multas,
                   COALESCE(m.percentual_multa_mes, 2) AS percentual_multa_mes,
                   COALESCE(m.percentual_juros_dia, 0.033) AS percentual_juros_dia
            FROM mensalidade_aluno ma
            JOIN mensalidades m ON m.id = ma.mensalidade_id
            WHERE {where_clause}
            ORDER BY ma.data_vencimento DESC
            LIMIT 200
        """, params)
        rows = cur.fetchall()
    except Exception:
        try:
            if mes:
                cur.execute("""
                    SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                           ma.observacoes, ma.status_pagamento, ma.comprovante_url,
                           m.nome as plano_nome, m.id_academia
                    FROM mensalidade_aluno ma
                    JOIN mensalidades m ON m.id = ma.mensalidade_id
                    WHERE ma.aluno_id = %s AND MONTH(ma.data_vencimento) = %s AND YEAR(ma.data_vencimento) = %s
                    ORDER BY ma.data_vencimento DESC
                    LIMIT 200
                """, (aluno["id"], mes, ano))
            else:
                cur.execute("""
                    SELECT ma.id, ma.data_vencimento, ma.data_pagamento, ma.valor, ma.valor_pago, ma.status,
                           ma.observacoes, ma.status_pagamento, ma.comprovante_url,
                           m.nome as plano_nome, m.id_academia
                    FROM mensalidade_aluno ma
                    JOIN mensalidades m ON m.id = ma.mensalidade_id
                    WHERE ma.aluno_id = %s AND YEAR(ma.data_vencimento) = %s
                    ORDER BY ma.data_vencimento DESC
                    LIMIT 200
                """, (aluno["id"], ano))
            rows = cur.fetchall()
            for r in rows:
                r.setdefault("remover_juros", 0)
                r.setdefault("aplicar_juros_multas", 0)
                r.setdefault("percentual_multa_mes", 2)
                r.setdefault("percentual_juros_dia", 0.033)
                r.setdefault("status_pagamento", None)
                r.setdefault("comprovante_url", None)
                r.setdefault("valor_original", None)
                r.setdefault("desconto_aplicado", 0)
                r.setdefault("id_desconto", None)
                r.setdefault("mensalidade_id", None)
                r.setdefault("asaas_tipo", None)
                r.setdefault("asaas_boleto_url", None)
                r.setdefault("asaas_pix_qrcode", None)
                r.setdefault("asaas_pix_copia_cola", None)
        except Exception:
            rows = []

    all_for_contagens = []
    try:
        if mes:
            cur.execute("""
                SELECT ma.id, ma.status, ma.status_pagamento, ma.data_vencimento
                FROM mensalidade_aluno ma
                WHERE ma.aluno_id = %s AND MONTH(ma.data_vencimento) = %s AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'
            """, (aluno["id"], mes, ano))
        else:
            cur.execute("""
                SELECT ma.id, ma.status, ma.status_pagamento, ma.data_vencimento
                FROM mensalidade_aluno ma
                WHERE ma.aluno_id = %s AND YEAR(ma.data_vencimento) = %s AND ma.status != 'cancelado'
            """, (aluno["id"], ano))
        all_for_contagens = cur.fetchall()
    except Exception:
        pass

    contagens = {"pago": 0, "pendente": 0, "atrasado": 0, "aguardando_confirmacao": 0}
    for r in all_for_contagens:
        se = _status_efetivo_painel(r.get("status"), r.get("data_vencimento"), r.get("status_pagamento"))
        contagens[se] = contagens.get(se, 0) + 1

    mensalidades = []
    for ma in rows:
        valor_display, valor_original, multa_val, juros_val = _calcular_valor_com_juros_multas(ma, hoje)
        ma["valor_display"] = valor_display
        ma["valor_original"] = valor_original
        ma["multa_val"] = multa_val
        ma["juros_val"] = juros_val
        ma["tem_juros"] = (multa_val or 0) + (juros_val or 0) > 0
        ma["status_efetivo"] = _status_efetivo_painel(ma.get("status"), ma.get("data_vencimento"), ma.get("status_pagamento"))
        ma["comentario_informado"] = ma.get("comentario_informado") or ma.get("observacoes")
        id_acad = ma.get("id_academia") or id_academia
        if id_acad:
            vi, vd, vf, desconto_nome = _valor_com_desconto(ma, aluno["id"], id_acad, hoje)
            ma["valor_integral"] = vi
            ma["valor_desconto"] = vd
            ma["valor_final"] = vf
            ma["desconto_nome"] = desconto_nome
            ma["tem_desconto"] = vd > 0
        else:
            ma["valor_integral"] = valor_display
            ma["valor_desconto"] = 0
            ma["valor_final"] = valor_display
            ma["tem_desconto"] = False
        mensalidades.append(ma)

    avulsas = []
    try:
        if mes:
            cur.execute("""
                SELECT id, descricao, valor, data_vencimento, data_pagamento, status,
                       asaas_tipo, asaas_boleto_url, asaas_pix_qrcode, asaas_pix_copia_cola
                FROM cobranca_avulsa
                WHERE aluno_id = %s AND status != 'cancelado'
                AND MONTH(data_vencimento) = %s AND YEAR(data_vencimento) = %s
                ORDER BY data_vencimento DESC
            """, (aluno["id"], mes, ano))
        else:
            cur.execute("""
                SELECT id, descricao, valor, data_vencimento, data_pagamento, status,
                       asaas_tipo, asaas_boleto_url, asaas_pix_qrcode, asaas_pix_copia_cola
                FROM cobranca_avulsa
                WHERE aluno_id = %s AND status != 'cancelado'
                AND YEAR(data_vencimento) = %s
                ORDER BY data_vencimento DESC
            """, (aluno["id"], ano))
        avulsas = cur.fetchall()
    except Exception:
        pass

    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/minhas_mensalidades.html",
        usuario=current_user,
        aluno=aluno,
        mensalidades=mensalidades,
        avulsas=avulsas,
        contagens=contagens,
        mes=mes,
        ano=ano,
        ano_atual=date.today().year,
    )


def _aluno_ou_professor_required(f):
    """Permite aluno (com aluno vinculado) ou professor."""
    from functools import wraps
    @wraps(f)
    def _view(*a, **kw):
        if not (current_user.has_role("aluno") or current_user.has_role("professor") or current_user.has_role("admin")):
            flash("Acesso restrito.", "danger")
            return redirect(url_for("painel.home"))
        aluno = _get_aluno() if current_user.has_role("aluno") else None
        if current_user.has_role("aluno") and not aluno and not current_user.has_role("admin"):
            flash("Nenhum aluno vinculado a este usuário.", "warning")
            return redirect(url_for("painel.home"))
        return f(*a, aluno=aluno, **kw)
    return _view


def _buscar_alunos_turma(cur, turma_id, id_academia_turma):
    """Retorna lista de alunos da turma (mesma turma e mesma academia)."""
    try:
        if id_academia_turma is not None:
            cur.execute("""
                SELECT a.id, a.nome, a.foto, g.faixa AS faixa_nome, g.graduacao AS graduacao_nome
                FROM alunos a
                LEFT JOIN graduacao g ON g.id = a.graduacao_id
                WHERE a.TurmaID = %s AND a.id_academia = %s
                ORDER BY a.nome
            """, (turma_id, id_academia_turma))
        else:
            cur.execute("""
                SELECT a.id, a.nome, a.foto, g.faixa AS faixa_nome, g.graduacao AS graduacao_nome
                FROM alunos a
                LEFT JOIN graduacao g ON g.id = a.graduacao_id
                WHERE a.TurmaID = %s
                ORDER BY a.nome
            """, (turma_id,))
        return cur.fetchall()
    except Exception:
        return []


@bp_painel_aluno.route("/turma")
@login_required
@_aluno_ou_professor_required
def minha_turma(aluno=None):
    turma_selecionada_id = request.args.get("turma_id", type=int)
    turmas_com_alunos = []  # [(turma, alunos), ...]

    if aluno:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        turmas_list = _turmas_do_aluno(cur, aluno["id"], aluno.get("TurmaID"))
        turma_ids = [t["TurmaID"] for t in turmas_list]
        cur.close()
        conn.close()
    elif current_user.has_role("professor") or current_user.has_role("admin"):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        turma_ids = []
        try:
            cur.execute("SELECT id FROM professores WHERE email = %s LIMIT 1", (current_user.email,))
            prof = cur.fetchone()
            if prof:
                cur.execute("SELECT TurmaID FROM turma_professor WHERE professor_id = %s ORDER BY TurmaID", (prof["id"],))
                turma_ids = [r["TurmaID"] for r in cur.fetchall()]
        except Exception:
            pass
        cur.close()
        conn.close()
    else:
        turma_ids = []

    if turma_ids:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        for tid in turma_ids:
            cur.execute("SELECT * FROM turmas WHERE TurmaID = %s", (tid,))
            t = cur.fetchone()
            if t:
                try:
                    cur.execute(
                        """SELECT p.nome FROM turma_professor tp
                           JOIN professores p ON p.id = tp.professor_id
                           WHERE tp.TurmaID = %s AND tp.tipo = 'responsavel' LIMIT 1""",
                        (tid,),
                    )
                    row = cur.fetchone()
                    t["Professor"] = row["nome"] if row and row.get("nome") else t.get("Professor") or "—"
                except Exception:
                    t["Professor"] = t.get("Professor") or "—"
                id_acad = t.get("id_academia")
                alns = _buscar_alunos_turma(cur, tid, id_acad)
                turmas_com_alunos.append((t, alns))
        cur.close()
        conn.close()

    if turma_selecionada_id and len(turmas_com_alunos) > 1:
        turmas_com_alunos.sort(key=lambda x: (0 if x[0]["TurmaID"] == turma_selecionada_id else 1, x[0]["Nome"] or ""))
    else:
        turmas_com_alunos.sort(key=lambda x: (x[0]["Nome"] or "").lower())

    return render_template(
        "painel_aluno/minha_turma.html",
        usuario=current_user,
        aluno=aluno,
        turmas_com_alunos=turmas_com_alunos,
        turma_selecionada_id=turma_selecionada_id,
    )


def _turmas_do_aluno(cur, aluno_id, aluno_turma_id):
    """Retorna lista de turmas do aluno: de aluno_turmas ou fallback para TurmaID."""
    turmas_list = []
    try:
        cur.execute("""
            SELECT t.TurmaID, t.Nome
            FROM aluno_turmas at
            JOIN turmas t ON t.TurmaID = at.TurmaID
            WHERE at.aluno_id = %s
            ORDER BY t.Nome
        """, (aluno_id,))
        turmas_list = cur.fetchall()
    except Exception:
        pass
    if not turmas_list and aluno_turma_id:
        try:
            cur.execute("SELECT TurmaID, Nome FROM turmas WHERE TurmaID = %s", (aluno_turma_id,))
            row = cur.fetchone()
            if row:
                turmas_list = [row]
        except Exception:
            pass
    return turmas_list


def _calcular_meses_filtro(ano, mes_de, mes_ate, atalho):
    """Calcula lista de meses. Retorna [] para ano inteiro."""
    hoje = datetime.today()
    a = ano or hoje.year
    if atalho == "este_mes" and a == hoje.year:
        return [hoje.month]
    if atalho == "ultimos_3" and a == hoje.year:
        m = hoje.month
        return list(range(max(1, m - 2), m + 1))
    if atalho == "trimestre" and a == hoje.year:
        m = hoje.month
        inicio = ((m - 1) // 3) * 3 + 1
        return list(range(inicio, min(inicio + 3, 13)))
    if atalho == "ano" or (not mes_de and not mes_ate and not atalho):
        return []
    if mes_de and mes_ate:
        de, ate = int(mes_de), int(mes_ate)
        if 1 <= de <= 12 and 1 <= ate <= 12:
            return list(range(min(de, ate), max(de, ate) + 1))
    if mes_de:
        m = int(mes_de)
        return [m] if 1 <= m <= 12 else []
    return []


@bp_painel_aluno.route("/presencas")
@login_required
@_aluno_required
def minhas_presencas(aluno):
    ano = request.args.get("ano", datetime.today().year, type=int)
    mes_de = request.args.get("mes_de", type=int)
    mes_ate = request.args.get("mes_ate", type=int)
    atalho = request.args.get("atalho", "").strip()
    meses_legado = [int(x) for x in request.args.getlist("mes") if str(x).isdigit() and 1 <= int(x) <= 12]
    turma_filtro_id = request.args.get("turma_id", type=int)

    meses_sel = _calcular_meses_filtro(ano, mes_de, mes_ate, atalho) if atalho or mes_de or mes_ate else meses_legado

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        _garantir_tabela_presencas_observacao_aluno(cur)
        conn.commit()
    except Exception:
        conn.rollback()

    turmas_do_aluno = _turmas_do_aluno(cur, aluno["id"], aluno.get("TurmaID"))

    if turmas_do_aluno and not turma_filtro_id:
        turma_filtro_id = turmas_do_aluno[0]["TurmaID"]

    where_extra = ""
    params_extra = []
    if turma_filtro_id:
        where_extra = " AND p.turma_id = %s"
        params_extra = [turma_filtro_id]

    try:
        join_aula = """
            LEFT JOIN registros_aula_presenca r
              ON r.turma_id = p.turma_id
             AND r.data_aula = p.data_presenca
             AND r.horario_aula = COALESCE(p.horario_aula, '00:00:00')
            LEFT JOIN presencas_observacao_aluno po
              ON po.aluno_id = p.aluno_id
             AND po.turma_id = p.turma_id
             AND po.data_aula = p.data_presenca
             AND po.horario_aula = COALESCE(p.horario_aula, '00:00:00')
        """
        sel_aula = """
                , p.horario_aula,
                 r.observacao AS aula_observacao,
                 r.plano_aula_texto AS aula_plano_texto,
                 r.plano_aula_arquivo AS aula_plano_arquivo,
                 r.plano_aula_arquivo_original AS aula_plano_arquivo_original,
                 po.observacao AS mensagem_professor_para_aluno
        """
        if meses_sel:
            placeholders = ",".join(["%s"] * len(meses_sel))
            cur.execute(
                """
                SELECT p.data_presenca, p.presente
                """
                + sel_aula
                + """
                FROM presencas p
                """
                + join_aula
                + """
                WHERE p.aluno_id = %s AND YEAR(p.data_presenca) = %s
                  AND MONTH(p.data_presenca) IN ("""
                + placeholders
                + ")"
                + where_extra
                + """
                ORDER BY p.data_presenca, p.horario_aula
            """,
                [aluno["id"], ano] + meses_sel + params_extra,
            )
        else:
            cur.execute(
                """
                SELECT p.data_presenca, p.presente
                """
                + sel_aula
                + """
                FROM presencas p
                """
                + join_aula
                + """
                WHERE p.aluno_id = %s AND YEAR(p.data_presenca) = %s
                """
                + where_extra
                + """
                ORDER BY p.data_presenca, p.horario_aula
            """,
                [aluno["id"], ano] + params_extra,
            )
        presencas = cur.fetchall()
        for pr in presencas:
            hv = pr.get("horario_aula")
            if hv is None:
                pr["horario_exibir"] = None
            elif hasattr(hv, "total_seconds"):
                sec = int(hv.total_seconds()) % 86400
                hs = f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}"
                pr["horario_exibir"] = None if hs == "00:00" else hs
            else:
                hs = hv.strftime("%H:%M") if hasattr(hv, "strftime") else str(hv)[:8]
                if len(hs) >= 5:
                    hs = hs[:5]
                pr["horario_exibir"] = None if hs in ("00:00", "00:00:00") else hs
    except Exception:
        presencas = []
    cur.close()
    conn.close()

    total = len(presencas)
    presentes = sum(1 for p in presencas if p.get("presente") == 1)
    return render_template(
        "painel_aluno/minhas_presencas.html",
        usuario=current_user,
        aluno=aluno,
        presencas=presencas,
        ano=ano,
        ano_atual=datetime.today().year,
        meses_sel=meses_sel,
        mes_de=mes_de,
        mes_ate=mes_ate,
        atalho=atalho,
        total=total,
        presentes=presentes,
        turmas_do_aluno=turmas_do_aluno,
        turma_filtro_id=turma_filtro_id,
    )


# ======================================================
# ASSOCIAÇÃO — Academias vinculadas à associação do aluno
# ======================================================

@bp_painel_aluno.route("/associacao")
@login_required
@_aluno_required
def associacao(aluno):
    """Exibe as academias da associação à qual o aluno pertence."""
    from utils.contexto_logo import buscar_logo_url

    academias = []
    associacao_nome = None
    associacao_endereco = None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_academia_aluno = aluno.get("id_academia")
        if not id_academia_aluno:
            cur.close()
            conn.close()
            return render_template(
                "painel_aluno/associacao.html",
                academias=[],
                associacao_nome=None,
                associacao_endereco=None,
                aluno=aluno,
            )

        cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_academia_aluno,))
        row = cur.fetchone()
        id_associacao = row.get("id_associacao") if row else None

        if not id_associacao:
            cur.close()
            conn.close()
            return render_template(
                "painel_aluno/associacao.html",
                academias=[],
                associacao_nome=None,
                associacao_endereco=None,
                aluno=aluno,
            )

        cur.execute("""
            SELECT nome, cep, rua, numero, complemento, bairro, cidade, uf
            FROM associacoes WHERE id = %s
        """, (id_associacao,))
        assoc = cur.fetchone()
        associacao_nome = assoc.get("nome") if assoc else None
        if assoc:
            partes_endereco = []
            if assoc.get("rua"):
                partes_endereco.append(assoc["rua"])
                if assoc.get("numero"):
                    partes_endereco.append(f"nº {assoc['numero']}")
            if assoc.get("bairro"):
                partes_endereco.append(assoc["bairro"])
            if assoc.get("cidade"):
                partes_endereco.append(assoc["cidade"])
            if assoc.get("uf"):
                partes_endereco.append(assoc["uf"])
            if assoc.get("cep"):
                partes_endereco.append(f"CEP: {assoc['cep']}")
            associacao_endereco = ", ".join(partes_endereco) if partes_endereco else None

        cur.execute("""
            SELECT a.id, a.nome, a.cidade, a.uf, a.email, a.telefone,
                   a.cep, a.rua, a.numero, a.complemento, a.bairro
            FROM academias a
            WHERE a.id_associacao = %s AND a.id != %s
            ORDER BY a.nome
        """, (id_associacao, id_academia_aluno))
        academias = cur.fetchall()
        
        # Buscar gestor/professor responsável de cada academia
        for acad in academias:
            try:
                # Primeiro tentar buscar por gestor_academia
                cur.execute("""
                    SELECT u.nome, u.email
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    INNER JOIN roles_usuario ru ON ru.usuario_id = u.id
                    INNER JOIN roles r ON r.id = ru.role_id
                    WHERE ua.academia_id = %s 
                      AND (
                        r.chave = 'gestor_academia'
                        OR r.nome = 'Gestor Academia'
                        OR LOWER(REPLACE(r.nome, ' ', '_')) = 'gestor_academia'
                      )
                      AND COALESCE(u.ativo, 1) = 1
                    LIMIT 1
                """, (acad["id"],))
                gestor = cur.fetchone()
                
                # Se não encontrou gestor, buscar professor
                if not gestor:
                    cur.execute("""
                        SELECT u.nome, u.email
                        FROM usuarios u
                        INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                        INNER JOIN roles_usuario ru ON ru.usuario_id = u.id
                        INNER JOIN roles r ON r.id = ru.role_id
                        WHERE ua.academia_id = %s 
                          AND (
                            r.chave = 'professor'
                            OR r.nome = 'Professor'
                            OR LOWER(REPLACE(r.nome, ' ', '_')) = 'professor'
                          )
                          AND COALESCE(u.ativo, 1) = 1
                        LIMIT 1
                    """, (acad["id"],))
                    gestor = cur.fetchone()
                
                # Se ainda não encontrou, tentar buscar da tabela professores vinculada à academia
                if not gestor:
                    cur.execute("""
                        SELECT p.nome, p.email
                        FROM professores p
                        WHERE p.id_academia = %s 
                          AND COALESCE(p.ativo, 1) = 1
                        ORDER BY p.id DESC
                        LIMIT 1
                    """, (acad["id"],))
                    prof_row = cur.fetchone()
                    if prof_row:
                        gestor = {"nome": prof_row.get("nome"), "email": prof_row.get("email")}
            except Exception as e:
                current_app.logger.warning(f"Erro ao buscar gestor da academia {acad['id']}: {e}", exc_info=True)
                gestor = None
            acad["gestor_nome"] = gestor.get("nome") if gestor else None
            acad["gestor_email"] = gestor.get("email") if gestor else None
            
            # Buscar turmas da academia com dias e horários
            try:
                cur.execute("""
                    SELECT t.TurmaID, t.Nome, t.hora_inicio, t.hora_fim, t.dias_semana, 
                           t.IdadeMin, t.IdadeMax, t.Classificacao
                    FROM turmas t
                    WHERE t.id_academia = %s
                    ORDER BY t.Nome
                """, (acad["id"],))
                turmas = cur.fetchall()
                # Formatar horários e dias
                turmas_formatadas = []
                dias_map = {'0': 'Dom', '1': 'Seg', '2': 'Ter', '3': 'Qua', '4': 'Qui', '5': 'Sex', '6': 'Sáb'}
                
                for turma in turmas:
                    hora_inicio = turma.get("hora_inicio")
                    hora_fim = turma.get("hora_fim")
                    dias_semana = turma.get("dias_semana")
                    
                    horario_str = ""
                    if hora_inicio:
                        if hasattr(hora_inicio, "strftime"):
                            horario_str = hora_inicio.strftime("%H:%M")
                        else:
                            horario_str = str(hora_inicio)[:5]
                        if hora_fim:
                            if hasattr(hora_fim, "strftime"):
                                horario_str += f" às {hora_fim.strftime('%H:%M')}"
                            else:
                                horario_str += f" às {str(hora_fim)[:5]}"
                    
                    # Converter dias da semana de números para nomes
                    dias_formatados = ""
                    if dias_semana:
                        dias_list = [d.strip() for d in str(dias_semana).split(',') if d.strip()]
                        dias_nomes = [dias_map.get(d, d) for d in dias_list]
                        dias_formatados = ", ".join(dias_nomes)
                    
                    # Formatar faixa etária
                    idade_min = turma.get("IdadeMin")
                    idade_max = turma.get("IdadeMax")
                    # Converter para int se não for None, permitindo 0
                    if idade_min is not None:
                        try:
                            idade_min = int(idade_min)
                        except (ValueError, TypeError):
                            idade_min = None
                    if idade_max is not None:
                        try:
                            idade_max = int(idade_max)
                        except (ValueError, TypeError):
                            idade_max = None
                    
                    faixa_etaria = ""
                    if idade_min is not None and idade_max is not None:
                        faixa_etaria = f"{idade_min} a {idade_max} anos"
                    elif idade_min is not None:
                        faixa_etaria = f"A partir de {idade_min} anos"
                    elif idade_max is not None:
                        faixa_etaria = f"Até {idade_max} anos"
                    
                    classificacao = turma.get("Classificacao")
                    classificacao = classificacao.strip() if classificacao and isinstance(classificacao, str) else (classificacao if classificacao else None)
                    
                    turma_info = {
                        "nome": turma.get("Nome"),
                        "horario": horario_str,
                        "dias": dias_formatados or dias_semana or "",
                        "idade_min": idade_min,
                        "idade_max": idade_max,
                        "faixa_etaria": faixa_etaria,
                        "classificacao": classificacao
                    }
                    turmas_formatadas.append(turma_info)
                acad["turmas"] = turmas_formatadas
            except Exception as e:
                try:
                    current_app.logger.warning(f"Erro ao buscar turmas da academia {acad['id']}: {e}")
                except:
                    pass
                acad["turmas"] = []
            
            # Formatar endereço da academia
            partes_endereco = []
            if acad.get("rua"):
                partes_endereco.append(acad["rua"])
                if acad.get("numero"):
                    partes_endereco.append(f"nº {acad['numero']}")
            if acad.get("bairro"):
                partes_endereco.append(acad["bairro"])
            # Sempre incluir cidade e UF se disponíveis
            cidade_uf = []
            if acad.get("cidade"):
                cidade_uf.append(acad["cidade"])
            if acad.get("uf"):
                cidade_uf.append(acad["uf"])
            if cidade_uf:
                partes_endereco.append(" - ".join(cidade_uf))
            if acad.get("cep"):
                partes_endereco.append(f"CEP: {acad['cep']}")
            acad["endereco_completo"] = ", ".join(partes_endereco) if partes_endereco else None
        
        # Buscar solicitações de visita para cada academia
        solicitacoes_por_academia = {}
        try:
            aluno_id = aluno.get("id")
            if aluno_id:
                cur.execute("""
                    SELECT s.*, 
                           ac_dest.nome AS academia_destino_nome,
                           ac_orig.nome AS academia_origem_nome,
                           t.Nome AS turma_nome,
                           t.hora_inicio, t.hora_fim, t.dias_semana
                    FROM solicitacoes_aprovacao s
                    INNER JOIN academias ac_dest ON ac_dest.id = s.academia_destino_id
                    INNER JOIN academias ac_orig ON ac_orig.id = s.academia_origem_id
                    LEFT JOIN turmas t ON t.TurmaID = s.turma_id
                    WHERE s.aluno_id = %s AND s.tipo = 'visita'
                    ORDER BY s.criado_em DESC
                """, (aluno_id,))
                solicitacoes = cur.fetchall()
            else:
                solicitacoes = []
            
            for sol in solicitacoes:
                acad_id = sol["academia_destino_id"]
                if acad_id not in solicitacoes_por_academia:
                    solicitacoes_por_academia[acad_id] = []
                # Formatar hora
                if sol.get("hora_inicio"):
                    hi = sol["hora_inicio"]
                    sol["hora_inicio_str"] = hi.strftime("%H:%M") if hasattr(hi, "strftime") else str(hi)[:5]
                if sol.get("hora_fim"):
                    hf = sol["hora_fim"]
                    sol["hora_fim_str"] = hf.strftime("%H:%M") if hasattr(hf, "strftime") else str(hf)[:5]
                # Formatar data
                if sol.get("data_visita"):
                    dv = sol["data_visita"]
                    sol["data_visita_formatada"] = dv.strftime("%d/%m/%Y") if hasattr(dv, "strftime") else str(dv)
                solicitacoes_por_academia[acad_id].append(sol)
        except Exception as e:
            try:
                current_app.logger.warning(f"Erro ao buscar solicitações: {e}")
            except:
                pass
        
        for acad in academias:
            try:
                acad["logo_url"] = buscar_logo_url("academia", acad["id"])
            except:
                acad["logo_url"] = None
            # Garantir que solicitacoes sempre seja uma lista
            acad["solicitacoes"] = solicitacoes_por_academia.get(acad["id"], []) or []
    except Exception as e:
        try:
            import traceback
            current_app.logger.error(f"Erro na função associacao: {e}", exc_info=True)
            current_app.logger.error(traceback.format_exc())
        except:
            import traceback
            print(f"Erro na função associacao: {e}")
            print(traceback.format_exc())
        # Garantir que variáveis estão definidas mesmo em caso de erro
        if associacao_endereco is None:
            associacao_endereco = None
        if associacao_nome is None:
            associacao_nome = None
        if not isinstance(academias, list):
            academias = []
        # Garantir que cada academia tem solicitacoes e logo_url
        if isinstance(academias, list):
            for acad in academias:
                if not isinstance(acad, dict):
                    continue
                if "solicitacoes" not in acad:
                    acad["solicitacoes"] = []
                if "logo_url" not in acad:
                    acad["logo_url"] = None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return render_template(
        "painel_aluno/associacao.html",
        academias=academias,
        associacao_nome=associacao_nome,
        associacao_endereco=associacao_endereco,
        aluno=aluno,
    )


@bp_painel_aluno.route("/associacao/solicitacoes/<int:academia_destino_id>")
@login_required
@_aluno_required
def solicitacoes_academia(aluno, academia_destino_id):
    """Exibe todas as solicitações de visita para uma academia específica."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar dados da academia destino
        cur.execute("""
            SELECT a.*, ass.nome AS associacao_nome, ass.cep AS ass_cep, ass.rua AS ass_rua,
                   ass.numero AS ass_numero, ass.complemento AS ass_complemento,
                   ass.bairro AS ass_bairro, ass.cidade AS ass_cidade, ass.uf AS ass_uf
            FROM academias a
            INNER JOIN associacoes ass ON ass.id = a.id_associacao
            WHERE a.id = %s
        """, (academia_destino_id,))
        academia = cur.fetchone()
        
        if not academia:
            flash("Academia não encontrada.", "danger")
            return redirect(url_for("painel_aluno.associacao"))
        
        # Buscar gestor/professor responsável da academia destino
        try:
            cur.execute("""
                SELECT u.nome, u.email
                FROM usuarios u
                INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                INNER JOIN roles_usuario ru ON ru.usuario_id = u.id
                INNER JOIN roles r ON r.id = ru.role_id
                WHERE ua.academia_id = %s 
                  AND (
                    r.chave IN ('gestor_academia', 'professor')
                    OR r.nome IN ('Gestor Academia', 'Professor')
                  )
                  AND u.ativo = 1
                ORDER BY CASE 
                    WHEN r.chave = 'gestor_academia' OR r.nome = 'Gestor Academia' THEN 1 
                    WHEN r.chave = 'professor' OR r.nome = 'Professor' THEN 2 
                    ELSE 3 
                END
                LIMIT 1
            """, (academia_destino_id,))
            gestor_destino = cur.fetchone()
        except Exception as e:
            current_app.logger.warning(f"Erro ao buscar gestor destino: {e}")
            gestor_destino = None
        
        # Buscar gestor/professor responsável da academia origem
        id_academia_aluno = aluno.get("id_academia")
        gestor_origem = None
        if id_academia_aluno:
            try:
                cur.execute("""
                    SELECT u.nome, u.email
                    FROM usuarios u
                    INNER JOIN usuarios_academias ua ON ua.usuario_id = u.id
                    INNER JOIN roles_usuario ru ON ru.usuario_id = u.id
                    INNER JOIN roles r ON r.id = ru.role_id
                    WHERE ua.academia_id = %s 
                      AND (
                        r.chave IN ('gestor_academia', 'professor')
                        OR r.nome IN ('Gestor Academia', 'Professor')
                      )
                      AND u.ativo = 1
                    ORDER BY CASE 
                        WHEN r.chave = 'gestor_academia' OR r.nome = 'Gestor Academia' THEN 1 
                        WHEN r.chave = 'professor' OR r.nome = 'Professor' THEN 2 
                        ELSE 3 
                    END
                    LIMIT 1
                """, (id_academia_aluno,))
                gestor_origem = cur.fetchone()
            except Exception as e:
                current_app.logger.warning(f"Erro ao buscar gestor origem: {e}")
                gestor_origem = None
        
        # Buscar todas as solicitações para esta academia
        cur.execute("""
            SELECT s.*, 
                   ac_dest.nome AS academia_destino_nome,
                   ac_orig.nome AS academia_origem_nome,
                   t.Nome AS turma_nome,
                   t.hora_inicio, t.hora_fim, t.dias_semana
            FROM solicitacoes_aprovacao s
            INNER JOIN academias ac_dest ON ac_dest.id = s.academia_destino_id
            INNER JOIN academias ac_orig ON ac_orig.id = s.academia_origem_id
            LEFT JOIN turmas t ON t.TurmaID = s.turma_id
            WHERE s.aluno_id = %s AND s.academia_destino_id = %s AND s.tipo = 'visita'
            ORDER BY s.criado_em DESC
        """, (aluno["id"], academia_destino_id))
        solicitacoes = cur.fetchall()
        
        # Formatar dados das solicitações e verificar presença/falta
        aluno_id = aluno.get("id")
        for sol in solicitacoes:
            if sol.get("hora_inicio"):
                hi = sol["hora_inicio"]
                sol["hora_inicio_str"] = hi.strftime("%H:%M") if hasattr(hi, "strftime") else str(hi)[:5]
            if sol.get("hora_fim"):
                hf = sol["hora_fim"]
                sol["hora_fim_str"] = hf.strftime("%H:%M") if hasattr(hf, "strftime") else str(hf)[:5]
            if sol.get("data_visita"):
                dv = sol["data_visita"]
                sol["data_visita_formatada"] = dv.strftime("%d/%m/%Y") if hasattr(dv, "strftime") else str(dv)
            
            # Verificar presença/falta na chamada para esta data
            sol["status_presenca"] = None  # None = não registrado, True = presente, False = faltou
            if sol.get("data_visita") and aluno_id and sol.get("status") == "aprovado_destino":
                try:
                    from datetime import date as date_class
                    data_visita = sol["data_visita"]
                    if hasattr(data_visita, "date"):
                        data_visita_date = data_visita.date()
                    elif isinstance(data_visita, date_class):
                        data_visita_date = data_visita
                    elif isinstance(data_visita, str):
                        from datetime import datetime as dt
                        data_visita_date = dt.strptime(data_visita[:10], "%Y-%m-%d").date()
                    else:
                        data_visita_date = None
                    
                    # Só verificar presença se a data já passou
                    hoje = date_class.today()
                    if data_visita_date and data_visita_date <= hoje:
                        # Buscar presença na turma da visita
                        turma_id_visita = sol.get("turma_id")
                        if turma_id_visita:
                            cur.execute("""
                                SELECT presente 
                                FROM presencas 
                                WHERE aluno_id = %s 
                                  AND data_presenca = %s 
                                  AND turma_id = %s
                                LIMIT 1
                            """, (aluno_id, data_visita_date, turma_id_visita))
                            presenca_row = cur.fetchone()
                            if presenca_row is not None:
                                sol["status_presenca"] = bool(presenca_row.get("presente"))
                except Exception as e:
                    try:
                        current_app.logger.warning(f"Erro ao verificar presença para solicitação {sol.get('id')}: {e}")
                    except:
                        pass
                    sol["status_presenca"] = None
        
        # Formatar endereço da academia destino
        partes_endereco = []
        if academia.get("rua"):
            partes_endereco.append(academia["rua"])
            if academia.get("numero"):
                partes_endereco.append(f"nº {academia['numero']}")
        if academia.get("bairro"):
            partes_endereco.append(academia["bairro"])
        # Sempre incluir cidade e UF se disponíveis
        cidade_uf = []
        if academia.get("cidade"):
            cidade_uf.append(academia["cidade"])
        if academia.get("uf"):
            cidade_uf.append(academia["uf"])
        if cidade_uf:
            partes_endereco.append(" - ".join(cidade_uf))
        if academia.get("cep"):
            partes_endereco.append(f"CEP: {academia['cep']}")
        academia["endereco_completo"] = ", ".join(partes_endereco) if partes_endereco else None
        
        # Formatar endereço da associação
        partes_endereco_assoc = []
        if academia.get("ass_rua"):
            partes_endereco_assoc.append(academia["ass_rua"])
            if academia.get("ass_numero"):
                partes_endereco_assoc.append(f"nº {academia['ass_numero']}")
        if academia.get("ass_bairro"):
            partes_endereco_assoc.append(academia["ass_bairro"])
        cidade_uf_assoc = []
        if academia.get("ass_cidade"):
            cidade_uf_assoc.append(academia["ass_cidade"])
        if academia.get("ass_uf"):
            cidade_uf_assoc.append(academia["ass_uf"])
        if cidade_uf_assoc:
            partes_endereco_assoc.append(" - ".join(cidade_uf_assoc))
        if academia.get("ass_cep"):
            partes_endereco_assoc.append(f"CEP: {academia['ass_cep']}")
        associacao_endereco = ", ".join(partes_endereco_assoc) if partes_endereco_assoc else None
        
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar solicitações: {e}", exc_info=True)
        flash("Erro ao carregar solicitações.", "danger")
        if cur:
            cur.close()
        if conn:
            conn.close()
        return redirect(url_for("painel_aluno.associacao"))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    
    return render_template(
        "painel_aluno/solicitacoes_academia.html",
        academia=academia,
        associacao_endereco=associacao_endereco,
        gestor_destino=gestor_destino,
        gestor_origem=gestor_origem,
        solicitacoes=solicitacoes,
        aluno=aluno,
    )


@bp_painel_aluno.route("/associacao/solicitar-visita/<int:academia_destino_id>", methods=["GET", "POST"])
@login_required
@_aluno_required
def solicitar_visita(aluno, academia_destino_id):
    """Formulário para escolher turma e data, e cria solicitação de visita."""
    id_academia_aluno = aluno.get("id_academia")
    if not id_academia_aluno:
        flash("Sua academia não está definida.", "danger")
        return redirect(url_for("painel_aluno.associacao"))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (id_academia_aluno,))
    row = cur.fetchone()
    id_associacao = row.get("id_associacao") if row else None
    if not id_associacao:
        cur.close()
        conn.close()
        flash("Sua academia não está vinculada a uma associação.", "danger")
        return redirect(url_for("painel_aluno.associacao"))
    cur.execute(
        "SELECT id, nome FROM academias WHERE id = %s AND id_associacao = %s",
        (academia_destino_id, id_associacao),
    )
    academia_destino = cur.fetchone()
    if not academia_destino:
        cur.close()
        conn.close()
        flash("Academia não encontrada ou não pertence à mesma associação.", "danger")
        return redirect(url_for("painel_aluno.associacao"))
    # Não bloqueia mais - permite múltiplas solicitações para datas diferentes
    try:
        cur.execute(
            "SELECT TurmaID, Nome, dias_semana, hora_inicio, hora_fim FROM turmas WHERE id_academia = %s ORDER BY Nome",
            (academia_destino_id,),
        )
    except Exception:
        cur.execute(
            "SELECT TurmaID, Nome FROM turmas WHERE id_academia = %s ORDER BY Nome",
            (academia_destino_id,),
        )
    turmas = cur.fetchall()
    for t in turmas:
        hi = t.get("hora_inicio")
        hf = t.get("hora_fim")
        t["hora_inicio_str"] = hi.strftime("%H:%M") if hi and hasattr(hi, "strftime") else (str(hi)[:5] if hi else "")
        t["hora_fim_str"] = hf.strftime("%H:%M") if hf and hasattr(hf, "strftime") else (str(hf)[:5] if hf else "")
        dias_nomes = {'0':'Dom','1':'Seg','2':'Ter','3':'Qua','4':'Qui','5':'Sex','6':'Sáb'}
        ds = (t.get("dias_semana") or "").strip()
        t["dias_display"] = "/".join(dias_nomes.get(d.strip(),'') for d in ds.split(',') if d.strip()) if ds else ""

    if request.method == "POST":
        turma_id = request.form.get("turma_id", type=int)
        datas_visita_str = request.form.get("datas_visita", "").strip()
        
        if not turma_id or not datas_visita_str:
            flash("Selecione a turma e pelo menos uma data da visita.", "danger")
            cur.close()
            conn.close()
            return render_template(
                "painel_aluno/solicitar_visita_form.html",
                academia_destino=academia_destino,
                turmas=turmas,
                aluno=aluno,
                min_data=date.today().strftime("%Y-%m-%d"),
            )
        
        # Processar múltiplas datas (separadas por vírgula)
        from datetime import datetime
        datas_visita_list = []
        for data_str in datas_visita_str.split(","):
            data_str = data_str.strip()
            if data_str:
                try:
                    data_visita_dt = datetime.strptime(data_str, "%Y-%m-%d").date()
                    datas_visita_list.append(data_visita_dt)
                except (ValueError, TypeError):
                    continue
        
        if not datas_visita_list:
            flash("Nenhuma data válida selecionada.", "danger")
            cur.close()
            conn.close()
            return render_template(
                "painel_aluno/solicitar_visita_form.html",
                academia_destino=academia_destino,
                turmas=turmas,
                aluno=aluno,
                min_data=date.today().strftime("%Y-%m-%d"),
            )
        
        cur.execute(
            """SELECT TurmaID, dias_semana FROM turmas WHERE TurmaID = %s AND id_academia = %s""",
            (turma_id, academia_destino_id),
        )
        row_turma = cur.fetchone()
        if not row_turma:
            cur.close()
            conn.close()
            flash("Turma inválida.", "danger")
            return redirect(url_for("painel_aluno.associacao"))
        
        dias_semana = (row_turma.get("dias_semana") or "").strip()
        dias_list = [d.strip() for d in dias_semana.split(",") if d.strip()] if dias_semana else []
        
        # Validar cada data
        datas_validas = []
        datas_invalidas = []
        for data_visita_dt in datas_visita_list:
            if dias_semana:
                wd = data_visita_dt.weekday()
                dia_num = "0" if wd == 6 else str(wd + 1)
                if dia_num not in dias_list:
                    datas_invalidas.append(data_visita_dt.strftime("%d/%m/%Y"))
                    continue
            
            # Verificar se já existe solicitação para esta data específica
            cur.execute(
                """SELECT id FROM solicitacoes_aprovacao
                   WHERE aluno_id = %s AND academia_destino_id = %s AND tipo = 'visita'
                     AND data_visita = %s
                     AND status IN ('pendente_origem', 'pendente_destino', 'aprovado_destino')""",
                (aluno["id"], academia_destino_id, data_visita_dt),
            )
            if cur.fetchone():
                datas_invalidas.append(f"{data_visita_dt.strftime('%d/%m/%Y')} (já existe solicitação)")
                continue
            
            datas_validas.append(data_visita_dt)
        
        if datas_invalidas:
            flash(f"Algumas datas não puderam ser processadas: {', '.join(datas_invalidas)}", "warning")
        
        if not datas_validas:
            flash("Nenhuma data válida para criar solicitação.", "danger")
            cur.close()
            conn.close()
            return render_template(
                "painel_aluno/solicitar_visita_form.html",
                academia_destino=academia_destino,
                turmas=turmas,
                aluno=aluno,
                min_data=date.today().strftime("%Y-%m-%d"),
            )
        
        # Criar uma solicitação para cada data válida
        criadas = 0
        try:
            for data_visita_dt in datas_validas:
                cur.execute(
                    """INSERT INTO solicitacoes_aprovacao (tipo, aluno_id, academia_origem_id, academia_destino_id, status, turma_id, data_visita)
                       VALUES ('visita', %s, %s, %s, 'pendente_origem', %s, %s)""",
                    (aluno["id"], id_academia_aluno, academia_destino_id, turma_id, data_visita_dt),
                )
                criadas += 1
            conn.commit()
            if criadas == 1:
                flash("Solicitação enviada. Aguarde aprovação da sua academia e da academia de destino.", "success")
            else:
                flash(f"{criadas} solicitações enviadas. Aguarde aprovação da sua academia e da academia de destino.", "success")
        except Exception as e:
            conn.rollback()
            current_app.logger.error(f"Erro ao criar solicitações: {e}", exc_info=True)
            flash(f"Erro ao enviar solicitação: {e}", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.associacao"))

    cur.close()
    conn.close()
    return render_template(
        "painel_aluno/solicitar_visita_form.html",
        academia_destino=academia_destino,
        turmas=turmas,
        aluno=aluno,
        min_data=date.today().strftime("%Y-%m-%d"),
    )


# ======================================================
# MEU CURRÍCULO — Dados do atleta (layout CV / PDF)
# ======================================================

@bp_painel_aluno.route("/curriculo", methods=["GET"])
@login_required
def curriculo():
    """Página Meu currículo: dados do cadastro do atleta."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso restrito aos alunos.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT a.*, t.Nome AS turma_nome, ac.nome AS academia_nome
        FROM alunos a
        LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
        LEFT JOIN academias ac ON ac.id = a.id_academia
        WHERE a.usuario_id = %s
    """, (current_user.id,))
    aluno = cur.fetchone()
    if aluno:
        try:
            cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (aluno.get("graduacao_id"),))
            g = cur.fetchone()
            if g:
                aluno["faixa_nome"] = g.get("faixa")
                aluno["graduacao_nome"] = g.get("graduacao")
        except Exception:
            pass
        aluno.setdefault("faixa_nome", None)
        aluno.setdefault("graduacao_nome", None)
        aluno["email_curriculo"] = aluno.get("email") or getattr(current_user, "email", None)
        aluno["telefone_curriculo"] = aluno.get("telefone_celular") or aluno.get("telefone") or ""
        exame = aluno.get("ultimo_exame_faixa")
        if exame and hasattr(exame, "strftime"):
            aluno["ultimo_exame_faixa_formatada"] = exame.strftime("%d/%m/%Y")
        else:
            try:
                aluno["ultimo_exame_faixa_formatada"] = datetime.strptime(str(exame)[:10], "%Y-%m-%d").strftime("%d/%m/%Y") if exame else None
            except (ValueError, TypeError):
                aluno["ultimo_exame_faixa_formatada"] = str(exame) if exame else None
        _build_endereco_completo(aluno)
    if not aluno:
        cur.close()
        conn.close()
        flash("Nenhum aluno vinculado a este usuário.", "warning")
        return redirect(url_for("painel_aluno.painel"))

    tipo = (aluno.get("tipo_aluno") or "").strip().lower()
    aluno["classe_categoria"] = {"infantil": "Infantil", "juvenil": "Juvenil", "adulto": "Adulto"}.get(tipo, "")

    aluno["proxima_faixa"] = "—"
    try:
        cur.execute("SELECT id, faixa, graduacao FROM graduacao ORDER BY id")
        faixas = cur.fetchall()
        gid = aluno.get("graduacao_id")
        for i, f in enumerate(faixas):
            if f["id"] == gid and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                aluno["proxima_faixa"] = f"{proxima.get('faixa', '')} {proxima.get('graduacao', '')}".strip() or "—"
                break
    except Exception:
        pass

    aluno["modalidades"] = []
    try:
        cur.execute("SELECT m.id, m.nome FROM modalidade m INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id WHERE am.aluno_id = %s ORDER BY m.nome", (aluno["id"],))
        aluno["modalidades"] = cur.fetchall()
    except Exception:
        pass

    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/curriculo.html",
        aluno=aluno,
    )


@bp_painel_aluno.route("/curriculo/impressao")
@login_required
def curriculo_impressao():
    """Página de impressão/PDF do currículo (sem sidebar, layout CV)."""
    if not (current_user.has_role("aluno") or current_user.has_role("admin")):
        flash("Acesso restrito.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT a.*, t.Nome AS turma_nome, ac.nome AS academia_nome
        FROM alunos a
        LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
        LEFT JOIN academias ac ON ac.id = a.id_academia
        WHERE a.usuario_id = %s
    """, (current_user.id,))
    aluno = cur.fetchone()
    if not aluno:
        cur.close()
        conn.close()
        return redirect(url_for("painel_aluno.painel"))

    try:
        cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (aluno.get("graduacao_id"),))
        g = cur.fetchone()
        if g:
            aluno["faixa_nome"] = g.get("faixa")
            aluno["graduacao_nome"] = g.get("graduacao")
    except Exception:
        pass
    aluno.setdefault("faixa_nome", None)
    aluno.setdefault("graduacao_nome", None)
    aluno["email_curriculo"] = aluno.get("email") or getattr(current_user, "email", None)
    aluno["telefone_curriculo"] = aluno.get("telefone_celular") or aluno.get("telefone") or ""
    exame = aluno.get("ultimo_exame_faixa")
    if exame and hasattr(exame, "strftime"):
        aluno["ultimo_exame_faixa_formatada"] = exame.strftime("%d/%m/%Y")
    else:
        try:
            aluno["ultimo_exame_faixa_formatada"] = datetime.strptime(str(exame)[:10], "%Y-%m-%d").strftime("%d/%m/%Y") if exame else None
        except (ValueError, TypeError):
            aluno["ultimo_exame_faixa_formatada"] = str(exame) if exame else None
    _build_endereco_completo(aluno)

    tipo = (aluno.get("tipo_aluno") or "").strip().lower()
    aluno["classe_categoria"] = {"infantil": "Infantil", "juvenil": "Juvenil", "adulto": "Adulto"}.get(tipo, "")
    aluno["proxima_faixa"] = "—"
    try:
        cur.execute("SELECT id, faixa, graduacao FROM graduacao ORDER BY id")
        faixas = cur.fetchall()
        gid = aluno.get("graduacao_id")
        for i, f in enumerate(faixas):
            if f["id"] == gid and i + 1 < len(faixas):
                proxima = faixas[i + 1]
                aluno["proxima_faixa"] = f"{proxima.get('faixa', '')} {proxima.get('graduacao', '')}".strip() or "—"
                break
    except Exception:
        pass

    aluno["modalidades"] = []
    try:
        cur.execute("SELECT m.id, m.nome FROM modalidade m INNER JOIN aluno_modalidades am ON am.modalidade_id = m.id WHERE am.aluno_id = %s", (aluno["id"],))
        aluno["modalidades"] = cur.fetchall()
    except Exception:
        pass

    cur.close()
    conn.close()

    return render_template(
        "painel_aluno/curriculo_impressao.html",
        aluno=aluno,
    )
