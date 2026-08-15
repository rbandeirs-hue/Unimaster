# -*- coding: utf-8 -*-
"""
Blueprint Eventos e Competições — inscrições com formulário, adesão por academia.
Visível em modo associação e academia.
"""
import json
import os
import secrets
import uuid
from collections import defaultdict
from datetime import datetime, date
from io import BytesIO
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    session,
    Response,
    jsonify,
    send_file,
    current_app,
    abort,
)
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room
from werkzeug.utils import secure_filename
from extensions import csrf
from config import get_db_connection, DatabaseUnavailableError
from utils.formularios_campos import CAMPOS_ALUNO_PADRAO, listar_campos_por_grupo, get_label

# Import socketio de forma segura (evita import circular)
_socketio_instance = None
_lutas_ativas_registry = {}  # Registry para evitar import circular

def get_socketio():
    """Retorna instância do SocketIO do app principal."""
    global _socketio_instance
    if _socketio_instance is None:
        from flask import current_app
        # Buscar socketio do contexto da aplicação
        if hasattr(current_app, 'extensions') and 'socketio' in current_app.extensions:
            _socketio_instance = current_app.extensions['socketio']
        else:
            # Fallback: importar diretamente (pode causar import circular em alguns casos)
            try:
                from app import socketio as _si
                _socketio_instance = _si
            except ImportError:
                # Se não conseguir importar, retornar None (WebSocket não funcionará)
                return None
    return _socketio_instance

def registrar_luta_ativa(luta_id):
    """Registra uma luta como ativa para receber broadcast periódico."""
    _lutas_ativas_registry[luta_id] = True
    print(f"📝 Luta {luta_id} registrada como ativa. Total: {len(_lutas_ativas_registry)}")
    # Notificar thread de broadcast se existir
    try:
        from app import iniciar_broadcast_periodico
        iniciar_broadcast_periodico()
    except Exception as e:
        print(f"⚠️ Erro ao iniciar broadcast: {e}")

def remover_luta_ativa(luta_id):
    """Remove uma luta da lista de ativas."""
    _lutas_ativas_registry.pop(luta_id, None)


# Monitor por área: chave "evento_id_area_num" -> luta_id ativa ou None (espera)
_placar_monitor_luta_por_area = {}


def _area_key(evento_id, area_num):
    return f"{int(evento_id)}_{int(area_num)}"


def _room_placar_area(evento_id, area_num):
    return f"placar_area_{int(evento_id)}_{int(area_num)}"


def _luta_area_num(luta_row):
    try:
        return max(1, int(luta_row.get("area_num") or 1))
    except (TypeError, ValueError):
        return 1


def _proxima_luta_id_na_area(cur, evento_id, area_num, luta_id_atual):
    """Próxima luta na mesma área (ordem de id)."""
    try:
        cur.execute(
            """
            SELECT id FROM judo_lutas
            WHERE evento_id = %s AND COALESCE(area_num, 1) = %s
            ORDER BY id ASC
            """,
            (evento_id, area_num),
        )
        ids = [row["id"] for row in cur.fetchall()]
    except Exception:
        cur.execute(
            "SELECT id FROM judo_lutas WHERE evento_id = %s ORDER BY id ASC",
            (evento_id,),
        )
        ids = [row["id"] for row in cur.fetchall()]
    if not ids:
        return None
    try:
        idx = ids.index(luta_id_atual)
    except ValueError:
        return ids[0]
    if idx + 1 < len(ids):
        return ids[idx + 1]
    return None


def _serializar_luta_socket(luta_dict):
    d = dict(luta_dict)
    for key, value in list(d.items()):
        if isinstance(value, datetime):
            d[key] = value.isoformat() if value else None
    return d


def _enriquecer_meta_luta(cur, luta_id, estado_dict):
    if not estado_dict:
        return
    try:
        cur.execute(
            """
            SELECT ec.nome AS evento_nome, c.nome_categoria AS categoria_nome
            FROM judo_lutas jl
            INNER JOIN eventos_competicoes ec ON ec.id = jl.evento_id
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.id = %s
            """,
            (luta_id,),
        )
        meta = cur.fetchone()
        if meta:
            estado_dict["evento_nome"] = meta.get("evento_nome")
            estado_dict["categoria_nome"] = meta.get("categoria_nome")
    except Exception:
        pass


def _emit_placar_monitor_standby(evento_id, area_num, mensagem=None):
    """Monitor entra em modo de espera entre lutas."""
    socketio_instance = get_socketio()
    if not socketio_instance:
        return
    key = _area_key(evento_id, area_num)
    _placar_monitor_luta_por_area[key] = None
    try:
        socketio_instance.emit(
            "placar_monitor_area",
            {
                "evento_id": int(evento_id),
                "area_num": int(area_num),
                "modo": "standby",
                "mensagem": mensagem or "Aguardando próxima luta",
            },
            room=_room_placar_area(evento_id, area_num),
        )
    except Exception as e:
        current_app.logger.warning(f"emit standby área: {e}")


def _emit_placar_monitor_luta_na_area(evento_id, area_num, luta_id, luta_estado, cur=None):
    """TV da área exibe esta luta (atletas e placar)."""
    if not luta_estado:
        return
    socketio_instance = get_socketio()
    if not socketio_instance:
        return
    key = _area_key(evento_id, area_num)
    _placar_monitor_luta_por_area[key] = luta_id
    if cur:
        _enriquecer_meta_luta(cur, luta_id, luta_estado)
    try:
        payload = {
            "evento_id": int(evento_id),
            "area_num": int(area_num),
            "modo": "luta",
            "luta_id": luta_id,
            "luta": _serializar_luta_socket(luta_estado),
        }
        socketio_instance.emit(
            "placar_monitor_area",
            payload,
            room=_room_placar_area(evento_id, area_num),
        )
    except Exception as e:
        current_app.logger.warning(f"emit luta área: {e}")


def _resolver_luta_monitor_area(cur, evento_id, area_num):
    """Luta em foco na TV da área; None = espera."""
    key = _area_key(evento_id, area_num)
    lid = _placar_monitor_luta_por_area.get(key)
    if lid:
        try:
            cur.execute(
                """
                SELECT jl.id FROM judo_lutas jl
                WHERE jl.id = %s AND jl.evento_id = %s AND COALESCE(jl.area_num, 1) = %s
                """,
                (lid, evento_id, area_num),
            )
        except Exception:
            cur.execute(
                "SELECT jl.id FROM judo_lutas jl WHERE jl.id = %s AND jl.evento_id = %s",
                (lid, evento_id),
            )
        if cur.fetchone():
            return lid
    return None


def _sincronizar_monitor_area_apos_finalizacao(cur, luta_id_finalizada, luta_atualizada):
    """
    Ao finalizar: monitor da área vai para espera. Retorna próxima luta (mesma área) para redirecionar o controle.
    """
    if not luta_atualizada or luta_atualizada.get("status") != "finalizada":
        return None
    evento_id = luta_atualizada.get("evento_id")
    if not evento_id:
        return None
    area_num = _luta_area_num(luta_atualizada)
    _emit_placar_monitor_standby(evento_id, area_num)
    return _proxima_luta_id_na_area(cur, evento_id, area_num, luta_id_finalizada)


def _evento_placar_num_areas(cur, evento_id):
    try:
        cur.execute(
            "SELECT COALESCE(placar_num_areas, 1) AS n FROM eventos_competicoes WHERE id = %s",
            (evento_id,),
        )
        r = cur.fetchone()
        n = int(r["n"]) if r and r.get("n") is not None else 1
    except Exception:
        n = 1
    return max(1, min(n, 50))


def _normalize_placar_controle_modelo(val):
    """Formulário: livre, unimaster (Controle 1), martialmatch (Controle 2)."""
    v = _as_texto_mysql(val) if val is not None else None
    v = (v or "").strip().lower()
    if v in ("unimaster", "controle1", "controle_1", "c1"):
        return "unimaster"
    if v in ("martialmatch", "controle2", "controle_2", "c2"):
        return "martialmatch"
    if v == "livre":
        return "livre"
    return "livre"


def _fetch_placar_controle_modelo_evento(cur, evento_id):
    try:
        cur.execute(
            "SELECT placar_controle_modelo FROM eventos_competicoes WHERE id = %s",
            (evento_id,),
        )
        row = cur.fetchone()
        if row and row.get("placar_controle_modelo") is not None:
            return _normalize_placar_controle_modelo(row["placar_controle_modelo"])
    except Exception as ex:
        err = str(ex).lower()
        if "placar_controle_modelo" not in err and "1054" not in err and "unknown column" not in err:
            raise
    return "livre"


def _try_update_placar_controle_modelo(cur, evento_id, id_associacao, modelo):
    m = _normalize_placar_controle_modelo(modelo)
    try:
        cur.execute(
            "UPDATE eventos_competicoes SET placar_controle_modelo = %s WHERE id = %s AND id_associacao = %s",
            (m, evento_id, id_associacao),
        )
        return True
    except Exception as ex:
        err = str(ex).lower()
        if "placar_controle_modelo" in err or "1054" in err or "unknown column" in err:
            return False
        raise


def _monitor_luta_shell_standby(evento_nome, area_num, tempo_padrao=300):
    """Estado visual inicial do monitor em espera (LUTA_ID=0 no cliente; sem polling de API)."""
    return {
        "id": 0,
        "evento_nome": evento_nome or "",
        "categoria_nome": "",
        "atleta_branco_nome": "—",
        "atleta_azul_nome": "—",
        "atleta_branco_academia": None,
        "atleta_azul_academia": None,
        "tempo_restante_segundos": tempo_padrao,
        "tempo_total_segundos": tempo_padrao,
        "golden_score_ativado": False,
        "tempo_golden_score_segundos": 0,
        "status": "aguardando",
        "pontos_branco_ippon": 0,
        "pontos_branco_wazaari": 0,
        "pontos_branco_yoko": 0,
        "pontos_branco_shido": 0,
        "pontos_azul_ippon": 0,
        "pontos_azul_wazaari": 0,
        "pontos_azul_yoko": 0,
        "pontos_azul_shido": 0,
        "pontos_branco_hansokumake": 0,
        "pontos_azul_hansokumake": 0,
        "vencedor": None,
        "tipo_vitoria": None,
    }


# Compat: redirecionamentos antigos
def _definir_monitor_luta_do_evento(evento_id, luta_id):
    _placar_monitor_luta_por_area[_area_key(evento_id, 1)] = luta_id


def _emit_placar_monitor_evento(evento_id, luta_id, luta_estado):
    """Deprecated: use área 1."""
    _emit_placar_monitor_luta_na_area(evento_id, 1, luta_id, luta_estado, cur=None)


bp_eventos_competicoes = Blueprint("eventos_competicoes", __name__, url_prefix="/eventos-competicoes")

UPLOAD_ANEXOS = "eventos_anexos"
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'gif', 'zip', 'rar', 'txt'}


# ============================================================
# 🥋 FUNÇÕES HELPER PARA PLACAR DE JUDÔ (Backend como fonte de verdade)
# ============================================================

def calcular_tempo_restante(luta):
    """
    Calcula tempo restante baseado em timestamps (BACKEND É A ÚNICA FONTE DE VERDADE).
    
    Args:
        luta: dict com dados da luta do banco
        
    Returns:
        dict com tempo_restante_segundos calculado (NÃO altera status se já está finalizada ou aguardando)
    """
    from datetime import datetime
    
    if not luta:
        return None
    
    status = luta.get("status", "aguardando")
    tempo_total = luta.get("tempo_total_segundos", 300)
    elapsed_time = luta.get("elapsed_time", 0) or 0
    started_at = luta.get("started_at")
    paused_at = luta.get("paused_at")
    golden_score_ativado = luta.get("golden_score_ativado", 0)
    
    # IMPORTANTE: Se já está finalizada ou cancelada, não calcular nada, apenas retornar valores do banco
    if status in ["finalizada", "cancelada"]:
        tempo_restante = luta.get("tempo_restante_segundos", 0)
        return {
            "tempo_restante_segundos": tempo_restante,
            "elapsed_time": elapsed_time
        }
    
    # Se está aguardando, retornar tempo inicial (não calcular)
    if status == "aguardando":
        tempo_restante = luta.get("tempo_restante_segundos", tempo_total)
        # Garantir que tempo_restante não seja negativo ou zero para lutas aguardando
        if tempo_restante <= 0:
            tempo_restante = tempo_total
        return {
            "tempo_restante_segundos": tempo_restante,
            "elapsed_time": 0  # Resetar elapsed_time se está aguardando
        }
    
    # Golden Score - tempo CRESCENTE (obrigatório checar ANTES do tempo normal)
    # Se golden_score_ativado, nunca usar tempo_restante_segundos; calcular tempo_golden_score_segundos
    if golden_score_ativado and status in ("em_andamento", "pausada"):
        tempo_golden_score = int(luta.get("tempo_golden_score_segundos", 0) or 0)
        golden_score_started_at_raw = luta.get("golden_score_started_at")
        golden_score_elapsed_time = tempo_golden_score  # fallback
        
        def parse_dt(val):
            if val is None:
                return None
            if hasattr(val, 'strftime'):
                return val
            if isinstance(val, str):
                s = val.split('.')[0].replace('T', ' ')
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                    try:
                        return datetime.strptime(s.strip(), fmt)
                    except ValueError:
                        continue
            return None
        
        golden_score_started_at = parse_dt(golden_score_started_at_raw)
        
        if golden_score_started_at:
            try:
                if paused_at:
                    paused_at_dt = parse_dt(paused_at)
                    if paused_at_dt:
                        tempo_golden_score = max(0, int((paused_at_dt - golden_score_started_at).total_seconds()))
                else:
                    agora = datetime.now()
                    tempo_golden_score = max(0, int((agora - golden_score_started_at).total_seconds()))
            except Exception as e:
                current_app.logger.warning(f"Erro ao calcular tempo golden score: {e}")
                tempo_golden_score = golden_score_elapsed_time
        
        return {
            "tempo_restante_segundos": 0,
            "tempo_golden_score_segundos": tempo_golden_score,
            "golden_score_ativado": True
        }
    
    # Tempo normal (regressivo) - só quando NÃO está em Golden Score
    if status == "em_andamento" and started_at is not None:
        def _parse_started(val):
            if val is None:
                return None
            if hasattr(val, 'strftime'):
                return val
            if isinstance(val, str):
                s = val.split('.')[0].replace('T', ' ').strip()
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                    try:
                        return datetime.strptime(s, fmt)
                    except ValueError:
                        continue
            return None
        started_at_parsed = _parse_started(started_at)
        
        if started_at_parsed:
            agora = datetime.now()
            tempo_decorrido_agora_float = (agora - started_at_parsed).total_seconds()
            tempo_total_decorrido_float = elapsed_time + tempo_decorrido_agora_float
            tempo_restante_float = tempo_total - tempo_total_decorrido_float
            
            # Verificar se tempo acabou - broadcast periódico detectará e ativará golden score automaticamente
            # Considerar "acabou" quando <= 2.0 para evitar travar em 0:01 (broadcast a cada 1s; janela maior garante trigger)
            if tempo_restante_float <= 0:
                return {
                    "tempo_restante_segundos": 0,
                    "elapsed_time": tempo_total
                }
            if tempo_restante_float <= 2.0:
                return {
                    "tempo_restante_segundos": 0,
                    "elapsed_time": tempo_total
                }
            tempo_restante = int(tempo_restante_float)
            return {
                "tempo_restante_segundos": max(0, tempo_restante),
                "elapsed_time": elapsed_time
            }
        else:
            # Se não tem started_at mas status é em_andamento, algo está errado
            # Retornar tempo do banco
            tempo_restante = luta.get("tempo_restante_segundos", tempo_total)
            return {
                "tempo_restante_segundos": tempo_restante,
                "elapsed_time": elapsed_time
            }
    
    # Fallback: retornar valores do banco sem alterar status
    tempo_restante = luta.get("tempo_restante_segundos", tempo_total)
    if tempo_restante <= 0 and status != "finalizada":
        tempo_restante = tempo_total
    return {
        "tempo_restante_segundos": tempo_restante,
        "elapsed_time": elapsed_time
    }


def obter_estado_luta_completo(luta_id):
    """
    Busca luta do banco e retorna estado completo com tempo calculado EM TEMPO REAL.
    BACKEND É A ÚNICA FONTE DE VERDADE - calcula tempo baseado em timestamps.
    IMPORTANTE: Não altera o status da luta no banco, apenas calcula tempo para exibição.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM judo_lutas WHERE id = %s", (luta_id,))
        luta = cur.fetchone()
        
        if not luta:
            return None
        
        # Guardar status original do banco
        status_original = luta.get("status", "aguardando")
        
        # CALCULAR TEMPO RESTANTE EM TEMPO REAL (backend é relógio)
        tempo_calculado = calcular_tempo_restante(luta)
        
        # Atualizar luta com tempo calculado (mas manter status original)
        if tempo_calculado:
            luta.update(tempo_calculado)
            # Garantir que status não seja alterado pelo cálculo
            luta["status"] = status_original
        
        # Osaekomi: tempo decorrido da imobilização (10s = waza-ari, 20s = ippon)
        if luta.get("osaekomi_ativo") and luta.get("osaekomi_started_at"):
            try:
                from datetime import datetime
                started = luta["osaekomi_started_at"]
                if isinstance(started, str):
                    started = datetime.strptime(started.split(".")[0], "%Y-%m-%d %H:%M:%S")
                luta["osaekomi_elapsed_seconds"] = int((datetime.now() - started).total_seconds())
            except Exception:
                luta["osaekomi_elapsed_seconds"] = 0
        else:
            luta["osaekomi_elapsed_seconds"] = 0
        
        return luta
    finally:
        cur.close()
        conn.close()


def aplicar_fim_de_tempo(luta_id):
    """
    Ao acabar o tempo (em_andamento e tempo_restante <= 0):
    - SÓ ativa Golden Score se os DOIS lados estiverem com 0 pontuação.
    - Se alguém pontuou: relógio para e a luta termina (vencedor por pontos ou empate).
    Regras (como no script de referência):
    - score_b == 0 e score_a == 0 → Golden Score.
    - Caso contrário → finaliza (vencedor por score ou empate).
    """
    luta = obter_estado_luta_completo(luta_id)
    if not luta:
        return None
    
    status = luta.get("status", "aguardando")
    tempo_restante = int(luta.get("tempo_restante_segundos", 300))
    golden_score_ja_ativo = bool(luta.get("golden_score_ativado"))
    
    # Se Golden Score JÁ está ativo, não reativar (evita loop infinito)
    if golden_score_ja_ativo:
        return luta
    
    if status != "em_andamento" or tempo_restante > 0:
        return luta
    
    # Pontos atuais (incluindo yoko para "zerado")
    ippon_b = int(luta.get("pontos_branco_ippon", 0) or 0)
    wazaari_b = int(luta.get("pontos_branco_wazaari", 0) or 0)
    yoko_b = int(luta.get("pontos_branco_yoko", 0) or 0)
    ippon_a = int(luta.get("pontos_azul_ippon", 0) or 0)
    wazaari_a = int(luta.get("pontos_azul_wazaari", 0) or 0)
    yoko_a = int(luta.get("pontos_azul_yoko", 0) or 0)
    
    # Critério de vitória: 1 ippon = 2 waza-ari
    score_b = ippon_b * 2 + wazaari_b
    score_a = ippon_a * 2 + wazaari_a
    
    # Zerado = nenhuma pontuação (ippon, wazaari, yoko) em ambos
    total_b = ippon_b + wazaari_b + yoko_b
    total_a = ippon_a + wazaari_a + yoko_a
    ambos_zerados = (total_b == 0 and total_a == 0)
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if score_b > score_a:
            # Branco vence
            tipo = "ippon" if ippon_b >= 1 else "wazaari"
            cur.execute("""
                UPDATE judo_lutas
                SET status = 'finalizada',
                    vencedor = 'branco',
                    tipo_vitoria = %s,
                    finalizada_em = NOW(),
                    tempo_restante_segundos = 0
                WHERE id = %s AND status = 'em_andamento'
            """, (tipo, luta_id))
            conn.commit()
            remover_luta_ativa(luta_id)
            current_app.logger.info(f"⏱️ Tempo esgotado luta {luta_id} – Branco vence por pontuação")
            return obter_estado_luta_completo(luta_id)
        
        if score_a > score_b:
            # Azul vence
            tipo = "ippon" if ippon_a >= 1 else "wazaari"
            cur.execute("""
                UPDATE judo_lutas
                SET status = 'finalizada',
                    vencedor = 'azul',
                    tipo_vitoria = %s,
                    finalizada_em = NOW(),
                    tempo_restante_segundos = 0
                WHERE id = %s AND status = 'em_andamento'
            """, (tipo, luta_id))
            conn.commit()
            remover_luta_ativa(luta_id)
            current_app.logger.info(f"⏱️ Tempo esgotado luta {luta_id} – Azul vence por pontuação")
            return obter_estado_luta_completo(luta_id)
        
        if not ambos_zerados:
            # Empate com pontuação: alguém pontuou → luta termina (empate por tempo, sem Golden Score)
            current_app.logger.info(f"⏱️ Tempo esgotado luta {luta_id} – Empate (houve pontuação, sem Golden Score)")
            cur.execute("""
                UPDATE judo_lutas
                SET status = 'finalizada',
                    vencedor = 'empate',
                    tipo_vitoria = NULL,
                    finalizada_em = NOW(),
                    tempo_restante_segundos = 0
                WHERE id = %s AND status = 'em_andamento'
            """, (luta_id,))
            conn.commit()
            remover_luta_ativa(luta_id)
            return obter_estado_luta_completo(luta_id)
        
        # Ambos zerados: ativar Golden Score (status continua em_andamento; ENUM não tem 'golden_score')
        current_app.logger.info(f"⏱️ Tempo acabou luta {luta_id} – Ambos 0 pontos → Golden Score ativado")
        cur.execute("""
            UPDATE judo_lutas
            SET golden_score_ativado = 1,
                golden_score_started_at = NOW(),
                tempo_restante_segundos = 0,
                tempo_golden_score_segundos = 0
            WHERE id = %s AND status = 'em_andamento'
        """, (luta_id,))
        conn.commit()
        registrar_luta_ativa(luta_id)
        luta_atualizada = obter_estado_luta_completo(luta_id)
        if luta_atualizada:
            broadcast_estado_luta(luta_id)
        return luta_atualizada
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro ao aplicar fim de tempo (luta {luta_id}): {e}")
        return luta
    finally:
        cur.close()
        conn.close()


def aplicar_osaekomi_yuko(luta_id):
    """Concede 1 yuko ao lado que aplica osaekomi (10-14s). Uma vez apenas.
    No Golden Score, qualquer pontuação finaliza a luta (regra oficial)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM judo_lutas WHERE id = %s FOR UPDATE", (luta_id,))
        luta = cur.fetchone()
        if not luta or not luta.get("osaekomi_ativo") or luta.get("osaekomi_yuko_concedido"):
            return None
        lado = (luta.get("osaekomi_lado") or "").strip().lower()
        golden_score = bool(luta.get("golden_score_ativado"))
        if lado == "branco":
            novo = (luta.get("pontos_branco_yoko") or 0) + 1
            if golden_score:
                cur.execute("""
                    UPDATE judo_lutas SET pontos_branco_yoko = %s, osaekomi_yuko_concedido = 1,
                        status = 'finalizada', vencedor = 'branco', tipo_vitoria = 'golden_score',
                        finalizada_em = NOW(), osaekomi_ativo = 0, osaekomi_lado = NULL,
                        osaekomi_started_at = NULL, osaekomi_wazaari_concedido = 0
                    WHERE id = %s
                """, (novo, luta_id))
                remover_luta_ativa(luta_id)
            else:
                cur.execute(
                    "UPDATE judo_lutas SET pontos_branco_yoko = %s, osaekomi_yuko_concedido = 1 WHERE id = %s",
                    (novo, luta_id),
                )
        elif lado == "azul":
            novo = (luta.get("pontos_azul_yoko") or 0) + 1
            if golden_score:
                cur.execute("""
                    UPDATE judo_lutas SET pontos_azul_yoko = %s, osaekomi_yuko_concedido = 1,
                        status = 'finalizada', vencedor = 'azul', tipo_vitoria = 'golden_score',
                        finalizada_em = NOW(), osaekomi_ativo = 0, osaekomi_lado = NULL,
                        osaekomi_started_at = NULL, osaekomi_wazaari_concedido = 0
                    WHERE id = %s
                """, (novo, luta_id))
                remover_luta_ativa(luta_id)
            else:
                cur.execute(
                    "UPDATE judo_lutas SET pontos_azul_yoko = %s, osaekomi_yuko_concedido = 1 WHERE id = %s",
                    (novo, luta_id),
                )
        else:
            return None
        # Registrar log para permitir desfazer (última ação precisa estar no log)
        try:
            id_op = luta.get("id_operador")
            cur.execute("""
                INSERT INTO judo_placar_logs (luta_id, acao, detalhes, id_usuario)
                VALUES (%s, %s, %s, %s)
            """, (luta_id, f"yoko_{lado}", json.dumps({"fonte": "osaekomi", "golden_score": golden_score}), id_op))
        except Exception as log_err:
            current_app.logger.warning(f"Erro ao registrar log osaekomi_yuko: {log_err}")
        conn.commit()
        current_app.logger.info(f"Osaekomi 10-14s luta {luta_id}: yuko para {lado}" + (" – Golden Score, luta finalizada" if golden_score else ""))
        return obter_estado_luta_completo(luta_id)
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro aplicar_osaekomi_yuko luta {luta_id}: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def aplicar_osaekomi_wazaari(luta_id):
    """Concede 1 waza-ari ao lado que aplica osaekomi (15-19s). Uma vez apenas.
    No Golden Score, qualquer pontuação finaliza a luta (regra oficial)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM judo_lutas WHERE id = %s FOR UPDATE", (luta_id,))
        luta = cur.fetchone()
        if not luta or not luta.get("osaekomi_ativo") or luta.get("osaekomi_wazaari_concedido"):
            return None
        lado = (luta.get("osaekomi_lado") or "").strip().lower()
        golden_score = bool(luta.get("golden_score_ativado"))
        if lado == "branco":
            novo = (luta.get("pontos_branco_wazaari") or 0) + 1
            if golden_score:
                cur.execute("""
                    UPDATE judo_lutas SET pontos_branco_wazaari = %s, osaekomi_wazaari_concedido = 1,
                        status = 'finalizada', vencedor = 'branco', tipo_vitoria = 'golden_score',
                        finalizada_em = NOW(), osaekomi_ativo = 0, osaekomi_lado = NULL,
                        osaekomi_started_at = NULL, osaekomi_yuko_concedido = 0
                    WHERE id = %s
                """, (novo, luta_id))
                remover_luta_ativa(luta_id)
            else:
                if novo >= 2:
                    cur.execute(
                        """
                        UPDATE judo_lutas SET pontos_branco_wazaari = 0, pontos_branco_ippon = 1, osaekomi_wazaari_concedido = 1,
                            status = 'finalizada', vencedor = 'branco', tipo_vitoria = 'ippon',
                            finalizada_em = NOW(), osaekomi_ativo = 0, osaekomi_lado = NULL,
                            osaekomi_started_at = NULL, osaekomi_yuko_concedido = 0
                        WHERE id = %s
                        """,
                        (luta_id,),
                    )
                    remover_luta_ativa(luta_id)
                else:
                    cur.execute(
                        "UPDATE judo_lutas SET pontos_branco_wazaari = %s, osaekomi_wazaari_concedido = 1 WHERE id = %s",
                        (novo, luta_id),
                    )
        elif lado == "azul":
            novo = (luta.get("pontos_azul_wazaari") or 0) + 1
            if golden_score:
                cur.execute("""
                    UPDATE judo_lutas SET pontos_azul_wazaari = %s, osaekomi_wazaari_concedido = 1,
                        status = 'finalizada', vencedor = 'azul', tipo_vitoria = 'golden_score',
                        finalizada_em = NOW(), osaekomi_ativo = 0, osaekomi_lado = NULL,
                        osaekomi_started_at = NULL, osaekomi_yuko_concedido = 0
                    WHERE id = %s
                """, (novo, luta_id))
                remover_luta_ativa(luta_id)
            else:
                if novo >= 2:
                    cur.execute(
                        """
                        UPDATE judo_lutas SET pontos_azul_wazaari = 0, pontos_azul_ippon = 1, osaekomi_wazaari_concedido = 1,
                            status = 'finalizada', vencedor = 'azul', tipo_vitoria = 'ippon',
                            finalizada_em = NOW(), osaekomi_ativo = 0, osaekomi_lado = NULL,
                            osaekomi_started_at = NULL, osaekomi_yuko_concedido = 0
                        WHERE id = %s
                        """,
                        (luta_id,),
                    )
                    remover_luta_ativa(luta_id)
                else:
                    cur.execute(
                        "UPDATE judo_lutas SET pontos_azul_wazaari = %s, osaekomi_wazaari_concedido = 1 WHERE id = %s",
                        (novo, luta_id),
                    )
        else:
            return None
        # Registrar log para permitir desfazer (última ação precisa estar no log)
        try:
            id_op = luta.get("id_operador")
            cur.execute("""
                INSERT INTO judo_placar_logs (luta_id, acao, detalhes, id_usuario)
                VALUES (%s, %s, %s, %s)
            """, (luta_id, f"wazaari_{lado}", json.dumps({"fonte": "osaekomi", "golden_score": golden_score}), id_op))
        except Exception as log_err:
            current_app.logger.warning(f"Erro ao registrar log osaekomi_wazaari: {log_err}")
        conn.commit()
        current_app.logger.info(f"Osaekomi 15-19s luta {luta_id}: waza-ari para {lado}" + (" – Golden Score, luta finalizada" if golden_score else ""))
        return obter_estado_luta_completo(luta_id)
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro aplicar_osaekomi_wazaari luta {luta_id}: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def aplicar_osaekomi_ippon(luta_id):
    """Concede ippon ao lado que aplica osaekomi (aos 20s) e finaliza a luta."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM judo_lutas WHERE id = %s FOR UPDATE", (luta_id,))
        luta = cur.fetchone()
        if not luta or not luta.get("osaekomi_ativo"):
            return None
        lado = (luta.get("osaekomi_lado") or "").strip().lower()
        if lado not in ("branco", "azul"):
            return None
        if lado == "branco":
            cur.execute("""
                UPDATE judo_lutas
                SET status = 'finalizada', vencedor = 'branco', tipo_vitoria = 'ippon',
                    finalizada_em = NOW(), pontos_branco_ippon = 1,
                    osaekomi_ativo = 0, osaekomi_lado = NULL, osaekomi_started_at = NULL,
                    osaekomi_wazaari_concedido = 0, osaekomi_yuko_concedido = 0
                WHERE id = %s
            """, (luta_id,))
        else:
            cur.execute("""
                UPDATE judo_lutas
                SET status = 'finalizada', vencedor = 'azul', tipo_vitoria = 'ippon',
                    finalizada_em = NOW(), pontos_azul_ippon = 1,
                    osaekomi_ativo = 0, osaekomi_lado = NULL, osaekomi_started_at = NULL,
                    osaekomi_wazaari_concedido = 0, osaekomi_yuko_concedido = 0
                WHERE id = %s
            """, (luta_id,))
        # Registrar log para permitir desfazer (última ação precisa estar no log)
        try:
            id_op = luta.get("id_operador")
            cur.execute("""
                INSERT INTO judo_placar_logs (luta_id, acao, detalhes, id_usuario)
                VALUES (%s, %s, %s, %s)
            """, (luta_id, f"ippon_{lado}", json.dumps({"fonte": "osaekomi"}), id_op))
        except Exception as log_err:
            current_app.logger.warning(f"Erro ao registrar log osaekomi_ippon: {log_err}")
        conn.commit()
        remover_luta_ativa(luta_id)
        current_app.logger.info(f"Osaekomi 20s luta {luta_id}: ippon para {lado}, luta finalizada")
        return obter_estado_luta_completo(luta_id)
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Erro aplicar_osaekomi_ippon luta {luta_id}: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def broadcast_estado_luta(luta_id):
    """
    Envia estado completo da luta para todos os clientes conectados na sala.
    """
    from datetime import datetime
    luta = obter_estado_luta_completo(luta_id)
    if not luta:
        return
    
    # Converter campos datetime para strings (JSON serializable)
    luta_serializada = dict(luta)
    for key, value in luta_serializada.items():
        if isinstance(value, datetime):
            luta_serializada[key] = value.isoformat() if value else None
    
    socketio_instance = get_socketio()
    if socketio_instance:
        try:
            socketio_instance.emit("placar_atualizado", luta_serializada, room=f"luta_{luta_id}")
        except Exception as e:
            print(f"Erro ao fazer broadcast: {e}")


def _allowed_file(filename):
    """Verifica se a extensão do arquivo é permitida."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _salvar_anexo_evento(file_storage, evento_id):
    """Salva anexo de evento em static/uploads/eventos_anexos/ — valida magic bytes."""
    from utils.upload_seguro import validar_upload, nome_seguro, UploadInvalido
    if not file_storage or not file_storage.filename:
        return None
    try:
        ext = validar_upload(
            file_storage,
            extensoes_extras={"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "gif", "txt"},
        )
    except UploadInvalido:
        return None

    filename_original = secure_filename(file_storage.filename)
    filename_safe = nome_seguro(f"evento_{evento_id}", ext)
    
    folder = os.path.join(current_app.root_path, "static", "uploads", UPLOAD_ANEXOS)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename_safe)
    
    try:
        file_storage.save(filepath)
        tamanho = os.path.getsize(filepath)
        return {
            "nome_original": filename_original,
            "caminho": filename_safe,
            "tamanho": tamanho,
            "tipo_mime": file_storage.content_type or "application/octet-stream"
        }
    except Exception as e:
        current_app.logger.error(f"Erro ao salvar anexo: {e}")
        return None


def _ids_academias_associacao(cursor, id_associacao):
    """Retorna ids das academias da associação."""
    cursor.execute("SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome", (id_associacao,))
    return [r["id"] for r in cursor.fetchall()]


def _evento_encerrado(ev):
    """True se data_fim já passou."""
    if not ev or not ev.get("data_fim"):
        return False
    df = ev["data_fim"]
    if hasattr(df, "replace"):
        try:
            df = datetime.strptime(df[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return False
    return datetime.now() > df


def _tipo_calendario_para_sinc(tipo_ec, natureza_ec):
    """
    Sincronização com tabela `eventos` (calendário): competição festival
    aparece como tipo 'evento', para não tratar como competição oficial.
    """
    if tipo_ec != "competicao":
        return "evento"
    n = natureza_ec or "oficial"
    if n == "festival":
        return "evento"
    return "competicao"


def _url_lista_eventos_competicoes(tipo_filtro=None, academia_id=None):
    """URL da lista conforme o menu: eventos gerais, competições ou visão completa."""
    kwargs = {}
    if academia_id is not None:
        kwargs["academia_id"] = academia_id
    if tipo_filtro == "evento":
        return url_for("eventos_competicoes.lista_eventos", **kwargs)
    if tipo_filtro == "competicao":
        return url_for("eventos_competicoes.lista_competicoes", **kwargs)
    return url_for("eventos_competicoes.lista", **kwargs)


def _url_hub_competicao(evento_id):
    """Painel de opções da competição (hub de navegação no modo associação)."""
    return url_for("eventos_competicoes.painel_competicao", evento_id=evento_id)


def _academia_anchor_inscricao_avulsa(cur, evento_id):
    """Academia usada como âncora FK para inscrições sem aluno cadastrado (link/planilha)."""
    cur.execute(
        """
        SELECT ea.academia_id FROM eventos_competicoes_adesao ea
        WHERE ea.evento_id = %s AND ea.aderiu = 1 ORDER BY ea.academia_id LIMIT 1
        """,
        (evento_id,),
    )
    r = cur.fetchone()
    if r:
        return r["academia_id"]
    cur.execute(
        """
        SELECT ac.id FROM academias ac
        INNER JOIN eventos_competicoes ec ON ec.id_associacao = ac.id_associacao
        WHERE ec.id = %s ORDER BY ac.nome LIMIT 1
        """,
        (evento_id,),
    )
    r2 = cur.fetchone()
    return r2["id"] if r2 else None


def _parse_data_nascimento_avulso(val):
    """Normaliza para YYYY-MM-DD ou retorna None."""
    if val is None:
        return None
    if hasattr(val, "strftime"):
        try:
            return val.strftime("%Y-%m-%d")
        except Exception:
            return None
    s = str(val).strip()
    if not s:
        return None
    if "/" in s[:11]:
        try:
            partes = s[:10].split("/")
            if len(partes) == 3:
                return f"{int(partes[2]):04d}-{int(partes[1]):02d}-{int(partes[0]):02d}"
        except Exception:
            return None
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    return None


def _mysql_int_opcional_aprox(val):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8", errors="replace").strip()
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(str(val).replace(",", ".")))
        except (TypeError, ValueError):
            return None


def _mysql_float_opcional_aprox(val):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8", errors="replace").strip()
    try:
        return float(str(val).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _mysql_texto_aprox(val):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="replace").strip()
    if isinstance(val, str):
        return val.strip()
    return str(val).strip()


def _linha_aproxima_ao_atleta(row, ano_nasc, genero_u, peso_f):
    """Regras em eventos_competicoes_categorias_aprox; NULL = não restringe."""
    gn = _mysql_int_opcional_aprox(row.get("ano_nasc_min"))
    gx = _mysql_int_opcional_aprox(row.get("ano_nasc_max"))
    if gn is not None and ano_nasc is not None and ano_nasc < gn:
        return False
    if gx is not None and ano_nasc is not None and ano_nasc > gx:
        return False
    g_rule = (_mysql_texto_aprox(row.get("genero_aprox")) or "A").upper()
    if g_rule not in ("A", ""):
        u = (genero_u or "").upper()
        if g_rule == "M" and u != "M":
            return False
        if g_rule == "F" and u != "F":
            return False
        if g_rule == "O" and u != "O":
            return False
    pmn = _mysql_float_opcional_aprox(row.get("peso_min_kg"))
    pmx = _mysql_float_opcional_aprox(row.get("peso_max_kg"))
    if pmn is not None and peso_f < pmn:
        return False
    if pmx is not None and peso_f > pmx:
        return False
    return True


def _normalizar_sexo_planilha(val):
    """M/F/O a partir de célula de planilha (M, Masculino, etc.)."""
    s = str(val or "").strip().upper()
    if not s:
        return None
    if len(s) == 1 and s in "MFO":
        return s
    if s.startswith("MASC") or s == "HOMEM" or s == "MALE":
        return "M"
    if s.startswith("FEM") or s == "MULHER" or s == "FEMALE":
        return "F"
    if s.startswith("OUT") or s == "NB" or s == "NON-BINARY":
        return "O"
    return None


def _sexo_mfo_para_aprox(val):
    """M, F ou O para cálculo de categoria por aproximação (formulário ou JSON legado)."""
    s = _normalizar_sexo_planilha(val)
    if s in ("M", "F", "O"):
        return s
    u = (str(val or "").strip().upper()[:1])
    return u if u in ("M", "F", "O") else ""


def _categoria_aprox_para_atleta(cur, evento_id, data_nasc_raw, genero, peso_raw):
    """Primeira categoria (por ordem) compatível com nascimento, sexo e peso."""
    data_iso = _parse_data_nascimento_avulso(data_nasc_raw)
    if not data_iso or len(data_iso) < 4:
        return None, None
    try:
        ano_nasc = int(data_iso[:4])
    except (TypeError, ValueError):
        return None, None
    try:
        peso_f = float(str(peso_raw).strip().replace(",", ".")) if peso_raw not in (None, "") else None
    except (TypeError, ValueError):
        return None, None
    if peso_f is None or peso_f <= 0:
        return None, None
    genero_u = _sexo_mfo_para_aprox(genero)
    if genero_u not in ("M", "F", "O"):
        return None, None
    rows = []
    try:
        cur.execute(
            """
            SELECT id, nome, ordem, ano_nasc_min, ano_nasc_max, genero_aprox, peso_min_kg, peso_max_kg
            FROM eventos_competicoes_categorias_aprox
            WHERE evento_id = %s
            ORDER BY ordem ASC, id ASC
            """,
            (evento_id,),
        )
        rows = cur.fetchall()
    except Exception as ex:
        current_app.logger.warning(
            "categorias_aprox colunas estendidas indisponíveis (migração?): %s", ex
        )
        try:
            cur.execute(
                """
                SELECT id, nome, ordem
                FROM eventos_competicoes_categorias_aprox
                WHERE evento_id = %s
                ORDER BY ordem ASC, id ASC
                """,
                (evento_id,),
            )
            rows = cur.fetchall()
        except Exception:
            return None, None
    for r in rows:
        if _linha_aproxima_ao_atleta(r, ano_nasc, genero_u, peso_f):
            nome = _mysql_texto_aprox(r.get("nome")) or ""
            if not nome:
                nome = "Faixa #%s" % (r.get("id"),)
            return (nome, r.get("id"))
    return None, None


def _dados_form_inscricao_como_dict(raw):
    """Parse de dados_form (JSON string, dict, bytes do MySQL ou JSON duplo-encoded)."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            raw = bytes(raw).decode("utf-8", errors="replace")
        except Exception:
            return {}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            obj = json.loads(s)
        except Exception:
            return {}
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, str):
            try:
                obj2 = json.loads(obj.strip())
                return obj2 if isinstance(obj2, dict) else {}
            except Exception:
                return {}
        return {}
    return {}


def _data_bruta_para_aprox(val):
    if val is None:
        return None
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    return s if s else None


def _sexo_para_aprox_inscricao(dados, aluno_row):
    if not isinstance(dados, dict):
        dados = {}
    for k in ("sexo", "genero", "gênero", "genero_aluno", "Genero"):
        s = _sexo_mfo_para_aprox(dados.get(k))
        if s:
            return s
    if aluno_row and aluno_row.get("sexo") is not None:
        return _sexo_mfo_para_aprox(aluno_row.get("sexo"))
    return ""


def _dados_obter_nascimento_aprox(dados, aluno_row):
    """Primeira data de nascimento encontrada no JSON (várias chaves possíveis) ou no cadastro do aluno."""
    if not isinstance(dados, dict):
        dados = {}
    for k in (
        "data_nascimento",
        "dataNascimento",
        "data_nasc",
        "nascimento",
        "dt_nascimento",
        "dn",
        "data de nascimento",
    ):
        v = dados.get(k)
        if v is not None and str(v).strip() not in ("", "None", "null", "undefined"):
            return v
    if aluno_row:
        return aluno_row.get("data_nascimento")
    return None


def _dados_obter_peso_bruto_aprox(dados, aluno_row):
    """Peso em kg no JSON (várias chaves) ou cadastro do aluno."""
    if not isinstance(dados, dict):
        dados = {}
    for k in ("peso", "peso_kg", "pesoKg", "weight", "peso (kg)", "Peso"):
        v = dados.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        try:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                if float(v) > 0:
                    return v
            else:
                s = str(v).strip().replace(",", ".")
                if s and float(s) > 0:
                    return v
        except (TypeError, ValueError):
            continue
    if aluno_row is not None and aluno_row.get("peso") not in (None, ""):
        return aluno_row.get("peso")
    return None


def _recalcular_todas_inscricoes_categorias_aprox(cur, evento_id):
    """
    Atualiza dados_form.categoria e categoria_aprox_id para todas as inscrições do evento.
    Usa dados do JSON e, se houver aluno_id, completa com data_nascimento, sexo e peso do cadastro.
    Retorna (n_linhas_alteradas_no_banco, n_inscricoes_sem_categoria_apos).
    """
    cur.execute(
        """
        SELECT id, aluno_id, dados_form
        FROM eventos_competicoes_inscricoes
        WHERE evento_id = %s
        """,
        (evento_id,),
    )
    inscricoes = cur.fetchall()
    aluno_cache = {}
    n_updates = 0
    n_sem_cat = 0

    for ins in inscricoes:
        dados = _dados_form_inscricao_como_dict(ins.get("dados_form"))
        aluno_row = None
        aid = ins.get("aluno_id")
        if aid:
            if aid not in aluno_cache:
                cur.execute(
                    "SELECT data_nascimento, sexo, peso FROM alunos WHERE id = %s LIMIT 1",
                    (aid,),
                )
                aluno_cache[aid] = cur.fetchone()
            aluno_row = aluno_cache.get(aid)

        data_raw = _dados_obter_nascimento_aprox(dados, aluno_row)
        if data_raw is not None:
            data_raw = _data_bruta_para_aprox(data_raw)
        genero = _sexo_para_aprox_inscricao(dados, aluno_row)
        peso_raw = _dados_obter_peso_bruto_aprox(dados, aluno_row)

        cn, ci = _categoria_aprox_para_atleta(cur, evento_id, data_raw, genero, peso_raw)
        if not cn:
            n_sem_cat += 1
            if dados.get("categoria") is not None or dados.get("categoria_aprox_id") is not None:
                dados.pop("categoria", None)
                dados.pop("categoria_aprox_id", None)
                cur.execute(
                    "UPDATE eventos_competicoes_inscricoes SET dados_form = %s WHERE id = %s",
                    (json.dumps(dados, ensure_ascii=False), ins["id"]),
                )
                n_updates += 1
            continue

        # Gravar no JSON data ISO, sexo e peso efetivos do cálculo (inclui complemento pelo cadastro do aluno).
        di = _parse_data_nascimento_avulso(data_raw)
        if di:
            dados["data_nascimento"] = di
        if genero in ("M", "F", "O"):
            dados["sexo"] = genero
        try:
            pf = float(str(peso_raw).strip().replace(",", ".")) if peso_raw not in (None, "") else None
            if pf is not None and pf > 0:
                dados["peso"] = pf
        except (TypeError, ValueError):
            pass

        ci_int = int(ci) if ci is not None else None
        dados["categoria"] = cn
        dados["categoria_aprox_id"] = ci_int
        cur.execute(
            "UPDATE eventos_competicoes_inscricoes SET dados_form = %s WHERE id = %s",
            (json.dumps(dados, ensure_ascii=False), ins["id"]),
        )
        n_updates += 1

    return n_updates, n_sem_cat


def _fetch_inscricoes_consolidar_associacao(cur, evento_id, id_assoc):
    """
    Inscrições enviadas do evento cuja academia pertence à associação.
    Não exige linha em eventos_competicoes_adesao nem aderiu=1 (avulsos podem usar só a FK âncora).
    """
    cur.execute(
        """
        SELECT i.id, i.academia_id, i.aluno_id, i.dados_form, i.inclusao_avulsa,
               ac.nome AS academia_nome, a.nome AS aluno_nome
        FROM eventos_competicoes_inscricoes i
        INNER JOIN academias ac ON ac.id = i.academia_id
        LEFT JOIN alunos a ON a.id = i.aluno_id
        WHERE i.evento_id = %s AND i.status = 'enviada' AND ac.id_associacao = %s
        ORDER BY ac.nome, COALESCE(a.nome, '')
        """,
        (evento_id, id_assoc),
    )
    # Completa com o cadastro do aluno o que a inscrição não capturou.
    return _completar_dados_form_com_aluno(cur, cur.fetchall())


def _agrupar_inscricoes_por_academia_categoria(inscricoes):
    """Monta academias_com_inscricoes a partir das linhas (cria cada academia ao encontrar a primeira inscrição)."""
    academias_com_inscricoes = {}
    for insc in inscricoes:
        try:
            academia_id = insc.get("academia_id")
            if not academia_id:
                continue
            dados_form_str = insc.get("dados_form")
            if dados_form_str:
                try:
                    if isinstance(dados_form_str, str):
                        dados = json.loads(dados_form_str)
                    else:
                        dados = dados_form_str
                except (json.JSONDecodeError, TypeError):
                    dados = {}
            else:
                dados = {}
            categoria = dados.get("categoria") or "Sem categoria"
            if academia_id not in academias_com_inscricoes:
                nome_ac = (insc.get("academia_nome") or "").strip()
                academias_com_inscricoes[academia_id] = {
                    "academia_nome": nome_ac or f"Academia #{academia_id}",
                    "categorias": {},
                }
            if categoria not in academias_com_inscricoes[academia_id]["categorias"]:
                academias_com_inscricoes[academia_id]["categorias"][categoria] = []
            # Origem do atleta para a associação: "Academia - Local de treino".
            # O local só é acrescentado quando difere do nome da academia (o
            # fallback grava o próprio nome da academia quando não há local).
            nome_ac = (insc.get("academia_nome") or "").strip()
            local = (dados.get("local_treino") or "").strip()
            if local and local.lower() != nome_ac.lower():
                origem = f"{nome_ac} - {local}" if nome_ac else local
            else:
                origem = nome_ac
            academias_com_inscricoes[academia_id]["categorias"][categoria].append(
                {
                    "id": insc.get("id"),
                    "academia_id": insc.get("academia_id"),
                    "aluno_id": insc.get("aluno_id"),
                    "aluno_nome": insc.get("aluno_nome") or "Avulso",
                    "academia_nome": nome_ac,
                    "origem": origem,
                    "dados_form": dados,
                }
            )
        except Exception as e:
            current_app.logger.error("Agrupar inscrição %s: %s", insc.get("id"), e)
            continue
    return academias_com_inscricoes


# Inscrição avulsa / link público grava chaves fixas em dados_form; o evento pode não ter id_formulario ou formulário sem linhas.
_CAMPOS_DADOS_AVULSO_ORDEM = [
    ("nome", None),
    ("data_nascimento", None),
    ("sexo", None),
    ("peso", None),
    ("categoria", None),
    ("professor", "Professor"),
    ("local_treino", "Local de treino"),
]
_CHAVES_DADOS_IGNORAR_COLUNA = frozenset(
    {"categoria_aprox_id", "professor_id", "id_academia_escolhida", "origem_inscricao"}
)
_CHAVES_PADRAO_AVULSO = frozenset(k for k, _ in _CAMPOS_DADOS_AVULSO_ORDEM)


def _merge_campos_form_faltantes_padrao_avulso(campos_list):
    """
    Acrescenta nome, data_nascimento, sexo, peso, etc. se o formulário do evento não os tiver
    (consolidar / impressão / edição passam a exibir sexo e demais dados da inscrição avulsa).
    """
    if not campos_list:
        return campos_list
    chaves = {c.get("campo_chave") for c in campos_list if c.get("campo_chave")}
    try:
        ordem_max = max(int(c.get("ordem") or 0) for c in campos_list)
    except (TypeError, ValueError):
        ordem_max = len(campos_list)
    out = list(campos_list)
    for chave, label_fixo in _CAMPOS_DADOS_AVULSO_ORDEM:
        if chave in chaves:
            continue
        ordem_max += 1
        lbl = label_fixo if label_fixo else get_label(chave)
        out.append({"campo_chave": chave, "label": lbl, "ordem": ordem_max})
        chaves.add(chave)
    return out


def _campos_form_efetivos_para_inscricoes(cur, id_formulario, inscricoes_rows):
    """
    Campos do formulário do evento; se não houver, monta colunas a partir das chaves em dados_form
    (consolidar / editar inscrição avulsa sem formulário cadastrado).
    """
    campos = []
    try:
        fid = int(id_formulario) if id_formulario else 0
    except (TypeError, ValueError):
        fid = 0
    if fid:
        try:
            cur.execute(
                "SELECT campo_chave, label, obrigatorio, ordem FROM formularios_campos WHERE formulario_id = %s ORDER BY ordem",
                (fid,),
            )
            campos = cur.fetchall()
        except Exception:
            campos = []
    if campos:
        return _merge_campos_form_faltantes_padrao_avulso(campos)

    union = set()
    for row in inscricoes_rows or []:
        if not isinstance(row, dict):
            continue
        d = _dados_form_inscricao_como_dict(row.get("dados_form"))
        union.update(d.keys())

    # Sempre listar colunas padrão (inclui sexo), mesmo vazio no JSON — facilita ver/editar no consolidar.
    out = []
    ordem = 0
    for chave, label_fixo in _CAMPOS_DADOS_AVULSO_ORDEM:
        lbl = label_fixo if label_fixo else get_label(chave)
        out.append({"campo_chave": chave, "label": lbl, "ordem": ordem})
        ordem += 1
    for chave in sorted(k for k in union if k not in _CHAVES_PADRAO_AVULSO and k not in _CHAVES_DADOS_IGNORAR_COLUNA):
        out.append({"campo_chave": chave, "label": get_label(chave), "ordem": ordem})
        ordem += 1
    return out


def _normalizar_inscricao_modo(modo_form, tipo_ec):
    if tipo_ec != "competicao":
        return "academias_formulario"
    if modo_form in ("academias_formulario", "publico_avulso", "misto"):
        return modo_form
    return "academias_formulario"


def _modo_aceita_inscricao_publica(modo):
    return modo in ("publico_avulso", "misto")


def _compute_inscricao_modo_e_token(tipo_ec, modo_form, token_atual=None, regenerar=False):
    """Calcula (modo, token) sem gravar no banco. token None = sem link público."""
    modo = _normalizar_inscricao_modo(modo_form, tipo_ec)
    token = None
    if tipo_ec == "competicao" and _modo_aceita_inscricao_publica(modo):
        raw = token_atual
        if raw is not None and not isinstance(raw, str):
            raw = str(raw)
        token = (raw or "").strip() or None
        if regenerar or not token:
            token = secrets.token_urlsafe(24)
    return modo, token


def _as_texto_mysql(val):
    """Evita comparações Jinja quebradas com bytes vindos do MySQL."""
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="replace").strip()
    if isinstance(val, str):
        return val.strip()
    return str(val)


def _aplicar_modo_e_token_inscricao(cur, evento_id, tipo_ec, modo_form, token_atual=None, regenerar=False):
    """Persiste inscricao_modo e token (ou NULL). Retorna (modo, token_efetivo, sucesso_no_banco)."""
    modo, token = _compute_inscricao_modo_e_token(tipo_ec, modo_form, token_atual, regenerar)
    try:
        cur.execute(
            """
            UPDATE eventos_competicoes
            SET inscricao_modo = %s, public_inscricao_token = %s
            WHERE id = %s
            """,
            (modo, token, evento_id),
        )
        return modo, token, True
    except Exception as ex:
        current_app.logger.warning("inscricao_modo/token não gravados (migração?): %s", ex)
        return modo, token_atual, False


def _lista_academias_adesao_evento(cur, evento_id, id_assoc):
    """Academias da associação com flag de adesão ao evento."""
    cur.execute(
        """
        SELECT ac.id, ac.nome, COALESCE(ea.aderiu, 0) AS aderiu
        FROM academias ac
        LEFT JOIN eventos_competicoes_adesao ea
          ON ea.academia_id = ac.id AND ea.evento_id = %s
        WHERE ac.id_associacao = %s
        ORDER BY ac.nome
        """,
        (evento_id, id_assoc),
    )
    return cur.fetchall()


def _ids_academias_aderentes_evento(cur, evento_id):
    cur.execute(
        """
        SELECT academia_id FROM eventos_competicoes_adesao
        WHERE evento_id = %s AND aderiu = 1
        """,
        (evento_id,),
    )
    return {int(r["academia_id"]) for r in cur.fetchall()}


def _professores_associacao_para_link(cur, id_assoc):
    cur.execute(
        """
        SELECT p.id, p.nome, p.id_academia, ac.nome AS academia_nome
        FROM professores p
        LEFT JOIN academias ac ON ac.id = p.id_academia
        WHERE p.id_associacao = %s AND p.ativo = 1 AND p.status = 'ativo'
        ORDER BY COALESCE(ac.nome, ''), p.nome
        """,
        (id_assoc,),
    )
    return cur.fetchall()


def _professores_responsavel_por_academia_para_link(cur, id_assoc, academias_permitidas=None):
    """
    Um registro por academia com o RESPONSÁVEL (gestor) da academia como professor.

    `academias_permitidas`: quando informado (conjunto de ids), só entram essas
    academias — usado para mostrar link só das que aderiram ao evento.
    """
    cur.execute(
        """
        SELECT p.id, p.nome, p.id_academia, p.usuario_id,
               ac.nome AS academia_nome, ac.responsavel AS academia_responsavel,
               u.nome AS usuario_nome
        FROM professores p
        LEFT JOIN academias ac ON ac.id = p.id_academia
        LEFT JOIN usuarios u ON u.id = p.usuario_id
        WHERE p.id_associacao = %s AND p.ativo = 1 AND p.status = 'ativo'
        ORDER BY COALESCE(ac.nome, ''), p.nome
        """,
        (id_assoc,),
    )
    rows = cur.fetchall()
    if not rows:
        return []

    def _norm(v):
        import unicodedata
        nfd = unicodedata.normalize("NFD", (v or "").strip())
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()

    gestor_uid_por_academia = {}
    try:
        cur.execute(
            """
            SELECT DISTINCT ua.academia_id, ua.usuario_id
            FROM usuarios_academias ua
            INNER JOIN roles_usuario ru ON ru.usuario_id = ua.usuario_id
            INNER JOIN roles r ON r.id = ru.role_id
            INNER JOIN academias ac ON ac.id = ua.academia_id AND ac.id_associacao = %s
            WHERE (
                r.chave = 'gestor_academia'
                OR r.nome = 'Gestor Academia'
                OR LOWER(REPLACE(COALESCE(r.chave, ''), ' ', '_')) = 'gestor_academia'
            )
            """,
            (id_assoc,),
        )
        for g in cur.fetchall():
            aid = g.get("academia_id")
            uid = g.get("usuario_id")
            if aid is None or uid is None:
                continue
            aid_i = int(aid)
            if aid_i not in gestor_uid_por_academia:
                gestor_uid_por_academia[aid_i] = int(uid)
    except Exception:
        gestor_uid_por_academia = {}

    prof_uid_por_academia = {}
    try:
        cur.execute(
            """
            SELECT DISTINCT ua.academia_id, ua.usuario_id
            FROM usuarios_academias ua
            INNER JOIN roles_usuario ru ON ru.usuario_id = ua.usuario_id
            INNER JOIN roles r ON r.id = ru.role_id
            INNER JOIN academias ac ON ac.id = ua.academia_id AND ac.id_associacao = %s
            WHERE (
                r.chave = 'professor'
                OR r.nome = 'Professor'
                OR LOWER(REPLACE(COALESCE(r.chave, ''), ' ', '_')) = 'professor'
            )
            """,
            (id_assoc,),
        )
        for g in cur.fetchall():
            aid = g.get("academia_id")
            uid = g.get("usuario_id")
            if aid is None or uid is None:
                continue
            aid_i = int(aid)
            if aid_i not in prof_uid_por_academia:
                prof_uid_por_academia[aid_i] = int(uid)
    except Exception:
        prof_uid_por_academia = {}

    by_acad = defaultdict(list)
    for r in rows:
        aid = r.get("id_academia")
        aid_k = int(aid) if aid is not None else None
        by_acad[aid_k].append(r)

    out = []
    for aid_k in sorted(by_acad.keys(), key=lambda x: (x is None, x if x is not None else 0)):
        lst = by_acad[aid_k]
        chosen = None
        # S\u00f3 academias aderidas ao evento, quando o filtro \u00e9 informado.
        if academias_permitidas is not None and aid_k not in academias_permitidas:
            continue
        # O professor do link \u00e9 o RESPONS\u00c1VEL definido no cadastro da academia
        # (campo `responsavel`), casando pelo nome do professor ou do usu\u00e1rio dele.
        # Sem esse casamento, cai no gestor da academia; sem nada, a academia n\u00e3o entra.
        if aid_k is not None:
            resp = _norm(lst[0].get("academia_responsavel"))
            if resp:
                for r in lst:
                    if _norm(r.get("nome")) == resp or _norm(r.get("usuario_nome")) == resp:
                        chosen = r
                        break
            if chosen is None:
                gestor_uid = gestor_uid_por_academia.get(aid_k)
                if gestor_uid is not None:
                    for r in lst:
                        u = r.get("usuario_id")
                        if u is not None and int(u) == gestor_uid:
                            chosen = r
                            break
        if chosen is None:
            continue
        out.append(
            {
                "id": chosen["id"],
                "nome": chosen["nome"],
                "id_academia": chosen.get("id_academia"),
                "academia_nome": chosen.get("academia_nome"),
            }
        )
    out.sort(key=lambda x: ((x.get("academia_nome") or "\uffff").lower(), (x.get("nome") or "").lower()))
    return out


def _academias_opcoes_inscricao_publica(cur, evento_id, id_assoc):
    """Academias com adesão confirmada; se nenhuma, todas da associação (para não bloquear o formulário)."""
    cur.execute(
        """
        SELECT ac.id, ac.nome FROM academias ac
        INNER JOIN eventos_competicoes_adesao ea
          ON ea.academia_id = ac.id AND ea.evento_id = %s AND ea.aderiu = 1
        WHERE ac.id_associacao = %s
        ORDER BY ac.nome
        """,
        (evento_id, id_assoc),
    )
    rows = cur.fetchall()
    if rows:
        return rows
    cur.execute(
        "SELECT id, nome FROM academias WHERE id_associacao = %s ORDER BY nome",
        (id_assoc,),
    )
    return cur.fetchall()


def _professores_opcoes_inscricao_publica(cur, id_assoc):
    return _professores_associacao_para_link(cur, id_assoc)


def _resolver_academia_id_inscricao_publica(cur, evento_id, id_assoc, id_academia_form):
    """FK da inscrição: academia escolhida (se válida) ou âncora atual."""
    try:
        wanted = int(id_academia_form) if id_academia_form not in (None, "") else None
    except (TypeError, ValueError):
        wanted = None
    cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (id_assoc,))
    permitidos = {int(r["id"]) for r in cur.fetchall()}
    if wanted is not None and wanted in permitidos:
        aderentes = _ids_academias_aderentes_evento(cur, evento_id)
        if not aderentes or wanted in aderentes:
            return wanted
    return _academia_anchor_inscricao_avulsa(cur, evento_id)


def _professor_publico_valido(cur, professor_id, id_assoc):
    if not professor_id:
        return None
    try:
        pid = int(professor_id)
    except (TypeError, ValueError):
        return None
    cur.execute(
        """
        SELECT id, nome FROM professores
        WHERE id = %s AND id_associacao = %s AND ativo = 1 AND status = 'ativo'
        LIMIT 1
        """,
        (pid, id_assoc),
    )
    return cur.fetchone()


def _evento_por_token_inscricao_publica(cur, token):
    if not token or len(str(token)) > 96:
        return None
    try:
        cur.execute(
            """
            SELECT id, nome, data_fim, tipo, id_associacao, inscricao_modo, public_inscricao_token, categorias_modo
            FROM eventos_competicoes
            WHERE public_inscricao_token = %s
            LIMIT 1
            """,
            (token,),
        )
        row = cur.fetchone()
    except Exception:
        try:
            cur.execute(
                """
                SELECT id, nome, data_fim, tipo, id_associacao, inscricao_modo, public_inscricao_token
                FROM eventos_competicoes
                WHERE public_inscricao_token = %s
                LIMIT 1
                """,
                (token,),
            )
            row = cur.fetchone()
        except Exception:
            return None
    if row and "categorias_modo" not in row:
        row["categorias_modo"] = "padrao"
    return row


def _inserir_inscricao_avulso_simples(
    cur,
    evento_id,
    academia_id,
    nome,
    data_nasc_iso,
    peso_val,
    professor,
    local_treino,
    categoria,
    origem,
    professor_id=None,
    id_academia_escolhida=None,
    categoria_aprox_id=None,
    sexo_aluno=None,
):
    dados = {
        "nome": nome,
        "data_nascimento": data_nasc_iso or "",
        "peso": peso_val,
        "professor": professor or "",
        "local_treino": local_treino or "",
        "categoria": (categoria or "").strip(),
        "origem_inscricao": origem,
    }
    if professor_id:
        dados["professor_id"] = int(professor_id)
    if id_academia_escolhida:
        dados["id_academia_escolhida"] = int(id_academia_escolhida)
    if categoria_aprox_id:
        dados["categoria_aprox_id"] = int(categoria_aprox_id)
    if sexo_aluno is not None and str(sexo_aluno).strip():
        dados["sexo"] = str(sexo_aluno).strip().upper()[:1]
    cur.execute(
        """
        INSERT INTO eventos_competicoes_inscricoes
        (evento_id, academia_id, aluno_id, usuario_inscricao_id, dados_form, inclusao_avulsa, status)
        VALUES (%s, %s, NULL, NULL, %s, 1, 'enviada')
        """,
        (evento_id, academia_id, json.dumps(dados, ensure_ascii=False)),
    )


@bp_eventos_competicoes.route("/inscricao-publica/<token>", methods=["GET", "POST"])
@csrf.exempt
def inscricao_publica(token):
    """Inscrição aberta por link (sem login): dados básicos para competição avulsa/mista."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ev = _evento_por_token_inscricao_publica(cur, token)
        if not ev:
            return render_template(
                "eventos_competicoes/inscricao_publica.html",
                erro="Link inválido ou expirado.",
                evento=None,
                token=token,
            ), 404
        if ev.get("tipo") != "competicao" or not _modo_aceita_inscricao_publica(ev.get("inscricao_modo") or ""):
            return render_template(
                "eventos_competicoes/inscricao_publica.html",
                erro="Esta competição não aceita inscrição por este link.",
                evento=ev,
                token=token,
            ), 403
        if _evento_encerrado(ev):
            return render_template(
                "eventos_competicoes/inscricao_publica.html",
                erro="O prazo de inscrições desta competição já encerrou.",
                evento=ev,
                token=token,
            )

        id_assoc_ev = int(ev["id_associacao"])
        if not _academia_anchor_inscricao_avulsa(cur, ev["id"]):
            return render_template(
                "eventos_competicoes/inscricao_publica.html",
                erro="Não há academia vinculada à competição para registrar a inscrição. Cadastre academias na associação.",
                evento=ev,
                token=token,
            ), 503

        cat_modo_ev = _as_texto_mysql(ev.get("categorias_modo")) or "padrao"
        ev["categorias_modo"] = cat_modo_ev
        categorias_opts = []
        if cat_modo_ev != "aproximacao":
            cur.execute(
                """
                SELECT id, nome_categoria FROM categorias WHERE ativo = 1
                ORDER BY genero, id_classe, peso_min
                LIMIT 500
                """
            )
            categorias_opts = cur.fetchall()
        academias_opts = _academias_opcoes_inscricao_publica(cur, ev["id"], id_assoc_ev)
        professores_opts = _professores_opcoes_inscricao_publica(cur, id_assoc_ev)
        professor_pre = _professor_publico_valido(cur, request.args.get("professor_id"), id_assoc_ev)
        # Ids dos professores que são o RESPONSÁVEL de cada academia (um por academia),
        # para o formulário já vir com o responsável pré-selecionado.
        responsaveis_ids = {
            p["id"] for p in _professores_responsavel_por_academia_para_link(cur, id_assoc_ev)
        }

        def _tpl_inscricao_publica(**extra):
            kw = dict(
                evento=ev,
                token=token,
                categorias_opts=categorias_opts,
                academias_opts=academias_opts,
                professores_opts=professores_opts,
                professor_pre=professor_pre,
                responsaveis_ids=responsaveis_ids,
            )
            kw.update(extra)
            return kw

        if request.method == "POST":
            nome = request.form.get("nome_completo", "").strip()
            data_nasc = _parse_data_nascimento_avulso(request.form.get("data_nascimento"))
            peso_raw = request.form.get("peso", "").strip().replace(",", ".")
            try:
                peso_val = float(peso_raw) if peso_raw else None
            except ValueError:
                peso_val = None
            id_academia_form = request.form.get("id_academia", "").strip()
            prof_sel = request.form.get("professor_id", "").strip()
            professor_manual = request.form.get("professor", "").strip()
            local_extra = request.form.get("local_treino", "").strip()
            categoria = (request.form.get("categoria") or "").strip()
            categoria_aprox_id = None
            pid_json = None
            professor = professor_manual
            if prof_sel.isdigit():
                prow = _professor_publico_valido(cur, int(prof_sel), id_assoc_ev)
                if prow:
                    professor = prow["nome"]
                    pid_json = prow["id"]
            if not professor:
                professor = professor_manual
            id_academia_escolhida = None
            if id_academia_form.isdigit():
                id_academia_escolhida = int(id_academia_form)
            local_treino = local_extra
            if id_academia_escolhida:
                cur.execute(
                    "SELECT nome FROM academias WHERE id = %s AND id_associacao = %s LIMIT 1",
                    (id_academia_escolhida, id_assoc_ev),
                )
                an = cur.fetchone()
                if an:
                    local_treino = (an["nome"] + (f" — {local_extra}" if local_extra else "")).strip()
            academia_fk = _resolver_academia_id_inscricao_publica(cur, ev["id"], id_assoc_ev, id_academia_form or None)
            if not nome:
                flash("Informe o nome completo.", "danger")
            elif not data_nasc:
                flash("Informe a data de nascimento válida.", "danger")
            elif peso_val is None:
                flash("Informe o peso (número).", "danger")
            else:
                sexo_aluno_ins = (request.form.get("sexo") or "").strip().upper()[:1]
                if sexo_aluno_ins not in ("M", "F", "O"):
                    flash("Informe o sexo (masculino, feminino ou outro).", "danger")
                else:
                    if cat_modo_ev == "aproximacao":
                        cn, ci = _categoria_aprox_para_atleta(
                            cur,
                            ev["id"],
                            data_nasc,
                            sexo_aluno_ins,
                            peso_val,
                        )
                        if cn and ci:
                            categoria, categoria_aprox_id = cn, ci
                        else:
                            categoria = ""
                            categoria_aprox_id = None
                    _inserir_inscricao_avulso_simples(
                        cur,
                        ev["id"],
                        academia_fk,
                        nome,
                        data_nasc,
                        peso_val,
                        professor,
                        local_treino,
                        categoria,
                        "link_publico",
                        professor_id=pid_json,
                        id_academia_escolhida=id_academia_escolhida,
                        categoria_aprox_id=categoria_aprox_id,
                        sexo_aluno=sexo_aluno_ins,
                    )
                    conn.commit()
                    flash("Inscrição registrada com sucesso.", "success")
                    if cat_modo_ev == "aproximacao" and not categoria_aprox_id:
                        flash(
                            "Por enquanto não há faixa cadastrada que corresponda aos seus dados: a inscrição ficou "
                            "sem categoria. A organização poderá cadastrar as faixas e atualizar as categorias depois.",
                            "info",
                        )
                    return render_template(
                        "eventos_competicoes/inscricao_publica.html",
                        **_tpl_inscricao_publica(ok=True),
                    )

        return render_template("eventos_competicoes/inscricao_publica.html", **_tpl_inscricao_publica())
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/")
@login_required
def lista():
    """Lista completa (eventos gerais e competições). Atalho: ?tipo=evento|competicao."""
    tipo = request.args.get("tipo")
    if tipo not in (None, "evento", "competicao"):
        tipo = None
    return _lista_eventos_competicoes_core(tipo_filtro=tipo)


@bp_eventos_competicoes.route("/eventos")
@login_required
def lista_eventos():
    """Menu Eventos: somente cadastros tipo evento geral (sem placar)."""
    return _lista_eventos_competicoes_core(tipo_filtro="evento")


@bp_eventos_competicoes.route("/competicoes")
@login_required
def lista_competicoes():
    """Menu Competições: somente competições de judô (com placar)."""
    return _lista_eventos_competicoes_core(tipo_filtro="competicao")


def _lista_eventos_competicoes_core(tipo_filtro):
    """Lista eventos: associação vê os que criou; academia vê os disponíveis. tipo_filtro: None, 'evento' ou 'competicao'."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))

    extra_where = ""
    extra_params = ()
    if tipo_filtro in ("evento", "competicao"):
        extra_where = " AND ec.tipo = %s"
        extra_params = (tipo_filtro,)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        ids_acad = _get_ids_academias(cur)

        url_kw = {}
        academia_id_arg = None

        if modo == "associacao" and (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
            # Eventos e competições são telas separadas: sem filtro, vai para eventos
            # em vez da lista misturada rotulada "Eventos".
            if tipo_filtro not in ("evento", "competicao"):
                return redirect(url_for("eventos_competicoes.lista_eventos"))
            if not id_assoc:
                flash("Selecione a associação.", "warning")
                return redirect(url_for("associacao.gerenciamento_associacao"))
            try:
                cur.execute("""
                    SELECT ec.id, ec.nome, ec.descricao, ec.tipo, ec.natureza, ec.categorias_modo, ec.data_inicio, ec.data_fim, ec.status, ec.id_formulario, f.nome as formulario_nome,
                           (SELECT COUNT(*) FROM eventos_competicoes_adesao WHERE evento_id=ec.id AND aderiu=1) as academias_aderidas,
                           (SELECT COUNT(*) FROM eventos_competicoes_inscricoes WHERE evento_id=ec.id AND status='enviada') as inscricoes_enviadas,
                           (SELECT COUNT(*) FROM eventos_competicoes_anexos WHERE evento_id=ec.id) as total_anexos
                    FROM eventos_competicoes ec
                    LEFT JOIN formularios f ON f.id = ec.id_formulario
                    WHERE ec.id_associacao = %s""" + extra_where + """
                    ORDER BY ec.data_fim DESC
                """, (id_assoc,) + extra_params)
            except Exception as ex_ls:
                err_ls = str(ex_ls).lower()
                if "natureza" in err_ls or "categorias_modo" in err_ls or "1054" in err_ls or "unknown column" in err_ls:
                    cur.execute("""
                        SELECT ec.id, ec.nome, ec.descricao, ec.tipo, ec.data_inicio, ec.data_fim, ec.status, ec.id_formulario, f.nome as formulario_nome,
                               (SELECT COUNT(*) FROM eventos_competicoes_adesao WHERE evento_id=ec.id AND aderiu=1) as academias_aderidas,
                               (SELECT COUNT(*) FROM eventos_competicoes_inscricoes WHERE evento_id=ec.id AND status='enviada') as inscricoes_enviadas,
                               (SELECT COUNT(*) FROM eventos_competicoes_anexos WHERE evento_id=ec.id) as total_anexos
                        FROM eventos_competicoes ec
                        LEFT JOIN formularios f ON f.id = ec.id_formulario
                        WHERE ec.id_associacao = %s""" + extra_where + """
                        ORDER BY ec.data_fim DESC
                    """, (id_assoc,) + extra_params)
                else:
                    raise
            eventos = cur.fetchall()
            for ev in eventos:
                if "natureza" not in ev:
                    ev["natureza"] = None
                if "categorias_modo" not in ev:
                    ev["categorias_modo"] = "padrao"
                ev["encerrado"] = _evento_encerrado(ev)
                cur.execute("""
                    SELECT id, nome_arquivo, tamanho_bytes, descricao
                    FROM eventos_competicoes_anexos
                    WHERE evento_id = %s
                    ORDER BY created_at DESC
                """, (ev["id"],))
                anexos = cur.fetchall()
                for anexo in anexos:
                    tamanho = anexo.get("tamanho_bytes") or 0
                    if tamanho < 1024:
                        anexo["tamanho_formatado"] = f"{tamanho} B"
                    elif tamanho < 1024 * 1024:
                        anexo["tamanho_formatado"] = f"{tamanho / 1024:.1f} KB"
                    else:
                        anexo["tamanho_formatado"] = f"{tamanho / (1024 * 1024):.1f} MB"
                ev["anexos"] = anexos
            return render_template(
                "eventos_competicoes/lista_associacao.html",
                eventos=eventos,
                back_url=url_for("associacao.gerenciamento_associacao"),
                tipo_filtro=tipo_filtro,
                url_lista_eventos=url_for("eventos_competicoes.lista_eventos"),
                url_lista_competicoes=url_for("eventos_competicoes.lista_competicoes"),
                url_lista_todos=url_for("eventos_competicoes.lista"),
            )

        if modo == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor") or current_user.has_role("admin")):
            if not ids_acad:
                flash("Nenhuma academia vinculada.", "warning")
                return redirect(url_for("painel.home"))
            # Eventos e competições são telas separadas: sem filtro, a academia vai
            # para a de eventos, em vez de uma lista misturada rotulada "Eventos".
            if tipo_filtro not in ("evento", "competicao"):
                return redirect(url_for("eventos_competicoes.lista_eventos",
                                        academia_id=request.args.get("academia_id")))
            academia_id_arg = request.args.get("academia_id", type=int) or (ids_acad[0] if ids_acad else None)
            if academia_id_arg not in ids_acad:
                academia_id_arg = ids_acad[0]
            url_kw["academia_id"] = academia_id_arg
            cur.execute("""
                SELECT ec.id, ec.nome, ec.descricao, ec.tipo, ec.data_inicio, ec.data_fim, ec.id_formulario, f.nome as formulario_nome,
                       COALESCE(ea.aderiu, 0) as aderiu, ea.academia_id
                FROM eventos_competicoes ec
                INNER JOIN academias ac ON ac.id_associacao = ec.id_associacao AND ac.id = %s
                LEFT JOIN formularios f ON f.id = ec.id_formulario
                LEFT JOIN eventos_competicoes_adesao ea ON ea.evento_id = ec.id AND ea.academia_id = %s
                """ + ("WHERE ec.tipo = %s " if tipo_filtro in ("evento", "competicao") else "") + """
                ORDER BY ec.data_fim DESC
            """, ((academia_id_arg, academia_id_arg) + ((tipo_filtro,) if tipo_filtro in ("evento", "competicao") else ())))
            eventos = cur.fetchall()
            for ev in eventos:
                ev["encerrado"] = _evento_encerrado(ev)
                cur.execute("""
                    SELECT id, nome_arquivo, tamanho_bytes, descricao
                    FROM eventos_competicoes_anexos
                    WHERE evento_id = %s
                    ORDER BY created_at DESC
                """, (ev["id"],))
                anexos = cur.fetchall()
                for anexo in anexos:
                    tamanho = anexo.get("tamanho_bytes") or 0
                    if tamanho < 1024:
                        anexo["tamanho_formatado"] = f"{tamanho} B"
                    elif tamanho < 1024 * 1024:
                        anexo["tamanho_formatado"] = f"{tamanho / 1024:.1f} KB"
                    else:
                        anexo["tamanho_formatado"] = f"{tamanho / (1024 * 1024):.1f} MB"
                ev["anexos"] = anexos
            cur.execute("SELECT id, nome FROM academias WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(ids_acad)), tuple(ids_acad))
            academias_sel = cur.fetchall()
            return render_template(
                "eventos_competicoes/lista_academia.html",
                eventos=eventos,
                academias=academias_sel,
                academias_ids=ids_acad,
                academia_id=academia_id_arg,
                back_url=url_for("academia.painel_academia", academia_id=academia_id_arg) if academia_id_arg else url_for("painel.home"),
                tipo_filtro=tipo_filtro,
                url_lista_eventos=url_for("eventos_competicoes.lista_eventos", **url_kw),
                url_lista_competicoes=url_for("eventos_competicoes.lista_competicoes", **url_kw),
                url_lista_todos=url_for("eventos_competicoes.lista", **url_kw),
            )

        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    finally:
        cur.close()
        conn.close()


def _get_ids_academias(cur):
    """Ids das academias do usuário (modo academia)."""
    ids = []
    # Primeiro: verificar usuarios_academias (prioridade)
    cur.execute("""
        SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s ORDER BY academia_id
    """, (current_user.id,))
    vinculadas = [r["academia_id"] for r in cur.fetchall()]
    if vinculadas:
        return vinculadas
    
    # Modo academia: gestor_academia/professor só veem academias de usuarios_academias (não id_academia)
    if session.get("modo_painel") == "academia" and (current_user.has_role("gestor_academia") or current_user.has_role("professor")):
        return []
    
    # Admin: todas as academias
    if current_user.has_role("admin"):
        cur.execute("SELECT id FROM academias ORDER BY nome")
        ids = [r["id"] for r in cur.fetchall()]
        return ids
    
    # Gestor federação: academias da federação
    if current_user.has_role("gestor_federacao"):
        cur.execute("""
            SELECT ac.id FROM academias ac 
            JOIN associacoes ass ON ass.id = ac.id_associacao 
            WHERE ass.id_federacao = %s ORDER BY ac.nome
        """, (getattr(current_user, "id_federacao", None),))
        ids = [r["id"] for r in cur.fetchall()]
        return ids
    
    # Gestor associação: academias da associação
    if current_user.has_role("gestor_associacao"):
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        if id_assoc:
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s ORDER BY nome", (id_assoc,))
            ids = [r["id"] for r in cur.fetchall()]
        return ids
    
    # Fallback: id_academia (se existir)
    if getattr(current_user, "id_academia", None):
        return [current_user.id_academia]
    
    return []


def _back_por_tipo_e_modo(evento_id, tipo_filtro=None, cur=None):
    """Voltar de telas da competição: associação → painel; academia → lista com academia_id quando possível."""
    tipo = _as_texto_mysql(tipo_filtro) or "evento"
    if session.get("modo_painel") == "associacao" and tipo == "competicao":
        return _url_hub_competicao(evento_id)
    aid = None
    if session.get("modo_painel") == "academia":
        aid = getattr(current_user, "id_academia", None) or request.args.get("academia_id", type=int)
        if aid is None and cur is not None:
            ids = _get_ids_academias(cur)
            if ids:
                aid = ids[0]
    return _url_lista_eventos_competicoes(tipo, academia_id=aid)


@bp_eventos_competicoes.route("/cadastro", methods=["GET", "POST"])
@login_required
def cadastro():
    """Associação cria evento com formulário e data fim."""
    if session.get("modo_painel") != "associacao":
        flash("Disponível apenas em modo associação.", "danger")
        return redirect(url_for("painel.home"))
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        flash("Selecione a associação.", "warning")
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome FROM formularios WHERE id_associacao = %s AND ativo = 1 ORDER BY nome", (id_assoc,))
        formularios = cur.fetchall()

        tipo_query = (request.args.get("tipo") or "").strip()
        if tipo_query not in ("evento", "competicao"):
            tipo_query = ""

        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            descricao = request.form.get("descricao", "").strip()
            tipo = request.form.get("tipo", "evento")
            id_formulario = request.form.get("id_formulario", type=int) or None
            data_inicio = request.form.get("data_inicio") or None
            data_fim = request.form.get("data_fim")
            if not nome or not data_fim:
                flash("Informe nome e data/hora fim do evento.", "danger")
                return render_template(
                    "eventos_competicoes/cadastro.html",
                    formularios=formularios,
                    back_url=_url_lista_eventos_competicoes(tipo if tipo in ("evento", "competicao") else None),
                    tipo_default=tipo if tipo in ("evento", "competicao") else "evento",
                    anexos_existentes=[],
                )
            if tipo not in ("evento", "competicao"):
                tipo = "evento"
            natureza = None
            categorias_modo = "padrao"
            if tipo == "competicao":
                natureza = request.form.get("natureza", "oficial") or "oficial"
                if natureza not in ("oficial", "festival"):
                    natureza = "oficial"
                categorias_modo = request.form.get("categorias_modo", "padrao") or "padrao"
                if categorias_modo not in ("padrao", "aproximacao"):
                    categorias_modo = "padrao"
            try:
                dt_fim = datetime.strptime(data_fim[:16], "%Y-%m-%dT%H:%M") if data_fim else None
            except Exception:
                dt_fim = None
            if not dt_fim:
                flash("Data/hora fim inválida.", "danger")
                return render_template(
                    "eventos_competicoes/cadastro.html",
                    formularios=formularios,
                    back_url=_url_lista_eventos_competicoes(tipo if tipo in ("evento", "competicao") else None),
                    tipo_default=tipo if tipo in ("evento", "competicao") else "evento",
                    anexos_existentes=[],
                )

            dt_ini = None
            if data_inicio:
                try:
                    dt_ini = datetime.strptime(data_inicio[:16], "%Y-%m-%dT%H:%M")
                except Exception:
                    pass

            modo_ins = request.form.get("inscricao_modo", "academias_formulario")
            modo_i, token_i = _compute_inscricao_modo_e_token(tipo, modo_ins, None, False)
            gravou_modo_no_insert = False
            try:
                cur.execute(
                    """
                    INSERT INTO eventos_competicoes (nome, descricao, id_associacao, id_formulario, tipo, natureza, categorias_modo, data_inicio, data_fim, inscricao_modo, public_inscricao_token)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        nome,
                        descricao or None,
                        id_assoc,
                        id_formulario,
                        tipo,
                        natureza,
                        categorias_modo,
                        dt_ini,
                        dt_fim,
                        modo_i,
                        token_i,
                    ),
                )
                gravou_modo_no_insert = True
            except Exception as ins_ev:
                err_ins = str(ins_ev).lower()
                falta_nc = ("unknown column" in err_ins or "1054" in err_ins) and (
                    "natureza" in err_ins or "categorias_modo" in err_ins
                )
                if falta_nc:
                    try:
                        cur.execute(
                            """
                            INSERT INTO eventos_competicoes (nome, descricao, id_associacao, id_formulario, tipo, data_inicio, data_fim, inscricao_modo, public_inscricao_token)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (nome, descricao or None, id_assoc, id_formulario, tipo, dt_ini, dt_fim, modo_i, token_i),
                        )
                        gravou_modo_no_insert = True
                    except Exception as ins2:
                        err2 = str(ins2).lower()
                        falta_ins = ("unknown column" in err2 or "1054" in err2) and (
                            "inscricao_modo" in err2 or "public_inscricao" in err2
                        )
                        if falta_ins:
                            cur.execute(
                                """
                                INSERT INTO eventos_competicoes (nome, descricao, id_associacao, id_formulario, tipo, data_inicio, data_fim)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """,
                                (nome, descricao or None, id_assoc, id_formulario, tipo, dt_ini, dt_fim),
                            )
                        else:
                            raise
                elif "inscricao_modo" in err_ins or "public_inscricao" in err_ins:
                    cur.execute(
                        """
                        INSERT INTO eventos_competicoes (nome, descricao, id_associacao, id_formulario, tipo, natureza, categorias_modo, data_inicio, data_fim)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (nome, descricao or None, id_assoc, id_formulario, tipo, natureza, categorias_modo, dt_ini, dt_fim),
                    )
                else:
                    raise
            evento_id = cur.lastrowid
            if not gravou_modo_no_insert:
                _aplicar_modo_e_token_inscricao(cur, evento_id, tipo, modo_ins)
            if tipo == "competicao":
                pcm_new = _normalize_placar_controle_modelo(request.form.get("placar_controle_modelo"))
                if not _try_update_placar_controle_modelo(cur, evento_id, id_assoc, pcm_new):
                    flash(
                        "Controle do placar não gravado nesta competição. Execute no MySQL: migrations/add_placar_controle_modelo_evento.sql",
                        "warning",
                    )

            # Processar anexos enviados
            anexos_enviados = request.files.getlist("anexos")
            for anexo_file in anexos_enviados:
                if anexo_file and anexo_file.filename:
                    resultado = _salvar_anexo_evento(anexo_file, evento_id)
                    if resultado:
                        descricao_anexo = request.form.get(f"descricao_anexo_{anexo_file.filename}", "").strip() or None
                        cur.execute("""
                            INSERT INTO eventos_competicoes_anexos 
                            (evento_id, nome_arquivo, caminho_arquivo, tamanho_bytes, tipo_mime, descricao, criado_por)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (
                            evento_id,
                            resultado["nome_original"],
                            resultado["caminho"],
                            resultado["tamanho"],
                            resultado["tipo_mime"],
                            descricao_anexo,
                            current_user.id
                        ))

            academias_ids = _ids_academias_associacao(cur, id_assoc)
            for ac_id in academias_ids:
                cur.execute("""
                    INSERT INTO eventos_competicoes_adesao (evento_id, academia_id, aderiu) VALUES (%s, %s, 0)
                """, (evento_id, ac_id))

            # Inserir no calendário da associação e das academias automaticamente
            dt_ini_date = dt_ini.date() if dt_ini else (dt_fim.date() if dt_fim else date.today())
            dt_fim_date = dt_fim.date() if dt_fim else dt_ini_date
            hora_ini = dt_ini.time() if dt_ini and hasattr(dt_ini, "time") else None
            hora_fim = dt_fim.time() if dt_fim and hasattr(dt_fim, "time") else None
            tipo_cal = _tipo_calendario_para_sinc(tipo, natureza)
            try:
                cur.execute("""
                    INSERT INTO eventos (titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim, tipo, recorrente,
                        nivel, nivel_id, criado_por_usuario_id, origem_sincronizacao, evento_competicao_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'associacao', %s, %s, 'eventos_competicoes', %s, 'ativo')
                """, (nome, descricao or None, dt_ini_date, dt_fim_date, hora_ini, hora_fim, tipo_cal, id_assoc, current_user.id, evento_id))
                for ac_id in academias_ids:
                    cur.execute("""
                        INSERT INTO eventos (titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim, tipo, recorrente,
                            nivel, nivel_id, criado_por_usuario_id, origem_sincronizacao, evento_competicao_id, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'academia', %s, %s, 'eventos_competicoes', %s, 'ativo')
                    """, (nome, descricao or None, dt_ini_date, dt_fim_date, hora_ini, hora_fim, tipo_cal, ac_id, current_user.id, evento_id))
            except Exception:
                try:
                    cur.execute("""
                        INSERT INTO eventos (titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim, tipo, recorrente,
                            nivel, nivel_id, criado_por_usuario_id, origem_sincronizacao, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'associacao', %s, %s, 'eventos_competicoes', 'ativo')
                    """, (nome, descricao or None, dt_ini_date, dt_fim_date, hora_ini, hora_fim, tipo_cal, id_assoc, current_user.id))
                    for ac_id in academias_ids:
                        cur.execute("""
                            INSERT INTO eventos (titulo, descricao, data_inicio, data_fim, hora_inicio, hora_fim, tipo, recorrente,
                                nivel, nivel_id, criado_por_usuario_id, origem_sincronizacao, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'academia', %s, %s, 'eventos_competicoes', 'ativo')
                        """, (nome, descricao or None, dt_ini_date, dt_fim_date, hora_ini, hora_fim, tipo_cal, ac_id, current_user.id))
                except Exception:
                    pass

            conn.commit()
            if tipo == "competicao":
                flash("Competição criada. Use Editar para o menu completo (inscrições, chaves, placar, etc.).", "success")
            else:
                flash("Evento criado. As academias podem aderir.", "success")
            return redirect(_url_lista_eventos_competicoes(tipo))

        # Buscar anexos existentes (vazio no cadastro)
        anexos_existentes = []

        return render_template(
            "eventos_competicoes/cadastro.html",
            formularios=formularios,
            anexos_existentes=anexos_existentes,
            back_url=_url_lista_eventos_competicoes(tipo_query or None),
            tipo_default=tipo_query or "evento",
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/painel-competicao", methods=["GET"])
@login_required
def painel_competicao(evento_id):
    """Página só com os cards de opções da competição (lista → abre esta tela)."""
    if session.get("modo_painel") != "associacao":
        flash("Disponível apenas em modo associação.", "danger")
        return redirect(url_for("painel.home"))
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        flash("Selecione a associação.", "warning")
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT id, nome, tipo, categorias_modo
                FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
                """,
                (evento_id, id_assoc),
            )
        except Exception as ex_pc:
            err_pc = str(ex_pc).lower()
            if "categorias_modo" in err_pc or "1054" in err_pc or "unknown column" in err_pc:
                cur.execute(
                    "SELECT id, nome, tipo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
                    (evento_id, id_assoc),
                )
            else:
                raise
        evento = cur.fetchone()
        if not evento:
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("eventos_competicoes.lista_competicoes"))
        if "categorias_modo" not in evento:
            evento["categorias_modo"] = "padrao"
        evento["tipo"] = _as_texto_mysql(evento.get("tipo")) or "evento"
        evento["categorias_modo"] = _as_texto_mysql(evento.get("categorias_modo")) or "padrao"
        if evento.get("tipo") != "competicao":
            flash("Este painel é apenas para competições de judô.", "warning")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))

        return render_template(
            "eventos_competicoes/painel_competicao.html",
            evento=evento,
            back_url=url_for("eventos_competicoes.lista_competicoes"),
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/editar/<int:evento_id>", methods=["GET", "POST"])
@login_required
def editar(evento_id):
    """Associação edita evento existente."""
    if session.get("modo_painel") != "associacao":
        flash("Disponível apenas em modo associação.", "danger")
        return redirect(url_for("painel.home"))
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        flash("Selecione a associação.", "warning")
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute("""
                SELECT id, nome, descricao, tipo, natureza, categorias_modo, id_formulario, data_inicio, data_fim,
                       inscricao_modo, public_inscricao_token
                FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
            """, (evento_id, id_assoc))
        except Exception as ex_ed:
            err_ed = str(ex_ed).lower()
            if "inscricao_modo" in err_ed or "public_inscricao" in err_ed:
                try:
                    cur.execute("""
                        SELECT id, nome, descricao, tipo, natureza, categorias_modo, id_formulario, data_inicio, data_fim
                        FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
                    """, (evento_id, id_assoc))
                except Exception as ex_ed2:
                    err_ed2s = str(ex_ed2).lower()
                    if "natureza" in err_ed2s or "categorias_modo" in err_ed2s or "1054" in err_ed2s or "unknown column" in err_ed2s:
                        cur.execute("""
                            SELECT id, nome, descricao, tipo, id_formulario, data_inicio, data_fim
                            FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
                        """, (evento_id, id_assoc))
                    else:
                        raise
            elif "natureza" in err_ed or "categorias_modo" in err_ed or "1054" in err_ed or "unknown column" in err_ed:
                cur.execute("""
                    SELECT id, nome, descricao, tipo, id_formulario, data_inicio, data_fim
                    FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
                """, (evento_id, id_assoc))
            else:
                raise
        evento = cur.fetchone()
        if not evento:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        if "natureza" not in evento:
            evento["natureza"] = None
        if "categorias_modo" not in evento:
            evento["categorias_modo"] = "padrao"
        if evento.get("tipo") == "competicao" and not evento.get("natureza"):
            evento["natureza"] = "oficial"
        evento["tipo"] = _as_texto_mysql(evento.get("tipo")) or "evento"
        if evento.get("natureza") is not None:
            evento["natureza"] = _as_texto_mysql(evento.get("natureza"))
        evento["categorias_modo"] = _as_texto_mysql(evento.get("categorias_modo")) or "padrao"
        if "inscricao_modo" not in evento:
            evento["inscricao_modo"] = "academias_formulario"
        if "public_inscricao_token" not in evento:
            evento["public_inscricao_token"] = None
        evento["inscricao_modo"] = _as_texto_mysql(evento.get("inscricao_modo")) or "academias_formulario"
        if evento.get("public_inscricao_token"):
            evento["public_inscricao_token"] = _as_texto_mysql(evento.get("public_inscricao_token")) or None
        evento["placar_controle_modelo"] = _fetch_placar_controle_modelo_evento(cur, evento_id)

        lista_back = _back_por_tipo_e_modo(evento_id, evento.get("tipo"), cur=cur)

        cur.execute("SELECT id, nome FROM formularios WHERE id_associacao = %s AND ativo = 1 ORDER BY nome", (id_assoc,))
        formularios = cur.fetchall()
        
        # Buscar anexos existentes
        cur.execute("""
            SELECT id, nome_arquivo, caminho_arquivo, tamanho_bytes, tipo_mime, descricao, created_at
            FROM eventos_competicoes_anexos
            WHERE evento_id = %s
            ORDER BY created_at DESC
        """, (evento_id,))
        anexos_existentes = cur.fetchall()
        for anexo in anexos_existentes:
            # Formatar tamanho
            tamanho = anexo.get("tamanho_bytes") or 0
            if tamanho < 1024:
                anexo["tamanho_formatado"] = f"{tamanho} B"
            elif tamanho < 1024 * 1024:
                anexo["tamanho_formatado"] = f"{tamanho / 1024:.1f} KB"
            else:
                anexo["tamanho_formatado"] = f"{tamanho / (1024 * 1024):.1f} MB"

        academias_adesao = _lista_academias_adesao_evento(cur, evento_id, id_assoc)
        # Link por academia só para as que aderiram a este evento.
        aderentes = _ids_academias_aderentes_evento(cur, evento_id)
        professores_para_links = _professores_responsavel_por_academia_para_link(
            cur, id_assoc, academias_permitidas=aderentes)

        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            descricao = request.form.get("descricao", "").strip()
            tipo = request.form.get("tipo", "evento")
            id_formulario = request.form.get("id_formulario", type=int) or None
            data_inicio = request.form.get("data_inicio") or None
            data_fim = request.form.get("data_fim")
            if not nome or not data_fim:
                flash("Informe nome e data/hora fim do evento.", "danger")
                if tipo == "competicao":
                    evento["placar_controle_modelo"] = _normalize_placar_controle_modelo(
                        request.form.get("placar_controle_modelo")
                    )
                return render_template(
                    "eventos_competicoes/editar.html",
                    evento=evento,
                    formularios=formularios,
                    anexos_existentes=anexos_existentes,
                    back_url=_url_lista_eventos_competicoes(tipo if tipo in ("evento", "competicao") else evento.get("tipo")),
                    data_inicio_val=data_inicio or "",
                    data_fim_val=data_fim or "",
                    academias_adesao=academias_adesao,
                    professores_para_links=professores_para_links,
                )
            if tipo not in ("evento", "competicao"):
                tipo = "evento"
            natureza = None
            categorias_modo = "padrao"
            if tipo == "competicao":
                natureza = request.form.get("natureza", "oficial") or "oficial"
                if natureza not in ("oficial", "festival"):
                    natureza = "oficial"
                categorias_modo = request.form.get("categorias_modo", "padrao") or "padrao"
                if categorias_modo not in ("padrao", "aproximacao"):
                    categorias_modo = "padrao"
            try:
                dt_fim = datetime.strptime(data_fim[:16], "%Y-%m-%dT%H:%M") if data_fim else None
            except Exception:
                dt_fim = None
            if not dt_fim:
                flash("Data/hora fim inválida.", "danger")
                if tipo == "competicao":
                    evento["placar_controle_modelo"] = _normalize_placar_controle_modelo(
                        request.form.get("placar_controle_modelo")
                    )
                return render_template(
                    "eventos_competicoes/editar.html",
                    evento=evento,
                    formularios=formularios,
                    anexos_existentes=anexos_existentes,
                    back_url=_url_lista_eventos_competicoes(tipo if tipo in ("evento", "competicao") else evento.get("tipo")),
                    data_inicio_val=data_inicio or "",
                    data_fim_val=data_fim or "",
                    academias_adesao=academias_adesao,
                    professores_para_links=professores_para_links,
                )
            
            # Remover anexos marcados para exclusão
            anexos_remover = request.form.getlist("remover_anexo")
            for anexo_id in anexos_remover:
                try:
                    anexo_id_int = int(anexo_id)
                    # Buscar caminho do arquivo antes de deletar
                    cur.execute("SELECT caminho_arquivo FROM eventos_competicoes_anexos WHERE id = %s AND evento_id = %s", 
                               (anexo_id_int, evento_id))
                    anexo_row = cur.fetchone()
                    if anexo_row:
                        # Deletar arquivo físico
                        filepath = os.path.join(current_app.root_path, "static", "uploads", UPLOAD_ANEXOS, anexo_row["caminho_arquivo"])
                        try:
                            if os.path.exists(filepath):
                                os.remove(filepath)
                        except Exception:
                            pass
                        # Deletar registro no banco
                        cur.execute("DELETE FROM eventos_competicoes_anexos WHERE id = %s AND evento_id = %s", 
                                   (anexo_id_int, evento_id))
                except Exception:
                    pass

            dt_ini = None
            if data_inicio:
                try:
                    dt_ini = datetime.strptime(data_inicio[:16], "%Y-%m-%dT%H:%M")
                except Exception:
                    pass

            modo_ed = request.form.get("inscricao_modo", "academias_formulario")
            regenerar_link = bool(request.form.get("regenerar_link_publico"))
            modo_i, token_i = _compute_inscricao_modo_e_token(
                tipo,
                modo_ed,
                token_atual=evento.get("public_inscricao_token"),
                regenerar=regenerar_link,
            )

            def _upd_ev_cols(cols_sql, params):
                cur.execute(
                    f"""
                    UPDATE eventos_competicoes
                    SET {cols_sql}
                    WHERE id = %s AND id_associacao = %s
                    """,
                    params,
                )

            try:
                _upd_ev_cols(
                    """nome = %s, descricao = %s, tipo = %s, natureza = %s, categorias_modo = %s, id_formulario = %s, data_inicio = %s, data_fim = %s,
                        inscricao_modo = %s, public_inscricao_token = %s""",
                    (
                        nome,
                        descricao or None,
                        tipo,
                        natureza,
                        categorias_modo,
                        id_formulario,
                        dt_ini,
                        dt_fim,
                        modo_i,
                        token_i,
                        evento_id,
                        id_assoc,
                    ),
                )
            except Exception as up_ev:
                err_up = str(up_ev).lower()
                # Não usar "1054" / "unknown column" sozinhos: qualquer coluna nova (ex.: inscricao_modo)
                # cairia aqui e este UPDATE removeria natureza/categorias_modo da gravação.
                falta_natureza_ou_categorias = ("unknown column" in err_up or "1054" in err_up) and (
                    "natureza" in err_up or "categorias_modo" in err_up
                )
                if falta_natureza_ou_categorias:
                    try:
                        _upd_ev_cols(
                            """nome = %s, descricao = %s, tipo = %s, id_formulario = %s, data_inicio = %s, data_fim = %s,
                                inscricao_modo = %s, public_inscricao_token = %s""",
                            (
                                nome,
                                descricao or None,
                                tipo,
                                id_formulario,
                                dt_ini,
                                dt_fim,
                                modo_i,
                                token_i,
                                evento_id,
                                id_assoc,
                            ),
                        )
                    except Exception as up_ev2:
                        err2 = str(up_ev2).lower()
                        falta_insc_cols = ("unknown column" in err2 or "1054" in err2) and (
                            "inscricao_modo" in err2 or "public_inscricao" in err2
                        )
                        if falta_insc_cols:
                            _upd_ev_cols(
                                "nome = %s, descricao = %s, tipo = %s, id_formulario = %s, data_inicio = %s, data_fim = %s",
                                (nome, descricao or None, tipo, id_formulario, dt_ini, dt_fim, evento_id, id_assoc),
                            )
                            _m, _t, ok_extra = _aplicar_modo_e_token_inscricao(
                                cur,
                                evento_id,
                                tipo,
                                modo_ed,
                                token_atual=evento.get("public_inscricao_token"),
                                regenerar=regenerar_link,
                            )
                            if not ok_extra:
                                flash(
                                    "Modo de inscrição/link não gravado. Confirme a migração add_competicao_inscricao_modo_publica.sql no MySQL.",
                                    "warning",
                                )
                        else:
                            raise
                elif "inscricao_modo" in err_up or "public_inscricao" in err_up:
                    _upd_ev_cols(
                        "nome = %s, descricao = %s, tipo = %s, natureza = %s, categorias_modo = %s, id_formulario = %s, data_inicio = %s, data_fim = %s",
                        (
                            nome,
                            descricao or None,
                            tipo,
                            natureza,
                            categorias_modo,
                            id_formulario,
                            dt_ini,
                            dt_fim,
                            evento_id,
                            id_assoc,
                        ),
                    )
                    _m, _t, ok_extra = _aplicar_modo_e_token_inscricao(
                        cur,
                        evento_id,
                        tipo,
                        modo_ed,
                        token_atual=evento.get("public_inscricao_token"),
                        regenerar=regenerar_link,
                    )
                    if not ok_extra:
                        flash(
                            "Modo de inscrição/link não gravado. Confirme a migração add_competicao_inscricao_modo_publica.sql no MySQL.",
                            "warning",
                        )
                else:
                    raise

            if tipo == "competicao":
                pcm_ev = _normalize_placar_controle_modelo(request.form.get("placar_controle_modelo"))
                if not _try_update_placar_controle_modelo(cur, evento_id, id_assoc, pcm_ev):
                    flash(
                        "Opção de controle do placar não gravada. Execute no MySQL: migrations/add_placar_controle_modelo_evento.sql",
                        "warning",
                    )

            # Processar novos anexos enviados
            anexos_enviados = request.files.getlist("anexos")
            for anexo_file in anexos_enviados:
                if anexo_file and anexo_file.filename:
                    resultado = _salvar_anexo_evento(anexo_file, evento_id)
                    if resultado:
                        descricao_anexo = request.form.get(f"descricao_anexo_{anexo_file.filename}", "").strip() or None
                        cur.execute("""
                            INSERT INTO eventos_competicoes_anexos 
                            (evento_id, nome_arquivo, caminho_arquivo, tamanho_bytes, tipo_mime, descricao, criado_por)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (
                            evento_id,
                            resultado["nome_original"],
                            resultado["caminho"],
                            resultado["tamanho"],
                            resultado["tipo_mime"],
                            descricao_anexo,
                            current_user.id
                        ))

            # Atualizar eventos do calendário vinculados
            dt_ini_date = dt_ini.date() if dt_ini else (dt_fim.date() if dt_fim else date.today())
            dt_fim_date = dt_fim.date() if dt_fim else dt_ini_date
            hora_ini = dt_ini.time() if dt_ini and hasattr(dt_ini, "time") else None
            hora_fim = dt_fim.time() if dt_fim and hasattr(dt_fim, "time") else None
            tipo_cal = _tipo_calendario_para_sinc(tipo, natureza)
            try:
                cur.execute("""
                    UPDATE eventos
                    SET titulo = %s, descricao = %s, data_inicio = %s, data_fim = %s, hora_inicio = %s, hora_fim = %s, tipo = %s
                    WHERE evento_competicao_id = %s
                """, (nome, descricao or None, dt_ini_date, dt_fim_date, hora_ini, hora_fim, tipo_cal, evento_id))
            except Exception:
                pass

            marcadas = set(request.form.getlist("adesao_academia"))
            cur.execute("SELECT id FROM academias WHERE id_associacao = %s", (id_assoc,))
            for row_ac in cur.fetchall():
                ac_id = int(row_ac["id"])
                ader = 1 if str(ac_id) in marcadas else 0
                cur.execute(
                    """
                    INSERT INTO eventos_competicoes_adesao (evento_id, academia_id, aderiu)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE aderiu = VALUES(aderiu)
                    """,
                    (evento_id, ac_id, ader),
                )

            conn.commit()
            if tipo == "competicao":
                flash("Competição atualizada. O menu acima reúne inscrições, chaves, placar e demais opções.", "success")
            else:
                flash("Evento atualizado.", "success")
            _ed_q = {}
            if (request.args.get("embed") or "").strip().lower() in ("1", "true", "yes"):
                _ed_q["embed"] = 1
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id, **_ed_q))

        # GET: formatar datas para datetime-local
        data_inicio_val = ""
        data_fim_val = ""
        if evento.get("data_inicio"):
            di = evento["data_inicio"]
            if hasattr(di, "strftime"):
                data_inicio_val = di.strftime("%Y-%m-%dT%H:%M")
            else:
                data_inicio_val = str(di)[:16].replace(" ", "T")
        if evento.get("data_fim"):
            df = evento["data_fim"]
            if hasattr(df, "strftime"):
                data_fim_val = df.strftime("%Y-%m-%dT%H:%M")
            else:
                data_fim_val = str(df)[:16].replace(" ", "T")

        return render_template(
            "eventos_competicoes/editar.html",
            evento=evento,
            formularios=formularios,
            data_inicio_val=data_inicio_val,
            data_fim_val=data_fim_val,
            anexos_existentes=anexos_existentes,
            back_url=lista_back,
            academias_adesao=academias_adesao,
            professores_para_links=professores_para_links,
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/finalizar/<int:evento_id>", methods=["POST"])
@login_required
def finalizar(evento_id):
    """Associação marca evento como finalizado ou reativa."""
    if session.get("modo_painel") != "associacao":
        flash("Disponível apenas em modo associação.", "danger")
        return redirect(url_for("painel.home"))
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ev = None
    try:
        cur.execute(
            "SELECT id, status, tipo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc),
        )
        ev = cur.fetchone()
        if not ev:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))

        novo_status = "finalizado" if ev.get("status") != "finalizado" else "ativo"
        cur.execute("UPDATE eventos_competicoes SET status = %s WHERE id = %s", (novo_status, evento_id))
        conn.commit()
        if novo_status == "finalizado":
            flash("Evento finalizado.", "success")
        else:
            flash("Evento reativado.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(_url_lista_eventos_competicoes(ev.get("tipo")) if ev else url_for("eventos_competicoes.lista"))


@bp_eventos_competicoes.route("/excluir/<int:evento_id>", methods=["POST"])
@login_required
def excluir(evento_id):
    """Associação remove permanentemente o evento ou competição e dados vinculados."""
    if session.get("modo_painel") != "associacao":
        flash("Disponível apenas em modo associação.", "danger")
        return redirect(url_for("painel.home"))
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        flash("Selecione a associação.", "warning")
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    ev = None
    try:
        cur.execute(
            "SELECT id, nome, tipo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc),
        )
        ev = cur.fetchone()
        if not ev:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))

        cur.execute(
            "SELECT caminho_arquivo FROM eventos_competicoes_anexos WHERE evento_id = %s",
            (evento_id,),
        )
        anexo_rows = cur.fetchall()
        caminhos = [r["caminho_arquivo"] for r in anexo_rows if r.get("caminho_arquivo")]

        try:
            cur.execute(
                """
                DELETE FROM eventos
                WHERE evento_competicao_id = %s AND origem_sincronizacao = %s
                """,
                (evento_id, "eventos_competicoes"),
            )
        except Exception as ex_cal:
            current_app.logger.warning(
                "Excluir evento %s: calendário não atualizado (%s)", evento_id, ex_cal
            )

        cur.execute(
            "DELETE FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc),
        )
        if cur.rowcount == 0:
            conn.rollback()
            flash("Evento não encontrado.", "danger")
            return redirect(_url_lista_eventos_competicoes(ev.get("tipo")))

        conn.commit()

        base_upload = os.path.join(current_app.root_path, "static", "uploads", UPLOAD_ANEXOS)
        for rel in caminhos:
            fp = os.path.join(base_upload, rel)
            try:
                if os.path.isfile(fp):
                    os.remove(fp)
            except OSError:
                pass

        flash(f"«{ev['nome']}» foi excluído permanentemente.", "success")
    except Exception:
        conn.rollback()
        current_app.logger.exception("Erro ao excluir evento/competição id=%s", evento_id)
        flash(
            "Não foi possível excluir. Verifique vínculos no banco ou tente novamente.",
            "danger",
        )
    finally:
        cur.close()
        conn.close()
    return redirect(_url_lista_eventos_competicoes(ev.get("tipo")) if ev else url_for("eventos_competicoes.lista"))


@bp_eventos_competicoes.route("/<int:evento_id>/gestor-incluir-participante", methods=["GET", "POST"])
@login_required
def gestor_incluir_participante_avulso(evento_id):
    """
    Inclui participante digitando os dados (mesmos campos do link público).

    Serve para atleta que NÃO está cadastrado no sistema. Disponível para a
    associação e também para a academia, que precisa inscrever gente de fora
    sem antes criar um cadastro completo de aluno.
    """
    modo = session.get("modo_painel")
    eh_associacao = modo == "associacao" and (
        current_user.has_role("gestor_associacao") or current_user.has_role("admin"))
    eh_academia = modo == "academia" and (
        current_user.has_role("gestor_academia") or current_user.has_role("admin")
        or current_user.has_role("professor"))
    if not (eh_associacao or eh_academia):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc and eh_academia:
        # A academia herda a associação do evento a que ela aderiu.
        _c = get_db_connection()
        _k = _c.cursor(dictionary=True)
        try:
            _k.execute("SELECT id_associacao FROM eventos_competicoes WHERE id = %s", (evento_id,))
            id_assoc = (_k.fetchone() or {}).get("id_associacao")
        finally:
            _k.close()
            _c.close()
    if not id_assoc:
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT id, nome, data_fim, tipo, inscricao_modo, categorias_modo
                FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
                """,
                (evento_id, id_assoc),
            )
        except Exception:
            cur.execute(
                "SELECT id, nome, data_fim, tipo, inscricao_modo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
                (evento_id, id_assoc),
            )
        ev = cur.fetchone()
        if not ev or ev.get("tipo") != "competicao":
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("eventos_competicoes.lista_competicoes"))
        if "categorias_modo" not in ev:
            ev["categorias_modo"] = "padrao"
        ev["categorias_modo"] = _as_texto_mysql(ev.get("categorias_modo")) or "padrao"
        modo = ev.get("inscricao_modo") or "academias_formulario"
        if modo not in ("publico_avulso", "misto"):
            flash("Inclua participantes por aqui apenas se a competição estiver em modo avulso ou misto.", "warning")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))
        if _evento_encerrado(ev):
            flash("Prazo encerrado.", "warning")
            return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))

        academia_id = _academia_anchor_inscricao_avulsa(cur, evento_id)
        if not academia_id:
            flash("Cadastre academias na associação para usar inscrições avulsas.", "danger")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))

        categorias_opts = []
        if ev["categorias_modo"] != "aproximacao":
            cur.execute(
                """
                SELECT id, nome_categoria FROM categorias WHERE ativo = 1
                ORDER BY genero, id_classe, peso_min LIMIT 500
                """
            )
            categorias_opts = cur.fetchall()

        if request.method == "POST":
            nome = request.form.get("nome_completo", "").strip()
            data_nasc = _parse_data_nascimento_avulso(request.form.get("data_nascimento"))
            peso_raw = request.form.get("peso", "").strip().replace(",", ".")
            try:
                peso_val = float(peso_raw) if peso_raw else None
            except ValueError:
                peso_val = None
            professor = request.form.get("professor", "").strip()
            local_treino = request.form.get("local_treino", "").strip()
            categoria = (request.form.get("categoria") or "").strip()
            categoria_aprox_id = None
            if not nome:
                flash("Informe o nome completo.", "danger")
            elif not data_nasc:
                flash("Data de nascimento inválida.", "danger")
            elif peso_val is None:
                flash("Informe o peso.", "danger")
            else:
                sexo_aluno_ins = (request.form.get("sexo") or "").strip().upper()[:1]
                if sexo_aluno_ins not in ("M", "F", "O"):
                    flash("Informe o sexo (M, F ou O).", "danger")
                else:
                    if ev["categorias_modo"] == "aproximacao":
                        cn, ci = _categoria_aprox_para_atleta(
                            cur,
                            evento_id,
                            data_nasc,
                            sexo_aluno_ins,
                            peso_val,
                        )
                        if cn and ci:
                            categoria, categoria_aprox_id = cn, ci
                        else:
                            categoria = ""
                            categoria_aprox_id = None
                    _inserir_inscricao_avulso_simples(
                        cur,
                        evento_id,
                        academia_id,
                        nome,
                        data_nasc,
                        peso_val,
                        professor,
                        local_treino,
                        categoria,
                        "manual_gestor",
                        categoria_aprox_id=categoria_aprox_id if ev["categorias_modo"] == "aproximacao" else None,
                        sexo_aluno=sexo_aluno_ins,
                    )
                    conn.commit()
                    flash("Participante incluído.", "success")
                    if ev["categorias_modo"] == "aproximacao" and not categoria_aprox_id:
                        flash(
                            "Sem faixa compatível no momento: inscrição ficou sem categoria. "
                            "Cadastre as faixas e use «Recalcular categorias».",
                            "info",
                        )
                    _emb_gestor = (request.form.get("embed") or request.args.get("embed") or "").strip().lower() in (
                        "1",
                        "true",
                        "yes",
                    )
                    if _emb_gestor:
                        return render_template(
                            "eventos_competicoes/inscricao_sucesso_recarrega.html",
                            evento_id=evento_id,
                        )
                    return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))

        return render_template(
            "eventos_competicoes/gestor_incluir_participante_avulso.html",
            evento=ev,
            categorias_opts=categorias_opts,
            back_url=url_for("eventos_competicoes.consolidar", evento_id=evento_id),
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/importar-inscricoes-excel", methods=["GET", "POST"])
@login_required
def importar_inscricoes_excel(evento_id):
    """Importa planilha .xlsx: nome, data nascimento, peso; professor e local opcionais; categoria opcional no modo padrão.
    Em competição com categorias por aproximação, exige coluna sexo (M/F/O) e define categoria automaticamente."""
    if session.get("modo_painel") != "associacao":
        flash("Disponível apenas em modo associação.", "danger")
        return redirect(url_for("painel.home"))
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        _emb_imp = (request.args.get("embed") or request.form.get("embed") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )

        def _url_importar():
            _q = {}
            if _emb_imp:
                _q["embed"] = 1
            return url_for("eventos_competicoes.importar_inscricoes_excel", evento_id=evento_id, **_q)

        try:
            cur.execute(
                """
                SELECT id, nome, data_fim, tipo, inscricao_modo, categorias_modo
                FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
                """,
                (evento_id, id_assoc),
            )
        except Exception:
            cur.execute(
                "SELECT id, nome, data_fim, tipo, inscricao_modo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
                (evento_id, id_assoc),
            )
        ev = cur.fetchone()
        if not ev or ev.get("tipo") != "competicao":
            flash("Competição não encontrada.", "danger")
            return redirect(url_for("eventos_competicoes.lista_competicoes"))
        if "categorias_modo" not in ev:
            ev["categorias_modo"] = "padrao"
        cat_modo_imp = _as_texto_mysql(ev.get("categorias_modo")) or "padrao"
        modo = ev.get("inscricao_modo") or "academias_formulario"
        if modo not in ("publico_avulso", "misto"):
            flash("Importação disponível apenas em modo avulso ou misto.", "warning")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))
        if _evento_encerrado(ev):
            flash("Prazo encerrado.", "warning")
            return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))

        academia_id = _academia_anchor_inscricao_avulsa(cur, evento_id)
        if not academia_id:
            flash("Cadastre academias na associação.", "danger")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))

        if request.method == "POST":
            from utils.upload_seguro import validar_upload, UploadInvalido
            f = request.files.get("planilha")
            _planilha_ok = False
            if not f or not f.filename:
                flash("Selecione um arquivo .xlsx.", "danger")
            else:
                try:
                    validar_upload(f, categorias=["planilha"])
                    _planilha_ok = True
                except UploadInvalido as _e:
                    flash(str(_e), "danger")

            if _planilha_ok:
                try:
                    from openpyxl import load_workbook
                except ImportError:
                    flash("Biblioteca openpyxl não instalada.", "danger")
                    return redirect(_url_importar())

                import tempfile

                tmp_path = None
                try:
                    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
                    os.close(fd)
                    f.save(tmp_path)
                    wb = load_workbook(filename=tmp_path, read_only=True, data_only=True)
                    ws = wb.active
                    rows = list(ws.iter_rows(values_only=True))
                    wb.close()
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass

                if len(rows) < 2:
                    flash("Planilha vazia ou só com cabeçalho.", "danger")
                    return redirect(_url_importar())

                header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]

                def col_idx(*aliases):
                    for a in aliases:
                        a = a.lower()
                        for i, h in enumerate(header):
                            if not h:
                                continue
                            if h == a or a in h or h in a:
                                return i
                    return None

                ic_nome = col_idx("nome", "nome completo", "atleta")
                ic_dn = col_idx("data nascimento", "nascimento", "data_nascimento", "dt nasc")
                ic_peso = col_idx("peso")
                ic_prof = col_idx("professor", "sensei")
                ic_loc = col_idx("local de treino", "local treino", "local", "dojo", "academia")
                ic_cat = col_idx("categoria", "cat")
                ic_sexo = col_idx("sexo", "gênero", "genero", "género")
                if ic_nome is None or ic_dn is None or ic_peso is None:
                    flash(
                        "Cabeçalho deve incluir colunas reconhecíveis: nome (ou nome completo), data de nascimento, peso. "
                        "Professor e local de treino são recomendados.",
                        "danger",
                    )
                    return redirect(_url_importar())
                if cat_modo_imp == "aproximacao" and ic_sexo is None:
                    flash(
                        "Nesta competição as categorias são por aproximação: inclua uma coluna «sexo» (M, F ou O) na planilha.",
                        "danger",
                    )
                    return redirect(_url_importar())

                ok = 0
                erros = []
                for ri, row in enumerate(rows[1:], start=2):
                    if not row or all(v is None or str(v).strip() == "" for v in row):
                        continue
                    def cell(i):
                        if i is None or i >= len(row):
                            return None
                        return row[i]

                    nome = cell(ic_nome)
                    nome = str(nome).strip() if nome is not None else ""
                    if not nome:
                        continue
                    data_nasc = _parse_data_nascimento_avulso(cell(ic_dn))
                    peso_raw = cell(ic_peso)
                    try:
                        if peso_raw is None or str(peso_raw).strip() == "":
                            peso_val = None
                        else:
                            peso_val = float(str(peso_raw).replace(",", "."))
                    except ValueError:
                        peso_val = None
                    professor = str(cell(ic_prof) or "").strip()
                    local_treino = str(cell(ic_loc) or "").strip()
                    categoria = str(cell(ic_cat) or "").strip() if ic_cat is not None else ""
                    if not data_nasc or peso_val is None:
                        erros.append(f"Linha {ri}: data ou peso inválido para «{nome[:40]}»")
                        continue
                    sexo_cel = _normalizar_sexo_planilha(cell(ic_sexo)) if ic_sexo is not None else None
                    categoria_aprox_id = None
                    sexo_ins = None
                    if cat_modo_imp == "aproximacao":
                        if not sexo_cel:
                            erros.append(f"Linha {ri}: sexo inválido ou vazio para «{nome[:40]}»")
                            continue
                        sexo_ins = sexo_cel
                        cn, ci = _categoria_aprox_para_atleta(
                            cur,
                            evento_id,
                            cell(ic_dn),
                            sexo_cel,
                            peso_val,
                        )
                        if cn and ci:
                            categoria, categoria_aprox_id = cn, ci
                        else:
                            categoria = ""
                            categoria_aprox_id = None
                    elif sexo_cel:
                        sexo_ins = sexo_cel
                    _inserir_inscricao_avulso_simples(
                        cur,
                        evento_id,
                        academia_id,
                        nome,
                        data_nasc,
                        peso_val,
                        professor,
                        local_treino,
                        categoria,
                        "planilha_excel",
                        categoria_aprox_id=categoria_aprox_id,
                        sexo_aluno=sexo_ins,
                    )
                    ok += 1
                conn.commit()
                flash(f"Importadas {ok} inscrição(ões)." + (f" Avisos: {len(erros)} linhas ignoradas." if erros else ""), "success")
                if erros:
                    for e in erros[:15]:
                        flash(e, "warning")
                if _emb_imp:
                    return render_template(
                        "eventos_competicoes/inscricao_sucesso_recarrega.html",
                        evento_id=evento_id,
                    )
                return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))

        return render_template(
            "eventos_competicoes/importar_inscricoes_excel.html",
            evento=ev,
            back_url=url_for("eventos_competicoes.consolidar", evento_id=evento_id),
            url_modelo=url_for("eventos_competicoes.modelo_planilha_inscricoes", evento_id=evento_id),
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/modelo-planilha-inscricoes.xlsx")
@login_required
def modelo_planilha_inscricoes(evento_id):
    if session.get("modo_painel") != "associacao":
        abort(403)
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        abort(403)
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc),
        )
        if not cur.fetchone():
            abort(404)
    finally:
        cur.close()
        conn.close()

    try:
        from openpyxl import Workbook
    except ImportError:
        abort(503)

    wb = Workbook()
    ws = wb.active
    ws.title = "Inscrições"
    ws.append(
        [
            "Nome completo",
            "Data nascimento",
            "Peso",
            "Sexo (M/F/O)",
            "Professor",
            "Local de treino",
            "Categoria (opcional)",
        ]
    )
    ws.append(
        [
            "Exemplo Silva",
            "2010-05-20",
            "45.5",
            "M",
            "João Sensei",
            "Academia Central",
            "",
        ]
    )
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio,
        as_attachment=True,
        download_name="modelo_inscricoes_competicao.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp_eventos_competicoes.route("/aderir/<int:evento_id>", methods=["POST"])
@login_required
def aderir(evento_id):
    """Academia adere ao evento (aderiu=1)."""
    return _toggle_adesao(evento_id, 1)


@bp_eventos_competicoes.route("/desaderir/<int:evento_id>", methods=["POST"])
@login_required
def desaderir(evento_id):
    """Academia desiste da adesão (aderiu=0)."""
    return _toggle_adesao(evento_id, 0)


def _toggle_adesao(evento_id, aderiu):
    academia_id = request.form.get("academia_id", type=int) or request.args.get("academia_id", type=int)
    if not academia_id:
        flash("Academia não informada.", "danger")
        return redirect(url_for("eventos_competicoes.lista"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, data_fim FROM eventos_competicoes WHERE id = %s", (evento_id,))
        ev = cur.fetchone()
        if not ev:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        if _evento_encerrado(ev):
            flash("Evento encerrado. Não é possível alterar adesão.", "warning")
            return redirect(url_for("eventos_competicoes.lista"))

        cur.execute("""
            UPDATE eventos_competicoes_adesao SET aderiu = %s WHERE evento_id = %s AND academia_id = %s
        """, (aderiu, evento_id, academia_id))
        if cur.rowcount == 0:
            cur.execute("INSERT INTO eventos_competicoes_adesao (evento_id, academia_id, aderiu) VALUES (%s, %s, %s)",
                (evento_id, academia_id, aderiu))
        conn.commit()
        flash("Adesão atualizada." if aderiu else "Adesão removida.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("eventos_competicoes.lista", academia_id=academia_id))


@bp_eventos_competicoes.route("/<int:evento_id>/inscritos")
@login_required
def inscritos(evento_id):
    """Gestor academia: lista de inscritos, incluir avulso, enviar à associação."""
    academia_id = request.args.get("academia_id", type=int)
    if not academia_id:
        flash("Academia não informada.", "danger")
        return redirect(url_for("eventos_competicoes.lista"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT ec.id, ec.nome, ec.data_fim, ec.id_formulario, ec.tipo
            FROM eventos_competicoes ec
            INNER JOIN eventos_competicoes_adesao ea ON ea.evento_id = ec.id AND ea.academia_id = %s AND ea.aderiu = 1
            WHERE ec.id = %s
        """, (academia_id, evento_id))
        ev = cur.fetchone()
        if not ev:
            flash("Evento não encontrado ou academia não aderiu.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        encerrado = _evento_encerrado(ev)

        cur.execute("""
            SELECT i.id, i.aluno_id, i.academia_id, i.dados_form, i.inclusao_avulsa,
                   i.status, i.created_at, i.data_envio,
                   a.nome as aluno_nome, a.foto as aluno_foto
            FROM eventos_competicoes_inscricoes i
            LEFT JOIN alunos a ON a.id = i.aluno_id
            WHERE i.evento_id = %s AND i.academia_id = %s
            ORDER BY i.inclusao_avulsa ASC, a.nome ASC
        """, (evento_id, academia_id))
        inscricoes = cur.fetchall()
        for i in inscricoes:
            if i.get("dados_form") and isinstance(i["dados_form"], str):
                try:
                    i["dados_form"] = json.loads(i["dados_form"])
                except Exception:
                    i["dados_form"] = {}
        _completar_dados_form_com_aluno(cur, inscricoes)

        campos_form = _campos_form_efetivos_para_inscricoes(cur, ev.get("id_formulario"), inscricoes)

        # Token do link público desta academia neste evento (para o botão de gerar/copiar).
        cur.execute(
            "SELECT token_inscricao FROM eventos_competicoes_adesao "
            "WHERE evento_id = %s AND academia_id = %s", (evento_id, academia_id))
        _ad = cur.fetchone()
        token_inscricao = (_ad or {}).get("token_inscricao")
        link_inscricao = (url_for("eventos_competicoes.inscricao_academia",
                                  token=token_inscricao, _external=True)
                          if token_inscricao else None)

        # Locais de treino da academia, marcando os já vinculados a este evento.
        locais_evento = _locais_do_evento(cur, evento_id, academia_id)

        return render_template("eventos_competicoes/inscritos.html",
            evento=ev, inscricoes=inscricoes, academia_id=academia_id, encerrado=encerrado, campos_form=campos_form,
            link_inscricao=link_inscricao, locais_evento=locais_evento,
            back_url=_url_lista_eventos_competicoes(ev.get("tipo"), academia_id=academia_id))
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/enviar-inscricoes", methods=["POST"])
@login_required
def enviar_inscricoes(evento_id):
    """Gestor academia marca inscrições como enviadas à associação."""
    academia_id = request.form.get("academia_id", type=int)
    if not academia_id:
        flash("Academia não informada.", "danger")
        return redirect(url_for("eventos_competicoes.lista"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, data_fim, id_formulario FROM eventos_competicoes WHERE id = %s", (evento_id,))
        ev = cur.fetchone()
        if not ev or _evento_encerrado(ev):
            flash("Evento encerrado.", "warning")
            return redirect(url_for("eventos_competicoes.lista"))

        # Não deixa a academia enviar inscrição incompleta para a associação: acusa
        # quem está faltando dado e bloqueia o envio inteiro até corrigir.
        obrigatorios = _campos_obrigatorios_do_form(cur, ev.get("id_formulario"))
        if obrigatorios:
            cur.execute(
                """SELECT i.id, i.aluno_id, i.academia_id, i.dados_form,
                          COALESCE(a.nome, '') AS aluno_nome
                   FROM eventos_competicoes_inscricoes i
                   LEFT JOIN alunos a ON a.id = i.aluno_id
                   WHERE i.evento_id = %s AND i.academia_id = %s AND i.status != 'enviada'""",
                (evento_id, academia_id))
            linhas = cur.fetchall()
            # Completa com o cadastro do aluno antes de julgar: nome, data etc. de
            # quem tem cadastro vêm de lá, não do dados_form.
            _completar_dados_form_com_aluno(cur, linhas)
            incompletas = []
            for linha in linhas:
                faltam = _faltando_na_inscricao(linha["dados_form"], obrigatorios)
                if faltam:
                    nome = linha["aluno_nome"] or (
                        (linha["dados_form"] or {}).get("nome") or "Atleta")
                    incompletas.append(f"{nome} (falta: {', '.join(faltam)})")
            if incompletas:
                flash("Não foi possível enviar — há inscrições com dados obrigatórios "
                      "faltando. Corrija antes de enviar: " + "; ".join(incompletas[:8])
                      + ("…" if len(incompletas) > 8 else ""), "danger")
                return redirect(url_for("eventos_competicoes.inscritos",
                                        evento_id=evento_id, academia_id=academia_id))

        cur.execute("""
            UPDATE eventos_competicoes_inscricoes SET status = 'enviada', data_envio = NOW()
            WHERE evento_id = %s AND academia_id = %s AND status != 'enviada'
        """, (evento_id, academia_id))
        conn.commit()
        flash("Inscrições enviadas à associação.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))


def _redirect_apos_falha_edicao_inscricao(evento_id, academia_id, origem):
    if origem == "consolidar":
        return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))
    if academia_id:
        return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))
    return redirect(url_for("eventos_competicoes.lista"))


# Chaves do formulário cujo nome difere da coluna em `alunos`. As demais são iguais.
_CAMPO_FORM_PARA_COLUNA_ALUNO = {
    "endereco": "rua",
    "telefone_celular": "tel_celular",
    "telefone_residencial": "tel_residencial",
    "telefone_comercial": "tel_comercial",
    "telefone_outro": "tel_outro",
    "responsavel_grau_parentesco": "responsavel_parentesco",
    "data_cadastro_zempo": "zempo_registro_data",
}


def _completar_dados_form_com_aluno(cur, inscricoes):
    """
    Preenche, só para exibição, os campos vazios de `dados_form` com o cadastro
    do aluno.

    A inscrição guarda um retrato dos dados no momento em que foi feita, e o que
    não foi capturado ali aparecia como "—" nas listas, mesmo o aluno tendo a
    informação cadastrada. Isto NÃO altera o que está gravado na inscrição.
    """
    ids = {i.get("aluno_id") for i in inscricoes if i.get("aluno_id")}
    if not ids:
        return inscricoes

    marcadores = ", ".join(["%s"] * len(ids))
    cur.execute(f"SELECT * FROM alunos WHERE id IN ({marcadores})", tuple(ids))
    alunos = {a["id"]: a for a in cur.fetchall()}

    # `professor` e `local_treino` não existem no cadastro do aluno: saem da
    # academia onde a inscrição foi feita. O professor vem da turma do aluno
    # naquela academia; sem isso, do professor responsável dela.
    academias_insc = {i.get("academia_id") for i in inscricoes if i.get("academia_id")}
    locais, professores_academia = {}, {}
    if academias_insc:
        marcadores_ac = ", ".join(["%s"] * len(academias_insc))
        cur.execute(f"SELECT id, nome FROM academias WHERE id IN ({marcadores_ac})",
                    tuple(academias_insc))
        locais = {a["id"]: a["nome"] for a in cur.fetchall()}
        cur.execute(
            f"""SELECT id_academia, nome FROM professores
                WHERE id_academia IN ({marcadores_ac}) AND (ativo = 1 OR ativo IS NULL)
                ORDER BY id""", tuple(academias_insc))
        for p in cur.fetchall():
            professores_academia.setdefault(p["id_academia"], p["nome"])

    cur.execute(
        """SELECT at.aluno_id, t.id_academia, p.nome
           FROM aluno_turmas at
           JOIN turmas t ON t.TurmaID = at.TurmaID
           JOIN turma_professor tp ON tp.TurmaID = t.TurmaID
           JOIN professores p ON p.id = tp.professor_id""")
    professor_da_turma = {(r["aluno_id"], r["id_academia"]): r["nome"] for r in cur.fetchall()}

    # Faixa e academia são guardadas como id; nas listas o que interessa é o nome.
    cur.execute("SELECT id, faixa, graduacao FROM graduacao")
    faixas = {str(g["id"]): " ".join(x for x in (g.get("faixa"), g.get("graduacao")) if x)
              for g in cur.fetchall()}
    cur.execute("SELECT id, nome FROM academias")
    nomes_academia = {str(a["id"]): a["nome"] for a in cur.fetchall()}

    for inscricao in inscricoes:
        aluno = alunos.get(inscricao.get("aluno_id"))
        dados = inscricao.get("dados_form")
        if not isinstance(dados, dict):
            dados = _dados_form_inscricao_como_dict(dados)

        if aluno:
            for chave in list(CAMPOS_ALUNO_PADRAO):
                if dados.get(chave) in (None, ""):
                    valor = _valor_do_cadastro_aluno(aluno, chave)
                    if valor not in (None, ""):
                        dados[chave] = valor

        acad = inscricao.get("academia_id")
        if not dados.get("local_treino") and acad in locais:
            dados["local_treino"] = locais[acad]
        if not dados.get("professor") and acad:
            dados["professor"] = (professor_da_turma.get((inscricao.get("aluno_id"), acad))
                                  or professores_academia.get(acad, ""))

        # Só para exibição — a edição continua recebendo o id, que o <select> usa.
        if dados.get("graduacao_id"):
            dados["graduacao_id"] = faixas.get(str(dados["graduacao_id"]), dados["graduacao_id"])
        if dados.get("id_academia"):
            dados["id_academia"] = nomes_academia.get(str(dados["id_academia"]), dados["id_academia"])

        inscricao["dados_form"] = dados
    return inscricoes


def _campos_obrigatorios_do_form(cur, id_formulario):
    """[(campo_chave, label)] dos campos marcados como obrigatórios no formulário."""
    if not id_formulario:
        return []
    cur.execute(
        "SELECT campo_chave, label FROM formularios_campos "
        "WHERE formulario_id = %s AND obrigatorio = 1 ORDER BY ordem", (id_formulario,))
    return [(r["campo_chave"], r["label"]) for r in cur.fetchall()]


def _faltando_na_inscricao(dados_form, obrigatorios):
    """Rótulos dos campos obrigatórios ainda vazios numa inscrição. `categoria`
    é calculada pelo sistema e nunca cobrada aqui."""
    if isinstance(dados_form, str):
        dados_form = _dados_form_inscricao_como_dict(dados_form)
    dados_form = dados_form or {}
    faltam = []
    for chave, label in obrigatorios:
        if chave in ("categoria", "id_academia"):
            continue
        if not str(dados_form.get(chave) or "").strip():
            faltam.append(label or chave)
    return faltam


def _professor_e_local_da_academia(cur, academia_id, aluno_id=None):
    """
    {professor, local_treino} da academia onde a inscrição foi feita.

    O professor vem da turma que o aluno faz nessa academia; sem turma com
    professor, cai no professor responsável da academia.
    """
    if not academia_id:
        return {"professor": "", "local_treino": ""}

    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
    linha = cur.fetchone()
    local = (linha or {}).get("nome") or ""

    professor = ""
    if aluno_id:
        cur.execute(
            """SELECT p.nome FROM aluno_turmas at
               JOIN turmas t ON t.TurmaID = at.TurmaID AND t.id_academia = %s
               JOIN turma_professor tp ON tp.TurmaID = t.TurmaID
               JOIN professores p ON p.id = tp.professor_id
               WHERE at.aluno_id = %s LIMIT 1""",
            (academia_id, aluno_id))
        achado = cur.fetchone()
        professor = (achado or {}).get("nome") or ""
    if not professor:
        cur.execute(
            """SELECT nome FROM professores
               WHERE id_academia = %s AND (ativo = 1 OR ativo IS NULL)
               ORDER BY id LIMIT 1""", (academia_id,))
        achado = cur.fetchone()
        professor = (achado or {}).get("nome") or ""
    return {"professor": professor, "local_treino": local}


def _valor_do_cadastro_aluno(aluno, campo_chave):
    """
    Valor do cadastro do aluno para um campo do formulário de inscrição.

    Serve de preenchimento quando a inscrição não guardou aquele dado — assim a
    academia confere o que já existe em vez de redigitar tudo.
    """
    if not aluno:
        return ""
    # `categoria` e `aluno_modalidade_ids` não têm equivalente direto em `alunos`.
    if campo_chave in ("categoria", "aluno_modalidade_ids"):
        return ""
    coluna = _CAMPO_FORM_PARA_COLUNA_ALUNO.get(campo_chave, campo_chave)
    valor = aluno.get(coluna)
    if valor is None:
        return ""
    if hasattr(valor, "strftime"):          # date/datetime -> ISO, convertido depois para BR
        return valor.strftime("%Y-%m-%d")
    return valor


@bp_eventos_competicoes.route("/<int:evento_id>/editar-inscricao/<int:inscricao_id>", methods=["GET", "POST"])
@login_required
def editar_inscricao(evento_id, inscricao_id):
    """Gestor academia edita antes de enviar; gestor associação/admin também podem ajustar inscrições já enviadas (ex.: pela consolidação)."""
    academia_id = request.args.get("academia_id", type=int) or request.form.get("academia_id", type=int)
    origem = (request.args.get("origem") or request.form.get("origem") or "").strip()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc_sess = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        gestor_assoc_panel = session.get("modo_painel") == "associacao" and (
            current_user.has_role("gestor_associacao") or current_user.has_role("admin")
        )
        if not academia_id and gestor_assoc_panel and id_assoc_sess:
            cur.execute(
                """
                SELECT i.academia_id
                FROM eventos_competicoes_inscricoes i
                INNER JOIN eventos_competicoes ec ON ec.id = i.evento_id
                WHERE i.id = %s AND i.evento_id = %s AND ec.id_associacao = %s
                LIMIT 1
                """,
                (inscricao_id, evento_id, id_assoc_sess),
            )
            rw = cur.fetchone()
            if rw and rw.get("academia_id") is not None:
                academia_id = int(rw["academia_id"])

        if not academia_id:
            flash("Academia não informada.", "danger")
            return _redirect_apos_falha_edicao_inscricao(evento_id, None, origem)

        # Verificar inscricao
        cur.execute(
            """
            SELECT i.id, i.aluno_id, i.dados_form, i.status, a.nome as aluno_nome
            FROM eventos_competicoes_inscricoes i
            LEFT JOIN alunos a ON a.id = i.aluno_id
            WHERE i.id = %s AND i.evento_id = %s AND i.academia_id = %s
            """,
            (inscricao_id, evento_id, academia_id),
        )
        inscricao = cur.fetchone()
        if not inscricao:
            flash("Inscrição não encontrada.", "danger")
            return _redirect_apos_falha_edicao_inscricao(evento_id, academia_id, origem)

        if session.get("modo_painel") == "academia" and (
            current_user.has_role("gestor_academia") or current_user.has_role("professor")
        ):
            permitidas = _get_ids_academias(cur)
            if permitidas and int(academia_id) not in permitidas:
                flash("Acesso negado.", "danger")
                return _redirect_apos_falha_edicao_inscricao(evento_id, None, origem)

        # Verificar permissão: gestor_academia, gestor_associacao ou admin podem editar
        pode_editar = (
            current_user.has_role("gestor_academia")
            or current_user.has_role("gestor_associacao")
            or current_user.has_role("admin")
        )
        if not pode_editar:
            flash("Você não tem permissão para editar inscrições.", "danger")
            return _redirect_apos_falha_edicao_inscricao(evento_id, academia_id, origem)

        pode_editar_enviada = gestor_assoc_panel and (
            current_user.has_role("gestor_associacao") or current_user.has_role("admin")
        )
        if inscricao["status"] == "enviada" and not pode_editar_enviada:
            flash("Não é possível editar inscrição já enviada.", "warning")
            return _redirect_apos_falha_edicao_inscricao(evento_id, academia_id, origem)

        try:
            cur.execute(
                "SELECT id, nome, id_formulario, data_fim, categorias_modo FROM eventos_competicoes WHERE id = %s",
                (evento_id,),
            )
        except Exception:
            cur.execute(
                "SELECT id, nome, id_formulario, data_fim FROM eventos_competicoes WHERE id = %s",
                (evento_id,),
            )
        ev = cur.fetchone()
        if not ev or _evento_encerrado(ev):
            flash("Evento encerrado.", "warning")
            return _redirect_apos_falha_edicao_inscricao(evento_id, academia_id, origem)
        if "categorias_modo" not in ev:
            ev["categorias_modo"] = "padrao"
        cat_modo_ed = _as_texto_mysql(ev.get("categorias_modo")) or "padrao"
        ev["categorias_modo"] = cat_modo_ed

        if origem == "consolidar":
            back_url = url_for("eventos_competicoes.consolidar", evento_id=evento_id)
        else:
            back_url = url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id)

        cur.execute("SELECT campo_chave, label, obrigatorio, ordem FROM formularios_campos WHERE formulario_id = %s ORDER BY ordem",
            (ev["id_formulario"] or 0,))
        campos_form = cur.fetchall()
        
        # Verificar se o formulário tem peso e data_nascimento mas não tem categoria
        # Se sim, adicionar categoria automaticamente
        campos_chaves = [c["campo_chave"] for c in campos_form]
        tem_peso = "peso" in campos_chaves
        tem_data_nasc = "data_nascimento" in campos_chaves
        tem_categoria = "categoria" in campos_chaves
        
        if cat_modo_ed != "aproximacao" and tem_peso and tem_data_nasc and not tem_categoria:
            try:
                # Adicionar categoria após peso
                ordem_peso = next((c["ordem"] for c in campos_form if c["campo_chave"] == "peso"), len(campos_form))
                from utils.formularios_campos import get_label
                label_categoria = get_label("categoria")
                cur.execute("""
                    INSERT INTO formularios_campos (formulario_id, campo_chave, label, ordem)
                    VALUES (%s, %s, %s, %s)
                """, (ev["id_formulario"], "categoria", label_categoria, ordem_peso + 1))
                conn.commit()
                # Recarregar campos
                cur.execute("SELECT campo_chave, label, obrigatorio, ordem FROM formularios_campos WHERE formulario_id = %s ORDER BY ordem",
                    (ev["id_formulario"] or 0,))
                campos_form = cur.fetchall()
            except Exception:
                # Se já existe ou erro, continuar normalmente
                pass

        if not campos_form:
            campos_form = _campos_form_efetivos_para_inscricoes(
                cur, ev.get("id_formulario"), [inscricao]
            )
        else:
            campos_form = _merge_campos_form_faltantes_padrao_avulso(campos_form)

        campos_form_ed = [
            c
            for c in campos_form
            if not (cat_modo_ed == "aproximacao" and c.get("campo_chave") == "categoria")
        ]

        cur.execute("SELECT id, faixa, graduacao, categoria FROM graduacao ORDER BY id")
        graduacoes = cur.fetchall()
        cur.execute("SELECT TurmaID, Nome, Classificacao, DiasHorario FROM turmas WHERE id_academia = %s ORDER BY Nome", (academia_id,))
        turmas = cur.fetchall()
        
        # Buscar aluno para obter dados necessários para categorias
        aluno_edit = None
        if inscricao.get("aluno_id"):
            cur.execute("SELECT * FROM alunos WHERE id = %s", (inscricao["aluno_id"],))
            aluno_edit = cur.fetchone()
        
        # Buscar categorias disponíveis
        categorias_disponiveis = []
        if cat_modo_ed != "aproximacao" and aluno_edit:
            peso = request.form.get("campo_peso") or aluno_edit.get("peso")
            data_nascimento = request.form.get("campo_data_nascimento") or aluno_edit.get("data_nascimento")
            genero = request.form.get("campo_sexo") or aluno_edit.get("sexo")
            
            if peso and data_nascimento and genero:
                try:
                    from datetime import datetime as dt
                    if isinstance(data_nascimento, str):
                        nasc = dt.strptime(data_nascimento[:10], "%Y-%m-%d").date()
                    else:
                        nasc = data_nascimento
                    hoje = date.today()
                    idade_ano_civil = hoje.year - nasc.year
                    genero_upper = (genero or "").upper()
                    peso_float = float(peso)
                    
                    if genero_upper in ("M", "F") and peso_float > 0:
                        cur.execute("""
                            SELECT id, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max
                            FROM categorias
                            WHERE genero = %s
                            AND (idade_min IS NULL OR %s >= idade_min)
                            AND (idade_max IS NULL OR %s <= idade_max)
                            AND (peso_min IS NULL OR %s >= peso_min)
                            AND (peso_max IS NULL OR %s <= peso_max)
                            ORDER BY nome_categoria
                        """, (genero_upper, idade_ano_civil, idade_ano_civil, peso_float, peso_float))
                        categorias_disponiveis = cur.fetchall()
                except Exception:
                    categorias_disponiveis = []

        skip_success_flash = False
        if request.method == "POST":
            dados = {}
            for c in campos_form_ed:
                chave = c["campo_chave"]
                val = request.form.get(f"campo_{chave}", "")
                if isinstance(val, str):
                    val = val.strip()
                # Converter data de formato BR para ISO se necessário
                if chave in ("data_nascimento", "ultimo_exame_faixa", "rg_data_emissao", "data_cadastro_zempo") and val:
                    try:
                        from datetime import datetime as dt
                        val_str = val[:10].strip()
                        if val_str and '/' in val_str:
                            partes = val_str.split('/')
                            if len(partes) == 3:
                                val = f"{partes[2]}-{partes[1]}-{partes[0]}"
                    except Exception:
                        pass
                dados[chave] = val

            def _editar_inscricao_rerender_form():
                vi = {}
                for c in campos_form_ed:
                    ch = c["campo_chave"]
                    vv = request.form.get(f"campo_{ch}", "")
                    if isinstance(vv, str):
                        vv = vv.strip()
                    vi[ch] = vv
                an = None
                if academia_id:
                    cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
                    r = cur.fetchone()
                    an = r["nome"] if r else None
                return render_template(
                    "eventos_competicoes/editar_inscricao.html",
                    evento=ev,
                    inscricao=inscricao,
                    academia_id=academia_id,
                    academia_nome=an,
                    campos_form=campos_form_ed,
                    valores_iniciais=vi,
                    graduacoes=graduacoes,
                    turmas=turmas,
                    categorias_disponiveis=[],
                    aluno=aluno_edit,
                    back_url=back_url,
                    origem=origem,
                )

            if cat_modo_ed == "aproximacao":
                try:
                    peso_ed = float(str(dados.get("peso") or "").replace(",", "."))
                except (ValueError, TypeError):
                    peso_ed = None
                sx = _sexo_mfo_para_aprox(dados.get("sexo"))
                if sx:
                    dados["sexo"] = sx
                data_iso_aprox = _parse_data_nascimento_avulso(dados.get("data_nascimento"))
                if data_iso_aprox:
                    dados["data_nascimento"] = data_iso_aprox
                dn = (str(data_iso_aprox or "")).strip()
                if not dn or sx not in ("M", "F", "O") or peso_ed is None or peso_ed <= 0:
                    flash(
                        "No modo categorias por aproximação, data de nascimento, sexo e peso são obrigatórios "
                        "e o peso deve ser maior que zero.",
                        "danger",
                    )
                    return _editar_inscricao_rerender_form()
                cur.execute(
                    "SELECT COUNT(*) AS n FROM eventos_competicoes_categorias_aprox WHERE evento_id = %s",
                    (evento_id,),
                )
                n_faixas_aprox = int((cur.fetchone() or {}).get("n") or 0)
                cn, ci = _categoria_aprox_para_atleta(
                    cur,
                    evento_id,
                    data_iso_aprox,
                    sx,
                    peso_ed,
                )
                if not cn:
                    dados.pop("categoria", None)
                    dados.pop("categoria_aprox_id", None)
                    skip_success_flash = True
                    if n_faixas_aprox == 0:
                        flash(
                            "Dados da inscrição foram salvos. Não há faixas de aproximação cadastradas neste evento — "
                            "cadastre-as em «Categorias por aproximação» para atribuir categoria automaticamente.",
                            "warning",
                        )
                    else:
                        flash(
                            "Dados da inscrição foram salvos. Nenhuma faixa cadastrada combina com ano de nascimento, "
                            "sexo e peso informados. Para atletas com sexo «Outro», inclua faixa com gênero «Ambos». "
                            "Ajuste faixas ou dados e use «Recalcular categorias» no evento se precisar.",
                            "warning",
                        )
                else:
                    dados["categoria"] = cn
                    if ci:
                        dados["categoria_aprox_id"] = int(ci)
            cur.execute("""
                UPDATE eventos_competicoes_inscricoes SET dados_form = %s WHERE id = %s
            """, (json.dumps(dados, ensure_ascii=False), inscricao_id))
            conn.commit()
            if not skip_success_flash:
                flash("Inscrição atualizada.", "success")
            if origem == "consolidar":
                return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))
            return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))

        # GET: montar valores iniciais
        valores_iniciais = {}
        dados_atuais = {}
        if inscricao.get("dados_form"):
            if isinstance(inscricao["dados_form"], str):
                try:
                    dados_atuais = json.loads(inscricao["dados_form"])
                except Exception:
                    pass
            else:
                dados_atuais = inscricao["dados_form"]
        for c in campos_form_ed:
            chave = c["campo_chave"]
            v = dados_atuais.get(chave, "")
            # O que não foi capturado na inscrição vem do cadastro do aluno, em vez
            # de aparecer em branco para ser redigitado.
            if (v is None or v == "") and aluno_edit:
                v = _valor_do_cadastro_aluno(aluno_edit, chave)
            # Professor e local de treino saem da academia onde a inscrição foi feita.
            if (v is None or v == "") and chave in ("professor", "local_treino"):
                v = _professor_e_local_da_academia(
                    cur, academia_id, inscricao.get("aluno_id")).get(chave, "")
            # Converter datas para formato BR
            if chave in ("data_nascimento", "ultimo_exame_faixa", "rg_data_emissao", "data_cadastro_zempo") and v:
                try:
                    from datetime import datetime as dt
                    # Tentar converter de ISO para BR
                    if isinstance(v, str) and '-' in v:
                        d = dt.strptime(v[:10], "%Y-%m-%d")
                        v = d.strftime("%d/%m/%Y")
                except Exception:
                    pass
            elif chave == "id_academia":
                # Usar academia_id atual
                v = academia_id or v
            valores_iniciais[chave] = v

        # Buscar nome da academia para exibição
        academia_nome = None
        if academia_id:
            cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
            ac_row = cur.fetchone()
            academia_nome = ac_row["nome"] if ac_row else None

        return render_template(
            "eventos_competicoes/editar_inscricao.html",
            evento=ev,
            inscricao=inscricao,
            academia_id=academia_id,
            academia_nome=academia_nome,
            campos_form=campos_form_ed,
            valores_iniciais=valores_iniciais,
            graduacoes=graduacoes,
            turmas=turmas,
            categorias_disponiveis=categorias_disponiveis,
            aluno=aluno_edit,
            back_url=back_url,
            origem=origem,
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/cancelar-inscricao/<int:inscricao_id>", methods=["POST"])
@login_required
def cancelar_inscricao(evento_id, inscricao_id):
    """Gestor academia cancela inscrição antes de enviar."""
    academia_id = request.form.get("academia_id", type=int)
    if not academia_id:
        flash("Academia não informada.", "danger")
        return redirect(url_for("eventos_competicoes.lista"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Verificar inscricao
        cur.execute("""
            SELECT i.id, i.status FROM eventos_competicoes_inscricoes i
            WHERE i.id = %s AND i.evento_id = %s AND i.academia_id = %s
        """, (inscricao_id, evento_id, academia_id))
        inscricao = cur.fetchone()
        if not inscricao:
            flash("Inscrição não encontrada.", "danger")
            return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))

        if inscricao["status"] == "enviada":
            flash("Não é possível cancelar inscrição já enviada.", "warning")
            return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))

        cur.execute("DELETE FROM eventos_competicoes_inscricoes WHERE id = %s", (inscricao_id,))
        conn.commit()
        flash("Inscrição cancelada.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))


@bp_eventos_competicoes.route("/<int:evento_id>/excluir-inscricao-consolidar/<int:inscricao_id>", methods=["POST"])
@login_required
def excluir_inscricao_consolidar(evento_id, inscricao_id):
    """Gestor da associação (ou admin) exclui inscrição a partir do consolidar."""
    if session.get("modo_painel") != "associacao" or not (
        current_user.has_role("gestor_associacao") or current_user.has_role("admin")
    ):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        return redirect(url_for("associacao.gerenciamento_associacao"))

    agr = (request.form.get("agrupamento") or "academia").strip()
    if agr not in ("academia", "categoria"):
        agr = "academia"
    redir = lambda: redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id, agrupamento=agr))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT i.id
            FROM eventos_competicoes_inscricoes i
            INNER JOIN eventos_competicoes ec ON ec.id = i.evento_id
            INNER JOIN academias ac ON ac.id = i.academia_id
            WHERE i.id = %s AND i.evento_id = %s AND ec.id_associacao = %s AND ac.id_associacao = %s
            """,
            (inscricao_id, evento_id, id_assoc, id_assoc),
        )
        if not cur.fetchone():
            flash("Inscrição não encontrada ou sem permissão.", "danger")
            return redir()
        cur.execute("DELETE FROM eventos_competicoes_inscricoes WHERE id = %s", (inscricao_id,))
        conn.commit()
        flash("Inscrição excluída.", "success")
    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "excluir_inscricao_consolidar evento_id=%s inscricao_id=%s", evento_id, inscricao_id
        )
        flash("Não foi possível excluir a inscrição.", "danger")
    finally:
        cur.close()
        conn.close()
    return redir()


@bp_eventos_competicoes.route("/<int:evento_id>/incluir-avulso", methods=["GET", "POST"])
@login_required
def incluir_avulso(evento_id):
    """Gestor academia inclui aluno avulso (manual)."""
    academia_id = request.args.get("academia_id", type=int) or request.form.get("academia_id", type=int)
    if not academia_id:
        flash("Academia não informada.", "danger")
        return redirect(url_for("eventos_competicoes.lista"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT ec.id, ec.nome, ec.data_fim, ec.id_formulario, ec.tipo
            FROM eventos_competicoes ec
            INNER JOIN eventos_competicoes_adesao ea ON ea.evento_id = ec.id AND ea.academia_id = %s AND ea.aderiu = 1
            WHERE ec.id = %s
        """, (academia_id, evento_id))
        ev = cur.fetchone()
        if not ev or _evento_encerrado(ev):
            flash("Evento não encontrado ou encerrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))

        # Só os alunos que têm ESTA academia como PRINCIPAL entram na inscrição do
        # evento. Quem é vinculado secundário se inscreve pela academia principal
        # dele — evita o mesmo atleta inscrito por duas academias.
        cur.execute("SELECT a.id, a.nome FROM alunos a WHERE a.id_academia = %s ORDER BY a.nome",
                    (academia_id,))
        alunos = cur.fetchall()

        # Campos do formulário do evento, para permitir inscrever quem não tem cadastro.
        cur.execute(
            "SELECT campo_chave, label, obrigatorio, ordem FROM formularios_campos "
            "WHERE formulario_id = %s ORDER BY ordem", (ev.get("id_formulario") or 0,))
        campos_form = _merge_campos_form_faltantes_padrao_avulso(cur.fetchall())
        cur.execute("SELECT id, faixa, graduacao FROM graduacao ORDER BY id")
        graduacoes = cur.fetchall()

        if request.method == "POST":
            aluno_id = request.form.get("aluno_id", type=int)
            if aluno_id:
                cur.execute("SELECT 1 FROM eventos_competicoes_inscricoes WHERE evento_id=%s AND academia_id=%s AND aluno_id=%s",
                    (evento_id, academia_id, aluno_id))
                if cur.fetchone():
                    flash("Aluno já inscrito.", "warning")
                else:
                    cur.execute("""
                        INSERT INTO eventos_competicoes_inscricoes (evento_id, academia_id, aluno_id, usuario_inscricao_id, inclusao_avulsa, status)
                        VALUES (%s, %s, %s, %s, 1, 'confirmada')
                    """, (evento_id, academia_id, aluno_id, current_user.id))
                    conn.commit()
                    flash("Aluno incluído.", "success")
            else:
                # Atleta sem cadastro no sistema: os dados digitados viram a
                # inscrição, sem criar um aluno.
                dados = {}
                for c in campos_form:
                    chave = c["campo_chave"]
                    valor = (request.form.get(f"campo_{chave}") or "").strip()
                    if chave in ("data_nascimento", "ultimo_exame_faixa", "rg_data_emissao") and valor and "/" in valor:
                        partes = valor[:10].split("/")
                        if len(partes) == 3:
                            valor = f"{partes[2]}-{partes[1]}-{partes[0]}"
                    dados[chave] = valor
                dados.setdefault("id_academia", str(academia_id))

                if not (dados.get("nome") or "").strip():
                    flash("Informe ao menos o nome do atleta.", "warning")
                else:
                    cur.execute(
                        """INSERT INTO eventos_competicoes_inscricoes
                           (evento_id, academia_id, aluno_id, usuario_inscricao_id,
                            dados_form, inclusao_avulsa, status)
                           VALUES (%s, %s, NULL, %s, %s, 1, 'confirmada')""",
                        (evento_id, academia_id, current_user.id, json.dumps(dados, ensure_ascii=False)))
                    conn.commit()
                    flash(f"{dados['nome']} inscrito(a).", "success")
            return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))

        return render_template("eventos_competicoes/incluir_avulso.html",
            evento=ev, alunos=alunos, academia_id=academia_id, campos_form=campos_form,
            graduacoes=graduacoes,
            back_url=url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/inscrever", methods=["GET", "POST"])
@login_required
def inscrever(evento_id):
    """Aluno ou responsável realiza inscrição preenchendo o formulário."""
    academia_id = request.args.get("academia_id", type=int) or request.form.get("academia_id", type=int)
    aluno_id = request.args.get("aluno_id", type=int) or request.form.get("aluno_id", type=int)
    if not academia_id:
        flash("Academia não informada.", "danger")
        return redirect(url_for("painel.home"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT ec.id, ec.nome, ec.data_fim, ec.id_formulario, ec.categorias_modo
                FROM eventos_competicoes ec
                INNER JOIN eventos_competicoes_adesao ea ON ea.evento_id = ec.id AND ea.academia_id = %s AND ea.aderiu = 1
                WHERE ec.id = %s
                """,
                (academia_id, evento_id),
            )
        except Exception:
            cur.execute(
                """
                SELECT ec.id, ec.nome, ec.data_fim, ec.id_formulario
                FROM eventos_competicoes ec
                INNER JOIN eventos_competicoes_adesao ea ON ea.evento_id = ec.id AND ea.academia_id = %s AND ea.aderiu = 1
                WHERE ec.id = %s
                """,
                (academia_id, evento_id),
            )
        ev = cur.fetchone()
        if not ev:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("painel.home"))
        if "categorias_modo" not in ev:
            ev["categorias_modo"] = "padrao"
        cat_modo_insc = _as_texto_mysql(ev.get("categorias_modo")) or "padrao"
        ev["categorias_modo"] = cat_modo_insc
        if _evento_encerrado(ev):
            flash("Inscrições encerradas.", "warning")
            return redirect(url_for("painel.home"))

        # Aluno ou responsável: verificar permissão
        alunos_permitidos = []
        if current_user.has_role("aluno"):
            # Inscrição só pela academia principal do aluno.
            cur.execute("SELECT a.id FROM alunos a WHERE a.id = %s AND a.id_academia = %s",
                        (aluno_id or 0, academia_id))
            if cur.fetchone():
                alunos_permitidos = [aluno_id]
        elif current_user.has_role("responsavel"):
            cur.execute("SELECT aluno_id FROM responsavel_alunos WHERE usuario_id = %s", (current_user.id,))
            ids_resp = [r["aluno_id"] for r in cur.fetchall()]
            if ids_resp:
                ph = ",".join(["%s"] * len(ids_resp))
                cur.execute(f"SELECT a.id FROM alunos a WHERE a.id IN ({ph}) AND a.id_academia = %s",
                            tuple(ids_resp) + (academia_id,))
                alunos_permitidos = [r["id"] for r in cur.fetchall()]
            else:
                alunos_permitidos = []
        else:
            flash("Acesso negado.", "danger")
            return redirect(url_for("painel.home"))

        if not alunos_permitidos:
            flash("Nenhum aluno vinculado para inscrição.", "danger")
            return redirect(url_for("painel.home"))

        # Se responsável tem vários alunos, precisa escolher
        if len(alunos_permitidos) > 1 and not aluno_id:
            cur.execute("SELECT id, nome FROM alunos WHERE id IN (%s) ORDER BY nome" % ",".join(["%s"] * len(alunos_permitidos)),
                tuple(alunos_permitidos))
            alunos_sel = cur.fetchall()
            return render_template("eventos_competicoes/escolher_aluno.html",
                evento=ev, alunos=alunos_sel, academia_id=academia_id, back_url=request.referrer or url_for("painel.home"))

        aluno_id = aluno_id or alunos_permitidos[0]

        cur.execute("SELECT * FROM alunos WHERE id = %s", (aluno_id,))
        aluno = cur.fetchone()
        if not aluno or aluno_id not in alunos_permitidos:
            flash("Aluno não encontrado.", "danger")
            return redirect(url_for("painel.home"))

        # Removida verificação de "aluno já inscrito" pois agora pode haver múltiplas inscrições (uma por categoria)

        cur.execute("SELECT campo_chave, label, obrigatorio, ordem FROM formularios_campos WHERE formulario_id = %s ORDER BY ordem",
            (ev["id_formulario"] or 0,))
        campos_form = cur.fetchall()
        if not campos_form:
            flash("Formulário sem campos configurados.", "warning")
            return redirect(request.referrer or url_for("painel.home"))
        
        # Verificar se o formulário tem peso, data_nascimento e sexo mas não tem categoria
        # Se sim, adicionar categoria automaticamente
        campos_chaves = [c["campo_chave"] for c in campos_form]
        tem_peso = "peso" in campos_chaves
        tem_data_nasc = "data_nascimento" in campos_chaves
        tem_sexo = "sexo" in campos_chaves
        tem_categoria = "categoria" in campos_chaves
        
        if cat_modo_insc != "aproximacao" and tem_peso and tem_data_nasc and tem_sexo and not tem_categoria:
            try:
                # Adicionar categoria após peso
                ordem_peso = next((c["ordem"] for c in campos_form if c["campo_chave"] == "peso"), len(campos_form))
                from utils.formularios_campos import get_label
                label_categoria = get_label("categoria")
                cur.execute("""
                    INSERT INTO formularios_campos (formulario_id, campo_chave, label, ordem)
                    VALUES (%s, %s, %s, %s)
                """, (ev["id_formulario"], "categoria", label_categoria, ordem_peso + 1))
                conn.commit()
                # Recarregar campos
                cur.execute("SELECT campo_chave, label, obrigatorio, ordem FROM formularios_campos WHERE formulario_id = %s ORDER BY ordem",
                    (ev["id_formulario"] or 0,))
                campos_form = cur.fetchall()
                # Atualizar lista de chaves
                campos_chaves = [c["campo_chave"] for c in campos_form]
                tem_categoria = "categoria" in campos_chaves
            except Exception as e:
                # Se já existe ou erro, continuar normalmente
                import traceback
                print(f"Erro ao adicionar categoria ao formulário: {e}")
                print(traceback.format_exc())
                pass

        campos_form_insc = [
            c
            for c in campos_form
            if not (cat_modo_insc == "aproximacao" and c.get("campo_chave") == "categoria")
        ]

        cur.execute("SELECT id, faixa, graduacao, categoria FROM graduacao ORDER BY id")
        graduacoes = cur.fetchall()
        cur.execute("SELECT TurmaID, Nome, Classificacao, DiasHorario FROM turmas WHERE id_academia = %s ORDER BY Nome", (academia_id,))
        turmas = cur.fetchall()
        
        # Buscar categorias disponíveis se aluno tem peso, data_nascimento e sexo
        categorias_disponiveis = []
        if cat_modo_insc != "aproximacao" and aluno.get("peso") and aluno.get("data_nascimento") and aluno.get("sexo"):
            try:
                from datetime import datetime as dt
                nasc = dt.strptime(str(aluno["data_nascimento"])[:10], "%Y-%m-%d").date()
                hoje = date.today()
                idade_ano_civil = hoje.year - nasc.year
                genero_upper = (aluno.get("sexo") or "").upper()
                peso_float = float(aluno.get("peso") or 0)
                
                if genero_upper in ("M", "F") and peso_float > 0:
                    # Mapear M/F para MASCULINO/FEMININO
                    genero_db = "MASCULINO" if genero_upper == "M" else "FEMININO" if genero_upper == "F" else genero_upper
                    cur.execute("""
                        SELECT id, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max
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
                    """, (genero_db, idade_ano_civil, idade_ano_civil, peso_float, peso_float))
                    categorias_disponiveis = cur.fetchall()
            except Exception:
                categorias_disponiveis = []

        if request.method == "POST":
            categorias_selecionadas = request.form.getlist("campo_categoria[]")

            dados_base = {}
            for c in campos_form_insc:
                chave = c["campo_chave"]
                val = request.form.get(f"campo_{chave}", "")
                if isinstance(val, str):
                    val = val.strip()
                dados_base[chave] = val

            # Não deixa gravar inscrição incompleta: os campos que o formulário
            # marca como obrigatórios têm de vir preenchidos.
            obrigatorios_insc = [(c["campo_chave"], c.get("label"))
                                 for c in campos_form_insc if c.get("obrigatorio")]
            faltam_insc = _faltando_na_inscricao(dados_base, obrigatorios_insc)
            if faltam_insc:
                flash("Preencha os campos obrigatórios: " + ", ".join(faltam_insc), "danger")
                return redirect(request.url)

            inscricoes_criadas = 0
            if cat_modo_insc == "aproximacao":
                try:
                    peso_ap = float(str(dados_base.get("peso") or "").replace(",", "."))
                except (ValueError, TypeError):
                    peso_ap = None
                cn, ci = _categoria_aprox_para_atleta(
                    cur,
                    evento_id,
                    dados_base.get("data_nascimento"),
                    dados_base.get("sexo"),
                    peso_ap,
                )
                if not cn:
                    flash(
                        "Não foi possível definir a categoria automaticamente (data de nascimento, sexo e peso devem "
                        "estar de acordo com as faixas da competição). Verifique os dados ou fale com a organização.",
                        "danger",
                    )
                    valores_iniciais = {}
                    for c in campos_form_insc:
                        chave = c["campo_chave"]
                        val = request.form.get(f"campo_{chave}", "")
                        if isinstance(val, str):
                            val = val.strip()
                        valores_iniciais[chave] = val
                    academia_nome = None
                    if academia_id:
                        cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
                        ac_row = cur.fetchone()
                        academia_nome = ac_row["nome"] if ac_row else None
                    return render_template(
                        "eventos_competicoes/inscrever.html",
                        evento=ev,
                        aluno=aluno,
                        academia_id=academia_id,
                        academia_nome=academia_nome,
                        campos_form=campos_form_insc,
                        valores_iniciais=valores_iniciais,
                        graduacoes=graduacoes,
                        turmas=turmas,
                        categorias_disponiveis=[],
                        back_url=request.referrer or url_for("painel.home"),
                    )
                dados = dados_base.copy()
                dados["categoria"] = cn
                if ci:
                    dados["categoria_aprox_id"] = int(ci)
                cur.execute(
                    """
                    INSERT INTO eventos_competicoes_inscricoes (evento_id, academia_id, aluno_id, usuario_inscricao_id, dados_form, inclusao_avulsa, status)
                    VALUES (%s, %s, %s, %s, %s, 0, 'confirmada')
                    """,
                    (evento_id, academia_id, aluno_id, current_user.id, json.dumps(dados, ensure_ascii=False)),
                )
                inscricoes_criadas = 1
            elif not categorias_selecionadas:
                dados = dados_base.copy()
                cur.execute(
                    """
                    INSERT INTO eventos_competicoes_inscricoes (evento_id, academia_id, aluno_id, usuario_inscricao_id, dados_form, inclusao_avulsa, status)
                    VALUES (%s, %s, %s, %s, %s, 0, 'confirmada')
                    """,
                    (evento_id, academia_id, aluno_id, current_user.id, json.dumps(dados, ensure_ascii=False)),
                )
                inscricoes_criadas = 1
            else:
                for categoria_nome in categorias_selecionadas:
                    dados = dados_base.copy()
                    dados["categoria"] = categoria_nome
                    cur.execute(
                        """
                        INSERT INTO eventos_competicoes_inscricoes (evento_id, academia_id, aluno_id, usuario_inscricao_id, dados_form, inclusao_avulsa, status)
                        VALUES (%s, %s, %s, %s, %s, 0, 'confirmada')
                        """,
                        (evento_id, academia_id, aluno_id, current_user.id, json.dumps(dados, ensure_ascii=False)),
                    )
                    inscricoes_criadas += 1

            # Atualizar dados do aluno conforme form (mapear form -> coluna DB)
            dados = dados_base.copy()  # Usar dados_base para atualização do aluno
            MAPEAMENTO_FORM_ALUNO = {
                "nome": "nome", "sexo": "sexo", "nome_pai": "nome_pai", "nome_mae": "nome_mae",
                "peso": "peso", "cpf": "cpf", "rg": "rg", "nacionalidade": "nacionalidade",
                "orgao_emissor": "orgao_emissor", "rg_data_emissao": "rg_data_emissao",
                "cep": "cep", "endereco": "rua", "numero": "numero", "bairro": "bairro",
                "cidade": "cidade", "estado": "estado", "complemento": "complemento",
                "email": "email", "observacoes": "observacoes", "zempo": "zempo",
                "responsavel_nome": "responsavel_nome", "responsavel_parentesco": "responsavel_parentesco",
                "responsavel_grau_parentesco": "responsavel_grau_parentesco",
                "responsavel_financeiro_nome": "responsavel_financeiro_nome",
                "responsavel_financeiro_cpf": "responsavel_financeiro_cpf",
                "telefone_celular": "tel_celular", "telefone_residencial": "tel_residencial",
                "telefone_comercial": "tel_comercial", "telefone_outro": "tel_outro",
                "ultimo_exame_faixa": "ultimo_exame_faixa", "data_cadastro_zempo": "data_cadastro_zempo",
                "graduacao_id": "graduacao_id", "TurmaID": "TurmaID", "data_nascimento": "data_nascimento",
            }
            for chave, val in dados.items():
                col = MAPEAMENTO_FORM_ALUNO.get(chave)
                if not col or chave in ("id_academia", "aluno_modalidade_ids", "foto"):
                    continue
                if col in ("graduacao_id", "TurmaID"):
                    try:
                        val = int(val) if val else None
                    except (ValueError, TypeError):
                        val = None
                elif col == "peso":
                    try:
                        val = float(val) if val else None
                    except (ValueError, TypeError):
                        val = None
                elif col in ("data_nascimento", "ultimo_exame_faixa", "rg_data_emissao", "data_cadastro_zempo"):
                    try:
                        from datetime import datetime as dt
                        val_str = str(val)[:10].strip()
                        if not val_str:
                            val = None
                        else:
                            # Tentar formato BR primeiro (dd/mm/yyyy), depois ISO (yyyy-mm-dd)
                            try:
                                val = dt.strptime(val_str, "%d/%m/%Y").date()
                            except ValueError:
                                try:
                                    val = dt.strptime(val_str, "%Y-%m-%d").date()
                                except ValueError:
                                    val = None
                    except Exception:
                        val = None
                if val is not None:
                    try:
                        cur.execute(f"UPDATE alunos SET `{col}` = %s WHERE id = %s", (val, aluno_id))
                    except Exception:
                        pass
            conn.commit()
            if cat_modo_insc == "aproximacao":
                flash("Inscrição realizada com sucesso! Categoria definida automaticamente.", "success")
            elif categorias_selecionadas and len(categorias_selecionadas) > 1:
                flash(f"{inscricoes_criadas} inscrições realizadas com sucesso! Uma para cada categoria selecionada.", "success")
            else:
                flash("Inscrição realizada com sucesso!", "success")
            return redirect(url_for("eventos_competicoes.disponiveis", aluno_id=aluno_id))

        # GET: montar valores iniciais do aluno (mapear col DB -> form)
        REV_MAP = {"rua": "endereco", "tel_celular": "telefone_celular", "tel_residencial": "telefone_residencial",
                   "tel_comercial": "telefone_comercial", "tel_outro": "telefone_outro", "telefone": "telefone_celular"}
        valores_iniciais = {}
        for c in campos_form_insc:
            chave = c["campo_chave"]
            v = aluno.get(chave)
            if v is None and chave in ("endereco",):
                v = aluno.get("rua")
            elif v is None and chave == "telefone_celular":
                v = aluno.get("tel_celular") or aluno.get("telefone")
            elif v is None and chave in ("telefone_residencial", "telefone_comercial", "telefone_outro"):
                v = aluno.get("tel_" + chave.split("_")[1])
            if hasattr(v, "strftime"):
                # Para input type="text" com formato BR, converter para BR
                v = v.strftime("%d/%m/%Y") if v else ""
            elif chave == "id_academia":
                # Se vier ID, usar o ID da academia atual
                v = academia_id or v
            elif chave == "graduacao_id" and v:
                # Manter ID para o value (o select já mostra o nome)
                pass
            elif chave == "TurmaID" and v:
                # Manter ID para o value (o select já mostra o nome)
                pass
            valores_iniciais[chave] = v or ""

        # Buscar nome da academia para exibição
        academia_nome = None
        if academia_id:
            cur.execute("SELECT nome FROM academias WHERE id = %s", (academia_id,))
            ac_row = cur.fetchone()
            academia_nome = ac_row["nome"] if ac_row else None
        
        return render_template(
            "eventos_competicoes/inscrever.html",
            evento=ev,
            aluno=aluno,
            academia_id=academia_id,
            academia_nome=academia_nome,
            campos_form=campos_form_insc,
            valores_iniciais=valores_iniciais,
            graduacoes=graduacoes,
            turmas=turmas,
            categorias_disponiveis=categorias_disponiveis,
            back_url=request.referrer or url_for("painel.home"),
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/consolidar")
@login_required
def consolidar(evento_id):
    """Associação: lista academias com alunos inscritos, botão exportar PDF/Excel."""
    if session.get("modo_painel") != "associacao" or not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT ec.id, ec.nome, ec.data_fim, ec.id_formulario, ec.categorias_modo, ec.tipo, ec.inscricao_modo
                FROM eventos_competicoes ec WHERE ec.id = %s AND ec.id_associacao = %s
                """,
                (evento_id, id_assoc),
            )
        except Exception:
            cur.execute(
                """
                SELECT ec.id, ec.nome, ec.data_fim, ec.id_formulario, ec.categorias_modo, ec.tipo
                FROM eventos_competicoes ec WHERE ec.id = %s AND ec.id_associacao = %s
                """,
                (evento_id, id_assoc),
            )
        ev = cur.fetchone()
        if not ev:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        if "categorias_modo" not in ev:
            ev["categorias_modo"] = "padrao"
        if "tipo" not in ev:
            ev["tipo"] = None
        if "inscricao_modo" not in ev:
            ev["inscricao_modo"] = "academias_formulario"
        else:
            ev["inscricao_modo"] = _as_texto_mysql(ev.get("inscricao_modo")) or "academias_formulario"
        ev["categorias_modo"] = _as_texto_mysql(ev.get("categorias_modo")) or "padrao"
        if ev.get("tipo") is not None:
            ev["tipo"] = _as_texto_mysql(ev.get("tipo"))

        inscricoes = _fetch_inscricoes_consolidar_associacao(cur, evento_id, id_assoc)
        academias_com_inscricoes = _agrupar_inscricoes_por_academia_categoria(inscricoes)
        try:
            aderentes_ids = _ids_academias_aderentes_evento(cur, evento_id)
        except Exception:
            aderentes_ids = set()
        for _aid, ac_data in academias_com_inscricoes.items():
            ac_data["aderiu_ao_evento"] = int(_aid) in aderentes_ids

        # Calcular totais
        for ac_id, ac_data in academias_com_inscricoes.items():
            try:
                total_por_categoria = {cat: len(alunos) for cat, alunos in ac_data.get("categorias", {}).items()}
                ac_data["total_inscritos"] = sum(total_por_categoria.values())
                ac_data["total_por_categoria"] = total_por_categoria
            except Exception as e:
                import logging
                logging.error(f"Erro ao calcular totais para academia {ac_id}: {e}")
                ac_data["total_inscritos"] = 0
                ac_data["total_por_categoria"] = {}

        campos_form = _campos_form_efetivos_para_inscricoes(cur, ev.get("id_formulario"), inscricoes)
        
        # Buscar configuração de exportação salva (se o campo existir)
        configuracao_exportacao = None
        try:
            cur.execute("SELECT configuracao_exportacao FROM eventos_competicoes WHERE id = %s", (evento_id,))
            ev_row = cur.fetchone()
            if ev_row and ev_row.get("configuracao_exportacao"):
                try:
                    config_str = ev_row["configuracao_exportacao"]
                    if isinstance(config_str, str) and config_str.strip():
                        configuracao_exportacao = json.loads(config_str)
                    elif isinstance(config_str, dict):
                        configuracao_exportacao = config_str
                except (json.JSONDecodeError, TypeError) as e:
                    # Log do erro mas continua sem configuração
                    import logging
                    logging.warning(f"Erro ao parsear configuracao_exportacao: {e}")
                    pass
        except Exception as e:
            # Campo não existe ainda ou erro na query, usar None
            import logging
            logging.warning(f"Erro ao buscar configuracao_exportacao: {e}")
            pass

        # Preparar agrupamento por categoria também
        categorias_com_inscricoes = {}
        for ac_id, ac_data in academias_com_inscricoes.items():
            for categoria, alunos in ac_data.get("categorias", {}).items():
                if categoria not in categorias_com_inscricoes:
                    categorias_com_inscricoes[categoria] = {
                        "academias": {},
                        "total_inscritos": 0
                    }
                # Agrupar alunos por academia dentro da categoria
                for aluno in alunos:
                    academia_nome = ac_data.get("academia_nome", "Academia Desconhecida")
                    if academia_nome not in categorias_com_inscricoes[categoria]["academias"]:
                        categorias_com_inscricoes[categoria]["academias"][academia_nome] = []
                    categorias_com_inscricoes[categoria]["academias"][academia_nome].append(aluno)
        
        # Calcular totais por categoria
        for categoria, cat_data in categorias_com_inscricoes.items():
            total = sum(len(alunos) for alunos in cat_data["academias"].values())
            cat_data["total_inscritos"] = total
        
        # Calcular total geral de inscritos
        total_geral_inscritos = len(inscricoes)
        
        # Buscar mapeamento de academias e graduações para exibir nomes ao invés de IDs
        academias_map = {}
        graduacoes_map = {}
        try:
            # Buscar todas as academias da associação
            cur.execute("SELECT id, nome FROM academias WHERE id_associacao = %s", (id_assoc,))
            for row in cur.fetchall():
                academias_map[str(row["id"])] = row["nome"]
            
            # Buscar todas as graduações
            cur.execute("SELECT id, faixa, graduacao, categoria FROM graduacao")
            for row in cur.fetchall():
                graduacao_nome = f"{row.get('faixa', '')} {row.get('graduacao', '')} {row.get('categoria', '')}".strip()
                graduacoes_map[str(row["id"])] = graduacao_nome if graduacao_nome else f"ID {row['id']}"
        except Exception as e:
            import logging
            logging.warning(f"Erro ao buscar mapeamentos de academias/graduações: {e}")
        
        # Obter tipo de agrupamento (padrão: academia)
        agrupamento = request.args.get("agrupamento", "academia")
        
        try:
            return render_template("eventos_competicoes/consolidar.html",
                evento=ev, academias_com_inscricoes=academias_com_inscricoes, 
                categorias_com_inscricoes=categorias_com_inscricoes,
                campos_form=campos_form, agrupamento=agrupamento,
                configuracao_exportacao=configuracao_exportacao or {},
                total_geral_inscritos=total_geral_inscritos,
                academias_map=academias_map,
                graduacoes_map=graduacoes_map,
                back_url=_back_por_tipo_e_modo(evento_id, ev.get("tipo"), cur=cur),
            )
        except Exception as e:
            import logging
            logging.error(f"Erro ao renderizar template consolidar: {e}", exc_info=True)
            flash(f"Erro ao carregar página: {str(e)}", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/anexo/<int:anexo_id>/download")
@login_required
def download_anexo(anexo_id):
    """Download de anexo de evento/competição."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    
    try:
        # Buscar anexo
        cur.execute("""
            SELECT eca.*, ec.id_associacao
            FROM eventos_competicoes_anexos eca
            INNER JOIN eventos_competicoes ec ON ec.id = eca.evento_id
            WHERE eca.id = %s
        """, (anexo_id,))
        anexo = cur.fetchone()
        
        if not anexo:
            flash("Anexo não encontrado.", "danger")
            return redirect(url_for("painel.home"))
        
        # Verificar permissão: associação (criador), academia (aderiu) ou aluno/responsável (aderiu)
        pode_baixar = False
        id_assoc = getattr(current_user, "id_associacao", None)
        
        if current_user.has_role("gestor_associacao") or current_user.has_role("admin"):
            # Associação pode baixar seus próprios eventos
            pode_baixar = (id_assoc == anexo["id_associacao"])
        elif current_user.has_role("gestor_academia") or current_user.has_role("professor"):
            # Academia pode baixar se aderiu ao evento
            academia_id = getattr(current_user, "id_academia", None)
            if academia_id:
                cur.execute("""
                    SELECT 1 FROM eventos_competicoes_adesao
                    WHERE evento_id = %s AND academia_id = %s AND aderiu = 1
                """, (anexo["evento_id"], academia_id))
                pode_baixar = cur.fetchone() is not None
        elif current_user.has_role("aluno") or current_user.has_role("responsavel"):
            # Aluno/responsável pode baixar se a academia aderiu
            if current_user.has_role("aluno"):
                cur.execute("SELECT id_academia FROM alunos WHERE usuario_id = %s LIMIT 1", (current_user.id,))
            else:
                aluno_id = request.args.get("aluno_id", type=int)
                if aluno_id:
                    cur.execute("SELECT id_academia FROM alunos WHERE id = %s", (aluno_id,))
                else:
                    cur.execute("""
                        SELECT a.id_academia FROM alunos a
                        INNER JOIN responsavel_alunos ra ON ra.aluno_id = a.id AND ra.usuario_id = %s
                        LIMIT 1
                    """, (current_user.id,))
            aluno_row = cur.fetchone()
            if aluno_row and aluno_row.get("id_academia"):
                academia_id = aluno_row["id_academia"]
                cur.execute("""
                    SELECT 1 FROM eventos_competicoes_adesao
                    WHERE evento_id = %s AND academia_id = %s AND aderiu = 1
                """, (anexo["evento_id"], academia_id))
                pode_baixar = cur.fetchone() is not None
        
        if not pode_baixar:
            flash("Você não tem permissão para baixar este anexo.", "danger")
            return redirect(url_for("painel.home"))
        
        # Caminho do arquivo
        filepath = os.path.join(current_app.root_path, "static", "uploads", UPLOAD_ANEXOS, anexo["caminho_arquivo"])
        
        if not os.path.exists(filepath):
            flash("Arquivo não encontrado no servidor.", "danger")
            return redirect(url_for("painel.home"))
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=anexo["nome_arquivo"],
            mimetype=anexo.get("tipo_mime") or "application/octet-stream"
        )
        
    except Exception as e:
        current_app.logger.error(f"Erro ao baixar anexo: {e}", exc_info=True)
        flash("Erro ao baixar anexo.", "danger")
        return redirect(url_for("painel.home"))
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/disponiveis")
@login_required
def disponiveis():
    """Aluno ou responsável: lista eventos (ativos e finalizados) com filtros."""
    if not (current_user.has_role("aluno") or current_user.has_role("responsavel")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    # Filtros
    filtro_status = request.args.get("status", "")  # ativo, finalizado, ou vazio (todos)
    filtro_mes = request.args.get("mes", "")  # 1-12 ou vazio (todos)
    filtro_ano = request.args.get("ano", "")  # ex: 2026 ou vazio

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        academia_id = None
        if current_user.has_role("aluno"):
            cur.execute("SELECT id_academia, id FROM alunos WHERE usuario_id = %s LIMIT 1", (current_user.id,))
            r = cur.fetchone()
            academia_id = r["id_academia"] if r else None
        elif current_user.has_role("responsavel"):
            aluno_id = request.args.get("aluno_id", type=int)
            if aluno_id:
                cur.execute("SELECT 1 FROM responsavel_alunos WHERE usuario_id=%s AND aluno_id=%s", (current_user.id, aluno_id))
                resultado = cur.fetchone()
                # Garantir que o resultado foi totalmente consumido
                cur.fetchall()  # Consumir qualquer resultado restante
                if resultado:
                    cur.execute("SELECT id_academia FROM alunos WHERE id = %s", (aluno_id,))
                    r = cur.fetchone()
                    # Garantir que o resultado foi totalmente consumido
                    cur.fetchall()  # Consumir qualquer resultado restante
                    academia_id = r["id_academia"] if r else None
            if not academia_id:
                cur.execute("SELECT a.id_academia FROM alunos a INNER JOIN responsavel_alunos ra ON ra.aluno_id = a.id AND ra.usuario_id = %s LIMIT 1", (current_user.id,))
                r = cur.fetchone()
                # Garantir que o resultado foi totalmente consumido
                cur.fetchall()  # Consumir qualquer resultado restante
                academia_id = r["id_academia"] if r else None

        if not academia_id:
            flash("Nenhum aluno vinculado.", "warning")
            return redirect(url_for("painel.home"))

        # Query base: todos os eventos que a academia aderiu
        query = """
            SELECT ec.id, ec.nome, ec.descricao, ec.tipo, ec.data_inicio, ec.data_fim, ec.status
            FROM eventos_competicoes ec
            INNER JOIN eventos_competicoes_adesao ea ON ea.evento_id = ec.id AND ea.academia_id = %s AND ea.aderiu = 1
            WHERE 1=1
        """
        params = [academia_id]

        # Filtro de status
        if filtro_status == "ativo":
            query += " AND (ec.status = 'ativo' AND ec.data_fim > NOW())"
        elif filtro_status == "finalizado":
            query += " AND (ec.status = 'finalizado' OR ec.data_fim <= NOW())"
        # Se vazio, mostra todos

        # Filtro de mês
        if filtro_mes:
            try:
                mes_int = int(filtro_mes)
                if 1 <= mes_int <= 12:
                    query += " AND MONTH(ec.data_fim) = %s"
                    params.append(mes_int)
            except ValueError:
                pass

        # Filtro de ano
        if filtro_ano:
            try:
                ano_int = int(filtro_ano)
                if ano_int >= 2020:
                    query += " AND YEAR(ec.data_fim) = %s"
                    params.append(ano_int)
            except ValueError:
                pass

        query += " ORDER BY ec.data_fim DESC"
        cur.execute(query, tuple(params))
        eventos = cur.fetchall()
        
        # Buscar anexos para cada evento
        for ev in eventos:
            cur.execute("""
                SELECT id, nome_arquivo, tamanho_bytes, descricao
                FROM eventos_competicoes_anexos
                WHERE evento_id = %s
                ORDER BY created_at DESC
            """, (ev["id"],))
            ev["anexos"] = cur.fetchall()
            # Formatar tamanhos
            for anexo in ev["anexos"]:
                tamanho = anexo.get("tamanho_bytes") or 0
                if tamanho < 1024:
                    anexo["tamanho_formatado"] = f"{tamanho} B"
                elif tamanho < 1024 * 1024:
                    anexo["tamanho_formatado"] = f"{tamanho / 1024:.1f} KB"
                else:
                    anexo["tamanho_formatado"] = f"{tamanho / (1024 * 1024):.1f} MB"

        # Obter alunos vinculados
        if current_user.has_role("aluno"):
            cur.execute("SELECT id, nome FROM alunos WHERE usuario_id = %s", (current_user.id,))
            alunos_resp = cur.fetchall()
        else:
            cur.execute("SELECT a.id, a.nome FROM alunos a INNER JOIN responsavel_alunos ra ON ra.aluno_id = a.id AND ra.usuario_id = %s ORDER BY a.nome", (current_user.id,))
            alunos_resp = cur.fetchall()

        # Determinar aluno_id atual
        aluno_id_atual = request.args.get("aluno_id", type=int)
        if not aluno_id_atual and alunos_resp:
            aluno_id_atual = alunos_resp[0]["id"]

        # Marcar status visual e verificar inscrição
        for ev in eventos:
            ev["encerrado"] = ev.get("status") == "finalizado" or (ev.get("data_fim") and ev["data_fim"] < datetime.now())
            ev["ja_inscrito"] = False
            if aluno_id_atual:
                cur.execute("""
                    SELECT 1 FROM eventos_competicoes_inscricoes
                    WHERE evento_id = %s AND academia_id = %s AND aluno_id = %s AND status = 'enviada'
                """, (ev["id"], academia_id, aluno_id_atual))
                resultado = cur.fetchone()
                ev["ja_inscrito"] = resultado is not None
                # Garantir que o resultado foi totalmente consumido antes da próxima query
                cur.fetchall()  # Consumir qualquer resultado restante

        back_url = url_for("painel_responsavel.meu_perfil") if current_user.has_role("responsavel") else url_for("painel_aluno.painel")

        # Anos disponíveis para filtro
        cur.execute("SELECT DISTINCT YEAR(data_fim) as ano FROM eventos_competicoes ORDER BY ano DESC")
        anos_disponiveis = [r["ano"] for r in cur.fetchall() if r["ano"]]

        return render_template("eventos_competicoes/disponiveis.html",
            eventos=eventos, academia_id=academia_id, alunos=alunos_resp,
            filtro_status=filtro_status, filtro_mes=filtro_mes, filtro_ano=filtro_ano,
            anos_disponiveis=anos_disponiveis,
            back_url=back_url)
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/configuracao-exportacao", methods=["GET"])
@login_required
def get_configuracao_exportacao(evento_id):
    """Retorna configuração de exportação salva."""
    if session.get("modo_painel") != "associacao" or not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        return jsonify({"error": "Acesso negado"}), 403
    
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        return jsonify({"error": "Associação não encontrada"}), 404
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT configuracao_exportacao FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc))
        ev = cur.fetchone()
        if not ev:
            return jsonify({"error": "Evento não encontrado"}), 404
        
        config = None
        if ev.get("configuracao_exportacao"):
            try:
                config = json.loads(ev["configuracao_exportacao"]) if isinstance(ev["configuracao_exportacao"], str) else ev["configuracao_exportacao"]
            except Exception:
                pass
        
        return jsonify({"campos": config.get("campos", []) if config else []})
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/configuracao-exportacao", methods=["POST"])
@login_required
def salvar_configuracao_exportacao(evento_id):
    """Salva configuração de exportação."""
    if session.get("modo_painel") != "associacao" or not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        return jsonify({"success": False, "error": "Acesso negado"}), 403
    
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        return jsonify({"success": False, "error": "Associação não encontrada"}), 404
    
    data = request.get_json()
    campos = data.get("campos", [])
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Verificar se evento existe e pertence à associação
        cur.execute("SELECT id FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc))
        if not cur.fetchone():
            return jsonify({"success": False, "error": "Evento não encontrado"}), 404
        
        config = json.dumps({"campos": campos}, ensure_ascii=False)
        cur.execute("UPDATE eventos_competicoes SET configuracao_exportacao = %s WHERE id = %s",
            (config, evento_id))
        conn.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/configurar-impressao")
@login_required
def configurar_impressao(evento_id):
    """Página de configuração de impressão/exportação com opções de escala e layout."""
    try:
        if session.get("modo_painel") != "associacao" or not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
            flash("Acesso negado.", "danger")
            return redirect(url_for("painel.home"))
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        if not id_assoc:
            return redirect(url_for("associacao.gerenciamento_associacao"))

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""
                SELECT ec.id, ec.nome, ec.data_fim, ec.id_formulario, ec.configuracao_exportacao
                FROM eventos_competicoes ec WHERE ec.id = %s AND ec.id_associacao = %s
            """, (evento_id, id_assoc))
            ev = cur.fetchone()
            if not ev:
                flash("Evento não encontrado.", "danger")
                return redirect(url_for("eventos_competicoes.lista"))

            todas_inscricoes_cfg = _fetch_inscricoes_consolidar_associacao(cur, evento_id, id_assoc)
            campos_form = _campos_form_efetivos_para_inscricoes(
                cur, ev.get("id_formulario"), todas_inscricoes_cfg
            )
            
            # Buscar configuração de exportação salva
            configuracao_exportacao = None
            try:
                if ev.get("configuracao_exportacao"):
                    try:
                        config_str = ev["configuracao_exportacao"]
                        if isinstance(config_str, str) and config_str.strip():
                            configuracao_exportacao = json.loads(config_str)
                        elif isinstance(config_str, dict):
                            configuracao_exportacao = config_str
                    except (json.JSONDecodeError, TypeError) as e:
                        import logging
                        logging.warning(f"Erro ao parsear configuracao_exportacao: {e}")
                        pass
            except Exception as e:
                import logging
                logging.warning(f"Erro ao buscar configuracao_exportacao: {e}")
                pass

            # Obter tipo de agrupamento (padrão: academia)
            agrupamento = request.args.get("agrupamento", "academia")
            
            # Buscar algumas inscrições para preview (limitar a 10 para performance)
            cur.execute("""
                SELECT i.id, i.dados_form, ac.nome as academia_nome, a.nome as aluno_nome
                FROM eventos_competicoes_inscricoes i
                INNER JOIN academias ac ON ac.id = i.academia_id
                LEFT JOIN alunos a ON a.id = i.aluno_id
                WHERE i.evento_id = %s AND i.status = 'enviada' AND ac.id_associacao = %s
                ORDER BY ac.nome, a.nome
                LIMIT 10
            """, (evento_id, id_assoc))
            preview_inscricoes_raw = cur.fetchall()
            
            # Processar dados_form de JSON string para dict
            preview_inscricoes = []
            for insc in preview_inscricoes_raw:
                dados_form_parsed = {}
                if insc.get("dados_form"):
                    try:
                        if isinstance(insc["dados_form"], str):
                            dados_form_parsed = json.loads(insc["dados_form"])
                        elif isinstance(insc["dados_form"], dict):
                            dados_form_parsed = insc["dados_form"]
                    except (json.JSONDecodeError, TypeError):
                        dados_form_parsed = {}
                preview_inscricoes.append({
                    "id": insc.get("id"),
                    "dados_form": dados_form_parsed,
                    "academia_nome": insc.get("academia_nome"),
                    "aluno_nome": insc.get("aluno_nome")
                })
            
            return render_template("eventos_competicoes/configurar_impressao.html",
                evento=ev, campos_form=campos_form, agrupamento=agrupamento,
                configuracao_exportacao=configuracao_exportacao or {},
                preview_inscricoes=preview_inscricoes,
                back_url=url_for("eventos_competicoes.consolidar", evento_id=evento_id))
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        import logging
        logging.error(f"Erro em configurar_impressao: {e}", exc_info=True)
        flash(f"Erro ao carregar página de configuração: {str(e)}", "danger")
        return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))


@bp_eventos_competicoes.route("/<int:evento_id>/imprimir")
@login_required
def imprimir(evento_id):
    """Página de impressão otimizada com configurações de escala."""
    if session.get("modo_painel") != "associacao" or not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT ec.id, ec.nome, ec.data_fim, ec.id_formulario
            FROM eventos_competicoes ec WHERE ec.id = %s AND ec.id_associacao = %s
        """, (evento_id, id_assoc))
        ev = cur.fetchone()
        if not ev:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))

        # Obter campos selecionados e configurações
        campos_selecionados = request.args.getlist("campos")
        agrupamento = request.args.get("agrupamento", "academia")
        escala = request.args.get("escala", "100", type=int)
        tamanho_fonte = request.args.get("tamanho_fonte", "10", type=int)
        orientacao = request.args.get("orientacao", "paisagem")
        margem_vertical = request.args.get("margem_vertical", "20", type=int)
        margem_horizontal = request.args.get("margem_horizontal", "20", type=int)
        
        # Obter parâmetros de ordenação
        ordenar_por = request.args.get("ordenar_por", "")
        ordenar_direcao = request.args.get("ordenar_direcao", "asc").upper()
        
        inscricoes = _fetch_inscricoes_consolidar_associacao(cur, evento_id, id_assoc)
        campos_form = _campos_form_efetivos_para_inscricoes(cur, ev.get("id_formulario"), inscricoes)

        # Aplicar ordenação por campo do formulário se especificado
        if ordenar_por and ordenar_por in {c["campo_chave"] for c in campos_form}:
            def get_sort_value(row):
                dados_form_str = row.get("dados_form")
                if dados_form_str:
                    try:
                        if isinstance(dados_form_str, str):
                            dados = json.loads(dados_form_str)
                        else:
                            dados = dados_form_str
                    except (json.JSONDecodeError, TypeError):
                        dados = {}
                else:
                    dados = {}
                valor = dados.get(ordenar_por, "")
                # Tentar converter para número se possível
                try:
                    if isinstance(valor, (int, float)):
                        return (0, valor)
                    valor_str = str(valor).strip()
                    if valor_str.replace('.', '').replace('-', '').isdigit():
                        return (0, float(valor_str))
                except (ValueError, TypeError):
                    pass
                return (1, str(valor).lower())
            
            inscricoes.sort(key=get_sort_value, reverse=(ordenar_direcao == "DESC"))

        academias_com_inscricoes = _agrupar_inscricoes_por_academia_categoria(inscricoes)

        # Calcular totais
        for ac_id, ac_data in academias_com_inscricoes.items():
            try:
                total_por_categoria = {cat: len(alunos) for cat, alunos in ac_data.get("categorias", {}).items()}
                ac_data["total_inscritos"] = sum(total_por_categoria.values())
                ac_data["total_por_categoria"] = total_por_categoria
            except Exception:
                ac_data["total_inscritos"] = 0
                ac_data["total_por_categoria"] = {}

        # Preparar agrupamento por categoria também
        categorias_com_inscricoes = {}
        for ac_id, ac_data in academias_com_inscricoes.items():
            for categoria, alunos in ac_data.get("categorias", {}).items():
                if categoria not in categorias_com_inscricoes:
                    categorias_com_inscricoes[categoria] = {
                        "academias": {},
                        "total_inscritos": 0
                    }
                for aluno in alunos:
                    academia_nome = ac_data.get("academia_nome", "Academia Desconhecida")
                    if academia_nome not in categorias_com_inscricoes[categoria]["academias"]:
                        categorias_com_inscricoes[categoria]["academias"][academia_nome] = []
                    categorias_com_inscricoes[categoria]["academias"][academia_nome].append(aluno)
        
        for categoria, cat_data in categorias_com_inscricoes.items():
            total = sum(len(alunos) for alunos in cat_data["academias"].values())
            cat_data["total_inscritos"] = total

        # Filtrar campos se selecionados e manter ordem da URL
        campos_para_imprimir = []
        if campos_selecionados:
            campos_map = {c["campo_chave"]: c for c in campos_form}
            for campo_chave in campos_selecionados:
                if campo_chave in campos_map:
                    campos_para_imprimir.append(campos_map[campo_chave])
        else:
            campos_para_imprimir = campos_form
        
        # Preparar inscrições simples para impressão (sem agrupamento complexo)
        inscricoes_para_imprimir = []
        for insc in inscricoes:
            try:
                dados_form_str = insc.get("dados_form")
                if dados_form_str:
                    try:
                        if isinstance(dados_form_str, str):
                            dados = json.loads(dados_form_str)
                        else:
                            dados = dados_form_str
                    except (json.JSONDecodeError, TypeError):
                        dados = {}
                else:
                    dados = {}
                
                inscricoes_para_imprimir.append({
                    "id": insc.get("id"),
                    "aluno_nome": insc.get("aluno_nome") or "Avulso",
                    "academia_nome": insc.get("academia_nome") or "Academia Desconhecida",
                    "dados_form": dados
                })
            except Exception as e:
                import logging
                logging.error(f"Erro ao processar inscrição para impressão {insc.get('id')}: {e}")
                continue

        # Função helper para formatação de valores (mesma lógica do consolidar)
        def _formatar_valor(campo_chave, valor):
            if campo_chave == 'sexo':
                if valor == 'M':
                    return 'Masculino'
                elif valor == 'F':
                    return 'Feminino'
                return valor or '-'
            elif campo_chave in ['data_nascimento', 'ultimo_exame_faixa', 'rg_data_emissao', 'data_cadastro_zempo']:
                if valor:
                    try:
                        if isinstance(valor, str) and len(valor) >= 10:
                            if '-' in valor[:10]:
                                # Formato ISO: YYYY-MM-DD
                                return f"{valor[8:10]}/{valor[5:7]}/{valor[0:4]}"
                    except Exception:
                        pass
                return valor or '-'
            return valor or '-'

        return render_template("eventos_competicoes/imprimir.html",
            evento=ev, academias_com_inscricoes=academias_com_inscricoes,
            categorias_com_inscricoes=categorias_com_inscricoes,
            campos_form=campos_para_imprimir, agrupamento=agrupamento,
            escala=escala, tamanho_fonte=tamanho_fonte,
            orientacao=orientacao, margem_vertical=margem_vertical,
            margem_horizontal=margem_horizontal,
            inscricoes_para_imprimir=inscricoes_para_imprimir)
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/exportar")
@login_required
def exportar(evento_id):
    """Exporta inscrições em PDF ou Excel conforme formato."""
    fmt = request.args.get("formato", "excel").lower()
    campos_selecionados = request.args.getlist("campos")  # Lista de campos selecionados
    
    # Filtrar campos vazios ou inválidos
    campos_selecionados = [c for c in campos_selecionados if c and c.strip() and c.strip().lower() not in ("aluno", "academia")]
    
    if session.get("modo_painel") != "associacao" or not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome, id_formulario, configuracao_exportacao FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
            (evento_id, id_assoc))
        ev = cur.fetchone()
        if not ev:
            return redirect(url_for("eventos_competicoes.lista"))

        rows = _fetch_inscricoes_consolidar_associacao(cur, evento_id, id_assoc)
        campos_form = _campos_form_efetivos_para_inscricoes(cur, ev.get("id_formulario"), rows)
        config = None
        if ev.get("configuracao_exportacao"):
            try:
                config = (
                    json.loads(ev["configuracao_exportacao"])
                    if isinstance(ev["configuracao_exportacao"], str)
                    else ev["configuracao_exportacao"]
                )
            except Exception:
                pass
        
        # Se campos foram selecionados via URL, usar eles; senão, usar configuração salva ou todos
        if campos_selecionados:
            # Filtrar campos_form pelos selecionados e manter ordem
            campos_para_exportar = []
            for chave in campos_selecionados:
                # Ignorar campos vazios ou inválidos
                if not chave or chave.strip() == "":
                    continue
                campo = next((c for c in campos_form if c["campo_chave"] == chave), None)
                if campo:
                    campos_para_exportar.append(campo)
                # Se campo não encontrado, não adicionar (evitar campos inválidos)
        else:
            if config and config.get("campos"):
                # Ordenar campos_form conforme configuração
                ordem_map = {c["chave"]: idx for idx, c in enumerate(config["campos"])}
                campos_para_exportar = sorted(
                    [c for c in campos_form if c["campo_chave"] in ordem_map],
                    key=lambda x: ordem_map.get(x["campo_chave"], 999)
                )
            else:
                # Usar todos os campos na ordem padrão
                campos_para_exportar = campos_form
        
        # Obter orientação do PDF (da configuração salva ou da URL, padrão: paisagem)
        orientacao_pdf = "paisagem"
        if campos_selecionados:
            # Se há campos na URL, tentar pegar orientação da URL também
            orientacao_url = request.args.get("orientacao", "").lower()
            if orientacao_url in ("paisagem", "retrato"):
                orientacao_pdf = orientacao_url
        elif config and config.get("orientacao_pdf"):
            orientacao_pdf = config.get("orientacao_pdf", "paisagem")
        
        # Garantir que labels e chaves correspondem APENAS aos campos selecionados
        # Remover qualquer campo que não esteja na lista de campos do formulário
        campos_validos_chaves = {c["campo_chave"] for c in campos_form}
        campos_para_exportar = [c for c in campos_para_exportar if c["campo_chave"] in campos_validos_chaves]
        
        labels = [c["label"] for c in campos_para_exportar]
        chaves = [c["campo_chave"] for c in campos_para_exportar]

        cur.execute("SELECT nome FROM associacoes WHERE id = %s", (id_assoc,))
        assoc_row = cur.fetchone()
        assoc_nome = assoc_row["nome"] if assoc_row else ""

        # Obter parâmetros de ordenação
        ordenar_por = request.args.get("ordenar_por", "")
        ordenar_direcao = request.args.get("ordenar_direcao", "asc").upper()
        
        # Construir ORDER BY dinâmico
        order_by = "ac.nome, a.nome"  # Padrão
        if ordenar_por:
            # Validar campo de ordenação (precisa estar nos campos do formulário)
            campos_validos = {c["campo_chave"] for c in campos_form}
            if ordenar_por in campos_validos:
                # Ordenação será feita após parsear JSON, então manteremos ordem padrão aqui
                # e ordenaremos depois no Python
                order_by = "ac.nome, a.nome"
            else:
                order_by = "ac.nome, a.nome"
        
        # Aplicar ordenação por campo do formulário se especificado
        if ordenar_por and ordenar_por in {c["campo_chave"] for c in campos_form}:
            def get_sort_value(row):
                dados_form_str = row.get("dados_form")
                if dados_form_str:
                    try:
                        if isinstance(dados_form_str, str):
                            dados = json.loads(dados_form_str)
                        else:
                            dados = dados_form_str
                    except (json.JSONDecodeError, TypeError):
                        dados = {}
                else:
                    dados = {}
                valor = dados.get(ordenar_por, "")
                # Tentar converter para número se possível
                try:
                    if isinstance(valor, (int, float)):
                        return (0, valor)
                    valor_str = str(valor).strip()
                    if valor_str.replace('.', '').replace('-', '').isdigit():
                        return (0, float(valor_str))
                except (ValueError, TypeError):
                    pass
                return (1, str(valor).lower())
            
            rows.sort(key=get_sort_value, reverse=(ordenar_direcao == "DESC"))
    finally:
        cur.close()
        conn.close()

    def _formatar_valor(chave, val):
        """Formata valor: sexo M/F -> Masculino/Feminino; datas -> dd/mm/yyyy."""
        if val is None or val == "":
            return ""
        s = str(val).strip()
        if chave == "sexo":
            if s.upper() == "M":
                return "Masculino"
            if s.upper() == "F":
                return "Feminino"
            return s
        if chave in ("data_nascimento", "ultimo_exame_faixa", "rg_data_emissao", "data_cadastro_zempo"):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    d = datetime.strptime(s[:10], fmt)
                    return d.strftime("%d/%m/%Y")
                except (ValueError, TypeError):
                    continue
        return s

    if fmt == "excel":
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment
            from io import BytesIO
            
            # Criar workbook e worksheet
            wb = Workbook()
            ws = wb.active
            ws.title = "Inscrições"
            
            # Estilizar cabeçalho
            header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            header_font = Font(bold=True, color="FFFFFF", size=11)
            header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            
            # Montar header APENAS com os campos selecionados (incluindo coluna # como na prévia)
            # Adicionar coluna "#" no início
            cell_numero = ws.cell(row=1, column=1, value="#")
            cell_numero.fill = header_fill
            cell_numero.font = header_font
            cell_numero.alignment = header_alignment
            
            # Adicionar labels dos campos
            for col_idx, label in enumerate(labels, start=2):
                cell = ws.cell(row=1, column=col_idx, value=label)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_alignment
            
            # Ajustar largura das colunas automaticamente baseado no conteúdo
            max_widths = {}
            # Coluna "#" - largura fixa pequena
            col_letter_numero = ws.cell(row=1, column=1).column_letter
            max_widths[col_letter_numero] = 8  # Largura pequena para coluna "#"
            ws.column_dimensions[col_letter_numero].width = max_widths[col_letter_numero]
            
            # Ajustar largura das outras colunas
            for col_idx, campo in enumerate(campos_para_exportar, start=2):
                col_letter = ws.cell(row=1, column=col_idx).column_letter
                # Começar com largura do cabeçalho
                max_width = len(str(labels[col_idx - 2])) + 2
                # Verificar conteúdo das células para encontrar maior valor
                for r in rows:
                    dados = json.loads(r["dados_form"]) if r.get("dados_form") else {}
                    k = campo["campo_chave"]
                    valor = dados.get(k, "")
                    if valor == "" and k == "id_academia":
                        valor = r.get("academia_nome", "")
                    elif valor == "" and k == "nome":
                        valor = r.get("aluno_nome", "")
                    valor_formatado = _formatar_valor(k, valor)
                    max_width = max(max_width, len(str(valor_formatado)) + 2)
                # Limitar entre mínimo e máximo
                max_widths[col_letter] = min(max(max_width, 10), 50)
                ws.column_dimensions[col_letter].width = max_widths[col_letter]
            
            # Adicionar dados nas linhas
            for row_idx, r in enumerate(rows, start=2):
                dados = json.loads(r["dados_form"]) if r.get("dados_form") else {}
                
                # Adicionar número da linha na primeira coluna
                cell_numero = ws.cell(row=row_idx, column=1, value=str(row_idx - 1))
                cell_numero.alignment = Alignment(vertical="top", horizontal="center")
                
                # Adicionar APENAS os campos selecionados
                for col_idx, campo in enumerate(campos_para_exportar, start=2):
                    k = campo["campo_chave"]
                    # Se o campo não estiver em dados_form, tentar buscar de outras fontes apenas se necessário
                    valor = dados.get(k, "")
                    if valor == "" and k == "id_academia":
                        # Se for id_academia e não tiver valor, buscar nome da academia do join
                        valor = r.get("academia_nome", "")
                    elif valor == "" and k == "nome":
                        # Se for nome e não tiver valor, buscar nome do aluno do join
                        valor = r.get("aluno_nome", "")
                    
                    # Formatar valor
                    valor_formatado = _formatar_valor(k, valor)
                    
                    # Adicionar célula
                    cell = ws.cell(row=row_idx, column=col_idx, value=valor_formatado)
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
            
            # Congelar primeira linha (cabeçalho)
            ws.freeze_panes = "A2"
            
            # Salvar em BytesIO
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            
            resp = Response(output.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            resp.headers["Content-Disposition"] = f'attachment; filename="inscricoes_{ev["nome"][:30]}.xlsx"'
            return resp
        except ImportError:
            flash("Biblioteca openpyxl não instalada. Execute: pip install openpyxl", "warning")
            return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))
        except Exception as e:
            flash(f"Erro ao exportar: {e}", "danger")
            return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))

    # PDF: tabela única, orientação configurável (paisagem/retrato), evento no título, associação abaixo
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from io import BytesIO
        buffer = BytesIO()
        
        # Obter configurações de impressão da URL
        escala_pdf = request.args.get("escala", "100", type=int)
        tamanho_fonte_pdf = request.args.get("tamanho_fonte", "10", type=int)
        margem_vertical = request.args.get("margem_vertical", "20", type=int)
        margem_horizontal = request.args.get("margem_horizontal", "20", type=int)
        
        # Usar orientação configurada (paisagem ou retrato)
        if orientacao_pdf == "retrato":
            page_size = A4
        else:
            page_size = landscape(A4)
        
        # Aplicar margens configuradas (converter mm para pontos: 1mm = 2.83465 pontos)
        left_margin = max(10, margem_horizontal * 2.83465)
        right_margin = max(10, margem_horizontal * 2.83465)
        top_margin = max(10, margem_vertical * 2.83465)
        bottom_margin = max(10, margem_vertical * 2.83465)
        
        doc = SimpleDocTemplate(buffer, pagesize=page_size, 
                                leftMargin=left_margin, rightMargin=right_margin, 
                                topMargin=top_margin, bottomMargin=bottom_margin)
        styles = getSampleStyleSheet()
        elements = []
        elements.append(Paragraph(f"<b>{ev['nome']}</b>", styles["Title"]))
        elements.append(Paragraph(assoc_nome, styles["Heading3"]))
        elements.append(Spacer(1, 12))
        
        # Montar header APENAS com os campos selecionados (incluindo coluna # como na prévia)
        tbl_header = ["#"] + labels  # Adicionar coluna "#" no início como na prévia
        tbl_rows = [tbl_header]
        for idx, r in enumerate(rows, start=1):
            dados = json.loads(r["dados_form"]) if r.get("dados_form") else {}
            linha = [str(idx)]  # Adicionar número da linha no início
            
            # Adicionar APENAS os campos selecionados na ordem correta
            for campo in campos_para_exportar:
                k = campo["campo_chave"]
                # Se o campo não estiver em dados_form, tentar buscar de outras fontes apenas se necessário
                valor = dados.get(k, "")
                if valor == "" and k == "id_academia":
                    # Se for id_academia e não tiver valor, buscar nome da academia do join
                    valor = r.get("academia_nome", "")
                elif valor == "" and k == "nome":
                    # Se for nome e não tiver valor, buscar nome do aluno do join
                    valor = r.get("aluno_nome", "Avulso")
                linha.append(_formatar_valor(k, valor))
            tbl_rows.append(linha)
        if len(tbl_rows) > 1:
            n_cols = len(tbl_header)
            # Calcular largura disponível considerando margens
            available_width = page_size[0] - left_margin - right_margin
            
            # Aplicar escala às larguras das colunas
            escala_factor = escala_pdf / 100.0
            # A coluna "#" deve ser menor (30 pontos), as outras dividem o espaço restante
            col_width_numero = 30 * escala_factor  # Coluna "#"
            largura_restante = (available_width - col_width_numero) * escala_factor
            base_col_width = largura_restante / (n_cols - 1) if n_cols > 1 else largura_restante
            col_widths = [max(20, col_width_numero)] + [max(30, base_col_width)] * (n_cols - 1)
            
            t = Table(tbl_rows, repeatRows=1, colWidths=col_widths)
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), tamanho_fonte_pdf),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e0e0")),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]))
            elements.append(t)
        else:
            elements.append(Paragraph("Nenhuma inscrição enviada.", styles["Normal"]))
        doc.build(elements)
        buffer.seek(0)
        resp = Response(buffer.getvalue(), mimetype="application/pdf")
        resp.headers["Content-Disposition"] = f'attachment; filename="inscricoes_{ev["nome"][:30]}.pdf"'
        return resp
    except ImportError:
        flash("Biblioteca reportlab não instalada. Use exportar em Excel.", "warning")
        return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))
    except Exception as e:
        flash(f"Erro ao gerar PDF: {e}", "danger")
        return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id))


@bp_eventos_competicoes.route("/buscar-categorias", methods=["POST"])
@login_required
def buscar_categorias():
    """Rota AJAX para buscar categorias disponíveis baseado em peso, idade e gênero."""
    try:
        peso = request.json.get("peso")
        data_nascimento = request.json.get("data_nascimento")
        genero = request.json.get("genero")
        
        if not peso or not data_nascimento or not genero:
            return Response(json.dumps({"categorias": []}), mimetype="application/json")
        
        # Calcular idade em ano civil
        try:
            from datetime import datetime as dt
            nasc = dt.strptime(data_nascimento[:10], "%Y-%m-%d").date()
            hoje = date.today()
            idade_ano_civil = hoje.year - nasc.year
        except Exception:
            return Response(json.dumps({"categorias": []}), mimetype="application/json")
        
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            genero_upper = genero.upper()
            if genero_upper not in ("M", "F"):
                return Response(json.dumps({"categorias": []}), mimetype="application/json")
            
            peso_float = float(peso)
            
            # Mapear M/F para MASCULINO/FEMININO
            genero_db = "MASCULINO" if genero_upper == "M" else "FEMININO" if genero_upper == "F" else genero_upper
            cur.execute("""
                SELECT id, categoria, nome_categoria, peso_min, peso_max, idade_min, idade_max
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
            """, (genero_db, idade_ano_civil, idade_ano_civil, peso_float, peso_float))
            
            categorias = cur.fetchall()
            return Response(json.dumps({"categorias": categorias}), mimetype="application/json")
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        return Response(json.dumps({"categorias": [], "erro": str(e)}), mimetype="application/json")


@bp_eventos_competicoes.route("/<int:evento_id>/categorias-aproximacao", methods=["GET", "POST"])
@login_required
def evento_categorias_aproximacao(evento_id):
    """Categorias próprias da competição (modo aproximação), para uso no placar."""
    if session.get("modo_painel") != "associacao":
        flash("Disponível apenas em modo associação.", "danger")
        return redirect(url_for("painel.home"))
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        flash("Selecione a associação.", "warning")
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT id, nome, tipo, categorias_modo
                FROM eventos_competicoes
                WHERE id = %s AND id_associacao = %s
                """,
                (evento_id, id_assoc),
            )
        except Exception as ex_ev:
            err_ev = str(ex_ev).lower()
            if "categorias_modo" in err_ev or "1054" in err_ev or "unknown column" in err_ev:
                cur.execute(
                    "SELECT id, nome, tipo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
                    (evento_id, id_assoc),
                )
            else:
                raise
        evento = cur.fetchone()
        if not evento:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        if "categorias_modo" not in evento:
            evento["categorias_modo"] = "padrao"
        if evento.get("tipo") != "competicao":
            flash("Categorias por aproximação existem apenas em competições.", "warning")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))
        if evento.get("categorias_modo") != "aproximacao":
            flash("Ative 'Categorias por aproximação' na edição da competição para usar esta tela.", "info")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))

        if request.method == "POST":
            del_id = request.form.get("delete_id", type=int)
            if del_id:
                cur.execute(
                    """
                    DELETE FROM eventos_competicoes_categorias_aprox
                    WHERE id = %s AND evento_id = %s
                    """,
                    (del_id, evento_id),
                )
                n_upd_del, n_sem_del = _recalcular_todas_inscricoes_categorias_aprox(cur, evento_id)
                conn.commit()
                flash("Categoria removida.", "success")
                flash(
                    f"Inscrições recalculadas automaticamente: {n_upd_del} atualizada(s), {n_sem_del} sem categoria.",
                    "info" if n_sem_del > 0 else "success",
                )
                _k_apx = {}
                if (request.args.get("embed") or request.form.get("embed") or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                ):
                    _k_apx["embed"] = 1
                return redirect(
                    url_for("eventos_competicoes.evento_categorias_aproximacao", evento_id=evento_id, **_k_apx)
                )

            update_id = request.form.get("update_id", type=int)
            if update_id:
                nome_up = (request.form.get("nome") or "").strip()
                if not nome_up:
                    flash("Informe o nome da faixa.", "danger")
                else:
                    cur.execute(
                        """
                        SELECT id, nome FROM eventos_competicoes_categorias_aprox
                        WHERE id = %s AND evento_id = %s
                        """,
                        (update_id, evento_id),
                    )
                    row_old = cur.fetchone()
                    if not row_old:
                        flash("Faixa não encontrada.", "danger")
                    else:
                        nome_antigo = (row_old.get("nome") or "").strip()

                        def _opt_int_aprox_u(k):
                            v = (request.form.get(k) or "").strip()
                            if not v:
                                return None
                            try:
                                return int(v)
                            except ValueError:
                                return None

                        def _opt_decimal_aprox_u(k):
                            v = (request.form.get(k) or "").strip().replace(",", ".")
                            if not v:
                                return None
                            try:
                                return float(v)
                            except ValueError:
                                return None

                        ano_nasc_min_u = _opt_int_aprox_u("ano_nasc_min")
                        ano_nasc_max_u = _opt_int_aprox_u("ano_nasc_max")
                        ga_u = (request.form.get("genero_aprox") or "A").strip().upper()[:1]
                        genero_aprox_u = ga_u if ga_u in ("A", "M", "F", "O") else "A"
                        peso_min_kg_u = _opt_decimal_aprox_u("peso_min_kg")
                        peso_max_kg_u = _opt_decimal_aprox_u("peso_max_kg")
                        try:
                            cur.execute(
                                """
                                UPDATE eventos_competicoes_categorias_aprox
                                SET nome = %s, ano_nasc_min = %s, ano_nasc_max = %s,
                                    genero_aprox = %s, peso_min_kg = %s, peso_max_kg = %s
                                WHERE id = %s AND evento_id = %s
                                """,
                                (
                                    nome_up,
                                    ano_nasc_min_u,
                                    ano_nasc_max_u,
                                    genero_aprox_u,
                                    peso_min_kg_u,
                                    peso_max_kg_u,
                                    update_id,
                                    evento_id,
                                ),
                            )
                        except Exception:
                            cur.execute(
                                """
                                UPDATE eventos_competicoes_categorias_aprox
                                SET nome = %s
                                WHERE id = %s AND evento_id = %s
                                """,
                                (nome_up, update_id, evento_id),
                            )
                        # Se o nome da faixa mudou, refletir nas lutas já geradas deste evento.
                        if nome_antigo and nome_antigo != nome_up:
                            try:
                                cur.execute(
                                    """
                                    UPDATE judo_lutas
                                    SET categoria_nome = %s
                                    WHERE evento_id = %s AND categoria_nome = %s
                                    """,
                                    (nome_up, evento_id, nome_antigo),
                                )
                            except Exception:
                                pass
                        n_upd_edit, n_sem_edit = _recalcular_todas_inscricoes_categorias_aprox(cur, evento_id)
                        conn.commit()
                        flash("Faixa atualizada.", "success")
                        flash(
                            f"Propagação automática concluída: {n_upd_edit} inscrição(ões) recalculada(s), {n_sem_edit} sem categoria.",
                            "info" if n_sem_edit > 0 else "success",
                        )
                _k_apx_u = {}
                if (request.args.get("embed") or request.form.get("embed") or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                ):
                    _k_apx_u["embed"] = 1
                return redirect(
                    url_for("eventos_competicoes.evento_categorias_aproximacao", evento_id=evento_id, **_k_apx_u)
                )

            nome = (request.form.get("nome") or "").strip()
            if nome:

                def _opt_int_aprox(k):
                    v = (request.form.get(k) or "").strip()
                    if not v:
                        return None
                    try:
                        return int(v)
                    except ValueError:
                        return None

                def _opt_decimal_aprox(k):
                    v = (request.form.get(k) or "").strip().replace(",", ".")
                    if not v:
                        return None
                    try:
                        return float(v)
                    except ValueError:
                        return None

                ano_nasc_min = _opt_int_aprox("ano_nasc_min")
                ano_nasc_max = _opt_int_aprox("ano_nasc_max")
                ga = (request.form.get("genero_aprox") or "A").strip().upper()[:1]
                genero_aprox = ga if ga in ("A", "M", "F", "O") else "A"
                peso_min_kg = _opt_decimal_aprox("peso_min_kg")
                peso_max_kg = _opt_decimal_aprox("peso_max_kg")
                cur.execute(
                    "SELECT COALESCE(MAX(ordem), 0) + 1 AS nx FROM eventos_competicoes_categorias_aprox WHERE evento_id = %s",
                    (evento_id,),
                )
                nx = cur.fetchone()
                ordem = int(nx["nx"]) if nx and nx.get("nx") is not None else 1
                try:
                    cur.execute(
                        """
                        INSERT INTO eventos_competicoes_categorias_aprox
                        (evento_id, nome, ordem, ano_nasc_min, ano_nasc_max, genero_aprox, peso_min_kg, peso_max_kg)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            evento_id,
                            nome,
                            ordem,
                            ano_nasc_min,
                            ano_nasc_max,
                            genero_aprox,
                            peso_min_kg,
                            peso_max_kg,
                        ),
                    )
                except Exception:
                    cur.execute(
                        """
                        INSERT INTO eventos_competicoes_categorias_aprox (evento_id, nome, ordem)
                        VALUES (%s, %s, %s)
                        """,
                        (evento_id, nome, ordem),
                    )
                n_upd_add, n_sem_add = _recalcular_todas_inscricoes_categorias_aprox(cur, evento_id)
                conn.commit()
                flash("Categoria adicionada.", "success")
                flash(
                    f"Inscrições recalculadas automaticamente: {n_upd_add} atualizada(s), {n_sem_add} sem categoria.",
                    "info" if n_sem_add > 0 else "success",
                )
            _k_apx2 = {}
            if (request.args.get("embed") or request.form.get("embed") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            ):
                _k_apx2["embed"] = 1
            return redirect(
                url_for("eventos_competicoes.evento_categorias_aproximacao", evento_id=evento_id, **_k_apx2)
            )

        try:
            cur.execute(
                """
                SELECT id, nome, ordem, ano_nasc_min, ano_nasc_max, genero_aprox, peso_min_kg, peso_max_kg
                FROM eventos_competicoes_categorias_aprox
                WHERE evento_id = %s
                ORDER BY ordem ASC, id ASC
                """,
                (evento_id,),
            )
            categorias = cur.fetchall()
        except Exception:
            try:
                cur.execute(
                    """
                    SELECT id, nome, ordem
                    FROM eventos_competicoes_categorias_aprox
                    WHERE evento_id = %s
                    ORDER BY ordem ASC, id ASC
                    """,
                    (evento_id,),
                )
                categorias = cur.fetchall()
            except Exception:
                categorias = []

        cur.execute(
            "SELECT COUNT(*) AS n FROM eventos_competicoes_inscricoes WHERE evento_id = %s",
            (evento_id,),
        )
        _nr = cur.fetchone()
        num_inscricoes = int(_nr["n"]) if _nr and _nr.get("n") is not None else 0

        return render_template(
            "eventos_competicoes/categorias_aproximacao.html",
            evento=evento,
            categorias=categorias,
            num_inscricoes=num_inscricoes,
            back_url=_back_por_tipo_e_modo(evento_id, evento.get("tipo"), cur=cur),
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/recalcular-categorias-aproximacao", methods=["POST"])
@login_required
def recalcular_categorias_aproximacao(evento_id):
    """Reaplica faixas por aproximação a todas as inscrições (útil após criar/editar categorias)."""
    if session.get("modo_painel") != "associacao":
        flash("Disponível apenas em modo associação.", "danger")
        return redirect(url_for("painel.home"))
    if not (current_user.has_role("gestor_associacao") or current_user.has_role("admin")):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))

    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    if not id_assoc:
        flash("Selecione a associação.", "warning")
        return redirect(url_for("associacao.gerenciamento_associacao"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT id, tipo, categorias_modo
                FROM eventos_competicoes
                WHERE id = %s AND id_associacao = %s
                """,
                (evento_id, id_assoc),
            )
        except Exception:
            cur.execute(
                "SELECT id, tipo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
                (evento_id, id_assoc),
            )
        evento = cur.fetchone()
        if not evento:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        if "categorias_modo" not in evento:
            evento["categorias_modo"] = "padrao"
        if evento.get("tipo") != "competicao":
            flash("Apenas competições usam categorias por aproximação.", "warning")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))
        if _as_texto_mysql(evento.get("categorias_modo")) != "aproximacao":
            flash("Ative «Categorias por aproximação» na edição da competição para usar esta ação.", "info")
            return redirect(url_for("eventos_competicoes.editar", evento_id=evento_id))

        cur.execute(
            "SELECT COUNT(*) AS n FROM eventos_competicoes_categorias_aprox WHERE evento_id = %s",
            (evento_id,),
        )
        n_faixas_evt = int((cur.fetchone() or {}).get("n") or 0)

        n_upd, n_sem = _recalcular_todas_inscricoes_categorias_aprox(cur, evento_id)
        conn.commit()
        msg = (
            f"Recálculo concluído: {n_upd} inscrição(ões) atualizadas no banco. "
            f"{n_sem} inscrição(ões) ficaram sem categoria "
            f"(falta data/sexo/peso válidos ou nenhuma faixa compatível)."
        )
        if n_faixas_evt == 0:
            msg += " Não há faixas cadastradas neste evento — inclua-as em «Categorias por aproximação»."
        elif n_sem > 0:
            msg += " Revise ano de nascimento, peso (kg), sexo (M/F/O) nas inscrições e as regras de cada faixa."
        flash(msg, "success" if n_sem == 0 else "warning")
    except Exception:
        conn.rollback()
        current_app.logger.exception("recalcular_categorias_aproximacao evento_id=%s", evento_id)
        flash("Não foi possível recalcular as categorias. Tente novamente.", "danger")
    finally:
        cur.close()
        conn.close()

    retorno = (request.form.get("retorno") or "").strip().lower()
    agr = (request.form.get("agrupamento_retorno") or "academia").strip()
    if agr not in ("academia", "categoria"):
        agr = "academia"
    if retorno == "consolidar":
        return redirect(url_for("eventos_competicoes.consolidar", evento_id=evento_id, agrupamento=agr))
    if retorno == "chaves":
        _k_ch = {}
        if (request.args.get("embed") or request.form.get("embed") or "").strip().lower() in ("1", "true", "yes"):
            _k_ch["embed"] = 1
        return redirect(url_for("competicoes.chaves_evento", evento_id=evento_id, **_k_ch))
    _k_re = {}
    if (request.args.get("embed") or request.form.get("embed") or "").strip().lower() in ("1", "true", "yes"):
        _k_re["embed"] = 1
    return redirect(url_for("eventos_competicoes.evento_categorias_aproximacao", evento_id=evento_id, **_k_re))


# ============================================================
# 🥋 PLACAR DE JUDÔ - Rotas e Handlers
# ============================================================

@bp_eventos_competicoes.route("/placar-judo")
@login_required
def placar_judo_selecionar_evento():
    """Seleciona evento para acessar o placar de judô."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        
        if modo == "associacao":
            if not id_assoc:
                flash("Selecione a associação.", "warning")
                return redirect(url_for("associacao.gerenciamento_associacao"))
            
            # Buscar eventos da associação
            try:
                cur.execute("""
                    SELECT ec.id, ec.nome, ec.tipo, ec.natureza, ec.data_inicio, ec.data_fim,
                           (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                    FROM eventos_competicoes ec
                    WHERE ec.id_associacao = %s AND ec.tipo = 'competicao'
                    ORDER BY ec.data_fim DESC, ec.nome
                """, (id_assoc,))
            except Exception as ex_pl:
                err_pl = str(ex_pl).lower()
                if "natureza" in err_pl or "1054" in err_pl or "unknown column" in err_pl:
                    cur.execute("""
                        SELECT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                               (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                        FROM eventos_competicoes ec
                        WHERE ec.id_associacao = %s AND ec.tipo = 'competicao'
                        ORDER BY ec.data_fim DESC, ec.nome
                    """, (id_assoc,))
                else:
                    raise
            eventos = cur.fetchall()
            for ev in eventos:
                if "natureza" not in ev:
                    ev["natureza"] = None
            
            return render_template("eventos_competicoes/placar_judo_selecionar_evento.html",
                eventos=eventos,
                back_url=url_for("associacao.gerenciamento_associacao"))
        
        elif modo == "academia":
            ids_acad = _get_ids_academias(cur)
            if not ids_acad:
                flash("Nenhuma academia vinculada.", "warning")
                return redirect(url_for("painel.home"))
            
            # Buscar eventos disponíveis para as academias
            placeholders = ",".join(["%s"] * len(ids_acad))
            try:
                cur.execute(f"""
                    SELECT DISTINCT ec.id, ec.nome, ec.tipo, ec.natureza, ec.data_inicio, ec.data_fim,
                           (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                    FROM eventos_competicoes ec
                    INNER JOIN academias ac ON ac.id_associacao = ec.id_associacao AND ac.id IN ({placeholders})
                    WHERE ec.tipo = 'competicao'
                    ORDER BY ec.data_fim DESC, ec.nome
                """, tuple(ids_acad))
            except Exception as ex_pl2:
                err_pl2 = str(ex_pl2).lower()
                if "natureza" in err_pl2 or "1054" in err_pl2 or "unknown column" in err_pl2:
                    cur.execute(f"""
                        SELECT DISTINCT ec.id, ec.nome, ec.tipo, ec.data_inicio, ec.data_fim,
                               (SELECT COUNT(*) FROM judo_lutas WHERE evento_id = ec.id) as total_lutas
                        FROM eventos_competicoes ec
                        INNER JOIN academias ac ON ac.id_associacao = ec.id_associacao AND ac.id IN ({placeholders})
                        WHERE ec.tipo = 'competicao'
                        ORDER BY ec.data_fim DESC, ec.nome
                    """, tuple(ids_acad))
                else:
                    raise
            eventos = cur.fetchall()
            for ev in eventos:
                if "natureza" not in ev:
                    ev["natureza"] = None
            
            return render_template("eventos_competicoes/placar_judo_selecionar_evento.html",
                eventos=eventos,
                back_url=url_for("academia.painel_academia"))
        
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/placar-judo")
@login_required
def placar_judo_lista(evento_id):
    """Lista lutas do evento e permite criar/editar."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Disponível apenas em modo associação ou academia.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        
        # Verificar se evento existe e pertence à associação
        try:
            cur.execute("""
                SELECT id, nome, tipo, categorias_modo, COALESCE(placar_num_areas, 1) AS placar_num_areas
                FROM eventos_competicoes 
                WHERE id = %s AND id_associacao = %s
            """, (evento_id, id_assoc))
        except Exception as ex:
            err = str(ex).lower()
            if "placar_num_areas" in err or "categorias_modo" in err or "1054" in err or "unknown column" in err:
                try:
                    cur.execute("""
                        SELECT id, nome, tipo, COALESCE(placar_num_areas, 1) AS placar_num_areas
                        FROM eventos_competicoes 
                        WHERE id = %s AND id_associacao = %s
                    """, (evento_id, id_assoc))
                except Exception:
                    cur.execute("""
                        SELECT id, nome, tipo FROM eventos_competicoes 
                        WHERE id = %s AND id_associacao = %s
                    """, (evento_id, id_assoc))
            else:
                raise
        evento = cur.fetchone()
        if not evento:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        if evento.get("tipo") != "competicao":
            flash(
                "O placar de judô é apenas para competições. Este registro é um evento geral (curso, seminário, etc.) — use a lista de eventos para inscrições.",
                "warning",
            )
            return redirect(url_for("eventos_competicoes.placar_judo_selecionar_evento"))
        if "categorias_modo" not in evento:
            evento["categorias_modo"] = "padrao"
        if "placar_num_areas" not in evento:
            evento["placar_num_areas"] = 1
        try:
            evento["placar_num_areas"] = max(1, min(int(evento.get("placar_num_areas") or 1), 50))
        except (TypeError, ValueError):
            evento["placar_num_areas"] = 1
        
        # Buscar lutas do evento
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
        
        return render_template(
            "eventos_competicoes/placar_judo_lista.html",
            evento=evento,
            lutas=lutas,
            back_url=_back_por_tipo_e_modo(evento_id, evento.get("tipo"), cur=cur),
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/placar-judo/nova-luta", methods=["GET", "POST"])
@login_required
def placar_judo_nova_luta(evento_id):
    """Cria uma nova luta."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
        
        try:
            cur.execute(
                """
                SELECT id, nome, tipo, categorias_modo, COALESCE(placar_num_areas, 1) AS placar_num_areas
                FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
                """,
                (evento_id, id_assoc),
            )
        except Exception as ex:
            err = str(ex).lower()
            if "placar_num_areas" in err or "categorias_modo" in err or "1054" in err or "unknown column" in err:
                try:
                    cur.execute(
                        """
                        SELECT id, nome, tipo, COALESCE(placar_num_areas, 1) AS placar_num_areas
                        FROM eventos_competicoes WHERE id = %s AND id_associacao = %s
                        """,
                        (evento_id, id_assoc),
                    )
                except Exception:
                    cur.execute(
                        "SELECT id, nome, tipo FROM eventos_competicoes WHERE id = %s AND id_associacao = %s",
                        (evento_id, id_assoc),
                    )
            else:
                raise
        evento = cur.fetchone()
        if not evento:
            flash("Evento não encontrado.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        if evento.get("tipo") != "competicao":
            flash("O placar só se aplica a competições.", "warning")
            return redirect(url_for("eventos_competicoes.placar_judo_selecionar_evento"))
        if "categorias_modo" not in evento:
            evento["categorias_modo"] = "padrao"
        if "placar_num_areas" not in evento:
            evento["placar_num_areas"] = 1
        try:
            evento["placar_num_areas"] = max(1, min(int(evento.get("placar_num_areas") or 1), 50))
        except (TypeError, ValueError):
            evento["placar_num_areas"] = 1
        
        if request.method == "POST":
            atleta_branco_nome = request.form.get("atleta_branco_nome", "").strip()
            atleta_branco_academia = request.form.get("atleta_branco_academia", "").strip() or None
            atleta_azul_nome = request.form.get("atleta_azul_nome", "").strip()
            atleta_azul_academia = request.form.get("atleta_azul_academia", "").strip() or None
            raw_cat = (request.form.get("categoria_id") or "").strip()
            categoria_id = None
            categoria_nome = None
            if raw_cat.startswith("aprox:"):
                try:
                    aprox_pk = int(raw_cat.split(":", 1)[1])
                except (ValueError, IndexError):
                    aprox_pk = None
                if aprox_pk and evento.get("categorias_modo") == "aproximacao":
                    cur.execute(
                        """
                        SELECT nome FROM eventos_competicoes_categorias_aprox
                        WHERE id = %s AND evento_id = %s
                        """,
                        (aprox_pk, evento_id),
                    )
                    row_cn = cur.fetchone()
                    if row_cn:
                        categoria_nome = row_cn.get("nome")
            elif raw_cat.isdigit():
                categoria_id = int(raw_cat)
            tempo_total = int(request.form.get("tempo_total", 300))
            area_num = request.form.get("area_num", type=int) or 1
            area_num = max(1, min(area_num, evento["placar_num_areas"]))
            
            if not atleta_branco_nome or not atleta_azul_nome:
                flash("Preencha os nomes dos dois atletas.", "danger")
            else:
                try:
                    cur.execute("""
                        INSERT INTO judo_lutas 
                        (evento_id, categoria_id, categoria_nome, area_num, atleta_branco_nome, atleta_branco_academia,
                         atleta_azul_nome, atleta_azul_academia, tempo_total_segundos, tempo_restante_segundos,
                         id_operador, status, elapsed_time, started_at, paused_at, golden_score_started_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'aguardando', 0, NULL, NULL, NULL)
                    """, (evento_id, categoria_id, categoria_nome, area_num, atleta_branco_nome, atleta_branco_academia,
                          atleta_azul_nome, atleta_azul_academia, tempo_total, tempo_total, current_user.id))
                except Exception as ins_ex:
                    err = str(ins_ex).lower()
                    if "categoria_nome" in err or "area_num" in err or "1054" in err or "unknown column" in err:
                        try:
                            cur.execute("""
                                INSERT INTO judo_lutas 
                                (evento_id, categoria_id, area_num, atleta_branco_nome, atleta_branco_academia,
                                 atleta_azul_nome, atleta_azul_academia, tempo_total_segundos, tempo_restante_segundos,
                                 id_operador, status, elapsed_time, started_at, paused_at, golden_score_started_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'aguardando', 0, NULL, NULL, NULL)
                            """, (evento_id, categoria_id, area_num, atleta_branco_nome, atleta_branco_academia,
                                  atleta_azul_nome, atleta_azul_academia, tempo_total, tempo_total, current_user.id))
                        except Exception as ins_ex2:
                            err2 = str(ins_ex2).lower()
                            if "area_num" in err2 or "1054" in err2 or "unknown column" in err2:
                                cur.execute("""
                                    INSERT INTO judo_lutas 
                                    (evento_id, categoria_id, atleta_branco_nome, atleta_branco_academia,
                                     atleta_azul_nome, atleta_azul_academia, tempo_total_segundos, tempo_restante_segundos,
                                     id_operador, status, elapsed_time, started_at, paused_at, golden_score_started_at)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'aguardando', 0, NULL, NULL, NULL)
                                """, (evento_id, categoria_id, atleta_branco_nome, atleta_branco_academia,
                                      atleta_azul_nome, atleta_azul_academia, tempo_total, tempo_total, current_user.id))
                            else:
                                raise
                    else:
                        raise
                conn.commit()
                flash("Luta criada com sucesso!", "success")
                return redirect(url_for("eventos_competicoes.placar_judo_lista", evento_id=evento_id))
        
        if evento.get("categorias_modo") == "aproximacao":
            try:
                cur.execute(
                    """
                    SELECT id, nome AS nome_categoria, nome AS categoria
                    FROM eventos_competicoes_categorias_aprox
                    WHERE evento_id = %s
                    ORDER BY ordem ASC, id ASC
                    """,
                    (evento_id,),
                )
                categorias = cur.fetchall()
                for c in categorias:
                    c["valor_option"] = f"aprox:{c['id']}"
            except Exception:
                categorias = []
        else:
            cur.execute("SELECT id, categoria, nome_categoria FROM categorias ORDER BY nome_categoria")
            categorias = cur.fetchall()
            for c in categorias:
                c["valor_option"] = str(c["id"])
        
        return render_template("eventos_competicoes/placar_judo_nova_luta.html",
            evento=evento, categorias=categorias,
            back_url=url_for("eventos_competicoes.placar_judo_lista", evento_id=evento_id))
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/placar-judo/config-areas", methods=["POST"])
@login_required
def placar_judo_config_areas(evento_id):
    """Define quantas áreas a competição terá no placar."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    n = request.form.get("placar_num_areas", type=int) or 1
    n = max(1, min(n, 50))
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        try:
            cur.execute(
                "UPDATE eventos_competicoes SET placar_num_areas = %s WHERE id = %s AND id_associacao = %s",
                (n, evento_id, id_assoc),
            )
        except Exception as ex:
            err = str(ex).lower()
            if "placar_num_areas" in err or "1054" in err or "unknown column" in err:
                flash(
                    "Execute a migração SQL: migrations/add_placar_areas.sql no banco de dados.",
                    "danger",
                )
                return redirect(url_for("eventos_competicoes.placar_judo_lista", evento_id=evento_id))
            raise
        conn.commit()
        if cur.rowcount:
            flash(f"Quantidade de áreas definida: {n}.", "success")
        else:
            flash("Evento não encontrado.", "danger")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("eventos_competicoes.placar_judo_lista", evento_id=evento_id))


@bp_eventos_competicoes.route("/placar-judo/<int:luta_id>/definir-area", methods=["POST"])
@login_required
def placar_judo_definir_area_luta(luta_id):
    """Altera a área de uma luta."""
    modo = session.get("modo_painel") or ""
    if modo not in ("associacao", "academia"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("painel.home"))
    area_num = request.form.get("area_num", type=int) or 1
    id_assoc = getattr(current_user, "id_associacao", None) or session.get("associacao_gerenciamento_id")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT jl.id, jl.evento_id FROM judo_lutas jl
            INNER JOIN eventos_competicoes ec ON ec.id = jl.evento_id
            WHERE jl.id = %s AND ec.id_associacao = %s
            """,
            (luta_id, id_assoc),
        )
        row = cur.fetchone()
        if not row:
            flash("Luta não encontrada.", "danger")
            return redirect(url_for("painel.home"))
        evento_id = row["evento_id"]
        nmax = _evento_placar_num_areas(cur, evento_id)
        area_num = max(1, min(area_num, nmax))
        try:
            cur.execute(
                "UPDATE judo_lutas SET area_num = %s WHERE id = %s",
                (area_num, luta_id),
            )
        except Exception as ex:
            err = str(ex).lower()
            if "area_num" in err or "1054" in err or "unknown column" in err:
                flash("Execute a migração: migrations/add_placar_areas.sql", "danger")
                return redirect(url_for("eventos_competicoes.placar_judo_lista", evento_id=evento_id))
            raise
        conn.commit()
        flash(f"Luta alocada na área {area_num}.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("eventos_competicoes.placar_judo_lista", evento_id=evento_id))


@bp_eventos_competicoes.route("/placar-judo/<int:luta_id>/controle")
@login_required
def placar_judo_controle(luta_id):
    """Interface de controle do placar (mesa/árbitro)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT jl.*, ec.nome as evento_nome, ec.id as evento_id,
                   c.nome_categoria, c.categoria
            FROM judo_lutas jl
            INNER JOIN eventos_competicoes ec ON ec.id = jl.evento_id
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.id = %s
        """, (luta_id,))
        luta = cur.fetchone()
        
        if not luta:
            flash("Luta não encontrada.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))

        an = _luta_area_num(luta)
        try:
            estado = obter_estado_luta_completo(luta_id)
            if estado:
                estado["evento_nome"] = luta.get("evento_nome")
                estado["categoria_nome"] = luta.get("nome_categoria") or luta.get("categoria_nome")
            _emit_placar_monitor_luta_na_area(luta["evento_id"], an, luta_id, estado, cur=cur)
        except Exception as e:
            current_app.logger.warning(f"Sync monitor área no controle: {e}")

        _k_voltar = {}
        if (request.args.get("embed") or "").strip().lower() in ("1", "true", "yes"):
            _k_voltar["embed"] = 1
        voltar_placar_url = url_for(
            "eventos_competicoes.placar_judo_voltar_placar_competicoes",
            luta_id=luta_id,
            **_k_voltar,
        )
        placar_controle_modelo = _fetch_placar_controle_modelo_evento(cur, luta["evento_id"])
        return render_template(
            "eventos_competicoes/placar_judo_controle.html",
            luta=luta,
            voltar_placar_url=voltar_placar_url,
            placar_controle_modelo=placar_controle_modelo,
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/placar-judo/<int:luta_id>/voltar-placar-competicoes")
@login_required
def placar_judo_voltar_placar_competicoes(luta_id):
    """Volta para /competicoes/placar/<evento> e coloca o monitor da área em espera (TV mostra a área + aguardando luta)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            cur.execute(
                """
                SELECT jl.id, jl.evento_id, jl.area_num
                FROM judo_lutas jl
                WHERE jl.id = %s
                """,
                (luta_id,),
            )
        except Exception as ex:
            err = str(ex).lower()
            if "area_num" in err or "1054" in err or "unknown column" in err:
                cur.execute(
                    "SELECT jl.id, jl.evento_id FROM judo_lutas jl WHERE jl.id = %s",
                    (luta_id,),
                )
            else:
                raise
        row = cur.fetchone()
        if not row:
            flash("Luta não encontrada.", "danger")
            return redirect(url_for("eventos_competicoes.lista"))
        evento_id = row["evento_id"]
        area_num = _luta_area_num(row)
        msg = f"Área {area_num} — aguardando luta"
        _emit_placar_monitor_standby(evento_id, area_num, msg)
        _k_back = {}
        if (request.args.get("embed") or "").strip().lower() in ("1", "true", "yes"):
            _k_back["embed"] = 1
        return redirect(url_for("competicoes.placar_lista", evento_id=evento_id, **_k_back))
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/placar-judo/<int:luta_id>/monitor")
def placar_judo_monitor(luta_id):
    """Interface de visualização pública (monitor/TV) - sem login necessário."""
    try:
        conn = get_db_connection()
    except DatabaseUnavailableError as e:
        current_app.logger.error("MySQL indisponível (monitor): %s", e)
        return render_template(
            "eventos_competicoes/placar_judo_monitor.html",
            luta=None,
            erro=str(e),
            erro_titulo="Banco de dados indisponível",
            monitor_por_evento=False,
            evento_id=0,
        )
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT jl.*, ec.nome as evento_nome, ec.id as evento_id,
                   c.nome_categoria, c.categoria
            FROM judo_lutas jl
            INNER JOIN eventos_competicoes ec ON ec.id = jl.evento_id
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.id = %s
        """, (luta_id,))
        luta = cur.fetchone()
        
        if not luta:
            return render_template("eventos_competicoes/placar_judo_monitor.html",
                luta=None, erro="Luta não encontrada")
        
        return render_template("eventos_competicoes/placar_judo_monitor.html",
            luta=luta)
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/<int:evento_id>/placar-judo/monitor-evento")
def placar_judo_monitor_evento(evento_id):
    """Compatibilidade: redireciona para o monitor da área 1."""
    return redirect(
        url_for("eventos_competicoes.placar_judo_monitor_area", evento_id=evento_id, area_num=1),
        code=302,
    )


@bp_eventos_competicoes.route("/<int:evento_id>/placar-judo/area/<int:area_num>/monitor")
def placar_judo_monitor_area(evento_id, area_num):
    """Monitor por área: espera entre lutas; mostra atletas ao abrir o controle da luta."""
    try:
        conn = get_db_connection()
    except DatabaseUnavailableError as e:
        current_app.logger.error("MySQL indisponível (monitor área): %s", e)
        return render_template(
            "eventos_competicoes/placar_judo_monitor.html",
            luta=None,
            erro=str(e),
            erro_titulo="Banco de dados indisponível",
            monitor_por_evento=False,
            monitor_por_area=False,
            evento_id=evento_id,
            area_num=area_num,
        )
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome FROM eventos_competicoes WHERE id = %s", (evento_id,))
        ev = cur.fetchone()
        if not ev:
            return render_template(
                "eventos_competicoes/placar_judo_monitor.html",
                luta=None,
                erro="Competição não encontrada",
                monitor_por_area=True,
                evento_id=evento_id,
                area_num=area_num,
                evento_nome="",
                placar_num_areas=1,
            )

        nmax = _evento_placar_num_areas(cur, evento_id)
        if area_num < 1 or area_num > nmax:
            return render_template(
                "eventos_competicoes/placar_judo_monitor.html",
                luta=None,
                erro=f"Área inválida. Esta competição tem {nmax} área(s) (1 a {nmax}).",
                erro_titulo="Área inválida",
                monitor_por_area=True,
                evento_id=evento_id,
                area_num=area_num,
                evento_nome=ev.get("nome") or "",
                placar_num_areas=nmax,
            )

        luta_id = _resolver_luta_monitor_area(cur, evento_id, area_num)
        if not luta_id:
            shell = _monitor_luta_shell_standby(ev.get("nome") or "", area_num)
            return render_template(
                "eventos_competicoes/placar_judo_monitor.html",
                luta=shell,
                erro=None,
                monitor_por_area=True,
                evento_id=evento_id,
                area_num=area_num,
                evento_nome=ev.get("nome") or "",
                placar_num_areas=nmax,
                monitor_standby_inicial=True,
            )

        cur.execute(
            """
            SELECT jl.*, ec.nome as evento_nome, ec.id as evento_id,
                   c.nome_categoria, c.categoria
            FROM judo_lutas jl
            INNER JOIN eventos_competicoes ec ON ec.id = jl.evento_id
            LEFT JOIN categorias c ON c.id = jl.categoria_id
            WHERE jl.id = %s
            """,
            (luta_id,),
        )
        luta = cur.fetchone()
        if not luta:
            shell = _monitor_luta_shell_standby(ev.get("nome") or "", area_num)
            return render_template(
                "eventos_competicoes/placar_judo_monitor.html",
                luta=shell,
                erro=None,
                monitor_por_area=True,
                evento_id=evento_id,
                area_num=area_num,
                evento_nome=ev.get("nome") or "",
                placar_num_areas=nmax,
                monitor_standby_inicial=True,
            )

        return render_template(
            "eventos_competicoes/placar_judo_monitor.html",
            luta=luta,
            monitor_por_area=True,
            evento_id=evento_id,
            area_num=area_num,
            evento_nome=ev.get("nome") or "",
            placar_num_areas=nmax,
            monitor_standby_inicial=False,
        )
    finally:
        cur.close()
        conn.close()


@bp_eventos_competicoes.route("/placar-judo/<int:luta_id>/api/estado", methods=["GET"])
def placar_judo_api_estado(luta_id):
    """API para buscar estado atual da luta (para polling do monitor).
    Retorna tempo calculado em tempo real pelo backend."""
    try:
        luta = obter_estado_luta_completo(luta_id)
        
        if not luta:
            return jsonify({"erro": "Luta não encontrada"}), 404
        
        return jsonify({"sucesso": True, "luta": luta})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


def _placar_permitido_externo(luta):
    """Permite acesso externo via session quando evento_id corresponde."""
    if current_user.is_authenticated:
        return True
    externo_evento = session.get("externo_evento_id")
    return externo_evento is not None and luta and luta.get("evento_id") == externo_evento


def _placar_id_operador():
    """Retorna id do operador (None se acesso externo)."""
    return current_user.id if current_user.is_authenticated else None


@bp_eventos_competicoes.route("/placar-judo/<int:luta_id>/api/resetar", methods=["POST"])
@csrf.exempt
def placar_judo_api_resetar(luta_id):
    """API para resetar a luta ao estado inicial (modo teste). Permite acesso externo."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        
        try:
            cur.execute("SELECT * FROM judo_lutas WHERE id = %s", (luta_id,))
            luta = cur.fetchone()
            if not luta:
                return jsonify({"erro": "Luta não encontrada"}), 404
            if not _placar_permitido_externo(luta):
                return jsonify({"erro": "Acesso não autorizado"}), 403
            
            tempo_total = luta.get("tempo_total_segundos", 300)
            id_op = _placar_id_operador()
            params = (tempo_total, id_op, luta_id)
            sql_reset_com_yoko = """
                UPDATE judo_lutas 
                SET status = 'aguardando',
                    tempo_restante_segundos = %s,
                    elapsed_time = 0,
                    started_at = NULL,
                    paused_at = NULL,
                    golden_score_ativado = 0,
                    golden_score_started_at = NULL,
                    tempo_golden_score_segundos = 0,
                    pontos_branco_ippon = 0,
                    pontos_branco_wazaari = 0,
                    pontos_branco_shido = 0,
                    pontos_branco_yoko = 0,
                    pontos_branco_hansokumake = 0,
                    pontos_azul_ippon = 0,
                    pontos_azul_wazaari = 0,
                    pontos_azul_shido = 0,
                    pontos_azul_yoko = 0,
                    pontos_azul_hansokumake = 0,
                    vencedor = NULL,
                    tipo_vitoria = NULL,
                    finalizada_em = NULL,
                    id_operador = %s,
                    updated_at = NOW()
                WHERE id = %s
            """
            sql_reset_sem_yoko = """
                UPDATE judo_lutas 
                SET status = 'aguardando',
                    tempo_restante_segundos = %s,
                    elapsed_time = 0,
                    started_at = NULL,
                    paused_at = NULL,
                    golden_score_ativado = 0,
                    golden_score_started_at = NULL,
                    tempo_golden_score_segundos = 0,
                    pontos_branco_ippon = 0,
                    pontos_branco_wazaari = 0,
                    pontos_branco_shido = 0,
                    pontos_branco_hansokumake = 0,
                    pontos_azul_ippon = 0,
                    pontos_azul_wazaari = 0,
                    pontos_azul_shido = 0,
                    pontos_azul_hansokumake = 0,
                    vencedor = NULL,
                    tipo_vitoria = NULL,
                    finalizada_em = NULL,
                    id_operador = %s,
                    updated_at = NOW()
                WHERE id = %s
            """
            try:
                cur.execute(sql_reset_com_yoko, params)
            except Exception as e:
                err_msg = str(e).lower() if e else ""
                if "1054" in err_msg or "unknown column" in err_msg or "pontos_branco_yoko" in err_msg or "pontos_azul_yoko" in err_msg:
                    cur.execute(sql_reset_sem_yoko, params)
                else:
                    raise
            
            # Registrar log
            try:
                cur.execute("""
                    INSERT INTO judo_placar_logs (luta_id, acao, detalhes, id_usuario)
                    VALUES (%s, %s, %s, %s)
                """, (luta_id, "resetar", json.dumps({"modo": "teste"}), id_op))
            except Exception as log_error:
                current_app.logger.warning(f"Erro ao registrar log (não crítico): {log_error}")
            
            conn.commit()
            
            # Remover da lista de ativas
            remover_luta_ativa(luta_id)
            
            # Buscar estado atualizado
            luta_atualizada = obter_estado_luta_completo(luta_id)
            
            # Emitir atualização via WebSocket
            socketio_instance = get_socketio()
            if socketio_instance and luta_atualizada:
                try:
                    # Converter campos datetime para strings (JSON serializable)
                    from datetime import datetime
                    luta_serializada = dict(luta_atualizada)
                    for key, value in luta_serializada.items():
                        if isinstance(value, datetime):
                            luta_serializada[key] = value.isoformat() if value else None
                    socketio_instance.emit("placar_atualizado", luta_serializada, room=f"luta_{luta_id}")
                except Exception as e:
                    current_app.logger.error(f"Erro ao emitir WebSocket: {e}")
            
            return jsonify({"sucesso": True, "luta": luta_atualizada, "mensagem": "Luta resetada com sucesso!"})
            
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@bp_eventos_competicoes.route("/placar-judo/<int:luta_id>/api/atualizar", methods=["POST"])
@csrf.exempt
def placar_judo_api_atualizar(luta_id):
    """API para atualizar pontuação/tempo da luta. Permite acesso externo via session."""
    try:
        data = request.get_json()
        acao = data.get("acao")
        
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        
        try:
            cur.execute("SELECT * FROM judo_lutas WHERE id = %s", (luta_id,))
            luta = cur.fetchone()
            if not luta:
                return jsonify({"erro": "Luta não encontrada"}), 404
            if not _placar_permitido_externo(luta):
                return jsonify({"erro": "Acesso não autorizado"}), 403
            
            id_op = _placar_id_operador()
            
            # Verificar se luta está finalizada (exceto desfazer: permite reverter última pontuação)
            if luta["status"] == "finalizada" and acao not in ("desfazer_ultima_acao", "desfazer_ponto"):
                return jsonify({"erro": "Luta já finalizada"}), 400
            
            atualizacoes = []
            valores = []
            ultimo_log_id = None  # usado ao desfazer: remove a ação desfeita do log
            
            # Processar ações
            from datetime import datetime
            
            if acao == "iniciar":
                # Verificar se luta não está finalizada
                if luta.get("status") == "finalizada":
                    return jsonify({"erro": "Não é possível iniciar uma luta finalizada"}), 400
                
                # Calcular tempo decorrido antes de pausar (se havia)
                elapsed_time = luta.get("elapsed_time", 0) or 0
                if luta.get("started_at") and luta.get("paused_at"):
                    # Se tinha started_at e paused_at, calcular tempo decorrido
                    try:
                        if isinstance(luta["started_at"], str):
                            started_at = datetime.strptime(luta["started_at"].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        else:
                            started_at = luta["started_at"]
                        if isinstance(luta["paused_at"], str):
                            paused_at = datetime.strptime(luta["paused_at"].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        else:
                            paused_at = luta["paused_at"]
                        elapsed_time += int((paused_at - started_at).total_seconds())
                    except:
                        elapsed_time = 0
                
                # Se está aguardando, resetar elapsed_time
                if luta.get("status") == "aguardando":
                    elapsed_time = 0
                    # Garantir que tempo_restante_segundos está correto
                    tempo_total = luta.get("tempo_total_segundos", 300)
                    atualizacoes.append("tempo_restante_segundos = %s")
                    valores.append(tempo_total)
                
                atualizacoes.append("status = 'em_andamento'")
                atualizacoes.append("id_operador = %s")
                atualizacoes.append("started_at = NOW()")
                atualizacoes.append("paused_at = NULL")
                atualizacoes.append("elapsed_time = %s")
                valores.append(id_op)
                valores.append(elapsed_time)
                
                # Registrar luta como ativa para broadcast periódico
                registrar_luta_ativa(luta_id)
                
            elif acao == "pausar":
                # Calcular tempo decorrido antes de pausar
                elapsed_time = luta.get("elapsed_time", 0) or 0
                golden_score_ativado = luta.get("golden_score_ativado", False)
                
                # Se está em golden_score, calcular tempo do golden score antes de pausar
                if golden_score_ativado and luta.get("golden_score_started_at"):
                    try:
                        if isinstance(luta["golden_score_started_at"], str):
                            golden_score_started_at = datetime.strptime(luta["golden_score_started_at"].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        else:
                            golden_score_started_at = luta["golden_score_started_at"]
                        agora = datetime.now()
                        tempo_golden_score_decorrido = int((agora - golden_score_started_at).total_seconds())
                        # Salvar tempo do golden score antes de pausar
                        atualizacoes.append("tempo_golden_score_segundos = %s")
                        valores.append(tempo_golden_score_decorrido)
                    except:
                        pass
                elif luta.get("started_at"):
                    # Calcular tempo normal se não está em golden_score
                    try:
                        if isinstance(luta["started_at"], str):
                            started_at = datetime.strptime(luta["started_at"].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        else:
                            started_at = luta["started_at"]
                        agora = datetime.now()
                        tempo_decorrido_agora = int((agora - started_at).total_seconds())
                        elapsed_time += tempo_decorrido_agora
                    except:
                        elapsed_time = luta.get("elapsed_time", 0) or 0
                
                tempo_total = luta.get("tempo_total_segundos", 300)
                tempo_restante = max(0, tempo_total - elapsed_time)
                
                atualizacoes.append("status = 'pausada'")
                atualizacoes.append("paused_at = NOW()")
                atualizacoes.append("elapsed_time = %s")
                atualizacoes.append("tempo_restante_segundos = %s")
                valores.append(elapsed_time)
                valores.append(tempo_restante)
                
                # Se está em golden_score, manter luta ativa para broadcast periódico continuar atualizando
                if golden_score_ativado:
                    registrar_luta_ativa(luta_id)
                
            elif acao == "retomar":
                elapsed_time = luta.get("elapsed_time", 0) or 0
                golden_score_ativado = luta.get("golden_score_ativado", False)
                
                # Se estava em golden_score antes de pausar, voltar para em_andamento (Golden Score controlado por golden_score_ativado)
                if golden_score_ativado:
                    atualizacoes.append("status = 'em_andamento'")
                    # Ajustar golden_score_started_at para continuar contagem crescente corretamente
                    # Calcular novo started_at baseado no tempo que já passou
                    tempo_gs_pausado = luta.get("tempo_golden_score_segundos", 0) or 0
                    # Usar DATE_SUB para ajustar o timestamp
                    atualizacoes.append("golden_score_started_at = DATE_SUB(NOW(), INTERVAL %s SECOND)")
                    valores.append(tempo_gs_pausado)
                else:
                    atualizacoes.append("status = 'em_andamento'")
                    atualizacoes.append("started_at = NOW()")
                
                atualizacoes.append("paused_at = NULL")
                atualizacoes.append("elapsed_time = %s")
                valores.append(elapsed_time)
                
                # Registrar luta como ativa para broadcast periódico
                registrar_luta_ativa(luta_id)
                
            elif acao == "golden_score":
                # Golden Score agora é automático, mas pode ser ativado manualmente também (status em_andamento)
                golden_score = data.get("ativado", False)
                if golden_score:
                    atualizacoes.append("status = 'em_andamento'")
                    atualizacoes.append("golden_score_ativado = 1")
                    atualizacoes.append("golden_score_started_at = NOW()")
                    atualizacoes.append("tempo_restante_segundos = 0")
                    # Registrar luta como ativa
                    registrar_luta_ativa(luta_id)
                else:
                    atualizacoes.append("golden_score_ativado = 0")
                    atualizacoes.append("golden_score_started_at = NULL")
                    atualizacoes.append("tempo_golden_score_segundos = 0")
            
            elif acao == "osaekomi_iniciar":
                lado = (data.get("lado") or "").strip().lower()
                if lado not in ("branco", "azul"):
                    return jsonify({"erro": "lado deve ser 'branco' ou 'azul'"}), 400
                if luta.get("status") not in ("em_andamento",):
                    return jsonify({"erro": "Osaekomi só pode ser iniciado com a luta em andamento"}), 400
                if luta.get("osaekomi_ativo"):
                    return jsonify({"erro": "Já existe osaekomi em andamento. Cancele antes de iniciar outro."}), 400
                atualizacoes.append("osaekomi_ativo = 1")
                atualizacoes.append("osaekomi_lado = %s")
                atualizacoes.append("osaekomi_started_at = NOW()")
                atualizacoes.append("osaekomi_wazaari_concedido = 0")
                atualizacoes.append("osaekomi_yuko_concedido = 0")
                valores.append(lado)
                registrar_luta_ativa(luta_id)
            
            elif acao == "osaekomi_cancelar":
                atualizacoes.append("osaekomi_ativo = 0")
                atualizacoes.append("osaekomi_lado = NULL")
                atualizacoes.append("osaekomi_started_at = NULL")
                atualizacoes.append("osaekomi_wazaari_concedido = 0")
                atualizacoes.append("osaekomi_yuko_concedido = 0")
            
            elif acao in ["ippon_branco", "wazaari_branco", "shido_branco", "yoko_branco"]:
                campo = acao.replace("_branco", "")
                cur.execute("SELECT * FROM judo_lutas WHERE id = %s FOR UPDATE", (luta_id,))
                pontos = cur.fetchone()
                em_golden_score = bool(luta.get("golden_score_ativado"))
                
                if campo == "ippon":
                    if pontos["pontos_branco_ippon"] >= 1:
                        return jsonify({"erro": "Ippon já marcado para este atleta"}), 400
                    atualizacoes.append("pontos_branco_ippon = 1")
                    atualizacoes.append("status = 'finalizada'")
                    atualizacoes.append("vencedor = 'branco'")
                    atualizacoes.append("tipo_vitoria = 'ippon'")
                    atualizacoes.append("finalizada_em = NOW()")
                    remover_luta_ativa(luta_id)
                elif campo == "wazaari":
                    novo_wazaari = pontos["pontos_branco_wazaari"] + 1
                    if novo_wazaari > 2:
                        return jsonify({"erro": "Máximo de 2 Waza-ari permitido"}), 400
                    atualizacoes.append("pontos_branco_wazaari = %s")
                    valores.append(novo_wazaari)
                    if novo_wazaari >= 2:
                        atualizacoes.append("pontos_branco_ippon = 1")
                        atualizacoes.append("pontos_branco_wazaari = 0")
                        atualizacoes.append("status = 'finalizada'")
                        atualizacoes.append("vencedor = 'branco'")
                        atualizacoes.append("tipo_vitoria = 'ippon'")
                        atualizacoes.append("finalizada_em = NOW()")
                        remover_luta_ativa(luta_id)
                    elif em_golden_score:
                        # No Golden Score, qualquer pontuação encerra a luta
                        atualizacoes.append("status = 'finalizada'")
                        atualizacoes.append("vencedor = 'branco'")
                        atualizacoes.append("tipo_vitoria = 'golden_score'")
                        atualizacoes.append("finalizada_em = NOW()")
                        remover_luta_ativa(luta_id)
                elif campo == "shido":
                    novo_shido = pontos["pontos_branco_shido"] + 1
                    if novo_shido > 3:
                        return jsonify({"erro": "Máximo de 3 Shido permitido"}), 400
                    atualizacoes.append("pontos_branco_shido = %s")
                    valores.append(novo_shido)
                    if novo_shido >= 3:
                        atualizacoes.append("pontos_branco_hansokumake = 1")
                        atualizacoes.append("pontos_azul_ippon = 1")
                        atualizacoes.append("status = 'finalizada'")
                        atualizacoes.append("vencedor = 'azul'")
                        atualizacoes.append("tipo_vitoria = 'hansoku_make'")
                        atualizacoes.append("finalizada_em = NOW()")
                        remover_luta_ativa(luta_id)
                elif campo == "yoko":
                    if "pontos_branco_yoko" not in pontos:
                        return jsonify({"erro": "Yoko não disponível. Execute a migração: migrations/add_yoko_judo.sql"}), 400
                    novo_yoko = (pontos.get("pontos_branco_yoko") or 0) + 1
                    atualizacoes.append("pontos_branco_yoko = %s")
                    valores.append(novo_yoko)
                    if em_golden_score:
                        atualizacoes.append("status = 'finalizada'")
                        atualizacoes.append("vencedor = 'branco'")
                        atualizacoes.append("tipo_vitoria = 'golden_score'")
                        atualizacoes.append("finalizada_em = NOW()")
                        remover_luta_ativa(luta_id)
            
            elif acao in ["ippon_azul", "wazaari_azul", "shido_azul", "yoko_azul"]:
                campo = acao.replace("_azul", "")
                cur.execute("SELECT * FROM judo_lutas WHERE id = %s FOR UPDATE", (luta_id,))
                pontos = cur.fetchone()
                em_golden_score = bool(luta.get("golden_score_ativado"))
                
                if campo == "ippon":
                    if pontos["pontos_azul_ippon"] >= 1:
                        return jsonify({"erro": "Ippon já marcado para este atleta"}), 400
                    atualizacoes.append("pontos_azul_ippon = 1")
                    atualizacoes.append("status = 'finalizada'")
                    atualizacoes.append("vencedor = 'azul'")
                    atualizacoes.append("tipo_vitoria = 'ippon'")
                    atualizacoes.append("finalizada_em = NOW()")
                    remover_luta_ativa(luta_id)
                elif campo == "wazaari":
                    novo_wazaari = pontos["pontos_azul_wazaari"] + 1
                    if novo_wazaari > 2:
                        return jsonify({"erro": "Máximo de 2 Waza-ari permitido"}), 400
                    atualizacoes.append("pontos_azul_wazaari = %s")
                    valores.append(novo_wazaari)
                    if novo_wazaari >= 2:
                        atualizacoes.append("pontos_azul_ippon = 1")
                        atualizacoes.append("pontos_azul_wazaari = 0")
                        atualizacoes.append("status = 'finalizada'")
                        atualizacoes.append("vencedor = 'azul'")
                        atualizacoes.append("tipo_vitoria = 'ippon'")
                        atualizacoes.append("finalizada_em = NOW()")
                        remover_luta_ativa(luta_id)
                    elif em_golden_score:
                        atualizacoes.append("status = 'finalizada'")
                        atualizacoes.append("vencedor = 'azul'")
                        atualizacoes.append("tipo_vitoria = 'golden_score'")
                        atualizacoes.append("finalizada_em = NOW()")
                        remover_luta_ativa(luta_id)
                elif campo == "shido":
                    novo_shido = pontos["pontos_azul_shido"] + 1
                    if novo_shido > 3:
                        return jsonify({"erro": "Máximo de 3 Shido permitido"}), 400
                    atualizacoes.append("pontos_azul_shido = %s")
                    valores.append(novo_shido)
                    if novo_shido >= 3:
                        atualizacoes.append("pontos_azul_hansokumake = 1")
                        atualizacoes.append("pontos_branco_ippon = 1")
                        atualizacoes.append("status = 'finalizada'")
                        atualizacoes.append("vencedor = 'branco'")
                        atualizacoes.append("tipo_vitoria = 'hansoku_make'")
                        atualizacoes.append("finalizada_em = NOW()")
                        remover_luta_ativa(luta_id)
                elif campo == "yoko":
                    if "pontos_azul_yoko" not in pontos:
                        return jsonify({"erro": "Yoko não disponível. Execute a migração: migrations/add_yoko_judo.sql"}), 400
                    novo_yoko = (pontos.get("pontos_azul_yoko") or 0) + 1
                    atualizacoes.append("pontos_azul_yoko = %s")
                    valores.append(novo_yoko)
                    if em_golden_score:
                        atualizacoes.append("status = 'finalizada'")
                        atualizacoes.append("vencedor = 'azul'")
                        atualizacoes.append("tipo_vitoria = 'golden_score'")
                        atualizacoes.append("finalizada_em = NOW()")
                        remover_luta_ativa(luta_id)
            
            elif acao == "finalizar":
                vencedor = data.get("vencedor")
                tipo_vitoria = data.get("tipo_vitoria", "golden_score")
                atualizacoes.append("status = 'finalizada'")
                atualizacoes.append("vencedor = %s")
                atualizacoes.append("tipo_vitoria = %s")
                atualizacoes.append("finalizada_em = NOW()")
                valores.extend([vencedor, tipo_vitoria])
                remover_luta_ativa(luta_id)
            
            elif acao in ("desfazer_ultima_acao", "desfazer_ponto"):
                # Desfazer última ação (busca no log) ou ponto específico; permite mesmo com luta finalizada
                if acao == "desfazer_ultima_acao":
                    cur.execute("""
                        SELECT id, acao, detalhes
                        FROM judo_placar_logs
                        WHERE luta_id = %s
                        ORDER BY id DESC
                        LIMIT 1
                    """, (luta_id,))
                    ultimo_log = cur.fetchone()
                    if not ultimo_log:
                        return jsonify({"erro": "Nenhuma ação anterior para desfazer"}), 400
                    ultima_acao = ultimo_log.get("acao")
                    acoes_pontos = [
                        "ippon_branco", "wazaari_branco", "shido_branco", "yoko_branco",
                        "ippon_azul", "wazaari_azul", "shido_azul", "yoko_azul"
                    ]
                    ultimo_log_id = ultimo_log.get("id")
                    if ultima_acao == "finalizar":
                        # Desfazer finalização manual (botão Finalizar) - reabrir luta
                        atualizacoes.append("status = 'em_andamento'")
                        atualizacoes.append("vencedor = NULL")
                        atualizacoes.append("tipo_vitoria = NULL")
                        atualizacoes.append("finalizada_em = NULL")
                        tipo_ponto, cor = None, None  # não remove ponto
                    elif ultima_acao == "osaekomi_iniciar" and luta.get("status") == "finalizada" and luta.get("vencedor") and luta.get("tipo_vitoria"):
                        # Luta finalizou por osaekomi (yuko/wazaari/ippon) mas o log é osaekomi_iniciar
                        # Reverter o ponto que encerrou a luta
                        cor = luta.get("vencedor")
                        tipo = luta.get("tipo_vitoria")
                        if tipo == "ippon":
                            tipo_ponto, cor = "ippon", cor
                        elif tipo == "golden_score":
                            # Golden Score: pode ter sido yoko ou wazaari
                            yoko_campo = "pontos_branco_yoko" if cor == "branco" else "pontos_azul_yoko"
                            wazaari_campo = "pontos_branco_wazaari" if cor == "branco" else "pontos_azul_wazaari"
                            yoko_val = luta.get(yoko_campo, 0) or 0
                            wazaari_val = luta.get(wazaari_campo, 0) or 0
                            if yoko_val > 0:
                                tipo_ponto, cor = "yoko", cor
                            elif wazaari_val > 0:
                                tipo_ponto, cor = "wazaari", cor
                            else:
                                return jsonify({"erro": "Não foi possível identificar o ponto do osaekomi para desfazer"}), 400
                        else:
                            return jsonify({"erro": "A última ação não é uma pontuação/penalidade desfaçável"}), 400
                        data["tipo_ponto"], data["cor"] = tipo_ponto, cor
                    elif ultima_acao in acoes_pontos:
                        partes = ultima_acao.split("_")
                        if len(partes) != 2:
                            return jsonify({"erro": "Formato de ação inválido no log"}), 400
                        tipo_ponto, cor = partes[0], partes[1]
                        data["tipo_ponto"] = tipo_ponto
                        data["cor"] = cor
                    else:
                        return jsonify({"erro": "A última ação não é uma pontuação/penalidade desfaçável"}), 400
                else:
                    tipo_ponto = data.get("tipo_ponto")
                    cor = data.get("cor")
                if tipo_ponto and cor and tipo_ponto in ["ippon", "wazaari", "shido", "yoko"] and cor in ["branco", "azul"]:
                    # Mapear campos válidos para evitar SQL injection
                    campos_validos = {
                        "branco_ippon": "pontos_branco_ippon",
                        "branco_wazaari": "pontos_branco_wazaari",
                        "branco_shido": "pontos_branco_shido",
                        "branco_yoko": "pontos_branco_yoko",
                        "azul_ippon": "pontos_azul_ippon",
                        "azul_wazaari": "pontos_azul_wazaari",
                        "azul_shido": "pontos_azul_shido",
                        "azul_yoko": "pontos_azul_yoko"
                    }
                    campo_key = f"{cor}_{tipo_ponto}"
                    campo = campos_validos.get(campo_key)
                    
                    if not campo:
                        return jsonify({"erro": "Campo inválido"}), 400
                    
                    # Buscar valor atual (yoko pode não existir se a migração não foi aplicada)
                    try:
                        cur.execute(f"SELECT {campo} FROM judo_lutas WHERE id = %s", (luta_id,))
                        resultado = cur.fetchone()
                        valor_atual = resultado.get(campo) if resultado else 0
                    except Exception as e:
                        err_msg = str(e).lower() if e else ""
                        if ("1054" in err_msg or "unknown column" in err_msg) and "yoko" in campo.lower():
                            return jsonify({"erro": "Yoko não disponível. Execute a migração: migrations/add_yoko_judo.sql"}), 400
                        raise
                    
                    if valor_atual and valor_atual > 0:
                        novo_valor = valor_atual - 1
                        atualizacoes.append(f"{campo} = %s")
                        valores.append(novo_valor)
                        
                        # Se estava finalizada por Ippon e removeu o Ippon, reabrir luta
                        if tipo_ponto == "ippon" and luta["status"] == "finalizada" and luta.get("vencedor") == cor:
                            atualizacoes.append("status = 'em_andamento'")
                            atualizacoes.append("vencedor = NULL")
                            atualizacoes.append("tipo_vitoria = NULL")
                            atualizacoes.append("finalizada_em = NULL")
                        
                        # Se estava finalizada por Waza-ari (2 waza-ari = ippon) e removeu waza-ari
                        if tipo_ponto == "wazaari":
                            # Verificar se tinha ippon por 2 waza-ari
                            campo_wazaari_key = f"{cor}_wazaari"
                            campo_wazaari = campos_validos.get(campo_wazaari_key)
                            if campo_wazaari:
                                cur.execute(f"SELECT {campo_wazaari} FROM judo_lutas WHERE id = %s", (luta_id,))
                                wazaari_result = cur.fetchone()
                                wazaari_atual = wazaari_result.get(campo_wazaari) if wazaari_result else 0
                                
                                # Se tinha 2 waza-ari e agora terá 1, remover ippon automático
                                if wazaari_atual == 2 and novo_valor == 1:
                                    campo_ippon_key = f"{cor}_ippon"
                                    campo_ippon = campos_validos.get(campo_ippon_key)
                                    if campo_ippon:
                                        atualizacoes.append(f"{campo_ippon} = %s")
                                        valores.append(0)
                                    if luta["status"] == "finalizada" and luta.get("vencedor") == cor:
                                        atualizacoes.append("status = 'em_andamento'")
                                        atualizacoes.append("vencedor = NULL")
                                        atualizacoes.append("tipo_vitoria = NULL")
                                        atualizacoes.append("finalizada_em = NULL")
                                # Golden Score: 1 waza-ari encerrou; ao remover, reabrir
                                elif wazaari_atual == 1 and novo_valor == 0 and luta["status"] == "finalizada" and luta.get("vencedor") == cor and luta.get("tipo_vitoria") == "golden_score":
                                    atualizacoes.append("status = 'em_andamento'")
                                    atualizacoes.append("vencedor = NULL")
                                    atualizacoes.append("tipo_vitoria = NULL")
                                    atualizacoes.append("finalizada_em = NULL")
                                    atualizacoes.append("osaekomi_wazaari_concedido = 0")
                        
                        # Se tinha hansoku-make e removeu shido suficiente
                        if tipo_ponto == "shido":
                            campo_shido_key = f"{cor}_shido"
                            campo_shido = campos_validos.get(campo_shido_key)
                            if campo_shido:
                                cur.execute(f"SELECT {campo_shido} FROM judo_lutas WHERE id = %s", (luta_id,))
                                shido_result = cur.fetchone()
                                shido_atual = shido_result.get(campo_shido) if shido_result else 0
                            
                            if shido_atual == 3 and novo_valor == 2:
                                # Remover hansoku-make se tinha
                                if cor == "branco" and luta.get("pontos_branco_hansokumake"):
                                    atualizacoes.append("pontos_branco_hansokumake = 0")
                                    atualizacoes.append("pontos_azul_ippon = 0")
                                    if luta["status"] == "finalizada":
                                        atualizacoes.append("status = 'em_andamento'")
                                        atualizacoes.append("vencedor = NULL")
                                        atualizacoes.append("tipo_vitoria = NULL")
                                        atualizacoes.append("finalizada_em = NULL")
                                elif cor == "azul" and luta.get("pontos_azul_hansokumake"):
                                    atualizacoes.append("pontos_azul_hansokumake = 0")
                                    atualizacoes.append("pontos_branco_ippon = 0")
                                    if luta["status"] == "finalizada":
                                        atualizacoes.append("status = 'em_andamento'")
                                        atualizacoes.append("vencedor = NULL")
                                        atualizacoes.append("tipo_vitoria = NULL")
                                        atualizacoes.append("finalizada_em = NULL")
                        
                        # Se estava finalizada por Yoko (ex.: no Golden Score) e removeu o Yoko, reabrir
                        if tipo_ponto == "yoko" and luta["status"] == "finalizada" and luta.get("vencedor") == cor:
                            atualizacoes.append("status = 'em_andamento'")
                            atualizacoes.append("vencedor = NULL")
                            atualizacoes.append("tipo_vitoria = NULL")
                            atualizacoes.append("finalizada_em = NULL")
                            if luta.get("tipo_vitoria") == "golden_score":
                                atualizacoes.append("osaekomi_yuko_concedido = 0")
                    else:
                        return jsonify({"erro": f"Não há {tipo_ponto} para remover do atleta {cor}"}), 400
                else:
                    return jsonify({"erro": "Tipo de ponto ou cor inválidos"}), 400
            
            if atualizacoes:
                valores.append(luta_id)
                sql = f"UPDATE judo_lutas SET {', '.join(atualizacoes)}, updated_at = NOW() WHERE id = %s"
                try:
                    cur.execute(sql, valores)
                    
                    # Registrar log (ao desfazer, remove a ação desfeita do log em vez de inserir nova)
                    if acao in ("desfazer_ultima_acao", "desfazer_ponto") and ultimo_log_id:
                        cur.execute("DELETE FROM judo_placar_logs WHERE id = %s", (ultimo_log_id,))
                    else:
                        try:
                            cur.execute("""
                                INSERT INTO judo_placar_logs (luta_id, acao, detalhes, id_usuario)
                                VALUES (%s, %s, %s, %s)
                            """, (luta_id, acao, json.dumps(data), id_op))
                        except Exception as log_error:
                            current_app.logger.warning(f"Erro ao registrar log (não crítico): {log_error}")
                    
                    conn.commit()
                    
                    # Chave: vencedor via luta_origem_*; repescagem/3º via judo_chave_feed; melhor-de-3 próxima luta
                    try:
                        from utils.judo_chaves_inteligentes import propagar_judo_chave_feeds, processar_bo3_apos_finalizacao

                        cur.execute(
                            "SELECT vencedor, atleta_branco_nome, atleta_branco_academia, atleta_azul_nome, atleta_azul_academia FROM judo_lutas WHERE id = %s",
                            (luta_id,),
                        )
                        row = cur.fetchone()
                        next_b = next_a = None
                        if row and row.get("vencedor") and row["vencedor"] in ("branco", "azul"):
                            w_nome = row["atleta_branco_nome"] if row["vencedor"] == "branco" else row["atleta_azul_nome"]
                            w_acad = (row["atleta_branco_academia"] if row["vencedor"] == "branco" else row["atleta_azul_academia"]) or "-"
                            cur.execute("SELECT id FROM judo_lutas WHERE luta_origem_branco_id = %s", (luta_id,))
                            next_b = cur.fetchone()
                            if next_b:
                                cur.execute(
                                    "UPDATE judo_lutas SET atleta_branco_nome = %s, atleta_branco_academia = %s WHERE id = %s",
                                    (w_nome, w_acad, next_b["id"]),
                                )
                            cur.execute("SELECT id FROM judo_lutas WHERE luta_origem_azul_id = %s", (luta_id,))
                            next_a = cur.fetchone()
                            if next_a:
                                cur.execute(
                                    "UPDATE judo_lutas SET atleta_azul_nome = %s, atleta_azul_academia = %s WHERE id = %s",
                                    (w_nome, w_acad, next_a["id"]),
                                )
                        changed_feeds = propagar_judo_chave_feeds(cur, luta_id)
                        if next_b or next_a or changed_feeds:
                            conn.commit()
                        processar_bo3_apos_finalizacao(cur, conn, luta_id)
                    except Exception as prop_err:
                        if "1054" not in str(prop_err) and "Unknown column" not in str(prop_err).lower():
                            current_app.logger.warning(f"Propagar chave / BO3: {prop_err}")
                    
                    # Buscar estado completo com tempo calculado
                    luta_atualizada = obter_estado_luta_completo(luta_id)
                    
                    # Se desfazer reverteu luta finalizada → em_andamento/golden_score, reativar broadcast
                    if acao in ("desfazer_ultima_acao", "desfazer_ponto") and luta.get("status") == "finalizada" and luta_atualizada and luta_atualizada.get("status") == "em_andamento":
                        registrar_luta_ativa(luta_id)
                    
                    # Ao acabar o tempo: se alguém está ganhando -> finaliza com vencedor; senão -> Golden Score
                    if luta_atualizada:
                        luta_atualizada = aplicar_fim_de_tempo(luta_id) or luta_atualizada
                    
                    # Emitir atualização via WebSocket
                    socketio_instance = get_socketio()
                    if socketio_instance and luta_atualizada:
                        try:
                            # Converter campos datetime para strings (JSON serializable)
                            from datetime import datetime
                            luta_serializada = dict(luta_atualizada)
                            for key, value in luta_serializada.items():
                                if isinstance(value, datetime):
                                    luta_serializada[key] = value.isoformat() if value else None
                            socketio_instance.emit("placar_atualizado", luta_serializada, room=f"luta_{luta_id}")
                        except Exception as e:
                            current_app.logger.error(f"Erro ao emitir WebSocket: {e}")

                    resp = {"sucesso": True, "luta": luta_atualizada}
                    proxima = None
                    if luta_atualizada and luta_atualizada.get("status") == "finalizada":
                        proxima = _sincronizar_monitor_area_apos_finalizacao(cur, luta_id, luta_atualizada)
                    if acao == "finalizar" and proxima:
                        resp["proxima_luta_id"] = proxima
                    return jsonify(resp)
                except Exception as db_error:
                    conn.rollback()
                    err_str = str(db_error)
                    if acao in ("osaekomi_iniciar", "osaekomi_cancelar") and ("1054" in err_str or "Unknown column" in err_str) and "osaekomi" in err_str.lower():
                        return jsonify({
                            "erro": "Colunas de Osaekomi não existem no banco. Execute a migração: migrations/add_osaekomi_judo.sql (no MySQL: USE seu_banco; depois rode o ALTER TABLE do arquivo)."
                        }), 400
                    current_app.logger.error("Erro ao atualizar luta: %s", db_error, exc_info=True)
                    return jsonify({"erro": "Erro interno ao salvar dados. Tente novamente."}), 500
            else:
                current_app.logger.warning(f"Ação sem atualizações: {acao}")
                return jsonify({"erro": f"Ação '{acao}' não gerou atualizações"}), 400
                
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# WebSocket Handlers - serão registrados no app.py


# =====================================================
# 🔹 Link de inscrição gerado pela ACADEMIA (por evento)
# =====================================================
# A academia aderida gera um link público. Atletas de fora (de escolas, projetos)
# preenchem os campos do evento + o local de treino, e entram como avulsos.
# O professor é preenchido automaticamente a partir do local escolhido.

def _campos_evento_para_form(cur, id_formulario):
    """Campos do formulário do evento, prontos para a tela pública."""
    cur.execute(
        "SELECT campo_chave, label, obrigatorio, ordem FROM formularios_campos "
        "WHERE formulario_id = %s ORDER BY ordem", (id_formulario or 0,))
    return _merge_campos_form_faltantes_padrao_avulso(cur.fetchall())


def _locais_do_evento(cur, evento_id, academia_id):
    """
    Locais de treino da academia, marcando quais estão vinculados a este evento.
    Retorna [(id, nome, professor_nome, vinculado)].
    """
    cur.execute(
        """SELECT lt.id, lt.nome, p.nome AS professor_nome,
                  EXISTS(SELECT 1 FROM evento_locais_treino elt
                         WHERE elt.evento_id = %s AND elt.local_treino_id = lt.id) AS vinculado
           FROM locais_treino lt
           LEFT JOIN professores p ON p.id = lt.professor_id
           WHERE lt.academia_id = %s AND lt.ativo = 1
           ORDER BY lt.nome""",
        (evento_id, academia_id))
    return cur.fetchall()


@bp_eventos_competicoes.route("/<int:evento_id>/locais-inscricao", methods=["POST"])
@login_required
def salvar_locais_inscricao(evento_id):
    """Academia define quais locais de treino valem para a inscrição deste evento."""
    academia_id = request.form.get("academia_id", type=int)
    if not academia_id:
        flash("Academia não informada.", "danger")
        return redirect(url_for("eventos_competicoes.lista_eventos"))

    escolhidos = {int(i) for i in request.form.getlist("local_id") if i.isdigit()}
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Só locais da própria academia podem ser vinculados.
        cur.execute("SELECT id FROM locais_treino WHERE academia_id = %s", (academia_id,))
        validos = {r["id"] for r in cur.fetchall()}
        escolhidos &= validos

        cur.execute(
            "DELETE FROM evento_locais_treino WHERE evento_id = %s AND academia_id = %s",
            (evento_id, academia_id))
        for local_id in escolhidos:
            cur.execute(
                """INSERT INTO evento_locais_treino (evento_id, academia_id, local_treino_id)
                   VALUES (%s, %s, %s)""", (evento_id, academia_id, local_id))
        conn.commit()
        flash(f"{len(escolhidos)} local(is) vinculado(s) à inscrição deste evento.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))


@bp_eventos_competicoes.route("/<int:evento_id>/gerar-link-inscricao", methods=["POST"])
@login_required
def gerar_link_inscricao(evento_id):
    """Cria (ou reaproveita) o token do link público desta academia neste evento."""
    academia_id = request.form.get("academia_id", type=int)
    if not academia_id:
        flash("Academia não informada.", "danger")
        return redirect(url_for("eventos_competicoes.lista_eventos"))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, token_inscricao, aderiu FROM eventos_competicoes_adesao "
            "WHERE evento_id = %s AND academia_id = %s", (evento_id, academia_id))
        adesao = cur.fetchone()
        if not adesao or not adesao.get("aderiu"):
            flash("Adira ao evento antes de gerar o link de inscrição.", "warning")
        elif adesao.get("token_inscricao"):
            flash("Link de inscrição já estava gerado.", "info")
        else:
            token = "ac" + secrets.token_urlsafe(20)
            cur.execute("UPDATE eventos_competicoes_adesao SET token_inscricao = %s WHERE id = %s",
                        (token, adesao["id"]))
            conn.commit()
            flash("Link de inscrição gerado.", "success")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for("eventos_competicoes.inscritos", evento_id=evento_id, academia_id=academia_id))


def _adesao_por_token_inscricao(cur, token):
    """(evento, academia_id) do link público, ou (None, None)."""
    cur.execute(
        """SELECT ea.academia_id, ec.id AS evento_id, ec.nome AS evento_nome,
                  ec.data_fim, ec.id_formulario, ec.categorias_modo, ec.tipo,
                  ac.nome AS academia_nome
           FROM eventos_competicoes_adesao ea
           JOIN eventos_competicoes ec ON ec.id = ea.evento_id
           JOIN academias ac ON ac.id = ea.academia_id
           WHERE ea.token_inscricao = %s AND ea.aderiu = 1""", (token,))
    linha = cur.fetchone()
    if not linha:
        return None
    return linha


@bp_eventos_competicoes.route("/inscricao/<token>", methods=["GET"])
@csrf.exempt
def inscricao_academia(token):
    """Formulário público de inscrição da academia (sem login)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        dados = _adesao_por_token_inscricao(cur, token)
        if not dados:
            return render_template("eventos_competicoes/inscricao_academia.html",
                                   invalido=True), 404
        if _evento_encerrado(dados):
            return render_template("eventos_competicoes/inscricao_academia.html",
                                   encerrado=True, evento=dados)

        campos = _campos_evento_para_form(cur, dados["id_formulario"])
        cur.execute("SELECT id, faixa, graduacao FROM graduacao ORDER BY id")
        graduacoes = cur.fetchall()
        # Locais vinculados a ESTE evento. Se a academia não restringiu nenhum,
        # o formulário oferece todos os locais ativos dela — cadastrar já basta
        # para aparecer; a vinculação serve só para limitar a um subconjunto.
        cur.execute(
            """SELECT lt.id, lt.nome, p.nome AS professor_nome
               FROM evento_locais_treino elt
               JOIN locais_treino lt ON lt.id = elt.local_treino_id
               LEFT JOIN professores p ON p.id = lt.professor_id
               WHERE elt.evento_id = %s AND elt.academia_id = %s AND lt.ativo = 1
               ORDER BY lt.nome""",
            (dados["evento_id"], dados["academia_id"]))
        locais = cur.fetchall()
        if not locais:
            cur.execute(
                """SELECT lt.id, lt.nome, p.nome AS professor_nome
                   FROM locais_treino lt LEFT JOIN professores p ON p.id = lt.professor_id
                   WHERE lt.academia_id = %s AND lt.ativo = 1 ORDER BY lt.nome""",
                (dados["academia_id"],))
            locais = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return render_template("eventos_competicoes/inscricao_academia.html",
                           token=token, evento=dados, campos=campos,
                           graduacoes=graduacoes, locais=locais)


@bp_eventos_competicoes.route("/inscricao/<token>", methods=["POST"])
@csrf.exempt
def inscricao_academia_enviar(token):
    """Grava a inscrição enviada pelo formulário público da academia."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        dados = _adesao_por_token_inscricao(cur, token)
        if not dados or _evento_encerrado(dados):
            flash("Este link não está mais disponível.", "danger")
            return redirect(url_for("eventos_competicoes.inscricao_academia", token=token))

        campos = _campos_evento_para_form(cur, dados["id_formulario"])
        valores = {}
        for c in campos:
            chave = c["campo_chave"]
            if chave in ("id_academia", "categoria"):
                continue
            v = (request.form.get(f"campo_{chave}") or "").strip()
            if chave in ("data_nascimento", "ultimo_exame_faixa", "rg_data_emissao") and v and "/" in v:
                p = v[:10].split("/")
                if len(p) == 3:
                    v = f"{p[2]}-{p[1]}-{p[0]}"
            valores[chave] = v
        valores["id_academia"] = str(dados["academia_id"])

        # Local de treino: grava o nome e puxa o professor do local escolhido.
        local_id = request.form.get("local_treino_id", type=int)
        if local_id:
            cur.execute(
                """SELECT lt.nome, p.nome AS professor_nome
                   FROM locais_treino lt LEFT JOIN professores p ON p.id = lt.professor_id
                   WHERE lt.id = %s AND lt.academia_id = %s""",
                (local_id, dados["academia_id"]))
            local = cur.fetchone()
            if local:
                valores["local_treino"] = local["nome"]
                if local.get("professor_nome"):
                    valores["professor"] = local["professor_nome"]

        # Sem local informado, o local de treino passa a ser a própria academia
        # que gerou o formulário — todo atleta fica com uma origem registrada.
        if not (valores.get("local_treino") or "").strip():
            valores["local_treino"] = dados["academia_nome"]

        # Valida obrigatórios do evento.
        obrigatorios = [(c["campo_chave"], c.get("label")) for c in campos if c.get("obrigatorio")]
        faltam = _faltando_na_inscricao(valores, obrigatorios)
        if not (valores.get("nome") or "").strip():
            faltam.insert(0, "Nome")
        if faltam:
            flash("Preencha os campos obrigatórios: " + ", ".join(dict.fromkeys(faltam)), "danger")
            return redirect(url_for("eventos_competicoes.inscricao_academia", token=token))

        cur.execute(
            """INSERT INTO eventos_competicoes_inscricoes
               (evento_id, academia_id, aluno_id, dados_form, inclusao_avulsa, status)
               VALUES (%s, %s, NULL, %s, 1, 'confirmada')""",
            (dados["evento_id"], dados["academia_id"],
             json.dumps(valores, ensure_ascii=False)))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return render_template("eventos_competicoes/inscricao_academia.html",
                           sucesso=True, evento=dados, token=token)
