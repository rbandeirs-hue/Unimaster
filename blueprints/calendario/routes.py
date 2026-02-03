# ============================================================
# 🗓️ SISTEMA DE CALENDÁRIO HIERÁRQUICO
# ============================================================
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from config import get_db_connection
from datetime import datetime, date, timedelta
import mysql.connector.errors
import hashlib
import requests
import json
import re
import os

bp_calendario = Blueprint('calendario', __name__, url_prefix='/calendario')

# ============================================================
# 🔹 HELPERS
# ============================================================

def _hora_para_sort(hora):
    """Converte hora (time/timedelta/str) para string ordenável HH:MM."""
    if hora is None:
        return '00:00'
    if hasattr(hora, 'strftime'):
        return hora.strftime('%H:%M')
    if hasattr(hora, 'total_seconds'):
        s = int(hora.total_seconds())
        h, m = divmod(s // 60, 60)
        return f'{h:02d}:{m:02d}'
    s = str(hora)
    return s[:5] if len(s) >= 5 else '00:00'


def _get_nivel_e_id_usuario():
    """Retorna o nível e ID do contexto atual do usuário baseado no modo_painel."""
    modo = session.get('modo_painel', 'academia')
    
    if modo == 'federacao' and current_user.id_federacao:
        return 'federacao', current_user.id_federacao
    elif modo == 'associacao' and current_user.id_associacao:
        return 'associacao', current_user.id_associacao
    elif modo == 'academia' and current_user.id_academia:
        return 'academia', current_user.id_academia
    elif modo == 'professor':
        # Professor vê calendário da academia
        if current_user.id_academia:
            return 'academia', current_user.id_academia
    elif modo == 'aluno':
        # Aluno vê calendário da sua academia
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, id_academia FROM alunos WHERE usuario_id = %s LIMIT 1", (current_user.id,))
        aluno = cur.fetchone()
        cur.close()
        conn.close()
        if aluno and aluno.get('id_academia'):
            return 'academia', aluno['id_academia']
    
    return None, None


def _get_academias_ids():
    """Retorna lista de IDs de academias que o usuário pode gerenciar."""
    if current_user.has_role('admin'):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id FROM academias")
        academias = cur.fetchall()
        cur.close()
        conn.close()
        return [a['id'] for a in academias]
    
    nivel, nivel_id = _get_nivel_e_id_usuario()
    if nivel == 'federacao':
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id FROM academias WHERE id_federacao = %s", (nivel_id,))
        academias = cur.fetchall()
        cur.close()
        conn.close()
        return [a['id'] for a in academias]
    elif nivel == 'associacao':
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (nivel_id,))
        academias = cur.fetchall()
        cur.close()
        conn.close()
        return [a['id'] for a in academias]
    elif nivel == 'academia':
        return [nivel_id] if nivel_id else []
    
    return []


def _sincronizar_feriados_nacionais(ano, nivel, nivel_id):
    """
    Sincroniza feriados nacionais brasileiros para o ano especificado.
    Usa a API pública do Brasil API (https://brasilapi.com.br/api/feriados/v1/{ano})
    Quando nivel=associacao, também insere em todas as academias vinculadas.
    """
    try:
        response = requests.get(f"https://brasilapi.com.br/api/feriados/v1/{ano}", timeout=10)
        if response.status_code != 200:
            return 0, "Erro ao buscar feriados da API"
        
        feriados = response.json()
        conn = get_db_connection()
        cur = conn.cursor()
        
        eventos_criados = 0
        
        # Níveis onde inserir: associação + academias vinculadas (se for associação)
        niveis_inserir = [(nivel, nivel_id)]
        if nivel == 'associacao':
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (nivel_id,))
            academias = cur.fetchall()
            for (acad_id,) in academias:
                niveis_inserir.append(('academia', acad_id))
        
        for feriado in feriados:
            data_feriado = feriado.get('date')
            nome_feriado = feriado.get('name')
            tipo_feriado = feriado.get('type', 'national')
            
            if not data_feriado or not nome_feriado:
                continue
            
            for niv, niv_id in niveis_inserir:
                cur.execute("""
                    SELECT id FROM eventos 
                    WHERE data_inicio = %s AND titulo = %s AND nivel = %s AND nivel_id = %s
                """, (data_feriado, nome_feriado, niv, niv_id))
                
                if cur.fetchone():
                    continue  # Já existe neste nível
                
                cur.execute("""
                    INSERT INTO eventos 
                    (titulo, descricao, data_inicio, tipo, nivel, nivel_id, 
                     feriado_nacional, origem_sincronizacao, criado_por_usuario_id, cor)
                    VALUES (%s, %s, %s, 'feriado', %s, %s, 1, 'api_brasilapi', %s, '#dc3545')
                """, (
                    nome_feriado,
                    f"Feriado {tipo_feriado}",
                    data_feriado,
                    niv,
                    niv_id,
                    current_user.id
                ))
                eventos_criados += 1
        
        conn.commit()
        cur.close()
        conn.close()
        
        return eventos_criados, None
    except Exception as e:
        return 0, str(e)


def _parsear_dias_de_diashorario(diashorario):
    """
    Tenta extrair dias da semana de DiasHorario (ex: "Seg/Qua/Sex", "1,3,5", "Segunda e Quarta").
    Retorna string no formato "1,3,5" (0=Dom, 1=Seg...6=Sab) ou None se não conseguir.
    """
    if not diashorario or not isinstance(diashorario, str):
        return None
    s = diashorario.upper().strip()
    dias_map = {
        'DOM': '0', 'SEG': '1', 'TER': '2', 'QUA': '3', 'QUI': '4', 'SEX': '5', 'SAB': '6',
        'SEGUNDA': '1', 'TERCA': '2', 'QUARTA': '3', 'QUINTA': '4', 'SEXTA': '5', 'SABADO': '6', 'DOMINGO': '0',
    }
    encontrados = set()
    # Números isolados (0-6)
    for m in re.finditer(r'\b([0-6])\b', s):
        encontrados.add(m.group(1))
    # Nomes abreviados ou completos (ex: SEG, Segunda, Quarta)
    s_norm = s.replace('Á', 'A').replace('Ã', 'A')
    for nome, num in dias_map.items():
        if nome in s or nome in s_norm:
            encontrados.add(num)
    if encontrados:
        return ','.join(sorted(encontrados, key=int))
    return None


def _parsear_horarios_de_diashorario(diashorario):
    """
    Extrai hora_inicio e hora_fim do texto DiasHorario.
    Ex: "Ter/Qui - 20:00 às 21:00" -> (20:00, 21:00)
    Retorna (hora_inicio, hora_fim) como objetos time ou (None, None).
    """
    if not diashorario or not isinstance(diashorario, str):
        return None, None
    s = diashorario.strip()
    m = re.search(r'(\d{1,2})[h:]?\s*(\d{2})?\s*(?:às|-|a|–)\s*(\d{1,2})[h:]?\s*(\d{2})?', s, re.I)
    if m:
        h1, m1, h2, m2 = m.group(1), m.group(2) or '00', m.group(3), m.group(4) or '00'
        try:
            from datetime import time
            return time(int(h1), int(m1)), time(int(h2), int(m2))
        except (ValueError, TypeError):
            pass
    m = re.search(r'(\d{1,2})[h:]?\s*(\d{2})?\b', s)
    if m:
        h, mn = m.group(1), m.group(2) or '00'
        try:
            from datetime import time
            return time(int(h), int(mn)), None
        except (ValueError, TypeError):
            pass
    return None, None


def _sincronizar_turmas_como_eventos(academia_id):
    """
    Sincroniza as turmas da academia como eventos recorrentes no calendário.
    Usa dias_semana/hora_inicio/hora_fim se existirem, senão tenta parsear DiasHorario.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Tenta com colunas novas; se não existirem, usa colunas antigas
        try:
            cur.execute("""
                SELECT TurmaID, Nome, dias_semana, hora_inicio, hora_fim, Observacoes, id_academia, DiasHorario
                FROM turmas WHERE id_academia = %s
            """, (academia_id,))
        except mysql.connector.errors.ProgrammingError:
            cur.execute("""
                SELECT TurmaID, Nome, Observacoes, id_academia, DiasHorario
                FROM turmas WHERE id_academia = %s
            """, (academia_id,))
        
        turmas = cur.fetchall()
        eventos_criados = 0
        
        for turma in turmas:
            dias_semana = turma.get('dias_semana') or ''
            if not dias_semana or (isinstance(dias_semana, str) and not dias_semana.strip()):
                dias_semana = _parsear_dias_de_diashorario(turma.get('DiasHorario') or '')
            if not dias_semana:
                continue  # Sem dias definidos, pula
            
            cur.execute("""
                SELECT id FROM eventos 
                WHERE turma_id = %s AND recorrente = 1 AND tipo = 'aula'
            """, (turma['TurmaID'],))
            evento_existente = cur.fetchone()
            
            descricao = turma.get('Observacoes') or ''
            hora_inicio = turma.get('hora_inicio')
            hora_fim = turma.get('hora_fim')
            if not hora_inicio and not hora_fim:
                hora_inicio, hora_fim = _parsear_horarios_de_diashorario(turma.get('DiasHorario') or '')
            
            # Título com horário quando disponível (ex: "Aula - Judô - 2º Turma (19:00-20:00)")
            titulo_aula = f"Aula - {turma['Nome']}"
            if hora_inicio:
                h_ini = hora_inicio.strftime('%H:%M') if hasattr(hora_inicio, 'strftime') else str(hora_inicio)[:5]
                if hora_fim:
                    h_fim = hora_fim.strftime('%H:%M') if hasattr(hora_fim, 'strftime') else str(hora_fim)[:5]
                    titulo_aula = f"Aula - {turma['Nome']} ({h_ini}-{h_fim})"
                else:
                    titulo_aula = f"Aula - {turma['Nome']} ({h_ini})"
            
            if evento_existente:
                # Atualiza evento existente com horários se estiverem vazios
                cur.execute("SELECT hora_inicio, hora_fim FROM eventos WHERE id = %s", (evento_existente['id'],))
                ev = cur.fetchone()
                if ev and (not ev.get('hora_inicio') or not ev.get('hora_fim')) and (hora_inicio or hora_fim):
                    cur.execute("""
                        UPDATE eventos SET hora_inicio = %s, hora_fim = %s, titulo = %s
                        WHERE id = %s
                    """, (hora_inicio, hora_fim, titulo_aula, evento_existente['id']))
                    eventos_criados += 1
            else:
                cur.execute("""
                    INSERT INTO eventos
                    (titulo, descricao, data_inicio, tipo, recorrente, dias_semana,
                     hora_inicio, hora_fim, nivel, nivel_id, turma_id, criado_por_usuario_id, cor)
                    VALUES (%s, %s, CURDATE(), 'aula', 1, %s, %s, %s, 'academia', %s, %s, %s, '#0d6efd')
                """, (
                    titulo_aula,
                    descricao,
                    dias_semana,
                    hora_inicio,
                    hora_fim,
                    academia_id,
                    turma['TurmaID'],
                    current_user.id
                ))
                eventos_criados += 1
        
        conn.commit()
        try:
            _detectar_conflitos_aula_feriado(academia_id, datetime.now().year)
        except Exception:
            pass
        return eventos_criados, None
    except Exception as e:
        conn.rollback()
        return 0, str(e)
    finally:
        cur.close()
        conn.close()


def _detectar_conflitos_aula_feriado(academia_id, ano):
    """
    Detecta aulas recorrentes que caem em feriados e cria registros pendentes para o gestor resolver.
    Retorna quantidade de conflitos criados.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    criados = 0
    try:
        data_ini = date(ano, 1, 1)
        data_fim = date(ano, 12, 31)

        cur.execute("""
            SELECT id, titulo, dias_semana FROM eventos
            WHERE nivel = 'academia' AND nivel_id = %s AND recorrente = 1
              AND tipo = 'aula' AND status = 'ativo' AND dias_semana IS NOT NULL
        """, (academia_id,))
        aulas = cur.fetchall()

        cur.execute("""
            SELECT data_inicio, titulo FROM eventos
            WHERE nivel = 'academia' AND nivel_id = %s
              AND (tipo = 'feriado' OR feriado_nacional = 1)
              AND status = 'ativo'
              AND data_inicio BETWEEN %s AND %s
        """, (academia_id, data_ini, data_fim))
        feriados_list = cur.fetchall()
        datas_feriados = set()
        feriados_por_data = {}
        for r in feriados_list:
            d = r['data_inicio']
            data_str = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)[:10]
            datas_feriados.add(data_str)
            feriados_por_data[data_str] = r['titulo'] or 'Feriado'

        for aula in aulas:
            dias_semana = [int(d) for d in aula['dias_semana'].split(',') if d.strip()]
            if not dias_semana:
                continue

            data_atual = data_ini
            while data_atual <= data_fim:
                dia_semana = data_atual.weekday()
                dia_sistema = (dia_semana + 1) % 7
                if dia_sistema in dias_semana:
                    data_str = data_atual.strftime('%Y-%m-%d')
                    if data_str in datas_feriados:
                        try:
                            cur.execute("""
                                INSERT IGNORE INTO conflitos_aula_feriado
                                (academia_id, evento_id, data_conflito, feriado_titulo, status)
                                VALUES (%s, %s, %s, %s, 'pendente')
                            """, (academia_id, aula['id'], data_atual, feriados_por_data.get(data_str, 'Feriado')))
                            criados += cur.rowcount
                        except Exception:
                            pass
                data_atual += timedelta(days=1)

        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close()
        conn.close()
    return criados


# ============================================================
# 🔹 ROTAS PRINCIPAIS
# ============================================================

@bp_calendario.route('/')
@login_required
def index():
    """Hub do calendário baseado no nível do usuário."""
    modo = session.get('modo_painel', 'academia')
    
    # Responsável vai para calendário do aluno
    if modo == 'responsavel':
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""
                SELECT a.id FROM responsavel_alunos ra
                JOIN alunos a ON a.id = ra.aluno_id
                WHERE ra.usuario_id = %s AND a.ativo = 1 ORDER BY a.nome
            """, (current_user.id,))
            alunos = cur.fetchall()
        except Exception:
            alunos = []
        cur.close()
        conn.close()
        if alunos:
            return redirect(url_for('calendario.aluno_responsavel', aluno_id=alunos[0]['id']))
        flash('Nenhum aluno vinculado.', 'warning')
        return redirect(url_for('painel.home'))
    
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        flash('Você não tem permissão para acessar o calendário.', 'warning')
        return redirect(url_for('painel.home'))
    
    modo = session.get('modo_painel', 'academia')
    
    # Redireciona para a visualização apropriada
    if modo in ['federacao', 'associacao', 'academia']:
        return redirect(url_for('calendario.visualizar', nivel=nivel, nivel_id=nivel_id))
    elif modo == 'professor':
        return redirect(url_for('calendario.visualizar', nivel='academia', nivel_id=nivel_id))
    elif modo == 'aluno':
        return redirect(url_for('calendario.aluno'))
    flash('Modo de visualização não reconhecido.', 'warning')
    return redirect(url_for('painel.home'))


@bp_calendario.route('/visualizar')
@login_required
def visualizar():
    """Visualização do calendário para gestores (federação, associação, academia, professor)."""
    nivel = request.args.get('nivel')
    nivel_id = request.args.get('nivel_id', type=int)
    mes = request.args.get('mes', type=int, default=datetime.now().month)
    ano = request.args.get('ano', type=int, default=datetime.now().year)
    
    # Validação de acesso
    nivel_usuario, nivel_id_usuario = _get_nivel_e_id_usuario()
    if not nivel_usuario or not nivel_id_usuario:
        flash('Você não tem permissão para acessar o calendário.', 'warning')
        return redirect(url_for('painel.home'))
    
    # Se não especificado, usa o nível do usuário
    if not nivel or not nivel_id:
        nivel = nivel_usuario
        nivel_id = nivel_id_usuario
    
    # Busca eventos do mês
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    data_inicio_mes = date(ano, mes, 1)
    if mes == 12:
        data_fim_mes = date(ano + 1, 1, 1) - timedelta(days=1)
    else:
        data_fim_mes = date(ano, mes + 1, 1) - timedelta(days=1)
    
    try:
        # Busca eventos normais (não recorrentes)
        cur.execute("""
            SELECT e.*, 
                   t.Nome as turma_nome,
                   u.nome as criador_nome
            FROM eventos e
            LEFT JOIN turmas t ON t.TurmaID = e.turma_id
            LEFT JOIN usuarios u ON u.id = e.criado_por_usuario_id
            WHERE e.nivel = %s AND e.nivel_id = %s
              AND e.recorrente = 0
              AND e.status = 'ativo'
              AND ((e.data_inicio BETWEEN %s AND %s) 
                   OR (e.data_fim IS NOT NULL AND e.data_fim >= %s AND e.data_inicio <= %s))
            ORDER BY e.data_inicio, e.hora_inicio
        """, (nivel, nivel_id, data_inicio_mes, data_fim_mes, data_inicio_mes, data_fim_mes))
        eventos_normais = cur.fetchall()
        
        # Busca eventos recorrentes (aulas)
        cur.execute("""
            SELECT e.*, 
                   t.Nome as turma_nome,
                   u.nome as criador_nome
            FROM eventos e
            LEFT JOIN turmas t ON t.TurmaID = e.turma_id
            LEFT JOIN usuarios u ON u.id = e.criado_por_usuario_id
            WHERE e.nivel = %s AND e.nivel_id = %s
              AND e.recorrente = 1
              AND e.status = 'ativo'
            ORDER BY e.hora_inicio
        """, (nivel, nivel_id))
        eventos_recorrentes = cur.fetchall()
        
        # Busca exceções de eventos recorrentes
        cur.execute("""
            SELECT ee.*, e.titulo, e.turma_id
            FROM eventos_excecoes ee
            JOIN eventos e ON e.id = ee.evento_id
            WHERE ee.data_excecao BETWEEN %s AND %s
        """, (data_inicio_mes, data_fim_mes))
        excecoes = cur.fetchall()
        excecoes_dict = {}
        for exc in excecoes:
            key = f"{exc['evento_id']}_{exc['data_excecao']}"
            excecoes_dict[key] = exc
        
        # Busca informações do contexto
        contexto = {}
        if nivel == 'federacao':
            cur.execute("SELECT nome FROM federacoes WHERE id = %s", (nivel_id,))
            fed = cur.fetchone()
            contexto = {'nome': fed['nome'] if fed else 'Federação'}
        elif nivel == 'associacao':
            cur.execute("SELECT nome FROM associacoes WHERE id = %s", (nivel_id,))
            assoc = cur.fetchone()
            contexto = {'nome': assoc['nome'] if assoc else 'Associação'}
        elif nivel == 'academia':
            cur.execute("SELECT nome FROM academias WHERE id = %s", (nivel_id,))
            acad = cur.fetchone()
            contexto = {'nome': acad['nome'] if acad else 'Academia'}
        
    except mysql.connector.errors.ProgrammingError:
        flash('Sistema de calendário não está configurado. Execute as migrações necessárias.', 'warning')
        return redirect(url_for('painel.home'))
    finally:
        cur.close()
        conn.close()
    
    # Expande eventos de múltiplos dias (data_inicio até data_fim) para aparecer em cada dia
    eventos_normais_expandidos = []
    for evento in eventos_normais:
        d_ini = evento['data_inicio']
        d_fim = evento.get('data_fim') or d_ini
        if isinstance(d_ini, str):
            d_ini = datetime.strptime(d_ini[:10], '%Y-%m-%d').date()
        if isinstance(d_fim, str):
            d_fim = datetime.strptime(d_fim[:10], '%Y-%m-%d').date() if d_fim else d_ini
        if d_fim < d_ini:
            d_fim = d_ini
        data_atual = max(d_ini, data_inicio_mes)
        fim_loop = min(d_fim, data_fim_mes)
        while data_atual <= fim_loop:
            ev = evento.copy()
            ev['data_inicio'] = data_atual
            ev['data_fim'] = d_fim
            eventos_normais_expandidos.append(ev)
            data_atual += timedelta(days=1)
    
    # Expande eventos recorrentes para o mês
    eventos_expandidos = []
    for evento in eventos_recorrentes:
        if not evento.get('dias_semana'):
            continue
        
        dias_permitidos = [int(d) for d in evento['dias_semana'].split(',') if d.strip()]
        
        data_atual = data_inicio_mes
        while data_atual <= data_fim_mes:
            dia_semana = data_atual.weekday()
            # Converte: Python usa 0=segunda, mas nosso sistema usa 0=domingo
            dia_semana_sistema = (dia_semana + 1) % 7
            
            if dia_semana_sistema in dias_permitidos:
                # Verifica se há exceção para este dia
                key_excecao = f"{evento['id']}_{data_atual}"
                excecao = excecoes_dict.get(key_excecao)
                
                if excecao and excecao['tipo'] == 'cancelamento':
                    data_atual += timedelta(days=1)
                    continue  # Pula este dia
                
                evento_dia = evento.copy()
                evento_dia['data_inicio'] = data_atual
                evento_dia['data_fim'] = data_atual
                
                # Se houver alteração de horário
                if excecao and excecao.get('nova_hora_inicio'):
                    evento_dia['hora_inicio'] = excecao['nova_hora_inicio']
                    evento_dia['hora_fim'] = excecao['nova_hora_fim']
                
                eventos_expandidos.append(evento_dia)
            
            data_atual += timedelta(days=1)
    
    # Combina todos os eventos
    todos_eventos = eventos_normais_expandidos + eventos_expandidos
    todos_eventos.sort(key=lambda x: (x['data_inicio'], _hora_para_sort(x.get('hora_inicio'))))
    
    # Agrupa eventos por data
    eventos_por_data = {}
    for evento in todos_eventos:
        data_str = evento['data_inicio'].strftime('%Y-%m-%d') if isinstance(evento['data_inicio'], date) else str(evento['data_inicio'])
        if data_str not in eventos_por_data:
            eventos_por_data[data_str] = []
        eventos_por_data[data_str].append(evento)
    
    hoje_str = date.today().strftime('%Y-%m-%d')
    return render_template('calendario/visualizar.html',
                          nivel=nivel,
                          nivel_id=nivel_id,
                          mes=mes,
                          ano=ano,
                          eventos_por_data=eventos_por_data,
                          contexto=contexto,
                          hoje_str=hoje_str)


@bp_calendario.route('/aluno')
@login_required
def aluno():
    """Visualização do calendário para alunos (somente leitura)."""
    # Busca academia do aluno
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    cur.execute("SELECT id, id_academia FROM alunos WHERE usuario_id = %s LIMIT 1", (current_user.id,))
    aluno = cur.fetchone()
    
    if not aluno or not aluno.get('id_academia'):
        flash('Você não está vinculado a nenhuma academia.', 'warning')
        cur.close()
        conn.close()
        return redirect(url_for('painel.home'))
    
    academia_id = aluno['id_academia']
    mes = request.args.get('mes', type=int, default=datetime.now().month)
    ano = request.args.get('ano', type=int, default=datetime.now().year)
    
    # Busca informações da academia
    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    academia = cur.fetchone()
    
    data_inicio_mes = date(ano, mes, 1)
    if mes == 12:
        data_fim_mes = date(ano + 1, 1, 1) - timedelta(days=1)
    else:
        data_fim_mes = date(ano, mes + 1, 1) - timedelta(days=1)
    
    try:
        # Busca eventos da academia
        cur.execute("""
            SELECT e.*, 
                   t.Nome as turma_nome
            FROM eventos e
            LEFT JOIN turmas t ON t.TurmaID = e.turma_id
            WHERE e.nivel = 'academia' AND e.nivel_id = %s
              AND e.recorrente = 0
              AND e.status = 'ativo'
              AND ((e.data_inicio BETWEEN %s AND %s) 
                   OR (e.data_fim IS NOT NULL AND e.data_fim >= %s AND e.data_inicio <= %s))
            ORDER BY e.data_inicio, e.hora_inicio
        """, (academia_id, data_inicio_mes, data_fim_mes, data_inicio_mes, data_fim_mes))
        eventos_normais = cur.fetchall()
        
        # Busca eventos recorrentes (aulas das turmas do aluno)
        cur.execute("""
            SELECT e.*, 
                   t.Nome as turma_nome
            FROM eventos e
            JOIN turmas t ON t.TurmaID = e.turma_id
            JOIN aluno_turmas at ON at.TurmaID = t.TurmaID
            WHERE at.aluno_id = %s
              AND e.nivel = 'academia' AND e.nivel_id = %s
              AND e.recorrente = 1
              AND e.status = 'ativo'
            ORDER BY e.hora_inicio
        """, (aluno['id'], academia_id))
        eventos_recorrentes = cur.fetchall()
        
        # Busca exceções
        cur.execute("""
            SELECT ee.*, e.titulo, e.turma_id
            FROM eventos_excecoes ee
            JOIN eventos e ON e.id = ee.evento_id
            WHERE ee.data_excecao BETWEEN %s AND %s
        """, (data_inicio_mes, data_fim_mes))
        excecoes = cur.fetchall()
        excecoes_dict = {}
        for exc in excecoes:
            key = f"{exc['evento_id']}_{exc['data_excecao']}"
            excecoes_dict[key] = exc
        
    except mysql.connector.errors.ProgrammingError:
        flash('Sistema de calendário não está configurado.', 'warning')
        cur.close()
        conn.close()
        return redirect(url_for('painel.home'))
    
    cur.close()
    conn.close()
    
    # Expande eventos de múltiplos dias para aparecer em cada dia
    eventos_normais_expandidos = []
    for evento in eventos_normais:
        d_ini = evento['data_inicio']
        d_fim = evento.get('data_fim') or d_ini
        if isinstance(d_ini, str):
            d_ini = datetime.strptime(d_ini[:10], '%Y-%m-%d').date()
        if isinstance(d_fim, str):
            d_fim = datetime.strptime(d_fim[:10], '%Y-%m-%d').date() if d_fim else d_ini
        if d_fim < d_ini:
            d_fim = d_ini
        data_atual = max(d_ini, data_inicio_mes)
        fim_loop = min(d_fim, data_fim_mes)
        while data_atual <= fim_loop:
            ev = evento.copy()
            ev['data_inicio'] = data_atual
            ev['data_fim'] = d_fim
            eventos_normais_expandidos.append(ev)
            data_atual += timedelta(days=1)
    
    # Expande eventos recorrentes
    eventos_expandidos = []
    for evento in eventos_recorrentes:
        if not evento.get('dias_semana'):
            continue
        
        dias_permitidos = [int(d) for d in evento['dias_semana'].split(',') if d.strip()]
        
        data_atual = data_inicio_mes
        while data_atual <= data_fim_mes:
            dia_semana = data_atual.weekday()
            dia_semana_sistema = (dia_semana + 1) % 7
            
            if dia_semana_sistema in dias_permitidos:
                key_excecao = f"{evento['id']}_{data_atual}"
                excecao = excecoes_dict.get(key_excecao)
                
                if excecao and excecao['tipo'] == 'cancelamento':
                    data_atual += timedelta(days=1)
                    continue
                
                evento_dia = evento.copy()
                evento_dia['data_inicio'] = data_atual
                evento_dia['data_fim'] = data_atual
                
                if excecao and excecao.get('nova_hora_inicio'):
                    evento_dia['hora_inicio'] = excecao['nova_hora_inicio']
                    evento_dia['hora_fim'] = excecao['nova_hora_fim']
                
                eventos_expandidos.append(evento_dia)
            
            data_atual += timedelta(days=1)
    
    # Combina eventos
    todos_eventos = eventos_normais_expandidos + eventos_expandidos
    todos_eventos.sort(key=lambda x: (x['data_inicio'], _hora_para_sort(x.get('hora_inicio'))))
    
    # Agrupa por data
    eventos_por_data = {}
    for evento in todos_eventos:
        data_str = evento['data_inicio'].strftime('%Y-%m-%d') if isinstance(evento['data_inicio'], date) else str(evento['data_inicio'])
        if data_str not in eventos_por_data:
            eventos_por_data[data_str] = []
        eventos_por_data[data_str].append(evento)
    
    hoje_str = date.today().strftime('%Y-%m-%d')
    return render_template('calendario/aluno.html',
                          mes=mes,
                          ano=ano,
                          eventos_por_data=eventos_por_data,
                          academia=academia,
                          hoje_str=hoje_str)


@bp_calendario.route('/aluno-responsavel')
@login_required
def aluno_responsavel():
    """Calendário para responsável (eventos da academia do aluno selecionado)."""
    if not (current_user.has_role('responsavel') or current_user.has_role('admin')):
        flash('Acesso restrito aos responsáveis.', 'warning')
        return redirect(url_for('painel.home'))
    
    aluno_id = request.args.get('aluno_id', type=int)
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        cur.execute("""
            SELECT a.id, a.nome, a.id_academia
            FROM responsavel_alunos ra
            JOIN alunos a ON a.id = ra.aluno_id
            WHERE ra.usuario_id = %s AND a.ativo = 1
            ORDER BY a.nome
        """, (current_user.id,))
        alunos = cur.fetchall()
    except Exception:
        alunos = []
    
    if not alunos:
        flash('Nenhum aluno vinculado a este responsável.', 'warning')
        cur.close()
        conn.close()
        return redirect(url_for('painel.home'))
    
    if not aluno_id and len(alunos) == 1:
        return redirect(url_for('calendario.aluno_responsavel', aluno_id=alunos[0]['id']))
    
    if not aluno_id:
        cur.close()
        conn.close()
        return redirect(url_for('painel_responsavel.meu_perfil'))
    
    aluno = next((a for a in alunos if a['id'] == aluno_id), None)
    if not aluno or not aluno.get('id_academia'):
        flash('Aluno não encontrado ou sem academia vinculada.', 'warning')
        cur.close()
        conn.close()
        return redirect(url_for('painel_responsavel.meu_perfil'))
    
    academia_id = aluno['id_academia']
    mes = request.args.get('mes', type=int, default=datetime.now().month)
    ano = request.args.get('ano', type=int, default=datetime.now().year)
    
    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    academia = cur.fetchone()
    
    data_inicio_mes = date(ano, mes, 1)
    if mes == 12:
        data_fim_mes = date(ano + 1, 1, 1) - timedelta(days=1)
    else:
        data_fim_mes = date(ano, mes + 1, 1) - timedelta(days=1)
    
    try:
        cur.execute("""
            SELECT e.*, t.Nome as turma_nome
            FROM eventos e
            LEFT JOIN turmas t ON t.TurmaID = e.turma_id
            WHERE e.nivel = 'academia' AND e.nivel_id = %s
              AND e.recorrente = 0 AND e.status = 'ativo'
              AND ((e.data_inicio BETWEEN %s AND %s) 
                   OR (e.data_fim IS NOT NULL AND e.data_fim >= %s AND e.data_inicio <= %s))
            ORDER BY e.data_inicio, e.hora_inicio
        """, (academia_id, data_inicio_mes, data_fim_mes, data_inicio_mes, data_fim_mes))
        eventos_normais = cur.fetchall()
        
        cur.execute("""
            SELECT e.*, t.Nome as turma_nome
            FROM eventos e
            JOIN turmas t ON t.TurmaID = e.turma_id
            JOIN aluno_turmas at ON at.TurmaID = t.TurmaID
            WHERE at.aluno_id = %s AND e.nivel = 'academia' AND e.nivel_id = %s
              AND e.recorrente = 1 AND e.status = 'ativo'
            ORDER BY e.hora_inicio
        """, (aluno_id, academia_id))
        eventos_recorrentes = cur.fetchall()
        
        cur.execute("""
            SELECT ee.*, e.titulo, e.turma_id
            FROM eventos_excecoes ee
            JOIN eventos e ON e.id = ee.evento_id
            WHERE ee.data_excecao BETWEEN %s AND %s
        """, (data_inicio_mes, data_fim_mes))
        excecoes = cur.fetchall()
        excecoes_dict = {f"{e['evento_id']}_{e['data_excecao']}": e for e in excecoes}
    except mysql.connector.errors.ProgrammingError:
        flash('Sistema de calendário não está configurado.', 'warning')
        cur.close()
        conn.close()
        return redirect(url_for('painel.home'))
    
    cur.close()
    conn.close()
    
    eventos_normais_expandidos = []
    for evento in eventos_normais:
        d_ini = evento['data_inicio']
        d_fim = evento.get('data_fim') or d_ini
        if isinstance(d_ini, str):
            d_ini = datetime.strptime(d_ini[:10], '%Y-%m-%d').date()
        if isinstance(d_fim, str):
            d_fim = datetime.strptime(d_fim[:10], '%Y-%m-%d').date() if d_fim else d_ini
        if d_fim < d_ini:
            d_fim = d_ini
        data_atual = max(d_ini, data_inicio_mes)
        fim_loop = min(d_fim, data_fim_mes)
        while data_atual <= fim_loop:
            ev = evento.copy()
            ev['data_inicio'] = data_atual
            ev['data_fim'] = d_fim
            eventos_normais_expandidos.append(ev)
            data_atual += timedelta(days=1)
    
    eventos_expandidos = []
    for evento in eventos_recorrentes:
        if not evento.get('dias_semana'):
            continue
        dias_permitidos = [int(d) for d in evento['dias_semana'].split(',') if d.strip()]
        data_atual = data_inicio_mes
        while data_atual <= data_fim_mes:
            dia_semana_sistema = (data_atual.weekday() + 1) % 7
            if dia_semana_sistema in dias_permitidos:
                key_exc = f"{evento['id']}_{data_atual}"
                excecao = excecoes_dict.get(key_exc)
                if excecao and excecao['tipo'] == 'cancelamento':
                    data_atual += timedelta(days=1)
                    continue
                ev = evento.copy()
                ev['data_inicio'] = data_atual
                ev['data_fim'] = data_atual
                if excecao and excecao.get('nova_hora_inicio'):
                    ev['hora_inicio'] = excecao['nova_hora_inicio']
                    ev['hora_fim'] = excecao['nova_hora_fim']
                eventos_expandidos.append(ev)
            data_atual += timedelta(days=1)
    
    todos_eventos = eventos_normais_expandidos + eventos_expandidos
    todos_eventos.sort(key=lambda x: (x['data_inicio'], _hora_para_sort(x.get('hora_inicio'))))
    eventos_por_data = {}
    for evento in todos_eventos:
        data_str = evento['data_inicio'].strftime('%Y-%m-%d') if isinstance(evento['data_inicio'], date) else str(evento['data_inicio'])
        if data_str not in eventos_por_data:
            eventos_por_data[data_str] = []
        eventos_por_data[data_str].append(evento)
    
    hoje_str = date.today().strftime('%Y-%m-%d')
    return render_template('calendario/aluno_responsavel.html',
                          mes=mes, ano=ano, eventos_por_data=eventos_por_data,
                          academia=academia, aluno=aluno, alunos=alunos,
                          hoje_str=hoje_str)


@bp_calendario.route('/sincronizar')
@login_required
def sincronizar():
    """Página de sincronização de eventos (feriados, PDF, turmas)."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        flash('Você não tem permissão para sincronizar eventos.', 'warning')
        return redirect(url_for('painel.home'))
    
    # Verifica se é gestor
    if not (current_user.has_role('admin') or current_user.has_role('gestor_federacao') or 
            current_user.has_role('gestor_associacao') or current_user.has_role('gestor_academia')):
        flash('Você não tem permissão para sincronizar eventos.', 'warning')
        return redirect(url_for('calendario.index'))
    
    # Busca histórico de sincronizações
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        cur.execute("""
            SELECT cs.*, u.nome as sincronizado_por_nome
            FROM calendario_sincronizacoes cs
            LEFT JOIN usuarios u ON u.id = cs.sincronizado_por_usuario_id
            WHERE cs.nivel = %s AND cs.nivel_id = %s
            ORDER BY cs.sincronizado_em DESC
            LIMIT 50
        """, (nivel, nivel_id))
        historico = cur.fetchall()
    except mysql.connector.errors.ProgrammingError:
        historico = []

    conflitos_pendentes = 0
    if nivel == 'academia':
        try:
            cur.execute(
                "SELECT COUNT(*) as c FROM conflitos_aula_feriado WHERE academia_id = %s AND status = 'pendente'",
                (nivel_id,)
            )
            r = cur.fetchone()
            conflitos_pendentes = (r.get('c') or 0) if r else 0
        except Exception:
            pass

    cur.close()
    conn.close()
    
    ano_atual = datetime.now().year
    return render_template('calendario/sincronizar.html',
                          nivel=nivel,
                          nivel_id=nivel_id,
                          historico=historico,
                          ano_atual=ano_atual,
                          conflitos_pendentes=conflitos_pendentes if nivel == 'academia' else 0)


@bp_calendario.route('/sincronizar/feriados', methods=['POST'])
@login_required
def sincronizar_feriados():
    """Sincroniza feriados nacionais do Brasil via API. Apenas federação e associação."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        return jsonify({'success': False, 'error': 'Permissão negada'}), 403
    
    if nivel == 'academia':
        flash('Academias não podem sincronizar feriados diretamente. Os eventos vêm do calendário da associação.', 'warning')
        return redirect(url_for('calendario.sincronizar'))
    
    ano = request.form.get('ano', type=int, default=datetime.now().year)
    
    eventos_criados, erro = _sincronizar_feriados_nacionais(ano, nivel, nivel_id)
    
    if erro:
        flash(f'Erro ao sincronizar feriados: {erro}', 'danger')
        return redirect(url_for('calendario.sincronizar'))
    
    # Detecta conflitos aula x feriado nas academias
    if nivel == 'associacao' and eventos_criados > 0:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (nivel_id,))
        for (acad_id,) in cur.fetchall():
            _detectar_conflitos_aula_feriado(acad_id, ano)
        cur.close()
        conn.close()
    
    # Registra sincronização
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO calendario_sincronizacoes
        (arquivo_nome, tipo_sincronizacao, nivel, nivel_id, eventos_criados, sincronizado_por_usuario_id)
        VALUES (%s, 'api', %s, %s, %s, %s)
    """, (f"Feriados {ano}", nivel, nivel_id, eventos_criados, current_user.id))
    conn.commit()
    cur.close()
    conn.close()
    
    if nivel == 'associacao' and eventos_criados > 0:
        flash(f'{eventos_criados} feriado(s) sincronizado(s) na associação e em todas as academias vinculadas!', 'success')
    else:
        flash(f'{eventos_criados} feriado(s) sincronizado(s) com sucesso!', 'success')
    return redirect(url_for('calendario.sincronizar'))


@bp_calendario.route('/sincronizar/turmas', methods=['POST'])
@login_required
def sincronizar_turmas():
    """Sincroniza turmas da academia como eventos recorrentes."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if nivel != 'academia':
        flash('Apenas gestores de academia podem sincronizar turmas.', 'warning')
        return redirect(url_for('calendario.sincronizar'))
    
    eventos_criados, erro = _sincronizar_turmas_como_eventos(nivel_id)
    
    if erro:
        flash(f'Erro ao sincronizar turmas: {erro}', 'danger')
        return redirect(url_for('calendario.sincronizar'))
    
    # Registra sincronização
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO calendario_sincronizacoes
        (arquivo_nome, tipo_sincronizacao, nivel, nivel_id, eventos_criados, sincronizado_por_usuario_id)
        VALUES ('Sincronização de Turmas', 'manual', %s, %s, %s, %s)
    """, (nivel, nivel_id, eventos_criados, current_user.id))
    conn.commit()
    cur.close()
    conn.close()
    
    flash(f'{eventos_criados} turma(s) sincronizada(s) como eventos recorrentes!', 'success')
    return redirect(url_for('calendario.sincronizar'))


def _sincronizar_eventos_da_sede(academia_id):
    """
    Sincroniza todos os eventos e feriados da associação (sede) para a academia.
    Eventos/feriados já existentes na academia (mesmo titulo, data_inicio, data_fim, tipo) são ignorados.
    Retorna (eventos_criados, erro).
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (academia_id,))
        row = cur.fetchone()
        if not row or not row.get("id_associacao"):
            return 0, "Academia não está vinculada a uma associação (sede)."
        id_associacao = row["id_associacao"]

        cur.execute("""
            SELECT id, titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim,
                   tipo, recorrente, dias_semana, feriado_nacional, origem_sincronizacao, cor
            FROM eventos
            WHERE nivel = 'associacao' AND nivel_id = %s AND status = 'ativo'
            ORDER BY data_inicio
        """, (id_associacao,))
        eventos_sede = cur.fetchall()

        eventos_criados = 0
        for ev in eventos_sede:
            titulo = ev.get("titulo") or ""
            data_inicio = ev.get("data_inicio")
            data_fim = ev.get("data_fim")
            tipo = ev.get("tipo") or "evento"
            if not titulo or not data_inicio:
                continue

            cur.execute("""
                SELECT id FROM eventos
                WHERE nivel = 'academia' AND nivel_id = %s AND status = 'ativo'
                  AND titulo = %s AND data_inicio = %s AND tipo = %s
                  AND ((data_fim IS NULL AND %s IS NULL) OR (data_fim <=> %s))
            """, (academia_id, titulo, data_inicio, tipo, data_fim, data_fim))
            if cur.fetchone():
                continue

            cur.execute("""
                INSERT INTO eventos
                (titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim,
                 tipo, recorrente, dias_semana, nivel, nivel_id, feriado_nacional,
                 origem_sincronizacao, evento_origem_id, criado_por_usuario_id, cor, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'academia', %s, %s, %s, %s, %s, %s, 'ativo')
            """, (
                titulo,
                ev.get("descricao"),
                data_inicio,
                data_fim,
                ev.get("hora_inicio"),
                ev.get("hora_fim"),
                tipo,
                ev.get("recorrente") or 0,
                ev.get("dias_semana"),
                academia_id,
                ev.get("feriado_nacional") or 0,
                "sede" if not ev.get("origem_sincronizacao") else ev.get("origem_sincronizacao"),
                ev.get("id"),
                current_user.id,
                ev.get("cor") or "#0d6efd",
            ))
            eventos_criados += 1

        conn.commit()
        cur.close()
        conn.close()
        return eventos_criados, None
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return 0, str(e)


@bp_calendario.route('/sincronizar/sede', methods=['POST'])
@login_required
def sincronizar_sede():
    """Sincroniza todos os eventos e feriados da associação (sede) para a academia."""
    nivel, nivel_id = _get_nivel_e_id_usuario()

    if nivel != 'academia':
        flash('Apenas academias podem sincronizar eventos da sede.', 'warning')
        return redirect(url_for('calendario.sincronizar'))

    eventos_criados, erro = _sincronizar_eventos_da_sede(nivel_id)

    if erro:
        flash(f'Erro ao sincronizar: {erro}', 'danger')
        return redirect(url_for('calendario.sincronizar'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO calendario_sincronizacoes
        (arquivo_nome, tipo_sincronizacao, nivel, nivel_id, eventos_criados, sincronizado_por_usuario_id)
        VALUES ('Eventos da Sede', 'manual', %s, %s, %s, %s)
    """, (nivel, nivel_id, eventos_criados, current_user.id))
    conn.commit()
    cur.close()
    conn.close()

    flash(f'{eventos_criados} evento(s)/feriado(s) sincronizado(s) da sede. Itens já existentes foram ignorados.', 'success')
    return redirect(url_for('calendario.sincronizar'))


MESES_ABREV = {'JAN': 1, 'FEV': 2, 'MAR': 3, 'ABR': 4, 'MAI': 5, 'JUN': 6,
               'JUL': 7, 'AGO': 8, 'SET': 9, 'OUT': 10, 'NOV': 11, 'DEZ': 12}


def _parsear_dias_evento(dia_str, mes_num, ano):
    """
    Converte string de dia(s) em lista de datas YYYY-MM-DD.
    Ex: "24" -> [2026-01-24], "01 e 02" -> [2026-02-01, 2026-02-02],
        "03 a 05" -> [2026-02-03, 2026-02-04, 2026-02-05],
        "31/10 a 01/11" -> [2026-10-31, 2026-11-01]
    """
    if not dia_str or not isinstance(dia_str, str):
        return []
    dia_str = dia_str.strip()
    if not dia_str or not dia_str[0].isdigit():
        return []
    
    datas = []
    
    # Formato "31/10 a 01/11" (intervalo entre meses)
    m_range = re.match(r'(\d{1,2})/(\d{1,2})\s+a\s+(\d{1,2})/(\d{1,2})', dia_str)
    if m_range:
        d1, m1, d2, m2 = int(m_range.group(1)), int(m_range.group(2)), int(m_range.group(3)), int(m_range.group(4))
        if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
            for d, m in [(d1, m1), (d2, m2)]:
                try:
                    dt = date(ano, m, d)
                    datas.append(dt.strftime('%Y-%m-%d'))
                except ValueError:
                    pass
        return datas
    
    # Formato "01 e 02" ou "22 e 23"
    m_e = re.match(r'(\d{1,2})\s+e\s+(\d{1,2})', dia_str)
    if m_e:
        d1, d2 = int(m_e.group(1)), int(m_e.group(2))
        for d in [d1, d2]:
            if 1 <= d <= 31:
                try:
                    dt = date(ano, mes_num, d)
                    datas.append(dt.strftime('%Y-%m-%d'))
                except ValueError:
                    pass
        return datas
    
    # Formato "03 a 05" ou "27 a 29" ou "14 a 16" ou "17 a 20"
    m_a = re.match(r'(\d{1,2})\s+a\s+(\d{1,2})', dia_str)
    if m_a:
        d1, d2 = int(m_a.group(1)), int(m_a.group(2))
        for d in range(min(d1, d2), max(d1, d2) + 1):
            if 1 <= d <= 31:
                try:
                    dt = date(ano, mes_num, d)
                    datas.append(dt.strftime('%Y-%m-%d'))
                except ValueError:
                    pass
        return datas
    
    # Dia único: "24", "31", "01", "07"
    m_single = re.match(r'^(\d{1,2})(?:\s|$|/)', dia_str)
    if m_single:
        d = int(m_single.group(1))
        if 1 <= d <= 31:
            try:
                dt = date(ano, mes_num, d)
                datas.append(dt.strftime('%Y-%m-%d'))
            except ValueError:
                pass
    return datas


def _extrair_eventos_tabela_pdf(pdf_file):
    """
    Extrai eventos de PDF com estrutura de tabela (MÊS | DIA | EVENTO | REALIZAÇÃO | LOCAL).
    Ex: Calendário FPJU.
    """
    try:
        import pdfplumber
    except ImportError:
        return []
    
    try:
        pdf_file.seek(0)
        with pdfplumber.open(pdf_file) as pdf:
            ano = date.today().year
            # Tenta inferir ano do documento (ex: "2026" no título)
            for page in pdf.pages[:2]:
                txt = page.extract_text() or ''
                m_ano = re.search(r'20[2-3][0-9]', txt)
                if m_ano:
                    ano = int(m_ano.group())
                    break
            
            mes_atual = None
            eventos = []
            vistos = set()
            
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    for row in table:
                        if not row or len(row) < 3:
                            continue
                        mes_cel, dia_cel, evento_cel = (row[0] or ''), (row[1] or ''), (row[2] or '')
                        
                        # Pula cabeçalhos
                        if mes_cel and ('MÊS' in str(mes_cel).upper() or 'DIA' in str(dia_cel).upper() or 'EVENTO' in str(evento_cel).upper()):
                            continue
                        if not evento_cel or len(str(evento_cel).strip()) < 3:
                            continue
                        
                        # Atualiza mês atual quando há nova célula de mês
                        if mes_cel and str(mes_cel).strip().upper() in MESES_ABREV:
                            mes_atual = MESES_ABREV[str(mes_cel).strip().upper()]
                        
                        if mes_atual is None:
                            continue
                        
                        titulo = re.sub(r'\s+', ' ', str(evento_cel).replace('\n', ' ')).strip()[:200]
                        if not titulo or titulo.lower() in ('evento', 'local', 'realização'):
                            continue
                        
                        datas = _parsear_dias_evento(str(dia_cel), mes_atual, ano)
                        
                        if not datas and dia_cel is None:
                            # Linha sem dia (ex: Workshop) - usa último dia conhecido da tabela
                            if eventos:
                                ultima_data = eventos[-1]['data_str']
                                datas = [ultima_data]
                        
                        for data_str in datas:
                            chave = (data_str, titulo[:60])
                            if chave not in vistos:
                                vistos.add(chave)
                                eventos.append({'data_str': data_str, 'titulo': titulo, 'linha_raw': f"{mes_cel} {dia_cel} {titulo}"})
            
            return eventos
    except Exception:
        return []


def _extrair_eventos_do_pdf(pdf_file):
    """
    Extrai texto do PDF e identifica possíveis eventos (data + título).
    Tenta primeiro extração por tabela (pdfplumber), depois por texto (pypdf).
    Retorna lista de dicts: [{'data_str': 'YYYY-MM-DD', 'titulo': str, 'linha_raw': str}, ...]
    """
    # 1) Tenta extração por tabela (calendários estruturados como FPJU)
    eventos_tabela = _extrair_eventos_tabela_pdf(pdf_file)
    if eventos_tabela:
        eventos_tabela.sort(key=lambda x: x['data_str'])
        return eventos_tabela, None
    
    # 2) Fallback: extração por texto
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], "Biblioteca pypdf não instalada. Execute: pip install pypdf"
    
    try:
        pdf_file.seek(0)
        reader = PdfReader(pdf_file)
        texto_completo = []
        for page in reader.pages:
            txt = page.extract_text()
            if txt:
                texto_completo.append(txt)
        
        texto = "\n".join(texto_completo)
        if not texto.strip():
            return [], "Nenhum texto encontrado no PDF."
    except Exception as e:
        return [], f"Erro ao ler PDF: {str(e)}"
    
    padrao_data_completa = re.compile(r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})\b', re.IGNORECASE)
    padrao_data_parcial = re.compile(r'(?<!\d)\b(\d{1,2})[/\-\.](\d{1,2})\b(?!\d)')
    meses_pt = {
        'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4, 'maio': 5, 'junho': 6,
        'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
    }
    padrao_data_extensa = re.compile(
        r'\b(\d{1,2})\s+de\s+(' + '|'.join(meses_pt.keys()) + r')(?:\s+de\s+(\d{2,4}))?\b',
        re.IGNORECASE
    )
    
    ano_atual = date.today().year
    m_ano = re.search(r'20[2-3][0-9]', texto)
    if m_ano:
        ano_atual = int(m_ano.group())
    
    eventos = []
    vistos = set()
    
    for linha in texto.split('\n'):
        linha = linha.strip()
        if not linha or len(linha) < 3:
            continue
        
        for m in padrao_data_completa.finditer(linha):
            dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if ano < 100:
                ano += 2000 if ano < 50 else 1900
            if 1 <= dia <= 31 and 1 <= mes <= 12 and 2020 <= ano <= 2030:
                data_str = f"{ano}-{mes:02d}-{dia:02d}"
                titulo = (linha[:m.start()].strip() or linha[m.end():].strip()).strip()
                titulo = re.sub(r'\s+', ' ', titulo)[:200] if titulo else f"Evento {data_str}"
                if titulo and len(titulo) > 2 and not re.match(r'^\d+[/\-\.]\d+', titulo):
                    chave = (data_str, titulo[:50])
                    if chave not in vistos:
                        vistos.add(chave)
                        eventos.append({'data_str': data_str, 'titulo': titulo, 'linha_raw': linha})
        
        for m in padrao_data_extensa.finditer(linha):
            dia = int(m.group(1))
            mes = meses_pt.get(m.group(2).lower(), 1)
            ano = int(m.group(3)) if m.group(3) else ano_atual
            if ano < 100:
                ano += 2000 if ano < 50 else 1900
            if 1 <= dia <= 31 and 1 <= mes <= 12:
                data_str = f"{ano}-{mes:02d}-{dia:02d}"
                titulo = (linha[:m.start()].strip() or linha[m.end():].strip()).strip()
                titulo = re.sub(r'\s+', ' ', titulo)[:200] if titulo else f"Evento {data_str}"
                if titulo and len(titulo) > 2:
                    chave = (data_str, titulo[:50])
                    if chave not in vistos:
                        vistos.add(chave)
                        eventos.append({'data_str': data_str, 'titulo': titulo, 'linha_raw': linha})
        
        for m in padrao_data_parcial.finditer(linha):
            dia, mes = int(m.group(1)), int(m.group(2))
            if 1 <= dia <= 31 and 1 <= mes <= 12:
                data_str = f"{ano_atual}-{mes:02d}-{dia:02d}"
                titulo = (linha[:m.start()].strip() or linha[m.end():].strip()).strip()
                titulo = re.sub(r'\s+', ' ', titulo)[:200] if titulo else f"Evento {data_str}"
                if titulo and len(titulo) > 2 and not re.match(r'^\d+[/\-\.]', titulo):
                    chave = (data_str, titulo[:50])
                    if chave not in vistos:
                        vistos.add(chave)
                        eventos.append({'data_str': data_str, 'titulo': titulo, 'linha_raw': linha})
    
    eventos.sort(key=lambda x: x['data_str'])
    return eventos, None


@bp_calendario.route('/sincronizar/pdf', methods=['GET', 'POST'])
@login_required
def sincronizar_pdf():
    """Upload de PDF e seleção de eventos para importar. Apenas federação e associação."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        flash('Você não tem permissão para sincronizar eventos.', 'warning')
        return redirect(url_for('painel.home'))
    
    if nivel == 'academia':
        flash('Academias não podem importar PDF. Os eventos vêm do calendário da associação e das turmas.', 'warning')
        return redirect(url_for('calendario.sincronizar'))
    
    if not (current_user.has_role('admin') or current_user.has_role('gestor_federacao') or 
            current_user.has_role('gestor_associacao') or current_user.has_role('gestor_academia')):
        flash('Você não tem permissão para sincronizar eventos.', 'warning')
        return redirect(url_for('calendario.sincronizar'))
    
    if request.method == 'POST':
        acao = request.form.get('acao')
        
        # Ação: processar PDF enviado
        if acao == 'upload' or acao is None:
            arquivo = request.files.get('arquivo_pdf')
            if not arquivo or arquivo.filename == '':
                flash('Selecione um arquivo PDF.', 'warning')
                return redirect(url_for('calendario.sincronizar_pdf'))
            
            if not arquivo.filename.lower().endswith('.pdf'):
                flash('O arquivo deve ser um PDF (.pdf).', 'warning')
                return redirect(url_for('calendario.sincronizar_pdf'))
            
            eventos, erro = _extrair_eventos_do_pdf(arquivo)
            
            if erro:
                flash(erro, 'danger')
                return redirect(url_for('calendario.sincronizar_pdf'))
            
            if not eventos:
                flash('Nenhum evento foi detectado no PDF. Verifique se o documento contém datas no formato dd/mm/aaaa, dd-mm-aaaa ou "dd de mês".', 'warning')
                return redirect(url_for('calendario.sincronizar_pdf'))
            
            arquivo_nome = arquivo.filename
            session['calendario_pdf_eventos'] = eventos
            session['calendario_pdf_nome'] = arquivo_nome
            
            return render_template('calendario/pdf_selecionar_eventos.html',
                                   eventos=eventos,
                                   arquivo_nome=arquivo_nome,
                                   nivel=nivel,
                                   nivel_id=nivel_id)
        
        # Ação: importar eventos selecionados
        if acao == 'importar':
            indices = request.form.getlist('evento_idx')
            if not indices:
                flash('Selecione pelo menos um evento para importar.', 'warning')
                eventos = session.get('calendario_pdf_eventos', [])
                arquivo_nome = session.get('calendario_pdf_nome', 'PDF')
                if eventos:
                    return render_template('calendario/pdf_selecionar_eventos.html',
                                           eventos=eventos,
                                           arquivo_nome=arquivo_nome,
                                           nivel=nivel,
                                           nivel_id=nivel_id)
                return redirect(url_for('calendario.sincronizar_pdf'))
            
            eventos = session.get('calendario_pdf_eventos', [])
            arquivo_nome = session.get('calendario_pdf_nome', 'PDF')
            
            if not eventos:
                flash('Sessão expirada. Faça o upload do PDF novamente.', 'warning')
                return redirect(url_for('calendario.sincronizar_pdf'))
            
            conn = get_db_connection()
            cur = conn.cursor()
            importados = 0
            
            try:
                # Se associação, busca academias vinculadas para sincronizar
                niveis_inserir = [(nivel, nivel_id)]
                if nivel == 'associacao':
                    cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (nivel_id,))
                    for (acad_id,) in cur.fetchall():
                        niveis_inserir.append(('academia', acad_id))
                
                for idx in indices:
                    try:
                        i = int(idx)
                        if 0 <= i < len(eventos):
                            ev = eventos[i]
                            for niv, niv_id in niveis_inserir:
                                cur.execute("""
                                    SELECT id FROM eventos
                                    WHERE titulo = %s AND data_inicio = %s AND nivel = %s AND nivel_id = %s
                                """, (ev['titulo'], ev['data_str'], niv, niv_id))
                                if cur.fetchone():
                                    continue
                                cur.execute("""
                                    INSERT INTO eventos
                                    (titulo, data_inicio, tipo, nivel, nivel_id, criado_por_usuario_id, origem_sincronizacao, cor)
                                    VALUES (%s, %s, 'evento', %s, %s, %s, 'pdf', '#6f42c1')
                                """, (ev['titulo'], ev['data_str'], niv, niv_id, current_user.id))
                                importados += 1
                    except (ValueError, IndexError):
                        continue
                
                cur.execute("""
                    INSERT INTO calendario_sincronizacoes
                    (arquivo_nome, tipo_sincronizacao, nivel, nivel_id, eventos_criados, sincronizado_por_usuario_id)
                    VALUES (%s, 'pdf', %s, %s, %s, %s)
                """, (arquivo_nome, nivel, nivel_id, importados, current_user.id))
                
                conn.commit()
                session.pop('calendario_pdf_eventos', None)
                session.pop('calendario_pdf_nome', None)
                if nivel == 'associacao' and importados > 0:
                    flash(f'{importados} evento(s) importado(s) e sincronizados na associação e em todas as academias vinculadas!', 'success')
                else:
                    flash(f'{importados} evento(s) importado(s) do calendário FPJU com sucesso!', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'Erro ao importar eventos: {str(e)}', 'danger')
            finally:
                cur.close()
                conn.close()
            
            return redirect(url_for('calendario.sincronizar'))
    
    return render_template('calendario/pdf_upload.html', nivel=nivel, nivel_id=nivel_id)


@bp_calendario.route('/conflitos')
@login_required
def conflitos_aula_feriado():
    """Lista conflitos (aula x feriado) pendentes para o gestor de academia resolver."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    if nivel != 'academia' or not nivel_id:
        flash('Acesso restrito aos gestores de academia.', 'warning')
        return redirect(url_for('painel.home'))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM academias WHERE id = %s", (nivel_id,))
    academia = cur.fetchone()
    cur.execute("""
        SELECT c.*, e.titulo as aula_titulo, e.hora_inicio, e.hora_fim
        FROM conflitos_aula_feriado c
        JOIN eventos e ON e.id = c.evento_id
        WHERE c.academia_id = %s AND c.status = 'pendente'
        ORDER BY c.data_conflito, e.hora_inicio
    """, (nivel_id,))
    conflitos = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('calendario/conflitos_aula_feriado.html',
                          conflitos=conflitos, academia=academia, nivel_id=nivel_id)


@bp_calendario.route('/conflitos/<int:conflito_id>/resolver', methods=['POST'])
@login_required
def resolver_conflito(conflito_id):
    """Resolve conflito: cancelar aula ou confirmar aula."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    if nivel != 'academia' or not nivel_id:
        flash('Acesso restrito.', 'warning')
        return redirect(url_for('painel.home'))

    acao = request.form.get('acao')  # cancelar | confirmar
    if acao not in ('cancelar', 'confirmar'):
        flash('Ação inválida.', 'warning')
        return redirect(url_for('calendario.conflitos_aula_feriado'))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT c.* FROM conflitos_aula_feriado c
        WHERE c.id = %s AND c.academia_id = %s AND c.status = 'pendente'
    """, (conflito_id, nivel_id))
    conflito = cur.fetchone()
    if not conflito:
        flash('Conflito não encontrado ou já resolvido.', 'warning')
        cur.close()
        conn.close()
        return redirect(url_for('calendario.conflitos_aula_feriado'))

    try:
        if acao == 'cancelar':
            cur.execute("SELECT id FROM eventos_excecoes WHERE evento_id = %s AND data_excecao = %s",
                        (conflito['evento_id'], conflito['data_conflito']))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO eventos_excecoes
                    (evento_id, data_excecao, tipo, motivo, criado_por_usuario_id)
                    VALUES (%s, %s, 'cancelamento', 'Conflito com feriado - cancelado pelo gestor', %s)
                """, (conflito['evento_id'], conflito['data_conflito'], current_user.id))
        cur.execute("""
            UPDATE conflitos_aula_feriado
            SET status = %s, resolvido_por_usuario_id = %s, resolvido_em = NOW()
            WHERE id = %s
        """, ('cancelado' if acao == 'cancelar' else 'confirmado', current_user.id, conflito_id))
        conn.commit()
        flash('Conflito resolvido com sucesso!' if acao == 'cancelar' else 'Aula confirmada para a data.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao resolver: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('calendario.conflitos_aula_feriado'))


@bp_calendario.route('/evento/novo', methods=['GET', 'POST'])
@login_required
def novo_evento():
    """Criar novo evento."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        flash('Você não tem permissão para criar eventos.', 'warning')
        return redirect(url_for('painel.home'))
    
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        data_inicio = request.form.get('data_inicio')
        data_fim = request.form.get('data_fim') or None
        hora_inicio = request.form.get('hora_inicio') or None
        hora_fim = request.form.get('hora_fim') or None
        tipo = request.form.get('tipo', 'evento')
        cor = request.form.get('cor', '#0d6efd')
        
        if not titulo or not data_inicio:
            flash('Título e data de início são obrigatórios.', 'warning')
            return redirect(url_for('calendario.novo_evento'))
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO eventos
                (titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim,
                 tipo, nivel, nivel_id, criado_por_usuario_id, cor)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim,
                  tipo, nivel, nivel_id, current_user.id, cor))
            
            evento_id = cur.lastrowid
            
            # Se for federação, cria aprovações para associações
            if nivel == 'federacao':
                cur.execute("SELECT id FROM associacoes WHERE id_federacao = %s", (nivel_id,))
                associacoes = cur.fetchall()
                for assoc in associacoes:
                    cur.execute("""
                        INSERT INTO eventos_aprovacoes
                        (evento_id, nivel_aprovador, nivel_aprovador_id)
                        VALUES (%s, 'associacao', %s)
                    """, (evento_id, assoc[0]))
            
            # Se for associação, cria aprovações para academias
            elif nivel == 'associacao':
                cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (nivel_id,))
                academias = cur.fetchall()
                for acad in academias:
                    cur.execute("""
                        INSERT INTO eventos_aprovacoes
                        (evento_id, nivel_aprovador, nivel_aprovador_id)
                        VALUES (%s, 'academia', %s)
                    """, (evento_id, acad[0]))
            
            conn.commit()
            flash('Evento criado com sucesso!', 'success')
            return redirect(url_for('calendario.visualizar', nivel=nivel, nivel_id=nivel_id))
        
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar evento: {str(e)}', 'danger')
        finally:
            cur.close()
            conn.close()
    
    return render_template('calendario/novo_evento.html', nivel=nivel, nivel_id=nivel_id)


@bp_calendario.route('/aprovacoes')
@login_required
def aprovacoes():
    """Lista de eventos pendentes de aprovação."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        flash('Você não tem permissão para aprovar eventos.', 'warning')
        return redirect(url_for('painel.home'))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Busca aprovações pendentes
        cur.execute("""
            SELECT ea.*, 
                   e.titulo, e.descricao, e.data_inicio, e.data_fim, 
                   e.hora_inicio, e.hora_fim, e.tipo, e.nivel as evento_nivel,
                   u.nome as criador_nome
            FROM eventos_aprovacoes ea
            JOIN eventos e ON e.id = ea.evento_id
            LEFT JOIN usuarios u ON u.id = e.criado_por_usuario_id
            WHERE ea.nivel_aprovador = %s AND ea.nivel_aprovador_id = %s
              AND ea.status = 'pendente'
            ORDER BY ea.criado_em DESC
        """, (nivel, nivel_id))
        aprovacoes_pendentes = cur.fetchall()
    except mysql.connector.errors.ProgrammingError:
        aprovacoes_pendentes = []
    
    cur.close()
    conn.close()
    
    return render_template('calendario/aprovacoes.html',
                          aprovacoes=aprovacoes_pendentes,
                          nivel=nivel,
                          nivel_id=nivel_id)


@bp_calendario.route('/aprovacoes/<int:aprovacao_id>/aprovar', methods=['POST'])
@login_required
def aprovar_evento(aprovacao_id):
    """Aprova um evento e replica para o nível da entidade."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        return jsonify({'success': False, 'error': 'Permissão negada'}), 403
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Busca aprovação
        cur.execute("""
            SELECT ea.*, e.*
            FROM eventos_aprovacoes ea
            JOIN eventos e ON e.id = ea.evento_id
            WHERE ea.id = %s AND ea.nivel_aprovador = %s AND ea.nivel_aprovador_id = %s
        """, (aprovacao_id, nivel, nivel_id))
        aprovacao = cur.fetchone()
        
        if not aprovacao:
            flash('Aprovação não encontrada.', 'warning')
            return redirect(url_for('calendario.aprovacoes'))
        
        # Atualiza aprovação
        cur.execute("""
            UPDATE eventos_aprovacoes
            SET status = 'aprovado', aprovado_em = NOW(), aprovado_por_usuario_id = %s
            WHERE id = %s
        """, (current_user.id, aprovacao_id))
        
        # Cria evento no calendário da entidade aprovadora (com evento_origem_id para cascata no cancelamento)
        evento_pai_id = aprovacao['evento_id']
        cur.execute("""
            INSERT INTO eventos
            (titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim,
             tipo, nivel, nivel_id, criado_por_usuario_id, cor, origem_sincronizacao, evento_origem_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'aprovacao', %s)
        """, (
            aprovacao['titulo'],
            aprovacao['descricao'],
            aprovacao['data_inicio'],
            aprovacao['data_fim'],
            aprovacao['hora_inicio'],
            aprovacao['hora_fim'],
            aprovacao['tipo'],
            nivel,
            nivel_id,
            current_user.id,
            aprovacao.get('cor', '#0d6efd'),
            evento_pai_id
        ))
        novo_evento_id = cur.lastrowid
        
        # Registra o evento criado na aprovação (para cascata no cancelamento via eventos_aprovacoes)
        try:
            cur.execute("""
                UPDATE eventos_aprovacoes SET evento_criado_id = %s WHERE id = %s
            """, (novo_evento_id, aprovacao_id))
        except Exception:
            pass  # Coluna pode não existir em migrações antigas
        
        conn.commit()
        flash('Evento aprovado e adicionado ao seu calendário!', 'success')
    
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao aprovar evento: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('calendario.aprovacoes'))


@bp_calendario.route('/aprovacoes/<int:aprovacao_id>/rejeitar', methods=['POST'])
@login_required
def rejeitar_evento(aprovacao_id):
    """Rejeita um evento."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        return jsonify({'success': False, 'error': 'Permissão negada'}), 403
    
    observacao = request.form.get('observacao', '').strip()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            UPDATE eventos_aprovacoes
            SET status = 'rejeitado', 
                rejeitado_em = NOW(), 
                rejeitado_por_usuario_id = %s,
                observacao = %s
            WHERE id = %s AND nivel_aprovador = %s AND nivel_aprovador_id = %s
        """, (current_user.id, observacao, aprovacao_id, nivel, nivel_id))
        
        conn.commit()
        flash('Evento rejeitado.', 'info')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao rejeitar evento: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('calendario.aprovacoes'))


@bp_calendario.route('/eventos')
@login_required
def lista_eventos():
    """Lista eventos do calendário para gestores (com opção de cancelar)."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        flash('Você não tem permissão para gerenciar eventos.', 'warning')
        return redirect(url_for('painel.home'))
    
    # Federação, associação, academia e professor podem listar/gerenciar
    modo = session.get('modo_painel', 'academia')
    if modo not in ('federacao', 'associacao', 'academia', 'professor'):
        flash('Acesso restrito.', 'warning')
        return redirect(url_for('painel.home'))
    
    mes = request.args.get('mes', type=int)
    ano = request.args.get('ano', type=int, default=datetime.now().year)
    filtro = request.args.get('filtro', 'ativos')  # ativos | cancelados | todos
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        where_status = ""
        params = [nivel, nivel_id]
        if filtro == 'ativos':
            where_status = " AND e.status = 'ativo'"
        elif filtro == 'cancelados':
            where_status = " AND e.status = 'cancelado'"
        
        where_extra = ""
        if mes and ano:
            where_extra = " AND MONTH(e.data_inicio) = %s AND YEAR(e.data_inicio) = %s"
            params.extend([mes, ano])
        elif ano:
            where_extra = " AND YEAR(e.data_inicio) = %s"
            params.append(ano)
        
        cur.execute(f"""
            SELECT e.id, e.titulo, e.descricao, e.data_inicio, e.data_fim,
                   e.hora_inicio, e.hora_fim, e.tipo, e.status, e.recorrente,
                   e.feriado_nacional, e.origem_sincronizacao, e.evento_origem_id,
                   t.Nome as turma_nome
            FROM eventos e
            LEFT JOIN turmas t ON t.TurmaID = e.turma_id
            WHERE e.nivel = %s AND e.nivel_id = %s {where_status} {where_extra}
            ORDER BY e.data_inicio DESC, e.hora_inicio
            LIMIT 200
        """, params)
        eventos = cur.fetchall()
        
        # Contexto (nome da fed/assoc/academia)
        contexto = {}
        if nivel == 'federacao':
            cur.execute("SELECT nome FROM federacoes WHERE id = %s", (nivel_id,))
            r = cur.fetchone()
            contexto = {'nome': r['nome'] if r else 'Federação'}
        elif nivel == 'associacao':
            cur.execute("SELECT nome FROM associacoes WHERE id = %s", (nivel_id,))
            r = cur.fetchone()
            contexto = {'nome': r['nome'] if r else 'Associação'}
        elif nivel == 'academia':
            cur.execute("SELECT nome FROM academias WHERE id = %s", (nivel_id,))
            r = cur.fetchone()
            contexto = {'nome': r['nome'] if r else 'Academia'}
    except mysql.connector.errors.ProgrammingError as e:
        eventos = []
        contexto = {'nome': ''}
    finally:
        cur.close()
        conn.close()
    
    return render_template('calendario/lista_eventos.html',
                          eventos=eventos, nivel=nivel, nivel_id=nivel_id,
                          contexto=contexto, mes=mes, ano=ano, filtro=filtro)


@bp_calendario.route('/evento/<int:evento_id>/cancelar', methods=['POST'])
@login_required
def cancelar_evento(evento_id):
    """Cancela evento e propaga para eventos derivados (academias que aderiram)."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        flash('Permissão negada.', 'warning')
        return redirect(url_for('painel.home'))
    
    motivo = request.form.get('motivo', '').strip()
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        cur.execute("SELECT id, titulo, nivel, nivel_id, status, feriado_nacional, tipo FROM eventos WHERE id = %s", (evento_id,))
        evento = cur.fetchone()
        
        if not evento:
            flash('Evento não encontrado.', 'warning')
            cur.close()
            conn.close()
            return redirect(url_for('calendario.lista_eventos'))
        
        if evento['nivel'] != nivel or evento['nivel_id'] != nivel_id:
            flash('Você não tem permissão para cancelar este evento.', 'warning')
            cur.close()
            conn.close()
            return redirect(url_for('calendario.lista_eventos'))
        
        if evento['status'] == 'cancelado':
            flash('Evento já está cancelado.', 'info')
            cur.close()
            conn.close()
            return redirect(url_for('calendario.lista_eventos'))
        
        if evento.get('feriado_nacional') or evento.get('tipo') == 'feriado':
            flash('Feriados nacionais não podem ser cancelados.', 'warning')
            cur.close()
            conn.close()
            return redirect(url_for('calendario.lista_eventos'))
        
        # Cancela em cascata: este evento + derivados (evento_origem_id) + eventos criados via aprovação
        ids_para_cancelar = [evento_id]
        processados = set()
        total_cancelados = 0
        
        # Inclui eventos criados por academias que aprovaram este evento (eventos_aprovacoes.evento_criado_id)
        try:
            cur.execute("""
                SELECT evento_criado_id as id FROM eventos_aprovacoes
                WHERE evento_id = %s AND status = 'aprovado' AND evento_criado_id IS NOT NULL
            """, (evento_id,))
            for row in cur.fetchall():
                if row['id']:
                    ids_para_cancelar.append(row['id'])
        except Exception:
            pass  # Coluna evento_criado_id pode não existir
        
        while ids_para_cancelar:
            eid = ids_para_cancelar.pop()
            if eid in processados:
                continue
            processados.add(eid)
            cur.execute("UPDATE eventos SET status = 'cancelado' WHERE id = %s AND status != 'cancelado'", (eid,))
            total_cancelados += cur.rowcount
            
            # Busca eventos derivados (criados por aprovação - evento_origem_id)
            cur.execute("SELECT id FROM eventos WHERE evento_origem_id = %s AND status = 'ativo'", (eid,))
            filhos = cur.fetchall()
            for r in filhos:
                if r['id'] and r['id'] not in processados:
                    ids_para_cancelar.append(r['id'])
        
        conn.commit()
        flash(f'Evento cancelado. {total_cancelados} registro(s) atualizado(s).', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao cancelar: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('calendario.lista_eventos'))


@bp_calendario.route('/evento/<int:evento_id>/excecao', methods=['GET', 'POST'])
@login_required
def criar_excecao(evento_id):
    """Cria exceção para evento recorrente (ex: cancelar aula em feriado)."""
    nivel, nivel_id = _get_nivel_e_id_usuario()
    
    if not nivel or not nivel_id:
        flash('Você não tem permissão para criar exceções.', 'warning')
        return redirect(url_for('painel.home'))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    # Busca evento
    cur.execute("SELECT * FROM eventos WHERE id = %s", (evento_id,))
    evento = cur.fetchone()
    
    if not evento or evento['nivel'] != nivel or evento['nivel_id'] != nivel_id:
        flash('Evento não encontrado.', 'warning')
        cur.close()
        conn.close()
        return redirect(url_for('calendario.index'))
    
    if request.method == 'POST':
        data_excecao = request.form.get('data_excecao')
        tipo = request.form.get('tipo', 'cancelamento')
        motivo = request.form.get('motivo', '').strip()
        nova_hora_inicio = request.form.get('nova_hora_inicio') or None
        nova_hora_fim = request.form.get('nova_hora_fim') or None
        
        if not data_excecao:
            flash('Data da exceção é obrigatória.', 'warning')
            return redirect(url_for('calendario.criar_excecao', evento_id=evento_id))
        
        try:
            cur.execute("""
                INSERT INTO eventos_excecoes
                (evento_id, data_excecao, tipo, motivo, nova_hora_inicio, nova_hora_fim, criado_por_usuario_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (evento_id, data_excecao, tipo, motivo, nova_hora_inicio, nova_hora_fim, current_user.id))
            
            conn.commit()
            flash('Exceção criada com sucesso!', 'success')
            return redirect(url_for('calendario.visualizar', nivel=nivel, nivel_id=nivel_id))
        
        except mysql.connector.errors.IntegrityError:
            flash('Já existe uma exceção para esta data.', 'warning')
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar exceção: {str(e)}', 'danger')
    
    cur.close()
    conn.close()
    
    return render_template('calendario/criar_excecao.html', evento=evento, nivel=nivel, nivel_id=nivel_id)
